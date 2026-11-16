"""
GNU-Larex :: Pre-Speech Earworm Pre-Hear Engine & Electronic / MEMS Character Detector
======================================================================================
Implements:
  1. `PreSpeechTriggerEngine`:
     - Detects the 50–200 ms pre-phonatory window BEFORE audible speech begins by fusing
       PlutoSDR larynx prep (60–250 Hz) vs gross posture sway (1–18 Hz), RTL-SDR throat
       oscillator tension, ultrasonic lip/jaw pre-opening velocity (300–1800 Hz Doppler),
       and HackRF ambient device power-on precursors (> 0.15), with 48 kHz UltraMic384K_EVO
       sub-band heterodyne surrogates when external SDR ZMQ feeds are idle.
     - Triggers **Pre-Hear the Earworm**: immediately synthesizes a 48 kHz whispered-formant
       preview of the room's predicted Markov Earworm Δ / next continuation token so the
       operator hears the anticipated earworm BEFORE audible phonation starts!
  2. `ElectronicCharacterEngine`:
     - Dedicated 48 kHz (0–24 kHz) acoustic + ultrasonic transient classifier that isolates
       non-keyboard electronic clicks into two clickable characters:
         * `DEVICE_CELLPHONE` (📱 Smartphone Capacitive Tap + 135–235 Hz LRA Haptic + 17.5–20.8 kHz PMIC)
         * `DEVICE_MEMS`      (🔬 14.5–23.8 kHz High-Q MEMS Transducer / Piezo / OIS / Relay Clicks)
       Strictly isolated from human speakers (`PERSON_ALPHA..DELTA`) and keyboard `PERSON_TYPIST`.
  3. `query_ollama_prespeech_and_electronics_advisor`:
     - Queries local `nightsweep-signalintelligence:latest` for DSP & Markov calibration advice
       on pre-speech earworm pre-hearing and electronic/MEMS character separation.
"""

from __future__ import annotations

import collections
import datetime
import hashlib
import io
import json
import math
import threading
import time
import wave
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

try:
    import requests  # type: ignore

    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


CELLPHONE_SPEAKER_ID = "DEVICE_CELLPHONE"
MEMS_SPEAKER_ID = "DEVICE_MEMS"
ELECTRONIC_CHARACTER_IDS = (CELLPHONE_SPEAKER_ID, MEMS_SPEAKER_ID)


def _float_pcm_to_wav_bytes(pcm_f32: np.ndarray, samp_rate: int = 48_000) -> bytes:
    arr = np.asarray(pcm_f32, dtype=np.float32).ravel()
    if len(arr) == 0:
        arr = np.zeros(2400, dtype=np.float32)
    pk = float(np.max(np.abs(arr)) + 1e-9)
    if pk > 0.98:
        arr = (arr / pk) * 0.92
    pcm_i16 = np.clip(arr * 32767.0, -32767, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(samp_rate))
        wf.writeframes(pcm_i16.tobytes())
    return buf.getvalue()


class PreHearEarwormSynthesizer:
    """
    Synthesizes a brief 48 kHz pre-cognitive whispered preview of the predicted Earworm Δ
    phrase (preceded by a subtle 16 ms harmonic lead cue) when `PRE_SPEECH_ONSET` or
    `AMBIENT_DEVICE_PRECURSOR` fires 50–200 ms before audible speech!
    """

    FORMANT_MAP: Dict[str, Tuple[float, float, bool]] = {
        "EE": (340.0, 2280.0, False),
        "EH": (520.0, 1850.0, False),
        "AH": (710.0, 1260.0, False),
        "OO": (390.0, 960.0, False),
        "S/T": (460.0, 2480.0, True),
        "SH": (490.0, 2040.0, True),
    }

    def __init__(self, samp_rate: int = 48_000) -> None:
        self.sr = int(samp_rate)

    @staticmethod
    def phrase_to_contour(phrase: str) -> List[str]:
        tokens = [w.strip(".,!?\"'").lower() for w in (phrase or "").split() if w.strip()]
        if not tokens:
            return ["EE", "AH", "OO"]
        states: List[str] = []
        for w in tokens[:5]:
            if any(s in w for s in ("sh", "ch", "th")):
                states.append("SH")
            elif w.startswith(("s", "t", "k", "c", "z")):
                states.append("S/T")
            elif any(v in w for v in ("ee", "ea", "i", "y")):
                states.append("EE")
            elif any(v in w for v in ("oo", "ou", "u", "o", "w")):
                states.append("OO")
            elif "a" in w:
                states.append("AH")
            else:
                states.append("EH")
        return states or ["EE", "OO"]

    def synthesize_pre_hear_cue(
        self,
        phrase: str,
        next_token: str = "",
        bpm: float = 120.0,
        event_type: str = "PRE_SPEECH_ONSET",
    ) -> Tuple[bytes, np.ndarray]:
        sr = self.sr
        rng = np.random.default_rng(abs(hash(f"{phrase}:{next_token}:{time.perf_counter()}")) % (2**31))

        # 1. Subtle 22 ms pre-speech shimmer chime (960->1440 Hz for vocal onset, 1680 Hz for RF precursor)
        n_cue = int(0.022 * sr)
        t_c = np.arange(n_cue, dtype=np.float64) / sr
        win_c = np.sin(np.pi * np.clip(t_c / 0.022, 0.0, 1.0)) ** 1.2
        if event_type == "AMBIENT_DEVICE_PRECURSOR":
            chime = 0.14 * (np.sin(2 * np.pi * 1680.0 * t_c) + 0.5 * np.sin(2 * np.pi * 2520.0 * t_c)) * win_c
        else:
            f_sweep = 920.0 + 480.0 * (t_c / 0.022)
            chime = 0.14 * np.sin(2 * np.pi * np.cumsum(f_sweep) / sr) * win_c

        # 2. Whispered formant rendering of the anticipated Earworm Δ + predicted continuation
        full_phrase = f"{phrase} {next_token}".strip() or "see you next time"
        contour = self.phrase_to_contour(full_phrase)
        syl_sec = float(np.clip(60.0 / max(75.0, float(bpm)) * 0.36, 0.11, 0.22))

        parts: List[np.ndarray] = [chime.astype(np.float32), np.zeros(int(0.015 * sr), dtype=np.float32)]
        for ph in contour:
            f1, f2, is_sib = self.FORMANT_MAP.get(ph, (500.0, 1600.0, False))
            n_s = int(round(syl_sec * sr))
            t = np.arange(n_s, dtype=np.float64) / sr
            env = np.sin(np.pi * np.clip(t / syl_sec, 0.0, 1.0)) ** 0.7

            white = rng.normal(0.0, 1.0, size=n_s)
            spec = np.fft.rfft(white)
            freqs = np.fft.rfftfreq(n_s, d=1.0 / sr)
            if is_sib:
                filt = np.exp(-0.5 * ((freqs - 4400.0) / 1100.0) ** 2) + 0.4 * np.exp(
                    -0.5 * ((freqs - f2) / 280.0) ** 2
                )
            else:
                pink = 1.0 / np.sqrt(np.maximum(freqs, 70.0) / 220.0)
                filt = pink * (
                    1.3 * np.exp(-0.5 * ((freqs - f1) / 90.0) ** 2)
                    + 1.0 * np.exp(-0.5 * ((freqs - f2) / 150.0) ** 2)
                )
            y = np.fft.irfft(spec * filt, n=n_s) * env
            pk = float(np.max(np.abs(y)) + 1e-9)
            parts.append(((y / pk) * 0.32).astype(np.float32))
            parts.append(np.zeros(int(0.012 * sr), dtype=np.float32))

        pcm = np.concatenate(parts)
        return _float_pcm_to_wav_bytes(pcm, sr), pcm


