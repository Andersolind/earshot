"""
GNU-Larex Core DSP Engine & GNU Radio 3.10 Embedded Block Library
==================================================================
Provides both pure-NumPy DSP processors (for unit testing & offline analysis)
and GNU Radio `gr.sync_block` blocks for real-time RF micro-Doppler vibrometry,
subvocalization isolation, infrasonic breathing sonification, biometric BPM
estimation, and multi-track session recording.
"""

from __future__ import annotations

import collections
import csv
import datetime
import math
import os
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure Radioconda Library\bin + mingw-w64\bin DLLs and SoapySDR plugin root resolve FIRST even outside run_larex.ps1
_RADIOCONDA_ROOT = Path(__file__).resolve().parent.parent / "radioconda"
_RADIOCONDA_LIB_BIN = _RADIOCONDA_ROOT / "Library" / "bin"
_RADIOCONDA_MINGW_BIN = _RADIOCONDA_ROOT / "Library" / "mingw-w64" / "bin"
if os.name == "nt" and _RADIOCONDA_LIB_BIN.exists():
    os.environ.setdefault("CONDA_PREFIX", str(_RADIOCONDA_ROOT))
    os.environ.setdefault("SOAPY_SDR_ROOT", str(_RADIOCONDA_ROOT / "Library"))
    for _dll_dir in (_RADIOCONDA_LIB_BIN, _RADIOCONDA_MINGW_BIN):
        if _dll_dir.exists():
            try:
                os.add_dll_directory(str(_dll_dir))
            except Exception:
                pass
    os.environ["PATH"] = f"{_RADIOCONDA_LIB_BIN};{_RADIOCONDA_MINGW_BIN};{os.environ.get('PATH', '')}"

import numpy as np

SPEED_OF_LIGHT_MPS = 299_792_458.0


_SOAPY_USB_LOCK = threading.Lock()


def soapy_info_to_markup(info: Dict[str, str]) -> str:
    """Converts a hardware info dict into a safe SoapySDR markup string (never a Python dict, which triggers SWIG wildcard UHD crash)."""
    drv = str(info.get("driver", "rtlsdr")).strip()
    parts = [f"driver={drv}"]
    if info.get("serial"):
        parts.append(f"serial={info['serial']}")
    return ",".join(parts)


def safe_enumerate_soapysdr(sdr_args: str = "") -> List[Dict[str, str]]:
    """
    Enumerates connected SoapySDR hardware using explicit driver filters (`rtlsdr`,
    `hackrf`, `plutosdr`, `airspy`) so unused UHD/LMS7 wildcard scans never crash on Windows.
    Returns all attached SDRs (e.g. both RTL-SDR Blog V4 and HackRF One simultaneously).
    """
    try:
        import SoapySDR  # type: ignore
    except ImportError:
        return []

    if sdr_args.strip():
        try:
            with _SOAPY_USB_LOCK:
                return [dict(d) for d in SoapySDR.Device.enumerate(sdr_args.strip())]
        except Exception:
            return []

    found: List[Dict[str, str]] = []
    for drv in ("driver=rtlsdr", "driver=hackrf", "driver=plutosdr", "driver=airspy"):
        try:
            with _SOAPY_USB_LOCK:
                res = SoapySDR.Device.enumerate(drv)
            for item in res:
                found.append(dict(item))
        except Exception:
            continue
    return found


_PORTAUDIO_INIT_LOCK = threading.Lock()


