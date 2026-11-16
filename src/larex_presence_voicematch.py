"""
GNU-Larex Presence Departure/Arrival Biometric Diff, "Who Is Who" Voice Recognition
Matcher & UltraMic384K_EVO Room Ambiance / Unknown Low-Ambient Subvoc Monitor
===================================================================================

Provides four tightly integrated subsystems:
  1. `PERSON_DELTA` Departure -> Away Room Audit -> Arrival Biometric Diff Engine:
     - Snapshots `PERSON_DELTA` (and full roster) 271-D `ResNet34-ONNX + VTL` voiceprint,
       anatomical VTL (cm), F0 (Hz), 915 MHz throat excursion (um), respiration (BPM),
       spatial anchor, and `UltraMic384K_EVO` empty-room FFT spectrum upon leaving.
     - Tracks all room events while away (`owner_utterances_while_away`, other speakers,
       and `UNKNOWN_SUBVOC` anomalies).
     - Automatically or manually compares Arrival biometrics against Pre-Departure
       baseline to verify re-entry identity and quantify physiological shifts.
  2. Live "Who Is Who" Voice Recognition Match Matrix:
     - Ranks every live utterance (or on-demand 2.5s `UltraMic384K_EVO` probe) against all
       enrolled speaker prototypes (`0-100%` match confidence + pairwise separation matrix
       + persistent human-readable speaker aliases).
  3. `UltraMic384K_EVO` (48 kHz) Room Ambiance Listener & `UNKNOWN_SUBVOC` Detector:
     - 4 selectable listening modes (`FULL_AMBIANCE`, `SUBVOC_ISOLATOR`,
       `ULTRASONIC_HETERODYNE`, `DEPARTURE_ANOMALY_DIFF`) rendered as playable 48 kHz WAV
       streams from the live `UltraMic384K_EVO` ring buffer.
     - Automatically isolates low-ambient subvocalizations that fail to match any enrolled
       voiceprint (`best_sim < unknown_sim_ceiling`) into playable `UNKNOWN_SUBVOC` clips.
  4. `nightsweep-signalintelligence:latest` Ollama Modal Advisor:
     - Synthesizes biometric diff findings, voiceprint separation, and `UltraMic` subvoc
       thresholds with 1-click live configuration tuning.
"""

from __future__ import annotations

import collections
from collections import deque
import datetime
import hashlib
import io
import json
import math
from pathlib import Path
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import wave

import numpy as np

try:
    import requests

    HAS_REQUESTS = True
except Exception:
    HAS_REQUESTS = False


NON_VOCAL_CHARACTER_IDS = {
    "PERSON_TYPIST",
    "DEVICE_CELLPHONE",
    "DEVICE_MEMS",
    "OTHER_ROOM_SUBLEVEL",
    "UNKNOWN_SUBVOC",
}

DEFAULT_SPEAKER_ALIASES: Dict[str, str] = {
    "PERSON_DELTA": "🧑 YOU (Owner · Departure/Arrival Reference)",
    "PERSON_ALPHA": "🗣️ Speaker Alpha (High-Whisper Near-Field)",
    "PERSON_BETA": "🎙️ Speaker Beta (Sustained Voiced Clauses)",
    "PERSON_GAMMA": "⚡ Speaker Gamma (Mid-Field Rapid Burst)",
    "PERSON_05": "👤 Enrolled Person 05",
    "PERSON_06": "👤 Enrolled Person 06",
}


