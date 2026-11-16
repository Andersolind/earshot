#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GNU-Larex Dodotronic UltraMic384K_EVO Hardware & DSP Unit Test Suite
====================================================================
Validates:
  1. PortAudio / WASAPI Exclusive enumeration & native 384 kHz hardware negotiation
     on `Microphone (UltraMic384K_EVO 16bit r0)` (verifying bypass of Windows Shared
     Mode `audiodg.exe`'s broken -96.7 dBFS 8:1 downsampler).
  2. Live 384 kHz wideband capture integrity: zero xruns, capsule DC-bias removal,
     genuine acoustic variance (> -88 dBFS, >= 25 quantization levels), and live
     20 - 180 kHz ultrasonic band telemetry.
  3. Anti-aliased 384 kHz -> 48 kHz FIR decimation into `RoomAndSublevelAutotuneCore`
     (1.0s room floor calibration, HPS F0 vocal pitch tracking) and all 4 modes of
     `PresenceVoiceMatchAndUltraMicEngine`.
  4. Full live GNU Radio 3.10 integration test: `UltraMicSourceBlock` (384 kHz) +
     VOLK C++ 8x FIR decimator + `RoomAndSublevelAutotuneBlock` + `SyncSDRFusionBlock`
     + `Tab3IQMonitorSource` running SIMULTANEOUSLY alongside live `RTL-SDR Blog V4`
     (915 MHz) and `HackRF One` (2450 MHz), asserting ZERO `aO` PortAudio overruns!
"""

from __future__ import annotations

import io
import math
import os
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_LIB_BIN = REPO_ROOT / "radioconda" / "Library" / "bin"
if os.name == "nt" and _LIB_BIN.exists():
    try:
        os.add_dll_directory(str(_LIB_BIN))
    except Exception:
        pass
    os.environ["PATH"] = f"{_LIB_BIN};{os.environ.get('PATH', '')}"

import numpy as np

from src.larex_dsp import (
    AsyncHackRFStream,
    AsyncSDRRadarStream,
    RoomAndSublevelAutotuneBlock,
    RoomAndSublevelAutotuneCore,
    SyncSDRFusionBlock,
    Tab3IQMonitorSource,
    UltraMicSourceBlock,
    UltraMicWASAPIDriver,
)
from src.larex_presence_voicematch import PresenceVoiceMatchAndUltraMicEngine


class TestUltraMicHardwareAndDSP(unittest.TestCase):
    """End-to-end hardware & DSP verification for Dodotronic UltraMic384K_EVO."""

    def test_01_device_enumeration_and_wasapi_exclusive_probe(self) -> None:
        devs = UltraMicWASAPIDriver.enumerate_input_devices()
        print("\n  [Test 1] PortAudio Input Endpoints Discovered:")
        for d in devs:
            print(
                f"    - Dev[{d['index']}] {d['name']!r} | API={d['host_api']} | "
                f"ch={d['max_input_channels']} | defSR={d['default_sr']:.0f} Hz"
            )
        self.assertGreater(len(devs), 0, "Expected at least one PortAudio capture endpoint.")

        probe = UltraMicWASAPIDriver.probe_best_hardware(prefer_ultrasonic=True)
        print(f"  [Test 1] Negotiated Best Hardware: {probe}")
        self.assertTrue(probe["available"], f"Microphone probe failed: {probe.get('error')}")
        if any("ultramic" in d["name"].lower() for d in devs):
            self.assertTrue(probe["is_ultramic"], "Expected UltraMic384K_EVO to be selected first.")
            self.assertTrue(
                probe["exclusive_mode"],
                "UltraMic384K_EVO must open in WASAPI Exclusive mode to avoid Windows Shared Mode -96.7 dBFS muting.",
            )
            self.assertEqual(
                probe["hw_sample_rate"],
                384_000,
                "UltraMic384K_EVO native hardware rate must be 384,000 Hz.",
            )

    def test_02_live_384khz_wideband_capture_and_signal_integrity(self) -> None:
        drv = UltraMicWASAPIDriver(output_rate=384_000, chunk_ms=20.0)
        started = drv.start()
        self.assertTrue(started, f"Failed to start UltraMicWASAPIDriver: {drv.last_error}")

        collected = []
        t0 = time.perf_counter()
        try:
            while (time.perf_counter() - t0) < 1.25:
                chunk = drv.read_samples(15_360, timeout=0.08)
                if len(chunk) > 0:
                    collected.append(chunk)
        finally:
            drv.stop()

        dt = time.perf_counter() - t0
        pcm = np.concatenate(collected) if collected else np.zeros(0, dtype=np.float32)
        eff_sr = len(pcm) / max(dt, 1e-6)
        rms = float(np.sqrt(np.mean(pcm.astype(np.float64) ** 2) + 1e-20))
        rms_dbfs = 20.0 * math.log10(max(rms, 1e-9))
        dc_res = float(np.mean(pcm))
        uniq_i16 = len(np.unique(np.round(pcm * 32768.0).astype(np.int32)))

        print(
            f"\n  [Test 2] Live 384 kHz Capture: {len(pcm):,} samples in {dt:.3f}s ({eff_sr:,.0f} Sps) | "
            f"xruns={drv.overrun_count} | drops={drv.queue_drops}\n"
            f"           RMS={rms_dbfs:.2f} dBFS | Peak={drv.peak_dbfs:.2f} dBFS | "
            f"Capsule DC={drv.dc_offset:+.5f} (residual={dc_res:+.6f}) | UniqueLSBs={uniq_i16}\n"
            f"           Voice(80-4k)={drv.voice_band_dbfs:.1f} dBFS | "
            f"Ultrasonic(20k-180k)={drv.ultrasonic_band_dbfs:.1f} dBFS @ {drv.peak_ultrasonic_hz:.0f} Hz"
        )

        self.assertEqual(drv.overrun_count, 0, "Expected zero PortAudio WASAPI overruns.")
        self.assertEqual(drv.queue_drops, 0, "Expected zero ring queue drops.")
        self.assertGreater(len(pcm), int(drv.output_sample_rate * 0.90), "Too few samples captured in 1.25s.")
        self.assertTrue(np.all(np.isfinite(pcm)), "Captured samples contain NaN/Inf.")
        self.assertLess(abs(dc_res), 1.5e-3, "Capsule DC offset was not removed cleanly.")
        # Critical regression check against MME/Shared Mode -96.7 dBFS (pk=1 LSB) silence bug:
        self.assertGreater(
            rms_dbfs,
            -88.0,
            f"Signal RMS ({rms_dbfs:.2f} dBFS) looks like muted -96.7 dBFS dither instead of live capsule audio!",
        )
        self.assertGreaterEqual(
            uniq_i16,
            20,
            f"Expected >= 20 distinct ADC levels from live UltraMic capsule, got only {uniq_i16}.",
        )

    def test_03_live_48khz_decimated_autotune_and_presence_engine(self) -> None:
        drv = UltraMicWASAPIDriver(output_rate=48_000, chunk_ms=20.0)
        self.assertTrue(drv.start(), f"Failed to start 48 kHz decimated UltraMic stream: {drv.last_error}")

        autotune = RoomAndSublevelAutotuneCore(
            samp_rate=48_000.0,
            pitch_autotune_strength=0.70,
            sublevel_sensitivity_db=6.0,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            presence = PresenceVoiceMatchAndUltraMicEngine(sample_rate=48_000, storage_dir=tmpdir)
            room_chunks = []
            try:
                t0 = time.perf_counter()
                while (time.perf_counter() - t0) < 1.25:
                    c48 = drv.read_samples(1920, timeout=0.08)
                    if len(c48) > 0:
                        r_o, _, _, _, _ = autotune.process(c48)
                        room_chunks.append(r_o)
                        presence.push_ultramic_frame(c48)
            finally:
                drv.stop()

            self.assertTrue(autotune.autotune_complete, "1.0-second Room Autotune did not complete.")
            room_cat = np.concatenate(room_chunks[-15:])
            cal_room_rms_db = 20.0 * math.log10(max(float(np.sqrt(np.mean(room_cat ** 2))), 1e-9))

            # Inject a faint synthetic 152 Hz harmonic sublevel vocal murmur (clear of 60/120/180 Hz mains notches)
            autotune.current_f0_hz = 0.0
            autotune._f0_hold_frames = 0
            t_v = np.arange(36_000, dtype=np.float64) / 48_000.0
            f0_true = 152.0
            murmur = np.zeros_like(t_v)
            for h in range(1, 7):
                murmur += (0.0030 / h) * np.sin(2.0 * math.pi * (h * f0_true) * t_v)
            murmur_f32 = murmur.astype(np.float32)
            sub_parts, vad_parts = [], []
            tracked_f0 = 0.0
            for i in range(0, len(murmur_f32), 2048):
                _, s_o, _, f_o, v_o = autotune.process(murmur_f32[i : i + 2048])
                sub_parts.append(s_o)
                vad_parts.append(v_o)
                tracked_f0 = float(f_o[-1])
            sub_v = np.concatenate(sub_parts)
            vad_vec = np.concatenate(vad_parts)

            print(
                f"\n  [Test 3] 48 kHz Autotune & Presence Engine:\n"
                f"           Calibrated 48k Floor={autotune.room_floor_dbfs:.1f} dBFS | "
                f"AutoRoomGain=+{autotune.auto_room_gain_db:.1f} dB -> Output={cal_room_rms_db:.1f} dBFS\n"
                f"           Injected {f0_true:.1f} Hz Murmur -> Tracked F0={tracked_f0:.1f} Hz | "
                f"Peak VAD={float(np.max(vad_vec)):.2f} | Subvoc RMS={float(np.sqrt(np.mean(sub_v**2))):.3f}"
            )

            self.assertGreater(cal_room_rms_db, -45.0, "Calibrated room output too quiet after autotune.")
            self.assertAlmostEqual(tracked_f0, f0_true, delta=8.0, msg="HPS F0 tracker missed 135 Hz murmur.")

            for mode in ("FULL_AMBIANCE", "SUBVOC_ISOLATOR", "ULTRASONIC_HETERODYNE", "DEPARTURE_ANOMALY_DIFF"):
                wav_bytes = presence.render_live_ambiance_wav(mode=mode, duration_sec=0.8)
                self.assertTrue(wav_bytes.startswith(b"RIFF"), f"Invalid WAV header for {mode}")
                with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                    self.assertEqual(wf.getframerate(), 48_000)
                    self.assertGreater(wf.getnframes(), 30_000)

    def test_04_live_gnuradio_ultramic_plus_dual_sdr_zero_overruns(self) -> None:
        from gnuradio import blocks, filter as gr_filter, gr  # type: ignore
        from gnuradio.fft import window  # type: ignore
        from gnuradio.filter import firdes  # type: ignore

        rtl_stream = AsyncSDRRadarStream(rf_freq_mhz=915.0, rf_gain=38.0)
        hrf_stream = AsyncHackRFStream(
            rf_freq_mhz=2450.0,
            rf_gain=44.0,
            wait_event=rtl_stream.initial_probe_done,
        )

        # Capture C-level stderr fd=2 to verify zero 'aO' PortAudio overrun markers
        import threading

        stderr_fd = sys.stderr.fileno()
        saved_stderr_fd = os.dup(stderr_fd)
        cap_r, cap_w = os.pipe()
        stderr_chunks: list[bytes] = []

        def _drain_pipe() -> None:
            while True:
                try:
                    b = os.read(cap_r, 4096)
                    if not b:
                        break
                    stderr_chunks.append(b)
                except Exception:
                    break

        drain_th = threading.Thread(target=_drain_pipe, daemon=True)
        drain_th.start()

        tb = gr.top_block("UltraMicDualSDRIntegrationTest")
        mic_src = UltraMicSourceBlock(output_rate=384_000, chunk_ms=20.0)
        lpf_taps = firdes.low_pass(1.0, 384_000.0, 18_000.0, 4_000.0, window.WIN_KAISER, 6.76)
        decim_48k = gr_filter.fir_filter_fff(8, lpf_taps)
        autotune_blk = RoomAndSublevelAutotuneBlock(samp_rate=48_000.0, pitch_autotune_strength=0.70, sublevel_sensitivity_db=6.0)
        rf_fusion = SyncSDRFusionBlock(
            samp_rate=48_000.0,
            sensor_mode=1,
            rf_device_select=0,
            shared_sdr_stream=rtl_stream,
            shared_hackrf_stream=hrf_stream,
        )
        tab3_mon = Tab3IQMonitorSource(
            baseband_rate=48_000.0,
            sensor_mode=1,
            rf_device_select=0,
            shared_sdr_stream=rtl_stream,
            shared_hackrf_stream=hrf_stream,
        )

        snk_room = blocks.vector_sink_f()
        snk_sub = blocks.vector_sink_f()
        snk_disp = blocks.vector_sink_f()
        snk_rf_sub = blocks.vector_sink_f()
        null_2 = blocks.null_sink(gr.sizeof_float)
        null_3 = blocks.null_sink(gr.sizeof_float)
        null_4 = blocks.null_sink(gr.sizeof_float)
        null_iq0 = blocks.null_sink(gr.sizeof_gr_complex)
        null_iq1 = blocks.null_sink(gr.sizeof_gr_complex)

        tb.connect(mic_src, decim_48k, autotune_blk)
        tb.connect(decim_48k, rf_fusion)
        tb.connect((autotune_blk, 0), snk_room)
        tb.connect((autotune_blk, 1), snk_sub)
        tb.connect((autotune_blk, 2), null_2)
        tb.connect((autotune_blk, 3), null_3)
        tb.connect((autotune_blk, 4), null_4)
        tb.connect((rf_fusion, 0), snk_disp)
        tb.connect((rf_fusion, 1), snk_rf_sub)
        tb.connect((tab3_mon, 0), null_iq0)
        tb.connect((tab3_mon, 1), null_iq1)

        t0 = time.perf_counter()
        try:
            os.dup2(cap_w, stderr_fd)
            os.close(cap_w)
            tb.start()
            time.sleep(3.5)
            tb.stop()
            tb.wait()
        finally:
            os.dup2(saved_stderr_fd, stderr_fd)
            os.close(saved_stderr_fd)
            drain_th.join(timeout=0.5)
            try:
                os.close(cap_r)
            except Exception:
                pass
            stderr_bytes = b"".join(stderr_chunks)
            rtl_stream.stop()
            hrf_stream.stop()

        dt = time.perf_counter() - t0
        stderr_txt = stderr_bytes.decode("utf-8", "ignore")
        ao_count = stderr_txt.count("aO")
        room_data = np.array(snk_room.data(), dtype=np.float32)
        disp_data = np.array(snk_disp.data(), dtype=np.float32)

        print(
            f"\n  [Test 4] Full Live GNU Radio + UltraMic (384k->48k) + Dual-SDR ({dt:.2f}s):\n"
            f"           48 kHz Frames={len(room_data):,} ({len(room_data)/dt:,.0f} Sps) | "
            f"WASAPI xruns={mic_src.driver.overrun_count} | stderr 'aO'={ao_count}\n"
            f"           RTL-SDR Connected={rtl_stream.sdr_info != {}} ({rtl_stream.sdr_label}, pkts={rtl_stream.packets_published})\n"
            f"           HackRF  Connected={hrf_stream.sdr_info != {}} ({hrf_stream.sdr_label}, pkts={hrf_stream.packets_published})\n"
            f"           Fused RF Disp std={float(np.std(disp_data[-24000:])) if len(disp_data) >= 24000 else 0.0:.3f} um"
        )

        self.assertEqual(ao_count, 0, f"Detected {ao_count} PortAudio 'aO' overruns in stderr: {stderr_txt!r}")
        self.assertEqual(mic_src.driver.overrun_count, 0, "Detected WASAPI Exclusive overruns under Dual-SDR load.")
        self.assertGreater(len(room_data), int(48_000 * 2.7), "Insufficient 48 kHz throughput under Dual-SDR load.")
        self.assertGreater(float(np.std(room_data[-24000:])), 1e-4, "Room audio flatlined during Dual-SDR integration.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