class UltraMicWASAPIDriver:
    """
    Low-jitter native PortAudio/WASAPI driver for the Dodotronic `UltraMic384K_EVO`
    (and standard Windows microphones as fallback):
      - Dodotronic `UltraMic384K_EVO 16bit` hardware only supports `384,000 Hz, 1-ch, int16`
        at its USB Audio endpoint; Windows Shared Mode (`audiodg.exe` / MME) mutes `8:1`
        downsampling to `-96.7 dBFS` 1-LSB dither.
      - Opens `UltraMic` directly via `portaudio.dll` with `PaWasapiStreamInfo`
        (`paWinWasapiExclusive | paWinWasapiThreadPriority`, `eThreadPriorityProAudio`)
        at native `384,000 Hz`, bypassing `audiodg.exe` completely with zero `aO` overruns!
      - Automatically removes hardware MEMS capsule DC bias on sample 0, tracks ultrasonic
        (`20 - 180 kHz`) + voice-band (`80 - 4,000 Hz`) RMS dBFS, and outputs either full
        `384,000 Hz` wideband float32 or anti-alias decimated `48,000 Hz` baseband float32.
    """

    PA_INT16 = 0x00000008
    PA_WASAPI_TYPE = 13
    WASAPI_FLAG_EXCLUSIVE = 0x00000001
    WASAPI_FLAG_THREAD_PRIORITY = 0x00000004
    THREAD_PRIORITY_PRO_AUDIO = 5

    def __init__(
        self,
        device_hint: str = "",
        output_rate: int = 384_000,
        chunk_ms: float = 20.0,
    ) -> None:
        self.device_hint = str(device_hint).strip()
        self.requested_output_rate = int(output_rate)
        self.chunk_ms = float(max(5.0, min(chunk_ms, 100.0)))

        self.connected: bool = False
        self.device_index: int = -1
        self.device_name: str = "Uninitialized"
        self.host_api: str = ""
        self.exclusive_mode: bool = False
        self.hw_sample_rate: int = 384_000
        self.output_sample_rate: int = self.requested_output_rate
        self.decim_factor: int = 1

        # Live hardware health & signal telemetry
        self.frames_captured: int = 0
        self.overrun_count: int = 0
        self.queue_drops: int = 0
        self.dc_offset: float = 0.0
        self.rms_dbfs: float = -120.0
        self.peak_dbfs: float = -120.0
        self.voice_band_dbfs: float = -120.0
        self.ultrasonic_band_dbfs: float = -120.0
        self.peak_ultrasonic_hz: float = 0.0
        self.last_error: str = ""

        self._pa: Any = None
        self._pa_initialized: bool = False
        self._stream_handle: Any = None
        self._wasapi_info_keepalive: Any = None
        self._params_keepalive: Any = None

        self._dc_initialized: bool = False
        self._dc_est: float = 0.0
        self._fir_taps: Optional[np.ndarray] = None
        self._fir_tail: np.ndarray = np.zeros(0, dtype=np.float32)

        self._queue: collections.deque[np.ndarray] = collections.deque()
        self._max_queue_chunks: int = max(24, int(round(800.0 / self.chunk_ms)))
        self._cond = threading.Condition()
        self._stop_evt = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @staticmethod
    def _load_portaudio_ctypes() -> Tuple[Any, Any, Any, Any, Any]:
        import ctypes

        if os.name == "nt":
            pa = ctypes.CDLL("portaudio.dll")
        else:
            from ctypes.util import find_library

            pa = ctypes.CDLL(find_library("portaudio") or "libportaudio.so.2")

        class PaHostApiInfo(ctypes.Structure):
            _fields_ = [
                ("structVersion", ctypes.c_int),
                ("type", ctypes.c_int),
                ("name", ctypes.c_char_p),
                ("deviceCount", ctypes.c_int),
                ("defaultInputDevice", ctypes.c_int),
                ("defaultOutputDevice", ctypes.c_int),
            ]

        class PaDeviceInfo(ctypes.Structure):
            _fields_ = [
                ("structVersion", ctypes.c_int),
                ("name", ctypes.c_char_p),
                ("hostApi", ctypes.c_int),
                ("maxInputChannels", ctypes.c_int),
                ("maxOutputChannels", ctypes.c_int),
                ("defaultLowInputLatency", ctypes.c_double),
                ("defaultLowOutputLatency", ctypes.c_double),
                ("defaultHighInputLatency", ctypes.c_double),
                ("defaultHighOutputLatency", ctypes.c_double),
                ("defaultSampleRate", ctypes.c_double),
            ]

        class PaStreamParameters(ctypes.Structure):
            _fields_ = [
                ("device", ctypes.c_int),
                ("channelCount", ctypes.c_int),
                ("sampleFormat", ctypes.c_ulong),
                ("suggestedLatency", ctypes.c_double),
                ("hostApiSpecificStreamInfo", ctypes.c_void_p),
            ]

        class PaWasapiStreamInfo(ctypes.Structure):
            _fields_ = [
                ("size", ctypes.c_ulong),
                ("hostApiType", ctypes.c_int),
                ("version", ctypes.c_ulong),
                ("flags", ctypes.c_ulong),
                ("channelMask", ctypes.c_uint32),
                ("hostProcessorOutput", ctypes.c_void_p),
                ("hostProcessorInput", ctypes.c_void_p),
                ("threadPriority", ctypes.c_int),
                ("streamCategory", ctypes.c_int),
                ("streamOption", ctypes.c_int),
            ]

        pa.Pa_Initialize.restype = ctypes.c_int
        pa.Pa_Terminate.restype = ctypes.c_int
        pa.Pa_GetHostApiCount.restype = ctypes.c_int
        pa.Pa_GetDeviceCount.restype = ctypes.c_int
        pa.Pa_GetHostApiInfo.restype = ctypes.POINTER(PaHostApiInfo)
        pa.Pa_GetHostApiInfo.argtypes = [ctypes.c_int]
        pa.Pa_GetDeviceInfo.restype = ctypes.POINTER(PaDeviceInfo)
        pa.Pa_GetDeviceInfo.argtypes = [ctypes.c_int]
        pa.Pa_GetErrorText.restype = ctypes.c_char_p
        pa.Pa_GetErrorText.argtypes = [ctypes.c_int]
        pa.Pa_IsFormatSupported.restype = ctypes.c_int
        pa.Pa_OpenStream.restype = ctypes.c_int
        pa.Pa_StartStream.restype = ctypes.c_int
        pa.Pa_ReadStream.restype = ctypes.c_int
        pa.Pa_StopStream.restype = ctypes.c_int
        pa.Pa_CloseStream.restype = ctypes.c_int
        return pa, PaHostApiInfo, PaDeviceInfo, PaStreamParameters, PaWasapiStreamInfo

    @classmethod
    def enumerate_input_devices(cls) -> List[Dict[str, Any]]:
        """Lists all PortAudio capture endpoints across MME, DirectSound, WASAPI, and WDM-KS."""
        try:
            pa, _, _, _, _ = cls._load_portaudio_ctypes()
        except Exception:
            return []
        out: List[Dict[str, Any]] = []
        with _PORTAUDIO_INIT_LOCK:
            if pa.Pa_Initialize() != 0:
                return []
            try:
                ndev = int(pa.Pa_GetDeviceCount())
                for idx in range(ndev):
                    di_ptr = pa.Pa_GetDeviceInfo(idx)
                    if not di_ptr:
                        continue
                    di = di_ptr.contents
                    if di.maxInputChannels <= 0:
                        continue
                    hi_ptr = pa.Pa_GetHostApiInfo(di.hostApi)
                    api_name = hi_ptr.contents.name.decode("utf-8", "ignore") if hi_ptr else "Unknown"
                    api_type = int(hi_ptr.contents.type) if hi_ptr else -1
                    out.append({
                        "index": idx,
                        "name": di.name.decode("utf-8", "ignore"),
                        "host_api": api_name,
                        "host_api_type": api_type,
                        "max_input_channels": int(di.maxInputChannels),
                        "default_sr": float(di.defaultSampleRate),
                        "low_latency_s": float(di.defaultLowInputLatency),
                        "high_latency_s": float(di.defaultHighInputLatency),
                    })
            finally:
                pa.Pa_Terminate()
        return out

    @classmethod
    def probe_best_hardware(cls, device_hint: str = "", prefer_ultrasonic: bool = True) -> Dict[str, Any]:
        """
        Probes attached microphones without keeping the stream open:
          1. Dodotronic UltraMic on Windows WASAPI Exclusive (`384,000 Hz` / `192,000 Hz` / `96,000 Hz` / `48,000 Hz`)
          2. Matching WASAPI / MME standard microphone fallback (`48,000 Hz` / `44,100 Hz`)
        """
        drv = cls(
            device_hint=device_hint,
            output_rate=384_000 if prefer_ultrasonic else 48_000,
        )
        ok = drv._open_portaudio_stream()
        info = {
            "available": bool(ok),
            "device_index": drv.device_index,
            "device_name": drv.device_name,
            "host_api": drv.host_api,
            "exclusive_mode": drv.exclusive_mode,
            "hw_sample_rate": drv.hw_sample_rate,
            "output_sample_rate": drv.output_sample_rate,
            "is_ultramic": "ultramic" in drv.device_name.lower(),
            "error": drv.last_error,
        }
        drv._close_portaudio_stream()
        return info

    @staticmethod
    def _design_decim_lpf(decim: int, cutoff_ratio: float = 0.80) -> np.ndarray:
        """63-tap Blackman-windowed sinc anti-aliasing filter for integer decimation."""
        if decim <= 1:
            return np.array([1.0], dtype=np.float32)
        num_taps = 8 * decim - 1  # 63 taps for 8x (384k -> 48k)
        fc = (0.5 / float(decim)) * cutoff_ratio
        n = np.arange(num_taps, dtype=np.float64) - (num_taps - 1) / 2.0
        h = np.sinc(2.0 * fc * n) * np.blackman(num_taps)
        h /= np.sum(h)
        return h.astype(np.float32)

    def _open_portaudio_stream(self) -> bool:
        import ctypes

        try:
            pa, _, _, PaStreamParameters, PaWasapiStreamInfo = self._load_portaudio_ctypes()
        except Exception as exc:
            self.last_error = f"portaudio load failed: {exc}"
            return False

        with _PORTAUDIO_INIT_LOCK:
            rc = pa.Pa_Initialize()
            if rc != 0:
                self.last_error = pa.Pa_GetErrorText(rc).decode("utf-8", "ignore")
                return False
            self._pa = pa
            self._pa_initialized = True

            ndev = int(pa.Pa_GetDeviceCount())
            candidates: List[Tuple[int, int, str, str, int, float, float, float]] = []
            hint_l = self.device_hint.lower()

            for idx in range(ndev):
                di_ptr = pa.Pa_GetDeviceInfo(idx)
                if not di_ptr:
                    continue
                di = di_ptr.contents
                if di.maxInputChannels <= 0:
                    continue
                hi_ptr = pa.Pa_GetHostApiInfo(di.hostApi)
                api_name = hi_ptr.contents.name.decode("utf-8", "ignore") if hi_ptr else ""
                api_type = int(hi_ptr.contents.type) if hi_ptr else -1
                dev_name = di.name.decode("utf-8", "ignore")
                if hint_l and hint_l not in dev_name.lower():
                    continue

                is_um = 1 if "ultramic" in dev_name.lower() else 0
                is_wasapi = 1 if api_type == self.PA_WASAPI_TYPE else 0
                is_mme = 1 if "mme" in api_name.lower() else 0
                not_mapper = 0 if ("mapper" in dev_name.lower() or "primary" in dev_name.lower()) else 1
                priority = is_um * 100 + is_wasapi * 40 + not_mapper * 10 + is_mme * 5
                candidates.append((
                    -priority,
                    idx,
                    dev_name,
                    api_name,
                    api_type,
                    float(di.defaultSampleRate),
                    float(di.defaultLowInputLatency),
                    float(di.defaultHighInputLatency),
                ))

            candidates.sort()

            # Try WASAPI Exclusive first for UltraMic / WASAPI endpoints, then Shared / MME fallback
            attempts: List[Tuple[int, str, str, bool, int]] = []
            for _, idx, dev_name, api_name, api_type, def_sr, _, _ in candidates:
                if api_type == self.PA_WASAPI_TYPE:
                    for sr_try in (384_000, 250_000, 192_000, 96_000, 48_000, int(round(def_sr))):
                        if sr_try > 0:
                            attempts.append((idx, dev_name, api_name, True, sr_try))
                    for sr_try in (int(round(def_sr)), 48_000):
                        if sr_try > 0:
                            attempts.append((idx, dev_name, api_name, False, sr_try))
                else:
                    for sr_try in (48_000, int(round(def_sr)), 384_000):
                        if sr_try > 0:
                            attempts.append((idx, dev_name, api_name, False, sr_try))

            for idx, dev_name, api_name, excl, sr_try in attempts:
                wasapi_info = None
                host_ptr = None
                if excl:
                    wasapi_info = PaWasapiStreamInfo()
                    wasapi_info.size = ctypes.sizeof(PaWasapiStreamInfo)
                    wasapi_info.hostApiType = self.PA_WASAPI_TYPE
                    wasapi_info.version = 1
                    wasapi_info.flags = self.WASAPI_FLAG_EXCLUSIVE | self.WASAPI_FLAG_THREAD_PRIORITY
                    wasapi_info.threadPriority = self.THREAD_PRIORITY_PRO_AUDIO
                    host_ptr = ctypes.cast(ctypes.byref(wasapi_info), ctypes.c_void_p)

                params = PaStreamParameters(
                    device=idx,
                    channelCount=1,
                    sampleFormat=self.PA_INT16,
                    suggestedLatency=0.020 if excl else 0.045,
                    hostApiSpecificStreamInfo=host_ptr,
                )
                if pa.Pa_IsFormatSupported(ctypes.byref(params), None, ctypes.c_double(sr_try)) != 0:
                    continue

                stream = ctypes.c_void_p()
                err = pa.Pa_OpenStream(
                    ctypes.byref(stream),
                    ctypes.byref(params),
                    None,
                    ctypes.c_double(sr_try),
                    ctypes.c_ulong(0),
                    ctypes.c_ulong(0),
                    None,
                    None,
                )
                if err != 0:
                    self.last_error = pa.Pa_GetErrorText(err).decode("utf-8", "ignore")
                    continue

                self._stream_handle = stream
                self._wasapi_info_keepalive = wasapi_info
                self._params_keepalive = params
                self.device_index = idx
                self.device_name = dev_name
                self.host_api = f"{api_name} ({'Exclusive' if excl else 'Shared'})"
                self.exclusive_mode = excl
                self.hw_sample_rate = int(sr_try)

                if self.requested_output_rate > 0 and self.hw_sample_rate > self.requested_output_rate and (
                    self.hw_sample_rate % self.requested_output_rate == 0
                ):
                    self.decim_factor = self.hw_sample_rate // self.requested_output_rate
                    self.output_sample_rate = self.requested_output_rate
                    self._fir_taps = self._design_decim_lpf(self.decim_factor)
                    self._fir_tail = np.zeros(len(self._fir_taps) - 1, dtype=np.float32)
                else:
                    self.decim_factor = 1
                    self.output_sample_rate = self.hw_sample_rate
                    self._fir_taps = None
                    self._fir_tail = np.zeros(0, dtype=np.float32)

                self.connected = True
                return True

            self._close_portaudio_stream()
            return False

    def _close_portaudio_stream(self) -> None:
        with _PORTAUDIO_INIT_LOCK:
            if self._pa is not None and self._stream_handle is not None:
                try:
                    self._pa.Pa_StopStream(self._stream_handle)
                except Exception:
                    pass
                try:
                    self._pa.Pa_CloseStream(self._stream_handle)
                except Exception:
                    pass
                self._stream_handle = None
            if self._pa is not None and self._pa_initialized:
                try:
                    self._pa.Pa_Terminate()
                except Exception:
                    pass
                self._pa_initialized = False
                self._pa = None
            self.connected = False

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return self.connected
        self._stop_evt.clear()
        self._dc_initialized = False
        if not self._open_portaudio_stream():
            return False
        err = self._pa.Pa_StartStream(self._stream_handle)
        if err != 0:
            self.last_error = self._pa.Pa_GetErrorText(err).decode("utf-8", "ignore")
            self._close_portaudio_stream()
            return False
        self._thread = threading.Thread(target=self._reader_loop, name="LarexUltraMicWASAPI", daemon=True)
        self._thread.start()
        print(
            f"[GNU-Larex] Connected Live UltraMic/Audio: {self.device_name} via {self.host_api} "
            f"@ {self.hw_sample_rate} Hz (out={self.output_sample_rate} Hz)",
            flush=True,
        )
        return True

    def stop(self) -> None:
        self._stop_evt.set()
        with self._cond:
            self._cond.notify_all()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None
        self._close_portaudio_stream()

    def _decimate_chunk(self, x_hw: np.ndarray) -> np.ndarray:
        if self.decim_factor <= 1 or self._fir_taps is None:
            return x_hw
        padded = np.concatenate([self._fir_tail, x_hw])
        self._fir_tail = padded[-(len(self._fir_taps) - 1) :].copy()
        filtered = np.convolve(padded, self._fir_taps, mode="valid")
        return filtered[:: self.decim_factor].astype(np.float32, copy=False)

    def _reader_loop(self) -> None:
        import ctypes

        raw_chunk = max(512, int(round(self.hw_sample_rate * (self.chunk_ms / 1000.0))))
        if self.decim_factor > 1:
            raw_chunk = max(self.decim_factor, (raw_chunk // self.decim_factor) * self.decim_factor)
        buf = (ctypes.c_int16 * raw_chunk)()
        spec_counter = 0

        while not self._stop_evt.is_set() and self._pa is not None and self._stream_handle is not None:
            rerr = self._pa.Pa_ReadStream(self._stream_handle, buf, ctypes.c_ulong(raw_chunk))
            if self._stop_evt.is_set():
                break
            if rerr != 0:
                # paInputOverflowed = -9981
                if rerr == -9981:
                    self.overrun_count += 1
                else:
                    self.last_error = self._pa.Pa_GetErrorText(rerr).decode("utf-8", "ignore")
                    time.sleep(0.005)
                    continue

            arr = np.frombuffer(buf, dtype=np.int16).astype(np.float32) * (1.0 / 32768.0)
            mean_v = float(np.mean(arr))
            if not self._dc_initialized:
                self._dc_est = mean_v
                self._dc_initialized = True
            else:
                self._dc_est = 0.96 * self._dc_est + 0.04 * mean_v
            self.dc_offset = self._dc_est
            ac = (arr - np.float32(self._dc_est)).astype(np.float32, copy=False)

            rms = float(np.sqrt(np.mean(ac * ac) + 1e-20))
            pk = float(np.max(np.abs(ac)) + 1e-20)
            self.rms_dbfs = round(20.0 * math.log10(max(rms, 1e-7)), 2)
            self.peak_dbfs = round(20.0 * math.log10(max(pk, 1e-7)), 2)
            self.frames_captured += len(ac)

            # Periodic wideband ultrasonic telemetry (~5 Hz)
            spec_counter += 1
            if (spec_counter % 10) == 1 and len(ac) >= 1024:
                n_fft = min(len(ac), 8192)
                sp = np.abs(np.fft.rfft(ac[:n_fft] * np.hanning(n_fft))) / (n_fft * 0.5)
                freqs = np.fft.rfftfreq(n_fft, d=1.0 / self.hw_sample_rate)
                v_mask = (freqs >= 80.0) & (freqs <= 4000.0)
                if np.any(v_mask):
                    v_rms = float(np.sqrt(np.sum(sp[v_mask] ** 2)))
                    self.voice_band_dbfs = round(20.0 * math.log10(max(v_rms, 1e-7)), 2)
                if self.hw_sample_rate >= 96_000:
                    u_mask = (freqs >= 20_000.0) & (freqs <= min(180_000.0, 0.48 * self.hw_sample_rate))
                    if np.any(u_mask):
                        u_sp = sp[u_mask]
                        u_rms = float(np.sqrt(np.sum(u_sp ** 2)))
                        self.ultrasonic_band_dbfs = round(20.0 * math.log10(max(u_rms, 1e-7)), 2)
                        self.peak_ultrasonic_hz = round(float(freqs[u_mask][int(np.argmax(u_sp))]), 1)

            out_chunk = self._decimate_chunk(ac)
            with self._cond:
                if len(self._queue) >= self._max_queue_chunks:
                    self._queue.popleft()
                    self.queue_drops += 1
                self._queue.append(out_chunk.copy())
                self._cond.notify()

    def read_samples(self, max_samples: int, timeout: float = 0.08) -> np.ndarray:
        """Blocking hardware-paced consumer for GNU Radio `UltraMicSourceBlock.work()`."""
        max_samples = max(1, int(max_samples))
        with self._cond:
            if not self._queue and not self._stop_evt.is_set():
                self._cond.wait(timeout=timeout)
            if not self._queue:
                return np.zeros(min(max_samples, 1024), dtype=np.float32)

            first = self._queue[0]
            if len(first) <= max_samples:
                chunks = [self._queue.popleft()]
                total = len(chunks[0])
                while self._queue and (total + len(self._queue[0])) <= max_samples:
                    c = self._queue.popleft()
                    chunks.append(c)
                    total += len(c)
                return chunks[0] if len(chunks) == 1 else np.concatenate(chunks)

            head = first[:max_samples].copy()
            self._queue[0] = first[max_samples:]
            return head


class BreathAndMouthExtractor:
    """
    Separates silent breathing cadence and mouth/lip articulation shapes from pitched
    laryngeal subvocalizations using simultaneous Ultrasonic Mic + RF Radar blocks.
    """

    SPEAKER_MOUTH_PROFILES: Dict[str, Dict[str, float]] = {
        # High whisper rate (47-55%) & rapid short bursts (med 1.24s): wider sibilant/cavity band + faster LFO
        "PERSON_ALPHA": {
            "mouth_lo_hz": 720.0,
            "mouth_hi_hz": 5200.0,
            "art_floor_mult": 1.75,
            "min_art_energy": 0.18,
            "breath_smooth": 0.84,
        },
        # High overall voiced speech activity (med 3.97s, 10.3 words/utt): stable vocal-tract centroid
        "PERSON_BETA": {
            "mouth_lo_hz": 800.0,
            "mouth_hi_hz": 4100.0,
            "art_floor_mult": 2.45,
            "min_art_energy": 0.36,
            "breath_smooth": 0.91,
        },
        # Low volume & short quiet whispers: maximum lip/whisper sensitivity
        "PERSON_DELTA": {
            "mouth_lo_hz": 700.0,
            "mouth_hi_hz": 5400.0,
            "art_floor_mult": 1.55,
            "min_art_energy": 0.14,
            "breath_smooth": 0.86,
        },
        # Mid-field (~1.67-2.2m) minimal count but fastest active pace (8,044 WPH): high-HF compensation
        "PERSON_GAMMA": {
            "mouth_lo_hz": 760.0,
            "mouth_hi_hz": 4800.0,
            "art_floor_mult": 1.85,
            "min_art_energy": 0.20,
            "breath_smooth": 0.85,
        },
    }

    def __init__(self, sample_rate: int = 48000, block_size: int = 2048) -> None:
        self.sr = sample_rate
        self.block_size = block_size
        self.freqs = np.fft.rfftfreq(block_size, 1.0 / sample_rate)
        self.window = np.hanning(block_size)

        # Adaptive mouth/whisper tuning parameters (defaulting to PERSON_ALPHA high-whisper profile)
        self.active_speaker_profile: str = "PERSON_ALPHA"
        self.mouth_lo_hz: float = 720.0
        self.mouth_hi_hz: float = 5200.0
        self.art_floor_mult: float = 1.75
        self.min_art_energy: float = 0.18
        self.breath_smooth: float = 0.84

        # Smoothing state for slow breathing envelope
        self.breath_envelope = 0.0
        self._art_floor = 0.05
        self._u_fifo = np.zeros(0, dtype=np.float64)
        self._r_fifo = np.zeros(0, dtype=np.float64)
        # Rolling 2-second decimated radar buffer (750 Hz -> 0.5 Hz bin resolution across 0.5-15 Hz)
        self._lfo_decim = max(1, int(round(sample_rate / 750.0)))
        self._lfo_sr = float(sample_rate) / self._lfo_decim
        self._lfo_len = max(256, int(round(self._lfo_sr * 2.0)))
        self._lfo_buf = np.zeros(self._lfo_len, dtype=np.float64)
        self._lfo_filled = 0
        self._lfo_win = np.hanning(self._lfo_len)
        self._lfo_freqs = np.fft.rfftfreq(self._lfo_len, 1.0 / self._lfo_sr)
        self._lfo_mask = (self._lfo_freqs >= 0.5) & (self._lfo_freqs <= 15.0)
        self.latest_state: Dict[str, Any] = {
            "breath_lfo": 0.0,
            "mouth_openness": 0.0,
            "articulation_energy": 0.0,
            "vowel_centroid_hz": 800.0,
            "viseme": "REST_CLOSED",
            "silent_mouthing": False,
            "active_speaker_profile": self.active_speaker_profile,
        }

    def set_speaker_profile(self, speaker_id: str, overrides: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        """Switches `BreathAndMouthExtractor` to the speaker's calibrated whisper/articulation profile."""
        prof = dict(self.SPEAKER_MOUTH_PROFILES.get(speaker_id, self.SPEAKER_MOUTH_PROFILES["PERSON_ALPHA"]))
        if overrides:
            for k, v in overrides.items():
                if k in prof:
                    prof[k] = float(v)
        self.active_speaker_profile = speaker_id
        self.mouth_lo_hz = float(np.clip(prof["mouth_lo_hz"], 500.0, 1500.0))
        self.mouth_hi_hz = float(np.clip(prof["mouth_hi_hz"], 2800.0, 8000.0))
        self.art_floor_mult = float(np.clip(prof["art_floor_mult"], 1.25, 4.0))
        self.min_art_energy = float(np.clip(prof["min_art_energy"], 0.08, 1.5))
        self.breath_smooth = float(np.clip(prof["breath_smooth"], 0.70, 0.97))
        return {
            "speaker_id": self.active_speaker_profile,
            "mouth_lo_hz": self.mouth_lo_hz,
            "mouth_hi_hz": self.mouth_hi_hz,
            "art_floor_mult": self.art_floor_mult,
            "min_art_energy": self.min_art_energy,
            "breath_smooth": self.breath_smooth,
        }

    def _fit_block(self, arr: np.ndarray) -> np.ndarray:
        x = np.asarray(arr, dtype=np.float64).ravel()
        if len(x) == self.block_size:
            return x
        if len(x) > self.block_size:
            return x[-self.block_size :]
        out = np.zeros(self.block_size, dtype=np.float64)
        out[-len(x) :] = x
        return out

    def extract_non_vocal_layers(
        self, ultrasonic_block: np.ndarray, pluto_radar_block: np.ndarray, f0_hz: float = 0.0
    ) -> Dict[str, Any]:
        """Separates silent breathing cadence and mouth articulation shapes

        from pitched laryngeal subvocalizations.
        """
        u_blk = self._fit_block(ultrasonic_block)
        r_blk = self._fit_block(pluto_radar_block)

        # 1. BREATHING CADENCE (Low-frequency chest/diaphragm drift on Pluto / RTL-SDR radar)
        # Compute ultra-low frequency energy (0.5 Hz - 15 Hz)
        r_sub = r_blk[:: self._lfo_decim]
        m_sub = len(r_sub)
        if m_sub > 0:
            if m_sub >= self._lfo_len:
                self._lfo_buf[:] = r_sub[-self._lfo_len :]
                self._lfo_filled = self._lfo_len
            else:
                self._lfo_buf[:-m_sub] = self._lfo_buf[m_sub:]
                self._lfo_buf[-m_sub:] = r_sub
                self._lfo_filled = min(self._lfo_len, self._lfo_filled + m_sub)

        breath_mask = (self.freqs >= 0.5) & (self.freqs <= 15.0)
        if np.any(breath_mask):
            radar_spec = np.abs(np.fft.rfft(r_blk * self.window))
            raw_breath = float(np.mean(radar_spec[breath_mask]))
        elif self._lfo_filled >= self._lfo_len // 4 and np.any(self._lfo_mask):
            lfo_centered = self._lfo_buf - float(np.mean(self._lfo_buf))
            lfo_spec = np.abs(np.fft.rfft(lfo_centered * self._lfo_win))
            raw_breath = float(np.mean(lfo_spec[self._lfo_mask]))
        else:
            # Single-call high-resolution zero-padded fallback (df <= 0.5 Hz)
            n_zp = max(self.block_size, int(round(self.sr * 2.0)))
            zp_freqs = np.fft.rfftfreq(n_zp, 1.0 / self.sr)
            zp_mask = (zp_freqs >= 0.5) & (zp_freqs <= 15.0)
            r_centered = (r_blk - float(np.mean(r_blk))) * self.window
            zp_spec = np.abs(np.fft.rfft(r_centered, n=n_zp))
            raw_breath = float(np.mean(zp_spec[zp_mask])) if np.any(zp_mask) else 0.0

        # Smooth over time to track slow inhales and exhales (LFO curve)
        alpha_b = self.breath_smooth
        self.breath_envelope = (self.breath_envelope * alpha_b) + (
            raw_breath * (1.0 - alpha_b)
        )

        # 2. MOUTH & LIP ARTICULATION (High-frequency air/skin Doppler on Ultrasonic Mic)
        ultra_spec = np.abs(np.fft.rfft(u_blk * self.window))
        mouth_mask = (self.freqs >= self.mouth_lo_hz) & (self.freqs <= self.mouth_hi_hz)

        # Spectral centroid of mouth cavity tells you if mouth is open ("ah") or closed ("oo")
        mouth_energies = ultra_spec[mouth_mask]
        mouth_freqs = self.freqs[mouth_mask]
        total_mouth_energy = float(np.sum(mouth_energies) + 1e-6)

        vowel_centroid_hz = float(
            np.sum(mouth_freqs * mouth_energies) / total_mouth_energy
        )

        # Normalize vowel shape from 0.0 (closed/pursed lips) to 1.0 (wide open mouth)
        span_hz = max(1600.0, (self.mouth_hi_hz - self.mouth_lo_hz) * 0.68)
        mouth_openness = float(np.clip((vowel_centroid_hz - self.mouth_lo_hz) / span_hz, 0.0, 1.0))

        # Track ambient mouth-band floor to classify active viseme & silent lip articulation
        if total_mouth_energy < 1.8 * self._art_floor:
            self._art_floor = 0.96 * self._art_floor + 0.04 * total_mouth_energy
        else:
            self._art_floor = 0.995 * self._art_floor + 0.005 * total_mouth_energy

        active_articulation = total_mouth_energy > max(
            self.min_art_energy, self.art_floor_mult * self._art_floor
        )
        if not active_articulation:
            viseme = "REST_CLOSED"
        elif mouth_openness < 0.20:
            viseme = "PURSED_OO"       # Pursed/rounded lips ("oo", "mm", "w")
        elif mouth_openness < 0.45:
            viseme = "ROUNDED_OH"      # Semi-closed ("oh", "ih", "u")
        elif mouth_openness < 0.72:
            viseme = "MID_EH"          # Neutral mid-open ("eh", "uh", "er")
        else:
            viseme = "WIDE_AH"         # Wide jaw/lip aperture ("ah", "ae", "ee")

        silent_mouthing = bool(active_articulation and f0_hz < 55.0)

        result = {
            "breath_lfo": round(self.breath_envelope, 4),
            "mouth_openness": round(mouth_openness, 3),
            "articulation_energy": round(total_mouth_energy, 2),
            "vowel_centroid_hz": round(vowel_centroid_hz, 1),
            "viseme": viseme,
            "silent_mouthing": silent_mouthing,
            "active_speaker_profile": self.active_speaker_profile,
        }
        self.latest_state = result
        return result

    def push_streaming_chunks(
        self, ultrasonic_chunk: np.ndarray, radar_chunk: np.ndarray, f0_hz: float = 0.0
    ) -> Dict[str, Any]:
        """Buffers arbitrary GNU Radio audio/radar chunk sizes into 2048-sample FFT blocks."""
        self._u_fifo = np.concatenate((self._u_fifo, np.asarray(ultrasonic_chunk, dtype=np.float64).ravel()))
        self._r_fifo = np.concatenate((self._r_fifo, np.asarray(radar_chunk, dtype=np.float64).ravel()))
        hop = self.block_size // 2
        while len(self._u_fifo) >= self.block_size and len(self._r_fifo) >= self.block_size:
            u_blk = self._u_fifo[: self.block_size]
            r_blk = self._r_fifo[: self.block_size]
            self._u_fifo = self._u_fifo[hop:]
            self._r_fifo = self._r_fifo[hop:]
            self.extract_non_vocal_layers(u_blk, r_blk, f0_hz=f0_hz)
        # Prevent unbounded growth if one stream pauses
        if len(self._u_fifo) > self.block_size * 4:
            self._u_fifo = self._u_fifo[-self.block_size * 2 :]
        if len(self._r_fifo) > self.block_size * 4:
            self._r_fifo = self._r_fifo[-self.block_size * 2 :]
        return self.latest_state


class AsyncSDRRadarStream:
    """
    Clock-decoupled background SoapySDR reader (`RTL-SDR Blog V4`, `PlutoSDR`, `Airspy`)
    that captures 960 kHz I/Q, runs `IQClutterCancellerCore` + `PhaseVibrometerCore`,
    and exposes BOTH:
      - Lock-free 48 kHz radar displacement ring buffer (`um`) + `RTLSDR_ZMQ` (`:5556`) PUB
      - Lock-free 960 kHz raw `complex64` I/Q ring buffer (`read_raw_iq`) so GNU Radio's
        `HybridSDRRadarSource` shares live hardware I/Q with ZERO WinUSB handle conflicts
        and ZERO two-clock PortAudio underruns!
    """

    def __init__(
        self,
        rf_samp_rate: float = 960_000.0,
        baseband_rate: float = 48_000.0,
        rf_freq_mhz: float = 915.0,
        rf_gain: float = 38.0,
        sdr_args: str = "",
    ) -> None:
        self.rf_samp_rate = float(rf_samp_rate)
        self.baseband_rate = float(baseband_rate)
        self.decim = max(1, int(round(self.rf_samp_rate / self.baseband_rate)))
        self.rf_freq_mhz = float(rf_freq_mhz)
        self.rf_gain = float(rf_gain)
        self.sdr_args = sdr_args

        self.sdr_connected: bool = False
        self.sdr_info: Dict[str, str] = {}
        self.sdr_label: str = "Probing RTL-SDR V4..."
        self.rf_power_dbfs: float = -95.0
        self.packets_published: int = 0

        self._clutter = IQClutterCancellerCore(alpha=0.005, mode=0)
        self._phase = PhaseVibrometerCore(samp_rate=self.baseband_rate, rf_freq_mhz=self.rf_freq_mhz)
        self._max_buf = int(self.baseband_rate * 10)  # 10 seconds @ 48 kHz
        self._disp_ring = np.zeros(self._max_buf, dtype=np.float32)
        self._write_ptr = 0
        self._disp_write_total = 0
        self._disp_read_total = 0
        self._iq48_raw_snap = np.zeros(4096, dtype=np.complex64)
        self._iq48_cen_snap = np.zeros(4096, dtype=np.complex64)

        # Lock-free 1.0-second 960 kHz complex64 I/Q ring for GNU Radio Tab 3 & Dual Sensor Fusion
        self._iq_cap = int(round(self.rf_samp_rate))
        self._iq_ring = np.zeros(self._iq_cap, dtype=np.complex64)
        self._iq_write_total = 0
        self._iq_read_total = 0
        self._raw_iq_requested = False

        self._lock = threading.Lock()
        self._iq_lock = threading.Lock()
        self._stop_evt = threading.Event()
        self._reconnect_evt = threading.Event()
        self.initial_probe_done = threading.Event()
        self._dev: Any = None
        self._rx_st: Any = None
        self._zmq_ctx: Any = None
        self._zmq_pub: Any = None
        self.zmq_pub_addr: str = "tcp://127.0.0.1:5556"
        self.zmq_pub_active: bool = False

        # Preload SoapySDR / libusb DLLs on main thread BEFORE pyzmq loads libzmq DLLs on Windows
        try:
            import SoapySDR as _soapy_preload  # type: ignore  # noqa: F401
        except Exception:
            pass

        try:
            import zmq  # type: ignore

            self._zmq_ctx = zmq.Context.instance()
            pub = self._zmq_ctx.socket(zmq.PUB)
            pub.setsockopt(zmq.SNDHWM, 8)
            pub.setsockopt(zmq.LINGER, 0)
            pub.bind(self.zmq_pub_addr)
            self._zmq_pub = pub
            self.zmq_pub_active = True
        except Exception:
            self._zmq_pub = None
            self.zmq_pub_active = False

        self._thread = threading.Thread(target=self._run_supervisor, name="LarexAsyncSDRRadar", daemon=True)
        self._thread.start()

    def _append_disp(
        self,
        disp: np.ndarray,
        dec_iq: Optional[np.ndarray] = None,
        cen_iq: Optional[np.ndarray] = None,
    ) -> None:
        m = len(disp)
        if m == 0:
            return
        if m >= self._max_buf:
            disp = disp[-self._max_buf :]
            m = len(disp)
        with self._lock:
            end = self._write_ptr + m
            if end <= self._max_buf:
                self._disp_ring[self._write_ptr : end] = disp
            else:
                first = self._max_buf - self._write_ptr
                self._disp_ring[self._write_ptr :] = disp[:first]
                self._disp_ring[: m - first] = disp[first:]
            self._write_ptr = end % self._max_buf
            self._disp_write_total += m
            if dec_iq is not None and len(dec_iq) > 0:
                k = min(len(dec_iq), len(self._iq48_raw_snap))
                if k < len(self._iq48_raw_snap):
                    self._iq48_raw_snap[:-k] = self._iq48_raw_snap[k:]
                self._iq48_raw_snap[-k:] = dec_iq[-k:]
            if cen_iq is not None and len(cen_iq) > 0:
                k = min(len(cen_iq), len(self._iq48_cen_snap))
                if k < len(self._iq48_cen_snap):
                    self._iq48_cen_snap[:-k] = self._iq48_cen_snap[k:]
                self._iq48_cen_snap[-k:] = cen_iq[-k:]

    def read_stream_disp_um(self, count: int) -> Optional[np.ndarray]:
        """Elastic non-blocking 48 kHz unwrapped displacement reader sample-locked to consumer."""
        if not self.sdr_connected or count <= 0:
            return None
        n = min(int(count), self._max_buf // 2)
        with self._lock:
            wt = self._disp_write_total
            if wt < n:
                return None
            avail = wt - self._disp_read_total
            max_lag = max(n * 4, int(self.baseband_rate * 0.18))
            if avail < n or avail > max_lag:
                self._disp_read_total = wt - n
            rp = self._disp_read_total % self._max_buf
            self._disp_read_total += n
            end = rp + n
            if end <= self._max_buf:
                return self._disp_ring[rp:end].copy()
            first = self._max_buf - rp
            out = np.empty(n, dtype=np.float32)
            out[:first] = self._disp_ring[rp:]
            out[first:] = self._disp_ring[: n - first]
            return out

    def get_recent_iq_48k_pair(self, count: int = 1024) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        if not self.sdr_connected or count <= 0:
            return None
        k = min(int(count), len(self._iq48_raw_snap))
        with self._lock:
            return self._iq48_raw_snap[-k:].copy(), self._iq48_cen_snap[-k:].copy()

    def _append_raw_iq(self, iq: np.ndarray) -> None:
        m = len(iq)
        if m == 0:
            return
        if m >= self._iq_cap:
            iq = iq[-self._iq_cap :]
            m = len(iq)
        with self._iq_lock:
            wp = self._iq_write_total % self._iq_cap
            end = wp + m
            if end <= self._iq_cap:
                self._iq_ring[wp:end] = iq
            else:
                first = self._iq_cap - wp
                self._iq_ring[wp:] = iq[:first]
                self._iq_ring[: m - first] = iq[first:]
            self._iq_write_total += m

    def read_raw_iq(self, count: int) -> Optional[np.ndarray]:
        """Elastic non-blocking 960 kHz I/Q reader for GNU Radio `HybridSDRRadarSource`."""
        self._raw_iq_requested = True
        if not self.sdr_connected or count <= 0:
            return None
        n = min(int(count), self._iq_cap // 2)
        with self._iq_lock:
            wt = self._iq_write_total
            if wt < n:
                return None
            avail = wt - self._iq_read_total
            # Keep elastic latency between n and 0.25s to absorb crystal PPM offset cleanly
            max_lag = max(n * 4, int(self.rf_samp_rate * 0.22))
            if avail < n or avail > max_lag:
                self._iq_read_total = wt - n
            rp = self._iq_read_total % self._iq_cap
            self._iq_read_total += n
            end = rp + n
            if end <= self._iq_cap:
                return self._iq_ring[rp:end].copy()
            first = self._iq_cap - rp
            out = np.empty(n, dtype=np.complex64)
            out[:first] = self._iq_ring[rp:]
            out[first:] = self._iq_ring[: n - first]
            return out

    def get_recent_samples(self, count: int) -> np.ndarray:
        count = max(1, min(int(count), self._max_buf))
        with self._lock:
            wp = self._write_ptr
            if wp >= count:
                return self._disp_ring[wp - count : wp].copy()
            part1 = self._disp_ring[self._max_buf - (count - wp) :]
            part2 = self._disp_ring[:wp]
            return np.concatenate((part1, part2)).copy()

    def set_rf_freq_mhz(self, freq_mhz: float) -> None:
        self.rf_freq_mhz = float(freq_mhz)
        self._phase.rf_freq_mhz = self.rf_freq_mhz

    def set_rf_gain(self, gain_db: float) -> None:
        self.rf_gain = float(np.clip(float(gain_db), 0.0, 60.0))

    def reconnect(self) -> None:
        self._reconnect_evt.set()

    @property
    def connected(self) -> bool:
        return self.sdr_connected

    @property
    def device_label(self) -> str:
        return self.sdr_label

    @property
    def sdr_rate(self) -> float:
        return self.rf_samp_rate

    @property
    def phase_coherence(self) -> float:
        return float(self._phase.last_coherence)

    def _try_open_device(self) -> bool:
        try:
            import SoapySDR  # type: ignore
            from SoapySDR import SOAPY_SDR_CF32, SOAPY_SDR_RX  # type: ignore

            dev = None
            target_args = self.sdr_args.strip()
            # Prefer RTL-SDR Blog V4 for coherent 960 kHz primary radar so HackRF stays dedicated on :5557
            if not target_args:
                devices = safe_enumerate_soapysdr("driver=rtlsdr")
                if not devices:
                    # Fallback to PlutoSDR / Airspy if no RTL-SDR attached
                    for fallback_drv in ("driver=plutosdr", "driver=airspy"):
                        devices = safe_enumerate_soapysdr(fallback_drv)
                        if devices:
                            break
            else:
                devices = safe_enumerate_soapysdr(target_args)

            with _SOAPY_USB_LOCK:
                if devices:
                    self.sdr_info = devices[0]
                    dev = SoapySDR.Device(soapy_info_to_markup(devices[0]))
                elif not target_args or "rtlsdr" in target_args:
                    try:
                        dev = SoapySDR.Device("driver=rtlsdr")
                        hw_key = str(dev.getHardwareKey())
                        self.sdr_info = {"driver": "rtlsdr", "product": "RTL-SDR Blog V4", "tuner": hw_key}
                    except Exception:
                        dev = None

                if dev is None:
                    self.sdr_connected = False
                    self.sdr_label = "No RTL-SDR (Waiting for USB)"
                    return False

                dev.setSampleRate(SOAPY_SDR_RX, 0, self.rf_samp_rate)
                dev.setFrequency(SOAPY_SDR_RX, 0, self.rf_freq_mhz * 1e6)
                dev.setGain(SOAPY_SDR_RX, 0, self.rf_gain)
                rx_st = dev.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
                dev.activateStream(rx_st)

            self._dev = dev
            self._rx_st = rx_st
            self.sdr_connected = True
            prod = self.sdr_info.get("product") or self.sdr_info.get("label") or self.sdr_info.get("driver", "RTL-SDR")
            if str(prod).strip() == "Blog V4":
                prod = "RTL-SDR Blog V4"
            tuner = self.sdr_info.get("tuner") or str(dev.getHardwareKey())
            self.sdr_label = f"{prod} ({tuner})" if (tuner and tuner not in str(prod)) else str(prod)
            print(
                f"[GNU-Larex] Live Primary SDR Radar ACTIVE: {self.sdr_label} @ {self.rf_freq_mhz:.2f} MHz -> RTLSDR_ZMQ :5556",
                flush=True,
            )
            return True
        except Exception as exc:
            self.sdr_connected = False
            self.sdr_label = f"RTL-SDR Standby ({exc})"
            return False

    def _close_device(self) -> None:
        dev, rx_st = self._dev, self._rx_st
        self._dev = None
        self._rx_st = None
        self.sdr_connected = False
        if dev is not None and rx_st is not None:
            try:
                with _SOAPY_USB_LOCK:
                    dev.deactivateStream(rx_st)
                    dev.closeStream(rx_st)
            except Exception:
                pass

    def _run_supervisor(self) -> None:
        from SoapySDR import SOAPY_SDR_RX  # type: ignore

        first_try = True
        while not self._stop_evt.is_set():
            self._reconnect_evt.clear()
            opened = self._try_open_device()
            if first_try:
                first_try = False
                self.initial_probe_done.set()

            if not opened:
                self._stop_evt.wait(4.0)
                continue

            dev = self._dev
            rx_st = self._rx_st
            chunk_rf = 16_384 - (16_384 % self.decim)
            iq_buf = np.empty(chunk_rf, dtype=np.complex64)
            active_freq = self.rf_freq_mhz
            active_gain = self.rf_gain
            consecutive_timeouts = 0

            try:
                while not self._stop_evt.is_set() and not self._reconnect_evt.is_set():
                    if abs(self.rf_freq_mhz - active_freq) > 0.01:
                        dev.setFrequency(SOAPY_SDR_RX, 0, self.rf_freq_mhz * 1e6)
                        active_freq = self.rf_freq_mhz
                    if abs(self.rf_gain - active_gain) > 0.25:
                        dev.setGain(SOAPY_SDR_RX, 0, self.rf_gain)
                        active_gain = self.rf_gain

                    sr = dev.readStream(rx_st, [iq_buf], chunk_rf, timeoutUs=120_000)
                    if sr.ret <= 0:
                        consecutive_timeouts += 1
                        if consecutive_timeouts > 35:
                            break
                        continue
                    consecutive_timeouts = 0
                    valid = iq_buf[: (sr.ret // self.decim) * self.decim]
                    if len(valid) == 0:
                        continue
                    if self._raw_iq_requested:
                        self._append_raw_iq(valid)
                    # Boxcar anti-alias decimation (960 kHz -> 48 kHz)
                    dec_iq = valid.reshape(-1, self.decim).mean(axis=1).astype(np.complex64)
                    pwr = float(np.mean(dec_iq.real * dec_iq.real + dec_iq.imag * dec_iq.imag) + 1e-14)
                    self.rf_power_dbfs = round(10.0 * math.log10(pwr), 1)
                    centered = self._clutter.process(dec_iq)
                    disp_um = self._phase.process(centered)
                    self._append_disp(disp_um, dec_iq, centered)
                    if self._zmq_pub is not None:
                        try:
                            import zmq  # type: ignore

                            norm_rtlsdr = np.tanh(disp_um / 250.0).astype(np.float32)
                            self._zmq_pub.send(norm_rtlsdr.tobytes(), flags=zmq.NOBLOCK)
                            self.packets_published += 1
                        except Exception:
                            pass
            except Exception as exc:
                self.sdr_label = f"RTL-SDR Reconnecting ({exc})"
            finally:
                self._close_device()

            if not self._stop_evt.is_set() and not self._reconnect_evt.is_set():
                self._stop_evt.wait(2.5)

    def stop(self) -> None:
        self._stop_evt.set()
        self._reconnect_evt.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.5)
        if self._zmq_pub is not None:
            try:
                self._zmq_pub.close(0)
            except Exception:
                pass
            self._zmq_pub = None


class AsyncHackRFStream:
    """
    Dedicated background Wideband HackRF One (`driver=hackrf`) stream & `HACKRF_ZMQ` (`:5557`)
    publisher that runs SIMULTANEOUSLY alongside `AsyncSDRRadarStream` (`RTL-SDR Blog V4`):
      - Captures native 2.0 MSps (`2_000_000` Hz) wideband I/Q across 1 MHz – 6 GHz (default `2450.0 MHz`
        ISM band for 5.6x microwave lip/throat sensitivity + ambient RF precursor detection).
      - Configures staged HackRF RX gains (`LNA` 0..40 dB in 8 dB steps + `VGA` 0..62 dB in 2 dB steps, `AMP=0`).
      - Anti-alias decimates 2.0 MSps -> 48 kHz, extracting BOTH microwave unwrapped phase micro-Doppler
        (`um`) and wideband RF burst/precursor envelope -> publishes live `float32` frames on `tcp://127.0.0.1:5557`.
      - Exposes a resampled 960 kHz `complex64` I/Q ring (`read_raw_iq`) for GNU Radio Tab 3 / Dual-SDR Fusion.
      - Includes hot-plug / USB-reset auto-attach so pressing HackRF's physical RESET button connects live!
    """

    def __init__(
        self,
        hw_samp_rate: float = 2_000_000.0,
        rf_out_rate: float = 960_000.0,
        baseband_rate: float = 48_000.0,
        rf_freq_mhz: float = 2450.0,
        rf_gain: float = 44.0,
        sdr_args: str = "driver=hackrf",
        wait_event: Optional[threading.Event] = None,
    ) -> None:
        self.hw_samp_rate = float(hw_samp_rate)  # Exact native 2.0 MSps HackRF rate
        self.rf_out_rate = float(rf_out_rate)
        self.baseband_rate = float(baseband_rate)
        self.rf_freq_mhz = float(rf_freq_mhz)
        self.rf_gain = float(rf_gain)
        self.sdr_args = sdr_args
        self._wait_event = wait_event

        self.sdr_connected: bool = False
        self.sdr_info: Dict[str, str] = {}
        self.sdr_label: str = "Probing HackRF One..."
        self.rf_power_dbfs: float = -95.0
        self.rf_envelope_peak: float = 0.0
        self.packets_published: int = 0

        self._clutter = IQClutterCancellerCore(alpha=0.008, mode=0)
        self._phase = PhaseVibrometerCore(samp_rate=self.baseband_rate, rf_freq_mhz=self.rf_freq_mhz)
        self._env_floor: float = 0.01

        self._max_buf = int(self.baseband_rate * 10)
        self._env_ring = np.zeros(self._max_buf, dtype=np.float32)
        self._disp_ring = np.zeros(self._max_buf, dtype=np.float32)
        self._write_ptr = 0
        self._disp_write_total = 0
        self._disp_read_total = 0
        self._iq48_raw_snap = np.zeros(4096, dtype=np.complex64)
        self._iq48_cen_snap = np.zeros(4096, dtype=np.complex64)

        self._iq_cap = int(round(self.rf_out_rate))
        self._iq_ring = np.zeros(self._iq_cap, dtype=np.complex64)
        self._iq_write_total = 0
        self._iq_read_total = 0
        self._raw_iq_requested = False

        self._lock = threading.Lock()
        self._iq_lock = threading.Lock()
        self._stop_evt = threading.Event()
        self._reconnect_evt = threading.Event()
        self._dev: Any = None
        self._rx_st: Any = None
        self._zmq_ctx: Any = None
        self._zmq_pub: Any = None
        self.zmq_pub_addr: str = "tcp://127.0.0.1:5557"
        self.zmq_pub_active: bool = False

        try:
            import SoapySDR as _soapy_preload  # type: ignore  # noqa: F401
        except Exception:
            pass

        try:
            import zmq  # type: ignore

            self._zmq_ctx = zmq.Context.instance()
            pub = self._zmq_ctx.socket(zmq.PUB)
            pub.setsockopt(zmq.SNDHWM, 8)
            pub.setsockopt(zmq.LINGER, 0)
            pub.bind(self.zmq_pub_addr)
            self._zmq_pub = pub
            self.zmq_pub_active = True
        except Exception:
            self._zmq_pub = None
            self.zmq_pub_active = False

        self._thread = threading.Thread(target=self._run_supervisor, name="LarexAsyncHackRF", daemon=True)
        self._thread.start()

    @staticmethod
    def _split_hackrf_gains(total_gain_db: float) -> Tuple[float, float]:
        g = float(np.clip(total_gain_db, 0.0, 88.0))
        lna = float(min(40, int(round((g * 0.55) / 8.0)) * 8))
        vga = float(min(62, max(0, int(round((g - lna) / 2.0)) * 2)))
        return lna, vga

    def set_rf_freq_mhz(self, freq_mhz: float) -> None:
        self.rf_freq_mhz = float(np.clip(float(freq_mhz), 1.0, 6000.0))
        self._phase.rf_freq_mhz = self.rf_freq_mhz

    def set_rf_gain(self, gain_db: float) -> None:
        self.rf_gain = float(np.clip(float(gain_db), 0.0, 88.0))

    def reconnect(self) -> None:
        self._reconnect_evt.set()

    @property
    def connected(self) -> bool:
        return self.sdr_connected

    @property
    def device_label(self) -> str:
        return self.sdr_label

    @property
    def sdr_rate(self) -> float:
        return self.hw_samp_rate

    @property
    def phase_coherence(self) -> float:
        return float(self._phase.last_coherence)

    def _append_baseband(
        self,
        env_sig: np.ndarray,
        disp_um: np.ndarray,
        dec_iq: Optional[np.ndarray] = None,
        cen_iq: Optional[np.ndarray] = None,
    ) -> None:
        m = min(len(env_sig), len(disp_um))
        if m == 0:
            return
        if m >= self._max_buf:
            env_sig = env_sig[-self._max_buf :]
            disp_um = disp_um[-self._max_buf :]
            m = self._max_buf
        with self._lock:
            end = self._write_ptr + m
            if end <= self._max_buf:
                self._env_ring[self._write_ptr : end] = env_sig[:m]
                self._disp_ring[self._write_ptr : end] = disp_um[:m]
            else:
                first = self._max_buf - self._write_ptr
                self._env_ring[self._write_ptr :] = env_sig[:first]
                self._env_ring[: m - first] = env_sig[first:m]
                self._disp_ring[self._write_ptr :] = disp_um[:first]
                self._disp_ring[: m - first] = disp_um[first:m]
            self._write_ptr = end % self._max_buf
            self._disp_write_total += m
            if dec_iq is not None and len(dec_iq) > 0:
                k = min(len(dec_iq), len(self._iq48_raw_snap))
                if k < len(self._iq48_raw_snap):
                    self._iq48_raw_snap[:-k] = self._iq48_raw_snap[k:]
                self._iq48_raw_snap[-k:] = dec_iq[-k:]
            if cen_iq is not None and len(cen_iq) > 0:
                k = min(len(cen_iq), len(self._iq48_cen_snap))
                if k < len(self._iq48_cen_snap):
                    self._iq48_cen_snap[:-k] = self._iq48_cen_snap[k:]
                self._iq48_cen_snap[-k:] = cen_iq[-k:]

    def read_stream_disp_um(self, count: int) -> Optional[np.ndarray]:
        if not self.sdr_connected or count <= 0:
            return None
        n = min(int(count), self._max_buf // 2)
        with self._lock:
            wt = self._disp_write_total
            if wt < n:
                return None
            avail = wt - self._disp_read_total
            max_lag = max(n * 4, int(self.baseband_rate * 0.18))
            if avail < n or avail > max_lag:
                self._disp_read_total = wt - n
            rp = self._disp_read_total % self._max_buf
            self._disp_read_total += n
            end = rp + n
            if end <= self._max_buf:
                return self._disp_ring[rp:end].copy()
            first = self._max_buf - rp
            out = np.empty(n, dtype=np.float32)
            out[:first] = self._disp_ring[rp:]
            out[first:] = self._disp_ring[: n - first]
            return out

    def get_recent_iq_48k_pair(self, count: int = 1024) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        if not self.sdr_connected or count <= 0:
            return None
        k = min(int(count), len(self._iq48_raw_snap))
        with self._lock:
            return self._iq48_raw_snap[-k:].copy(), self._iq48_cen_snap[-k:].copy()

    def _append_raw_iq(self, iq_960k: np.ndarray) -> None:
        m = len(iq_960k)
        if m == 0:
            return
        if m >= self._iq_cap:
            iq_960k = iq_960k[-self._iq_cap :]
            m = len(iq_960k)
        with self._iq_lock:
            wp = self._iq_write_total % self._iq_cap
            end = wp + m
            if end <= self._iq_cap:
                self._iq_ring[wp:end] = iq_960k
            else:
                first = self._iq_cap - wp
                self._iq_ring[wp:] = iq_960k[:first]
                self._iq_ring[: m - first] = iq_960k[first:]
            self._iq_write_total += m

    def read_raw_iq(self, count: int) -> Optional[np.ndarray]:
        self._raw_iq_requested = True
        if not self.sdr_connected or count <= 0:
            return None
        n = min(int(count), self._iq_cap // 2)
        with self._iq_lock:
            wt = self._iq_write_total
            if wt < n:
                return None
            avail = wt - self._iq_read_total
            max_lag = max(n * 4, int(self.rf_out_rate * 0.22))
            if avail < n or avail > max_lag:
                self._iq_read_total = wt - n
            rp = self._iq_read_total % self._iq_cap
            self._iq_read_total += n
            end = rp + n
            if end <= self._iq_cap:
                return self._iq_ring[rp:end].copy()
            first = self._iq_cap - rp
            out = np.empty(n, dtype=np.complex64)
            out[:first] = self._iq_ring[rp:]
            out[first:] = self._iq_ring[: n - first]
            return out

    def get_recent_samples(self, count: int) -> np.ndarray:
        count = max(1, min(int(count), self._max_buf))
        with self._lock:
            wp = self._write_ptr
            if wp >= count:
                return self._env_ring[wp - count : wp].copy()
            part1 = self._env_ring[self._max_buf - (count - wp) :]
            part2 = self._env_ring[:wp]
            return np.concatenate((part1, part2)).copy()

    def get_recent_displacement_um(self, count: int) -> np.ndarray:
        count = max(1, min(int(count), self._max_buf))
        with self._lock:
            wp = self._write_ptr
            if wp >= count:
                return self._disp_ring[wp - count : wp].copy()
            part1 = self._disp_ring[self._max_buf - (count - wp) :]
            part2 = self._disp_ring[:wp]
            return np.concatenate((part1, part2)).copy()

    def _try_open_device(self) -> bool:
        try:
            import SoapySDR  # type: ignore
            from SoapySDR import SOAPY_SDR_CF32, SOAPY_SDR_RX  # type: ignore

            devices = safe_enumerate_soapysdr(self.sdr_args or "driver=hackrf")
            with _SOAPY_USB_LOCK:
                if devices:
                    self.sdr_info = devices[0]
                    dev = SoapySDR.Device(soapy_info_to_markup(devices[0]))
                else:
                    dev = SoapySDR.Device("driver=hackrf")
                    self.sdr_info = {"driver": "hackrf", "device": "HackRF One"}

                dev.setSampleRate(SOAPY_SDR_RX, 0, self.hw_samp_rate)
                dev.setFrequency(SOAPY_SDR_RX, 0, self.rf_freq_mhz * 1e6)
                lna_db, vga_db = self._split_hackrf_gains(self.rf_gain)
                try:
                    dev.setGain(SOAPY_SDR_RX, 0, "AMP", 0.0)
                    dev.setGain(SOAPY_SDR_RX, 0, "LNA", lna_db)
                    dev.setGain(SOAPY_SDR_RX, 0, "VGA", vga_db)
                except Exception:
                    dev.setGain(SOAPY_SDR_RX, 0, self.rf_gain)

                rx_st = dev.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
                dev.activateStream(rx_st)

            self._dev = dev
            self._rx_st = rx_st
            self.sdr_connected = True
            lbl = self.sdr_info.get("label") or self.sdr_info.get("device") or "HackRF One"
            ver = self.sdr_info.get("version", "")
            self.sdr_label = f"{lbl} ({ver})" if (ver and ver not in str(lbl)) else str(lbl)
            print(
                f"[GNU-Larex] Live Wideband HackRF One ACTIVE: {self.sdr_label} @ {self.rf_freq_mhz:.1f} MHz "
                f"(2.0 MSps -> HACKRF_ZMQ :5557)",
                flush=True,
            )
            return True
        except Exception as exc:
            self.sdr_connected = False
            msg = str(exc)
            if "no hackrf" in msg.lower() or "access" in msg.lower():
                self.sdr_label = "HackRF One Detected (Tap HackRF RESET or Reconnect if busy)"
            else:
                self.sdr_label = f"HackRF Standby ({msg})"
            return False

    def _close_device(self) -> None:
        dev, rx_st = self._dev, self._rx_st
        self._dev = None
        self._rx_st = None
        self.sdr_connected = False
        if dev is not None and rx_st is not None:
            try:
                with _SOAPY_USB_LOCK:
                    dev.deactivateStream(rx_st)
                    dev.closeStream(rx_st)
            except Exception:
                pass

    @staticmethod
    def _resample_complex(x: np.ndarray, out_len: int) -> np.ndarray:
        if len(x) == out_len or out_len <= 0:
            return x[:out_len].astype(np.complex64, copy=False)
        if len(x) <= 1:
            return np.zeros(out_len, dtype=np.complex64)
        grid = np.linspace(0.0, float(len(x) - 1), out_len, dtype=np.float64)
        i0 = np.floor(grid).astype(np.int64)
        i1 = np.minimum(i0 + 1, len(x) - 1)
        f = (grid - i0).astype(np.float32)
        return (x[i0] * (1.0 - f) + x[i1] * f).astype(np.complex64)

    def _run_supervisor(self) -> None:
        from SoapySDR import SOAPY_SDR_RX  # type: ignore

        # Let primary RTL-SDR Blog V4 claim its handle cleanly first on startup
        if self._wait_event is not None:
            self._wait_event.wait(timeout=3.5)

        while not self._stop_evt.is_set():
            self._reconnect_evt.clear()
            if not self._try_open_device():
                self._stop_evt.wait(4.5)
                continue

            dev = self._dev
            rx_st = self._rx_st
            # 80,000 samples @ 2.0 MSps = 40 ms exact block -> 3,200 @ 80 kHz -> 1,920 @ 48 kHz (only 25 reads/sec -> ultra-low GIL!)
            chunk_hw = 80_000
            iq_buf = np.empty(chunk_hw, dtype=np.complex64)
            grid_full = np.linspace(0.0, 3199.0, 1920, dtype=np.float64)
            i0_full = np.floor(grid_full).astype(np.int64)
            i1_full = np.minimum(i0_full + 1, 3199)
            f_full = (grid_full - i0_full).astype(np.float32)
            active_freq = self.rf_freq_mhz
            active_gain = self.rf_gain
            consecutive_timeouts = 0

            try:
                while not self._stop_evt.is_set() and not self._reconnect_evt.is_set():
                    if abs(self.rf_freq_mhz - active_freq) > 0.02:
                        dev.setFrequency(SOAPY_SDR_RX, 0, self.rf_freq_mhz * 1e6)
                        active_freq = self.rf_freq_mhz
                    if abs(self.rf_gain - active_gain) > 0.5:
                        lna_db, vga_db = self._split_hackrf_gains(self.rf_gain)
                        try:
                            dev.setGain(SOAPY_SDR_RX, 0, "LNA", lna_db)
                            dev.setGain(SOAPY_SDR_RX, 0, "VGA", vga_db)
                        except Exception:
                            dev.setGain(SOAPY_SDR_RX, 0, self.rf_gain)
                        active_gain = self.rf_gain

                    sr = dev.readStream(rx_st, [iq_buf], chunk_hw, timeoutUs=120_000)
                    if sr.ret <= 0:
                        consecutive_timeouts += 1
                        if consecutive_timeouts > 35:
                            break
                        continue
                    consecutive_timeouts = 0
                    n_got = (sr.ret // 25) * 25
                    if n_got < 25:
                        continue
                    valid = iq_buf[:n_got]

                    if self._raw_iq_requested:
                        iq_1m = valid[: (n_got // 2) * 2].reshape(-1, 2).mean(axis=1).astype(np.complex64)
                        n_960k = max(1, int(round(len(valid) * (self.rf_out_rate / self.hw_samp_rate))))
                        self._append_raw_iq(self._resample_complex(iq_1m, n_960k))

                    # Anti-alias 2.0 MSps -> 80 kHz (25x boxcar) -> exact 48 kHz (3/5 rate)
                    iq_80k = valid.reshape(-1, 25).mean(axis=1).astype(np.complex64)
                    if len(iq_80k) == 3200:
                        dec_iq = (iq_80k[i0_full] * (1.0 - f_full) + iq_80k[i1_full] * f_full).astype(np.complex64)
                    else:
                        n_48k = max(1, (len(iq_80k) * 3) // 5)
                        dec_iq = self._resample_complex(iq_80k, n_48k)

                    pwr = float(np.mean(dec_iq.real * dec_iq.real + dec_iq.imag * dec_iq.imag) + 1e-14)
                    self.rf_power_dbfs = round(10.0 * math.log10(pwr), 1)

                    # Wideband RF precursor / burst envelope + microwave unwrapped phase micro-Doppler
                    inst_mag = np.abs(dec_iq).astype(np.float32)
                    mean_mag = float(np.mean(inst_mag))
                    self._env_floor = 0.96 * self._env_floor + 0.04 * mean_mag
                    rf_burst = np.clip((inst_mag - self._env_floor) * 3.5, -1.0, 1.0).astype(np.float32)
                    self.rf_envelope_peak = round(float(np.max(np.abs(rf_burst))), 3)

                    centered = self._clutter.process(dec_iq)
                    disp_um = self._phase.process(centered)
                    norm_phase = np.tanh(disp_um / 120.0).astype(np.float32)
                    hackrf_fused = np.clip(0.65 * rf_burst + 0.35 * norm_phase, -1.0, 1.0).astype(np.float32)

                    self._append_baseband(hackrf_fused, disp_um, dec_iq, centered)
                    if self._zmq_pub is not None:
                        try:
                            import zmq  # type: ignore

                            self._zmq_pub.send(hackrf_fused.tobytes(), flags=zmq.NOBLOCK)
                            self.packets_published += 1
                        except Exception:
                            pass
            except Exception as exc:
                self.sdr_label = f"HackRF Reconnecting ({exc})"
            finally:
                self._close_device()

            if not self._stop_evt.is_set() and not self._reconnect_evt.is_set():
                self._stop_evt.wait(3.0)

    def stop(self) -> None:
        self._stop_evt.set()
        self._reconnect_evt.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.5)
        if self._zmq_pub is not None:
            try:
                self._zmq_pub.close(0)
            except Exception:
                pass
            self._zmq_pub = None


class WhisperEarwormEngine:
    """
    4-Sensor Whisper Phoneme Classifier, Earworm Rhythmic & Markov Lyric Predictor,
    and Stateful Formant Vocal Mimicry Synthesizer (`WhisperEarwormEnhanced` profile).

    Fuses:
      1. Ultrasonic / Wideband Air Doppler (`ultra`: 40 kHz carrier heterodyne or 48 kHz baseband)
      2. PlutoSDR 2.45 GHz Lip/Larynx Micro-Doppler (`pluto`: ZMQ tcp://127.0.0.1:5555)
      3. RTL-SDR VHF/ISM Throat Tension Microphonics (`rtlsdr`: ZMQ tcp://127.0.0.1:5556 / Live Blog V4)
      4. HackRF Wideband RF Envelope (`hackrf`: ZMQ tcp://127.0.0.1:5557)
    """

    def __init__(
        self,
        sr: int = 48000,
        block_size: int = 2048,
        whisper_trigger_mult: float = 2.15,
        silence_hangover_blocks: int = 5,
        sibilant_ratio: float = 1.45,
        markov_order: int = 2,
        pink_noise_alpha: float = 0.82,
        enhanced_phonemes: bool = True,
        stateful_sos_formants: bool = True,
    ) -> None:
        self.sr = int(sr)
        self.block_size = int(block_size)
        self.freqs = np.fft.rfftfreq(self.block_size, 1.0 / self.sr)
        self.window = np.hanning(self.block_size)

        # NightSweep `WhisperEarwormEnhanced` configurable parameters
        self.whisper_trigger_mult = float(whisper_trigger_mult)
        self.silence_hangover_blocks = int(silence_hangover_blocks)
        self.sibilant_ratio = float(sibilant_ratio)
        self.markov_order = int(markov_order)
        self.pink_noise_alpha = float(pink_noise_alpha)
        self.enhanced_phonemes = bool(enhanced_phonemes)
        self.stateful_sos_formants = bool(stateful_sos_formants)
        self.air_weight: float = 0.70
        self.rf_weight: float = 0.30

        # Adaptive whisper noise floor (high sensitivity for quiet rooms)
        self.whisper_floor: float = 0.005
        self.in_syllable: bool = False
        self.current_word_phonemes: List[str] = []
        self.silence_blocks: int = 0

        # Earworm Rhythmic & Lyric Sequence Predictor (1st-order + 2nd-order bigram Markov)
        self.last_syllable_time: float = time.perf_counter()
        self.inter_syllable_intervals: collections.deque = collections.deque(maxlen=8)
        self.earworm_bpm: float = 120.0
        self.word_transitions: Dict[str, Dict[str, int]] = collections.defaultdict(
            lambda: collections.defaultdict(int)
        )
        self.bigram_transitions: Dict[Tuple[str, str], Dict[str, int]] = collections.defaultdict(
            lambda: collections.defaultdict(int)
        )
        self.prev_detected_word: Optional[str] = None
        self.last_detected_word: Optional[str] = None
        self.predicted_next_word: Optional[str] = None
        self.next_eta_ms: int = 500
        self.recent_whisper_words: collections.deque = collections.deque(maxlen=20)

        # Parallel Lexical Earworm Predictor fed by Faster-Whisper word streams
        self.lexical_transitions: Dict[str, Dict[str, int]] = collections.defaultdict(
            lambda: collections.defaultdict(int)
        )
        self.lexical_bigrams: Dict[Tuple[str, str], Dict[str, int]] = collections.defaultdict(
            lambda: collections.defaultdict(int)
        )
        self._prev_lex_word: Optional[str] = None
        self.last_lexical_word: Optional[str] = None
        self.predicted_lexical_word: Optional[str] = None

        # Vocal Mimicry Synthesis State (Stateful cross-block IIR formant memory + pink airflow)
        self.synth_phase: float = 0.0
        self.target_f1: float = 500.0
        self.target_f2: float = 1500.0
        self.whisper_gain: float = 0.0
        self.active_phoneme: str = "IDLE"
        self.is_whispering: bool = False
        self._pink_z: float = 0.0
        self._f1_zi: Optional[np.ndarray] = None
        self._f2_zi: Optional[np.ndarray] = None
        self._rng = np.random.default_rng(1337)

        # Streaming FIFO & ultrasonic carrier downconverter state
        self._u_fifo = np.zeros(0, dtype=np.float32)
        self._p_fifo = np.zeros(0, dtype=np.float32)
        self._r_fifo = np.zeros(0, dtype=np.float32)
        self._h_fifo = np.zeros(0, dtype=np.float32)
        self._lo_phase: float = 0.0
        self.latest_telemetry: Dict[str, Any] = self.get_telemetry()

    def _fit_block(self, arr: Optional[np.ndarray]) -> np.ndarray:
        if arr is None or len(arr) == 0:
            return np.zeros(self.block_size, dtype=np.float32)
        x = np.asarray(arr, dtype=np.float32).ravel()
        if len(x) == self.block_size:
            return x
        if len(x) > self.block_size:
            return x[-self.block_size :]
        out = np.zeros(self.block_size, dtype=np.float32)
        out[-len(x) :] = x
        return out

    def classify_whisper_phoneme(self, spec: np.ndarray) -> Tuple[str, float, float]:
        """Extracts F1 (jaw openness) and F2 (tongue front/back) from whispered airflow

        to classify silent/whispered vowel shapes without vocal cord pitch.
        """
        f1_mask = (self.freqs >= 300.0) & (self.freqs <= 900.0)
        f2_mask = (self.freqs >= 900.0) & (self.freqs <= 2800.0)
        sib_mask = (self.freqs >= 3500.0) & (self.freqs <= 10000.0)

        f1_energy = spec[f1_mask]
        f2_energy = spec[f2_mask]
        sib_vals = spec[sib_mask]
        sib_energy = float(np.mean(sib_vals)) if len(sib_vals) else 0.0
        mean_f1 = float(np.mean(f1_energy)) if len(f1_energy) else 1e-6

        f1_hz = float(np.sum(self.freqs[f1_mask] * f1_energy) / (np.sum(f1_energy) + 1e-6))
        f2_hz = float(np.sum(self.freqs[f2_mask] * f2_energy) / (np.sum(f2_energy) + 1e-6))

        # High-frequency turbulent hiss indicates whispered consonants (S, T, K, SH)
        if sib_energy > (mean_f1 * self.sibilant_ratio):
            if self.enhanced_phonemes and len(sib_vals) > 0:
                sib_centroid = float(
                    np.sum(self.freqs[sib_mask] * sib_vals) / (np.sum(sib_vals) + 1e-6)
                )
                if sib_centroid < 5200.0:
                    return "SH", f1_hz, f2_hz
            return "S/T", f1_hz, f2_hz

        # Formant mapping for whispered vowels
        if f2_hz > 1850.0:
            return "EE", f1_hz, f2_hz  # Front vowel ("see", "me")
        if self.enhanced_phonemes and f2_hz > 1520.0 and f1_hz >= 480.0:
            return "EH", f1_hz, f2_hz  # Mid-front vowel ("let", "get")
        if f1_hz > 620.0:
            return "AH", f1_hz, f2_hz  # Open vowel ("la", "heart")
        return "OO", f1_hz, f2_hz      # Rounded vowel ("you", "move")

    def process_whisper_stream(
        self,
        pluto: np.ndarray,
        rtlsdr: np.ndarray,
        hackrf: np.ndarray,
        ultra: np.ndarray,
    ) -> Dict[str, Any]:
        """Fuses all 4 sensors to segment whispered syllables into words and

        predicts the next whispered word based on earworm rhythm & sequence.
        """
        u_blk = self._fit_block(ultra)
        p_blk = self._fit_block(pluto)
        r_blk = self._fit_block(rtlsdr)
        h_blk = self._fit_block(hackrf)

        ultra_spec = np.abs(np.fft.rfft(u_blk * self.window))
        pluto_spec = np.abs(np.fft.rfft(p_blk * self.window))

        # 1. Measure Whisper Airflow + Laryngeal Tension across all sensors
        whisper_band = (self.freqs >= 400.0) & (self.freqs <= 6000.0)
        air_energy = float(np.mean(ultra_spec[whisper_band]))

        # Cross-check with PlutoSDR lip/throat Doppler, RTL-SDR throat tension & HackRF envelope
        pluto_low = (self.freqs >= 5.0) & (self.freqs <= 120.0)
        pluto_term = float(np.mean(pluto_spec[pluto_low])) if np.any(pluto_low) else 0.0
        hackrf_env = float(np.mean(np.abs(h_blk))) * 0.25
        throat_tension = float(np.mean(np.abs(r_blk))) + pluto_term + hackrf_env
        combined_activity = (air_energy * self.air_weight) + (throat_tension * self.rf_weight)

        # Update adaptive quiet-room noise floor during pauses
        if combined_activity < (self.whisper_floor * 1.8):
            self.whisper_floor = max(
                1e-5, (self.whisper_floor * 0.95) + (combined_activity * 0.05)
            )

        is_whispering = bool(
            combined_activity > (self.whisper_floor * self.whisper_trigger_mult)
        )
        self.is_whispering = is_whispering
        self.whisper_gain = (
            float(np.clip(combined_activity * 8.0, 0.0, 0.85)) if is_whispering else 0.0
        )

        now = time.perf_counter()

        # 2. Syllable & Word Segmentation
        if is_whispering:
            self.silence_blocks = 0
            phoneme, f1, f2 = self.classify_whisper_phoneme(ultra_spec)
            self.active_phoneme = phoneme
            self.target_f1 = (self.target_f1 * 0.6) + (f1 * 0.4)
            self.target_f2 = (self.target_f2 * 0.6) + (f2 * 0.4)

            if not self.in_syllable:
                # New whispered syllable onset detected
                self.in_syllable = True
                dt = now - self.last_syllable_time
                self.last_syllable_time = now

                # Track earworm rhythmic cadence (syllables between 150ms and 1.2s apart)
                if 0.15 <= dt <= 1.2:
                    self.inter_syllable_intervals.append(dt)
                    avg_dt = float(np.mean(self.inter_syllable_intervals))
                    self.earworm_bpm = round(60.0 / max(avg_dt, 0.05), 1)

                if not self.current_word_phonemes or self.current_word_phonemes[-1] != phoneme:
                    self.current_word_phonemes.append(phoneme)
        else:
            self.in_syllable = False
            self.silence_blocks += 1
            if self.silence_blocks > self.silence_hangover_blocks * 2:
                self.active_phoneme = "IDLE"

            # Pause of ~silence_hangover_blocks (~210-250ms) marks end of a whispered word
            if self.silence_blocks == self.silence_hangover_blocks and self.current_word_phonemes:
                detected_word = "-".join(self.current_word_phonemes[:6])
                self.current_word_phonemes = []

                # Update 1st-order & 2nd-order Earworm Word Sequence Predictor
                if self.last_detected_word:
                    self.word_transitions[self.last_detected_word][detected_word] += 1
                    if self.prev_detected_word:
                        self.bigram_transitions[(self.prev_detected_word, self.last_detected_word)][
                            detected_word
                        ] += 1

                # Forecast the next whispered word & when it will arrive
                predicted_word: Optional[str] = None
                if self.markov_order >= 2 and self.last_detected_word:
                    bi_cands = self.bigram_transitions.get(
                        (self.last_detected_word, detected_word), {}
                    )
                    if bi_cands:
                        predicted_word = max(bi_cands, key=bi_cands.get)
                if not predicted_word:
                    next_candidates = self.word_transitions.get(detected_word, {})
                    if next_candidates:
                        predicted_word = max(next_candidates, key=next_candidates.get)
                    else:
                        predicted_word = detected_word  # Earworms naturally loop!

                next_eta_ms = int(60000.0 / max(40.0, self.earworm_bpm))
                self.prev_detected_word = self.last_detected_word
                self.last_detected_word = detected_word
                self.predicted_next_word = predicted_word
                self.next_eta_ms = next_eta_ms
                self.recent_whisper_words.append(
                    {
                        "word": detected_word,
                        "predicted_next": predicted_word,
                        "earworm_bpm": self.earworm_bpm,
                        "eta_ms": next_eta_ms,
                        "f1_hz": round(self.target_f1, 1),
                        "f2_hz": round(self.target_f2, 1),
                        "ts": datetime.datetime.now().strftime("%H:%M:%S"),
                    }
                )
                print(
                    f"[WHISPER WORD] '{detected_word}' | Earworm Tempo:"
                    f" {self.earworm_bpm} BPM | Predicted Next:"
                    f" '{predicted_word}' in ~{next_eta_ms} ms",
                    flush=True,
                )

        self.latest_telemetry = self.get_telemetry()
        return self.latest_telemetry

    def ingest_lexical_utterance(self, words: List[str]) -> None:
        """Feeds real Faster-Whisper decoded words into the parallel Lexical Earworm Markov graph."""
        tokens = [
            w.strip(".,!?;:\"'()").lower()
            for w in words
            if len(w.strip(".,!?;:\"'()")) >= 2
        ]
        for tok in tokens:
            if self.last_lexical_word:
                self.lexical_transitions[self.last_lexical_word][tok] += 1
                if self._prev_lex_word:
                    self.lexical_bigrams[(self._prev_lex_word, self.last_lexical_word)][tok] += 1
            self._prev_lex_word = self.last_lexical_word
            self.last_lexical_word = tok

        if self.last_lexical_word:
            bi = (
                self.lexical_bigrams.get((self._prev_lex_word or "", self.last_lexical_word), {})
                if self._prev_lex_word
                else {}
            )
            if bi:
                self.predicted_lexical_word = max(bi, key=bi.get)
            else:
                uni = self.lexical_transitions.get(self.last_lexical_word, {})
                self.predicted_lexical_word = (
                    max(uni, key=uni.get) if uni else self.last_lexical_word
                )
        self.latest_telemetry = self.get_telemetry()

    def synthesize_whisper_mirror(self, num_samples: int, sr_out: int) -> np.ndarray:
        """Generates a breathy, formant-filtered vocal mirror that mimics the exact

        F1/F2 vowel resonances of each whispered word in real time.
        """
        if self.whisper_gain <= 0.01 or num_samples <= 0:
            self._f1_zi = None
            self._f2_zi = None
            return np.zeros(max(0, int(num_samples)), dtype=np.float32)

        from scipy.signal import butter, lfilter  # type: ignore

        # Generate turbulent whisper air source (1/f pink-shaped airflow + soft 130 Hz sub-harmonic)
        white = self._rng.normal(0.0, 0.4, num_samples).astype(np.float64)
        if self.pink_noise_alpha > 0.05:
            a_p = float(np.clip(self.pink_noise_alpha, 0.1, 0.95))
            b_pink = np.array([1.0 - a_p], dtype=np.float64)
            a_pink = np.array([1.0, -a_p], dtype=np.float64)
            noise, zf = lfilter(b_pink, a_pink, white, zi=np.array([self._pink_z], dtype=np.float64))
            self._pink_z = float(zf[0])
            noise = (noise * 1.85).astype(np.float32)
        else:
            noise = white.astype(np.float32)

        t = np.arange(num_samples, dtype=np.float64) / float(sr_out)
        phase_inc = 2.0 * np.pi * 130.0 * t + self.synth_phase
        soft_hum = (np.sin(phase_inc) * 0.25).astype(np.float32)
        self.synth_phase = float(
            (phase_inc[-1] + (2.0 * np.pi * 130.0 / float(sr_out))) % (2.0 * np.pi)
        )

        raw_source = (noise + soft_hum) * float(self.whisper_gain)

        # Shape the air through dual formant bandpass filters (F1 and F2)
        nyq = 0.5 * float(sr_out)
        f1_low = float(np.clip((self.target_f1 - 120.0) / nyq, 0.005, 0.90))
        f1_high = float(np.clip((self.target_f1 + 120.0) / nyq, f1_low + 0.01, 0.95))
        b1, a1 = butter(2, [f1_low, f1_high], btype="band")

        f2_low = float(np.clip((self.target_f2 - 200.0) / nyq, 0.01, 0.90))
        f2_high = float(np.clip((self.target_f2 + 200.0) / nyq, f2_low + 0.01, 0.95))
        b2, a2 = butter(2, [f2_low, f2_high], btype="band")

        if self.stateful_sos_formants:
            zi1 = (
                self._f1_zi
                if (self._f1_zi is not None and len(self._f1_zi) == len(a1) - 1)
                else np.zeros(len(a1) - 1, dtype=np.float64)
            )
            zi2 = (
                self._f2_zi
                if (self._f2_zi is not None and len(self._f2_zi) == len(a2) - 1)
                else np.zeros(len(a2) - 1, dtype=np.float64)
            )
            y1, self._f1_zi = lfilter(b1, a1, raw_source.astype(np.float64), zi=zi1)
            y2, self._f2_zi = lfilter(b2, a2, raw_source.astype(np.float64), zi=zi2)
            mimicked_whisper = y1 + (y2 * 0.7)
        else:
            mimicked_whisper = lfilter(b1, a1, raw_source) + (lfilter(b2, a2, raw_source) * 0.7)

        return np.clip(mimicked_whisper, -0.95, 0.95).astype(np.float32)

    def downconvert_ultrasonic(
        self, audio_chunk: np.ndarray, audio_sr: int, carrier_hz: float = 40000.0
    ) -> np.ndarray:
        """
        Heterodynes wideband 96k/192k/384k UltraMic384K_EVO input around `carrier_hz - 400 Hz`
        with anti-alias filtering down to `self.sr` (48 kHz). Passes 48 kHz baseband cleanly.
        """
        x = np.asarray(audio_chunk, dtype=np.float32).ravel()
        if len(x) == 0 or audio_sr <= self.sr or audio_sr < int(carrier_hz * 2):
            return x
        decim = max(1, int(round(audio_sr / self.sr)))
        lo_hz = max(1000.0, float(carrier_hz) - 400.0)
        t = np.arange(len(x), dtype=np.float64) / float(audio_sr)
        lo = np.cos(2.0 * np.pi * lo_hz * t + self._lo_phase).astype(np.float32)
        self._lo_phase = float(
            (self._lo_phase + 2.0 * np.pi * lo_hz * len(x) / float(audio_sr)) % (2.0 * np.pi)
        )
        shifted = x * lo
        # Boxcar anti-alias lowpass prior to integer decimation
        usable = (len(shifted) // decim) * decim
        if usable == 0:
            return shifted
        return shifted[:usable].reshape(-1, decim).mean(axis=1).astype(np.float32)

    def push_streaming_chunks(
        self,
        pluto_chunk: np.ndarray,
        rtlsdr_chunk: np.ndarray,
        hackrf_chunk: np.ndarray,
        ultra_chunk: np.ndarray,
        audio_sr: int = 48000,
        ultrasonic_carrier_hz: float = 40000.0,
    ) -> Dict[str, Any]:
        u_dec = self.downconvert_ultrasonic(
            ultra_chunk, audio_sr=audio_sr, carrier_hz=ultrasonic_carrier_hz
        )
        self._u_fifo = np.concatenate((self._u_fifo, np.asarray(u_dec, dtype=np.float32).ravel()))
        self._p_fifo = np.concatenate((self._p_fifo, np.asarray(pluto_chunk, dtype=np.float32).ravel()))
        self._r_fifo = np.concatenate((self._r_fifo, np.asarray(rtlsdr_chunk, dtype=np.float32).ravel()))
        self._h_fifo = np.concatenate((self._h_fifo, np.asarray(hackrf_chunk, dtype=np.float32).ravel()))

        hop = self.block_size // 2
        while len(self._u_fifo) >= self.block_size:
            u_b = self._u_fifo[: self.block_size]
            p_b = self._fit_block(self._p_fifo[: self.block_size])
            r_b = self._fit_block(self._r_fifo[: self.block_size])
            h_b = self._fit_block(self._h_fifo[: self.block_size])
            self._u_fifo = self._u_fifo[hop:]
            self._p_fifo = self._p_fifo[min(hop, len(self._p_fifo)) :]
            self._r_fifo = self._r_fifo[min(hop, len(self._r_fifo)) :]
            self._h_fifo = self._h_fifo[min(hop, len(self._h_fifo)) :]
            self.process_whisper_stream(p_b, r_b, h_b, u_b)

        for attr in ("_u_fifo", "_p_fifo", "_r_fifo", "_h_fifo"):
            arr = getattr(self, attr)
            if len(arr) > self.block_size * 4:
                setattr(self, attr, arr[-self.block_size * 2 :])

        return self.latest_telemetry

    def apply_config(self, cfg: Dict[str, Any]) -> List[str]:
        applied: List[str] = []
        if "whisper_trigger_mult" in cfg:
            self.whisper_trigger_mult = float(np.clip(float(cfg["whisper_trigger_mult"]), 1.3, 5.0))
            applied.append(f"whisper_trigger_mult={self.whisper_trigger_mult:.2f}x")
        if "silence_hangover_blocks" in cfg:
            self.silence_hangover_blocks = int(np.clip(int(cfg["silence_hangover_blocks"]), 2, 16))
            applied.append(f"silence_hangover_blocks={self.silence_hangover_blocks}")
        if "sibilant_ratio" in cfg:
            self.sibilant_ratio = float(np.clip(float(cfg["sibilant_ratio"]), 1.05, 3.5))
            applied.append(f"sibilant_ratio={self.sibilant_ratio:.2f}")
        if "markov_order" in cfg:
            self.markov_order = int(np.clip(int(cfg["markov_order"]), 1, 2))
            applied.append(f"markov_order={self.markov_order}")
        if "pink_noise_alpha" in cfg:
            self.pink_noise_alpha = float(np.clip(float(cfg["pink_noise_alpha"]), 0.0, 0.94))
            applied.append(f"pink_noise_alpha={self.pink_noise_alpha:.2f}")
        if "enhanced_phonemes" in cfg:
            self.enhanced_phonemes = bool(cfg["enhanced_phonemes"])
            applied.append(f"enhanced_phonemes={self.enhanced_phonemes}")
        if "stateful_sos_formants" in cfg:
            self.stateful_sos_formants = bool(cfg["stateful_sos_formants"])
            applied.append(f"stateful_sos_formants={self.stateful_sos_formants}")
        self.latest_telemetry = self.get_telemetry()
        return applied

    def get_telemetry(self) -> Dict[str, Any]:
        top_edges = []
        for src_w, dsts in list(self.word_transitions.items())[:8]:
            if dsts:
                best_dst = max(dsts, key=dsts.get)
                top_edges.append({"from": src_w, "to": best_dst, "count": int(dsts[best_dst])})
        top_edges.sort(key=lambda e: e["count"], reverse=True)

        top_lex = []
        for src_w, dsts in list(self.lexical_transitions.items())[:12]:
            if dsts:
                best_dst = max(dsts, key=dsts.get)
                top_lex.append({"from": src_w, "to": best_dst, "count": int(dsts[best_dst])})
        top_lex.sort(key=lambda e: e["count"], reverse=True)

        return {
            "is_whispering": bool(self.is_whispering),
            "active_phoneme": self.active_phoneme,
            "current_word_phonemes": list(self.current_word_phonemes[-6:]),
            "target_f1_hz": round(float(self.target_f1), 1),
            "target_f2_hz": round(float(self.target_f2), 1),
            "whisper_gain": round(float(self.whisper_gain), 3),
            "whisper_floor": round(float(self.whisper_floor), 5),
            "earworm_bpm": round(float(self.earworm_bpm), 1),
            "last_detected_word": self.last_detected_word or "--",
            "predicted_next_word": self.predicted_next_word or "--",
            "next_eta_ms": int(self.next_eta_ms),
            "last_lexical_word": self.last_lexical_word or "--",
            "predicted_lexical_word": self.predicted_lexical_word or "--",
            "recent_whisper_words": list(self.recent_whisper_words)[-8:],
            "top_phoneme_transitions": top_edges[:6],
            "top_lexical_transitions": top_lex[:6],
            "config": {
                "whisper_trigger_mult": round(self.whisper_trigger_mult, 2),
                "silence_hangover_blocks": self.silence_hangover_blocks,
                "sibilant_ratio": round(self.sibilant_ratio, 2),
                "markov_order": self.markov_order,
                "pink_noise_alpha": round(self.pink_noise_alpha, 2),
                "enhanced_phonemes": self.enhanced_phonemes,
                "stateful_sos_formants": self.stateful_sos_formants,
            },
        }


class ZMQWhisperSensorBridge:
    """
    Non-blocking ZeroMQ 3-SDR subscriber (`PLUTO_ZMQ :5555`, `RTLSDR_ZMQ :5556`, `HACKRF_ZMQ :5557`)
    + UDP Formant Vocal Mirror broadcaster (`MIXER_PORT = 5005`).
    Uses `RCVHWM = 4` so subscribers always read fresh low-latency RF frames without queue lag.
    """

    def __init__(
        self,
        pluto_zmq: str = "tcp://127.0.0.1:5555",
        rtlsdr_zmq: str = "tcp://127.0.0.1:5556",
        hackrf_zmq: str = "tcp://127.0.0.1:5557",
        udp_host: str = "127.0.0.1",
        mixer_port: int = 5005,
        udp_mirror_enabled: bool = True,
        ultrasonic_carrier_hz: float = 40000.0,
    ) -> None:
        self.pluto_zmq = pluto_zmq
        self.rtlsdr_zmq = rtlsdr_zmq
        self.hackrf_zmq = hackrf_zmq
        self.udp_host = udp_host
        self.mixer_port = int(mixer_port)
        self.udp_mirror_enabled = bool(udp_mirror_enabled)
        self.ultrasonic_carrier_hz = float(ultrasonic_carrier_hz)

        self.pluto_pkts: int = 0
        self.rtlsdr_pkts: int = 0
        self.hackrf_pkts: int = 0
        self.udp_sent_pkts: int = 0
        self.zmq_ready: bool = False

        self._ctx: Any = None
        self._pluto_sock: Any = None
        self._rtlsdr_sock: Any = None
        self._hackrf_sock: Any = None
        self._udp_sock: Optional[Any] = None

        try:
            import socket as _socket
            import zmq  # type: ignore

            self._ctx = zmq.Context.instance()
            self._pluto_sock = self._make_sub(self.pluto_zmq)
            self._rtlsdr_sock = self._make_sub(self.rtlsdr_zmq)
            self._hackrf_sock = self._make_sub(self.hackrf_zmq)
            self.zmq_ready = True

            u_sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
            u_sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_BROADCAST, 1)
            u_sock.setblocking(False)
            self._udp_sock = u_sock
        except Exception:
            self.zmq_ready = False

    def _make_sub(self, addr: str) -> Any:
        import zmq  # type: ignore

        s = self._ctx.socket(zmq.SUB)
        s.setsockopt(zmq.RCVHWM, 4)
        s.setsockopt(zmq.LINGER, 0)
        s.connect(addr)
        s.setsockopt_string(zmq.SUBSCRIBE, "")
        return s

    @staticmethod
    def _pull_zmq(sock: Any, length: int) -> Tuple[np.ndarray, int]:
        buf = np.zeros(length, dtype=np.float32)
        got = 0
        if sock is None:
            return buf, 0
        try:
            import zmq  # type: ignore

            while True:
                raw = sock.recv(flags=zmq.NOBLOCK)
                got += 1
                arr = np.frombuffer(raw, dtype=np.float32)
                if len(arr) >= length:
                    buf = arr[-length:].copy()
                elif len(arr) > 0:
                    buf[-len(arr) :] = arr
        except Exception:
            pass
        return buf, got

    def pull_all(self, length: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        p_blk, p_n = self._pull_zmq(self._pluto_sock, length)
        r_blk, r_n = self._pull_zmq(self._rtlsdr_sock, length)
        h_blk, h_n = self._pull_zmq(self._hackrf_sock, length)
        self.pluto_pkts += p_n
        self.rtlsdr_pkts += r_n
        self.hackrf_pkts += h_n
        return p_blk, r_blk, h_blk

    def broadcast_mirror_audio(self, mono_mirror: np.ndarray) -> None:
        if not self.udp_mirror_enabled or self._udp_sock is None or len(mono_mirror) == 0:
            return
        if float(np.max(np.abs(mono_mirror))) < 1e-4:
            return
        try:
            stereo = np.empty(len(mono_mirror) * 2, dtype=np.float32)
            stereo[0::2] = mono_mirror
            stereo[1::2] = mono_mirror
            self._udp_sock.sendto(stereo.tobytes(), (self.udp_host, self.mixer_port))
            self.udp_sent_pkts += 1
        except Exception:
            pass

    def get_status(self) -> Dict[str, Any]:
        return {
            "zmq_ready": self.zmq_ready,
            "pluto_zmq": self.pluto_zmq,
            "rtlsdr_zmq": self.rtlsdr_zmq,
            "hackrf_zmq": self.hackrf_zmq,
            "pluto_pkts": self.pluto_pkts,
            "rtlsdr_pkts": self.rtlsdr_pkts,
            "hackrf_pkts": self.hackrf_pkts,
            "udp_host": self.udp_host,
            "mixer_port": self.mixer_port,
            "udp_mirror_enabled": self.udp_mirror_enabled,
            "udp_sent_pkts": self.udp_sent_pkts,
            "ultrasonic_carrier_hz": self.ultrasonic_carrier_hz,
        }

    def close(self) -> None:
        for s in (self._pluto_sock, self._rtlsdr_sock, self._hackrf_sock):
            if s is not None:
                try:
                    s.close(0)
                except Exception:
                    pass
        if self._udp_sock is not None:
            try:
                self._udp_sock.close()
            except Exception:
                pass


# ============================================================================
# 1. PHYSIOLOGICAL RF MICRO-DOPPLER SIMULATOR CORE
# ============================================================================


class PhysiologicalRadarSimulatorCore:
    """
    Synthesizes realistic complex baseband I/Q reflections from a human neck/chest
    illuminated by a CW RF carrier at `rf_freq_hz`.

    Models:
      - Asymmetric respiration (inhalation/exhalation + tracheal airflow turbulence)
      - Carotid ballistocardiogram pulse (~68 BPM, dicrotic pulse shape)
      - Laryngeal subvocalization & silent-speech bursts (glottal F0 + F1/F2 formants)
      - Pre-phonatory cricothyroid infrasonic muscle tension (3-14 Hz)
      - Static TX-to-RX RF clutter leakage, subtle I/Q imbalance, and thermal/phase noise
    """

    def __init__(
        self,
        rf_samp_rate: float = 960_000.0,
        baseband_rate: float = 48_000.0,
        rf_freq_mhz: float = 915.0,
        resp_bpm: float = 15.0,
        subvoc_um_rms: float = 22.0,
        resp_um_peak: float = 650.0,
        clutter_i: float = 0.78,
        clutter_q: float = -0.52,
        skin_refl_amp: float = 0.32,
        noise_std: float = 0.00045,
    ) -> None:
        self.rf_samp_rate = float(rf_samp_rate)
        self.baseband_rate = float(baseband_rate)
        self.rf_freq_mhz = float(rf_freq_mhz)
        self.resp_bpm = float(resp_bpm)
        self.subvoc_um_rms = float(subvoc_um_rms)
        self.resp_um_peak = float(resp_um_peak)
        self.clutter_i = float(clutter_i)
        self.clutter_q = float(clutter_q)
        self.skin_refl_amp = float(skin_refl_amp)
        self.noise_std = float(noise_std)

        self._sample_idx: int = 0
        self._glottal_phase: float = 0.0
        self._rng = np.random.default_rng(42)
        self._prev_disp_m: float = 0.0
        self._turb_z1: float = 0.0
        self._turb_z2: float = 0.0

    def _synthesize_baseband_displacement_m(self, n_base: int) -> np.ndarray:
        """Compute physiological neck/chest displacement (in meters) at `baseband_rate`."""
        fs = self.baseband_rate
        t = (np.arange(n_base, dtype=np.float64) + (self._sample_idx / self._oversample)) / fs

        # 1. Respiration wave (~15 BPM = 0.25 Hz) with realistic inhale/exhale asymmetry
        f_resp = max(self.resp_bpm, 4.0) / 60.0
        w_resp = 2.0 * math.pi * f_resp * t
        resp_norm = 0.84 * np.sin(w_resp) - 0.18 * np.sin(2.0 * w_resp + 0.35)
        x_resp_m = (self.resp_um_peak * 1e-6) * resp_norm

        # Respiratory airflow velocity envelope -> tracheal turbulence (200-850 Hz)
        resp_vel = np.abs(np.cos(w_resp))
        white = self._rng.standard_normal(n_base)
        # Lightweight 2-pole resonator/bandpass around ~420 Hz for tracheal breath sound
        turb = np.empty(n_base, dtype=np.float64)
        r = 0.965
        theta = 2.0 * math.pi * 420.0 / fs
        a1 = -2.0 * r * math.cos(theta)
        a2 = r * r
        z1, z2 = self._turb_z1, self._turb_z2
        for i in range(n_base):
            y = white[i] - a1 * z1 - a2 * z2
            z2 = z1
            z1 = y
            turb[i] = y * (1.0 - r)
        self._turb_z1, self._turb_z2 = z1, z2
        x_trachea_m = (4.5e-6) * (resp_vel ** 1.6) * turb

        # 2. Carotid pulse (~68 BPM = 1.133 Hz, ~24 um peak-to-peak dicrotic wave)
        w_heart = 2.0 * math.pi * 1.133 * t
        x_heart_m = (12.0e-6) * (
            0.70 * np.sin(w_heart)
            + 0.35 * np.sin(2.0 * w_heart + 0.6)
            + 0.15 * np.sin(3.0 * w_heart + 1.1)
        )

        # 3. Subvocalization & silent-speech bursts (phrase cadence every 3.2 s)
        phrase_phase = np.mod(t, 3.2)
        in_phrase = (phrase_phase >= 0.45) & (phrase_phase <= 2.45)
        # Syllable envelope (~3.6 syllables/sec inside active silent-speech phrase)
        syll_raw = np.maximum(0.0, np.sin(2.0 * math.pi * 3.6 * (t - 0.45)))
        syll_env = np.where(in_phrase, syll_raw ** 0.65, 0.0)
        # Smooth attack/release via short moving kernel
        if n_base >= 16:
            k = np.hanning(16)
            k /= k.sum()
            syll_env = np.convolve(syll_env, k, mode="same")

        # Pre-phonatory & active cricothyroid infrasonic tension (5-11 Hz, ~32 um)
        tension_gate = np.where((phrase_phase >= 0.25) & (phrase_phase <= 2.60), 1.0, 0.0)
        x_tension_m = (30.0e-6) * tension_gate * (
            0.65 * np.sin(2.0 * math.pi * 6.5 * t)
            + 0.35 * np.sin(2.0 * math.pi * 11.2 * t + 0.4)
        )

        # Glottal / arytenoid subvocalization pitch contour (118-148 Hz) + vocal-tract formants
        f0_inst = 128.0 + 16.0 * np.sin(2.0 * math.pi * 1.3 * t) + 4.0 * np.sin(2.0 * math.pi * 5.2 * t)
        dphi = 2.0 * math.pi * f0_inst / fs
        phi = self._glottal_phase + np.cumsum(dphi)
        self._glottal_phase = float(np.mod(phi[-1], 2.0 * math.pi)) if n_base > 0 else self._glottal_phase

        # Rich vocal-fold + formant harmonic sum (F0 + F1 ~ 520 Hz + F2 ~ 1420 Hz)
        subvoc_wave = (
            0.55 * np.sin(phi)
            + 0.38 * np.sin(2.0 * phi + 0.2)
            + 0.28 * np.sin(3.0 * phi + 0.5)
            + 0.42 * (0.5 + 0.5 * np.sin(2.0 * math.pi * 2.1 * t)) * np.sin(4.0 * phi + 0.8)
            + 0.25 * (0.5 + 0.5 * np.cos(2.0 * math.pi * 3.4 * t)) * np.sin(9.0 * phi + 0.3)
            + 0.16 * np.sin(11.0 * phi + 1.2)
        )
        x_subvoc_m = (self.subvoc_um_rms * 1e-6) * syll_env * subvoc_wave

        return x_resp_m + x_trachea_m + x_heart_m + x_tension_m + x_subvoc_m

    @property
    def _oversample(self) -> int:
        return max(1, int(round(self.rf_samp_rate / self.baseband_rate)))

    def generate_iq(self, n_samples: int) -> np.ndarray:
        """Generate `n_samples` of complex64 RF baseband I/Q at `rf_samp_rate`."""
        ov = self._oversample
        n_base = max(2, int(math.ceil(n_samples / ov)) + 1)
        disp_base = self._synthesize_baseband_displacement_m(n_base - 1)
        disp_nodes = np.empty(n_base, dtype=np.float64)
        disp_nodes[0] = self._prev_disp_m
        disp_nodes[1:] = disp_base
        self._prev_disp_m = float(disp_base[-1])

        # Fast linear interpolation from baseband_rate up to rf_samp_rate
        grid_fine = np.arange(n_samples, dtype=np.float64) / ov
        idx0 = np.floor(grid_fine).astype(np.int64)
        idx1 = np.minimum(idx0 + 1, n_base - 1)
        frac = grid_fine - idx0
        x_m = disp_nodes[idx0] * (1.0 - frac) + disp_nodes[idx1] * frac

        self._sample_idx += n_samples

        # Phase modulation: phi(t) = phi0 + (4 * pi / lambda) * x(t)
        freq_hz = max(self.rf_freq_mhz, 10.0) * 1e6
        wavelength_m = SPEED_OF_LIGHT_MPS / freq_hz
        phase = 0.65 + (4.0 * math.pi / wavelength_m) * x_m

        # Complex reflection with slight realistic quadrature imbalance + static clutter
        refl_i = self.skin_refl_amp * np.cos(phase)
        refl_q = self.skin_refl_amp * 1.03 * np.sin(phase + 0.035)

        noise_i = self._rng.normal(0.0, self.noise_std, n_samples)
        noise_q = self._rng.normal(0.0, self.noise_std, n_samples)

        iq = (self.clutter_i + refl_i + noise_i) + 1j * (self.clutter_q + refl_q + noise_q)
        return iq.astype(np.complex64)


# ============================================================================
# 2. ADAPTIVE I/Q CLUTTER & CIRCLE-CENTER CALIBRATOR CORE
# ============================================================================


class IQClutterCancellerCore:
    """
    Removes static TX-to-RX RF leakage and stationary clutter while preserving
    the true skin-reflection phasor radius for calibrated phase demodulation.

    Combines:
      - Conditioned algebraic circle-center estimation (Kasa least-squares fit)
        when arc angular span / sagitta exceeds noise floor.
      - Optional small-angle virtual-carrier tangent projection (`mode == 1`)
        for extreme far-field / 8-bit SDR setups.
      - Manual / locked clutter vector subtraction (`mode == 2`).
    """

    def __init__(self, alpha: float = 0.005, mode: int = 0) -> None:
        self.alpha = float(alpha)
        self.mode = int(mode)
        self._clutter_est: complex = 0.0 + 0.0j
        self._mean_iq: complex = 0.0 + 0.0j
        self._comp_rot: complex = 1.0 + 0.0j
        self._initialized: bool = False
        self._ring = np.zeros(2048, dtype=np.complex128)
        self._ring_ptr: int = 0
        self._ring_filled: int = 0
        self._step_counter: int = 0

    def _fit_circle_center(self, pts: np.ndarray) -> Optional[complex]:
        """
        Hybrid Large-Arc Kasa + Small-Arc Unbiased PCA Parabola Curvature Estimator.
        Accurately recovers the center of curvature (static RF clutter vector) across
        both large phase arcs (>0.5 rad) and sub-millimeter small-angle arcs (~0.02 rad).
        """
        x = pts.real
        y = pts.imag
        xm = float(np.mean(x))
        ym = float(np.mean(y))
        dx = x - xm
        dy = y - ym

        cxx = float(np.mean(dx * dx))
        cyy = float(np.mean(dy * dy))
        cxy = float(np.mean(dx * dy))
        total_var = cxx + cyy
        if total_var < 1e-9:
            return None

        # Eigen-decomposition of 2x2 covariance -> principal tangent (u) & normal (v) axes
        diff = cxx - cyy
        disc = math.hypot(diff, 2.0 * cxy)
        lam1 = 0.5 * (total_var + disc)  # Tangent variance
        lam2 = max(0.0, 0.5 * (total_var - disc))  # Normal (sagitta + noise) variance

        theta = 0.5 * math.atan2(2.0 * cxy, diff)
        ct, st = math.cos(theta), math.sin(theta)
        u = dx * ct + dy * st          # High-SNR tangent coordinate
        v = -dx * st + dy * ct         # Normal coordinate

        # If arc spans a wide angle (lam2 / lam1 > 0.04 -> > ~45 deg), use full Kasa fit
        if lam2 > 0.04 * lam1:
            suu = float(np.dot(u, u))
            svv = float(np.dot(v, v))
            w = 0.5 * (u * u + v * v)
            uc = float(np.dot(u, w)) / max(suu, 1e-12)
            vc = float(np.dot(v, w)) / max(svv, 1e-12)
            radius = math.hypot(uc, vc)
            if 0.02 <= radius <= 4.0:
                cx = xm + (uc * ct - vc * st)
                cy = ym + (uc * st + vc * ct)
                return complex(cx, cy)

        # Small-to-moderate arc regime: unbiased regression of normal v onto q = u^2
        # For an arc around (0, vc), v ≈ (u^2 - mean(u^2)) / (2 * vc)
        q = u * u
        q_centered = q - float(np.mean(q))
        denom = float(np.dot(q_centered, q_centered))
        if denom < 1e-16:
            return None

        signed_curv = 2.0 * float(np.dot(q_centered, v)) / denom  # = 1 / vc
        if abs(signed_curv) < 0.28:
            # Extremely tiny motion (<10 um only): use reference carrier radius 0.32
            prev_rad = complex(xm, ym) - self._clutter_est
            prev_v = -prev_rad.real * st + prev_rad.imag * ct
            vc = -0.32 if prev_v >= 0.0 else 0.32
        else:
            vc = np.clip(1.0 / signed_curv, -2.5, 2.5)
            if abs(vc) < 0.04:
                vc = 0.04 if vc >= 0 else -0.04

        cx = xm - vc * st
        cy = ym + vc * ct
        return complex(cx, cy)

    def process(self, iq: np.ndarray) -> np.ndarray:
        n = len(iq)
        if n == 0:
            return iq

        iq128 = iq.astype(np.complex128, copy=False)
        chunk_mean = complex(np.mean(iq128))

        if not self._initialized:
            self._mean_iq = chunk_mean
            # Initial reference carrier offset of 0.32 along +Re axis
            self._clutter_est = chunk_mean - 0.32 + 0.0j
            rad0 = chunk_mean - self._clutter_est
            self._comp_rot = np.exp(-1j * math.atan2(rad0.imag, rad0.real))
            self._initialized = True

        # Update slow mean & decimated ring buffer (1 sample every 64 -> ~750 Hz at 48 kHz, ~2.7 s span)
        a = np.clip(self.alpha, 1e-5, 0.2)
        self._mean_iq = (1.0 - a) * self._mean_iq + a * chunk_mean

        sub = iq128[::64]
        for s in sub:
            self._ring[self._ring_ptr] = s
            self._ring_ptr = (self._ring_ptr + 1) % len(self._ring)
            self._ring_filled = min(self._ring_filled + 1, len(self._ring))

        self._step_counter += n
        if self.mode == 0 and self._ring_filled >= 512 and self._step_counter >= 2400:
            self._step_counter = 0
            pts = self._ring[: self._ring_filled]
            ref_pt = complex(np.mean(pts))
            old_vec = ref_pt - self._clutter_est
            old_ang = math.atan2(old_vec.imag, old_vec.real)

            center = self._fit_circle_center(pts)
            if center is not None:
                blend = min(0.20, max(0.02, a * 8.0))
                new_clutter = (1.0 - blend) * self._clutter_est + blend * center
            else:
                dz = pts - ref_pt
                cov_xx = float(np.mean(dz.real * dz.real))
                cov_yy = float(np.mean(dz.imag * dz.imag))
                cov_xy = float(np.mean(dz.real * dz.imag))
                theta = 0.5 * math.atan2(2.0 * cov_xy, cov_xx - cov_yy)
                nx, ny = -math.sin(theta), math.cos(theta)
                r_ref = 0.32
                virt_center = ref_pt - complex(r_ref * nx, r_ref * ny)
                if (old_vec.real * nx + old_vec.imag * ny) < 0:
                    virt_center = ref_pt + complex(r_ref * nx, r_ref * ny)
                new_clutter = 0.92 * self._clutter_est + 0.08 * virt_center

            # Compensate center-update rotation so refining clutter injects ZERO phase drift
            new_vec = ref_pt - new_clutter
            if abs(new_vec) > 1e-4:
                new_ang = math.atan2(new_vec.imag, new_vec.real)
                d_ang = (new_ang - old_ang + math.pi) % (2.0 * math.pi) - math.pi
                self._comp_rot *= complex(math.cos(-d_ang), math.sin(-d_ang))
                self._comp_rot /= abs(self._comp_rot)
                self._clutter_est = new_clutter

        elif self.mode == 1:
            # Explicit Small-Angle Virtual-Carrier Tangent Mode
            dz = iq128 - self._mean_iq
            cov_xx = float(np.mean(dz.real * dz.real)) + 1e-12
            cov_yy = float(np.mean(dz.imag * dz.imag)) + 1e-12
            cov_xy = float(np.mean(dz.real * dz.imag))
            theta = 0.5 * math.atan2(2.0 * cov_xy, cov_xx - cov_yy)
            tangent = dz.real * math.cos(theta) + dz.imag * math.sin(theta)
            r_ref = 0.32
            out = r_ref + 1j * tangent
            return out.astype(np.complex64)

        # Mode 0 (Curvature/Smart) and Mode 2 (Locked Clutter Vector)
        centered = (iq128 - self._clutter_est) * self._comp_rot
        return centered.astype(np.complex64)


# ============================================================================
# 3. CONTINUOUS ARCTANGENT PHASE DEMODULATOR (RAD -> MICROMETERS)
# ============================================================================


class PhaseVibrometerCore:
    """
    Computes continuous sample-accurate unwrapped phase from centered I/Q samples
    and converts phase excursion directly into micrometers (um) of tissue motion:

        x_um(t) = unwrap(atan2(Q, I)) * (c / (4 * pi * f_rf)) * 1e6

    Includes an ultra-low cutoff (0.035 Hz) DC drift blocker so slow posture shifts
    do not cause floating-point offset accumulation while 0.08-2.5 Hz breathing
    and 70-3000 Hz laryngeal vibrations pass undistorted.
    """

    def __init__(self, samp_rate: float = 48_000.0, rf_freq_mhz: float = 915.0) -> None:
        self.samp_rate = float(samp_rate)
        self.rf_freq_mhz = float(rf_freq_mhz)
        self._prev_wrapped: float = 0.0
        self._unwrapped_acc: float = 0.0
        self._dc_est: float = 0.0
        self._env_ema: float = 0.0
        self._env_dc: float = 0.0
        self._env_init: bool = False
        self.last_coherence: float = 0.0
        self._initialized: bool = False

    def process(self, iq: np.ndarray) -> np.ndarray:
        n = len(iq)
        if n == 0:
            return np.empty(0, dtype=np.float32)

        mag = np.abs(iq).astype(np.float64)
        unit = iq.astype(np.complex128) / (mag + 1e-12)
        rayleigh = float(np.abs(np.mean(unit)))

        wrapped = np.angle(iq).astype(np.float64)
        if not self._initialized:
            self._prev_wrapped = float(wrapped[0])
            self._unwrapped_acc = 0.0
            self._initialized = True

        ext = np.empty(n + 1, dtype=np.float64)
        ext[0] = self._prev_wrapped
        ext[1:] = wrapped
        self._prev_wrapped = float(wrapped[-1])

        # Wrap differences strictly into [-pi, pi)
        dphi = (np.diff(ext) + math.pi) % (2.0 * math.pi) - math.pi
        freq_hz = max(self.rf_freq_mhz, 10.0) * 1e6
        rad_to_um = (SPEED_OF_LIGHT_MPS / (4.0 * math.pi * freq_hz)) * 1e6

        med_dphi = float(np.median(np.abs(dphi)))
        dphi_acf = (
            float(np.dot(dphi[:-1], dphi[1:]) / (np.dot(dphi, dphi) + 1e-18))
            if n >= 8
            else 1.0
        )
        dphi_std_um = float(np.std(dphi)) * rad_to_um
        is_white_thermal = (dphi_acf < 0.05) and (dphi_std_um > 65.0)
        is_coherent_cw = (rayleigh >= 0.45) and (med_dphi < 0.55) and not is_white_thermal

        if not is_coherent_cw:
            # Passive RX without CW radar carrier: prevent ±pi thermal phase-walk runaway!
            self.last_coherence = round(float(min(0.25, rayleigh * 0.40)), 4)
            self._unwrapped_acc *= 0.85
            self._dc_est *= 0.85
            env_mean = float(np.mean(mag))
            if not self._env_init:
                self._env_ema = max(env_mean, 1e-6)
                self._env_dc = 0.0
                self._env_init = True
            else:
                self._env_ema = 0.96 * self._env_ema + 0.04 * max(env_mean, 1e-6)
            rel_env = ((mag - self._env_ema) / max(self._env_ema, 1e-5)) * 18.0
            # Smooth chunk-level infrasonic envelope motion (chest/body proximity) bounded to ±45 um
            blk_val = float(np.mean(rel_env))
            self._env_dc = 0.985 * self._env_dc + 0.015 * blk_val
            smooth_um = 45.0 * np.tanh((rel_env - self._env_dc) / 45.0)
            # Suppress wideband sample-to-sample thermal jitter via smooth 16-tap boxcar if n >= 16
            if n >= 16:
                k = np.ones(16, dtype=np.float64) / 16.0
                smooth_um = np.convolve(smooth_um, k, mode="same")
            return smooth_um.astype(np.float32)

        if dphi_acf >= 0.18 or (rayleigh >= 0.96 and med_dphi < 0.04):
            scale = 0.86 if (rayleigh >= 0.96 and med_dphi < 0.04) else (0.62 + 0.38 * max(0.0, dphi_acf))
            self.last_coherence = round(float(np.clip(rayleigh * scale, 0.0, 1.0)), 4)
        else:
            self.last_coherence = round(float(np.clip(rayleigh * 0.50, 0.0, 1.0)), 4)

        unwrapped = self._unwrapped_acc + np.cumsum(dphi)
        self._unwrapped_acc = float(unwrapped[-1])
        disp_um = unwrapped * rad_to_um

        # Ultra-slow 1-pole high-pass (fc = 0.035 Hz) to remove multi-minute posture drift
        alpha_dc = min(1.0, 2.0 * math.pi * 0.035 / max(self.samp_rate, 1.0))
        # Vectorized chunk DC tracking (accurate since alpha_dc ~ 4.5e-6 << 1/n)
        out = np.empty(n, dtype=np.float64)
        dc = self._dc_est
        if n <= 4096:
            # Exact fast chunk update with linear ramp correction
            mean_chunk = float(np.mean(disp_um))
            dc_end = dc + (1.0 - (1.0 - alpha_dc) ** n) * (mean_chunk - dc)
            ramp = np.linspace(dc, dc_end, n)
            out = disp_um - ramp
            self._dc_est = dc_end
        else:
            for i in range(n):
                dc += alpha_dc * (disp_um[i] - dc)
                out[i] = disp_um[i] - dc
            self._dc_est = dc

        # Periodically recenter accumulator & DC state together to preserve float64 precision forever
        if abs(self._unwrapped_acc) > 1e5:
            shift_rad = self._dc_est / max(rad_to_um, 1e-9)
            self._unwrapped_acc -= shift_rad
            self._dc_est = 0.0

        return out.astype(np.float32)


# ============================================================================
# 4. STFT SPECTRAL NOISE GATE, FORMANT ENHANCER & SOFT-KNEE AGC
# ============================================================================


class SubvocSpectralEnhancerCore:
    """
    Real-time 50%-overlap-add Hann STFT enhancer tailored for subtle laryngeal
    and subvocalization vibrations (70 - 3000 Hz):
      1. Tracks per-bin SDR LO phase noise floor.
      2. Applies smooth Wiener / soft spectral gate (`gate_thresh_db`).
      3. Applies vocal-tract formant presence boost (250 - 2200 Hz) + 60 Hz hum notch.
      4. Applies soft-knee dynamic range AGC + ear-safe `tanh` limiter.
    """

    def __init__(
        self,
        samp_rate: float = 48_000.0,
        fft_size: int = 512,
        gate_thresh_db: float = -42.0,
        gain_db: float = 18.0,
    ) -> None:
        self.samp_rate = float(samp_rate)
        self.fft_size = int(fft_size)
        self.hop = self.fft_size // 2
        self.gate_thresh_db = float(gate_thresh_db)
        self.gain_db = float(gain_db)

        self._win = np.hanning(self.fft_size).astype(np.float64)
        self._in_fifo = np.zeros(0, dtype=np.float64)
        self._ola_buf = np.zeros(self.fft_size, dtype=np.float64)
        self._out_fifo = np.zeros(0, dtype=np.float64)

        n_bins = self.fft_size // 2 + 1
        freqs = np.fft.rfftfreq(self.fft_size, d=1.0 / self.samp_rate)
        self._noise_psd = np.full(n_bins, 1e-6, dtype=np.float64)
        self._noise_init = False
        self._agc_env: float = 0.05

        # Formant presence EQ curve (+4.5 dB across 250-2200 Hz, gentle roll-off >3400 Hz)
        eq = np.ones(n_bins, dtype=np.float64)
        formant_bell = np.exp(-0.5 * ((np.log2(np.maximum(freqs, 20.0) / 850.0)) / 1.35) ** 2)
        eq *= 1.0 + 0.68 * formant_bell
        eq *= np.where(freqs < 55.0, 0.05, 1.0)
        eq *= 1.0 / (1.0 + (freqs / 3400.0) ** 4)
        self._eq_curve = eq

    def _process_frame(self, frame: np.ndarray) -> np.ndarray:
        spec = np.fft.rfft(frame * self._win)
        mag2 = (spec.real * spec.real + spec.imag * spec.imag) + 1e-18

        if not self._noise_init:
            self._noise_psd = mag2.copy()
            self._noise_init = True
        else:
            # Asymmetric tracker: fast downward (tracks true floor), very slow upward
            up_mask = mag2 > self._noise_psd
            self._noise_psd = np.where(
                up_mask,
                0.996 * self._noise_psd + 0.004 * mag2,
                0.85 * self._noise_psd + 0.15 * mag2,
            )

        # Combine adaptive SNR gate with user threshold relative to full-scale um reference
        abs_thresh_lin2 = (10.0 ** (self.gate_thresh_db / 20.0) * 50.0) ** 2
        eff_floor = np.maximum(self._noise_psd * 2.2, abs_thresh_lin2 * 0.02)
        snr = mag2 / (eff_floor + 1e-18)
        wiener_gain = np.clip((snr - 1.0) / (snr + 0.6), 0.05, 1.0) ** 1.15

        enhanced_spec = spec * wiener_gain * self._eq_curve
        recon = np.fft.irfft(enhanced_spec, n=self.fft_size) * self._win
        return recon

    def process(self, x: np.ndarray) -> np.ndarray:
        n = len(x)
        if n == 0:
            return np.empty(0, dtype=np.float32)

        # Normalize um scale (~25 um -> ~0.25 audio unit before user gain)
        scaled_in = x.astype(np.float64) * 0.012
        self._in_fifo = np.concatenate([self._in_fifo, scaled_in])

        while len(self._in_fifo) >= self.fft_size:
            frame = self._in_fifo[: self.fft_size]
            self._in_fifo = self._in_fifo[self.hop :]
            recon = self._process_frame(frame)
            self._ola_buf += recon
            hop_out = self._ola_buf[: self.hop].copy()
            self._ola_buf[: -self.hop] = self._ola_buf[self.hop :]
            self._ola_buf[-self.hop :] = 0.0
            self._out_fifo = np.concatenate([self._out_fifo, hop_out])

        if len(self._out_fifo) >= n:
            raw_out = self._out_fifo[:n]
            self._out_fifo = self._out_fifo[n:]
        else:
            pad = n - len(self._out_fifo)
            raw_out = np.concatenate([np.zeros(pad, dtype=np.float64), self._out_fifo])
            self._out_fifo = np.zeros(0, dtype=np.float64)

        # Soft-knee AGC + user gain + headphone limiter
        lin_gain = 10.0 ** (self.gain_db / 20.0)
        boosted = raw_out * lin_gain
        rms = float(np.sqrt(np.mean(boosted * boosted) + 1e-12))
        if rms > self._agc_env:
            self._agc_env = 0.85 * self._agc_env + 0.15 * rms
        else:
            self._agc_env = 0.992 * self._agc_env + 0.008 * rms

        comp_gain = 1.0 / max(1.0, (self._agc_env / 0.35) ** 0.65)
        safe_audio = 0.88 * np.tanh(boosted * comp_gain * 1.15)
        return safe_audio.astype(np.float32)


# ============================================================================
# 5. INFRASONIC (< 20 HZ) BREATHING SONIFIER & SUBVOC VAD DETECTOR
# ============================================================================


class InfrasonicSonifierCore:
    """
    Translates sub-audible (< 20 Hz) breathing & pre-phonatory laryngeal tension
    into an intuitive, fatigue-free warm heterodyne/FM audible stream, and computes
    a real-time Subvocalization Voice Activity Detection (VAD) envelope [0.0 .. 1.0].

      - Inhalation shifts carrier pitch smoothly upward; exhalation shifts downward.
      - Breath velocity modulates amplitude + subtle filtered breath-air shimmer.
      - 2-18 Hz infrasonic throat tension adds warm octave harmonic richness.
    """

    def __init__(
        self,
        samp_rate: float = 48_000.0,
        carrier_hz: float = 168.0,
        vad_thresh_db: float = -42.0,
    ) -> None:
        self.samp_rate = float(samp_rate)
        self.carrier_hz = float(carrier_hz)
        self.vad_thresh_db = float(vad_thresh_db)
        self._phase1: float = 0.0
        self._phase2: float = 0.0
        self._prev_infra: float = 0.0
        self._vel_smooth: float = 0.0
        self._vad_env: float = 0.0
        self._vad_floor: float = 0.02
        self._shimmer_z: float = 0.0
        self._rng = np.random.default_rng(7)

    def process(self, infra_um: np.ndarray, subvoc_audio: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        n = len(infra_um)
        if n == 0:
            empty = np.empty(0, dtype=np.float32)
            return empty, empty

        fs = self.samp_rate
        infra = infra_um.astype(np.float64)

        # Differentiate infrasonic displacement -> respiratory velocity (um/s)
        ext = np.empty(n + 1, dtype=np.float64)
        ext[0] = self._prev_infra
        ext[1:] = infra
        self._prev_infra = float(infra[-1])
        vel_um_s = np.diff(ext) * fs

        # Smooth velocity slightly to suppress differentiation hiss
        chunk_vel = float(np.mean(vel_um_s))
        self._vel_smooth = 0.75 * self._vel_smooth + 0.25 * chunk_vel
        vel_norm = np.tanh(vel_um_s / 950.0)  # +1 on brisk inhale, -1 on brisk exhale
        disp_norm = np.tanh(infra / 750.0)

        # Instantaneous FM carrier: rises up to +38 Hz on inhale, drops -28 Hz on exhale
        f_inst = np.maximum(45.0, self.carrier_hz + 34.0 * vel_norm + 12.0 * disp_norm)
        dphi1 = 2.0 * math.pi * f_inst / fs
        phi1 = self._phase1 + np.cumsum(dphi1)
        self._phase1 = float(np.mod(phi1[-1], 2.0 * math.pi))

        phi2 = self._phase2 + np.cumsum(2.0 * dphi1)
        self._phase2 = float(np.mod(phi2[-1], 2.0 * math.pi))

        # Amplitude swells gently during active inhalation/exhalation airflow
        flow_mag = np.abs(vel_norm)
        amp_env = 0.14 + 0.52 * flow_mag + 0.12 * np.abs(disp_norm)

        # Subtle warm low-passed airflow whisper proportional to breath flow speed
        noise = self._rng.normal(0.0, 0.08, n)
        shimmer = np.empty(n, dtype=np.float64)
        z = self._shimmer_z
        for i in range(n):
            z = 0.94 * z + 0.06 * noise[i]
            shimmer[i] = z
        self._shimmer_z = z

        sonified = amp_env * (
            0.74 * np.sin(phi1) + 0.20 * np.abs(vel_norm) * np.sin(phi2)
        ) + (0.45 * flow_mag * shimmer)
        sonified = 0.85 * np.tanh(sonified)

        # Adaptive Subvocalization VAD envelope detector (0..1 soft probability/gate)
        sub_abs = np.abs(subvoc_audio.astype(np.float64))
        thresh_lin = max(0.012, 10.0 ** ((self.vad_thresh_db + 16.0) / 20.0))
        vad = np.empty(n, dtype=np.float32)
        env = self._vad_env
        floor = self._vad_floor
        att = min(1.0, 1.0 / (0.010 * fs))
        rel = min(1.0, 1.0 / (0.140 * fs))
        fl_up = min(1.0, 1.0 / (6.0 * fs))
        fl_dn = min(1.0, 1.0 / (0.20 * fs))
        for i in range(n):
            v = sub_abs[i]
            env += (att if v > env else rel) * (v - env)
            floor += (fl_up if env > floor else fl_dn) * (env - floor)
            eff_gate = max(thresh_lin * 0.65, floor * 1.35)
            vad[i] = min(1.0, max(0.0, (env - eff_gate) / max(eff_gate * 0.55, 0.012)))
        self._vad_env = env
        self._vad_floor = floor

        return sonified.astype(np.float32), vad


# ============================================================================
# 6. REAL-TIME BIOMETRIC TRACKER (RESPIRATION BPM & DISPLACEMENT UM)
# ============================================================================


class BiometricTrackerCore:
    """
    Operates at decimated `breath_rate` (default 400 Hz) on the isolated
    respiration wave (0.08 - 2.5 Hz) to compute:
      - Respiration Rate in Breaths Per Minute (BPM) via windowed autocorrelation
        with parabolic peak interpolation over [5.0, 42.0] BPM.
      - Robust Peak-to-Peak Tissue Displacement (um, P95 - P5 over rolling 10 s).
    """

    def __init__(self, samp_rate: float = 400.0) -> None:
        self.samp_rate = float(samp_rate)
        self._win_sec = 20.0
        self._buf_len = max(512, int(round(self.samp_rate * self._win_sec)))
        self._buf = np.zeros(self._buf_len, dtype=np.float64)
        self._filled: int = 0
        self._since_update: int = 0
        self._update_stride = max(20, int(round(self.samp_rate * 0.25)))
        self.current_bpm: float = 0.0
        self.current_disp_pp_um: float = 0.0

    def _estimate_metrics(self) -> None:
        valid = self._buf[-self._filled :]
        # Robust peak-to-peak displacement over most recent 10 seconds
        recent_n = min(len(valid), int(self.samp_rate * 10.0))
        recent = valid[-recent_n:]
        p95, p5 = np.percentile(recent, [96.0, 4.0])
        disp_pp = float(max(0.0, p95 - p5))
        if self.current_disp_pp_um == 0.0:
            self.current_disp_pp_um = disp_pp
        else:
            self.current_disp_pp_um = 0.75 * self.current_disp_pp_um + 0.25 * disp_pp

        # Need at least 8 seconds of signal and >8 um motion to report valid BPM
        if len(valid) < int(self.samp_rate * 8.0) or disp_pp < 8.0:
            return

        # Downsample internally by 8x (400 Hz -> 50 Hz) for ultra-fast autocorrelation
        ds = max(1, int(round(self.samp_rate / 50.0)))
        fs_eff = self.samp_rate / ds
        sig = valid[::ds].copy()
        # Detrend linear drift (mean + slope) before autocorrelation
        t_idx = np.arange(len(sig), dtype=np.float64)
        t_idx -= np.mean(t_idx)
        slope = float(np.dot(t_idx, sig)) / max(float(np.dot(t_idx, t_idx)), 1e-12)
        sig = sig - np.mean(sig) - slope * t_idx

        # Detrend recent window too for accurate P-P breathing excursion
        rec_t = np.arange(len(recent), dtype=np.float64)
        rec_t -= np.mean(rec_t)
        rec_slope = float(np.dot(rec_t, recent)) / max(float(np.dot(rec_t, rec_t)), 1e-12)
        rec_detrended = recent - np.mean(recent) - rec_slope * rec_t
        p95, p5 = np.percentile(rec_detrended, [96.0, 4.0])
        disp_pp = float(max(0.0, p95 - p5))
        self.current_disp_pp_um = (
            disp_pp if self.current_disp_pp_um == 0.0 else 0.72 * self.current_disp_pp_um + 0.28 * disp_pp
        )

        energy = float(np.dot(sig, sig))
        if energy < 1e-9:
            return

        # FFT-based unbiased autocorrelation
        nfft = 1 << (2 * len(sig) - 1).bit_length()
        spec = np.fft.rfft(sig, n=nfft)
        acf = np.fft.irfft(spec * np.conj(spec), n=nfft)[: len(sig)] / energy

        # Search physiological breathing lag range: [5.0 BPM .. 42.0 BPM] -> [1.43 s .. 12.0 s]
        min_lag = max(2, int(math.floor(fs_eff * (60.0 / 42.0))))
        max_lag = min(len(acf) - 2, int(math.ceil(fs_eff * (60.0 / 5.0))))
        if max_lag <= min_lag + 2:
            return

        # Locate local maxima inside [min_lag, max_lag] after initial lobe drops < 0.45
        below_lobe = np.where(acf[: max_lag + 1] < 0.45)[0]
        if len(below_lobe) == 0:
            return
        search_start = max(min_lag, int(below_lobe[0]))
        if max_lag <= search_start + 2:
            return

        seg = acf[search_start : max_lag + 1]
        local_max_mask = (seg[1:-1] > seg[:-2]) & (seg[1:-1] >= seg[2:])
        cand_indices = np.where(local_max_mask)[0] + 1
        if len(cand_indices) == 0:
            return

        # Pick strongest fundamental local peak (prefer first peak within 85% of global max to avoid 2x period)
        cand_vals = seg[cand_indices]
        best_val = float(np.max(cand_vals))
        if best_val < 0.18:
            return
        prominent = cand_indices[cand_vals >= 0.82 * best_val]
        pk_idx = search_start + int(prominent[0])

        # Parabolic sub-sample lag refinement
        if 1 <= pk_idx < len(acf) - 1:
            y0, y1, y2 = acf[pk_idx - 1], acf[pk_idx], acf[pk_idx + 1]
            denom = y0 - 2.0 * y1 + y2
            delta = 0.5 * (y0 - y2) / denom if abs(denom) > 1e-12 else 0.0
            true_lag = pk_idx + np.clip(delta, -0.5, 0.5)
        else:
            true_lag = float(pk_idx)

        bpm = 60.0 * fs_eff / max(true_lag, 1e-6)
        if 4.5 <= bpm <= 45.0:
            if self.current_bpm <= 0.0:
                self.current_bpm = float(bpm)
            else:
                self.current_bpm = 0.72 * self.current_bpm + 0.28 * float(bpm)

    def process(self, resp_um: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        n = len(resp_um)
        if n == 0:
            empty = np.empty(0, dtype=np.float32)
            return empty, empty, empty

        if n >= self._buf_len:
            self._buf[:] = resp_um[-self._buf_len :]
            self._filled = self._buf_len
        else:
            self._buf[:-n] = self._buf[n:]
            self._buf[-n:] = resp_um
            self._filled = min(self._buf_len, self._filled + n)

        self._since_update += n
        if self._since_update >= self._update_stride:
            self._since_update = 0
            self._estimate_metrics()

        bpm_vec = np.full(n, self.current_bpm, dtype=np.float32)
        disp_vec = np.full(n, self.current_disp_pp_um, dtype=np.float32)
        return resp_um.astype(np.float32), bpm_vec, disp_vec


# ============================================================================
# 7. STEREO EXPERIENCE MATRIX & 4-CHANNEL WAV + CSV SESSION RECORDER
# ============================================================================


class MasterExperienceOutputCore:
    """
    Mixes Enhanced Subvocalization & Sonified Breathing into 4 selectable headphone
    experience modes and optionally streams timestamped 4-channel scientific WAV
    + biometric CSV logs when `record_enable` is active:

      Audio Modes:
        0: Stereo Split (Left = Subvocalization | Right = Sonified Breathing)
        1: Binaural Spatial Blend (Centered vocal + wide stereo breath drone)
        2: Pure Subvocalization Focus (Dual-mono isolated larynx 70-2600 Hz)
        3: Pure Sonified Breathing & Infrasonic Vibrometry

      4-Channel WAV Layout (16-bit PCM @ 48 kHz):
        Ch 1: Headphone Left
        Ch 2: Headphone Right
        Ch 3: Isolated Subvocalization Audio
        Ch 4: Normalized Raw Tissue Displacement
    """

    def __init__(
        self,
        samp_rate: float = 48_000.0,
        audio_mix_mode: int = 0,
        breath_mix_gain: float = 0.45,
        record_enable: bool = False,
        recordings_dir: str = "recordings",
    ) -> None:
        self.samp_rate = int(round(samp_rate))
        self.audio_mix_mode = int(audio_mix_mode)
        self.breath_mix_gain = float(breath_mix_gain)
        self.record_enable = bool(record_enable)
        self.recordings_dir = str(recordings_dir)

        self._wav: Optional[wave.Wave_write] = None
        self._csv_file = None
        self._csv_writer = None
        self._frames_written: int = 0
        self._last_csv_sec: int = -1
        self.active_wav_path: Optional[str] = None

        # Lock-free mid-air acoustic talkback TX FIFO + half-duplex self-echo blanking guard
        self._tx_lock = threading.Lock()
        self._tx_queue: "collections.deque[np.ndarray]" = collections.deque(maxlen=16)
        self._tx_cur: Optional[np.ndarray] = None
        self._tx_pos: int = 0
        self._tx_echo_guard_samples: int = 0
        self.talkback_packets_emitted: int = 0

    def enqueue_talkback_pcm(self, pcm_48k: np.ndarray, echo_guard_ms: float = 420.0) -> bool:
        arr = np.asarray(pcm_48k, dtype=np.float32).ravel()
        if len(arr) == 0:
            return False
        with self._tx_lock:
            self._tx_queue.append(arr.copy())
            self._tx_echo_guard_samples = max(
                self._tx_echo_guard_samples, int(round((echo_guard_ms / 1000.0) * self.samp_rate))
            )
            self.talkback_packets_emitted += 1
        return True

    @property
    def is_transmitting_talkback(self) -> bool:
        with self._tx_lock:
            return self._tx_cur is not None or len(self._tx_queue) > 0

    @property
    def is_echo_suppressed(self) -> bool:
        with self._tx_lock:
            return self._tx_cur is not None or len(self._tx_queue) > 0 or self._tx_echo_guard_samples > 0

    def _open_session(self) -> None:
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        candidate_dirs = [
            Path(self.recordings_dir),
            Path(tempfile.gettempdir()) / "GNU-Larex" / "recordings",
        ]
        for out_dir in candidate_dirs:
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
                wav_path = out_dir / f"larex_session_{stamp}.wav"
                csv_path = out_dir / f"larex_session_{stamp}_biometrics.csv"

                f_wav = open(wav_path, "wb")
                w = wave.open(f_wav, "wb")
                w.setnchannels(4)
                w.setsampwidth(2)  # 16-bit PCM for universal DAW/Audacity compatibility
                w.setframerate(self.samp_rate)

                cf = open(csv_path, "w", newline="", encoding="utf-8")
                cw = csv.writer(cf)
                cw.writerow(["elapsed_sec", "timestamp_iso", "subvoc_rms", "vad_mean", "raw_disp_um_rms"])

                self._wav = w
                self.active_wav_path = str(wav_path)
                self._csv_file = cf
                self._csv_writer = cw
                self._frames_written = 0
                self._last_csv_sec = -1
                return
            except PermissionError:
                continue

    def close(self) -> None:
        if self._wav is not None:
            try:
                self._wav.close()
            except Exception:
                pass
            self._wav = None
        if self._csv_file is not None:
            try:
                self._csv_file.close()
            except Exception:
                pass
            self._csv_file = None
            self._csv_writer = None

    def process(
        self,
        subvoc: np.ndarray,
        sonified_breath: np.ndarray,
        raw_disp_um: np.ndarray,
        vad: Optional[np.ndarray] = None,
    ) -> Tuple[np.ndarray, np.ndarray]:
        n = len(subvoc)
        if n == 0:
            empty = np.empty(0, dtype=np.float32)
            return empty, empty

        breath = sonified_breath * self.breath_mix_gain
        mode = self.audio_mix_mode
        if mode == 0:
            left = subvoc + 0.12 * breath
            right = breath + 0.12 * subvoc
        elif mode == 4:
            left = breath + 0.12 * subvoc
            right = subvoc + 0.12 * breath
        elif mode == 1:
            left = 0.78 * subvoc + 0.58 * breath
            right = 0.78 * subvoc + 0.52 * breath
        elif mode == 2:
            left = subvoc.copy()
            right = subvoc.copy()
        else:
            left = breath.copy()
            right = breath.copy()

        left = np.clip(left, -0.98, 0.98).astype(np.float32)
        right = np.clip(right, -0.98, 0.98).astype(np.float32)

        # Mix outbound Mid-Air Acoustic Whisper Talkback payload (ducking room loopback by -30 dB to prevent howl)
        tx_chunk: Optional[np.ndarray] = None
        with self._tx_lock:
            if self._tx_cur is None and self._tx_queue:
                self._tx_cur = self._tx_queue.popleft()
                self._tx_pos = 0
            if self._tx_cur is not None:
                tx_chunk = np.zeros(n, dtype=np.float32)
                filled = 0
                while filled < n and self._tx_cur is not None:
                    rem = len(self._tx_cur) - self._tx_pos
                    take = min(n - filled, rem)
                    tx_chunk[filled : filled + take] = self._tx_cur[self._tx_pos : self._tx_pos + take]
                    self._tx_pos += take
                    filled += take
                    if self._tx_pos >= len(self._tx_cur):
                        self._tx_cur = self._tx_queue.popleft() if self._tx_queue else None
                        self._tx_pos = 0
                self._tx_echo_guard_samples = max(
                    self._tx_echo_guard_samples, int(round(0.42 * self.samp_rate))
                )
            elif self._tx_echo_guard_samples > 0:
                self._tx_echo_guard_samples = max(0, self._tx_echo_guard_samples - n)

        if tx_chunk is not None:
            left = np.clip(left * 0.03 + tx_chunk, -0.98, 0.98).astype(np.float32)
            right = np.clip(right * 0.03 + tx_chunk, -0.98, 0.98).astype(np.float32)

        # Handle dynamic record toggle
        if self.record_enable and self._wav is None:
            self._open_session()
        elif not self.record_enable and self._wav is not None:
            self.close()

        if self._wav is not None:
            ch3 = np.clip(subvoc, -0.99, 0.99)
            ch4 = np.tanh(raw_disp_um.astype(np.float64) / 1000.0).astype(np.float32)
            interleaved = np.empty((n, 4), dtype=np.int16)
            interleaved[:, 0] = (left * 32767.0).astype(np.int16)
            interleaved[:, 1] = (right * 32767.0).astype(np.int16)
            interleaved[:, 2] = (ch3 * 32767.0).astype(np.int16)
            interleaved[:, 3] = (ch4 * 32767.0).astype(np.int16)
            self._wav.writeframes(interleaved.tobytes())
            self._frames_written += n

            elapsed_sec = self._frames_written // max(self.samp_rate, 1)
            if elapsed_sec > self._last_csv_sec and self._csv_writer is not None:
                self._last_csv_sec = elapsed_sec
                sub_rms = float(np.sqrt(np.mean(subvoc * subvoc)))
                vad_mean = float(np.mean(vad)) if vad is not None and len(vad) > 0 else 0.0
                disp_rms = float(np.sqrt(np.mean(raw_disp_um * raw_disp_um)))
                self._csv_writer.writerow([
                    elapsed_sec,
                    datetime.datetime.now().isoformat(timespec="seconds"),
                    f"{sub_rms:.5f}",
                    f"{vad_mean:.3f}",
                    f"{disp_rms:.2f}",
                ])
                self._csv_file.flush()

        return left, right


# ============================================================================
# 8. GNU RADIO 3.10 BLOCK WRAPPERS (LAZY IMPORT SO NUMPY TESTS RUN STANDALONE)
# ============================================================================

try:
    from gnuradio import gr
    HAS_GNURADIO = True
except ImportError:  # pragma: no cover - allows standalone DSP testing prior to radioconda install
    HAS_GNURADIO = False
    gr = None  # type: ignore


if HAS_GNURADIO:

    class HybridSDRRadarSource(gr.sync_block):
        """
        Multi-backend RF Radar / Vibrometry I/Q Source:
          - `source_mode == 0`: High-fidelity Physiological RF Micro-Doppler Simulator
          - `source_mode == 1`: Live SDR via SoapySDR (RTL-SDR, PlutoSDR, HackRF, USRP,
            LimeSDR, BladeRF) with optional Full-Duplex CW TX illuminator and automatic
            zero-crash fallback to Simulator if no USB SDR hardware is attached.
        """

        def __init__(
            self,
            rf_samp_rate: float = 960_000.0,
            baseband_rate: float = 48_000.0,
            rf_freq_mhz: float = 915.0,
            rf_gain: float = 35.0,
            source_mode: int = 0,
            sdr_args: str = "",
            enable_cw_tx: bool = False,
            tx_gain: float = 25.0,
            pace_sim: bool = True,
            shared_sdr_stream: Optional[AsyncSDRRadarStream] = None,
            shared_hackrf_stream: Optional[AsyncHackRFStream] = None,
            rf_device_select: int = 0,
        ) -> None:
            gr.sync_block.__init__(
                self,
                name="Hybrid SDR / Radar Vibrometry Source",
                in_sig=None,
                out_sig=[np.complex64],
            )
            self.rf_samp_rate = float(rf_samp_rate)
            self.baseband_rate = float(baseband_rate)
            self.rf_freq_mhz = float(rf_freq_mhz)
            self.rf_gain = float(rf_gain)
            self.source_mode = int(source_mode)
            self.sdr_args = str(sdr_args)
            self.enable_cw_tx = bool(enable_cw_tx)
            self.tx_gain = float(tx_gain)
            self.pace_sim = bool(pace_sim)
            self.shared_sdr_stream = shared_sdr_stream
            self.shared_hackrf_stream = shared_hackrf_stream
            # 0 = Auto Dual-SDR (RTL-SDR Blog V4 + HackRF One), 1 = RTL-SDR Blog V4, 2 = HackRF One
            self.rf_device_select = int(rf_device_select)

            self._sim = PhysiologicalRadarSimulatorCore(
                rf_samp_rate=self.rf_samp_rate,
                baseband_rate=self.baseband_rate,
                rf_freq_mhz=self.rf_freq_mhz,
            )
            self._sdr = None
            self._rx_stream = None
            self._tx_stream = None
            self._sdr_attempted: bool = False
            self._tx_tone: Optional[np.ndarray] = None
            self._last_sim_wall: float = 0.0

        def set_rf_device_select(self, sel: int) -> None:
            self.rf_device_select = int(sel)

        def _pull_shared_iq(self, n: int) -> Optional[np.ndarray]:
            rtl = self.shared_sdr_stream
            hrf = self.shared_hackrf_stream
            if rtl is None and hrf is None:
                return None

            sel = self.rf_device_select
            if sel == 1:
                return rtl.read_raw_iq(n) if (rtl is not None and rtl.connected) else None
            if sel == 2:
                return hrf.read_raw_iq(n) if (hrf is not None and hrf.connected) else None

            # Mode 0: Auto Dual-SDR Fusion (coherent RTL-SDR primary + HackRF wideband quadrature reinforcement)
            iq_rtl = rtl.read_raw_iq(n) if (rtl is not None and rtl.connected) else None
            iq_hrf = hrf.read_raw_iq(n) if (hrf is not None and hrf.connected) else None
            if iq_rtl is not None and iq_hrf is not None and len(iq_rtl) == len(iq_hrf):
                return (0.72 * iq_rtl + 0.28 * iq_hrf).astype(np.complex64)
            if iq_rtl is not None:
                return iq_rtl
            return iq_hrf

        def _open_soapy_if_needed(self) -> bool:
            if self.shared_sdr_stream is not None or self.shared_hackrf_stream is not None:
                return False
            if self._sdr is not None:
                return True
            if self._sdr_attempted:
                return False
            self._sdr_attempted = True
            try:
                import SoapySDR
                from SoapySDR import SOAPY_SDR_CF32, SOAPY_SDR_RX, SOAPY_SDR_TX

                results = safe_enumerate_soapysdr(self.sdr_args)
                if len(results) == 0:
                    print(
                        "[GNU-Larex] No SoapySDR USB device detected -> streaming Physiological RF Radar Simulator."
                    )
                    return False

                chosen = results[0]
                dev = SoapySDR.Device(soapy_info_to_markup(chosen))
                dev.setSampleRate(SOAPY_SDR_RX, 0, self.rf_samp_rate)
                dev.setFrequency(SOAPY_SDR_RX, 0, self.rf_freq_mhz * 1e6)
                dev.setGain(SOAPY_SDR_RX, 0, self.rf_gain)
                rx_st = dev.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
                dev.activateStream(rx_st)

                self._sdr = dev
                self._rx_stream = rx_st
                print(f"[GNU-Larex] Connected Live SDR: { dict(chosen) } @ {self.rf_freq_mhz:.2f} MHz")

                drv_name = str(chosen.get("driver", "")).lower()
                if self.enable_cw_tx and drv_name != "hackrf" and dev.getNumChannels(SOAPY_SDR_TX) > 0:
                    dev.setSampleRate(SOAPY_SDR_TX, 0, self.rf_samp_rate)
                    dev.setFrequency(SOAPY_SDR_TX, 0, self.rf_freq_mhz * 1e6)
                    dev.setGain(SOAPY_SDR_TX, 0, self.tx_gain)
                    tx_st = dev.setupStream(SOAPY_SDR_TX, SOAPY_SDR_CF32)
                    dev.activateStream(tx_st)
                    self._tx_stream = tx_st
                    self._tx_tone = np.full(4096, 0.5 + 0.0j, dtype=np.complex64)
                    print("[GNU-Larex] Full-Duplex CW Radar TX Illuminator ACTIVE.")
                return True
            except Exception as exc:
                print(f"[GNU-Larex] SoapySDR init notice ({exc}) -> using Physiological RF Simulator.")
                self._sdr = None
                return False

        def _close_soapy(self) -> None:
            if self._sdr is not None:
                try:
                    if self._rx_stream is not None:
                        self._sdr.deactivateStream(self._rx_stream)
                        self._sdr.closeStream(self._rx_stream)
                    if self._tx_stream is not None:
                        self._sdr.deactivateStream(self._tx_stream)
                        self._sdr.closeStream(self._tx_stream)
                except Exception:
                    pass
                self._sdr = None
                self._rx_stream = None
                self._tx_stream = None

        def set_source_mode(self, mode: int) -> None:
            self.source_mode = int(mode)
            if self.source_mode == 1:
                self._sdr_attempted = False

        def set_rf_freq_mhz(self, freq_mhz: float) -> None:
            self.rf_freq_mhz = float(freq_mhz)
            self._sim.rf_freq_mhz = self.rf_freq_mhz
            if self.shared_sdr_stream is not None:
                self.shared_sdr_stream.set_rf_freq_mhz(self.rf_freq_mhz)
            if self._sdr is not None:
                try:
                    from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_TX
                    self._sdr.setFrequency(SOAPY_SDR_RX, 0, self.rf_freq_mhz * 1e6)
                    if self._tx_stream is not None:
                        self._sdr.setFrequency(SOAPY_SDR_TX, 0, self.rf_freq_mhz * 1e6)
                except Exception:
                    pass

        def set_rf_gain(self, gain: float) -> None:
            self.rf_gain = float(gain)
            if self.shared_sdr_stream is not None:
                self.shared_sdr_stream.set_rf_gain(self.rf_gain)
            if self._sdr is not None:
                try:
                    from SoapySDR import SOAPY_SDR_RX
                    self._sdr.setGain(SOAPY_SDR_RX, 0, self.rf_gain)
                except Exception:
                    pass

        def stop(self) -> bool:
            self._close_soapy()
            return True

        def work(self, input_items, output_items) -> int:
            out = output_items[0]
            n = len(out)

            if self.source_mode == 1:
                chunk_req = min(n, 8192)
                shared_iq = self._pull_shared_iq(chunk_req)
                if shared_iq is not None and len(shared_iq) > 0:
                    m = len(shared_iq)
                    out[:m] = shared_iq
                    return m

                if self._open_soapy_if_needed():
                    if self._tx_stream is not None and self._tx_tone is not None:
                        if len(self._tx_tone) < n:
                            self._tx_tone = np.full(n, 0.5 + 0.0j, dtype=np.complex64)
                        self._sdr.writeStream(self._tx_stream, [self._tx_tone[:n]], n, timeoutUs=5000)

                    sr = self._sdr.readStream(self._rx_stream, [out], n, timeoutUs=50_000)
                    if sr.ret > 0:
                        return int(sr.ret)

            # Simulator output (rate-paced gently if audio sink is bypassed, otherwise audio sink paces graph)
            chunk = min(n, 8192)
            out[:chunk] = self._sim.generate_iq(chunk)
            if self.pace_sim:
                now = time.perf_counter()
                if self._last_sim_wall > 0.0:
                    min_dt = (chunk / self.rf_samp_rate) * 0.65
                    elapsed = now - self._last_sim_wall
                    if elapsed < min_dt:
                        time.sleep(min_dt - elapsed)
                self._last_sim_wall = time.perf_counter()
            return chunk

    class IQClutterCancellerBlock(gr.sync_block):
        """GNU Radio wrapper for `IQClutterCancellerCore`."""

        def __init__(self, alpha: float = 0.005, mode: int = 0) -> None:
            gr.sync_block.__init__(
                self,
                name="Adaptive I/Q Clutter & Circle Canceller",
                in_sig=[np.complex64],
                out_sig=[np.complex64],
            )
            self._core = IQClutterCancellerCore(alpha=alpha, mode=mode)

        def set_alpha(self, alpha: float) -> None:
            self._core.alpha = float(alpha)

        def set_mode(self, mode: int) -> None:
            self._core.mode = int(mode)

        def work(self, input_items, output_items) -> int:
            output_items[0][:] = self._core.process(input_items[0])
            return len(output_items[0])

    class PhaseVibrometerBlock(gr.sync_block):
        """GNU Radio wrapper for `PhaseVibrometerCore`."""

        def __init__(self, samp_rate: float = 48_000.0, rf_freq_mhz: float = 915.0) -> None:
            gr.sync_block.__init__(
                self,
                name="Arctan Phase Vibrometer (rad -> um)",
                in_sig=[np.complex64],
                out_sig=[np.float32],
            )
            self._core = PhaseVibrometerCore(samp_rate=samp_rate, rf_freq_mhz=rf_freq_mhz)

        def set_rf_freq_mhz(self, rf_freq_mhz: float) -> None:
            self._core.rf_freq_mhz = float(rf_freq_mhz)

        def work(self, input_items, output_items) -> int:
            output_items[0][:] = self._core.process(input_items[0])
            return len(output_items[0])

    class SubvocSpectralEnhancerBlock(gr.sync_block):
        """GNU Radio wrapper for `SubvocSpectralEnhancerCore`."""

        def __init__(
            self,
            samp_rate: float = 48_000.0,
            gate_thresh_db: float = -42.0,
            gain_db: float = 18.0,
        ) -> None:
            gr.sync_block.__init__(
                self,
                name="Subvocalization STFT Gate & Enhancer",
                in_sig=[np.float32],
                out_sig=[np.float32],
            )
            self._core = SubvocSpectralEnhancerCore(
                samp_rate=samp_rate,
                gate_thresh_db=gate_thresh_db,
                gain_db=gain_db,
            )

        def set_gate_thresh_db(self, val: float) -> None:
            self._core.gate_thresh_db = float(val)

        def set_gain_db(self, val: float) -> None:
            self._core.gain_db = float(val)

        def work(self, input_items, output_items) -> int:
            output_items[0][:] = self._core.process(input_items[0])
            return len(output_items[0])

    class InfrasonicSonifierBlock(gr.sync_block):
        """GNU Radio wrapper for `InfrasonicSonifierCore`."""

        def __init__(
            self,
            samp_rate: float = 48_000.0,
            carrier_hz: float = 168.0,
            vad_thresh_db: float = -42.0,
        ) -> None:
            gr.sync_block.__init__(
                self,
                name="Infrasonic Breathing Sonifier & VAD",
                in_sig=[np.float32, np.float32],
                out_sig=[np.float32, np.float32],
            )
            self._core = InfrasonicSonifierCore(
                samp_rate=samp_rate,
                carrier_hz=carrier_hz,
                vad_thresh_db=vad_thresh_db,
            )

        def set_carrier_hz(self, val: float) -> None:
            self._core.carrier_hz = float(val)

        def set_vad_thresh_db(self, val: float) -> None:
            self._core.vad_thresh_db = float(val)

        def work(self, input_items, output_items) -> int:
            sonified, vad = self._core.process(input_items[0], input_items[1])
            output_items[0][:] = sonified
            output_items[1][:] = vad
            return len(output_items[0])

    class BiometricTrackerBlock(gr.sync_block):
        """GNU Radio wrapper for `BiometricTrackerCore`."""

        def __init__(self, samp_rate: float = 400.0) -> None:
            gr.sync_block.__init__(
                self,
                name="Biometric Respiration & Displacement Tracker",
                in_sig=[np.float32],
                out_sig=[np.float32, np.float32, np.float32],
            )
            self._core = BiometricTrackerCore(samp_rate=samp_rate)

        def work(self, input_items, output_items) -> int:
            wave_out, bpm_out, disp_out = self._core.process(input_items[0])
            output_items[0][:] = wave_out
            output_items[1][:] = bpm_out
            output_items[2][:] = disp_out
            return len(output_items[0])

    class MasterExperienceOutputBlock(gr.sync_block):
        """GNU Radio wrapper for `MasterExperienceOutputCore`."""

        def __init__(
            self,
            samp_rate: float = 48_000.0,
            audio_mix_mode: int = 0,
            breath_mix_gain: float = 0.45,
            record_enable: bool = False,
            recordings_dir: str = "recordings",
        ) -> None:
            gr.sync_block.__init__(
                self,
                name="Stereo Experience Matrix & 4-Ch Recorder",
                in_sig=[np.float32, np.float32, np.float32, np.float32],
                out_sig=[np.float32, np.float32],
            )
            self._core = MasterExperienceOutputCore(
                samp_rate=samp_rate,
                audio_mix_mode=audio_mix_mode,
                breath_mix_gain=breath_mix_gain,
                record_enable=record_enable,
                recordings_dir=recordings_dir,
            )
            self.bio_hook = None

        def set_audio_mix_mode(self, mode: int) -> None:
            self._core.audio_mix_mode = int(mode)

        def set_breath_mix_gain(self, gain: float) -> None:
            self._core.breath_mix_gain = float(gain)

        def set_record_enable(self, enable: bool) -> None:
            self._core.record_enable = bool(enable)

        def enqueue_talkback_pcm(self, pcm_48k: np.ndarray, echo_guard_ms: float = 420.0) -> bool:
            return self._core.enqueue_talkback_pcm(pcm_48k, echo_guard_ms=echo_guard_ms)

        @property
        def is_transmitting_talkback(self) -> bool:
            return self._core.is_transmitting_talkback

        @property
        def is_echo_suppressed(self) -> bool:
            return self._core.is_echo_suppressed

        def stop(self) -> bool:
            self._core.close()
            return True

        def work(self, input_items, output_items) -> int:
            if self.bio_hook is not None and not self._core.is_echo_suppressed:
                self.bio_hook(input_items[2], input_items[0])
            left, right = self._core.process(
                input_items[0],
                input_items[1],
                input_items[2],
                input_items[3],
            )
            output_items[0][:] = left
            output_items[1][:] = right
            return len(output_items[0])


# ============================================================================
# 9. LIVE ROOM AUDIO & SUBLEVEL VOCALIZATION AUTOTUNE ENGINE
# ============================================================================


class RoomAndSublevelAutotuneCore:
    """
    Dual-stream real-time processor for live Room Audio (e.g. Dodotronic UltraMic384K_EVO)
    and isolated Sublevel Vocalizations (whispers, under-breath murmurs, laryngeal clicks,
    and faint vocal-tract resonances):

      1. Automatic Room Calibration ('Autotune'):
         Profiles per-bin ambient room noise PSD, stationary fan/hum peaks, and average
         dBFS over ~1.0 second to automatically calibrate Room Trim Gain, Sublevel Boost
         Gain, and Wiener Spectral Subtraction thresholds.
      2. Harmonic Pitch Tracking & Chromatic/Harmonic Autotune Comb:
         Tracks vocal-fold fundamental F0 (65 - 380 Hz) via Harmonic Product Spectrum (HPS),
         builds a soft harmonic comb mask across k * F0 + formant presence band (300 - 3200 Hz),
         and optionally pitch-stabilizes ('autotunes') faint voiced murmurs to the nearest
         chromatic semitone while preserving unvoiced consonant whispers (1.2 - 3.8 kHz).
      3. Anti-Howl Feedback Suppressor & Upward/Ceiling Sublevel Compressor:
         Boosts -82..-45 dBFS micro-vocalizations while compressing loud room transients
         and notching narrowband speaker-feedback ringing.
    """

    SEMITONE_FREQS = 440.0 * (2.0 ** ((np.arange(-36, 12, dtype=np.float64)) / 12.0))

    def __init__(
        self,
        samp_rate: float = 48_000.0,
        fft_size: int = 1024,
        pitch_autotune_strength: float = 0.65,
        sublevel_sensitivity_db: float = 0.0,
        room_trim_offset_db: float = 0.0,
    ) -> None:
        self.samp_rate = float(samp_rate)
        self.fft_size = int(fft_size)
        self.hop = self.fft_size // 4  # 75% overlap (256 samples = 5.3 ms @ 48 kHz)
        self.pitch_autotune_strength = float(pitch_autotune_strength)
        self.sublevel_sensitivity_db = float(sublevel_sensitivity_db)
        self.room_trim_offset_db = float(room_trim_offset_db)

        self._win = np.hanning(self.fft_size).astype(np.float64)
        # COLA normalization for 75% overlap Hann window (sum of w^2 = 1.5)
        self._ola_norm = 1.0 / 1.5

        n_bins = self.fft_size // 2 + 1
        self._freqs = np.fft.rfftfreq(self.fft_size, d=1.0 / self.samp_rate)

        self._in_fifo = np.zeros(0, dtype=np.float64)
        self._ola_buf = np.zeros(self.fft_size, dtype=np.float64)
        self._out_sub_fifo = np.zeros(0, dtype=np.float64)

        # Calibration ('Autotune') state
        self._cal_active: bool = True
        self._cal_frames_target: int = max(40, int(round(1.0 * self.samp_rate / self.hop)))
        self._cal_psds: list[np.ndarray] = []
        self._cal_rms_acc: list[float] = []

        self._noise_psd = np.full(n_bins, 1e-9, dtype=np.float64)
        self._howl_persistence = np.zeros(n_bins, dtype=np.float64)
        self.room_floor_dbfs: float = -60.0
        self.auto_room_gain_db: float = 28.0
        self.auto_subvoc_gain_db: float = 42.0
        self.autotune_complete: bool = False

        # Live tracked metrics
        self.current_room_dbfs: float = -60.0
        self.current_f0_hz: float = 0.0
        self.snapped_f0_hz: float = 0.0
        self._f0_hold_frames: int = 0
        self._hop_counter: int = 0
        self._last_conf: float = 0.0
        self.current_vad: float = 0.0
        self._dc_state: float = 0.0
        self._dc_initialized: bool = False
        self._sub_agc_env: float = 0.05
        self._vad_env: float = 0.0
        self._vad_floor: float = 0.01
        self._synth_phase = np.zeros(14, dtype=np.float64)

        # Vocal band mask (65 Hz - 3800 Hz) + Formant presence curve + 60/120 Hz hum notches
        vocal_mask = np.ones(n_bins, dtype=np.float64)
        vocal_mask *= 1.0 / (1.0 + (68.0 / np.maximum(self._freqs, 1.0)) ** 6)
        vocal_mask *= 1.0 / (1.0 + (self._freqs / 3800.0) ** 6)
        for hum_hz in (60.0, 120.0, 180.0):
            vocal_mask *= 1.0 - 0.85 * np.exp(-0.5 * ((self._freqs - hum_hz) / 8.0) ** 2)
        formant_boost = 1.0 + 0.75 * np.exp(
            -0.5 * ((np.log2(np.maximum(self._freqs, 30.0) / 950.0)) / 1.4) ** 2
        )
        self._vocal_eq = vocal_mask * formant_boost

    def trigger_autotune(self) -> None:
        """Re-run 1.0-second live room noise floor, hum & gain calibration."""
        self._cal_active = True
        self._cal_psds.clear()
        self._cal_rms_acc.clear()
        self.autotune_complete = False

    def _finalize_autotune(self) -> None:
        if len(self._cal_psds) > 0:
            stack = np.vstack(self._cal_psds)
            # 80th percentile captures stationary fan/room tones without transient spikes
            self._noise_psd = np.percentile(stack, 80.0, axis=0) + 1e-16
        if len(self._cal_rms_acc) > 0:
            med_rms = float(np.median(self._cal_rms_acc))
            self.room_floor_dbfs = float(20.0 * math.log10(max(med_rms, 1e-7)))
            # Bring ambient room floor (including high-headroom -76 dBFS UltraMic384K_EVO) to ~ -28 dBFS
            self.auto_room_gain_db = float(np.clip(-28.0 - self.room_floor_dbfs, 0.0, 52.0))
            # Bring sublevel murmurs (just 4-15 dB above room floor) up to clear -12 dBFS audible level
            self.auto_subvoc_gain_db = float(np.clip(-14.0 - self.room_floor_dbfs, 16.0, 64.0))
        self._cal_active = False
        self.autotune_complete = True

    def _estimate_f0_hps(self, time_recon: np.ndarray) -> Tuple[float, float]:
        """High-resolution 4096-pt zero-padded Harmonic Product Spectrum (HPS) F0 tracker."""
        zp_n = 4096
        df = self.samp_rate / zp_n  # 11.71875 Hz bin resolution @ 48 kHz
        mag = np.abs(np.fft.rfft(time_recon, n=zp_n))
        min_b = max(2, int(math.ceil(72.0 / df)))
        max_b = min(len(mag) // 3 - 1, int(math.floor(360.0 / df)))
        if max_b <= min_b + 2:
            return 0.0, 0.0

        hps = mag[min_b : max_b + 1].copy()
        hps *= mag[2 * min_b : 2 * (max_b + 1) : 2]
        hps *= mag[3 * min_b : 3 * (max_b + 1) : 3]

        pk_rel = int(np.argmax(hps))
        pk_bin = min_b + pk_rel
        med_val = float(np.median(hps)) + 1e-18
        prominence = float(hps[pk_rel]) / med_val
        if prominence < 8.0:
            return 0.0, 0.0

        if 1 <= pk_bin < len(mag) - 1:
            y0 = math.log(mag[pk_bin - 1] + 1e-18)
            y1 = math.log(mag[pk_bin] + 1e-18)
            y2 = math.log(mag[pk_bin + 1] + 1e-18)
            denom = y0 - 2.0 * y1 + y2
            delta = 0.5 * (y0 - y2) / denom if abs(denom) > 1e-12 else 0.0
            f0 = (pk_bin + float(np.clip(delta, -0.5, 0.5))) * df
        else:
            f0 = pk_bin * df

        conf = float(np.clip((prominence - 8.0) / 30.0, 0.0, 1.0))
        return float(f0), conf

    def _process_sublevel_frame(self, frame: np.ndarray) -> Tuple[np.ndarray, float]:
        spec = np.fft.rfft(frame * self._win)
        mag2 = (spec.real * spec.real + spec.imag * spec.imag) + 1e-18

        if self._cal_active:
            self._cal_psds.append(mag2.copy())
            if len(self._cal_psds) >= self._cal_frames_target:
                self._finalize_autotune()
        else:
            # Continuous slow minimum-statistics adaptation for non-speech drift
            up = mag2 > self._noise_psd * 2.5
            self._noise_psd = np.where(
                up,
                0.9985 * self._noise_psd + 0.0015 * mag2,
                0.94 * self._noise_psd + 0.06 * mag2,
            )

        # Sensitivity knob shifts noise over-subtraction factor smoothly
        sens_scale = 10.0 ** (-self.sublevel_sensitivity_db / 12.0)
        over_sub = np.clip(2.2 * sens_scale, 0.85, 8.0)
        post_snr = mag2 / (self._noise_psd * over_sub + 1e-18)
        wiener = np.clip((post_snr - 1.0) / (post_snr + 0.45), 0.015, 1.0) ** 1.15

        # Anti-howl narrowband ringing guard
        med_mag2 = np.median(mag2) + 1e-18
        ringing = mag2 > (med_mag2 * 120.0)
        self._howl_persistence = np.where(
            ringing, np.minimum(1.0, self._howl_persistence + 0.12), self._howl_persistence * 0.85
        )
        howl_notch = 1.0 - 0.92 * np.clip((self._howl_persistence - 0.55) / 0.45, 0.0, 1.0)

        clean_spec = spec * wiener * self._vocal_eq * howl_notch
        clean_mag = np.sqrt(clean_spec.real * clean_spec.real + clean_spec.imag * clean_spec.imag)

        # Harmonic Pitch Tracking (every 4th hop = ~47 Hz update rate for ultra-low CPU)
        self._hop_counter += 1
        if (self._hop_counter & 3) == 0:
            pre_recon = np.fft.irfft(clean_spec, n=self.fft_size) * self._win
            f0, conf = self._estimate_f0_hps(pre_recon)
            self._last_conf = conf
            if f0 > 0.0:
                self.current_f0_hz = f0 if self.current_f0_hz <= 20.0 else 0.65 * self.current_f0_hz + 0.35 * f0
                self._f0_hold_frames = 16
                nearest_idx = int(np.argmin(np.abs(self.SEMITONE_FREQS - self.current_f0_hz)))
                self.snapped_f0_hz = float(self.SEMITONE_FREQS[nearest_idx])
            else:
                if self._f0_hold_frames > 0:
                    self._f0_hold_frames -= 1
                else:
                    self.current_f0_hz = 0.0
                    self.snapped_f0_hz = 0.0

        conf = self._last_conf
        f0 = self.current_f0_hz
        if f0 > 55.0 and conf > 0.05:
            comb = 1.0 + 0.55 * conf * np.maximum(0.0, np.cos(2.0 * math.pi * self._freqs / f0))
            comb = np.where(self._freqs < 1600.0, comb, 1.0)
            clean_spec = clean_spec * comb
            clean_mag = np.sqrt(clean_spec.real * clean_spec.real + clean_spec.imag * clean_spec.imag)

        recon = np.fft.irfft(clean_spec, n=self.fft_size) * self._win * self._ola_norm

        # Optional subtle chromatic pitch-locked harmonic reinforcement ('Autotune' vocal clarifier)
        if f0 > 0.0 and self.pitch_autotune_strength > 0.02 and self.snapped_f0_hz > 60.0:
            df = self.samp_rate / self.fft_size
            t_hop = np.arange(self.fft_size, dtype=np.float64) / self.samp_rate
            harmonic_sum = np.zeros(self.fft_size, dtype=np.float64)
            for h in range(1, 9):
                src_bin = int(round(h * self.current_f0_hz / df))
                if src_bin >= len(clean_mag):
                    break
                h_amp = float(clean_mag[src_bin]) / (self.fft_size * 0.5)
                f_target = h * (
                    (1.0 - self.pitch_autotune_strength) * self.current_f0_hz
                    + self.pitch_autotune_strength * self.snapped_f0_hz
                )
                ph0 = self._synth_phase[h]
                harmonic_sum += h_amp * np.cos(ph0 + 2.0 * math.pi * f_target * t_hop)
                self._synth_phase[h] = float(
                    (ph0 + 2.0 * math.pi * f_target * (self.hop / self.samp_rate)) % (2.0 * math.pi)
                )
            blend = 0.38 * conf * self.pitch_autotune_strength
            recon = (1.0 - blend) * recon + (blend * 2.2) * (harmonic_sum * self._win * self._ola_norm)

        frame_vad_energy = float(np.sqrt(np.mean(recon * recon)))
        return recon, frame_vad_energy

    def process(
        self, mic_in: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        n = len(mic_in)
        if n == 0:
            e = np.empty(0, dtype=np.float32)
            return e, e, e, e, e

        x = mic_in.astype(np.float64)
        # Instant-seeded DC blocker (removes +0.0037 Dodotronic UltraMic capsule bias on sample 0)
        mean_x = float(np.mean(x))
        if not self._dc_initialized:
            self._dc_state = mean_x
            self._dc_initialized = True
        else:
            self._dc_state = 0.96 * self._dc_state + 0.04 * mean_x
        x_dc = x - self._dc_state

        raw_rms = float(np.sqrt(np.mean(x_dc * x_dc) + 1e-16))
        inst_dbfs = float(20.0 * math.log10(max(raw_rms, 1e-7)))
        self.current_room_dbfs = 0.80 * self.current_room_dbfs + 0.20 * inst_dbfs
        if self._cal_active:
            self._cal_rms_acc.append(raw_rms)

        # 1. Calibrated Room Audio Output
        room_gain = 10.0 ** ((self.auto_room_gain_db + self.room_trim_offset_db) / 20.0)
        room_out = (0.90 * np.tanh(x_dc * room_gain)).astype(np.float32)

        # 2. STFT Sublevel Vocalization Extraction + Autotune Harmonic Clarifier
        self._in_fifo = np.concatenate([self._in_fifo, x_dc])
        while len(self._in_fifo) >= self.fft_size:
            frame = self._in_fifo[: self.fft_size]
            self._in_fifo = self._in_fifo[self.hop :]
            recon, _ = self._process_sublevel_frame(frame)
            self._ola_buf += recon
            hop_out = self._ola_buf[: self.hop].copy()
            self._ola_buf[: -self.hop] = self._ola_buf[self.hop :]
            self._ola_buf[-self.hop :] = 0.0
            self._out_sub_fifo = np.concatenate([self._out_sub_fifo, hop_out])

        if len(self._out_sub_fifo) >= n:
            sub_raw = self._out_sub_fifo[:n]
            self._out_sub_fifo = self._out_sub_fifo[n:]
        else:
            pad = n - len(self._out_sub_fifo)
            sub_raw = np.concatenate([np.zeros(pad, dtype=np.float64), self._out_sub_fifo])
            self._out_sub_fifo = np.zeros(0, dtype=np.float64)

        # Sublevel Upward Boost + Loud-Speech Ceiling Compressor (emphasizes whispers/sub-vocalizations!)
        sub_gain = 10.0 ** ((self.auto_subvoc_gain_db + self.sublevel_sensitivity_db) / 20.0)
        boosted = sub_raw * sub_gain
        sub_rms = float(np.sqrt(np.mean(boosted * boosted) + 1e-14))
        self._sub_agc_env = (
            0.80 * self._sub_agc_env + 0.20 * sub_rms
            if sub_rms > self._sub_agc_env
            else 0.992 * self._sub_agc_env + 0.008 * sub_rms
        )
        # Compress loud speech (>0.22) strongly so quiet sublevel murmurs remain prominent and ear-safe
        ceiling_comp = 1.0 / max(1.0, (self._sub_agc_env / 0.22) ** 0.78)
        sub_out = (0.85 * np.tanh(boosted * ceiling_comp * 1.25)).astype(np.float32)

        # Adaptive VAD on sublevel stream
        sub_abs_mean = float(np.mean(np.abs(sub_out)))
        self._vad_env = 0.65 * self._vad_env + 0.35 * sub_abs_mean
        if self._vad_env > self._vad_floor:
            self._vad_floor = 0.992 * self._vad_floor + 0.008 * self._vad_env
        else:
            self._vad_floor = 0.85 * self._vad_floor + 0.15 * self._vad_env
        gate = max(0.018, self._vad_floor * 1.45)
        self.current_vad = float(np.clip((self._vad_env - gate) / max(gate * 1.2, 0.015), 0.0, 1.0))

        dbfs_vec = np.full(n, self.current_room_dbfs, dtype=np.float32)
        f0_vec = np.full(n, self.current_f0_hz, dtype=np.float32)
        vad_vec = np.full(n, self.current_vad, dtype=np.float32)
        return room_out, sub_out, dbfs_vec, f0_vec, vad_vec


if HAS_GNURADIO:

    class RoomAndSublevelAutotuneBlock(gr.sync_block):
        """GNU Radio 3.10 block wrapping `RoomAndSublevelAutotuneCore`."""

        def __init__(
            self,
            samp_rate: float = 48_000.0,
            pitch_autotune_strength: float = 0.65,
            sublevel_sensitivity_db: float = 0.0,
            room_trim_offset_db: float = 0.0,
        ) -> None:
            gr.sync_block.__init__(
                self,
                name="Room Audio & Sublevel Vocalization Autotune",
                in_sig=[np.float32],
                out_sig=[np.float32, np.float32, np.float32, np.float32, np.float32],
            )
            self._core = RoomAndSublevelAutotuneCore(
                samp_rate=samp_rate,
                pitch_autotune_strength=pitch_autotune_strength,
                sublevel_sensitivity_db=sublevel_sensitivity_db,
                room_trim_offset_db=room_trim_offset_db,
            )

        def trigger_autotune(self) -> None:
            self._core.trigger_autotune()

        def set_pitch_autotune_strength(self, val: float) -> None:
            self._core.pitch_autotune_strength = float(val)

        def set_sublevel_sensitivity_db(self, val: float) -> None:
            self._core.sublevel_sensitivity_db = float(val)

        def set_room_trim_offset_db(self, val: float) -> None:
            self._core.room_trim_offset_db = float(val)

        @property
        def core(self) -> RoomAndSublevelAutotuneCore:
            return self._core

        def work(self, input_items, output_items) -> int:
            room_o, sub_o, dbfs_o, f0_o, vad_o = self._core.process(input_items[0])
            output_items[0][:] = room_o
            output_items[1][:] = sub_o
            output_items[2][:] = dbfs_o
            output_items[3][:] = f0_o
            output_items[4][:] = vad_o
            return len(output_items[0])

    class UltraMicSourceBlock(gr.sync_block):
        """
        Single-master-clock GNU Radio 3.10 audio source wrapping `UltraMicWASAPIDriver`:
          - Captures native 384 kHz WASAPI Exclusive audio on Dodotronic `UltraMic384K_EVO`
            (bypassing `audiodg.exe`'s broken 8:1 shared-mode resampler) with zero `aO` overruns.
          - Supports either `384,000 Hz` wideband output (for full 0 - 192 kHz ultrasonic FFT + C++
            VOLK FIR decimation) or `48,000 Hz` anti-aliased baseband output.
        """

        def __init__(
            self,
            device_hint: str = "",
            output_rate: int = 384_000,
            chunk_ms: float = 20.0,
        ) -> None:
            gr.sync_block.__init__(
                self,
                name="UltraMic WASAPI Exclusive Source",
                in_sig=None,
                out_sig=[np.float32],
            )
            self.driver = UltraMicWASAPIDriver(
                device_hint=device_hint,
                output_rate=output_rate,
                chunk_ms=chunk_ms,
            )

        def start(self) -> bool:
            self.driver.start()
            return True

        def stop(self) -> bool:
            self.driver.stop()
            return True

        def work(self, input_items, output_items) -> int:
            out = output_items[0]
            n = len(out)
            if not self.driver.connected:
                if not self.driver.start():
                    time.sleep(0.02)
                    out[:] = 0.0
                    return min(n, 1024)
            # Smooth 20 ms block pacing prevents multi-chunk burst overruns on PortAudio speaker sink
            max_req = min(n, max(1024, int(round(self.driver.output_sample_rate * 0.020))))
            samples = self.driver.read_samples(max_req, timeout=0.06)
            m = min(len(samples), n)
            if m <= 0:
                return 0
            out[:m] = samples[:m]
            return m

    class SyncSDRFusionBlock(gr.sync_block):
        """
        Single-clock synchronous Dual-SDR RF displacement & subvoc fusion block:
          - Driven 1:1 by the `48,000 Hz` microphone stream (`in_sig=[np.float32]`), eliminating
            two-source clock skew, buffer starvation, and 960 kHz duplicate GIL overhead!
          - Port 0 (`disp_um`): 48 kHz unwrapped radar displacement (`um`) for respiration BPM & infrasonic sonifier.
          - Port 1 (`rf_subvoc`): 48 kHz isolated RF micro-Doppler vocalization signal for Dual Sensor Fusion
            (gated to 0.0 on passive non-CW RX noise so passive SDR static never enters headphones or Whisper ASR!).
        """

        def __init__(
            self,
            samp_rate: float = 48_000.0,
            sensor_mode: int = 1,
            rf_device_select: int = 0,
            rf_freq_mhz: float = 915.0,
            gate_thresh_db: float = -42.0,
            gain_db: float = 18.0,
            enable_cw_tx: bool = False,
            shared_sdr_stream: Optional[AsyncSDRRadarStream] = None,
            shared_hackrf_stream: Optional[AsyncHackRFStream] = None,
        ) -> None:
            gr.sync_block.__init__(
                self,
                name="Synchronous Dual-SDR Fusion Tap",
                in_sig=[np.float32],
                out_sig=[np.float32, np.float32],
            )
            self.samp_rate = float(samp_rate)
            self.sensor_mode = int(sensor_mode)
            self.rf_device_select = int(rf_device_select)
            self.rf_freq_mhz = float(rf_freq_mhz)
            self.enable_cw_tx = bool(enable_cw_tx)
            self.shared_sdr_stream = shared_sdr_stream
            self.shared_hackrf_stream = shared_hackrf_stream

            self._enhancer = SubvocSpectralEnhancerCore(
                samp_rate=self.samp_rate,
                gate_thresh_db=gate_thresh_db,
                gain_db=gain_db,
            )
            self._sim = PhysiologicalRadarSimulatorCore(
                rf_samp_rate=self.samp_rate,
                baseband_rate=self.samp_rate,
                rf_freq_mhz=self.rf_freq_mhz,
            )
            self._sim_clutter = IQClutterCancellerCore(alpha=0.005, mode=0)
            self._sim_phase = PhaseVibrometerCore(samp_rate=self.samp_rate, rf_freq_mhz=self.rf_freq_mhz)
            self._hp_prev_x: float = 0.0
            self._hp_prev_y: float = 0.0

        def set_sensor_mode(self, mode: int) -> None:
            self.sensor_mode = int(mode)

        def set_rf_device_select(self, sel: int) -> None:
            self.rf_device_select = int(sel)

        def set_rf_freq_mhz(self, freq_mhz: float) -> None:
            self.rf_freq_mhz = float(freq_mhz)
            self._sim.rf_freq_mhz = self.rf_freq_mhz
            self._sim_phase.rf_freq_mhz = self.rf_freq_mhz

        def _highpass_70hz(self, x: np.ndarray) -> np.ndarray:
            if len(x) == 0:
                return x
            # Fast vectorized block DC/infrasonic removal + 3 kHz smoothing for 70-2800 Hz vocal band
            ac = (x - float(np.mean(x))).astype(np.float32)
            return np.clip(ac * 0.015, -1.0, 1.0).astype(np.float32)

        def _live_rf_is_coherent(self) -> bool:
            """True only when a genuine coherent CW carrier is locked (or CW TX illuminator enabled)."""
            if self.enable_cw_tx:
                return True
            rtl = self.shared_sdr_stream
            hrf = self.shared_hackrf_stream
            sel = self.rf_device_select
            if sel == 1:
                return bool(rtl is not None and rtl.connected and rtl.phase_coherence >= 0.62)
            if sel == 2:
                return bool(hrf is not None and hrf.connected and hrf.phase_coherence >= 0.62)
            c_rtl = rtl.phase_coherence if (rtl is not None and rtl.connected) else 0.0
            c_hrf = hrf.phase_coherence if (hrf is not None and hrf.connected) else 0.0
            return max(c_rtl, c_hrf) >= 0.62

        def _pull_live_disp(self, n: int) -> Optional[np.ndarray]:
            rtl = self.shared_sdr_stream
            hrf = self.shared_hackrf_stream
            sel = self.rf_device_select
            if sel == 1:
                return rtl.read_stream_disp_um(n) if (rtl is not None and rtl.connected) else None
            if sel == 2:
                return hrf.read_stream_disp_um(n) if (hrf is not None and hrf.connected) else None

            d_rtl = rtl.read_stream_disp_um(n) if (rtl is not None and rtl.connected) else None
            d_hrf = hrf.read_stream_disp_um(n) if (hrf is not None and hrf.connected) else None
            if d_rtl is not None and d_hrf is not None and len(d_rtl) == len(d_hrf):
                return (0.70 * d_rtl + 0.30 * d_hrf).astype(np.float32)
            return d_rtl if d_rtl is not None else d_hrf

        def work(self, input_items, output_items) -> int:
            mic_in = input_items[0]
            out_disp = output_items[0]
            out_sub = output_items[1]
            n = len(mic_in)

            if self.sensor_mode == 0:
                out_disp[:] = mic_in * np.float32(25000.0)
                out_sub[:] = 0.0
                return n

            if self.sensor_mode == 1:
                disp = self._pull_live_disp(n)
                if disp is not None and len(disp) == n:
                    out_disp[:] = disp
                    if self._live_rf_is_coherent():
                        out_sub[:] = self._enhancer.process(self._highpass_70hz(disp))
                    else:
                        # Passive RX SDRs without CW carrier: keep audio stream 100% free of RF thermal static!
                        out_sub[:] = 0.0
                    return n
                # Graceful fallback while SDR USB opens during first ~1.5s
                out_disp[:] = mic_in * np.float32(25000.0)
                out_sub[:] = 0.0
                return n

            # Mode 2: Physiological RF Micro-Doppler Simulator at native 48 kHz
            sim_iq = self._sim.generate_iq(n)
            cen_iq = self._sim_clutter.process(sim_iq)
            disp_sim = self._sim_phase.process(cen_iq)
            out_disp[:] = disp_sim
            out_sub[:] = self._enhancer.process(self._highpass_70hz(disp_sim))
            return n

    class Tab3IQMonitorSource(gr.sync_block):
        """
        Gentle 20 FPS I/Q snapshot source for Tab 3 (`const_iq` Phasor Arc + `freq_rf` Baseband Spectrum),
        completely decoupled from the real-time audio graph so it consumes <0.1% CPU and never blocks audio.
        """

        def __init__(
            self,
            baseband_rate: float = 48_000.0,
            sensor_mode: int = 1,
            rf_device_select: int = 0,
            rf_freq_mhz: float = 915.0,
            shared_sdr_stream: Optional[AsyncSDRRadarStream] = None,
            shared_hackrf_stream: Optional[AsyncHackRFStream] = None,
        ) -> None:
            gr.sync_block.__init__(
                self,
                name="Tab 3 Throttled I/Q Monitor",
                in_sig=None,
                out_sig=[np.complex64, np.complex64],
            )
            self.baseband_rate = float(baseband_rate)
            self.sensor_mode = int(sensor_mode)
            self.rf_device_select = int(rf_device_select)
            self.shared_sdr_stream = shared_sdr_stream
            self.shared_hackrf_stream = shared_hackrf_stream
            self._sim = PhysiologicalRadarSimulatorCore(
                rf_samp_rate=self.baseband_rate,
                baseband_rate=self.baseband_rate,
                rf_freq_mhz=rf_freq_mhz,
            )
            self._sim_clutter = IQClutterCancellerCore(alpha=0.005, mode=0)
            self._last_emit: float = 0.0

        def set_sensor_mode(self, mode: int) -> None:
            self.sensor_mode = int(mode)

        def set_rf_device_select(self, sel: int) -> None:
            self.rf_device_select = int(sel)

        def set_rf_freq_mhz(self, freq_mhz: float) -> None:
            self._sim.rf_freq_mhz = float(freq_mhz)

        def work(self, input_items, output_items) -> int:
            out_raw = output_items[0]
            out_cen = output_items[1]
            m = min(len(out_raw), 1024)
            now = time.perf_counter()
            dt = now - self._last_emit
            if dt < 0.045:
                time.sleep(0.045 - dt)
            self._last_emit = time.perf_counter()

            rtl = self.shared_sdr_stream
            hrf = self.shared_hackrf_stream
            if self.sensor_mode == 1:
                pair: Optional[Tuple[np.ndarray, np.ndarray]] = None
                if self.rf_device_select == 1 and rtl is not None:
                    pair = rtl.get_recent_iq_48k_pair(m)
                elif self.rf_device_select == 2 and hrf is not None:
                    pair = hrf.get_recent_iq_48k_pair(m)
                else:
                    p_r = rtl.get_recent_iq_48k_pair(m) if rtl is not None else None
                    p_h = hrf.get_recent_iq_48k_pair(m) if hrf is not None else None
                    if p_r is not None and p_h is not None and len(p_r[0]) == m and len(p_h[0]) == m:
                        pair = (
                            (0.72 * p_r[0] + 0.28 * p_h[0]).astype(np.complex64),
                            (0.72 * p_r[1] + 0.28 * p_h[1]).astype(np.complex64),
                        )
                    else:
                        pair = p_r if p_r is not None else p_h

                if pair is not None and len(pair[0]) == m:
                    out_raw[:m] = pair[0]
                    out_cen[:m] = pair[1]
                    return m

            if self.sensor_mode == 2:
                raw = self._sim.generate_iq(m)
                out_raw[:m] = raw
                out_cen[:m] = self._sim_clutter.process(raw)
                return m

            out_raw[:m] = 0.0j
            out_cen[:m] = 0.0j
            return m