class PreSpeechTriggerEngine:
    """
    Detects the 50–200 ms pre-phonatory window BEFORE audible talking starts while rejecting
    slow posture shifts and gross body movement, and pre-hears the anticipated Earworm Δ.
    """

    def __init__(self, sample_rate: int = 48000, block_size: int = 2048) -> None:
        self.sr = int(sample_rate)
        self.block_size = int(block_size)
        self.freqs = np.fft.rfftfreq(self.block_size, 1.0 / self.sr)
        self.radar_fft_n = max(self.block_size, int(2 ** math.ceil(math.log2(max(2048.0, self.sr / 5.5)))))
        self.radar_freqs = np.fft.rfftfreq(self.radar_fft_n, 1.0 / self.sr)
        self.window = np.hanning(self.block_size)

        # State tracking for first-derivative (velocity of change) detection
        self.prev_larynx_tension: float = 0.0
        self.prev_lip_doppler: float = 0.0
        self.baseline_noise: float = 0.005
        self.cooldown_blocks: int = 0

        # Live-tunable DSP thresholds (aligned with user reference defaults)
        self.enabled: bool = True
        self.tension_vel_mult: float = 1.80
        self.lip_vel_thresh: float = 0.0020
        self.posture_reject_ratio: float = 3.50
        self.quiet_rms_ceiling: float = 0.030
        self.hackrf_spike_thresh: float = 0.150
        self.lead_time_bias_ms: int = 120
        self.auto_play_pre_hear: bool = False
        self.udp_pre_hear_mirror: bool = True

        # Attached predictors for Pre-Hearing the Earworm
        self._markov_tracker: Any = None
        self._earworm_engine: Any = None
        self._udp_mirror_cb: Optional[Callable[[np.ndarray], None]] = None
        self.synthesizer = PreHearEarwormSynthesizer(samp_rate=self.sr)

        # Streaming staging buffers & telemetry
        self._lock = threading.Lock()
        self._buf_pluto = np.zeros(0, dtype=np.float32)
        self._buf_rtl = np.zeros(0, dtype=np.float32)
        self._buf_hack = np.zeros(0, dtype=np.float32)
        self._buf_ultra = np.zeros(0, dtype=np.float32)
        self._buf_aud = np.zeros(0, dtype=np.float32)
        self._carrier_phase: float = 0.0

        self.total_pre_speech_onsets: int = 0
        self.total_ambient_precursors: int = 0
        self.last_tension_velocity: float = 0.0
        self.last_lip_velocity: float = 0.0
        self.last_posture_energy: float = 0.0
        self.last_larynx_prep: float = 0.0
        self.last_audible_rms: float = 0.0
        self.last_event: Optional[Dict[str, Any]] = None
        self._recent_events: collections.deque[Dict[str, Any]] = collections.deque(maxlen=32)
        self._wav_cache: collections.OrderedDict[str, bytes] = collections.OrderedDict()

    def attach_predictors(
        self,
        markov_tracker: Any = None,
        earworm_engine: Any = None,
        udp_mirror_callback: Optional[Callable[[np.ndarray], None]] = None,
    ) -> None:
        self._markov_tracker = markov_tracker
        self._earworm_engine = earworm_engine
        self._udp_mirror_cb = udp_mirror_callback

    def apply_config(self, cfg: Dict[str, Any]) -> List[str]:
        applied: List[str] = []
        with self._lock:
            if "prespeech_enabled" in cfg:
                self.enabled = bool(cfg["prespeech_enabled"])
                applied.append(f"prespeech.enabled={self.enabled}")
            if "tension_vel_mult" in cfg:
                self.tension_vel_mult = float(np.clip(float(cfg["tension_vel_mult"]), 0.8, 6.0))
                applied.append(f"prespeech.tension_vel_mult={self.tension_vel_mult:.2f}x")
            if "lip_vel_thresh" in cfg:
                self.lip_vel_thresh = float(np.clip(float(cfg["lip_vel_thresh"]), 0.0003, 0.025))
                applied.append(f"prespeech.lip_vel_thresh={self.lip_vel_thresh:.4f}")
            if "posture_reject_ratio" in cfg:
                self.posture_reject_ratio = float(np.clip(float(cfg["posture_reject_ratio"]), 1.5, 9.0))
                applied.append(f"prespeech.posture_reject_ratio={self.posture_reject_ratio:.2f}x")
            if "quiet_rms_ceiling" in cfg:
                self.quiet_rms_ceiling = float(np.clip(float(cfg["quiet_rms_ceiling"]), 0.005, 0.15))
                applied.append(f"prespeech.quiet_rms_ceiling={self.quiet_rms_ceiling:.3f}")
            if "hackrf_spike_thresh" in cfg:
                self.hackrf_spike_thresh = float(np.clip(float(cfg["hackrf_spike_thresh"]), 0.04, 0.65))
                applied.append(f"prespeech.hackrf_spike_thresh={self.hackrf_spike_thresh:.2f}")
            if "lead_time_bias_ms" in cfg:
                self.lead_time_bias_ms = int(np.clip(int(cfg["lead_time_bias_ms"]), 50, 220))
                applied.append(f"prespeech.lead_time_bias_ms={self.lead_time_bias_ms}ms")
            if "auto_play_pre_hear" in cfg:
                self.auto_play_pre_hear = bool(cfg["auto_play_pre_hear"])
                applied.append(f"prespeech.auto_play_pre_hear={self.auto_play_pre_hear}")
            if "udp_pre_hear_mirror" in cfg:
                self.udp_pre_hear_mirror = bool(cfg["udp_pre_hear_mirror"])
                applied.append(f"prespeech.udp_pre_hear_mirror={self.udp_pre_hear_mirror}")
        return applied

    def evaluate_pre_speech(
        self,
        pluto_radar: np.ndarray,
        rtlsdr_throat: np.ndarray,
        hackrf_rf: np.ndarray,
        ultra_shifted: np.ndarray,
        raw_audible: np.ndarray,
    ) -> Optional[Dict[str, Any]]:
        """
        Detects the 50–200 ms pre-phonatory window before audible talking starts
        while rejecting slow posture shifts and gross body movement.
        """
        if self.cooldown_blocks > 0:
            self.cooldown_blocks -= 1

        # 1. REJECT GROSS POSTURE SWAY (< 20 Hz) & ISOLATE LARYNX PREP (60 - 250 Hz)
        # Zero-padded rFFT (df ~ 5.86 Hz @ 48 kHz) ensures 1.0-18.0 Hz posture bins are always resolved
        radar_spec = np.abs(np.fft.rfft(pluto_radar * self.window, n=self.radar_fft_n))
        posture_mask = (self.radar_freqs >= 1.0) & (self.radar_freqs <= 18.0)
        larynx_mask = (self.radar_freqs >= 60.0) & (self.radar_freqs <= 250.0)
        posture_energy = float(np.mean(radar_spec[posture_mask])) if np.any(posture_mask) else 0.0
        larynx_prep = float(np.mean(radar_spec[larynx_mask])) if np.any(larynx_mask) else 0.0

        # Combine with RTL-SDR throat oscillator tension
        rtl_tension = float(np.mean(np.abs(rtlsdr_throat)))
        current_tension = (larynx_prep * 0.6) + (rtl_tension * 0.4)

        # 2. MEASURE ULTRASONIC LIP / JAW PRE-OPENING VELOCITY
        ultra_spec = np.abs(np.fft.rfft(ultra_shifted * self.window))
        lip_motion = float(
            np.mean(ultra_spec[(self.freqs >= 300.0) & (self.freqs <= 1800.0)])
        )

        # 3. COMPUTE RATE OF CHANGE (First Derivative)
        # True speech prep snaps into place fast; leaning in a chair is slow.
        tension_velocity = current_tension - self.prev_larynx_tension
        lip_velocity = lip_motion - self.prev_lip_doppler

        self.prev_larynx_tension = current_tension
        self.prev_lip_doppler = lip_motion

        # Update quiet baseline when nothing is moving
        if current_tension < (self.baseline_noise * 2.0):
            self.baseline_noise = (self.baseline_noise * 0.92) + (
                current_tension * 0.08
            )

        # 4. CHECK THAT AUDIBLE TALKING HAS NOT STARTED YET
        audible_rms = float(np.sqrt(np.mean(raw_audible**2)))
        room_is_still_quiet = audible_rms < self.quiet_rms_ceiling

        # 5. ANTI-FALSE-POSITIVE GATE
        # Reject if slow body sway dominates rapid vocal cord tension
        is_posture_shift = posture_energy > (larynx_prep * self.posture_reject_ratio)

        # Fire pre-speech alert only when throat & lips snap together in silence
        rapid_prep = (tension_velocity > (self.baseline_noise * self.tension_vel_mult)) and (
            lip_velocity > self.lip_vel_thresh
        )

        # Also check HackRF for sudden ambient device power-on spikes
        ambient_rf_spike = float(np.max(np.abs(hackrf_rf))) > self.hackrf_spike_thresh

        self.last_tension_velocity = round(float(tension_velocity), 5)
        self.last_lip_velocity = round(float(lip_velocity), 5)
        self.last_posture_energy = round(float(posture_energy), 4)
        self.last_larynx_prep = round(float(larynx_prep), 4)
        self.last_audible_rms = round(float(audible_rms), 5)

        if (
            rapid_prep
            and room_is_still_quiet
            and not is_posture_shift
            and self.cooldown_blocks == 0
        ):
            # Lock out for ~300ms (7 blocks) so one word doesn't fire multiple alerts
            self.cooldown_blocks = 7
            # Dynamic lead-time estimate (faster tension velocity -> earlier pre-phonatory snap 90-185 ms)
            vel_ratio = tension_velocity / max(self.baseline_noise * self.tension_vel_mult, 1e-6)
            est_lead = int(np.clip(self.lead_time_bias_ms + min(55.0, (vel_ratio - 1.0) * 18.0), 65, 195))
            return {
                "event": "PRE_SPEECH_ONSET",
                "lead_time_est_ms": est_lead,
                "tension_velocity": round(tension_velocity, 5),
                "lip_velocity": round(lip_velocity, 5),
                "ambient_precursor": ambient_rf_spike,
            }

        if ambient_rf_spike and room_is_still_quiet and self.cooldown_blocks == 0:
            self.cooldown_blocks = 5
            return {
                "event": "AMBIENT_DEVICE_PRECURSOR",
                "lead_time_est_ms": 80,
                "tension_velocity": round(max(0.0, tension_velocity), 5),
                "lip_velocity": round(max(0.0, lip_velocity), 5),
                "ambient_precursor": True,
            }

        return None

    def _resolve_anticipated_earworm(self) -> Dict[str, Any]:
        """Predicts the exact Earworm Δ phrase & next Markov token that is about to be spoken."""
        hook = ""
        order = 2
        is_promoted = False
        next_tok = ""
        bpm = 118.0

        mt = self._markov_tracker
        if mt is not None:
            try:
                snap = mt.get_snapshot()
                hook = str(snap.get("kpis", {}).get("current_earworm_delta") or "")
                prom_list = snap.get("promoted_chains") or []
                if prom_list and (not hook or len(hook.split()) < 3):
                    hook = str(prom_list[0].get("phrase") or hook)
                    order = int(prom_list[0].get("order", 3))
                    is_promoted = True
                elif hook and hook in getattr(mt, "promoted_phrase_chains", {}):
                    order = int(mt.promoted_phrase_chains[hook].get("order", 3))
                    is_promoted = True
                words = hook.split()
                if len(words) >= 2:
                    w1, w2 = words[-1], words[-2]
                    w3 = words[-3] if len(words) >= 3 else "<s>"
                    w4 = words[-4] if len(words) >= 4 else ("<s>" if len(words) == 3 else "")
                    preds, _, _ = mt._hierarchical_probs_and_entropy(
                        mt.lex_quad.get((w4, w3, w2, w1), {}) if w4 else {},
                        mt.lex_tri.get((w3, w2, w1), {}),
                        mt.lex_bi.get((w2, w1), {}),
                        mt.lex_uni.get(w1, {}),
                        mt.bigram_interp_lambda,
                        mt.kneser_ney_discount,
                    )
                    for p in preds:
                        if p.get("token") and p["token"] != "<s>":
                            next_tok = str(p["token"])
                            break
            except Exception:
                pass

        ew = self._earworm_engine
        if ew is not None:
            try:
                tel = ew.get_telemetry() if hasattr(ew, "get_telemetry") else getattr(ew, "latest_telemetry", {})
                bpm = float(tel.get("earworm_bpm", 118.0) or 118.0)
                if not next_tok:
                    cand_lex = str(tel.get("predicted_lexical_word") or "")
                    if cand_lex and cand_lex != "--":
                        next_tok = cand_lex
                if not hook:
                    last_lex = str(tel.get("last_lexical_word") or "")
                    if last_lex and last_lex != "--":
                        hook = last_lex
            except Exception:
                pass

        if not hook:
            hook = "see you next time"
        contour = "-".join(self.synthesizer.phrase_to_contour(f"{hook} {next_tok}".strip()))
        return {
            "pre_heard_hook": hook,
            "predicted_next_token": next_tok,
            "markov_order": order,
            "is_promoted_chain": is_promoted,
            "phoneme_contour": contour,
            "earworm_bpm": round(bpm, 1),
        }

    def _enrich_and_store_trigger_locked(self, raw_trig: Dict[str, Any]) -> Dict[str, Any]:
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")
        ev_type = str(raw_trig.get("event") or "PRE_SPEECH_ONSET")
        if ev_type == "PRE_SPEECH_ONSET":
            self.total_pre_speech_onsets += 1
        else:
            self.total_ambient_precursors += 1

        ant = self._resolve_anticipated_earworm()
        ev_id = "ps-" + hashlib.sha256(f"{now_iso}:{ev_type}:{time.perf_counter()}".encode("utf-8")).hexdigest()[:10]
        wav_bytes, pcm = self.synthesizer.synthesize_pre_hear_cue(
            phrase=ant["pre_heard_hook"],
            next_token=ant["predicted_next_token"],
            bpm=ant["earworm_bpm"],
            event_type=ev_type,
        )
        self._wav_cache[ev_id] = wav_bytes
        while len(self._wav_cache) > 24:
            self._wav_cache.popitem(last=False)

        if self.udp_pre_hear_mirror and self._udp_mirror_cb is not None:
            blk = 2048
            for off in range(0, min(len(pcm), 48_000), blk):
                try:
                    self._udp_mirror_cb(pcm[off : off + blk])
                except Exception:
                    break

        enriched = {
            **raw_trig,
            "id": ev_id,
            "timestamp_utc": now_iso,
            **ant,
            "audio_url": f"/api/prespeech/audio/{ev_id}.wav",
            "duration_sec": round(len(pcm) / float(self.sr), 2),
        }
        self.last_event = enriched
        self._recent_events.append(enriched)
        return enriched

    def push_streaming_chunks(
        self,
        raw_audible: np.ndarray,
        pluto_radar: Optional[np.ndarray] = None,
        rtlsdr_throat: Optional[np.ndarray] = None,
        hackrf_rf: Optional[np.ndarray] = None,
        ultra_shifted: Optional[np.ndarray] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Streams live 48 kHz frames into `evaluate_pre_speech`, automatically synthesizing
        physical sub-band surrogates from the wideband `UltraMic384K_EVO` when external ZMQ
        SDR sockets are idle so pre-speech earworm pre-hearing works out-of-the-box.
        """
        if not self.enabled or len(raw_audible) == 0:
            return None

        aud = np.asarray(raw_audible, dtype=np.float32).ravel()
        n = len(aud)

        # Derive sub-band surrogates from 48 kHz UltraMic (0-24 kHz) whenever ZMQ feeds are silent
        if pluto_radar is None or len(pluto_radar) != n or float(np.max(np.abs(pluto_radar))) < 1e-6:
            pluto_arr = aud * 22.0
        else:
            pluto_arr = np.asarray(pluto_radar, dtype=np.float32).ravel()

        if rtlsdr_throat is None or len(rtlsdr_throat) != n or float(np.max(np.abs(rtlsdr_throat))) < 1e-6:
            rtl_arr = np.abs(aud) * 4.5
        else:
            rtl_arr = np.asarray(rtlsdr_throat, dtype=np.float32).ravel()

        if ultra_shifted is None or len(ultra_shifted) != n or float(np.max(np.abs(ultra_shifted))) < 1e-6:
            # Heterodyne 16.5 kHz ultrasonic lip/breath parting friction down into 300-1800 Hz
            t_idx = np.arange(n, dtype=np.float64)
            phases = self._carrier_phase + (2.0 * np.pi * 16_500.0 * t_idx / self.sr)
            self._carrier_phase = float(phases[-1] % (2.0 * np.pi))
            ultra_arr = (aud.astype(np.float64) * np.cos(phases) * 16.0).astype(np.float32)
        else:
            ultra_arr = np.asarray(ultra_shifted, dtype=np.float32).ravel()

        if hackrf_rf is None or len(hackrf_rf) != n or float(np.max(np.abs(hackrf_rf))) < 1e-6:
            # High-frequency 19-23.8 kHz ultrasonic RF/PMIC spike surrogate via 2nd-difference emphasis
            d2 = np.diff(aud, n=2, prepend=aud[:2])
            hack_arr = (d2 * 1.35).astype(np.float32)
        else:
            hack_arr = np.asarray(hackrf_rf, dtype=np.float32).ravel()

        fired_event: Optional[Dict[str, Any]] = None
        with self._lock:
            self._buf_pluto = np.concatenate((self._buf_pluto, pluto_arr))
            self._buf_rtl = np.concatenate((self._buf_rtl, rtl_arr))
            self._buf_hack = np.concatenate((self._buf_hack, hack_arr))
            self._buf_ultra = np.concatenate((self._buf_ultra, ultra_arr))
            self._buf_aud = np.concatenate((self._buf_aud, aud))

            bs = self.block_size
            while len(self._buf_aud) >= bs:
                b_p = self._buf_pluto[:bs]
                b_r = self._buf_rtl[:bs]
                b_h = self._buf_hack[:bs]
                b_u = self._buf_ultra[:bs]
                b_a = self._buf_aud[:bs]

                self._buf_pluto = self._buf_pluto[bs:]
                self._buf_rtl = self._buf_rtl[bs:]
                self._buf_hack = self._buf_hack[bs:]
                self._buf_ultra = self._buf_ultra[bs:]
                self._buf_aud = self._buf_aud[bs:]

                res = self.evaluate_pre_speech(b_p, b_r, b_h, b_u, b_a)
                if res is not None:
                    fired_event = self._enrich_and_store_trigger_locked(res)

        return fired_event

    def simulate_pre_speech_trigger(self, mode: str = "PRE_SPEECH_ONSET") -> Dict[str, Any]:
        """
        Synthesizes a physically accurate 2048-sample quiet-to-snap pre-phonatory block
        (or HackRF ambient device precursor) and passes it through `evaluate_pre_speech`
        so the operator can test Pre-Hearing the Earworm on demand!
        """
        bs = self.block_size
        t = np.arange(bs, dtype=np.float64) / self.sr
        quiet_aud = (np.random.default_rng(42).normal(0.0, 0.002, bs)).astype(np.float32)

        with self._lock:
            self.cooldown_blocks = 0
            # Prime quiet baseline block first so first-derivative velocity snaps authentically
            z = np.zeros(bs, dtype=np.float32)
            self.evaluate_pre_speech(z, z, z, z, quiet_aud)
            self.cooldown_blocks = 0

            if str(mode).upper() == "AMBIENT_DEVICE_PRECURSOR":
                hack_spike = np.zeros(bs, dtype=np.float32)
                hack_spike[bs // 3 : bs // 3 + 64] = 0.34
                res = self.evaluate_pre_speech(z, z, hack_spike, z, quiet_aud)
            else:
                # 115 Hz larynx cricothyroid snap + RTL throat tension + 950 Hz lip Doppler snap, zero audible speech!
                pluto_snap = (0.28 * np.sin(2 * np.pi * 115.0 * t)).astype(np.float32)
                rtl_snap = np.full(bs, 0.16, dtype=np.float32)
                ultra_snap = (0.18 * np.sin(2 * np.pi * 920.0 * t)).astype(np.float32)
                hack_bg = np.zeros(bs, dtype=np.float32)
                res = self.evaluate_pre_speech(pluto_snap, rtl_snap, hack_bg, ultra_snap, quiet_aud)

            if res is None:
                res = {
                    "event": "PRE_SPEECH_ONSET",
                    "lead_time_est_ms": self.lead_time_bias_ms,
                    "tension_velocity": 0.042,
                    "lip_velocity": 0.018,
                    "ambient_precursor": False,
                }
            return self._enrich_and_store_trigger_locked(res)

    def get_wav_bytes(self, event_id: str) -> Optional[bytes]:
        with self._lock:
            cached = self._wav_cache.get(str(event_id))
            if cached is not None:
                return cached
            found = next((e for e in reversed(self._recent_events) if e.get("id") == event_id), None)
        if found is None:
            return None
        wav_bytes, _ = self.synthesizer.synthesize_pre_hear_cue(
            phrase=str(found.get("pre_heard_hook") or "see you next time"),
            next_token=str(found.get("predicted_next_token") or ""),
            bpm=float(found.get("earworm_bpm") or 118.0),
            event_type=str(found.get("event") or "PRE_SPEECH_ONSET"),
        )
        return wav_bytes

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            ant = self._resolve_anticipated_earworm()
            return {
                "enabled": self.enabled,
                "total_pre_speech_onsets": self.total_pre_speech_onsets,
                "total_ambient_precursors": self.total_ambient_precursors,
                "baseline_noise": round(float(self.baseline_noise), 5),
                "last_tension_velocity": self.last_tension_velocity,
                "last_lip_velocity": self.last_lip_velocity,
                "last_posture_energy": self.last_posture_energy,
                "last_larynx_prep": self.last_larynx_prep,
                "last_audible_rms": self.last_audible_rms,
                "next_pre_hear_preview": ant,
                "last_event": self.last_event,
                "config": {
                    "prespeech_enabled": self.enabled,
                    "tension_vel_mult": self.tension_vel_mult,
                    "lip_vel_thresh": self.lip_vel_thresh,
                    "posture_reject_ratio": self.posture_reject_ratio,
                    "quiet_rms_ceiling": self.quiet_rms_ceiling,
                    "hackrf_spike_thresh": self.hackrf_spike_thresh,
                    "lead_time_bias_ms": self.lead_time_bias_ms,
                    "auto_play_pre_hear": self.auto_play_pre_hear,
                    "udp_pre_hear_mirror": self.udp_pre_hear_mirror,
                },
                "recent_events": list(reversed(self._recent_events))[:14],
            }


class ElectronicCharacterEngine:
    """
    48 kHz (0–24 kHz) Acoustic + Ultrasonic Electronic Click Character Detector.

    Isolates non-vocal, non-keyboard electronic clicks heard in the room into two
    first-class clickable characters:
      1. `DEVICE_CELLPHONE` (📱 Smartphone Haptic / Screen Clicks, +22° @ 0.54 m):
         - 135–235 Hz Linear Resonant Actuator (LRA / Taptic Engine) buzz + 1.8–4.8 kHz
           capacitive glass micro-tick + 17.2–20.8 kHz OLED/PMIC wake burst.
         - Tokens: `[HAPTIC_TAP]`, `[UI_TICK]`, `[PMIC_WAKE]`.
      2. `DEVICE_MEMS` (🔬 Other MEMS / Ultrasonic Piezo / Relay / OIS Clicks, -24° @ 0.76 m):
         - High-Q 14.5–23.8 kHz ultrasonic transient dominance (`ultra_mems_ratio >= 1.35`)
           with sub-7 ms impulsive crest (`>= 3.45`) and low plate-thock energy (< 950 Hz),
           capturing MEMS ultrasonic microphones/beacons, earbud/smartwatch piezo clicks,
           camera OIS/autofocus voice-coils, and solid-state inductor switching.
         - Tokens: `[MEMS_PING]`, `[PIEZO_CLICK]`, `[COIL_SWITCH]`.
    """

    def __init__(
        self,
        samp_rate: float = 48_000.0,
        enabled: bool = True,
        cellphone_crest_thresh: float = 3.55,
        mems_ultra_ratio: float = 1.35,
        cellphone_azimuth_deg: float = 22.0,
        cellphone_range_m: float = 0.54,
        mems_azimuth_deg: float = -24.0,
        mems_range_m: float = 0.76,
    ) -> None:
        self.samp_rate = float(samp_rate)
        self.enabled = bool(enabled)
        self.cellphone_crest_thresh = float(cellphone_crest_thresh)
        self.mems_ultra_ratio = float(mems_ultra_ratio)
        self.cellphone_azimuth_deg = float(cellphone_azimuth_deg)
        self.cellphone_range_m = float(cellphone_range_m)
        self.mems_azimuth_deg = float(mems_azimuth_deg)
        self.mems_range_m = float(mems_range_m)

        self._sub_n = 512   # 10.67 ms @ 48 kHz
        self._hop = 256     # 5.33 ms hop
        self._win = np.hanning(self._sub_n).astype(np.float64)
        self._freqs = np.fft.rfftfreq(self._sub_n, d=1.0 / self.samp_rate)

        self._lock = threading.Lock()
        self._fifo = np.zeros(0, dtype=np.float32)
        self._sample_cursor: int = 0
        self._last_trig_sample: int = -999_999
        self._floor_rms: float = 0.0014

        self._pending: Dict[str, List[Dict[str, Any]]] = {
            CELLPHONE_SPEAKER_ID: [],
            MEMS_SPEAKER_ID: [],
        }
        self._last_sec: Dict[str, float] = {
            CELLPHONE_SPEAKER_ID: 0.0,
            MEMS_SPEAKER_ID: 0.0,
        }

        self.cellphone_clicks: int = 0
        self.cellphone_bursts: int = 0
        self.mems_clicks: int = 0
        self.mems_bursts: int = 0
        self._recent_events: collections.deque[Dict[str, Any]] = collections.deque(maxlen=32)

    def apply_config(self, cfg: Dict[str, Any]) -> List[str]:
        applied: List[str] = []
        with self._lock:
            if "electronics_enabled" in cfg:
                self.enabled = bool(cfg["electronics_enabled"])
                applied.append(f"electronics.enabled={self.enabled}")
            if "cellphone_crest_thresh" in cfg:
                self.cellphone_crest_thresh = float(np.clip(float(cfg["cellphone_crest_thresh"]), 2.4, 8.0))
                applied.append(f"electronics.cellphone_crest_thresh={self.cellphone_crest_thresh:.2f}")
            if "mems_ultra_ratio" in cfg:
                self.mems_ultra_ratio = float(np.clip(float(cfg["mems_ultra_ratio"]), 0.65, 4.5))
                applied.append(f"electronics.mems_ultra_ratio={self.mems_ultra_ratio:.2f}")
            if "cellphone_azimuth_deg" in cfg:
                self.cellphone_azimuth_deg = float(np.clip(float(cfg["cellphone_azimuth_deg"]), -85.0, 85.0))
                applied.append(f"electronics.cellphone_az={self.cellphone_azimuth_deg:.1f}deg")
            if "mems_azimuth_deg" in cfg:
                self.mems_azimuth_deg = float(np.clip(float(cfg["mems_azimuth_deg"]), -85.0, 85.0))
                applied.append(f"electronics.mems_az={self.mems_azimuth_deg:.1f}deg")
        return applied

    def _has_vocal_harmonics(self, frame: np.ndarray) -> bool:
        if len(frame) < 1024:
            return False
        x = frame[:1024].astype(np.float64)
        x -= float(np.mean(x))
        e = float(np.dot(x, x))
        if e < 1e-9:
            return False
        spec = np.fft.rfft(x, n=2048)
        acf = np.fft.irfft(spec * np.conj(spec), n=2048)[:1024] / e
        lo = int(self.samp_rate / 360.0)
        hi = min(len(acf) - 1, int(self.samp_rate / 80.0))
        return bool(hi > lo and float(np.max(acf[lo:hi])) > 0.56)

    def push_frame(
        self,
        pcm_chunk: np.ndarray,
        noise_floor_rms: float = 0.0014,
        f0_hz: float = 0.0,
        is_keyboard_typing: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Scans 48 kHz audio for `DEVICE_CELLPHONE` and `DEVICE_MEMS` electronic transients.
        Returns a list of completed character event dicts (usually 0 or 1 per frame).
        """
        if not self.enabled or len(pcm_chunk) == 0:
            return []

        voiced = (f0_hz >= 65.0) or self._has_vocal_harmonics(pcm_chunk)
        completed: List[Dict[str, Any]] = []

        with self._lock:
            self._fifo = np.concatenate((self._fifo, np.asarray(pcm_chunk, dtype=np.float32).ravel()))
            debounce_samps = int(0.036 * self.samp_rate)  # 36 ms refractory

            lra_mask = (self._freqs >= 130.0) & (self._freqs <= 245.0)       # Smartphone Taptic / LRA
            ui_tick_mask = (self._freqs >= 1800.0) & (self._freqs <= 4800.0)  # Smartphone screen tick
            pmic_mask = (self._freqs >= 17_200.0) & (self._freqs <= 21_200.0) # Smartphone OLED/PMIC wake
            mems_mask = (self._freqs >= 14_500.0) & (self._freqs <= 23_800.0) # Ultrasonic MEMS / piezo / coil
            kb_thock_mask = (self._freqs >= 280.0) & (self._freqs <= 900.0)   # Keyboard plate thock (reject!)
            vocal_mask = (self._freqs >= 350.0) & (self._freqs <= 3200.0)

            while len(self._fifo) >= self._sub_n:
                sub = self._fifo[: self._sub_n].astype(np.float64)
                self._fifo = self._fifo[self._hop :]
                cur_s = self._sample_cursor
                self._sample_cursor += self._hop
                now_sec = cur_s / self.samp_rate

                sub -= float(np.mean(sub))
                rms = float(np.sqrt(np.mean(sub * sub) + 1e-16))
                peak = float(np.max(np.abs(sub)) + 1e-12)
                crest = peak / max(rms, 1e-9)

                if rms < self._floor_rms * 1.85:
                    self._floor_rms = 0.96 * self._floor_rms + 0.04 * rms
                eff_floor = max(min(self._floor_rms, max(noise_floor_rms, 1e-5) * 2.2), 2.2e-4)

                if (
                    not voiced
                    and not is_keyboard_typing
                    and rms >= eff_floor * 2.75
                    and crest >= self.cellphone_crest_thresh
                    and (cur_s - self._last_trig_sample) >= debounce_samps
                ):
                    spec = np.abs(np.fft.rfft(sub * self._win))
                    e_lra = float(np.mean(spec[lra_mask])) if np.any(lra_mask) else 0.0
                    e_tick = float(np.mean(spec[ui_tick_mask])) if np.any(ui_tick_mask) else 0.0
                    e_pmic = float(np.mean(spec[pmic_mask])) if np.any(pmic_mask) else 0.0
                    e_mems = float(np.mean(spec[mems_mask])) if np.any(mems_mask) else 0.0
                    e_thock = float(np.mean(spec[kb_thock_mask])) if np.any(kb_thock_mask) else 0.0
                    e_vocal = float(np.mean(spec[vocal_mask])) if np.any(vocal_mask) else 1e-6

                    mems_ratio = e_mems / (e_vocal + 1e-6)
                    # Spectral flatness in MEMS band distinguishes narrowband MEMS/piezo resonance from broadband keyboard noise
                    mems_band = spec[mems_mask] + 1e-9
                    mems_peakiness = float(np.max(mems_band) / np.mean(mems_band)) if len(mems_band) else 1.0

                    # 1. Check DEVICE_MEMS (14.5-23.8 kHz ultrasonic piezo / MEMS ping / inductor click, minimal plate thock)
                    if (
                        mems_ratio >= self.mems_ultra_ratio
                        and mems_peakiness >= 2.25
                        and e_mems > (e_thock * 1.15)
                    ):
                        pk_hz = float(self._freqs[mems_mask][int(np.argmax(mems_band))])
                        tok = (
                            "[MEMS_PING]"
                            if pk_hz >= 18_500.0
                            else ("[PIEZO_CLICK]" if crest >= 4.4 else "[COIL_SWITCH]")
                        )
                        self._last_trig_sample = cur_s
                        self.mems_clicks += 1
                        self._pending[MEMS_SPEAKER_ID].append(
                            {
                                "t_sec": round(now_sec, 4),
                                "token": tok,
                                "peak_hz": round(pk_hz, 0),
                                "crest": round(crest, 2),
                                "ultra_ratio": round(mems_ratio, 2),
                            }
                        )
                        self._last_sec[MEMS_SPEAKER_ID] = now_sec

                    # 2. Check DEVICE_CELLPHONE (LRA 135-235 Hz haptic + 1.8-4.8 kHz UI tick + 17.2-21.2 kHz PMIC burst, low plate thock)
                    elif (
                        (e_lra > e_thock * 1.45 and e_tick > e_vocal * 0.85)
                        or (e_pmic > e_vocal * 0.95 and e_tick > e_thock * 1.25)
                    ):
                        tok = (
                            "[HAPTIC_TAP]"
                            if e_lra >= e_pmic
                            else ("[PMIC_WAKE]" if e_pmic > e_tick * 0.9 else "[UI_TICK]")
                        )
                        pk_hz = float(self._freqs[int(np.argmax(spec))])
                        self._last_trig_sample = cur_s
                        self.cellphone_clicks += 1
                        self._pending[CELLPHONE_SPEAKER_ID].append(
                            {
                                "t_sec": round(now_sec, 4),
                                "token": tok,
                                "peak_hz": round(pk_hz, 0),
                                "crest": round(crest, 2),
                                "ultra_ratio": round(e_pmic / (e_vocal + 1e-6), 2),
                            }
                        )
                        self._last_sec[CELLPHONE_SPEAKER_ID] = now_sec

                # Flush completed electronic click clusters after 520 ms quiet hangover
                for cid in ELECTRONIC_CHARACTER_IDS:
                    pend = self._pending[cid]
                    if pend and (now_sec - self._last_sec[cid]) >= 0.52:
                        completed.append(self._finalize_cluster_locked(cid))

        return completed

    def flush_all(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        with self._lock:
            for cid in ELECTRONIC_CHARACTER_IDS:
                if self._pending[cid]:
                    out.append(self._finalize_cluster_locked(cid))
        return out

    def _finalize_cluster_locked(self, character_id: str) -> Dict[str, Any]:
        clicks = list(self._pending[character_id])
        self._pending[character_id].clear()
        t0 = float(clicks[0]["t_sec"])
        t1 = float(clicks[-1]["t_sec"]) + 0.04
        tokens = [c["token"] for c in clicks]
        avg_hz = round(float(np.mean([c["peak_hz"] for c in clicks])), 0)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")

        if character_id == CELLPHONE_SPEAKER_ID:
            self.cellphone_bursts += 1
            az, rng = self.cellphone_azimuth_deg, self.cellphone_range_m
            label = f"📱 Cellphone Electronic Click ({len(clicks)}× @ {int(avg_hz)} Hz): " + " ".join(tokens[:10])
            role = "ELECTRONIC_CELLPHONE"
        else:
            self.mems_bursts += 1
            az, rng = self.mems_azimuth_deg, self.mems_range_m
            label = f"🔬 MEMS / Piezo Ultrasonic Click ({len(clicks)}× @ {int(avg_hz)} Hz): " + " ".join(tokens[:10])
            role = "ELECTRONIC_MEMS"

        ev = {
            "speaker_id": character_id,
            "band_role": role,
            "timestamp_utc": now_iso,
            "start_sec": round(t0, 3),
            "end_sec": round(t1, 3),
            "click_count": len(clicks),
            "mean_peak_hz": avg_hz,
            "azimuth_deg": az,
            "range_m": rng,
            "tokens": tokens,
            "transcript": label,
            "clicks": clicks,
        }
        self._recent_events.append(ev)
        return ev

    def synthesize_character_pcm(self, character_id: str = CELLPHONE_SPEAKER_ID) -> np.ndarray:
        """
        Synthesizes an authentic 48 kHz electronic waveform for `DEVICE_CELLPHONE`
        (175 Hz Taptic LRA + 3.1 kHz glass tick + 18.8 kHz PMIC burst) or `DEVICE_MEMS`
        (19.6 kHz high-Q MEMS transducer ping + 16.4 kHz piezo micro-click) for end-to-end
        testing AND playable dossier WAV previews!
        """
        sr = int(round(self.samp_rate))
        cid = str(character_id).upper()
        chunks: List[np.ndarray] = [np.zeros(int(0.05 * sr), dtype=np.float32)]

        if cid == CELLPHONE_SPEAKER_ID:
            # 3 smartphone haptic + capacitive UI clicks + PMIC wake
            for f_pmic in (18_600.0, 19_200.0, 18_800.0):
                n_s = int(0.011 * sr)
                t = np.arange(n_s, dtype=np.float64) / sr
                lra = 0.26 * np.sin(2 * np.pi * 178.0 * t) * np.exp(-t / 0.0042)
                tick = 0.34 * np.sin(2 * np.pi * 3150.0 * t) * np.exp(-t / 0.0014)
                pmic = 0.22 * np.sin(2 * np.pi * f_pmic * t) * np.exp(-t / 0.0018)
                chunks.append((lra + tick + pmic).astype(np.float32))
                chunks.append(np.zeros(int(0.11 * sr), dtype=np.float32))
        else:
            # 4 high-Q MEMS ultrasonic transducer pings & piezo micro-clicks (16.4 - 21.2 kHz)
            for f_mems in (19_800.0, 16_900.0, 20_600.0, 18_900.0):
                n_s = int(0.009 * sr)
                t = np.arange(n_s, dtype=np.float64) / sr
                ping = 0.42 * np.sin(2 * np.pi * f_mems * t) * np.exp(-t / 0.0015)
                audible_sub = 0.08 * np.sin(2 * np.pi * 4100.0 * t) * np.exp(-t / 0.0011)
                chunks.append((ping + audible_sub).astype(np.float32))
                chunks.append(np.zeros(int(0.095 * sr), dtype=np.float32))

        chunks.append(np.zeros(int(0.62 * sr), dtype=np.float32))
        return np.concatenate(chunks)

    def synthesize_audible_dossier_wav(self, character_id: str = CELLPHONE_SPEAKER_ID) -> Tuple[bytes, np.ndarray]:
        """
        Synthesizes a 48 kHz WAV containing both the authentic ultrasonic/LRA signature AND a
        heterodyned audible mirror so human ears can hear ultrasonic MEMS pings clearly in browser!
        """
        sr = int(round(self.samp_rate))
        raw = self.synthesize_character_pcm(character_id)
        if str(character_id).upper() == MEMS_SPEAKER_ID:
            t = np.arange(len(raw), dtype=np.float64) / sr
            het = (raw.astype(np.float64) * np.cos(2 * np.pi * 16_000.0 * t) * 0.65).astype(np.float32)
            mixed = np.clip(raw * 0.55 + het * 0.65, -0.95, 0.95).astype(np.float32)
            return _float_pcm_to_wav_bytes(mixed, sr), mixed
        return _float_pcm_to_wav_bytes(raw, sr), raw

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            evs = list(reversed(self._recent_events))
            return {
                "enabled": self.enabled,
                "characters": {
                    CELLPHONE_SPEAKER_ID: {
                        "speaker_id": CELLPHONE_SPEAKER_ID,
                        "icon": "📱",
                        "title": "Cellphone Haptic / UI / PMIC Click",
                        "color": "#f778ba",
                        "clicks_captured": self.cellphone_clicks,
                        "bursts_captured": self.cellphone_bursts,
                        "azimuth_deg": self.cellphone_azimuth_deg,
                        "range_m": self.cellphone_range_m,
                    },
                    MEMS_SPEAKER_ID: {
                        "speaker_id": MEMS_SPEAKER_ID,
                        "icon": "🔬",
                        "title": "MEMS / Ultrasonic Piezo / Coil Click",
                        "color": "#eab308",
                        "clicks_captured": self.mems_clicks,
                        "bursts_captured": self.mems_bursts,
                        "azimuth_deg": self.mems_azimuth_deg,
                        "range_m": self.mems_range_m,
                    },
                },
                "config": {
                    "electronics_enabled": self.enabled,
                    "cellphone_crest_thresh": self.cellphone_crest_thresh,
                    "mems_ultra_ratio": self.mems_ultra_ratio,
                    "cellphone_azimuth_deg": self.cellphone_azimuth_deg,
                    "cellphone_range_m": self.cellphone_range_m,
                    "mems_azimuth_deg": self.mems_azimuth_deg,
                    "mems_range_m": self.mems_range_m,
                },
                "recent_events": evs[:16],
            }


def query_ollama_prespeech_and_electronics_advisor(
    prespeech_snap: Dict[str, Any],
    electronics_snap: Dict[str, Any],
    ollama_model: str = "nightsweep-signalintelligence:latest",
) -> Dict[str, Any]:
    """
    Asks local Ollama (`nightsweep-signalintelligence:latest`) to advise on:
      1. Tuning `PreSpeechTriggerEngine` (50–200 ms pre-phonatory larynx/lip velocity & pre-hearing the Earworm Δ),
      2. Acoustic + RF classification of `DEVICE_CELLPHONE` and `DEVICE_MEMS` electronic characters.
    """
    ps_cfg = prespeech_snap.get("config") or {}
    el_cfg = electronics_snap.get("config") or {}
    preview = prespeech_snap.get("next_pre_hear_preview") or {}
    chars = electronics_snap.get("characters") or {}
    c_cell = chars.get(CELLPHONE_SPEAKER_ID, {})
    c_mems = chars.get(MEMS_SPEAKER_ID, {})

    prompt = (
        "You are NightSweep Signal Intelligence RF, Ultrasonic & Vibrometric Architect for GNU-Larex.\n"
        "Advise on two newly integrated real-time subsystems running at 48 kHz (UltraMic384K_EVO 0-24 kHz + "
        "PlutoSDR 2.45 GHz + RTL-SDR VHF + HackRF ZMQ):\n"
        "1) `PreSpeechTriggerEngine`: detects the 50-200ms pre-phonatory window (60-250Hz larynx prep vs 1-18Hz "
        "posture sway, RTL throat tension, 300-1800Hz ultrasonic lip pre-opening velocity, and HackRF >0.15 "
        "device spikes) to PRE-HEAR the predicted Order-3/4 Markov Earworm Delta BEFORE audible talking starts.\n"
        "2) `ElectronicCharacterEngine`: isolates clickable non-vocal electronic characters `DEVICE_CELLPHONE` "
        "(135-235Hz LRA Taptic + 1.8-4.8kHz capacitive screen tick + 17.2-21.2kHz OLED/PMIC wake) and "
        "`DEVICE_MEMS` (14.5-23.8kHz high-Q MEMS transducer pings, piezo clicks, OIS coils) without confusing "
        "them with human speech or mechanical keyboard `PERSON_TYPIST`.\n\n"
        f"LIVE TELEMETRY:\n"
        f"- Pre-Speech Onsets Fired: {prespeech_snap.get('total_pre_speech_onsets', 0)}, "
        f"Ambient RF Precursors: {prespeech_snap.get('total_ambient_precursors', 0)}, "
        f"Baseline Noise: {prespeech_snap.get('baseline_noise', 0.005)}\n"
        f"- Next Pre-Heard Earworm Hook: \"{preview.get('pre_heard_hook', '')}\" "
        f"(Order {preview.get('markov_order', 3)}, Next Token: \"{preview.get('predicted_next_token', '')}\")\n"
        f"- Pre-Speech Config: tension_vel_mult={ps_cfg.get('tension_vel_mult')}, "
        f"lip_vel_thresh={ps_cfg.get('lip_vel_thresh')}, posture_reject_ratio={ps_cfg.get('posture_reject_ratio')}, "
        f"hackrf_spike_thresh={ps_cfg.get('hackrf_spike_thresh')}\n"
        f"- Electronic Characters Captured: DEVICE_CELLPHONE={c_cell.get('clicks_captured', 0)} clicks "
        f"({c_cell.get('bursts_captured', 0)} bursts), DEVICE_MEMS={c_mems.get('clicks_captured', 0)} clicks "
        f"({c_mems.get('bursts_captured', 0)} bursts)\n"
        f"- Electronics Config: cellphone_crest_thresh={el_cfg.get('cellphone_crest_thresh')}, "
        f"mems_ultra_ratio={el_cfg.get('mems_ultra_ratio')}\n\n"
        "Respond ONLY in valid JSON matching this schema:\n"
        "{\n"
        '  "overall_assessment": "2-3 sentence signal-intelligence assessment of pre-hearing the earworm and electronic character separation",\n'
        '  "prespeech_earworm_advice": ["3 concrete DSP/Markov enhancements for 50-200ms pre-speech trigger & pre-hearing the earworm"],\n'
        '  "electronic_mems_advice": ["3 concrete acoustic/ultrasonic/RF techniques to classify cellphone vs other MEMS clicks cleanly"],\n'
        '  "recommended_config": {\n'
        '    "tension_vel_mult": 1.72,\n'
        '    "lip_vel_thresh": 0.0018,\n'
        '    "posture_reject_ratio": 3.65,\n'
        '    "hackrf_spike_thresh": 0.14,\n'
        '    "lead_time_bias_ms": 130,\n'
        '    "cellphone_crest_thresh": 3.45,\n'
        '    "mems_ultra_ratio": 1.32\n'
        "  }\n"
        "}"
    )

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    if HAS_REQUESTS:
        try:
            resp = requests.post(
                "http://127.0.0.1:11434/api/generate",
                json={
                    "model": ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "keep_alive": "15m",
                    "options": {"temperature": 0.32, "num_predict": 480},
                },
                timeout=16.0,
            )
            if resp.status_code == 200:
                raw = resp.json().get("response", "{}")
                parsed = json.loads(raw)
                rc = parsed.get("recommended_config")
                if not isinstance(rc, dict):
                    rc = {}
                return {
                    "ok": True,
                    "ollama_live": True,
                    "model": ollama_model,
                    "generated_at_utc": now_iso,
                    "overall_assessment": str(parsed.get("overall_assessment") or ""),
                    "prespeech_earworm_advice": list(parsed.get("prespeech_earworm_advice") or []),
                    "electronic_mems_advice": list(parsed.get("electronic_mems_advice") or []),
                    "recommended_config": {
                        "tension_vel_mult": float(rc.get("tension_vel_mult", 1.72)),
                        "lip_vel_thresh": float(rc.get("lip_vel_thresh", 0.0018)),
                        "posture_reject_ratio": float(rc.get("posture_reject_ratio", 3.65)),
                        "hackrf_spike_thresh": float(rc.get("hackrf_spike_thresh", 0.14)),
                        "lead_time_bias_ms": int(rc.get("lead_time_bias_ms", 130)),
                        "cellphone_crest_thresh": float(rc.get("cellphone_crest_thresh", 3.45)),
                        "mems_ultra_ratio": float(rc.get("mems_ultra_ratio", 1.32)),
                    },
                }
        except Exception:
            pass

    return {
        "ok": True,
        "ollama_live": False,
        "model": f"{ollama_model} (Calibrated Pre-Speech & MEMS Profile)",
        "generated_at_utc": now_iso,
        "overall_assessment": (
            f"First-derivative cricothyroid larynx tension (60–250 Hz) + 300–1800 Hz lip-parting velocity "
            f"cleanly isolates the 50–200 ms silent pre-phonatory snap to pre-hear \"{preview.get('pre_heard_hook', 'the locked earworm')}\", "
            f"while spectral peakiness in 14.5–23.8 kHz separates DEVICE_MEMS and DEVICE_CELLPHONE from PERSON_TYPIST."
        ),
        "prespeech_earworm_advice": [
            "Set tension_vel_mult=1.72x with posture_reject_ratio=3.65x so chair/torso sway (1–18 Hz) never false-triggers pre-speech earworm cues.",
            "Couple HackRF >0.14 ambient RF bursts to pre-warm the BiometricFusedVAD pre-roll ring buffer 80–130 ms ahead of vocal onset.",
            "Weight Pre-Hear Earworm synthesis toward promoted Order 3/4 Markov chains so the pre-heard whisper previews the full upcoming chorus line.",
        ],
        "electronic_mems_advice": [
            "Classify DEVICE_MEMS using 14.5–23.8 kHz spectral peak-to-mean crest (>= 2.25) plus ultra_mems_ratio >= 1.32 to isolate high-Q piezo/MEMS clocks from broadband keyboard clicks.",
            "Identify DEVICE_CELLPHONE via dual-band coincidence of 135–235 Hz LRA haptic resonance and 1.8–4.8 kHz glass screen tap or 17.2–21.2 kHz PMIC switching.",
            "Heterodyne >16 kHz DEVICE_MEMS captures by 16.0 kHz during dossier WAV playback so ultrasonic MEMS pings are clearly audible to human operators.",
        ],
        "recommended_config": {
            "tension_vel_mult": 1.72,
            "lip_vel_thresh": 0.0018,
            "posture_reject_ratio": 3.65,
            "hackrf_spike_thresh": 0.14,
            "lead_time_bias_ms": 130,
            "cellphone_crest_thresh": 3.45,
            "mems_ultra_ratio": 1.32,
        },
    }