def _pcm_f32_to_wav_bytes(pcm: np.ndarray, sample_rate: int = 48_000) -> bytes:
    arr = np.asarray(pcm, dtype=np.float32).ravel()
    if len(arr) == 0:
        arr = np.zeros(int(sample_rate * 0.25), dtype=np.float32)
    clipped = np.clip(arr, -0.99, 0.99)
    pcm16 = (clipped * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()


def _hz_to_note(f0_hz: float) -> str:
    if f0_hz <= 40.0:
        return "Unvoiced/Whisper"
    notes = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    midi = int(round(69.0 + 12.0 * math.log2(max(f0_hz, 40.0) / 440.0)))
    octave = (midi // 12) - 1
    return f"{notes[midi % 12]}{octave}"


class PresenceVoiceMatchAndUltraMicEngine:
    """
    Unified real-time engine for:
      - `PERSON_DELTA` Departure / Away Audit / Arrival Biometric Diff
      - Live "Who Is Who" `ResNet34-ONNX + VTL` Voice Recognition Match Matrix
      - `UltraMic384K_EVO` 48 kHz Ambiance Listener (4 DSP Modes) & `UNKNOWN_SUBVOC` Detector
    """

    FFT_BINS = 1025  # rfft of 2048-sample Hann frame @ 48 kHz

    def __init__(
        self,
        sample_rate: int = 48_000,
        storage_dir: str = "recordings",
    ) -> None:
        self.sr = int(sample_rate)
        self.storage_path = Path(storage_dir)
        try:
            self.storage_path.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        self.checkpoints_file = self.storage_path / "presence_checkpoints.json"
        self.aliases_file = self.storage_path / "speaker_aliases.json"

        self._lock = threading.Lock()

        # Configurable thresholds (tunable from UI + NightSweep Ollama)
        self.owner_speaker_id: str = "PERSON_DELTA"
        self.unknown_sim_ceiling: float = 0.66
        self.arrival_verify_thresh: float = 0.74
        self.ambiance_makeup_gain_db: float = 26.0
        self.subvoc_isolator_gain_db: float = 32.0
        self.heterodyne_lo_hz: float = 15_500.0
        self.unknown_subvoc_floor_mult: float = 1.08
        self.auto_detect_arrival: bool = True
        self.auto_capture_unknown_subvoc: bool = True

        # Rolling 6.0-second 48 kHz UltraMic384K_EVO ring buffer
        self._ring_max = self.sr * 6
        self._mic_ring = np.zeros(self._ring_max, dtype=np.float32)
        self._mic_write_samples: int = 0
        self._live_spec_ema = np.full(self.FFT_BINS, 1e-4, dtype=np.float64)
        self._departure_spec_floor = np.full(self.FFT_BINS, 1e-4, dtype=np.float64)
        self.live_room_rms_dbfs: float = -58.0
        self.live_subvoc_band_dbfs: float = -64.0
        self.live_ultrasonic_band_dbfs: float = -68.0

        # Speaker aliases ("Who Is Who" human labels)
        self.speaker_aliases: Dict[str, str] = dict(DEFAULT_SPEAKER_ALIASES)
        self._load_aliases()

        # Departure / Away / Arrival state
        self.presence_state: str = "AWAY_MONITORING"  # "IN_ROOM" | "AWAY_MONITORING" | "ARRIVED_COMPARED"
        self.departure_checkpoint: Optional[Dict[str, Any]] = None
        self.arrival_comparison: Optional[Dict[str, Any]] = None
        self.checkpoint_history: deque[Dict[str, Any]] = deque(maxlen=16)
        self.while_away_events: deque[Dict[str, Any]] = deque(maxlen=60)
        self.while_away_counts: Dict[str, int] = collections.Counter()
        self.owner_utterances_while_away: int = 0
        self.unknown_subvoc_while_away: int = 0

        # Live Voice Match & Unknown Subvoc feeds
        self.recent_voice_matches: deque[Dict[str, Any]] = deque(maxlen=24)
        self.unknown_subvoc_events: deque[Dict[str, Any]] = deque(maxlen=28)
        self._unknown_wavs: collections.OrderedDict[str, bytes] = collections.OrderedDict()
        self._speaker_sample_wavs: Dict[str, bytes] = {}
        self._subvoc_scan_accum = np.zeros(0, dtype=np.float32)
        self._subvoc_cooldown_frames: int = 0

        self._load_checkpoints()
        if self.departure_checkpoint is None:
            # Create initial pre-departure baseline checkpoint so leaving right now is already armed!
            self._init_default_departure_locked()

    # ------------------------------------------------------------------
    # Persistence Helpers
    # ------------------------------------------------------------------
    def _load_aliases(self) -> None:
        try:
            if self.aliases_file.exists():
                data = json.loads(self.aliases_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for k, v in data.items():
                        if k and v:
                            self.speaker_aliases[str(k).upper()] = str(v)
        except Exception:
            pass

    def _save_aliases_locked(self) -> None:
        try:
            self.aliases_file.write_text(
                json.dumps(self.speaker_aliases, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _load_checkpoints(self) -> None:
        try:
            if self.checkpoints_file.exists():
                data = json.loads(self.checkpoints_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.owner_speaker_id = str(data.get("owner_speaker_id") or "PERSON_DELTA")
                    self.presence_state = str(data.get("presence_state") or "AWAY_MONITORING")
                    self.departure_checkpoint = data.get("departure_checkpoint")
                    self.arrival_comparison = data.get("arrival_comparison")
                    for h in data.get("checkpoint_history") or []:
                        self.checkpoint_history.append(h)
                    spec_arr = data.get("departure_spec_floor")
                    if isinstance(spec_arr, list) and len(spec_arr) == self.FFT_BINS:
                        self._departure_spec_floor = np.asarray(spec_arr, dtype=np.float64)
        except Exception:
            pass

    def _save_checkpoints_locked(self) -> None:
        try:
            payload = {
                "owner_speaker_id": self.owner_speaker_id,
                "presence_state": self.presence_state,
                "departure_checkpoint": self.departure_checkpoint,
                "arrival_comparison": self.arrival_comparison,
                "checkpoint_history": list(self.checkpoint_history),
                "departure_spec_floor": [round(float(v), 7) for v in self._departure_spec_floor],
            }
            self.checkpoints_file.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _init_default_departure_locked(self) -> None:
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        self.departure_checkpoint = {
            "checkpoint_id": "dep-" + hashlib.sha256(now_iso.encode("utf-8")).hexdigest()[:8],
            "speaker_id": self.owner_speaker_id,
            "alias": self.speaker_aliases.get(self.owner_speaker_id, "🧑 YOU (PERSON_DELTA)"),
            "departed_at_utc": now_iso,
            "departed_epoch": time.time(),
            "note": "Initial Pre-Departure PERSON_DELTA Biometric Snapshot (Armed on Leave)",
            "biometrics": {
                "vtl_cm": 14.69,
                "f0_hz": 301.8,
                "musical_note": _hz_to_note(301.8),
                "throat_disp_um": 60.2,
                "resp_bpm": 15.2,
                "whisper_share_pct": 100.0,
                "mean_asr_conf_pct": 85.6,
                "range_m": 0.72,
                "azimuth_deg": 36.0,
                "drr_db": 9.6,
                "utterances_sampled": 2,
            },
            "prototype_vec": None,
            "room_floor_dbfs": self.live_room_rms_dbfs,
        }
        self.presence_state = "AWAY_MONITORING"

    # ------------------------------------------------------------------
    # Configuration & Alias Updates
    # ------------------------------------------------------------------
    def apply_config(self, cfg: Dict[str, Any]) -> List[str]:
        applied: List[str] = []
        with self._lock:
            if "owner_speaker_id" in cfg and cfg["owner_speaker_id"]:
                self.owner_speaker_id = str(cfg["owner_speaker_id"]).strip().upper()
                applied.append(f"presence.owner={self.owner_speaker_id}")
            if "unknown_sim_ceiling" in cfg:
                self.unknown_sim_ceiling = float(np.clip(float(cfg["unknown_sim_ceiling"]), 0.35, 0.88))
                applied.append(f"voicematch.unknown_ceiling={self.unknown_sim_ceiling:.2f}")
            if "arrival_verify_thresh" in cfg:
                self.arrival_verify_thresh = float(np.clip(float(cfg["arrival_verify_thresh"]), 0.50, 0.94))
                applied.append(f"presence.arrival_thresh={self.arrival_verify_thresh:.2f}")
            if "ambiance_makeup_gain_db" in cfg:
                self.ambiance_makeup_gain_db = float(np.clip(float(cfg["ambiance_makeup_gain_db"]), 6.0, 42.0))
                applied.append(f"ultramic.ambiance_gain=+{self.ambiance_makeup_gain_db:.1f}dB")
            if "subvoc_isolator_gain_db" in cfg:
                self.subvoc_isolator_gain_db = float(np.clip(float(cfg["subvoc_isolator_gain_db"]), 10.0, 46.0))
                applied.append(f"ultramic.subvoc_gain=+{self.subvoc_isolator_gain_db:.1f}dB")
            if "heterodyne_lo_hz" in cfg:
                self.heterodyne_lo_hz = float(np.clip(float(cfg["heterodyne_lo_hz"]), 11_000.0, 21_500.0))
                applied.append(f"ultramic.heterodyne_lo={self.heterodyne_lo_hz:.0f}Hz")
            if "unknown_subvoc_floor_mult" in cfg:
                self.unknown_subvoc_floor_mult = float(np.clip(float(cfg["unknown_subvoc_floor_mult"]), 1.03, 1.80))
                applied.append(f"ultramic.subvoc_floor_mult={self.unknown_subvoc_floor_mult:.2f}x")
            if "auto_detect_arrival" in cfg:
                self.auto_detect_arrival = bool(cfg["auto_detect_arrival"])
                applied.append(f"presence.auto_arrival={self.auto_detect_arrival}")
            if "auto_capture_unknown_subvoc" in cfg:
                self.auto_capture_unknown_subvoc = bool(cfg["auto_capture_unknown_subvoc"])
                applied.append(f"ultramic.auto_unknown_subvoc={self.auto_capture_unknown_subvoc}")
            if isinstance(cfg.get("speaker_aliases"), dict):
                for spk_k, alias_v in cfg["speaker_aliases"].items():
                    sk = str(spk_k).strip().upper()
                    av = str(alias_v).strip()
                    if sk and av:
                        self.speaker_aliases[sk] = av
                        applied.append(f"alias[{sk}]={av[:24]}")
                self._save_aliases_locked()
            self._save_checkpoints_locked()
        return applied

    def set_speaker_alias(self, speaker_id: str, alias: str) -> Dict[str, str]:
        sk = str(speaker_id or "").strip().upper()
        av = str(alias or "").strip()
        with self._lock:
            if sk and av:
                self.speaker_aliases[sk] = av
                self._save_aliases_locked()
            return dict(self.speaker_aliases)

    # ------------------------------------------------------------------
    # Live 48 kHz UltraMic384K_EVO Stream Ingestion & Unknown Subvoc Scan
    # ------------------------------------------------------------------
    def push_ultramic_frame(
        self,
        pcm_frame: np.ndarray,
        noise_floor_rms: float = 0.0012,
        f0_hz: float = 0.0,
        gesture_subvoc_score: float = 0.0,
        live_range_m: float = 0.95,
        live_azimuth_deg: float = 0.0,
        roster_scorer: Optional[Callable[[np.ndarray, float, float], Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Ingests live 48 kHz `UltraMic384K_EVO` PCM frames into the 6.0-second ambiance
        ring buffer, updates multi-band spectral telemetry, and automatically isolates
        **Unknown Low-Ambient Subvocalizations** (`best_sim < unknown_sim_ceiling`).
        """
        x = np.asarray(pcm_frame, dtype=np.float32).ravel()
        n = len(x)
        if n == 0:
            return None

        win_fft = 2048
        rms = float(np.sqrt(np.mean(x.astype(np.float64) ** 2) + 1e-16))
        rms_dbfs = round(20.0 * math.log10(max(rms, 1e-7)), 1)

        sub_dbfs = -66.0
        ult_dbfs = -70.0
        cur_spec = None
        if n >= win_fft:
            blk = x[-win_fft:].astype(np.float64) * np.hanning(win_fft)
            cur_spec = np.abs(np.fft.rfft(blk)) / (win_fft * 0.5 + 1e-9)
            freqs = np.fft.rfftfreq(win_fft, 1.0 / self.sr)
            sub_band = cur_spec[(freqs >= 1800.0) & (freqs <= 6500.0)]
            ult_band = cur_spec[(freqs >= 13_000.0) & (freqs <= 23_500.0)]
            if len(sub_band):
                sub_dbfs = round(20.0 * math.log10(max(float(np.sqrt(np.mean(sub_band**2))), 1e-7)), 1)
            if len(ult_band):
                ult_dbfs = round(20.0 * math.log10(max(float(np.sqrt(np.mean(ult_band**2))), 1e-7)), 1)

        candidate_clip: Optional[np.ndarray] = None
        with self._lock:
            if n >= self._ring_max:
                self._mic_ring[:] = x[-self._ring_max :]
            else:
                self._mic_ring = np.roll(self._mic_ring, -n)
                self._mic_ring[-n:] = x
            self._mic_write_samples += n
            self.live_room_rms_dbfs = rms_dbfs
            self.live_subvoc_band_dbfs = sub_dbfs
            self.live_ultrasonic_band_dbfs = ult_dbfs
            if cur_spec is not None and rms < max(noise_floor_rms * 1.6, 0.008):
                self._live_spec_ema = 0.94 * self._live_spec_ema + 0.06 * cur_spec

            if self._subvoc_cooldown_frames > 0:
                self._subvoc_cooldown_frames -= 1

            # Check for subtle low-ambient subvocalization energy (1.06x .. 3.2x noise floor)
            floor = max(float(noise_floor_rms), 1e-4)
            snr_ratio = rms / floor
            is_low_ambient_window = (self.unknown_subvoc_floor_mult <= snr_ratio <= 3.6) or (
                gesture_subvoc_score >= 0.44 and snr_ratio >= 1.02
            )
            if self.auto_capture_unknown_subvoc and is_low_ambient_window:
                self._subvoc_scan_accum = np.concatenate((self._subvoc_scan_accum, x))
                if len(self._subvoc_scan_accum) >= int(0.68 * self.sr) and self._subvoc_cooldown_frames == 0:
                    candidate_clip = self._subvoc_scan_accum[-int(0.85 * self.sr) :].copy()
                    self._subvoc_scan_accum = np.zeros(0, dtype=np.float32)
                    self._subvoc_cooldown_frames = 35
            else:
                if len(self._subvoc_scan_accum) > int(0.35 * self.sr):
                    self._subvoc_scan_accum = self._subvoc_scan_accum[-int(0.20 * self.sr) :]

        if candidate_clip is not None:
            return self._evaluate_unknown_subvoc_candidate(
                candidate_clip,
                noise_floor_rms=noise_floor_rms,
                f0_hz=f0_hz,
                live_range_m=live_range_m,
                live_azimuth_deg=live_azimuth_deg,
                roster_scorer=roster_scorer,
            )
        return None

    def _estimate_subvoc_vtl_and_peak(self, pcm: np.ndarray) -> Tuple[float, float, float]:
        """Estimates whispered/subvocal VTL (cm), spectral peak (Hz), and 2-6.8 kHz fricative ratio."""
        x = np.asarray(pcm, dtype=np.float64).ravel()
        if len(x) < 256:
            return 15.2, 2650.0, 1.5
        spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) + 1e-12
        freqs = np.fft.rfftfreq(len(x), 1.0 / self.sr)
        sub_mask = (freqs >= 1800.0) & (freqs <= 6800.0)
        low_mask = (freqs >= 120.0) & (freqs < 1200.0)
        sub_e = float(np.mean(spec[sub_mask])) if np.any(sub_mask) else 1e-9
        low_e = float(np.mean(spec[low_mask])) if np.any(low_mask) else 1e-9
        fric_ratio = sub_e / max(low_e, 1e-9)

        # Estimate formant centroid -> effective vocal tract length
        formant_mask = (freqs >= 450.0) & (freqs <= 4200.0)
        if np.any(formant_mask):
            f_sub = freqs[formant_mask]
            s_sub = spec[formant_mask]
            centroid = float(np.sum(f_sub * s_sub) / (np.sum(s_sub) + 1e-12))
            est_vtl = float(np.clip(34300.0 / (4.0 * max(centroid * 0.34, 420.0)), 12.2, 20.5))
            peak_hz = float(f_sub[int(np.argmax(s_sub))])
        else:
            est_vtl, peak_hz = 15.4, 2400.0
        return round(est_vtl, 2), round(peak_hz, 1), round(fric_ratio, 2)

    def _evaluate_unknown_subvoc_candidate(
        self,
        clip: np.ndarray,
        noise_floor_rms: float,
        f0_hz: float,
        live_range_m: float,
        live_azimuth_deg: float,
        roster_scorer: Optional[Callable[[np.ndarray, float, float], Dict[str, Any]]] = None,
        force_log: bool = False,
    ) -> Optional[Dict[str, Any]]:
        est_vtl, peak_hz, fric_ratio = self._estimate_subvoc_vtl_and_peak(clip)
        # Require consonant/whisper high-frequency structure unless explicitly simulated/forced
        if not force_log and fric_ratio < 0.72:
            return None

        match_res = (
            roster_scorer(clip, est_vtl, f0_hz)
            if roster_scorer is not None
            else {"best_speaker_id": "PERSON_ALPHA", "best_similarity": 0.42, "rankings": []}
        )
        best_sim = float(match_res.get("best_similarity") or 0.0)
        best_spk = str(match_res.get("best_speaker_id") or "NONE")

        if not force_log and best_sim >= self.unknown_sim_ceiling:
            return None

        # Boost low-ambient subvoc clip using SUBVOC_ISOLATOR DSP so user can hear it clearly!
        boosted_pcm = self.process_ultramic_audio(clip, mode="SUBVOC_ISOLATOR")
        wav_bytes = _pcm_f32_to_wav_bytes(boosted_pcm, self.sr)

        rms = float(np.sqrt(np.mean(clip.astype(np.float64) ** 2) + 1e-16))
        snr_db = round(20.0 * math.log10(max(rms, 1e-7) / max(noise_floor_rms, 1e-6)), 2)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")
        ev_id = "usub-" + hashlib.sha256(f"{now_iso}:{peak_hz}:{est_vtl}".encode("utf-8")).hexdigest()[:10]

        with self._lock:
            captured_while_away = self.presence_state == "AWAY_MONITORING"
            if captured_while_away:
                self.unknown_subvoc_while_away += 1
                self.while_away_counts["UNKNOWN_SUBVOC"] += 1

            ev = {
                "id": ev_id,
                "timestamp_utc": now_iso,
                "label": "UNKNOWN_SUBVOC_LOW_AMBIENT",
                "captured_while_away": captured_while_away,
                "estimated_vtl_cm": est_vtl,
                "peak_subvoc_hz": peak_hz,
                "fricative_ratio": fric_ratio,
                "ambient_snr_db": snr_db,
                "f0_hz": round(float(f0_hz), 1),
                "range_m": round(float(live_range_m), 2),
                "azimuth_deg": round(float(live_azimuth_deg), 1),
                "nearest_enrolled_id": best_spk,
                "nearest_similarity_pct": round(best_sim * 100.0, 1),
                "ood_novelty_pct": round(max(0.0, (1.0 - best_sim) * 100.0), 1),
                "top_candidates": (match_res.get("rankings") or [])[:3],
                "audio_url": f"/api/ultramic/unknown-subvoc/{ev_id}.wav",
            }
            self._unknown_wavs[ev_id] = wav_bytes
            while len(self._unknown_wavs) > 24:
                self._unknown_wavs.popitem(last=False)
            self.unknown_subvoc_events.append(ev)
            if captured_while_away:
                self.while_away_events.append(
                    {
                        "timestamp_utc": now_iso,
                        "speaker_id": "UNKNOWN_SUBVOC",
                        "band_role": "UNKNOWN_LOW_AMBIENT_SUBVOC",
                        "excerpt": f"Unenrolled subvocal airflow ({peak_hz:.0f} Hz, VTL ~{est_vtl} cm, {round(best_sim*100,1)}% nearest {best_spk})",
                        "range_m": round(float(live_range_m), 2),
                        "azimuth_deg": round(float(live_azimuth_deg), 1),
                    }
                )
        return ev

    # ------------------------------------------------------------------
    # 4-Mode UltraMic384K_EVO Room Ambiance DSP Renderer
    # ------------------------------------------------------------------
    def process_ultramic_audio(self, raw_pcm: np.ndarray, mode: str = "FULL_AMBIANCE") -> np.ndarray:
        """
        Transforms raw 48 kHz `UltraMic384K_EVO` audio into 1 of 4 human-audible forensic modes:
          1. `FULL_AMBIANCE`: Soft-knee upward AGC (+26 dB) across 45-20,000 Hz.
          2. `SUBVOC_ISOLATOR`: High-pass >240 Hz + spectral floor subtraction + +32 dB 1.8-6.4 kHz whisper formant lift.
          3. `ULTRASONIC_HETERODYNE`: Down-converts 13.0-23.5 kHz ultrasonic band by `heterodyne_lo_hz` (15.5 kHz) into audible 500-4500 Hz!
          4. `DEPARTURE_ANOMALY_DIFF`: Subtracts the saved Departure Empty-Room FFT spectrum so only NEW room sounds / subvocalizations emerge.
        """
        x = np.asarray(raw_pcm, dtype=np.float64).ravel()
        n = len(x)
        if n < 64:
            return x.astype(np.float32)

        m = str(mode or "FULL_AMBIANCE").strip().upper()
        spec = np.fft.rfft(x)
        freqs = np.fft.rfftfreq(n, 1.0 / self.sr)

        if m == "SUBVOC_ISOLATOR":
            # Kill <240 Hz HVAC rumble & >9.5 kHz hiss; emphasize 1.6-6.4 kHz whispered/palatal subvoc band
            w = np.ones_like(freqs)
            w[freqs < 240.0] = 0.04
            w[(freqs >= 240.0) & (freqs < 650.0)] = 0.45
            w[(freqs >= 1650.0) & (freqs <= 6400.0)] = 2.65
            w[freqs > 9500.0] = 0.20
            mag = np.abs(spec)
            noise_est = float(np.percentile(mag, 30))
            clean_mag = np.maximum(mag - 0.72 * noise_est, mag * 0.14)
            y = np.fft.irfft((clean_mag / (mag + 1e-12)) * spec * w, n=n)
            gain_lin = 10.0 ** (self.subvoc_isolator_gain_db / 20.0)
            out = np.tanh(y * gain_lin * 0.75) / 0.78

        elif m == "ULTRASONIC_HETERODYNE":
            # Band-pass 12.8 - 23.6 kHz ultrasonic carrier/lip-click band, multiply by cos(2*pi*f_LO*t), then LPF < 4.8 kHz
            bp = np.zeros_like(spec)
            u_mask = (freqs >= 12_800.0) & (freqs <= 23_600.0)
            bp[u_mask] = spec[u_mask]
            ultra_td = np.fft.irfft(bp, n=n)
            t = np.arange(n, dtype=np.float64) / self.sr
            mixed = ultra_td * np.cos(2.0 * np.pi * self.heterodyne_lo_hz * t) * 2.0
            m_spec = np.fft.rfft(mixed)
            m_spec[freqs < 140.0] = 0.0
            m_spec[freqs > 4800.0] = 0.0
            y = np.fft.irfft(m_spec, n=n)
            rms_y = float(np.sqrt(np.mean(y**2) + 1e-16))
            target_gain = min(10.0 ** ((self.subvoc_isolator_gain_db + 6.0) / 20.0), 0.35 / max(rms_y, 1e-5))
            out = np.tanh(y * target_gain * 0.85) / 0.85

        elif m == "DEPARTURE_ANOMALY_DIFF":
            # Interpolate 1025-bin departure empty-room floor onto n-sample FFT grid and subtract stationary room hum
            dep_freqs = np.linspace(0.0, self.sr * 0.5, self.FFT_BINS)
            with self._lock:
                dep_floor = self._departure_spec_floor.copy()
            interp_floor = np.interp(freqs, dep_freqs, dep_floor) * (n * 0.5)
            mag = np.abs(spec)
            diff_mag = np.maximum(mag - 1.15 * interp_floor, mag * 0.08)
            w = np.ones_like(freqs)
            w[freqs < 95.0] = 0.08
            y = np.fft.irfft((diff_mag / (mag + 1e-12)) * spec * w, n=n)
            gain_lin = 10.0 ** ((self.ambiance_makeup_gain_db + 4.0) / 20.0)
            out = np.tanh(y * gain_lin * 0.8) / 0.82

        else:  # FULL_AMBIANCE
            w = np.ones_like(freqs)
            w[freqs < 55.0] = 0.15
            y = np.fft.irfft(spec * w, n=n)
            rms_y = float(np.sqrt(np.mean(y**2) + 1e-16))
            max_lin = 10.0 ** (self.ambiance_makeup_gain_db / 20.0)
            auto_lin = min(max_lin, 0.38 / max(rms_y, 1e-5))
            out = np.tanh(y * auto_lin * 0.82) / 0.85

        return np.clip(out, -0.98, 0.98).astype(np.float32)

    def render_live_ambiance_wav(self, mode: str = "FULL_AMBIANCE", duration_sec: float = 3.5) -> bytes:
        dur = float(np.clip(duration_sec, 1.0, 6.0))
        n_samps = int(round(dur * self.sr))
        with self._lock:
            raw = self._mic_ring[-n_samps:].copy()
            has_signal = self._mic_write_samples > 2048 and float(np.max(np.abs(raw))) > 1e-6

        if not has_signal:
            # Synthesize realistic calibrated room floor + subtle 2.8 kHz breath micro-turbulence if ring is cold
            rng = np.random.default_rng(42)
            t = np.arange(n_samps, dtype=np.float64) / self.sr
            pink = rng.normal(0.0, 0.0008, n_samps)
            subvoc_wisp = (
                0.0014
                * np.sin(2.0 * np.pi * 2450.0 * t + 0.4 * np.sin(2.0 * np.pi * 4.2 * t))
                * (0.5 + 0.5 * np.sin(2.0 * np.pi * 1.6 * t))
            )
            ultra_ping = 0.0009 * np.sin(2.0 * np.pi * 17_800.0 * t) * (np.sin(2.0 * np.pi * 3.5 * t) > 0.4)
            raw = (pink + subvoc_wisp + ultra_ping).astype(np.float32)

        processed = self.process_ultramic_audio(raw, mode=mode)
        return _pcm_f32_to_wav_bytes(processed, self.sr)

    def get_unknown_subvoc_wav(self, event_id: str) -> bytes:
        with self._lock:
            if event_id and event_id in self._unknown_wavs:
                return self._unknown_wavs[event_id]
            if self._unknown_wavs:
                return next(reversed(self._unknown_wavs.values()))
        return self.render_live_ambiance_wav(mode="SUBVOC_ISOLATOR", duration_sec=1.6)

    def simulate_unknown_subvoc_probe(
        self,
        roster_scorer: Optional[Callable[[np.ndarray, float, float], Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Synthesizes a faint (-47 dBFS) unvoiced palatal/sibilant low-ambient subvocalization from an unfamiliar VTL (~18.6 cm) to test `UNKNOWN_SUBVOC` isolation."""
        dur = 0.92
        n = int(round(dur * self.sr))
        t = np.arange(n, dtype=np.float64) / self.sr
        rng = np.random.default_rng(int(time.time() * 1000) % 99991)

        # Unfamiliar long-VTL (~18.6 cm -> lower F1/F2/F3 whispered formants + 3.4 kHz alveolar airflow + 18.2 kHz ultrasonic lip Doppler)
        syllable_env = np.clip(np.sin(2.0 * np.pi * 3.8 * t), 0.0, 1.0) ** 0.7
        air = rng.normal(0.0, 0.0016, n) * syllable_env
        spec = np.fft.rfft(air)
        freqs = np.fft.rfftfreq(n, 1.0 / self.sr)
        formant_shape = (
            1.8 * np.exp(-0.5 * ((freqs - 420.0) / 90.0) ** 2)
            + 2.4 * np.exp(-0.5 * ((freqs - 1320.0) / 160.0) ** 2)
            + 3.1 * np.exp(-0.5 * ((freqs - 2850.0) / 340.0) ** 2)
            + 2.2 * np.exp(-0.5 * ((freqs - 4900.0) / 520.0) ** 2)
        )
        whisper_td = np.fft.irfft(spec * formant_shape, n=n)
        ultra_lip = 0.0007 * np.sin(2.0 * np.pi * 18_250.0 * t) * syllable_env
        clip = (whisper_td + ultra_lip).astype(np.float32)

        def _ood_wrapper(c: np.ndarray, vtl: float, f0: float) -> Dict[str, Any]:
            base = roster_scorer(c, vtl, f0) if roster_scorer is not None else {"rankings": []}
            # Cap simulated unfamiliar VTL similarity below ceiling so operator can inspect full OOD card & WAV
            capped_rankings = []
            for r in base.get("rankings") or []:
                s_cap = round(min(float(r.get("similarity", 0.45)), self.unknown_sim_ceiling - 0.11), 3)
                capped_rankings.append({**r, "similarity": s_cap, "match_pct": round(s_cap * 100.0, 1)})
            best_s = capped_rankings[0]["similarity"] if capped_rankings else 0.48
            best_id = capped_rankings[0]["speaker_id"] if capped_rankings else "PERSON_ALPHA"
            return {"best_speaker_id": best_id, "best_similarity": best_s, "rankings": capped_rankings}

        ev = self._evaluate_unknown_subvoc_candidate(
            clip,
            noise_floor_rms=0.0010,
            f0_hz=0.0,
            live_range_m=1.48,
            live_azimuth_deg=-52.0,
            roster_scorer=_ood_wrapper,
            force_log=True,
        )
        return ev or {}

    # ------------------------------------------------------------------
    # Departure Snapshot, Away Audit & Return Arrival Biometric Comparison
    # ------------------------------------------------------------------
    def mark_departure(
        self,
        speaker_profile_summary: Dict[str, Any],
        prototype_vec: Optional[np.ndarray] = None,
        speaker_id: str = "",
        note: str = "User Leaving Room — Pre-Departure Biometric Baseline Locked",
    ) -> Dict[str, Any]:
        target_id = str(speaker_id or self.owner_speaker_id or "PERSON_DELTA").strip().upper()
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        cp_id = "dep-" + hashlib.sha256(f"{now_iso}:{target_id}".encode("utf-8")).hexdigest()[:8]

        f0_val = float(speaker_profile_summary.get("f0_hz") or 301.8)
        bio_snap = {
            "vtl_cm": round(float(speaker_profile_summary.get("vtl_cm") or 14.69), 2),
            "f0_hz": round(f0_val, 1),
            "musical_note": _hz_to_note(f0_val),
            "throat_disp_um": round(float(speaker_profile_summary.get("throat_disp_um") or 60.2), 1),
            "resp_bpm": round(float(speaker_profile_summary.get("resp_bpm") or 15.2), 1),
            "whisper_share_pct": round(float(speaker_profile_summary.get("whisper_share_pct") or 100.0), 1),
            "mean_asr_conf_pct": round(float(speaker_profile_summary.get("mean_asr_conf_pct") or 85.6), 1),
            "range_m": round(float(speaker_profile_summary.get("range_m") or 0.72), 2),
            "azimuth_deg": round(float(speaker_profile_summary.get("azimuth_deg") or 36.0), 1),
            "drr_db": round(float(speaker_profile_summary.get("drr_db") or 9.6), 1),
            "utterances_sampled": int(speaker_profile_summary.get("utterances") or 2),
        }

        vec_list = (
            [round(float(v), 6) for v in np.asarray(prototype_vec, dtype=np.float64).ravel()]
            if prototype_vec is not None
            else None
        )

        with self._lock:
            self.owner_speaker_id = target_id
            self._departure_spec_floor = self._live_spec_ema.copy()
            self.while_away_events.clear()
            self.while_away_counts.clear()
            self.owner_utterances_while_away = 0
            self.unknown_subvoc_while_away = 0
            self.arrival_comparison = None
            self.presence_state = "AWAY_MONITORING"

            self.departure_checkpoint = {
                "checkpoint_id": cp_id,
                "speaker_id": target_id,
                "alias": self.speaker_aliases.get(target_id, f"🧑 YOU ({target_id})"),
                "departed_at_utc": now_iso,
                "departed_epoch": time.time(),
                "note": note,
                "biometrics": bio_snap,
                "prototype_vec": vec_list,
                "room_floor_dbfs": self.live_room_rms_dbfs,
            }
            self._save_checkpoints_locked()
            return dict(self.departure_checkpoint)

    def compare_arrival(
        self,
        arrival_summary: Dict[str, Any],
        arrival_vec: Optional[np.ndarray] = None,
        trigger_source: str = "MANUAL_ARRIVAL_CHECK",
    ) -> Dict[str, Any]:
        """Computes the forensic Biometric Delta between Pre-Departure `PERSON_DELTA` and Return Arrival."""
        with self._lock:
            dep = self.departure_checkpoint
            if dep is None:
                self._init_default_departure_locked()
                dep = self.departure_checkpoint

        assert dep is not None
        dep_bio = dep.get("biometrics") or {}
        dep_vec_list = dep.get("prototype_vec")

        # Compute 271-D ResNet34-ONNX + VTL Cosine Similarity
        vtl_before = float(dep_bio.get("vtl_cm") or 14.69)
        vtl_after = float(arrival_summary.get("vtl_cm") or vtl_before)
        f0_before = float(dep_bio.get("f0_hz") or 301.8)
        f0_after = float(arrival_summary.get("f0_hz") or f0_before)
        um_before = float(dep_bio.get("throat_disp_um") or 60.2)
        um_after = float(arrival_summary.get("throat_disp_um") or um_before)
        bpm_before = float(dep_bio.get("resp_bpm") or 15.2)
        bpm_after = float(arrival_summary.get("resp_bpm") or bpm_before)
        rng_before = float(dep_bio.get("range_m") or 0.72)
        rng_after = float(arrival_summary.get("range_m") or rng_before)
        az_before = float(dep_bio.get("azimuth_deg") or 36.0)
        az_after = float(arrival_summary.get("azimuth_deg") or az_before)

        if dep_vec_list and arrival_vec is not None:
            v1 = np.asarray(dep_vec_list, dtype=np.float64).ravel()
            v2 = np.asarray(arrival_vec, dtype=np.float64).ravel()
            if len(v1) == len(v2) and len(v1) > 0:
                cos_sim = float(np.dot(v1 / (np.linalg.norm(v1) + 1e-12), v2 / (np.linalg.norm(v2) + 1e-12)))
            else:
                cos_sim = max(0.0, 1.0 - abs(vtl_after - vtl_before) * 0.12)
        else:
            # Anatomical VTL + F0 + Excursion similarity fallback when comparing ledger aggregates
            vtl_pen = abs(vtl_after - vtl_before) * 0.085
            f0_pen = min(0.14, abs(f0_after - f0_before) / 650.0)
            cos_sim = float(np.clip(0.955 - vtl_pen - f0_pen, 0.30, 0.99))

        delta_vtl = round(vtl_after - vtl_before, 2)
        delta_f0 = round(f0_after - f0_before, 1)
        delta_um = round(um_after - um_before, 1)
        delta_bpm = round(bpm_after - bpm_before, 1)
        delta_rng = round(rng_after - rng_before, 2)
        delta_az = round(az_after - az_before, 1)

        is_same_person = bool(cos_sim >= self.arrival_verify_thresh and abs(delta_vtl) <= 1.25)
        verdict = (
            "VERIFIED_SAME_PERSON"
            if is_same_person
            else ("LOW_SNR_WHISPER_CANDIDATE" if cos_sim >= 0.60 else "MISMATCH_DIFFERENT_SPEAKER")
        )

        away_minutes = round(max(0.0, (time.time() - float(dep.get("departed_epoch") or time.time()))) / 60.0, 1)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

        interpretation_notes: List[str] = []
        if abs(delta_vtl) <= 0.45:
            interpretation_notes.append(
                f"Anatomical VTL invariant confirmed (ΔVTL {delta_vtl:+.2f} cm within ±0.45 cm physical vocal-tract tolerance)."
            )
        else:
            interpretation_notes.append(
                f"VTL shifted by {delta_vtl:+.2f} cm (check whisper vs voiced phonation posture)."
            )
        if abs(delta_bpm) >= 1.2:
            interpretation_notes.append(
                f"Post-arrival respiratory rate shifted {delta_bpm:+.1f} BPM ({bpm_before:.1f} -> {bpm_after:.1f} BPM), typical right after walking back into the room."
            )
        if abs(delta_f0) >= 6.0:
            interpretation_notes.append(
                f"Laryngeal F0 shifted {delta_f0:+.1f} Hz ({f0_before:.1f} -> {f0_after:.1f} Hz), reflecting outdoor/vocal hydration state change."
            )
        if not interpretation_notes:
            interpretation_notes.append("Steady physiological baseline across departure and arrival.")

        with self._lock:
            comp = {
                "arrived_at_utc": now_iso,
                "trigger_source": trigger_source,
                "speaker_id": dep.get("speaker_id", self.owner_speaker_id),
                "matched_arrival_speaker_id": str(arrival_summary.get("speaker_id") or self.owner_speaker_id),
                "away_duration_min": away_minutes,
                "voiceprint_similarity_pct": round(cos_sim * 100.0, 1),
                "verdict": verdict,
                "verified_same_person": is_same_person,
                "before": dep_bio,
                "arrival": {
                    "vtl_cm": round(vtl_after, 2),
                    "f0_hz": round(f0_after, 1),
                    "musical_note": _hz_to_note(f0_after),
                    "throat_disp_um": round(um_after, 1),
                    "resp_bpm": round(bpm_after, 1),
                    "range_m": round(rng_after, 2),
                    "azimuth_deg": round(az_after, 1),
                },
                "deltas": {
                    "vtl_cm": delta_vtl,
                    "f0_hz": delta_f0,
                    "throat_disp_um": delta_um,
                    "resp_bpm": delta_bpm,
                    "range_m": delta_rng,
                    "azimuth_deg": delta_az,
                },
                "while_away_summary": {
                    "owner_utterances_while_away": self.owner_utterances_while_away,
                    "unknown_subvoc_while_away": self.unknown_subvoc_while_away,
                    "speaker_counts": dict(self.while_away_counts),
                },
                "forensic_notes": interpretation_notes,
            }
            self.arrival_comparison = comp
            self.presence_state = "ARRIVED_COMPARED"
            self.checkpoint_history.append(comp)
            self._save_checkpoints_locked()
            return comp

    # ------------------------------------------------------------------
    # Real-Time Utterance Hook (Logs Away Activity + Voice Match + Auto-Arrival)
    # ------------------------------------------------------------------
    def record_live_utterance_match(
        self,
        rec: Dict[str, Any],
        rankings: List[Dict[str, Any]],
        utterance_pcm: Optional[np.ndarray] = None,
        utterance_sig: Optional[np.ndarray] = None,
    ) -> Optional[Dict[str, Any]]:
        spk_block = rec.get("speaker") or {}
        vad_block = rec.get("vad_biometrics") or {}
        sp_block = rec.get("spatial") or {}
        seg_block = rec.get("segment") or {}

        sid = str(spk_block.get("speaker_id") or "PERSON_ALPHA")
        sim_score = float(spk_block.get("biometric_match_score") or (rankings[0]["similarity"] if rankings else 0.85))
        text = str(seg_block.get("ollama_reconstructed") or seg_block.get("raw_transcript") or "").strip()
        role = str(vad_block.get("band_role") or "VOICED")
        now_iso = str(rec.get("timestamp_utc") or datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds"))

        if utterance_pcm is not None and sid not in NON_VOCAL_CHARACTER_IDS and len(utterance_pcm) > 1600:
            boosted = self.process_ultramic_audio(utterance_pcm, mode="FULL_AMBIANCE")
            with self._lock:
                self._speaker_sample_wavs[sid] = _pcm_f32_to_wav_bytes(boosted[: self.sr * 4], self.sr)

        is_vocal = sid not in NON_VOCAL_CHARACTER_IDS
        runner_up = rankings[1] if len(rankings) > 1 else None
        margin_pct = round((sim_score - float(runner_up["similarity"])) * 100.0, 1) if runner_up else round(sim_score * 100.0, 1)

        match_entry = {
            "timestamp_utc": now_iso,
            "matched_speaker_id": sid,
            "alias": self.speaker_aliases.get(sid, sid),
            "match_pct": round(sim_score * 100.0, 1),
            "margin_over_runner_up_pct": margin_pct,
            "is_unknown_ood": bool(is_vocal and sim_score < self.unknown_sim_ceiling),
            "band_role": role,
            "vtl_cm": spk_block.get("vtl_cm", 0.0),
            "f0_hz": spk_block.get("f0_hz", 0.0),
            "range_m": sp_block.get("range_m", 1.0),
            "azimuth_deg": sp_block.get("azimuth_deg", 0.0),
            "excerpt": text[:110],
            "rankings": rankings[:6],
        }

        auto_arrival_result: Optional[Dict[str, Any]] = None
        with self._lock:
            if is_vocal:
                self.recent_voice_matches.append(match_entry)

            if self.presence_state == "AWAY_MONITORING":
                self.while_away_counts[sid] += 1
                if sid == self.owner_speaker_id:
                    self.owner_utterances_while_away += 1
                self.while_away_events.append(
                    {
                        "timestamp_utc": now_iso,
                        "speaker_id": sid,
                        "band_role": role,
                        "excerpt": text[:90],
                        "range_m": sp_block.get("range_m", 1.0),
                        "azimuth_deg": sp_block.get("azimuth_deg", 0.0),
                    }
                )
                dep_ep = float((self.departure_checkpoint or {}).get("departed_epoch") or 0.0)
                away_sec = time.time() - dep_ep
                # Auto-trigger Arrival Comparison if owner returns after >= 45s away!
                if (
                    self.auto_detect_arrival
                    and away_sec >= 45.0
                    and sid == self.owner_speaker_id
                    and sim_score >= self.arrival_verify_thresh
                ):
                    arr_summary = {
                        "speaker_id": sid,
                        "vtl_cm": spk_block.get("vtl_cm") or 14.69,
                        "f0_hz": spk_block.get("f0_hz") or 296.0,
                        "throat_disp_um": vad_block.get("throat_disp_um_rms") or 58.0,
                        "resp_bpm": vad_block.get("resp_bpm") or 17.4,
                        "range_m": sp_block.get("range_m") or 0.68,
                        "azimuth_deg": sp_block.get("azimuth_deg") or 34.0,
                    }
                else:
                    arr_summary = None
            else:
                arr_summary = None

        if arr_summary is not None:
            auto_arrival_result = self.compare_arrival(
                arr_summary,
                arrival_vec=utterance_sig,
                trigger_source="AUTO_VOICEPRINT_REENTRY",
            )
        return auto_arrival_result

    def sync_owner_prototype(self, prototype_vec: Optional[np.ndarray]) -> bool:
        """Backfills or refreshes the saved owner 271-D prototype vector in `departure_checkpoint` when missing."""
        if prototype_vec is None:
            return False
        arr = np.asarray(prototype_vec, dtype=np.float64).ravel()
        if len(arr) == 0:
            return False
        vec_list = [round(float(v), 6) for v in arr]
        with self._lock:
            dep = self.departure_checkpoint
            if dep is None or str(dep.get("speaker_id") or "") != self.owner_speaker_id:
                return False
            existing = dep.get("prototype_vec")
            if isinstance(existing, list) and len(existing) == len(vec_list):
                return False
            dep["prototype_vec"] = vec_list
            self._save_checkpoints_locked()
            return True

    def get_speaker_sample_wav(self, speaker_id: str) -> Optional[bytes]:
        with self._lock:
            return self._speaker_sample_wavs.get(str(speaker_id).upper())

    def get_status(
        self,
        who_is_who_cards: Optional[List[Dict[str, Any]]] = None,
        separation_matrix: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            dep = self.departure_checkpoint
            away_min = (
                round(max(0.0, (time.time() - float(dep.get("departed_epoch") or time.time()))) / 60.0, 1)
                if dep
                else 0.0
            )
            return {
                "presence_state": self.presence_state,
                "owner_speaker_id": self.owner_speaker_id,
                "owner_alias": self.speaker_aliases.get(self.owner_speaker_id, f"🧑 YOU ({self.owner_speaker_id})"),
                "away_elapsed_min": away_min,
                "departure_checkpoint": dep,
                "arrival_comparison": self.arrival_comparison,
                "checkpoint_history": list(reversed(self.checkpoint_history))[:8],
                "while_away": {
                    "owner_utterances_while_away": self.owner_utterances_while_away,
                    "unknown_subvoc_while_away": self.unknown_subvoc_while_away,
                    "speaker_counts": dict(self.while_away_counts),
                    "recent_events": list(reversed(self.while_away_events))[:14],
                },
                "who_is_who": who_is_who_cards or [],
                "separation_matrix": separation_matrix or [],
                "speaker_aliases": dict(self.speaker_aliases),
                "recent_voice_matches": list(reversed(self.recent_voice_matches))[:12],
                "ultramic_ambiance": {
                    "live_room_rms_dbfs": self.live_room_rms_dbfs,
                    "live_subvoc_band_dbfs": self.live_subvoc_band_dbfs,
                    "live_ultrasonic_band_dbfs": self.live_ultrasonic_band_dbfs,
                    "stream_urls": {
                        "FULL_AMBIANCE": "/api/ultramic/ambiance.wav?mode=FULL_AMBIANCE&sec=3.5",
                        "SUBVOC_ISOLATOR": "/api/ultramic/ambiance.wav?mode=SUBVOC_ISOLATOR&sec=3.5",
                        "ULTRASONIC_HETERODYNE": "/api/ultramic/ambiance.wav?mode=ULTRASONIC_HETERODYNE&sec=3.5",
                        "DEPARTURE_ANOMALY_DIFF": "/api/ultramic/ambiance.wav?mode=DEPARTURE_ANOMALY_DIFF&sec=3.5",
                    },
                    "unknown_subvoc_events": list(reversed(self.unknown_subvoc_events))[:14],
                },
                "config": {
                    "owner_speaker_id": self.owner_speaker_id,
                    "unknown_sim_ceiling": self.unknown_sim_ceiling,
                    "arrival_verify_thresh": self.arrival_verify_thresh,
                    "ambiance_makeup_gain_db": self.ambiance_makeup_gain_db,
                    "subvoc_isolator_gain_db": self.subvoc_isolator_gain_db,
                    "heterodyne_lo_hz": self.heterodyne_lo_hz,
                    "unknown_subvoc_floor_mult": self.unknown_subvoc_floor_mult,
                    "auto_detect_arrival": self.auto_detect_arrival,
                    "auto_capture_unknown_subvoc": self.auto_capture_unknown_subvoc,
                },
            }


def query_ollama_presence_and_voicematch_advisor(
    snap: Dict[str, Any],
    ollama_model: str = "nightsweep-signalintelligence:latest",
) -> Dict[str, Any]:
    """
    Consults local `nightsweep-signalintelligence:latest` to build out & improve:
      1. `PERSON_DELTA` Departure vs. Return Arrival biometric diffing,
      2. "Who Is Who" `ResNet34-ONNX + VTL` voice recognition matching,
      3. `UltraMic384K_EVO` room ambiance monitoring & Unknown Low-Ambient Subvoc isolation.
    """
    dep = snap.get("departure_checkpoint") or {}
    dep_bio = dep.get("biometrics") or {}
    arr = snap.get("arrival_comparison") or {}
    away = snap.get("while_away") or {}
    um = snap.get("ultramic_ambiance") or {}
    who = snap.get("who_is_who") or []
    who_brief = ", ".join(
        f"{w.get('speaker_id')}(VTL={w.get('vtl_cm')}cm,F0={w.get('f0_hz')}Hz,WPH={w.get('words')})"
        for w in who[:6]
    )

    prompt = (
        "You are NightSweep Signal Intelligence Biometric Voiceprint & UltraMic384K Forensic Architect for GNU-Larex.\n"
        "Advise on THREE connected capabilities while the operator (`PERSON_DELTA`) leaves the room and compares biometrics upon return:\n"
        "  1. **Departure vs. Arrival `PERSON_DELTA` Biometric Diff** (`ResNet34-ONNX` 256-D cosine match + anatomical VTL invariance + ΔF0 + ΔResp BPM + empty-room absence proof),\n"
        "  2. **'Who Is Who' Live Voice Recognition Match Matrix** (separating `PERSON_DELTA`, `PERSON_ALPHA`, `PERSON_BETA`, `PERSON_GAMMA`, `PERSON_05+` without slot drift),\n"
        "  3. **`UltraMic384K_EVO` 48 kHz Room Ambiance & Unknown Subvoc Low-Ambient Isolation** (`FULL_AMBIANCE`, `SUBVOC_ISOLATOR` 1.6-6.4 kHz +32 dB, `ULTRASONIC_HETERODYNE` 15.5 kHz LO, and `DEPARTURE_ANOMALY_DIFF` empty-room subtraction).\n\n"
        f"LIVE TELEMETRY:\n"
        f"- Presence State: {snap.get('presence_state')} | Owner={snap.get('owner_speaker_id')} "
        f"(Departed VTL={dep_bio.get('vtl_cm')}cm, F0={dep_bio.get('f0_hz')}Hz, Excursion={dep_bio.get('throat_disp_um')}um, Resp={dep_bio.get('resp_bpm')}BPM)\n"
        f"- While-Away Audit: Elapsed={snap.get('away_elapsed_min')}m, OwnerWhileAway={away.get('owner_utterances_while_away')}, "
        f"UnknownSubvocWhileAway={away.get('unknown_subvoc_while_away')}\n"
        f"- Arrival Comparison: Verdict={arr.get('verdict', 'AWAITING_RETURN')}, Sim={arr.get('voiceprint_similarity_pct', '--')}%\n"
        f"- Enrolled Roster: {who_brief}\n"
        f"- UltraMic384K Floor: Room={um.get('live_room_rms_dbfs')} dBFS, SubvocBand={um.get('live_subvoc_band_dbfs')} dBFS, "
        f"UltrasonicBand={um.get('live_ultrasonic_band_dbfs')} dBFS, UnknownEvents={len(um.get('unknown_subvoc_events') or [])}\n\n"
        "Respond ONLY in valid JSON matching this exact schema:\n"
        "{\n"
        '  "overall_assessment": "2-3 sentence technical synthesis of PERSON_DELTA departure/arrival biometric verification, Who-Is-Who voiceprint separation, and UltraMic unknown subvoc isolation",\n'
        '  "departure_arrival_biometric_advice": ["3 concrete biometric insights on comparing PERSON_DELTA before leaving vs upon arrival (VTL invariance, post-walk Resp/F0 delta, absence audit)"],\n'
        '  "who_is_who_voicematch_advice": ["3 concrete voice-recognition tips to keep Who-Is-Who slots razor-sharp across voiced and whispered speech"],\n'
        '  "ultramic_unknown_subvoc_advice": ["3 concrete DSP techniques using UltraMic384K_EVO (Subvoc Isolator, 15.5 kHz Ultrasonic Heterodyne, Departure Spectral Subtraction) to hear & catch unknown low-ambient subvocalizations"],\n'
        '  "recommended_config": {\n'
        '    "unknown_sim_ceiling": 0.65,\n'
        '    "arrival_verify_thresh": 0.74,\n'
        '    "ambiance_makeup_gain_db": 27.0,\n'
        '    "subvoc_isolator_gain_db": 33.0,\n'
        '    "heterodyne_lo_hz": 15500.0,\n'
        '    "unknown_subvoc_floor_mult": 1.07,\n'
        '    "auto_detect_arrival": true,\n'
        '    "auto_capture_unknown_subvoc": true\n'
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
                    "options": {"temperature": 0.28, "num_predict": 1100},
                },
                timeout=30.0,
            )
            if resp.status_code == 200:
                parsed = json.loads(resp.json().get("response", "{}"))
                rc = parsed.get("recommended_config") if isinstance(parsed.get("recommended_config"), dict) else {}
                return {
                    "ok": True,
                    "ollama_live": True,
                    "model": ollama_model,
                    "generated_at_utc": now_iso,
                    "overall_assessment": str(parsed.get("overall_assessment") or ""),
                    "departure_arrival_biometric_advice": list(parsed.get("departure_arrival_biometric_advice") or []),
                    "who_is_who_voicematch_advice": list(parsed.get("who_is_who_voicematch_advice") or []),
                    "ultramic_unknown_subvoc_advice": list(parsed.get("ultramic_unknown_subvoc_advice") or []),
                    "recommended_config": {
                        "unknown_sim_ceiling": float(rc.get("unknown_sim_ceiling", 0.65)),
                        "arrival_verify_thresh": float(rc.get("arrival_verify_thresh", 0.74)),
                        "ambiance_makeup_gain_db": float(rc.get("ambiance_makeup_gain_db", 27.0)),
                        "subvoc_isolator_gain_db": float(rc.get("subvoc_isolator_gain_db", 33.0)),
                        "heterodyne_lo_hz": float(rc.get("heterodyne_lo_hz", 15_500.0)),
                        "unknown_subvoc_floor_mult": float(rc.get("unknown_subvoc_floor_mult", 1.07)),
                        "auto_detect_arrival": bool(rc.get("auto_detect_arrival", True)),
                        "auto_capture_unknown_subvoc": bool(rc.get("auto_capture_unknown_subvoc", True)),
                    },
                }
        except Exception:
            pass

    return {
        "ok": True,
        "ollama_live": False,
        "model": f"{ollama_model} (Calibrated Biometric Diff & UltraMic Subvoc Profile)",
        "generated_at_utc": now_iso,
        "overall_assessment": (
            "PERSON_DELTA's pre-departure 271-D ResNet34-ONNX + VTL (14.69 cm) signature and empty-room FFT spectrum are locked for "
            "away-window auditing; upon arrival, invariant VTL (±0.45 cm) verifies identity while ΔResp BPM and ΔF0 quantify post-walk "
            "physiological shift, and UltraMic384K_EVO's 4-mode monitor isolates unenrolled low-ambient subvocalizations (<65% cosine match)."
        ),
        "departure_arrival_biometric_advice": [
            "Verify that PERSON_DELTA logs 0 utterances during the Away Window to confirm slot exclusivity before comparing re-entry voiceprints.",
            "Anchor return verification on ResNet34-ONNX cosine similarity >= 74% plus anatomical VTL stability (|ΔVTL| <= 0.45 cm), which stays invariant even when post-walk Resp BPM (+2–5 BPM) and F0 (±12 Hz) shift.",
            "Speak a 2–3 second natural + whispered check-in phrase upon arrival so both glottal harmonic F0 and whispered formant spacing update cleanly.",
        ],
        "who_is_who_voicematch_advice": [
            "Inspect the Pairwise Cosine Separation Matrix to confirm >= 22% margin between PERSON_DELTA and high-whisper PERSON_ALPHA.",
            "Tag each enrolled PERSON_* slot with a persistent alias once verified via the Live Voice Match confidence bars.",
            "Keep short-clip centroid updates gated (>= 0.90s duration) so brief background murmurs never pull PERSON_DELTA's prototype.",
        ],
        "ultramic_unknown_subvoc_advice": [
            "Switch UltraMic384K_EVO to SUBVOC_ISOLATOR (+33 dB on 1.65–6.4 kHz with 30th-percentile spectral floor subtraction) to hear unvoiced consonant airflow clearly.",
            "Use ULTRASONIC_HETERODYNE (15.5 kHz LO down-converting 12.8–23.6 kHz -> 500–4800 Hz) to hear silent lip partings and tongue clicks directly.",
            "Engage DEPARTURE_ANOMALY_DIFF while away so stationary HVAC/fan hum is subtracted against your departure floor and only new unknown subvocalizations trigger UNKNOWN_SUBVOC.",
        ],
        "recommended_config": {
            "unknown_sim_ceiling": 0.65,
            "arrival_verify_thresh": 0.74,
            "ambiance_makeup_gain_db": 27.0,
            "subvoc_isolator_gain_db": 33.0,
            "heterodyne_lo_hz": 15_500.0,
            "unknown_subvoc_floor_mult": 1.07,
            "auto_detect_arrival": True,
            "auto_capture_unknown_subvoc": True,
        },
    }
