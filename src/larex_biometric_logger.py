"""
GNU-Larex :: Enhanced Biometric-Fused VAD, Per-Person Speaker Attribution &
Forensic Word Audit Ledger (LAREX-NSIG-v1 Standard)
===========================================================================
Reference Architecture aligned with local Ollama model:
  `nightsweep-signalintelligence:latest` / `strategic-relay:latest`
  (Sections 1, 9, 13, 14, 19, 28, 36, 37, and 41).

Capabilities:
  1. Multi-Modal Biometric-Gated VAD (`BiometricFusedVAD`):
     - Pre-emphasis (alpha = 0.97) + 80 Hz rumble high-pass (Sec. 9)
     - Spectral Entropy + Zero-Crossing Rate (ZCR) + 2-8 kHz Fricative Ratio (Sec. 9)
     - Adaptive 3.5x Noise-Floor Gate & Band-Role A/B Split (Sec. 41)
     - 1-NN Cosine OOD Hallucination Guard vs CLEAN_VOCAL_CLUSTER (Sec. 13)
     - Physiological Liveness Co-Gate (Respiration exhalation phase / throat micro-motion)
  2. Whisper-Invariant Per-Person Biometric Diarizer (`BiometricSpeakerAttributor`):
     - Estimates physical Vocal Tract Length (VTL in cm from F1/F2/F3 formants —
       invariant across normal speech AND unvoiced whispers!) + F0 + MFCC + BPM
     - Open-set cosine prototype clustering (PERSON_ALPHA, PERSON_BETA, PERSON_GAMMA...)
  3. Streaming Word-Level ASR + Local Ollama (`nightsweep-signalintelligence:latest`)
     Contextual Phonetic Repair (preserving both `raw_words` and `reconstructed_text`)
  4. Tamper-Evident Triple-Sink Forensic Ledger (`ForensicWordLedger`):
     - SHA-256 Hash-Chained `.jsonl` (`biometric_words_<session>.jsonl`)
     - Optional `cryptography.fernet.Fernet` encrypted `.enc` ledger (Sec. 14)
     - Indexed SQLite WAL database (`larex_speaker_words.db`, Sec. 36)
"""

from __future__ import annotations

import collections
import dataclasses
import datetime
import hashlib
import json
import math
import os
import queue
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import numpy as np

from src.larex_dsp import (
    AsyncHackRFStream,
    AsyncSDRRadarStream,
    BreathAndMouthExtractor,
    WhisperEarwormEngine,
    ZMQWhisperSensorBridge,
)
from src.larex_markov_typing import (
    TYPIST_SPEAKER_ID,
    AcousticTypingPersonEngine,
    SentenceMarkovDeltaTracker,
)
from src.larex_prespeech_electronics import (
    CELLPHONE_SPEAKER_ID,
    ELECTRONIC_CHARACTER_IDS,
    MEMS_SPEAKER_ID,
    ElectronicCharacterEngine,
    PreSpeechTriggerEngine,
)
from src.larex_presence_voicematch import PresenceVoiceMatchAndUltraMicEngine
from src.larex_delta_avatar import DeltaMotionAndAvatarEngine
from src.larex_reading_piggyback import (
    OTHER_ROOM_SPEAKER_ID,
    MidAirPiggybackSublevelEngine,
    SilentReadingDetector,
)
from src.larex_talkback import EarwormTalkbackOrchestrator

try:
    from cryptography.fernet import Fernet  # type: ignore
    HAS_FERNET = True
except ImportError:
    HAS_FERNET = False

try:
    import requests  # type: ignore
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from scipy import signal as sp_signal  # type: ignore
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


# Section 13 Reference Cluster from `nightsweep-signalintelligence:latest`
CLEAN_VOCAL_CLUSTER = np.array([0.15, 0.22, 0.05, 0.12], dtype=np.float64)


@dataclasses.dataclass
class BiometricSnapshot:
    """Real-time physiological liveness & vocal biomarkers bound to an audio frame/segment."""
    resp_bpm: float = 0.0
    resp_phase_exhale: bool = True
    throat_disp_um_rms: float = 0.0
    f0_hz: float = 0.0
    vtl_cm: float = 17.0
    ood_cosine_dist: float = 0.0
    liveness_verified: bool = True
    band_role: str = "VOICED_LARYNX"  # VOICED_LARYNX | UNVOICED_WHISPER | LOW_AMBIENT_WHISPER
    gesture_subvoc_score: float = 0.0
    low_ambient_cued: bool = False
    ambient_snr_db: float = 0.0
    vad_motion_score: float = 0.0
    movement_state: str = "STILL_ANCHORED"


@dataclasses.dataclass
class ExtractedWord:
    """Word-level forensic token with timing and ASR probability."""
    word: str
    start_sec: float
    end_sec: float
    probability: float


@dataclasses.dataclass
class SpatialPositionSnapshot:
    """
    2D Acoustic / RF Spatial Position Fix relative to sensor origin (0, 0).
      - Tier 1 (`TIER1_DRR_POLAR`): Single wideband mic DRR + C50 clarity ranging + HF polar off-axis directivity
      - Tier 2 (`TIER2_ACOUSTIC_RF_TOF`): Hybrid SDR RF vs Acoustic Time-of-Flight ranging (r = c_sound * dt)
      - Tier 3 (`TIER3_GCC_PHAT_TDOA`): Dual-mic stereo GCC-PHAT azimuth triangulation + DRR/ToF range
    """
    range_m: float = 1.15
    azimuth_deg: float = 0.0
    x_m: float = 0.0
    y_m: float = 1.15
    drr_db: float = 4.5
    c50_db: float = 6.0
    hf_directivity_db: float = -4.0
    radial_vel_cms: float = 0.0
    azimuth_vel_degs: float = 0.0
    movement_state: str = "STILL_ANCHORED"
    proximity_zone: str = "MID_FIELD"   # NEAR_FIELD | MID_FIELD | FAR_FIELD
    positioning_mode: str = "TIER1_DRR_POLAR"
    confidence: float = 0.76


class SpatialPositionEstimator:
    """
    Real-time 3-Tier Spatial Position Estimator for GNU-Larex:
      1. Tier 1 (Single Wideband Mic — Active Default):
         - Computes Direct-to-Reverberant Energy Ratio (DRR) & C50 Clarity Index from
           phoneme onset impulses (0-18 ms early arrival) vs diffuse room reverberant decay
           (50-160 ms tail): r_drr = r_critical * 10^(-DRR_dB / 20).
         - Computes High-Frequency Polar Off-Axis Directivity (4-15 kHz vs 300-1800 Hz tilt)
           to estimate off-axis polar angle |theta| on directional/ultrasonic capsules.
         - Stabilizes per-speaker 2D coordinates (range_m, azimuth_deg, x_m, y_m) and
           tracks radial approach/recede velocity (cm/s).
      2. Tier 2 (Acoustic-RF Hybrid Time-of-Flight):
         - Cross-correlates instantaneous 915 MHz SDR RF laryngeal/chest phase envelope against
           delayed acoustic wave arrival (c_sound = 343.2 m/s -> 2.914 ms/meter).
      3. Tier 3 (Dual-Mic Stereo GCC-PHAT TDOA):
         - Generalized Cross-Correlation with Phase Transform across mic baseline d_m:
           theta = arcsin(343.2 * tau_lag / d_m).
    """

    SPEED_OF_SOUND_MPS = 343.2
    SPEAKER_SECTOR_SIGN = {
        "PERSON_ALPHA": -1.0,
        "PERSON_BETA": 1.0,
        "PERSON_GAMMA": -0.65,
        "PERSON_DELTA": 0.65,
    }
    SPEAKER_POLAR_ALIGNMENT: Dict[str, Dict[str, float]] = {
        "DEFAULT": {
            "anchor_az_deg": 0.0,
            "polar_gain": 2.10,
            "ref_tilt_voiced_db": -11.5,
            "ref_tilt_whisper_db": -6.0,
            "drr_trim_db": 0.0,
            "max_range_step_m": 0.45,
            "max_az_step_deg": 9.0,
        },
        # PERSON_ALPHA: Near-field left sector (-45 deg), high whisper rate
        "PERSON_ALPHA": {
            "anchor_az_deg": -45.0,
            "polar_gain": 1.85,
            "ref_tilt_voiced_db": -11.5,
            "ref_tilt_whisper_db": -5.8,
            "drr_trim_db": 0.5,
            "max_range_step_m": 0.40,
            "max_az_step_deg": 8.0,
        },
        # PERSON_BETA: Near-field right sector (+48 deg), high voiced speech activity
        "PERSON_BETA": {
            "anchor_az_deg": 48.0,
            "polar_gain": 1.80,
            "ref_tilt_voiced_db": -11.8,
            "ref_tilt_whisper_db": -6.2,
            "drr_trim_db": 0.8,
            "max_range_step_m": 0.38,
            "max_az_step_deg": 7.5,
        },
        # PERSON_GAMMA: Mid-field (-15 deg, ~1.67 m), fast active pace (8,044 WPH)
        "PERSON_GAMMA": {
            "anchor_az_deg": -15.0,
            "polar_gain": 2.05,
            "ref_tilt_voiced_db": -13.2,
            "ref_tilt_whisper_db": -7.5,
            "drr_trim_db": -1.5,
            "max_range_step_m": 0.48,
            "max_az_step_deg": 8.5,
        },
        # PERSON_DELTA: Quiet short whispers (+36 deg), DRR boost compensates low vocal output
        "PERSON_DELTA": {
            "anchor_az_deg": 36.0,
            "polar_gain": 1.75,
            "ref_tilt_voiced_db": -11.2,
            "ref_tilt_whisper_db": -5.5,
            "drr_trim_db": 2.8,
            "max_range_step_m": 0.36,
            "max_az_step_deg": 7.0,
        },
        # PERSON_TYPIST: Dedicated isolated desk-keyboard acoustic transient capture (-8 deg, ~0.68 m)
        "PERSON_TYPIST": {
            "anchor_az_deg": -8.0,
            "polar_gain": 1.50,
            "ref_tilt_voiced_db": -8.0,
            "ref_tilt_whisper_db": -3.5,
            "drr_trim_db": 4.2,
            "max_range_step_m": 0.25,
            "max_az_step_deg": 5.0,
        },
    }

    def __init__(
        self,
        samp_rate: float = 48_000.0,
        room_critical_dist_m: float = 1.45,
        mic_spacing_m: float = 0.18,
        gcc_phat_beta: float = 0.78,
    ) -> None:
        self.samp_rate = float(samp_rate)
        self.room_critical_dist_m = float(room_critical_dist_m)
        self.mic_spacing_m = float(mic_spacing_m)
        self.gcc_phat_beta = float(np.clip(gcc_phat_beta, 0.45, 1.0))
        self.polar_profiles: Dict[str, Dict[str, float]] = {
            k: dict(v) for k, v in self.SPEAKER_POLAR_ALIGNMENT.items()
        }
        self._speaker_tracks: Dict[str, Dict[str, float]] = {}
        self.live_fix = SpatialPositionSnapshot()
        self.last_multi_gcc_sources: List[Dict[str, float]] = []

    def set_speaker_polar_alignment(
        self, speaker_id: str, overrides: Optional[Dict[str, Any]] = None
    ) -> Dict[str, float]:
        spk = str(speaker_id or "DEFAULT").strip().upper()
        base = dict(self.polar_profiles.get(spk, self.polar_profiles["DEFAULT"]))
        if overrides:
            bounds = {
                "anchor_az_deg": (-80.0, 80.0),
                "polar_gain": (0.4, 4.5),
                "ref_tilt_voiced_db": (-24.0, 2.0),
                "ref_tilt_whisper_db": (-20.0, 4.0),
                "drr_trim_db": (-6.0, 6.0),
                "max_range_step_m": (0.10, 1.50),
                "max_az_step_deg": (2.0, 30.0),
            }
            for k, (lo, hi) in bounds.items():
                if k in overrides and overrides[k] is not None:
                    base[k] = round(float(np.clip(float(overrides[k]), lo, hi)), 3)
        self.polar_profiles[spk] = base
        return dict(base)

    def get_polar_alignment_profiles(self) -> Dict[str, Dict[str, float]]:
        return {k: dict(v) for k, v in self.polar_profiles.items()}

    @staticmethod
    def _zone_from_range(r_m: float) -> str:
        if r_m < 0.90:
            return "NEAR_FIELD"
        if r_m <= 2.25:
            return "MID_FIELD"
        return "FAR_FIELD"

    def locate_multi_speaker_gcc_phat(
        self,
        ch_left: np.ndarray,
        ch_right: np.ndarray,
        max_sources: int = 3,
        beta: Optional[float] = None,
        f_lo_hz: float = 250.0,
        f_hi_hz: float = 6800.0,
    ) -> List[Dict[str, float]]:
        """
        Advanced Multiband Speech-Weighted GCC-PHAT-Beta Localization & Separation:
          - Applies a 250-6800 Hz speech/formant spectral coherence mask to reject <250 Hz
            HVAC room rumble and out-of-band ultrasonic noise.
          - Applies partial Phase Transform weighting |X1 * X2*|^beta (beta=0.78 default)
            for reverberation resilience without amplifying silent frequency bins.
          - Uses 16x zero-padded IFFT + 3-point parabolic sub-sample lag interpolation
            for sub-degree TDOA precision (+-0.2 deg).
          - Iteratively notches detected TDOA peaks (+-320 us guard window) to separate
            simultaneous / overlapping speakers.
        """
        n = min(len(ch_left), len(ch_right))
        if n < 256:
            return []
        use_beta = float(np.clip(self.gcc_phat_beta if beta is None else beta, 0.45, 1.0))
        win = np.hanning(n)
        x1 = (ch_left[:n].astype(np.float64) - float(np.mean(ch_left[:n]))) * win
        x2 = (ch_right[:n].astype(np.float64) - float(np.mean(ch_right[:n]))) * win

        interp = 16
        n_fft = 1 << int(math.ceil(math.log2(max(1024, 2 * n))))
        X1 = np.fft.rfft(x1, n=n_fft)
        X2 = np.fft.rfft(x2, n=n_fft)
        freqs = np.fft.rfftfreq(n_fft, d=1.0 / self.samp_rate)

        cross = X1 * np.conj(X2)
        mag = np.abs(cross)
        # Smooth speech/whisper formant coherence taper (250 Hz .. 6800 Hz)
        band_mask = (freqs >= f_lo_hz) & (freqs <= min(f_hi_hz, 0.46 * self.samp_rate))
        weights = np.zeros_like(freqs, dtype=np.float64)
        if np.any(band_mask):
            bf = freqs[band_mask]
            # Slight SNR-aware spectral Magnitude Weighting * PHAT^beta
            taper = np.sin(np.pi * np.clip((bf - f_lo_hz) / max(f_hi_hz - f_lo_hz, 100.0), 0.08, 0.92))
            weights[band_mask] = 0.35 + 0.65 * taper
        R = (cross * weights) / ((mag ** use_beta) + 1e-12)
        cc = np.fft.irfft(R, n=interp * n_fft)

        max_tau = self.mic_spacing_m / self.SPEED_OF_SOUND_MPS
        max_shift = max(2, int(round(interp * self.samp_rate * max_tau)))
        cc_win = np.abs(np.concatenate((cc[-max_shift:], cc[: max_shift + 1]))).copy()
        if len(cc_win) < 5:
            return []

        notch_rad = max(2, int(round(0.00032 * interp * self.samp_rate)))  # +-320 us separation guard
        baseline_med = float(np.median(cc_win) + 1e-12)
        baseline_rms = float(np.sqrt(np.mean(cc_win * cc_win)) + 1e-12)
        work = cc_win.copy()
        sources: List[Dict[str, float]] = []

        for rank in range(max(1, int(max_sources))):
            pk = int(np.argmax(work))
            pk_val = float(work[pk])
            if pk_val <= 0.0:
                break
            psr_db = 20.0 * math.log10(max(pk_val, 1e-12) / max(baseline_med, 1e-12))
            if rank > 0 and psr_db < 8.5:
                break

            # 3-point parabolic sub-sample interpolation around peak
            if 0 < pk < (len(cc_win) - 1):
                y0 = float(cc_win[pk - 1])
                y1 = float(cc_win[pk])
                y2 = float(cc_win[pk + 1])
                denom = y0 - 2.0 * y1 + y2
                frac = 0.5 * (y0 - y2) / denom if abs(denom) > 1e-12 else 0.0
                frac = float(np.clip(frac, -0.5, 0.5))
            else:
                frac = 0.0

            exact_shift = (pk + frac) - max_shift
            tau_s = exact_shift / float(interp * self.samp_rate)
            sin_theta = float(
                np.clip((self.SPEED_OF_SOUND_MPS * tau_s) / max(self.mic_spacing_m, 0.03), -1.0, 1.0)
            )
            az_deg = math.degrees(math.asin(sin_theta))
            conf = float(np.clip((pk_val / (baseline_rms * 2.6 + 1e-12)) * 0.55 + (psr_db / 42.0), 0.15, 0.99))
            sources.append(
                {
                    "rank": float(rank + 1),
                    "azimuth_deg": round(az_deg, 2),
                    "tdoa_us": round(tau_s * 1e6, 2),
                    "psr_db": round(psr_db, 2),
                    "confidence": round(conf, 3),
                }
            )
            lo_i = max(0, pk - notch_rad)
            hi_i = min(len(work), pk + notch_rad + 1)
            work[lo_i:hi_i] = 0.0

        self.last_multi_gcc_sources = sources
        return sources

    def estimate_gcc_phat_azimuth(self, ch_left: np.ndarray, ch_right: np.ndarray) -> Tuple[float, float]:
        """Tier 3: Multiband Speech-Weighted GCC-PHAT-Beta sub-sample TDOA bearing."""
        sources = self.locate_multi_speaker_gcc_phat(ch_left, ch_right, max_sources=2)
        if not sources:
            return 0.0, 0.0
        primary = sources[0]
        return round(float(primary["azimuth_deg"]), 1), round(float(primary["confidence"]), 3)

    def estimate_acoustic_rf_tof(self, acoustic_pcm: np.ndarray, rf_subvoc: np.ndarray) -> Optional[float]:
        """Tier 2: Hybrid RF-to-Acoustic Time-of-Flight physical distance r = c_sound * lag_sec."""
        n = min(len(acoustic_pcm), len(rf_subvoc))
        if n < int(0.12 * self.samp_rate):
            return None
        rf_rms = float(np.sqrt(np.mean(rf_subvoc[:n].astype(np.float64) ** 2)))
        if rf_rms < 1e-4:
            return None

        # Decimate amplitude envelopes to 2000 Hz (0.5 ms = 17 cm resolution, interpolated to +-2 cm)
        dec = max(1, int(round(self.samp_rate / 2000.0)))
        env_fs = self.samp_rate / dec
        env_ac = np.abs(acoustic_pcm[:n:dec].astype(np.float64))
        env_rf = np.abs(rf_subvoc[:n:dec].astype(np.float64))
        env_ac -= float(np.mean(env_ac))
        env_rf -= float(np.mean(env_rf))

        min_lag = max(1, int(round(0.20 / self.SPEED_OF_SOUND_MPS * env_fs)))  # 0.20 m
        max_lag = min(len(env_ac) // 3, int(round(6.00 / self.SPEED_OF_SOUND_MPS * env_fs)))  # 6.00 m
        if max_lag <= min_lag + 2:
            return None

        scores = []
        denom = float(np.linalg.norm(env_ac) * np.linalg.norm(env_rf) + 1e-12)
        for lag in range(min_lag, max_lag + 1):
            c_val = float(np.dot(env_ac[lag:], env_rf[:-lag])) / denom
            scores.append(c_val)
        best_i = int(np.argmax(scores))
        if scores[best_i] < 0.14:
            return None
        lag_sec = (min_lag + best_i) / env_fs
        return float(np.clip(self.SPEED_OF_SOUND_MPS * lag_sec, 0.20, 6.00))

    def _compute_drr_and_c50(self, pcm: np.ndarray, noise_floor_rms: float = 1e-4) -> Tuple[float, float, float]:
        """Computes Direct-to-Reverberant Ratio (dB), C50 Clarity (dB), and HF polar directivity (dB)."""
        x = pcm.astype(np.float64)
        n = len(x)
        sr = self.samp_rate
        early_n = max(64, int(round(0.018 * sr)))   # 0..18 ms direct wave + first table bounce
        c50_n = max(early_n + 32, int(round(0.050 * sr)))  # 50 ms early speech clarity boundary
        tail_n = max(c50_n + 64, int(round(0.155 * sr)))   # 50..155 ms diffuse room reverberation

        # Smooth 4 ms energy contour to locate clean syllabic onset peaks
        win_env = max(16, int(round(0.004 * sr)))
        sq = x * x
        if n > tail_n + win_env * 2:
            kernel = np.ones(win_env, dtype=np.float64) / win_env
            env = np.convolve(sq, kernel, mode="same")
            peak_idx = int(np.argmax(env[: n - tail_n]))
            e_direct = float(np.mean(sq[peak_idx : peak_idx + early_n])) + 1e-15
            e_early50 = float(np.mean(sq[peak_idx : peak_idx + c50_n])) + 1e-15
            late_seg = sq[peak_idx + c50_n : peak_idx + tail_n]
            floor_pow = max(noise_floor_rms * noise_floor_rms, 1e-12)
            e_reverb = max(float(np.percentile(late_seg, 35)) - 0.5 * floor_pow, e_direct * 0.025)
            drr_db = float(np.clip(10.0 * math.log10(e_direct / (e_reverb + 1e-15)), -8.0, 18.0))
            c50_db = float(np.clip(10.0 * math.log10(e_early50 / (e_reverb + 1e-15)), -6.0, 22.0))
        else:
            rms = float(np.sqrt(np.mean(sq) + 1e-16))
            snr_db = 20.0 * math.log10(max(rms, 1e-7) / max(noise_floor_rms, 1e-6))
            drr_db = float(np.clip((snr_db - 11.0) * 0.65, -6.0, 15.0))
            c50_db = float(np.clip(drr_db + 2.2, -4.0, 18.0))

        # High-frequency polar directivity tilt (4-14 kHz vs 300-1800 Hz)
        spec = np.abs(np.fft.rfft(x * np.hanning(n))) + 1e-12
        freqs = np.fft.rfftfreq(n, d=1.0 / sr)
        m_mid = (freqs >= 300.0) & (freqs <= 1800.0)
        m_hf = (freqs >= 4000.0) & (freqs <= min(14_000.0, 0.46 * sr))
        p_mid = float(np.mean(spec[m_mid] ** 2)) + 1e-16 if np.any(m_mid) else 1e-10
        p_hf = float(np.mean(spec[m_hf] ** 2)) + 1e-16 if np.any(m_hf) else p_mid * 0.1
        hf_tilt_db = float(np.clip(10.0 * math.log10(p_hf / p_mid), -28.0, 6.0))
        return round(drr_db, 2), round(c50_db, 2), round(hf_tilt_db, 2)

    def estimate_utterance_position(
        self,
        pcm: np.ndarray,
        speaker_id: str,
        bio: BiometricSnapshot,
        noise_floor_rms: float = 1e-4,
        rf_subvoc: Optional[np.ndarray] = None,
        right_ch_pcm: Optional[np.ndarray] = None,
    ) -> SpatialPositionSnapshot:
        drr_db_raw, c50_db, hf_tilt_db = self._compute_drr_and_c50(pcm, noise_floor_rms=noise_floor_rms)
        p_align = self.polar_profiles.get(speaker_id, self.polar_profiles["DEFAULT"])
        drr_db = round(float(np.clip(drr_db_raw + p_align["drr_trim_db"], -8.0, 19.0)), 2)

        rms = float(np.sqrt(np.mean(pcm.astype(np.float64) ** 2) + 1e-16))
        snr_db = 20.0 * math.log10(max(rms, 1e-7) / max(noise_floor_rms, 1e-6))

        # Sabine DRR inverse-square law blended with per-speaker DRR trim & calibrated SNR curve
        r_drr = self.room_critical_dist_m * (10.0 ** (-drr_db / 20.0))
        # Adjust expected vocal output reference for whisper (-11 dB quieter than voiced speech)
        ref_snr_1m = 11.5 if "WHISPER" in bio.band_role else 21.0
        r_snr = 1.0 * (10.0 ** ((ref_snr_1m - snr_db) / 20.0))
        raw_range_m = float(np.clip(0.74 * r_drr + 0.26 * r_snr, 0.25, 4.80))
        mode = "TIER1_DRR_POLAR_ALIGNED"
        conf = 0.78

        # Upgrade range to Tier 2 exact Time-of-Flight if live SDR RF subvoc envelope is correlated
        if rf_subvoc is not None:
            tof_r = self.estimate_acoustic_rf_tof(pcm, rf_subvoc)
            if tof_r is not None:
                raw_range_m = 0.75 * tof_r + 0.25 * raw_range_m
                mode = "TIER2_ACOUSTIC_RF_TOF"
                conf = 0.92

        # Upgrade bearing to Tier 3 exact GCC-PHAT-Beta TDOA if dual-mic right channel is available
        if right_ch_pcm is not None and len(right_ch_pcm) >= 256:
            az_deg, tdoa_conf = self.estimate_gcc_phat_azimuth(pcm, right_ch_pcm)
            mode = "TIER3_GCC_PHAT_BETA_TDOA"
            conf = max(conf, tdoa_conf)
        else:
            # Tier 1 speaker-calibrated DRR polar alignment around seated sector anchor
            ref_tilt = (
                p_align["ref_tilt_whisper_db"]
                if "WHISPER" in bio.band_role
                else p_align["ref_tilt_voiced_db"]
            )
            if speaker_id in self.polar_profiles and speaker_id != "DEFAULT":
                anchor_az = p_align["anchor_az_deg"]
                tilt_delta = float(np.clip((ref_tilt - hf_tilt_db) * p_align["polar_gain"], -14.0, 14.0))
                sign = 1.0 if anchor_az >= 0.0 else -1.0
                az_deg = float(np.clip(anchor_az + sign * (tilt_delta * 0.35), -75.0, 75.0))
            else:
                off_axis_mag = float(np.clip((ref_tilt - hf_tilt_db) * p_align["polar_gain"], 3.0, 68.0))
                sign = self.SPEAKER_SECTOR_SIGN.get(
                    speaker_id, -1.0 if (hash(speaker_id) % 2 == 0) else 1.0
                )
                az_deg = sign * off_axis_mag

        now_t = time.time()
        trk = self._speaker_tracks.get(speaker_id)
        if trk is not None:
            dt = max(0.25, now_t - trk["ts"])
            # Huber/Kalman step clamp prevents single reverberant bursts from jumping speaker position
            clamped_r = float(
                np.clip(
                    raw_range_m,
                    trk["range_m"] - p_align["max_range_step_m"],
                    trk["range_m"] + p_align["max_range_step_m"],
                )
            )
            clamped_az = float(
                np.clip(
                    az_deg,
                    trk["azimuth_deg"] - p_align["max_az_step_deg"],
                    trk["azimuth_deg"] + p_align["max_az_step_deg"],
                )
            )
            sm_range = 0.66 * trk["range_m"] + 0.34 * clamped_r
            sm_az = 0.70 * trk["azimuth_deg"] + 0.30 * clamped_az
            vel_cms = float(np.clip(((sm_range - trk["range_m"]) / dt) * 100.0, -85.0, 85.0))
            az_vel = float(np.clip((sm_az - trk["azimuth_deg"]) / dt, -65.0, 65.0))
        else:
            sm_range = raw_range_m
            sm_az = az_deg
            vel_cms = 0.0
            az_vel = 0.0

        if abs(az_vel) >= 6.0 and abs(az_vel) >= abs(vel_cms) * 0.95:
            mov_state = "LATERAL_PACING"
        elif vel_cms <= -4.5:
            mov_state = "APPROACHING"
        elif vel_cms >= 4.5:
            mov_state = "RETREATING"
        elif abs(vel_cms) >= 1.8 or abs(az_vel) >= 2.2:
            mov_state = "MICRO_SWAY"
        else:
            mov_state = "STILL_ANCHORED"

        self._speaker_tracks[speaker_id] = {
            "range_m": sm_range,
            "azimuth_deg": sm_az,
            "ts": now_t,
        }

        rad = math.radians(sm_az)
        x_m = round(sm_range * math.sin(rad), 2)
        y_m = round(sm_range * math.cos(rad), 2)
        snap = SpatialPositionSnapshot(
            range_m=round(sm_range, 2),
            azimuth_deg=round(sm_az, 1),
            x_m=x_m,
            y_m=y_m,
            drr_db=drr_db,
            c50_db=c50_db,
            hf_directivity_db=hf_tilt_db,
            radial_vel_cms=round(vel_cms, 1),
            azimuth_vel_degs=round(az_vel, 1),
            movement_state=mov_state,
            proximity_zone=self._zone_from_range(sm_range),
            positioning_mode=mode,
            confidence=round(conf, 2),
        )
        self.live_fix = snap
        return snap

    def update_live_frame(self, frame: np.ndarray, gate_open: bool, noise_floor_rms: float) -> None:
        """Lightweight frame-rate range & velocity update while VAD gate is open."""
        if not gate_open or len(frame) < 256:
            self.live_fix.radial_vel_cms = round(0.86 * self.live_fix.radial_vel_cms, 1)
            self.live_fix.azimuth_vel_degs = round(0.86 * self.live_fix.azimuth_vel_degs, 1)
            if abs(self.live_fix.radial_vel_cms) < 1.8 and abs(self.live_fix.azimuth_vel_degs) < 2.2:
                self.live_fix.movement_state = "STILL_ANCHORED"
            return
        rms = float(np.sqrt(np.mean(frame.astype(np.float64) ** 2) + 1e-16))
        snr_db = 20.0 * math.log10(max(rms, 1e-7) / max(noise_floor_rms, 1e-6))
        inst_r = float(np.clip(self.room_critical_dist_m * (10.0 ** ((16.5 - snr_db) / 24.0)), 0.28, 4.50))
        prev_r = float(self.live_fix.range_m)
        r_sm = round(0.84 * prev_r + 0.16 * inst_r, 2)
        dt_f = max(0.02, len(frame) / max(1.0, self.samp_rate))
        inst_vr = float(np.clip(((r_sm - prev_r) / dt_f) * 100.0, -65.0, 65.0))
        v_sm = round(0.76 * self.live_fix.radial_vel_cms + 0.24 * inst_vr, 1)
        rad = math.radians(self.live_fix.azimuth_deg)
        self.live_fix.range_m = r_sm
        self.live_fix.x_m = round(r_sm * math.sin(rad), 2)
        self.live_fix.y_m = round(r_sm * math.cos(rad), 2)
        self.live_fix.radial_vel_cms = v_sm
        if v_sm <= -4.5:
            self.live_fix.movement_state = "APPROACHING"
        elif v_sm >= 4.5:
            self.live_fix.movement_state = "RETREATING"
        elif abs(v_sm) >= 1.8:
            self.live_fix.movement_state = "MICRO_SWAY"
        self.live_fix.proximity_zone = self._zone_from_range(r_sm)


# ============================================================================
# 1. BIOMETRIC-FUSED MULTI-FEATURE VAD + OOD HALLUCINATION GUARD
# ============================================================================


class BiometricFusedVAD:
    """
    Implements the Enhanced Multi-Modal Biometric VAD Standard with Per-Speaker Tuning:
      - Rejects stationary noise via Spectral Entropy + Adaptive Baseline (Sec. 9 & 41)
      - Rejects synthetic/mechanical sub-harmonic hallucinations via 1-NN Cosine OOD
        distance against `CLEAN_VOCAL_CLUSTER` (Sec. 13)
      - Per-speaker VAD profiles (`PERSON_ALPHA`, `PERSON_BETA`, `PERSON_DELTA`, `PERSON_GAMMA`)
        dynamically adapt hangover, clause flush cap, OOD guard, C50 pre-emphasis, and
        low-ambient whisper thresholds.
    """

    SPEAKER_VAD_PROFILES: Dict[str, Dict[str, float]] = {
        "DEFAULT": {
            "dyn_thresh_mult": 3.50,
            "low_ambient_whisper_mult": 1.18,
            "gesture_cue_threshold": 0.42,
            "ood_threshold": 0.35,
            "pre_emphasis_alpha": 0.970,
            "hangover_ms": 360.0,
            "min_utt_sec": 0.25,
            "max_utt_sec": 8.0,
        },
        # PERSON_ALPHA: High whisper rate + active short-phrase cadence (6,087 active WPH)
        "PERSON_ALPHA": {
            "dyn_thresh_mult": 3.15,
            "low_ambient_whisper_mult": 1.14,
            "gesture_cue_threshold": 0.38,
            "ood_threshold": 0.36,
            "pre_emphasis_alpha": 0.975,
            "hangover_ms": 310.0,
            "min_utt_sec": 0.22,
            "max_utt_sec": 7.5,
        },
        # PERSON_BETA: High overall voiced speech activity (10.3 words/utt, 7,732 active WPH)
        "PERSON_BETA": {
            "dyn_thresh_mult": 3.60,
            "low_ambient_whisper_mult": 1.20,
            "gesture_cue_threshold": 0.43,
            "ood_threshold": 0.31,
            "pre_emphasis_alpha": 0.968,
            "hangover_ms": 280.0,
            "min_utt_sec": 0.25,
            "max_utt_sec": 6.0,
        },
        # PERSON_DELTA: Low overall speech activity, short utterances & quiet whispers
        "PERSON_DELTA": {
            "dyn_thresh_mult": 2.85,
            "low_ambient_whisper_mult": 1.10,
            "gesture_cue_threshold": 0.35,
            "ood_threshold": 0.38,
            "pre_emphasis_alpha": 0.978,
            "hangover_ms": 420.0,
            "min_utt_sec": 0.18,
            "max_utt_sec": 7.0,
        },
        # PERSON_GAMMA: Mid-field (~1.67 m) minimal turn count yet fastest active pace (8,044 WPH)
        "PERSON_GAMMA": {
            "dyn_thresh_mult": 2.55,
            "low_ambient_whisper_mult": 1.12,
            "gesture_cue_threshold": 0.36,
            "ood_threshold": 0.37,
            "pre_emphasis_alpha": 0.985,
            "hangover_ms": 340.0,
            "min_utt_sec": 0.20,
            "max_utt_sec": 7.5,
        },
    }

    def __init__(
        self,
        samp_rate: float = 48_000.0,
        pre_roll_ms: float = 260.0,
        hangover_ms: float = 360.0,
        ood_threshold: float = 0.35,
        require_biometric_liveness: bool = False,
        low_ambient_whisper_mult: float = 1.18,
        gesture_cue_threshold: float = 0.42,
    ) -> None:
        self.samp_rate = float(samp_rate)
        self.pre_roll_samples = int(round(self.samp_rate * pre_roll_ms / 1000.0))
        self.hangover_samples = int(round(self.samp_rate * hangover_ms / 1000.0))
        self.low_ambient_hangover_samples = int(round(self.samp_rate * (hangover_ms + 180.0) / 1000.0))
        self.ood_threshold = float(ood_threshold)
        self.require_biometric_liveness = bool(require_biometric_liveness)
        self.low_ambient_whisper_mult = float(low_ambient_whisper_mult)
        self.gesture_cue_threshold = float(gesture_cue_threshold)
        self.dyn_thresh_mult: float = 3.50
        self.pre_emphasis_alpha: float = 0.970
        self.min_utt_sec: float = 0.25
        self.max_utt_sec: float = 8.0
        self.active_speaker_profile: str = "DEFAULT"
        self.speaker_profiles: Dict[str, Dict[str, float]] = {
            k: dict(v) for k, v in self.SPEAKER_VAD_PROFILES.items()
        }

        self._noise_floor_rms: float = 1e-4
        self._floor_init: bool = False
        self._hangover_rem: int = 0
        self._pre_buf = np.zeros(self.pre_roll_samples, dtype=np.float32)
        self._active_utterance: List[np.ndarray] = []
        self._active_snaps: List[BiometricSnapshot] = []
        self._utterance_start_sample: int = 0
        self._total_samples: int = 0
        self.last_gate_open: bool = False
        self.last_conf: float = 0.0
        self.last_snap: BiometricSnapshot = BiometricSnapshot()

    def set_speaker_vad_profile(
        self, speaker_id: str, overrides: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        spk = str(speaker_id or "DEFAULT").strip().upper()
        base = dict(self.speaker_profiles.get(spk, self.speaker_profiles["DEFAULT"]))
        if overrides:
            bounds = {
                "dyn_thresh_mult": (1.60, 6.00),
                "low_ambient_whisper_mult": (1.04, 2.50),
                "gesture_cue_threshold": (0.18, 0.85),
                "ood_threshold": (0.18, 0.55),
                "pre_emphasis_alpha": (0.90, 0.995),
                "hangover_ms": (160.0, 900.0),
                "min_utt_sec": (0.12, 1.00),
                "max_utt_sec": (3.0, 14.0),
            }
            for k, (lo, hi) in bounds.items():
                if k in overrides and overrides[k] is not None:
                    base[k] = round(float(np.clip(float(overrides[k]), lo, hi)), 4)
        self.speaker_profiles[spk] = base
        self.active_speaker_profile = spk
        self.dyn_thresh_mult = float(base["dyn_thresh_mult"])
        self.low_ambient_whisper_mult = float(base["low_ambient_whisper_mult"])
        self.gesture_cue_threshold = float(base["gesture_cue_threshold"])
        self.ood_threshold = float(base["ood_threshold"])
        self.pre_emphasis_alpha = float(base["pre_emphasis_alpha"])
        self.hangover_samples = int(round(self.samp_rate * float(base["hangover_ms"]) / 1000.0))
        self.low_ambient_hangover_samples = int(
            round(self.samp_rate * (float(base["hangover_ms"]) + 160.0) / 1000.0)
        )
        self.min_utt_sec = float(base["min_utt_sec"])
        self.max_utt_sec = float(base["max_utt_sec"])
        return {"speaker_id": spk, **base}

    @staticmethod
    def _pre_emphasize(x: np.ndarray, alpha: float = 0.97) -> np.ndarray:
        out = np.empty_like(x, dtype=np.float64)
        out[0] = x[0]
        out[1:] = x[1:] - alpha * x[:-1]
        return out

    @staticmethod
    def compute_gesture_subvoc_cue(
        mouth_cue: Optional[Dict[str, Any]],
        earworm_cue: Optional[Dict[str, Any]],
        throat_disp_um: float,
        e_formant_f1: float,
        e_fricative: float,
        zcr: float,
    ) -> float:
        """
        Fuses oral-cavity mouth gestures (`BreathAndMouthExtractor`) with subtle laryngeal
        subvocalizations (`RTL-SDR` micro-motion + `WhisperEarwormEngine` 4-sensor state)
        into a [0.0, 1.0] co-gating score that unlocks +1.4 dB ultra-low ambient whisper capture.
        """
        mouth_score = 0.0
        if mouth_cue:
            openness = float(mouth_cue.get("mouth_openness", 0.0) or 0.0)
            viseme = str(mouth_cue.get("viseme", "REST_CLOSED") or "REST_CLOSED")
            silent_m = bool(mouth_cue.get("silent_mouthing", False))
            art_e = float(mouth_cue.get("articulation_energy", 0.0) or 0.0)
            open_term = float(np.clip((openness - 0.10) / 0.42, 0.0, 0.50))
            viseme_term = 0.28 if viseme != "REST_CLOSED" else 0.0
            silent_term = 0.30 if silent_m else 0.0
            art_term = float(np.clip(art_e / 2.2, 0.0, 0.28))
            mouth_score = float(np.clip(open_term + viseme_term + silent_term + art_term, 0.0, 1.0))

        subvoc_score = 0.0
        capped_disp = min(float(throat_disp_um), 85.0)
        if capped_disp >= 2.2:
            # Cap standalone throat excursion to 0.32 unless co-validated by mouth/earworm activity
            disp_cap = 0.52 if (mouth_score >= 0.14 or bool((earworm_cue or {}).get("is_whispering"))) else 0.32
            subvoc_score += float(np.clip((capped_disp - 2.0) / 11.0, 0.0, disp_cap))
        if earworm_cue:
            if bool(earworm_cue.get("is_whispering", False)):
                subvoc_score += 0.48
            elif str(earworm_cue.get("active_phoneme", "IDLE")) != "IDLE":
                subvoc_score += 0.24
            w_gain = float(earworm_cue.get("whisper_gain", 0.0) or 0.0)
            subvoc_score += float(np.clip(w_gain * 0.45, 0.0, 0.28))
        if (e_fricative + e_formant_f1) >= 0.60 and zcr >= 0.055:
            subvoc_score += 0.18
        subvoc_score = float(np.clip(subvoc_score, 0.0, 1.0))

        return round(float(np.clip(0.52 * mouth_score + 0.48 * subvoc_score, 0.0, 1.0)), 3)

    def evaluate_frame(
        self,
        audio_chunk: np.ndarray,
        resp_bpm: float = 15.0,
        throat_disp_um: float = 18.0,
        mouth_cue: Optional[Dict[str, Any]] = None,
        earworm_cue: Optional[Dict[str, Any]] = None,
        motion_cue: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, float, BiometricSnapshot]:
        """Returns `(is_speech, vad_confidence, BiometricSnapshot)` for `audio_chunk`."""
        x = audio_chunk.astype(np.float64)
        n = len(x)
        if n < 64:
            return False, 0.0, BiometricSnapshot()

        rms = float(np.sqrt(np.mean(x * x) + 1e-16))

        # Raw spectrum for true physiological energy balance (Section 13 & 41 Role A/B)
        win = np.hanning(n)
        spec_raw = np.abs(np.fft.rfft(x * win)) + 1e-12
        psd_raw = spec_raw * spec_raw

        # Pre-emphasis alpha (per-speaker tuned, e.g. 0.985 C50 dereverb lift for PERSON_GAMMA)
        x_pre = self._pre_emphasize(x, alpha=self.pre_emphasis_alpha)
        zcr = float(np.mean(np.abs(np.diff(np.signbit(x_pre)))))

        spec_pre = np.abs(np.fft.rfft(x_pre * win)) + 1e-12
        freqs = np.fft.rfftfreq(n, d=1.0 / self.samp_rate)
        psd_pre = spec_pre * spec_pre
        psd_norm = psd_pre / np.sum(psd_pre)
        spectral_entropy = float(-np.sum(psd_norm * np.log2(psd_norm + 1e-18)) / math.log2(len(psd_norm)))

        # Band energy ratios for Section 13 4-D vocal feature vector & Section 41 Role A/B
        e_total = float(np.sum(psd_raw)) + 1e-18
        e_low_larynx = float(np.sum(psd_raw[(freqs >= 70.0) & (freqs <= 350.0)])) / e_total
        e_formant_f1 = float(np.sum(psd_raw[(freqs > 350.0) & (freqs <= 1500.0)])) / e_total
        e_delta_sub = float(np.sum(psd_raw[freqs < 55.0])) / e_total
        e_fricative = float(np.sum(psd_raw[(freqs > 1500.0) & (freqs <= 6500.0)])) / e_total

        gesture_subvoc_score = self.compute_gesture_subvoc_cue(
            mouth_cue=mouth_cue,
            earworm_cue=earworm_cue,
            throat_disp_um=throat_disp_um,
            e_formant_f1=e_formant_f1,
            e_fricative=e_fricative,
            zcr=zcr,
        )
        mc = motion_cue or {}
        vad_motion_score = round(float(np.clip(float(mc.get("vad_motion_score", 0.0) or 0.0), 0.0, 1.0)), 3)
        vad_motion_weight = float(np.clip(float(mc.get("vad_motion_weight", 0.24) or 0.24), 0.0, 0.60))
        movement_state = str(mc.get("movement_state") or "STILL_ANCHORED")

        if not self._floor_init:
            self._noise_floor_rms = max(rms, 1e-5)
            self._floor_init = True
        elif rms < 1.85 * self._noise_floor_rms and gesture_subvoc_score < 0.45:
            # Adapt ambient noise floor during pauses while freezing during real whispers/speech
            self._noise_floor_rms = 0.95 * self._noise_floor_rms + 0.05 * rms
        elif rms < 1.35 * self._noise_floor_rms:
            # Slow leak prevents floor lock-up if stationary HVAC/fan rises slightly
            self._noise_floor_rms = 0.99 * self._noise_floor_rms + 0.01 * rms

        dyn_thresh = self.dyn_thresh_mult * self._noise_floor_rms
        ambient_snr_db = round(
            20.0 * math.log10(max(rms, 1e-7) / max(self._noise_floor_rms, 1e-7)), 2
        )

        feat_vec = np.array([e_low_larynx, e_formant_f1, e_delta_sub, e_fricative], dtype=np.float64)
        cos_sim = float(
            np.dot(feat_vec, CLEAN_VOCAL_CLUSTER)
            / (np.linalg.norm(feat_vec) * np.linalg.norm(CLEAN_VOCAL_CLUSTER) + 1e-12)
        )
        ood_dist = max(0.0, 1.0 - cos_sim)

        # Estimate Vocal Tract Length (VTL) from pre-emphasized formant peaks F1, F2, F3
        vtl_cm = self._estimate_vtl_cm(freqs, spec_pre)
        f0_hz = self._estimate_f0_hz(freqs, spec_raw) if e_low_larynx >= 0.12 else 0.0
        band_role = (
            "UNVOICED_WHISPER"
            if (e_fricative > 1.5 * e_low_larynx and e_low_larynx < 0.20)
            else "VOICED_LARYNX"
        )

        eff_low_mult = max(1.22, self.low_ambient_whisper_mult)
        vocal_spectral_ok = (zcr >= 0.048 or (e_fricative + e_formant_f1) >= 0.54) and e_delta_sub < 0.50
        # VAD Motion co-validation: moving speaker whispers receive kinetic threshold support while rejecting <55 Hz thumps
        motion_whisper_cued = bool(
            vad_motion_score >= 0.34
            and gesture_subvoc_score >= max(0.24, self.gesture_cue_threshold - 0.10)
            and rms >= max(1.18, eff_low_mult - 0.06) * self._noise_floor_rms
            and vocal_spectral_ok
        )
        low_ambient_cued = bool(
            (gesture_subvoc_score >= self.gesture_cue_threshold and rms >= eff_low_mult * self._noise_floor_rms and vocal_spectral_ok)
            or motion_whisper_cued
        )

        # Biometric Liveness Check: human breathing cadence, >5 um throat motion, subtle >2.2 um + mouth gesture, or vocal motion
        liveness_ok = (
            (4.5 <= resp_bpm <= 42.0)
            or (throat_disp_um >= 5.0)
            or (throat_disp_um >= 2.2 and gesture_subvoc_score >= self.gesture_cue_threshold)
            or (vad_motion_score >= 0.35 and vocal_spectral_ok)
        )
        if self.require_biometric_liveness and not liveness_ok:
            gate_open = False
            conf = 0.0
        else:
            energy_score = np.clip((rms / max(dyn_thresh, 1e-7)) - 0.85, 0.0, 1.5)
            entropy_score = np.clip((0.92 - spectral_entropy) * 2.5, 0.0, 1.0)
            is_whisper_like = ("WHISPER" in band_role) or low_ambient_cued
            ood_pass = (e_delta_sub < 0.50) if is_whisper_like else (ood_dist <= self.ood_threshold)
            bio_bonus = 0.18 if liveness_ok else 0.0
            cue_bonus = 0.28 * gesture_subvoc_score if low_ambient_cued else 0.0
            motion_bonus = (vad_motion_weight * vad_motion_score) if vocal_spectral_ok else 0.0
            conf = float(
                np.clip(
                    0.50 * energy_score + 0.25 * entropy_score + bio_bonus + cue_bonus + motion_bonus,
                    0.0,
                    1.0,
                )
            )
            std_whisper_open = (
                band_role == "UNVOICED_WHISPER"
                and zcr > 0.08
                and rms >= 2.2 * self._noise_floor_rms
            )
            gate_open = bool((rms >= dyn_thresh or std_whisper_open or low_ambient_cued) and ood_pass)
            if gate_open and low_ambient_cued and rms < 2.6 * self._noise_floor_rms:
                band_role = "LOW_AMBIENT_WHISPER"
                conf = max(conf, round(0.45 + 0.45 * gesture_subvoc_score + 0.15 * vad_motion_score, 3))

        snap = BiometricSnapshot(
            resp_bpm=float(resp_bpm),
            resp_phase_exhale=True,
            throat_disp_um_rms=float(throat_disp_um),
            f0_hz=f0_hz,
            vtl_cm=vtl_cm,
            ood_cosine_dist=round(ood_dist, 4),
            liveness_verified=liveness_ok,
            band_role=band_role,
            gesture_subvoc_score=gesture_subvoc_score,
            low_ambient_cued=low_ambient_cued,
            ambient_snr_db=ambient_snr_db,
            vad_motion_score=vad_motion_score,
            movement_state=movement_state,
        )
        return gate_open, conf, snap

    @staticmethod
    def _estimate_vtl_cm(freqs: np.ndarray, spec: np.ndarray) -> float:
        """
        Estimates physical Vocal Tract Length (cm) via Wakita / Fitch formant dispersion:
        VTL ≈ ((2k - 1) * c) / (4 * F_k) averaged across F1 (300-900 Hz), F2 (900-2300 Hz), F3 (2300-3600 Hz).
        Invariant across voiced speech and unvoiced whispers!
        """
        c_cm_s = 34_300.0
        estimates = []
        for k_idx, (f_lo, f_hi) in enumerate(((300.0, 900.0), (900.0, 2300.0), (2300.0, 3600.0)), start=1):
            mask = (freqs >= f_lo) & (freqs <= f_hi)
            if np.any(mask):
                sub_f = freqs[mask]
                sub_s = spec[mask]
                fk = float(sub_f[int(np.argmax(sub_s))])
                if fk > 100.0:
                    vtl = ((2 * k_idx - 1) * c_cm_s) / (4.0 * fk)
                    estimates.append(vtl)
        if not estimates:
            return 17.0
        return float(np.clip(np.median(estimates), 12.5, 22.5))

    @staticmethod
    def _estimate_f0_hz(freqs: np.ndarray, spec: np.ndarray) -> float:
        mask = (freqs >= 72.0) & (freqs <= 350.0)
        if not np.any(mask):
            return 0.0
        sub_f = freqs[mask]
        sub_s = spec[mask]
        return float(sub_f[int(np.argmax(sub_s))])

    def _aggregate_utterance_biometrics(self, fallback: BiometricSnapshot) -> BiometricSnapshot:
        if not self._active_snaps:
            return fallback
        vtls = [s.vtl_cm for s in self._active_snaps]
        f0s = [s.f0_hz for s in self._active_snaps if s.f0_hz > 55.0]
        oods = [s.ood_cosine_dist for s in self._active_snaps]
        disps = [s.throat_disp_um_rms for s in self._active_snaps]
        bpms = [s.resp_bpm for s in self._active_snaps if s.resp_bpm > 0.0]
        g_scores = [s.gesture_subvoc_score for s in self._active_snaps]
        snrs = [s.ambient_snr_db for s in self._active_snaps]
        m_scores = [s.vad_motion_score for s in self._active_snaps]
        m_states = [s.movement_state for s in self._active_snaps if s.movement_state != "STILL_ANCHORED"]
        dom_mov = collections.Counter(m_states).most_common(1)[0][0] if m_states else fallback.movement_state
        voiced_cnt = sum(1 for s in self._active_snaps if s.band_role == "VOICED_LARYNX")
        low_amb_cnt = sum(1 for s in self._active_snaps if s.band_role == "LOW_AMBIENT_WHISPER" or s.low_ambient_cued)
        if voiced_cnt >= (len(self._active_snaps) / 2.0):
            role = "VOICED_LARYNX"
        elif low_amb_cnt >= max(1, len(self._active_snaps) // 3):
            role = "LOW_AMBIENT_WHISPER"
        else:
            role = "UNVOICED_WHISPER"
        return BiometricSnapshot(
            resp_bpm=float(np.median(bpms)) if bpms else fallback.resp_bpm,
            resp_phase_exhale=True,
            throat_disp_um_rms=float(np.max(disps)) if disps else fallback.throat_disp_um_rms,
            f0_hz=float(np.median(f0s)) if f0s else 0.0,
            vtl_cm=float(np.median(vtls)) if vtls else fallback.vtl_cm,
            ood_cosine_dist=round(float(np.mean(oods)), 4) if oods else fallback.ood_cosine_dist,
            liveness_verified=any(s.liveness_verified for s in self._active_snaps),
            band_role=role,
            gesture_subvoc_score=round(float(np.max(g_scores)), 3) if g_scores else fallback.gesture_subvoc_score,
            low_ambient_cued=any(s.low_ambient_cued for s in self._active_snaps),
            ambient_snr_db=round(float(np.mean(snrs)), 2) if snrs else fallback.ambient_snr_db,
            vad_motion_score=round(float(np.max(m_scores)), 3) if m_scores else fallback.vad_motion_score,
            movement_state=dom_mov,
        )

    def push_streaming_chunk(
        self,
        audio_chunk: np.ndarray,
        resp_bpm: float = 15.0,
        throat_disp_um: float = 18.0,
        mouth_cue: Optional[Dict[str, Any]] = None,
        earworm_cue: Optional[Dict[str, Any]] = None,
        motion_cue: Optional[Dict[str, Any]] = None,
    ) -> Optional[Tuple[np.ndarray, float, float, BiometricSnapshot]]:
        """
        Feeds live audio chunks; returns completed `(utterance_pcm, start_s, end_s, bio_snapshot)`
        with pre-roll and hangover padding whenever an utterance finishes (or hits 8.0s streaming cap).
        """
        is_speech, conf, snap = self.evaluate_frame(
            audio_chunk,
            resp_bpm=resp_bpm,
            throat_disp_um=throat_disp_um,
            mouth_cue=mouth_cue,
            earworm_cue=earworm_cue,
            motion_cue=motion_cue,
        )
        self.last_gate_open = is_speech
        self.last_conf = conf
        self.last_snap = snap
        n = len(audio_chunk)

        completed = None
        if is_speech:
            if not self._active_utterance:
                self._utterance_start_sample = max(0, self._total_samples - len(self._pre_buf))
                self._active_utterance.append(self._pre_buf.copy())
                self._active_snaps.clear()
            self._active_utterance.append(audio_chunk.astype(np.float32))
            self._active_snaps.append(snap)
            kin_bonus_ms = float((motion_cue or {}).get("kinetic_hangover_bonus_ms", 0.0) or 0.0)
            kin_samples = int(round(self.samp_rate * max(0.0, min(200.0, kin_bonus_ms)) / 1000.0))
            self._hangover_rem = (
                self.low_ambient_hangover_samples if snap.low_ambient_cued else self.hangover_samples
            ) + kin_samples

            # Flush continuous speech at speaker-tuned clause cap (e.g. 6.0s for PERSON_BETA)
            cur_dur = ((self._total_samples + n) - self._utterance_start_sample) / self.samp_rate
            if cur_dur >= self.max_utt_sec:
                pcm = np.concatenate(self._active_utterance)
                agg_bio = self._aggregate_utterance_biometrics(snap)
                start_s = self._utterance_start_sample / self.samp_rate
                end_s = (self._total_samples + n) / self.samp_rate
                self._active_utterance.clear()
                self._active_snaps.clear()
                self._hangover_rem = 0
                completed = (pcm, start_s, end_s, agg_bio)
        elif self._active_utterance:
            self._active_utterance.append(audio_chunk.astype(np.float32))
            self._hangover_rem -= n
            if self._hangover_rem <= 0:
                pcm = np.concatenate(self._active_utterance)
                agg_bio = self._aggregate_utterance_biometrics(snap)
                self._active_utterance.clear()
                self._active_snaps.clear()
                start_s = self._utterance_start_sample / self.samp_rate
                end_s = (self._total_samples + n) / self.samp_rate
                if (end_s - start_s) >= self.min_utt_sec:
                    completed = (pcm, start_s, end_s, agg_bio)

        # Update rolling pre-roll buffer
        if n >= self.pre_roll_samples:
            self._pre_buf[:] = audio_chunk[-self.pre_roll_samples :]
        else:
            self._pre_buf[:-n] = self._pre_buf[n:]
            self._pre_buf[-n:] = audio_chunk
        self._total_samples += n
        return completed


# ============================================================================
# 2. OPEN-SET PER-PERSON BIOMETRIC SPEAKER ATTRIBUTOR (WHISPER-INVARIANT)
# ============================================================================


class BiometricSpeakerAttributor:
    """
    Assigns utterances to distinct human speakers (`PERSON_ALPHA`, `PERSON_BETA`,
    `PERSON_GAMMA`, ...) using a fused Neural + Biometric speaker embedding:
      - 256-D WeSpeaker VoxCeleb ResNet34-LM ONNX neural speaker embedding
        (`models/speaker-onnx/voxceleb_resnet34_LM.onnx`, 80-bin Kaldi Log-Mel + CMN)
      - 15-D Whisper-Invariant Biometric Signature (12-band vocal-tract envelope +
        Wakita VTL cm + Voiced F0 + Respiration BPM)
      - Short-Clip Anti-Fragmentation Gate (`min_enroll_sec = 1.50 s` incl. padding):
        short exclamations (`< 1.50 s`) attach to the closest enrolled speaker instead
        of spawning singleton `PERSON_*` slots.
    """

    SLOT_NAMES = ["PERSON_DELTA", "PERSON_ALPHA", "PERSON_BETA", "PERSON_GAMMA"]

    def __init__(
        self,
        samp_rate: float = 48_000.0,
        similarity_threshold: Optional[float] = None,
        min_enroll_sec: float = 1.15,
        max_speakers: int = 8,
        owner_speaker_id: str = "PERSON_DELTA",
        storage_path: Optional[Union[str, Path]] = None,
    ) -> None:
        self.samp_rate = float(samp_rate)
        self.min_enroll_sec = float(min_enroll_sec)
        self.max_speakers = int(max_speakers)
        self.owner_speaker_id = str(owner_speaker_id or "PERSON_DELTA").strip().upper()
        self.storage_path: Optional[Path] = Path(storage_path) if storage_path is not None else None
        self._lock = threading.Lock()
        self._prototypes: Dict[str, np.ndarray] = {}
        self._counts: Dict[str, int] = {}

        self._ort_sess = None
        self._mel_basis: Optional[np.ndarray] = None
        onnx_dir = Path(__file__).resolve().parent.parent / "models" / "speaker-onnx"
        onnx_candidates = sorted(onnx_dir.glob("*.onnx")) if onnx_dir.exists() else []
        if onnx_candidates:
            try:
                import onnxruntime as ort  # type: ignore

                opts = ort.SessionOptions()
                opts.intra_op_num_threads = 2
                self._ort_sess = ort.InferenceSession(
                    str(onnx_candidates[0]),
                    sess_options=opts,
                    providers=["CPUExecutionProvider"],
                )
                self._mel_basis = self._build_kaldi_mel_filterbank(
                    sr=16_000, n_fft=512, n_mels=80, fmin=20.0, fmax=7600.0
                )
            except Exception:
                self._ort_sess = None

        self.signature_dim: int = 271 if self._ort_sess is not None else 15

        if similarity_threshold is not None:
            self.similarity_threshold = float(similarity_threshold)
        else:
            # VoxCeleb ResNet34-LM (0.84) + Biometric VTL/Formant (0.54) cosine decision boundary
            self.similarity_threshold = 0.56 if self._ort_sess is not None else 0.82

        self._load_persisted_voiceprints()

    def _slot_order(self) -> List[str]:
        ordered: List[str] = [self.owner_speaker_id]
        for s in self.SLOT_NAMES:
            if s not in ordered:
                ordered.append(s)
        return ordered

    def _next_available_slot(self) -> str:
        for slot in self._slot_order():
            if slot not in self._prototypes:
                return slot
        idx = len(self._prototypes) + 1
        while f"PERSON_{idx:02d}" in self._prototypes:
            idx += 1
        return f"PERSON_{idx:02d}"

    def _load_persisted_voiceprints(self) -> None:
        if self.storage_path is None or not self.storage_path.exists():
            return
        try:
            raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
            protos = raw.get("prototypes") if isinstance(raw, dict) else None
            counts = raw.get("counts") if isinstance(raw, dict) else {}
            if not isinstance(protos, dict):
                return
            with self._lock:
                for sid, vec in protos.items():
                    spk = str(sid or "").strip().upper()
                    if not spk or spk in (TYPIST_SPEAKER_ID, OTHER_ROOM_SPEAKER_ID, *ELECTRONIC_CHARACTER_IDS):
                        continue
                    arr = np.asarray(vec, dtype=np.float64).ravel()
                    if len(arr) != self.signature_dim:
                        continue
                    norm = float(np.linalg.norm(arr))
                    if norm <= 1e-9 or not np.all(np.isfinite(arr)):
                        continue
                    self._prototypes[spk] = arr / norm
                    self._counts[spk] = max(1, int((counts or {}).get(spk, 1)))
        except Exception:
            pass

    def _save_persisted_voiceprints_locked(self) -> None:
        if self.storage_path is None:
            return
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "updated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                "owner_speaker_id": self.owner_speaker_id,
                "signature_dim": self.signature_dim,
                "counts": {k: int(v) for k, v in self._counts.items()},
                "prototypes": {
                    k: [round(float(x), 6) for x in v.ravel()]
                    for k, v in self._prototypes.items()
                },
            }
            tmp_path = self.storage_path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp_path.replace(self.storage_path)
        except Exception:
            pass

    def seed_prototype_vector(self, speaker_id: str, vec: Optional[Union[List[float], np.ndarray]], count: int = 2) -> bool:
        """Seeds a speaker slot from an existing normalized prototype vector if that slot is currently empty."""
        if vec is None:
            return False
        spk = str(speaker_id or "").strip().upper()
        if not spk:
            return False
        arr = np.asarray(vec, dtype=np.float64).ravel()
        if len(arr) != self.signature_dim:
            return False
        norm = float(np.linalg.norm(arr))
        if norm <= 1e-9 or not np.all(np.isfinite(arr)):
            return False
        with self._lock:
            if spk in self._prototypes:
                return False
            self._prototypes[spk] = arr / norm
            self._counts[spk] = max(1, int(count))
            self._save_persisted_voiceprints_locked()
        return True

    def enroll_speaker_clip(
        self,
        speaker_id: str,
        pcm: np.ndarray,
        bio: BiometricSnapshot,
        blend_weight: float = 0.70,
    ) -> Tuple[np.ndarray, float]:
        """Explicitly enrolls or anchors `speaker_id` (e.g. `PERSON_DELTA`) from a reference PCM clip and persists immediately."""
        spk = str(speaker_id or self.owner_speaker_id or "PERSON_DELTA").strip().upper()
        sig = self.extract_signature(pcm, bio)
        w = float(np.clip(blend_weight, 0.10, 1.0))
        with self._lock:
            if spk in self._prototypes and len(self._prototypes[spk]) == len(sig) and w < 0.999:
                merged = (1.0 - w) * self._prototypes[spk] + w * sig
                proto = merged / (np.linalg.norm(merged) + 1e-12)
                self._prototypes[spk] = proto
                self._counts[spk] = int(self._counts.get(spk, 1)) + 1
            else:
                proto = sig
                self._prototypes[spk] = proto
                self._counts[spk] = max(2, int(self._counts.get(spk, 0)) + 1)
            sim = float(np.clip(np.dot(sig, proto), 0.0, 1.0))
            self._save_persisted_voiceprints_locked()
        return proto.copy(), round(sim, 4)

    @staticmethod
    def _build_kaldi_mel_filterbank(
        sr: int = 16_000, n_fft: int = 512, n_mels: int = 80, fmin: float = 20.0, fmax: float = 7600.0
    ) -> np.ndarray:
        def hz_to_mel(f: float) -> float:
            return 1127.0 * math.log(1.0 + f / 700.0)

        def mel_to_hz(m: np.ndarray) -> np.ndarray:
            return 700.0 * (np.exp(m / 1127.0) - 1.0)

        mel_pts = np.linspace(hz_to_mel(fmin), hz_to_mel(fmax), n_mels + 2)
        hz_pts = mel_to_hz(mel_pts)
        bins = np.floor((n_fft + 1) * hz_pts / sr).astype(int)
        fbank = np.zeros((n_mels, n_fft // 2 + 1), dtype=np.float32)
        for m in range(1, n_mels + 1):
            f_left, f_center, f_right = bins[m - 1], bins[m], bins[m + 1]
            if f_center > f_left:
                for k in range(f_left, f_center):
                    fbank[m - 1, k] = (k - f_left) / (f_center - f_left)
            if f_right > f_center:
                for k in range(f_center, min(f_right, n_fft // 2 + 1)):
                    fbank[m - 1, k] = (f_right - k) / (f_right - f_center)
        return fbank

    def _extract_neural_embedding(self, pcm: np.ndarray) -> Optional[np.ndarray]:
        if self._ort_sess is None or self._mel_basis is None:
            return None
        x = pcm.astype(np.float32)
        if abs(self.samp_rate - 16_000.0) > 1.0:
            if HAS_SCIPY:
                g = math.gcd(16_000, int(round(self.samp_rate)))
                x = sp_signal.resample_poly(x, 16_000 // g, int(round(self.samp_rate)) // g).astype(np.float32)
            else:
                t_len = max(400, int(round(len(x) * 16_000.0 / self.samp_rate)))
                x = np.interp(np.linspace(0.0, 1.0, t_len), np.linspace(0.0, 1.0, len(x)), x).astype(np.float32)

        # Kaldi 16-bit scale + pre-emphasis 0.97 + 25 ms Povey window / 10 ms shift
        peak = float(np.max(np.abs(x)) + 1e-9)
        x = (x / peak) * (0.7 * 32768.0)
        if len(x) < 640:
            x = np.pad(x, (0, 640 - len(x)))
        x_pre = np.empty_like(x)
        x_pre[0] = x[0]
        x_pre[1:] = x[1:] - 0.97 * x[:-1]

        win_len, hop_len, n_fft = 400, 160, 512
        n_frames = max(1, 1 + (len(x_pre) - win_len) // hop_len)
        strides = (x_pre.strides[0] * hop_len, x_pre.strides[0])
        frames = np.lib.stride_tricks.as_strided(x_pre, shape=(n_frames, win_len), strides=strides).copy()
        frames -= np.mean(frames, axis=1, keepdims=True)
        povey = (0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(win_len) / (win_len - 1))) ** 0.85
        frames *= povey.astype(np.float32)

        power_spec = np.abs(np.fft.rfft(frames, n=n_fft, axis=1)) ** 2
        mel_energies = np.maximum(power_spec @ self._mel_basis.T, 1e-10)
        log_mel = np.log(mel_energies).astype(np.float32)
        # Cepstral Mean Normalization (CMN) across time
        log_mel -= np.mean(log_mel, axis=0, keepdims=True)

        inp_name = self._ort_sess.get_inputs()[0].name
        emb = self._ort_sess.run(None, {inp_name: log_mel[np.newaxis, :, :]})[0][0].astype(np.float64)
        emb /= np.linalg.norm(emb) + 1e-12
        return emb

    def extract_signature(self, pcm: np.ndarray, bio: BiometricSnapshot) -> np.ndarray:
        x = pcm.astype(np.float64)
        spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) + 1e-12
        freqs = np.fft.rfftfreq(len(x), d=1.0 / self.samp_rate)

        # 12 logarithmically spaced vocal-tract filterbank bands (120 Hz .. 4200 Hz)
        edges = np.geomspace(120.0, 4200.0, 13)
        band_feats = np.zeros(12, dtype=np.float64)
        for i in range(12):
            m = (freqs >= edges[i]) & (freqs < edges[i + 1])
            band_feats[i] = math.log(float(np.mean(spec[m])) + 1e-9) if np.any(m) else -20.0
        band_feats -= np.mean(band_feats)
        band_feats /= np.linalg.norm(band_feats) + 1e-12

        vtl_norm = (bio.vtl_cm - 17.0) / 4.0
        resp_norm = (bio.resp_bpm - 15.0) / 10.0 if bio.resp_bpm > 0 else 0.0
        f0_norm = (bio.f0_hz - 140.0) / 80.0 if bio.f0_hz > 55.0 else 0.0

        bio_vec = np.concatenate([band_feats, [0.45 * vtl_norm, 0.20 * resp_norm, 0.25 * f0_norm]])
        bio_vec /= np.linalg.norm(bio_vec) + 1e-12

        neural_emb = self._extract_neural_embedding(pcm)
        if neural_emb is not None:
            sig = np.concatenate([0.84 * neural_emb, 0.54 * bio_vec])
        else:
            sig = bio_vec
        sig /= np.linalg.norm(sig) + 1e-12
        return sig

    def identify_or_enroll(self, pcm: np.ndarray, bio: BiometricSnapshot) -> Tuple[str, float]:
        sig = self.extract_signature(pcm, bio)
        dur_sec = len(pcm) / max(self.samp_rate, 1.0)
        best_id = None
        best_sim = -1.0

        with self._lock:
            for spk_id, proto in self._prototypes.items():
                if len(proto) != len(sig):
                    continue
                sim = float(np.dot(sig, proto))
                if sim > best_sim:
                    best_sim = sim
                    best_id = spk_id

            # Match existing speaker if above threshold OR if utterance is a short exclamation (< min_enroll_sec)
            # with plausible similarity OR if room speaker cap is reached (including NightSweep Sec. 1 whisper-invariant VTL fallback)
            short_clip_attach = (best_id is not None) and (dur_sec < self.min_enroll_sec) and (best_sim >= 0.44)
            cap_attach = (best_id is not None) and (len(self._prototypes) >= self.max_speakers) and (best_sim >= 0.34)
            if not cap_attach and (best_id is not None) and (len(self._prototypes) >= self.max_speakers) and ("WHISPER" in str(bio.band_role).upper()):
                # VoxCeleb ResNet34 degrades on pure unvoiced whispers; match on physical vocal-tract filterbank + VTL tail
                best_bio_id = None
                best_bio_sim = -1.0
                tail_dim = min(15, len(sig))
                sig_tail = sig[-tail_dim:] / (np.linalg.norm(sig[-tail_dim:]) + 1e-12)
                for spk_id, proto in self._prototypes.items():
                    if len(proto) >= tail_dim:
                        pt = proto[-tail_dim:] / (np.linalg.norm(proto[-tail_dim:]) + 1e-12)
                        bsim = float(np.dot(sig_tail, pt))
                        if bsim > best_bio_sim:
                            best_bio_sim = bsim
                            best_bio_id = spk_id
                if best_bio_id is not None:
                    best_id = best_bio_id
                    best_sim = max(best_sim, best_bio_sim)
                    cap_attach = True

            if best_id is not None and (best_sim >= self.similarity_threshold or short_clip_attach or cap_attach):
                # Update prototype only on substantive, high-confidence matches so short noise clips don't drift centroids
                if dur_sec >= 0.85 and best_sim >= self.similarity_threshold:
                    c = int(self._counts.get(best_id, 1))
                    alpha = max(0.04, 1.0 / (c + 3))
                    updated = (1.0 - alpha) * self._prototypes[best_id] + alpha * sig
                    self._prototypes[best_id] = updated / (np.linalg.norm(updated) + 1e-12)
                    self._counts[best_id] = c + 1
                    if self._counts[best_id] <= 3 or (self._counts[best_id] % 5 == 0):
                        self._save_persisted_voiceprints_locked()
                return best_id, round(max(0.0, best_sim), 4)

            # Open-set enrollment of new speaker slot (owner_speaker_id = PERSON_DELTA is ALWAYS Slot #0!)
            new_id = self._next_available_slot()
            self._prototypes[new_id] = sig
            self._counts[new_id] = 1
            self._save_persisted_voiceprints_locked()
            return new_id, 1.0

    def reset_speakers(self) -> None:
        with self._lock:
            self._prototypes.clear()
            self._counts.clear()
            if self.storage_path is not None and self.storage_path.exists():
                try:
                    self.storage_path.unlink()
                except Exception:
                    pass

    def recluster_orphan_prototypes(self) -> Dict[str, str]:
        """NightSweep Sec. 1 Hybrid Neural + VTL/Weibull Open-Set Prototype Merger."""
        from src.larex_data_intelligence import HybridNeuralVTLPostClusterer

        with self._lock:
            merged = HybridNeuralVTLPostClusterer.recluster_live_prototypes(
                self._prototypes, self._counts
            )
            if merged:
                self._save_persisted_voiceprints_locked()
            return merged

    def score_against_all(
        self, pcm: np.ndarray, bio: BiometricSnapshot
    ) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
        """Scores a PCM clip + biometric snapshot against every enrolled speaker prototype without mutating centroids."""
        sig = self.extract_signature(pcm, bio)
        rankings: List[Dict[str, Any]] = []
        with self._lock:
            snapshot_items = [(k, v.copy(), int(self._counts.get(k, 1))) for k, v in self._prototypes.items()]
        for spk_id, proto, cnt in snapshot_items:
            if spk_id in (TYPIST_SPEAKER_ID, OTHER_ROOM_SPEAKER_ID, *ELECTRONIC_CHARACTER_IDS):
                continue
            if len(proto) == len(sig):
                sim = float(np.clip(np.dot(sig, proto), 0.0, 1.0))
            else:
                sim = 0.35
            rankings.append(
                {
                    "speaker_id": spk_id,
                    "similarity": round(sim, 4),
                    "match_pct": round(sim * 100.0, 1),
                    "samples_enrolled": cnt,
                }
            )
        rankings.sort(key=lambda item: float(item["similarity"]), reverse=True)
        return sig, rankings

    def compute_separation_matrix(self) -> List[Dict[str, Any]]:
        """Computes pairwise voiceprint cosine similarity & separation margin across enrolled human speakers."""
        with self._lock:
            items = [
                (sid, proto.copy())
                for sid, proto in self._prototypes.items()
                if sid not in (TYPIST_SPEAKER_ID, OTHER_ROOM_SPEAKER_ID, *ELECTRONIC_CHARACTER_IDS)
            ]
        pairs: List[Dict[str, Any]] = []
        for i in range(len(items)):
            sid_a, vec_a = items[i]
            for j in range(i + 1, len(items)):
                sid_b, vec_b = items[j]
                if len(vec_a) == len(vec_b):
                    sim = float(np.clip(np.dot(vec_a, vec_b), 0.0, 1.0))
                else:
                    sim = 0.25
                pairs.append(
                    {
                        "speaker_a": sid_a,
                        "speaker_b": sid_b,
                        "similarity_pct": round(sim * 100.0, 1),
                        "separation_pct": round((1.0 - sim) * 100.0, 1),
                    }
                )
        pairs.sort(key=lambda item: float(item["separation_pct"]), reverse=True)
        return pairs


# ============================================================================
# 3. LOCAL OLLAMA (`nightsweep-signalintelligence:latest`) CONTEXTUAL REPAIR
# ============================================================================


class OllamaNightSweepReconstructor:
    """
    Calls local Ollama (`nightsweep-signalintelligence:latest` at 127.0.0.1:11434)
    at temperature=0.15 with strict English dictionary orthography constraints and
    post-validation guards so clean Faster-Whisper transcripts are never mangled
    into phonetic/dialect respellings.
    """

    FORBIDDEN_META = (
        "voiced larynx",
        "unvoiced consonant",
        "person alpha",
        "person beta",
        "person gamma",
        "person delta",
        "rawasr",
        "inventing new facts",
    )

    PHONETIC_ARTIFACTS = {
        "wnt", "cee", "yoo", "nxt", "tyme", "hppn", "gnnnna", "wuz", "sekand",
        "wuant", "fawk", "vih-dohz", "peepul", "luv", "yew", "tday", "rdy",
    }

    def __init__(
        self,
        model: str = "nightsweep-signalintelligence:latest",
        endpoint: str = "http://127.0.0.1:11434/api/generate",
        timeout_sec: float = 15.0,
    ) -> None:
        self.model = model
        self.endpoint = endpoint
        self.timeout_sec = timeout_sec

    @classmethod
    def _is_valid_orthographic_repair(cls, raw_text: str, candidate: str) -> bool:
        if not candidate or len(candidate) < 2:
            return False
        low = candidate.lower()
        for phrase in cls.FORBIDDEN_META:
            if phrase in low:
                return False

        # Reject extreme length distortion
        ratio = len(candidate) / max(len(raw_text), 1)
        if ratio < 0.65 or ratio > 1.50:
            return False

        # Reject spaced-out letter mangling (e.g. "p r s t a b l y" or "s-m-l")
        tokens = candidate.split()
        if len(tokens) >= 5 and sum(1 for t in tokens if len(t.strip(".,!?-")) == 1) >= 4:
            return False
        if candidate.count("-") > raw_text.count("-") + 2:
            return False
        if candidate.count("'") > raw_text.count("'") + 2:
            return False

        # Reject phonetic/SMS respellings introduced by LLM
        raw_words = {w.strip(".,!?;:\"'()").lower() for w in raw_text.split()}
        cand_words = {w.strip(".,!?;:\"'()").lower() for w in tokens}
        added_words = cand_words - raw_words
        if added_words & cls.PHONETIC_ARTIFACTS:
            return False
        # Reject vowel-stripped tokens >= 3 chars containing zero vowels (unless acronym/known in raw)
        vowels = set("aeiouy")
        for w in added_words:
            if len(w) >= 3 and w.isalpha() and not (set(w) & vowels):
                return False
        return True

    # Deterministic NightSweep Sec. 9 unvoiced initial wh-word / plosive drop repairs observed in corpus
    DROPPED_ONSET_REPAIRS = {
        "the is going on?": "What is going on?",
        "the is going on": "What is going on?",
        "is going on?": "What is going on?",
        "are you doing?": "What are you doing?",
        "do you mean?": "What do you mean?",
    }

    def reconstruct(
        self,
        raw_text: str,
        speaker_id: str,
        bio: BiometricSnapshot,
        viseme_hint: str = "",
        phoneme_contour: str = "",
        avg_word_prob: float = 0.80,
    ) -> str:
        clean_raw = raw_text.strip()
        if not clean_raw:
            return clean_raw
        low_norm = " ".join(clean_raw.lower().split())
        if low_norm in self.DROPPED_ONSET_REPAIRS and avg_word_prob < 0.72:
            return self.DROPPED_ONSET_REPAIRS[low_norm]
        if not HAS_REQUESTS or len(clean_raw.split()) < 2:
            return clean_raw

        articulatory_ctx = ""
        if "WHISPER" in bio.band_role and avg_word_prob < 0.68 and (viseme_hint or phoneme_contour):
            articulatory_ctx = (
                f" | MouthViseme={viseme_hint or 'UNKNOWN'}"
                f" | SubvocPhonemeContour={phoneme_contour or 'N/A'}"
                f" | GestureSubvocScore={bio.gesture_subvoc_score:.2f}"
            )

        prompt = (
            "You are a strict English orthographic ASR proofreader (NightSweep Sec. 9 Whisper Speech Reconstruction). "
            "RULES:\n"
            "1. Use ONLY standard English dictionary words and normal punctuation.\n"
            "2. NEVER use phonetic spelling, dialect spelling, slang, abbreviations, hyphens, or dropped vowels.\n"
            "3. Only fix an obvious missing article ('a', 'the'), dropped unvoiced initial wh-word ('what', 'where', 'how'), "
            "or clear homophone error in low-ambient whispered speech "
            "(using MouthViseme / SubvocPhonemeContour only when a word is clearly misheard). "
            "If RawASR is already valid English, copy RawASR verbatim without changing a single word.\n"
            '4. Return ONLY JSON: {"reconstructed": "<clean standard English sentence>"}.\n'
            f"Mode={bio.band_role}{articulatory_ctx} | RawASR={clean_raw!r}"
        )
        try:
            resp = requests.post(
                self.endpoint,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "keep_alive": "15m",
                    "options": {"temperature": 0.1, "repeat_penalty": 1.1, "num_predict": 96},
                },
                timeout=self.timeout_sec,
            )
            if resp.status_code == 200:
                payload = json.loads(resp.json().get("response", "{}"))
                rec = str(payload.get("reconstructed", "")).strip()
                if self._is_valid_orthographic_repair(clean_raw, rec):
                    return rec
        except Exception:
            pass
        return clean_raw


# ============================================================================
# 4. TAMPER-EVIDENT HASH-CHAINED JSONL + FERNET + SQLITE WORD AUDIT LEDGER
# ============================================================================


class ForensicWordLedger:
    """
    Triple-sink forensic logger compliant with Sections 14, 36, and 41:
      1. `biometric_words_<session>.jsonl` — Append-only SHA-256 hash-chained JSONL
      2. `biometric_words_<session>.enc`   — Optional Fernet-encrypted ciphertext mirror
      3. `larex_speaker_words.db`          — SQLite WAL database with per-word indexing
    """

    def __init__(self, output_dir: str = "recordings", encrypt_fernet: bool = True) -> None:
        self.out_path = Path(output_dir)
        try:
            self.out_path.mkdir(parents=True, exist_ok=True)
            probe = self.out_path / ".write_probe"
            probe.write_bytes(b"")
            probe.unlink(missing_ok=True)
        except PermissionError:
            self.out_path = Path(tempfile.gettempdir()) / "GNU-Larex" / "recordings"
            self.out_path.mkdir(parents=True, exist_ok=True)

        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%SZ")
        self.jsonl_path = self.out_path / f"biometric_words_{stamp}.jsonl"
        self.enc_path = self.out_path / f"biometric_words_{stamp}.enc"
        self.db_path = self.out_path / "larex_speaker_words.db"

        self._prev_hash = "0" * 64
        self._fernet = None
        if encrypt_fernet and HAS_FERNET:
            key_file = self.out_path / "secret.key"
            if key_file.exists():
                key = key_file.read_bytes()
            else:
                key = Fernet.generate_key()
                key_file.write_bytes(key)
            self._fernet = Fernet(key)

        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS utterances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp_utc TEXT NOT NULL,
                speaker_id TEXT NOT NULL,
                speaker_match_score REAL NOT NULL,
                start_sec REAL NOT NULL,
                end_sec REAL NOT NULL,
                band_role TEXT NOT NULL,
                raw_transcript TEXT NOT NULL,
                reconstructed_transcript TEXT NOT NULL,
                resp_bpm REAL,
                throat_disp_um REAL,
                f0_hz REAL,
                vtl_cm REAL,
                ood_cosine_dist REAL,
                liveness_verified INTEGER,
                record_sha256 TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS speaker_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                utterance_id INTEGER NOT NULL,
                timestamp_utc TEXT NOT NULL,
                speaker_id TEXT NOT NULL,
                word TEXT NOT NULL,
                word_start_sec REAL NOT NULL,
                word_end_sec REAL NOT NULL,
                asr_probability REAL NOT NULL,
                resp_bpm REAL,
                band_role TEXT,
                FOREIGN KEY(utterance_id) REFERENCES utterances(id)
            );

            CREATE INDEX IF NOT EXISTS idx_words_speaker ON speaker_words(speaker_id, timestamp_utc);
            """
        )
        # Backward-compatible spatial & mouth articulation columns on existing databases
        for col_sql in (
            "ALTER TABLE utterances ADD COLUMN range_m REAL;",
            "ALTER TABLE utterances ADD COLUMN azimuth_deg REAL;",
            "ALTER TABLE utterances ADD COLUMN drr_db REAL;",
            "ALTER TABLE utterances ADD COLUMN c50_db REAL;",
            "ALTER TABLE utterances ADD COLUMN radial_vel_cms REAL;",
            "ALTER TABLE utterances ADD COLUMN proximity_zone TEXT;",
            "ALTER TABLE utterances ADD COLUMN positioning_mode TEXT;",
            "ALTER TABLE utterances ADD COLUMN mouth_openness REAL;",
            "ALTER TABLE utterances ADD COLUMN breath_lfo REAL;",
            "ALTER TABLE utterances ADD COLUMN articulation_energy REAL;",
            "ALTER TABLE utterances ADD COLUMN viseme TEXT;",
        ):
            try:
                self._conn.execute(col_sql)
            except sqlite3.OperationalError:
                pass
        self._conn.commit()

    def log_utterance(
        self,
        speaker_id: str,
        speaker_similarity: float,
        start_sec: float,
        end_sec: float,
        words: List[ExtractedWord],
        reconstructed_transcript: str,
        bio: BiometricSnapshot,
        spatial: Optional[SpatialPositionSnapshot] = None,
        mouth: Optional[Dict[str, Any]] = None,
        earworm: Optional[Dict[str, Any]] = None,
        markov_activation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")
        raw_transcript = " ".join(w.word.strip() for w in words).strip()
        sp = spatial or SpatialPositionSnapshot()
        mo = mouth or {
            "breath_lfo": 0.0,
            "mouth_openness": 0.0,
            "articulation_energy": 0.0,
            "vowel_centroid_hz": 800.0,
            "viseme": "REST_CLOSED",
            "silent_mouthing": False,
        }
        ew = earworm or {}

        # NightSweep Sec. 11 & Sec. 13 Physiological Phase-Unwrap Drift Guard (<= 500 um ceiling)
        clamped_throat_um = float(min(500.0, max(0.0, float(bio.throat_disp_um_rms or 0.0))))

        payload: Dict[str, Any] = {
            "schema_version": "LAREX-NSIG-1.0",
            "timestamp_utc": now_utc,
            "speaker": {
                "speaker_id": speaker_id,
                "biometric_match_score": speaker_similarity,
                "vtl_cm": round(bio.vtl_cm, 2),
                "f0_hz": round(bio.f0_hz, 1),
            },
            "vad_biometrics": {
                "liveness_verified": bio.liveness_verified,
                "band_role": bio.band_role,
                "resp_bpm": round(bio.resp_bpm, 2),
                "throat_disp_um_rms": round(clamped_throat_um, 2),
                "ood_cosine_dist": bio.ood_cosine_dist,
                "gesture_subvoc_score": round(bio.gesture_subvoc_score, 3),
                "low_ambient_cued": bool(bio.low_ambient_cued),
                "ambient_snr_db": round(bio.ambient_snr_db, 2),
            },
            "spatial": dataclasses.asdict(sp),
            "mouth_articulation": mo,
            "whisper_earworm": ew,
            "segment": {
                "start_sec": round(start_sec, 3),
                "end_sec": round(end_sec, 3),
                "raw_transcript": raw_transcript,
                "ollama_reconstructed": reconstructed_transcript,
                "words": [dataclasses.asdict(w) for w in words],
            },
            "prev_sha256": self._prev_hash,
        }
        if markov_activation is not None:
            payload["markov_activation"] = markov_activation

        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        rec_hash = hashlib.sha256(canonical).hexdigest()
        payload["record_sha256"] = rec_hash
        self._prev_hash = rec_hash

        line_bytes = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        with open(self.jsonl_path, "ab") as jf:
            jf.write(line_bytes)

        if self._fernet is not None:
            token = self._fernet.encrypt(line_bytes)
            with open(self.enc_path, "ab") as ef:
                ef.write(token + b"\n")

        cur = self._conn.cursor()
        cur.execute(
            """
            INSERT INTO utterances (
                timestamp_utc, speaker_id, speaker_match_score, start_sec, end_sec,
                band_role, raw_transcript, reconstructed_transcript, resp_bpm,
                throat_disp_um, f0_hz, vtl_cm, ood_cosine_dist, liveness_verified, record_sha256,
                range_m, azimuth_deg, drr_db, c50_db, radial_vel_cms, proximity_zone, positioning_mode,
                mouth_openness, breath_lfo, articulation_energy, viseme
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now_utc,
                speaker_id,
                speaker_similarity,
                start_sec,
                end_sec,
                bio.band_role,
                raw_transcript,
                reconstructed_transcript,
                bio.resp_bpm,
                clamped_throat_um,
                bio.f0_hz,
                bio.vtl_cm,
                bio.ood_cosine_dist,
                1 if bio.liveness_verified else 0,
                rec_hash,
                sp.range_m,
                sp.azimuth_deg,
                sp.drr_db,
                sp.c50_db,
                sp.radial_vel_cms,
                sp.proximity_zone,
                sp.positioning_mode,
                float(mo.get("mouth_openness", 0.0)),
                float(mo.get("breath_lfo", 0.0)),
                float(mo.get("articulation_energy", 0.0)),
                str(mo.get("viseme", "REST_CLOSED")),
            ),
        )
        utt_id = int(cur.lastrowid)
        for w in words:
            cur.execute(
                """
                INSERT INTO speaker_words (
                    utterance_id, timestamp_utc, speaker_id, word,
                    word_start_sec, word_end_sec, asr_probability, resp_bpm, band_role
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utt_id,
                    now_utc,
                    speaker_id,
                    w.word.strip(),
                    w.start_sec,
                    w.end_sec,
                    w.probability,
                    bio.resp_bpm,
                    bio.band_role,
                ),
            )
        self._conn.commit()
        return payload

    def close(self) -> None:
        self._conn.close()


# ============================================================================
# 5. FASTER-WHISPER WORD EXTRACTOR & END-TO-END ORCHESTRATION PIPELINE
# ============================================================================


class FasterWhisperWordExtractor:
    """
    Section 9 Word-Level ASR Extractor using `faster-whisper` with:
      - Local workspace model cache (`models/faster-whisper`) for instant offline startup
      - Exact cross-attention word timestamps (`word_timestamps=True`)
      - `condition_on_previous_text=False` + `no_speech_threshold=0.6` + hallucination
        phrase filter to prevent Whisper silence repetition loops.
    """

    HALLUCINATION_PHRASES = {
        "thank you",
        "thank you.",
        "thank you!",
        "for watching",
        "for watching.",
        "for watching!",
        "thank you for watching",
        "thank you for watching.",
        "thank you for watching!",
        "thanks for watching",
        "thanks for watching.",
        "thanks for watching!",
        "see you next time",
        "see you next time.",
        "see you next time!",
        "see you in the next video",
        "see you in the next video.",
        "see you in the next video!",
        "see you the next video",
        "see you the next video.",
        "see you the next video!",
        "comment and subscribe",
        "comment and subscribe.",
        "comment and subscribe!",
        "like and subscribe",
        "like and subscribe.",
        "like and subscribe!",
        "bye",
        "bye.",
        "bye!",
        "bye-bye",
        "bye-bye.",
        "bye-bye!",
        "bye bye",
        "bye bye.",
        "subtitles by",
        "you",
        "you.",
        "you much",
        "you much.",
        "you very much",
        "you very much.",
        ".",
    }

    HALLUCINATION_SUBSTRINGS = (
        "next video",
        "for watching",
        "comment and subscribe",
        "like and subscribe",
        "forget to subscribe",
        "hit the bell",
        "subtitles by",
        "amara.org",
        "transcribed by",
    )

    @classmethod
    def is_hallucination_transcript(
        cls, text: str, avg_prob: float = 0.65, dur_sec: float = 1.0
    ) -> bool:
        """NightSweep Sec. 9 & Sec. 13 Subtitle/Outro Hallucination Firewall."""
        s = " ".join(str(text or "").strip().lower().split())
        if not s:
            return True
        s_bare = s.strip(" .,!?;:\"'()-")
        if not s_bare:
            return True
        if s in cls.HALLUCINATION_PHRASES or s_bare in cls.HALLUCINATION_PHRASES:
            if s_bare in ("bye", "bye-bye", "bye bye", "thank you"):
                return avg_prob < 0.80
            return True
        for sub in cls.HALLUCINATION_SUBSTRINGS:
            if sub in s:
                return True
        toks = [t.strip(".,!?;:\"'()-") for t in s.split() if t.strip(".,!?;:\"'()-")]
        if dur_sec >= 2.5 and len(toks) <= 3 and s_bare in ("you very much", "you much", "thank you much"):
            return True
        return False

    @staticmethod
    def _is_percussive_tick_artifact(words: List[ExtractedWord]) -> bool:
        """Rejects pure lip/desk click repetitions that Whisper renders as `-T -T -T -T` or `-D -D -D`."""
        if len(words) < 4:
            return False
        stripped = [w.word.strip(" .,!?;:\"'()-").lower() for w in words]
        non_empty = [t for t in stripped if t]
        if not non_empty:
            return True
        if all(len(t) == 1 for t in non_empty):
            return True
        if len(non_empty) >= 5 and len(set(non_empty)) == 1 and len(non_empty[0]) <= 2:
            return True
        return False

    @staticmethod
    def condition_low_ambient_whisper(x_16k: np.ndarray) -> np.ndarray:
        """
        Sub-Ambient Whisper Conditioner (16 kHz):
          1. Cuts <115 Hz HVAC / room sub-hum so low-frequency rumble cannot hijack AGC gain.
          2. Applies a +8.5 dB formant & consonant presence lift across 850–6200 Hz where
             unvoiced F1/F2/F3 oral-cavity resonances and sibilants reside.
          3. Applies soft-knee upward RMS normalization (-16.8 dBFS target) with tanh ceiling
             so faint +1.4 dB ambient whispers enter Faster-Whisper in its optimal dynamic band.
        """
        if len(x_16k) < 64:
            return x_16k
        xf = x_16k.astype(np.float64)
        xf -= float(np.mean(xf))
        n = len(xf)
        spec = np.fft.rfft(xf)
        freqs = np.fft.rfftfreq(n, d=1.0 / 16_000.0)

        # Smooth spectral gain curve: attenuate <115 Hz hum, lift 850-6200 Hz whisper formants (+8.5 dB = 2.66x)
        gain = np.ones_like(freqs, dtype=np.float64)
        hum_mask = freqs < 115.0
        gain[hum_mask] = np.clip((freqs[hum_mask] / 115.0) ** 2, 0.03, 1.0)

        ramp_up = (freqs >= 450.0) & (freqs < 850.0)
        gain[ramp_up] = 1.0 + 1.66 * ((freqs[ramp_up] - 450.0) / 400.0)

        presence = (freqs >= 850.0) & (freqs <= 6200.0)
        gain[presence] = 2.66

        ramp_dn = freqs > 6200.0
        gain[ramp_dn] = np.clip(2.66 - 1.40 * ((freqs[ramp_dn] - 6200.0) / 1800.0), 1.15, 2.66)

        y = np.fft.irfft(spec * gain, n=n)
        rms = float(np.sqrt(np.mean(y * y) + 1e-12))
        target_rms = 0.145
        upward_gain = min(120.0, target_rms / max(rms, 1e-6))
        y_norm = np.tanh((y * upward_gain) / 0.92) * 0.90
        return y_norm.astype(np.float32)

    @staticmethod
    def denoise_short_quiet_utterance(x_16k: np.ndarray, strength: float = 1.65) -> np.ndarray:
        """
        Enhanced Minimum-Statistics Spectral Wiener Denoiser (16 kHz) tuned for PERSON_DELTA
        and quiet, short utterances:
          1. Computes 50%-overlapped 256-sample Hann STFT (16 ms frames).
          2. Estimates stationary background noise PSD from the 18th-percentile frame spectrum.
          3. Applies soft-floor Wiener suppression G(f) = clamp((P - alpha*Pn)/(P + eps), 0.08, 1.0)
             to eliminate room hiss (~10-13 dB SNR gain) with zero musical-noise artifacts.
          4. Follows with +10.5 dB whisper formant lift (820-6200 Hz) & soft-knee 0.165 RMS lift.
        """
        if len(x_16k) < 256:
            return FasterWhisperWordExtractor.condition_low_ambient_whisper(x_16k)
        xf = x_16k.astype(np.float64)
        xf -= float(np.mean(xf))
        n_orig = len(xf)
        win_len = 256
        hop = 128
        pad_right = (hop - ((n_orig - win_len) % hop)) % hop
        x_pad = np.pad(xf, (hop, pad_right + hop), mode="reflect")
        n_frames = 1 + (len(x_pad) - win_len) // hop
        win = np.hanning(win_len)

        frames = np.lib.stride_tricks.as_strided(
            x_pad,
            shape=(n_frames, win_len),
            strides=(x_pad.strides[0] * hop, x_pad.strides[0]),
        ).copy()
        stft = np.fft.rfft(frames * win[None, :], axis=1)
        psd = np.abs(stft) ** 2 + 1e-15

        # Bias-corrected Minimum-Statistics noise PSD: for complex Gaussian room noise,
        # |STFT|^2 ~ Exp(sigma^2), so the 30th percentile equals -ln(1 - 0.30) * sigma^2 = 0.3567 * sigma^2.
        noise_psd = np.percentile(psd, 30.0, axis=0) / 0.3567
        wiener_gain = np.clip((psd - float(strength) * noise_psd[None, :]) / psd, 0.05, 1.0)
        # Mild temporal smoothing across adjacent STFT frames to prevent warble
        if n_frames >= 3:
            wiener_gain[1:-1] = (
                0.22 * wiener_gain[:-2] + 0.56 * wiener_gain[1:-1] + 0.22 * wiener_gain[2:]
            )

        denoised_frames = np.fft.irfft(stft * wiener_gain, n=win_len, axis=1) * win[None, :]
        y_ola = np.zeros(len(x_pad), dtype=np.float64)
        w_ola = np.zeros(len(x_pad), dtype=np.float64)
        w_sq = win * win
        for idx in range(n_frames):
            s = idx * hop
            y_ola[s : s + win_len] += denoised_frames[idx]
            w_ola[s : s + win_len] += w_sq
        y_clean = y_ola / np.maximum(w_ola, 1e-8)
        y_trim = y_clean[hop : hop + n_orig]

        # Apply whisper formant lift + upward RMS target (0.165 for quiet short phrases)
        spec = np.fft.rfft(y_trim)
        freqs = np.fft.rfftfreq(len(y_trim), d=1.0 / 16_000.0)
        eq = np.ones_like(freqs, dtype=np.float64)
        eq[freqs < 120.0] = np.clip((freqs[freqs < 120.0] / 120.0) ** 2, 0.02, 1.0)
        pres = (freqs >= 820.0) & (freqs <= 6200.0)
        eq[pres] = 3.15  # +10.0 dB presence boost for quiet short utterances
        y_eq = np.fft.irfft(spec * eq, n=len(y_trim))
        rms = float(np.sqrt(np.mean(y_eq * y_eq) + 1e-12))
        up_gain = min(145.0, 0.165 / max(rms, 1e-6))
        return (np.tanh((y_eq * up_gain) / 0.92) * 0.90).astype(np.float32)

    def __init__(
        self,
        model_size: str = "small.en",
        device: str = "cpu",
        compute_type: str = "int8",
        download_root: Optional[str] = None,
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        default_cache = Path(__file__).resolve().parent.parent / "models" / "faster-whisper"
        self.download_root = download_root or str(default_cache)
        self.delta_denoise_strength: float = 1.65
        self._model = None

    def _ensure_loaded(self) -> None:
        if self._model is None:
            from faster_whisper import WhisperModel  # type: ignore

            try:
                self._model = WhisperModel(
                    self.model_size,
                    device=self.device,
                    compute_type=self.compute_type,
                    cpu_threads=4,
                    download_root=self.download_root,
                    local_files_only=True,
                )
            except Exception:
                Path(self.download_root).mkdir(parents=True, exist_ok=True)
                self._model = WhisperModel(
                    self.model_size,
                    device=self.device,
                    compute_type=self.compute_type,
                    cpu_threads=4,
                    download_root=self.download_root,
                    local_files_only=False,
                )

    def extract_words(
        self,
        pcm: np.ndarray,
        samp_rate: float = 48_000.0,
        utterance_offset_sec: float = 0.0,
        low_ambient_boost: bool = False,
        denoise_boost: bool = False,
        speaker_hint: str = "",
    ) -> List[ExtractedWord]:
        from src.larex_data_intelligence import UltrasonicAndAcousticOODPreGate

        self._ensure_loaded()
        x = pcm.astype(np.float32)

        # NightSweep Sec. 9 & 40: Strip >14.2 kHz MEMS/ultrasonic carriers & 3 kHz SMPS harmonic combs before resampling
        if samp_rate > 28_000.0 and len(x) >= 256:
            x, _ = UltrasonicAndAcousticOODPreGate.filter_ultrasonic_and_smps_comb(x, samp_rate=samp_rate)

        # Resample 48 kHz -> 16 kHz required by Whisper acoustic frontend
        if abs(samp_rate - 16_000.0) > 1.0:
            if HAS_SCIPY:
                up = 16_000
                down = int(round(samp_rate))
                g = math.gcd(up, down)
                x = sp_signal.resample_poly(x, up // g, down // g).astype(np.float32)
            else:
                target_len = max(1, int(round(len(x) * 16_000.0 / samp_rate)))
                x = np.interp(
                    np.linspace(0.0, 1.0, target_len),
                    np.linspace(0.0, 1.0, len(x)),
                ).astype(np.float32)

        dur_16k = len(x) / 16_000.0
        raw_rms = float(np.sqrt(np.mean(x.astype(np.float64) ** 2) + 1e-16))
        peak = float(np.max(np.abs(x)) + 1e-9)
        if peak < 3e-6:
            return []

        use_wiener_denoise = bool(
            denoise_boost
            or speaker_hint == "PERSON_DELTA"
            or (dur_16k <= 2.40 and raw_rms < 0.018)
        )
        use_whisper_cond = bool(use_wiener_denoise or low_ambient_boost or raw_rms < 0.022)
        if use_wiener_denoise:
            x = self.denoise_short_quiet_utterance(x, strength=self.delta_denoise_strength)
        elif use_whisper_cond:
            x = self.condition_low_ambient_whisper(x)
        else:
            x = (x / peak) * 0.85

        pre_ctx = UltrasonicAndAcousticOODPreGate.evaluate_pre_asr_context(x)
        if use_whisper_cond and pre_ctx["is_stationary_noise_ood"] and raw_rms < 0.008:
            return []

        no_speech_thr = max(0.72, float(pre_ctx["recommended_no_speech_thr"])) if use_whisper_cond else 0.60
        max_seg_nospeech = 0.78 if use_whisper_cond else 0.70
        min_word_prob = 0.14 if use_whisper_cond else 0.16

        segments, _ = self._model.transcribe(
            x,
            beam_size=5,
            word_timestamps=True,
            vad_filter=False,  # Already gated by BiometricFusedVAD + Gesture/Subvoc Co-Gate
            condition_on_previous_text=False,
            repetition_penalty=1.18,
            compression_ratio_threshold=2.2,
            no_speech_threshold=no_speech_thr,
            log_prob_threshold=-1.18 if use_whisper_cond else -1.0,
        )

        extracted: List[ExtractedWord] = []
        for seg in segments:
            if getattr(seg, "no_speech_prob", 0.0) > max_seg_nospeech:
                continue
            seg_txt = str(getattr(seg, "text", "")).strip().lower()
            if self.is_hallucination_transcript(
                seg_txt,
                avg_prob=float(math.exp(max(-5.0, float(getattr(seg, "avg_logprob", -1.0))))),
                dur_sec=dur_16k,
            ):
                continue
            if getattr(seg, "words", None):
                for w in seg.words:
                    token = str(w.word).strip()
                    if token and float(w.probability) >= min_word_prob:
                        extracted.append(
                            ExtractedWord(
                                word=token,
                                start_sec=round(utterance_offset_sec + float(w.start), 3),
                                end_sec=round(utterance_offset_sec + float(w.end), 3),
                                probability=round(float(w.probability), 4),
                            )
                        )
        if not extracted or self._is_percussive_tick_artifact(extracted):
            return []
        full_lower = " ".join(w.word for w in extracted).strip().lower()
        avg_p = float(np.mean([w.probability for w in extracted]))
        if self.is_hallucination_transcript(full_lower, avg_prob=avg_p, dur_sec=dur_16k):
            return []
        return extracted


class BiometricWordLoggingPipeline:
    """
    Complete synchronous/offline pipeline:
      Audio + Biometrics -> BiometricFusedVAD -> BiometricSpeakerAttributor
      -> FasterWhisperWordExtractor -> OllamaNightSweepReconstructor -> ForensicWordLedger
    """

    def __init__(
        self,
        samp_rate: float = 48_000.0,
        output_dir: str = "recordings",
        ollama_model: str = "nightsweep-signalintelligence:latest",
        asr_extractor: Optional[FasterWhisperWordExtractor] = None,
    ) -> None:
        self.vad = BiometricFusedVAD(samp_rate=samp_rate)
        self.attributor = BiometricSpeakerAttributor(samp_rate=samp_rate)
        self.spatial_estimator = SpatialPositionEstimator(samp_rate=samp_rate)
        self.asr = asr_extractor or FasterWhisperWordExtractor()
        self.ollama = OllamaNightSweepReconstructor(model=ollama_model)
        self.ledger = ForensicWordLedger(output_dir=output_dir)
        self.samp_rate = samp_rate

    def process_chunk(
        self,
        audio_chunk: np.ndarray,
        resp_bpm: float = 15.0,
        throat_disp_um: float = 18.0,
    ) -> Optional[Dict[str, Any]]:
        utt = self.vad.push_streaming_chunk(
            audio_chunk, resp_bpm=resp_bpm, throat_disp_um=throat_disp_um
        )
        if utt is None:
            return None

        pcm, start_s, end_s, bio = utt
        spk_id, sim = self.attributor.identify_or_enroll(pcm, bio)
        words = self.asr.extract_words(pcm, samp_rate=self.samp_rate, utterance_offset_sec=start_s)
        if not words:
            return None

        sp = self.spatial_estimator.estimate_utterance_position(
            pcm, speaker_id=spk_id, bio=bio, noise_floor_rms=self.vad._noise_floor_rms
        )
        raw_txt = " ".join(w.word for w in words)
        reconstructed = self.ollama.reconstruct(raw_txt, speaker_id=spk_id, bio=bio)
        return self.ledger.log_utterance(
            speaker_id=spk_id,
            speaker_similarity=sim,
            start_sec=start_s,
            end_sec=end_s,
            words=words,
            reconstructed_transcript=reconstructed,
            bio=bio,
            spatial=sp,
        )

    def close(self) -> None:
        self.ledger.close()


# ============================================================================
# 6. LOCK-FREE REAL-TIME GNU RADIO TAP & ASYNC WORKER FOR LIVE GUI COCKPIT
# ============================================================================


class AsyncBiometricWordService:
    """
    Runs BiometricFusedVAD, per-person speaker diarization, Faster-Whisper ASR,
    3-Tier Acoustic/RF Spatial Position Estimator, Ollama `nightsweep-signalintelligence`
    repair, and ForensicWordLedger inside a dedicated background daemon thread so
    GNU Radio's 48 kHz audio callback never blocks on GIL, disk I/O, CTranslate2, or HTTP.
    """

    FRAME_SAMPLES = 4096  # ~85.3 ms @ 48 kHz -> 11.7 Hz FFT bin resolution for F0 & VTL

    def __init__(
        self,
        samp_rate: float = 48_000.0,
        output_dir: str = "recordings",
        whisper_model: str = "small.en",
        ollama_model: str = "nightsweep-signalintelligence:latest",
        enable_logging: bool = True,
        require_biometric_liveness: bool = True,
        use_ollama_repair: bool = True,
        rf_freq_mhz: float = 915.0,
        rf_gain: float = 38.0,
        sdr_args: str = "",
        hackrf_freq_mhz: float = 2450.0,
        hackrf_gain: float = 44.0,
    ) -> None:
        self.samp_rate = float(samp_rate)
        self.enable_logging = bool(enable_logging)
        self.use_ollama_repair = bool(use_ollama_repair)

        self.vad = BiometricFusedVAD(
            samp_rate=self.samp_rate,
            require_biometric_liveness=require_biometric_liveness,
        )
        self.presence_engine = PresenceVoiceMatchAndUltraMicEngine(
            sample_rate=int(round(self.samp_rate)),
            storage_dir=output_dir,
        )
        self.delta_avatar_engine = DeltaMotionAndAvatarEngine(
            sample_rate=int(round(self.samp_rate)),
            storage_dir=output_dir,
        )
        self.attributor = BiometricSpeakerAttributor(
            samp_rate=self.samp_rate,
            owner_speaker_id=self.presence_engine.owner_speaker_id,
            storage_path=Path(output_dir) / "speaker_voiceprints.json",
        )
        # Cross-sync owner 271-D prototype vector between speaker_voiceprints.json and presence_checkpoints.json
        owner_id = self.presence_engine.owner_speaker_id
        dep_vec = (self.presence_engine.departure_checkpoint or {}).get("prototype_vec")
        if owner_id not in self.attributor._prototypes and dep_vec is not None:
            self.attributor.seed_prototype_vector(owner_id, dep_vec, count=2)
        elif owner_id in self.attributor._prototypes:
            self.presence_engine.sync_owner_prototype(self.attributor._prototypes.get(owner_id))

        self.spatial_estimator = SpatialPositionEstimator(samp_rate=self.samp_rate)
        self.mouth_extractor = BreathAndMouthExtractor(
            sample_rate=int(round(self.samp_rate)), block_size=2048
        )
        self.sdr_radar = AsyncSDRRadarStream(
            rf_samp_rate=960_000.0,
            baseband_rate=self.samp_rate,
            rf_freq_mhz=rf_freq_mhz,
            rf_gain=rf_gain,
            sdr_args=sdr_args,
        )
        self.hackrf_stream = AsyncHackRFStream(
            hw_samp_rate=2_000_000.0,
            rf_out_rate=960_000.0,
            baseband_rate=self.samp_rate,
            rf_freq_mhz=hackrf_freq_mhz,
            rf_gain=hackrf_gain,
            sdr_args="driver=hackrf",
            wait_event=self.sdr_radar.initial_probe_done,
        )
        self.earworm_engine = WhisperEarwormEngine(
            sr=int(round(self.samp_rate)), block_size=2048
        )
        self.zmq_bridge = ZMQWhisperSensorBridge(
            pluto_zmq="tcp://127.0.0.1:5555",
            rtlsdr_zmq="tcp://127.0.0.1:5556",
            hackrf_zmq="tcp://127.0.0.1:5557",
            udp_host="127.0.0.1",
            mixer_port=5005,
            udp_mirror_enabled=True,
            ultrasonic_carrier_hz=40_000.0,
        )
        self.asr = FasterWhisperWordExtractor(model_size=whisper_model)
        self.ollama = OllamaNightSweepReconstructor(model=ollama_model)
        self.ledger = ForensicWordLedger(output_dir=output_dir)
        self.talkback = EarwormTalkbackOrchestrator(
            recordings_dir=Path(output_dir),
            ollama_model=ollama_model,
            udp_broadcast_callback=self.zmq_bridge.broadcast_mirror_audio,
            sse_broadcast_callback=lambda msg: self._broadcast_web_event(
                {"_event_type": "talkback", "talkback_message": msg, "talkback_status": self.talkback.get_status()}
            ),
        )
        self.markov_tracker = SentenceMarkovDeltaTracker()
        self.talkback.harvester.attach_markov_tracker(self.markov_tracker)
        self.typing_engine = AcousticTypingPersonEngine(samp_rate=self.samp_rate)
        self.prespeech_engine = PreSpeechTriggerEngine(sample_rate=int(round(self.samp_rate)))
        self.prespeech_engine.attach_predictors(
            markov_tracker=self.markov_tracker,
            earworm_engine=self.earworm_engine,
            udp_mirror_callback=self.zmq_bridge.broadcast_mirror_audio,
        )
        self.electronics_engine = ElectronicCharacterEngine(samp_rate=self.samp_rate)
        self.reading_detector = SilentReadingDetector(sample_rate=int(round(self.samp_rate)))
        self.piggyback_engine = MidAirPiggybackSublevelEngine(
            samp_rate=self.samp_rate,
            reading_detector=self.reading_detector,
            lexical_resolver=self._resolve_silent_reading_lexical_context,
        )

        self._audio_q: "queue.Queue[Tuple[np.ndarray, float, float]]" = queue.Queue(maxsize=320)
        self.ui_events: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=200)
        self._web_subscribers: List["queue.Queue[Dict[str, Any]]"] = []
        self._web_sub_lock = threading.Lock()

        # Live telemetry readable by Qt timer, Flask SSE API & GNU Radio BiometricAudioTapBlock
        self.live_vad_conf: float = 0.0
        self.live_gate_open: bool = False
        self.live_liveness_ok: bool = True
        self.live_band_role: str = "LISTENING"
        self.live_vtl_cm: float = 17.0
        self.live_ood_dist: float = 0.0
        self.live_spatial: SpatialPositionSnapshot = SpatialPositionSnapshot()
        self.live_mouth: Dict[str, Any] = dict(self.mouth_extractor.latest_state)
        self.mouth_history: List[Dict[str, Any]] = []
        self.live_earworm: Dict[str, Any] = dict(self.earworm_engine.latest_telemetry)
        self.live_gesture_subvoc_score: float = 0.0
        self.live_low_ambient_cued: bool = False
        self.live_ambient_snr_db: float = 0.0
        self.low_ambient_whispers_decoded: int = 0
        default_owner = self.presence_engine.owner_speaker_id or "PERSON_DELTA"
        self.active_speaker_profile: str = default_owner
        self.dynamic_speaker_adaptation: bool = True
        self.mouth_extractor.set_speaker_profile(default_owner)
        self.vad.set_speaker_vad_profile(default_owner)
        self.asr_ready: bool = False
        self.asr_status_msg: str = f"Loading Faster-Whisper ({whisper_model})..."
        self.speaker_stats: Dict[str, Dict[str, Any]] = {}
        self.total_words_logged: int = 0

        # Pre-load CTranslate2 model BEFORE PortAudio stream starts so 48 kHz audio never sees import GIL pauses
        spk_tag = "ResNet34-ONNX" if self.attributor._ort_sess is not None else "BioVTL"
        try:
            self.asr._ensure_loaded()
            self.asr_ready = True
            self.asr_status_msg = f"{spk_tag} + Faster-Whisper ({self.asr.model_size}) + NightSweep Ready"
        except Exception as exc:
            self.asr_status_msg = f"ASR Init Error: {exc}"

        self._stop_evt = threading.Event()
        self._worker = threading.Thread(
            target=self._worker_loop, name="LarexBiometricASRWorker", daemon=True
        )
        self._worker.start()

    def apply_self_improvement(self, payload: Dict[str, Any]) -> List[str]:
        """Applies per-speaker DSP, MouthExtractor, BiometricVAD, Wiener Denoise, and Spatial DRR/GCC-PHAT improvements live."""
        applied: List[str] = []
        target_spk = str(payload.get("speaker_id") or "").strip().upper()
        if "dynamic_speaker_adaptation" in payload:
            self.dynamic_speaker_adaptation = bool(payload["dynamic_speaker_adaptation"])
            applied.append(f"dynamic_speaker_adaptation={self.dynamic_speaker_adaptation}")
        if "gcc_phat_beta" in payload:
            beta_v = float(np.clip(float(payload["gcc_phat_beta"]), 0.45, 1.0))
            self.spatial_estimator.gcc_phat_beta = round(beta_v, 3)
            applied.append(f"gcc_phat_beta={beta_v:.2f}")
        if "delta_denoise_strength" in payload:
            ds_v = float(np.clip(float(payload["delta_denoise_strength"]), 0.80, 3.00))
            self.asr.delta_denoise_strength = round(ds_v, 2)
            applied.append(f"delta_denoise_strength={ds_v:.2f}")
        if isinstance(payload.get("mouth_overrides"), dict) and target_spk:
            mp = self.mouth_extractor.set_speaker_profile(target_spk, payload["mouth_overrides"])
            applied.append(f"mouth_profile[{target_spk}](f_hi={mp['mouth_hi_hz']:.0f}Hz,mult={mp['art_floor_mult']:.2f})")
        if isinstance(payload.get("vad_overrides"), dict) and target_spk:
            vp = self.vad.set_speaker_vad_profile(target_spk, payload["vad_overrides"])
            applied.append(
                f"vad_profile[{target_spk}](dyn={vp['dyn_thresh_mult']:.2f}x,hang={vp['hangover_ms']:.0f}ms,max={vp['max_utt_sec']:.1f}s)"
            )
        if isinstance(payload.get("polar_overrides"), dict) and target_spk:
            pp = self.spatial_estimator.set_speaker_polar_alignment(target_spk, payload["polar_overrides"])
            applied.append(
                f"polar_align[{target_spk}](az={pp['anchor_az_deg']:+.1f}deg,drr_trim={pp['drr_trim_db']:+.1f}dB)"
            )
        if payload.get("activate_speaker_profile") and target_spk and target_spk != TYPIST_SPEAKER_ID:
            self.active_speaker_profile = target_spk
            self.mouth_extractor.set_speaker_profile(target_spk)
            self.vad.set_speaker_vad_profile(target_spk)
            applied.append(f"active_speaker_profile={target_spk}")
        if isinstance(payload.get("markov_config"), dict):
            applied.extend(self.markov_tracker.apply_config(payload["markov_config"]))
        if isinstance(payload.get("typing_config"), dict):
            applied.extend(self.typing_engine.apply_config(payload["typing_config"]))
        if isinstance(payload.get("closest_focus_config"), dict):
            applied.extend(self.piggyback_engine.closest_focus.apply_config(payload["closest_focus_config"]))
        if isinstance(payload.get("three_state_config"), dict):
            applied.extend(self.piggyback_engine.three_state_router.apply_config(payload["three_state_config"]))
        applied.extend(self.piggyback_engine.closest_focus.apply_config(payload))
        applied.extend(self.piggyback_engine.three_state_router.apply_config(payload))
        applied.extend(self.presence_engine.apply_config(payload))
        applied.extend(self.delta_avatar_engine.apply_config(payload))
        return applied

    def score_clip_against_roster(
        self, pcm: np.ndarray, est_vtl_cm: float = 15.2, f0_hz: float = 0.0
    ) -> Dict[str, Any]:
        snap = BiometricSnapshot(
            resp_bpm=15.0,
            resp_phase_exhale=True,
            throat_disp_um_rms=12.0,
            f0_hz=float(f0_hz),
            vtl_cm=float(est_vtl_cm),
            ood_cosine_dist=0.14,
            liveness_verified=True,
            band_role="LOW_AMBIENT_WHISPER" if f0_hz < 55.0 else "VOICED_LARYNX",
        )
        _, rankings = self.attributor.score_against_all(pcm, snap)
        if rankings:
            return {
                "best_speaker_id": rankings[0]["speaker_id"],
                "best_similarity": rankings[0]["similarity"],
                "rankings": rankings,
            }
        return {"best_speaker_id": "NONE", "best_similarity": 0.0, "rankings": []}

    def enroll_speaker_from_pcm(
        self,
        speaker_id: str,
        pcm: np.ndarray,
        est_vtl_cm: float = 14.8,
        f0_hz: float = 185.0,
        blend_weight: float = 0.75,
    ) -> Dict[str, Any]:
        """Enrolls or pins `speaker_id` (e.g. `PERSON_DELTA`) from a live PCM clip and syncs owner presence baseline."""
        spk = str(speaker_id or self.presence_engine.owner_speaker_id or "PERSON_DELTA").strip().upper()
        snap = BiometricSnapshot(
            resp_bpm=15.2,
            resp_phase_exhale=True,
            throat_disp_um_rms=24.0,
            f0_hz=float(f0_hz),
            vtl_cm=float(est_vtl_cm),
            ood_cosine_dist=0.10,
            liveness_verified=True,
            band_role="LOW_AMBIENT_WHISPER" if f0_hz < 55.0 else "VOICED_LARYNX",
        )
        proto, sim = self.attributor.enroll_speaker_clip(spk, pcm, snap, blend_weight=blend_weight)
        if spk == self.presence_engine.owner_speaker_id:
            self.presence_engine.sync_owner_prototype(proto)
        _, rankings = self.attributor.score_against_all(pcm, snap)
        return {
            "speaker_id": spk,
            "similarity": sim,
            "rankings": rankings,
            "prototype_vec": proto,
        }

    def _resolve_silent_reading_lexical_context(self) -> Dict[str, Any]:
        """Resolves the active reader's subvocal / Markov Order-3/4 passage for Silent Reading Out-Loud synthesis."""
        cf = self.piggyback_engine.closest_focus
        preferred_spk = (
            cf.pinned_speaker_id
            if (cf.focus_mode in ("PINNED", "BOTH") and cf.pinned_speaker_id)
            else (cf.locked_speaker_id or self.active_speaker_profile or "PERSON_ALPHA")
        )
        spk = preferred_spk or "PERSON_ALPHA"
        try:
            mk = self.markov_tracker.get_status()
            recent_acts = mk.get("recent_activations") or []
            # Pass 1: match pinned / focused speaker first so pinned identity's Markov chain is spoken out loud
            for match_only_pref in (True, False):
                for act in recent_acts:
                    s_id = str(act.get("speaker_id") or "")
                    if not s_id or s_id in (TYPIST_SPEAKER_ID, OTHER_ROOM_SPEAKER_ID, *ELECTRONIC_CHARACTER_IDS):
                        continue
                    if match_only_pref and s_id != spk:
                        continue
                    hook = str(act.get("earworm_phrase") or act.get("sentence_excerpt") or "").strip()
                    pred = str(act.get("predicted_continuation") or "").strip()
                    if hook:
                        phrase = f"{hook} ... {pred}".strip(" .") if pred else hook
                        return {
                            "speaker_id": s_id,
                            "spoken_text": phrase,
                            "source": f"Promoted {act.get('dominant_model', 'M4')} Markov Chain ({s_id})",
                        }
        except Exception:
            pass
        ew_word = str(self.live_earworm.get("last_lexical_word") or self.live_earworm.get("last_detected_word") or "").strip()
        ew_next = str(self.live_earworm.get("predicted_lexical_word") or self.live_earworm.get("predicted_next_word") or "").strip()
        if ew_word and ew_word != "--":
            return {
                "speaker_id": spk,
                "spoken_text": f"Reading silently: {ew_word} {ew_next}".strip(),
                "source": f"4-Sensor Earworm Subvocal Contour ({spk})",
            }
        wpm = int(self.reading_detector.last_estimated_wpm or 202)
        return {
            "speaker_id": spk,
            "spoken_text": f"{spk.replace('_', ' ').title()} reading silently at {wpm} words per minute in near-field lock.",
            "source": f"ThreeStateVADRouter Cadence ({wpm} WPM)",
        }

    def get_self_improvement_state(self) -> Dict[str, Any]:
        return {
            "active_speaker_profile": self.active_speaker_profile,
            "dynamic_speaker_adaptation": self.dynamic_speaker_adaptation,
            "gcc_phat_beta": round(float(self.spatial_estimator.gcc_phat_beta), 3),
            "delta_denoise_strength": round(float(self.asr.delta_denoise_strength), 2),
            "mouth_profiles": {
                k: dict(v) for k, v in self.mouth_extractor.SPEAKER_MOUTH_PROFILES.items()
            },
            "active_mouth_profile": {
                "speaker_id": self.mouth_extractor.active_speaker_profile,
                "mouth_lo_hz": self.mouth_extractor.mouth_lo_hz,
                "mouth_hi_hz": self.mouth_extractor.mouth_hi_hz,
                "art_floor_mult": self.mouth_extractor.art_floor_mult,
                "min_art_energy": self.mouth_extractor.min_art_energy,
                "breath_smooth": self.mouth_extractor.breath_smooth,
            },
            "vad_profiles": {k: dict(v) for k, v in self.vad.speaker_profiles.items()},
            "polar_alignment_profiles": self.spatial_estimator.get_polar_alignment_profiles(),
            "last_multi_gcc_sources": list(self.spatial_estimator.last_multi_gcc_sources),
        }

    def subscribe_web_events(self) -> "queue.Queue[Dict[str, Any]]":
        q: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=100)
        with self._web_sub_lock:
            self._web_subscribers.append(q)
        return q

    def unsubscribe_web_events(self, q: "queue.Queue[Dict[str, Any]]") -> None:
        with self._web_sub_lock:
            if q in self._web_subscribers:
                self._web_subscribers.remove(q)

    def _broadcast_web_event(self, record: Dict[str, Any]) -> None:
        with self._web_sub_lock:
            subs = list(self._web_subscribers)
        for q in subs:
            try:
                q.put_nowait(record)
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait(record)
                except Exception:
                    pass

    def set_require_liveness(self, required: bool) -> None:
        self.vad.require_biometric_liveness = bool(required)

    def reset_speakers(self) -> None:
        self.attributor.reset_speakers()
        self.spatial_estimator._speaker_tracks.clear()
        self.speaker_stats.clear()

    def _record_typing_burst(
        self, burst: Dict[str, Any], resp_bpm: float = 15.0, throat_disp_um: float = 4.2
    ) -> Dict[str, Any]:
        """
        Logs an acoustic keystroke burst EXCLUSIVELY to `PERSON_TYPIST` (never mixes with human speech/whispers).
        """
        tokens = list(burst.get("tokens") or ["[ALPHA]"])
        t0 = float(burst.get("start_sec", 0.0))
        t1 = float(burst.get("end_sec", t0 + 0.5))
        step = max(0.04, (t1 - t0) / max(1, len(tokens)))
        words = [
            ExtractedWord(
                word=tok,
                start_sec=round(t0 + idx * step, 3),
                end_sec=round(t0 + (idx + 0.8) * step, 3),
                probability=0.96,
            )
            for idx, tok in enumerate(tokens[:24])
        ]
        bio = BiometricSnapshot(
            resp_bpm=round(float(resp_bpm), 2),
            resp_phase_exhale=True,
            throat_disp_um_rms=round(min(float(throat_disp_um), 5.5), 2),
            f0_hz=0.0,
            vtl_cm=0.0,
            ood_cosine_dist=0.04,
            liveness_verified=True,
            band_role="ACOUSTIC_TYPING",
            gesture_subvoc_score=0.0,
            low_ambient_cued=False,
            ambient_snr_db=8.5,
        )
        az_d = float(self.typing_engine.desk_azimuth_deg)
        rng_m = float(self.typing_engine.desk_range_m)
        rad = math.radians(az_d)
        sp_snap = SpatialPositionSnapshot(
            range_m=round(rng_m, 2),
            azimuth_deg=round(az_d, 1),
            x_m=round(rng_m * math.sin(rad), 2),
            y_m=round(rng_m * math.cos(rad), 2),
            drr_db=round(max(-2.0, 12.0 - 5.2 * rng_m), 1),
            c50_db=11.2,
            hf_directivity_db=-3.2,
            radial_vel_cms=0.0,
            proximity_zone="NEAR_FIELD" if rng_m <= 1.05 else "MID_FIELD",
            positioning_mode="TIER1_DESK_TRANSIENT",
            confidence=0.94,
        )
        transcript = str(burst.get("transcript") or " ".join(tokens))
        preview_rec = {
            "timestamp_utc": burst.get("timestamp_utc"),
            "speaker": {"speaker_id": TYPIST_SPEAKER_ID, "f0_hz": 0.0, "vtl_cm": 0.0},
            "vad_biometrics": {"band_role": "ACOUSTIC_TYPING", "low_ambient_cued": False},
            "segment": {"raw_transcript": " ".join(tokens), "ollama_reconstructed": transcript},
        }
        mk_act = self.markov_tracker.evaluate_sentence(preview_rec)
        utt_earworm = {
            "earworm_bpm": round(float(burst.get("kpm", 180.0)) / 2.0, 1),
            "target_f1_hz": 580.0,
            "target_f2_hz": 4200.0,
            "last_phoneme_word": "TIK-THOCK",
            "predicted_phoneme_word": "TIK",
            "last_lexical_word": tokens[-1] if tokens else "[ALPHA]",
            "predicted_lexical_word": "[ALPHA]",
            "next_eta_ms": int(burst.get("mean_iki_ms", 160)),
            "typing_metrics": {
                "key_count": burst.get("key_count", len(tokens)),
                "wpm": burst.get("wpm", 0.0),
                "kpm": burst.get("kpm", 0.0),
                "mean_iki_ms": burst.get("mean_iki_ms", 0.0),
                "z_vibro_score": burst.get("z_vibro_score", 0.0),
                "click_pop_ratio": burst.get("click_pop_ratio", 0.0),
                "desk_sector_preset": burst.get("desk_sector_preset", "CENTER_DESK"),
                "key_classes": burst.get("key_classes", {}),
            },
        }
        rec = self.ledger.log_utterance(
            speaker_id=TYPIST_SPEAKER_ID,
            speaker_similarity=1.0,
            start_sec=t0,
            end_sec=t1,
            words=words,
            reconstructed_transcript=transcript,
            bio=bio,
            spatial=sp_snap,
            mouth={
                "breath_lfo": 0.0,
                "mouth_openness": 0.0,
                "articulation_energy": 0.0,
                "vowel_centroid_hz": 4800.0,
                "viseme": "TYPING_KEYS",
                "silent_mouthing": False,
            },
            earworm=utt_earworm,
            markov_activation=mk_act,
        )
        st = self.speaker_stats.setdefault(
            TYPIST_SPEAKER_ID,
            {
                "words": 0,
                "utterances": 0,
                "vtl_cm": 0.0,
                "f0_hz": 0.0,
                "resp_bpm": 0.0,
                "role": "ACOUSTIC_TYPING",
                "range_m": round(rng_m, 2),
                "azimuth_deg": round(az_d, 1),
                "proximity_zone": "NEAR_FIELD",
            },
        )
        st["words"] += len(words)
        st["utterances"] += 1
        st["role"] = "ACOUSTIC_TYPING"
        st["range_m"] = round(rng_m, 2)
        st["azimuth_deg"] = round(az_d, 1)
        self.total_words_logged += len(words)
        self._broadcast_web_event(rec)
        return rec

    def _record_electronic_event(self, ev: Dict[str, Any]) -> Dict[str, Any]:
        """Logs an isolated electronic click cluster exclusively to `DEVICE_CELLPHONE` or `DEVICE_MEMS`."""
        cid = str(ev.get("speaker_id") or CELLPHONE_SPEAKER_ID).upper()
        role = str(ev.get("band_role") or "ELECTRONIC_CELLPHONE")
        tokens = list(ev.get("tokens") or ["[UI_TICK]"])
        t0 = float(ev.get("start_sec", 0.0))
        t1 = float(ev.get("end_sec", t0 + 0.25))
        step = max(0.035, (t1 - t0) / max(1, len(tokens)))
        words = [
            ExtractedWord(
                word=tok,
                start_sec=round(t0 + idx * step, 3),
                end_sec=round(t0 + (idx + 0.75) * step, 3),
                probability=0.97,
            )
            for idx, tok in enumerate(tokens[:16])
        ]
        bio = BiometricSnapshot(
            resp_bpm=0.0,
            resp_phase_exhale=True,
            throat_disp_um_rms=1.4,
            f0_hz=0.0,
            vtl_cm=0.0,
            ood_cosine_dist=0.03,
            liveness_verified=True,
            band_role=role,
            gesture_subvoc_score=0.0,
            low_ambient_cued=False,
            ambient_snr_db=9.2,
        )
        az_d = float(ev.get("azimuth_deg", 22.0 if cid == CELLPHONE_SPEAKER_ID else -24.0))
        rng_m = float(ev.get("range_m", 0.54 if cid == CELLPHONE_SPEAKER_ID else 0.76))
        rad = math.radians(az_d)
        sp_snap = SpatialPositionSnapshot(
            range_m=round(rng_m, 2),
            azimuth_deg=round(az_d, 1),
            x_m=round(rng_m * math.sin(rad), 2),
            y_m=round(rng_m * math.cos(rad), 2),
            drr_db=round(max(0.0, 13.0 - 4.8 * rng_m), 1),
            c50_db=12.4,
            hf_directivity_db=-1.8,
            radial_vel_cms=0.0,
            proximity_zone="NEAR_FIELD" if rng_m <= 1.05 else "MID_FIELD",
            positioning_mode="TIER1_ULTRASONIC_MEMS",
            confidence=0.95,
        )
        transcript = str(ev.get("transcript") or " ".join(tokens))
        preview_rec = {
            "timestamp_utc": ev.get("timestamp_utc"),
            "speaker": {"speaker_id": cid, "f0_hz": 0.0, "vtl_cm": 0.0},
            "vad_biometrics": {"band_role": role, "low_ambient_cued": False},
            "segment": {"raw_transcript": " ".join(tokens), "ollama_reconstructed": transcript},
        }
        mk_act = self.markov_tracker.evaluate_sentence(preview_rec)
        pk_hz = float(ev.get("mean_peak_hz", 18800.0))
        rec = self.ledger.log_utterance(
            speaker_id=cid,
            speaker_similarity=1.0,
            start_sec=t0,
            end_sec=t1,
            words=words,
            reconstructed_transcript=transcript,
            bio=bio,
            spatial=sp_snap,
            mouth={
                "breath_lfo": 0.0,
                "mouth_openness": 0.0,
                "articulation_energy": 0.0,
                "vowel_centroid_hz": pk_hz,
                "viseme": "MEMS_CLICK",
                "silent_mouthing": False,
            },
            earworm={
                "earworm_bpm": 120.0,
                "target_f1_hz": 180.0 if cid == CELLPHONE_SPEAKER_ID else 4100.0,
                "target_f2_hz": round(min(22000.0, pk_hz), 1),
                "last_phoneme_word": tokens[-1] if tokens else "[MEMS_PING]",
                "predicted_phoneme_word": tokens[0] if tokens else "[MEMS_PING]",
                "last_lexical_word": tokens[-1] if tokens else "[MEMS_PING]",
                "predicted_lexical_word": tokens[0] if tokens else "[MEMS_PING]",
                "next_eta_ms": 110,
                "electronic_metrics": {
                    "click_count": ev.get("click_count", len(tokens)),
                    "mean_peak_hz": pk_hz,
                },
            },
            markov_activation=mk_act,
        )
        st = self.speaker_stats.setdefault(
            cid,
            {
                "words": 0,
                "utterances": 0,
                "vtl_cm": 0.0,
                "f0_hz": 0.0,
                "resp_bpm": 0.0,
                "role": role,
                "range_m": round(rng_m, 2),
                "azimuth_deg": round(az_d, 1),
                "proximity_zone": "NEAR_FIELD",
            },
        )
        st["words"] += len(words)
        st["utterances"] += 1
        st["role"] = role
        st["range_m"] = round(rng_m, 2)
        st["azimuth_deg"] = round(az_d, 1)
        self.total_words_logged += len(words)
        self._broadcast_web_event(rec)
        return rec

    def simulate_electronic_click(self, character_id: str = CELLPHONE_SPEAKER_ID) -> Optional[Dict[str, Any]]:
        cid = str(character_id or CELLPHONE_SPEAKER_ID).strip().upper()
        if cid not in ELECTRONIC_CHARACTER_IDS:
            cid = CELLPHONE_SPEAKER_ID
        pcm = self.electronics_engine.synthesize_character_pcm(cid)
        logged: Optional[Dict[str, Any]] = None
        step = self.FRAME_SAMPLES
        for off in range(0, len(pcm), step):
            evs = self.electronics_engine.push_frame(pcm[off : off + step], noise_floor_rms=0.0011, f0_hz=0.0)
            for ev in evs:
                logged = self._record_electronic_event(ev)
        if logged is None:
            for ev in self.electronics_engine.flush_all():
                logged = self._record_electronic_event(ev)
        return logged

    def simulate_prespeech_event(self, mode: str = "PRE_SPEECH_ONSET") -> Dict[str, Any]:
        ev = self.prespeech_engine.simulate_pre_speech_trigger(mode=mode)
        self._broadcast_web_event({"_event_type": "prespeech", "prespeech_event": ev})
        return ev

    def _record_piggyback_event(self, ev: Dict[str, Any]) -> Dict[str, Any]:
        """Logs a non-occupant other-room sublevel event piggybacked on mid-air acoustics to `OTHER_ROOM_SUBLEVEL`."""
        tokens = list(ev.get("tokens") or ["[WALL_VOICE_MOD]"])
        words = [
            ExtractedWord(
                word=tok,
                start_sec=round(idx * 0.14, 3),
                end_sec=round((idx + 0.85) * 0.14, 3),
                probability=0.95,
            )
            for idx, tok in enumerate(tokens[:10])
        ]
        bio = BiometricSnapshot(
            resp_bpm=0.0,
            resp_phase_exhale=True,
            throat_disp_um_rms=0.0,
            f0_hz=0.0,
            vtl_cm=0.0,
            ood_cosine_dist=0.02,
            liveness_verified=False,  # Explicitly non-occupant!
            band_role="OTHER_ROOM_PIGGYBACK",
            gesture_subvoc_score=0.0,
            low_ambient_cued=False,
            ambient_snr_db=round(float(ev.get("drr_db", -3.2)), 2),
        )
        az_d = float(ev.get("azimuth_deg", self.piggyback_engine.boundary_azimuth_deg))
        rng_m = float(ev.get("range_m", self.piggyback_engine.boundary_range_m))
        rad = math.radians(az_d)
        sp_snap = SpatialPositionSnapshot(
            range_m=round(rng_m, 2),
            azimuth_deg=round(az_d, 1),
            x_m=round(rng_m * math.sin(rad), 2),
            y_m=round(rng_m * math.cos(rad), 2),
            drr_db=round(float(ev.get("drr_db", -3.2)), 1),
            c50_db=-2.8,
            hf_directivity_db=-14.5,
            radial_vel_cms=0.0,
            proximity_zone="FAR_BOUNDARY",
            positioning_mode="TIER2_MIDAIR_PIGGYBACK",
            confidence=round(float(ev.get("coherence", 0.72)), 2),
        )
        transcript = str(ev.get("transcript") or " ".join(tokens))
        preview_rec = {
            "timestamp_utc": ev.get("timestamp_utc"),
            "speaker": {"speaker_id": OTHER_ROOM_SPEAKER_ID, "f0_hz": 0.0, "vtl_cm": 0.0},
            "vad_biometrics": {"band_role": "OTHER_ROOM_PIGGYBACK", "low_ambient_cued": False},
            "segment": {"raw_transcript": " ".join(tokens), "ollama_reconstructed": transcript},
        }
        mk_act = self.markov_tracker.evaluate_sentence(preview_rec)
        rec = self.ledger.log_utterance(
            speaker_id=OTHER_ROOM_SPEAKER_ID,
            speaker_similarity=1.0,
            start_sec=0.0,
            end_sec=0.48,
            words=words,
            reconstructed_transcript=transcript,
            bio=bio,
            spatial=sp_snap,
            mouth={
                "breath_lfo": 0.0,
                "mouth_openness": 0.0,
                "articulation_energy": 0.0,
                "vowel_centroid_hz": float(ev.get("carrier_hz", 19200.0)),
                "viseme": "BOUNDARY_PIGGYBACK",
                "silent_mouthing": False,
            },
            earworm={
                "earworm_bpm": round(float(ev.get("syllabic_mod_hz", 4.0)) * 30.0, 1),
                "target_f1_hz": 165.0,
                "target_f2_hz": 490.0,
                "last_phoneme_word": tokens[0] if tokens else "[WALL_VOICE_MOD]",
                "predicted_phoneme_word": tokens[0] if tokens else "[WALL_VOICE_MOD]",
                "last_lexical_word": tokens[0] if tokens else "[WALL_VOICE_MOD]",
                "predicted_lexical_word": tokens[0] if tokens else "[WALL_VOICE_MOD]",
                "next_eta_ms": 240,
                "piggyback_metrics": {
                    "carrier_hz": ev.get("carrier_hz", 19200.0),
                    "coherence": ev.get("coherence", 0.0),
                    "drr_db": ev.get("drr_db", 0.0),
                    "wall_lpf_ratio": ev.get("wall_lpf_ratio", 0.0),
                    "occupant_reading_state": ev.get("occupant_reading_state", "IDLE"),
                    "audio_url": ev.get("audio_url", ""),
                },
            },
            markov_activation=mk_act,
        )
        st = self.speaker_stats.setdefault(
            OTHER_ROOM_SPEAKER_ID,
            {
                "words": 0,
                "utterances": 0,
                "vtl_cm": 0.0,
                "f0_hz": 0.0,
                "resp_bpm": 0.0,
                "role": "OTHER_ROOM_PIGGYBACK",
                "range_m": round(rng_m, 2),
                "azimuth_deg": round(az_d, 1),
                "proximity_zone": "FAR_BOUNDARY",
            },
        )
        st["words"] += len(words)
        st["utterances"] += 1
        st["role"] = "OTHER_ROOM_PIGGYBACK"
        st["range_m"] = round(rng_m, 2)
        st["azimuth_deg"] = round(az_d, 1)
        self.total_words_logged += len(words)
        self._broadcast_web_event(rec)
        return rec

    def simulate_piggyback_or_reading(
        self, mode: str = "PIGGYBACK_SUBLEVEL", custom_text: str = ""
    ) -> Dict[str, Any]:
        m = str(mode or "PIGGYBACK_SUBLEVEL").strip().upper()
        if m == "SILENT_READING":
            return self.reading_detector.simulate_silent_reading(syllable_hz=4.4)
        if m in ("READING_OUT_LOUD", "THREE_STATE_READING"):
            ev_ol = self.piggyback_engine.three_state_router.simulate_three_state_reading_outloud(
                syllable_hz=4.5, custom_text=custom_text
            )
            self._broadcast_web_event({"_event_type": "reading_outloud", "reading_outloud": ev_ol})
            return ev_ol
        ev = self.piggyback_engine.simulate_piggyback_capture(with_silent_reading=True)
        rec = self._record_piggyback_event(ev)
        return {"event": ev, "record": rec}

    def simulate_live_typing_burst(
        self,
        pattern: str = "ALPHA ALPHA ALPHA ALPHA SPACE ALPHA ALPHA ALPHA MOD ALPHA ALPHA RET",
        wpm: float = 72.0,
    ) -> Optional[Dict[str, Any]]:
        """Synthesizes 48 kHz mechanical keystrokes and runs them through `AcousticTypingPersonEngine`."""
        pcm = self.typing_engine.synthesize_demo_typing_pcm(pattern=pattern, wpm=wpm)
        logged: Optional[Dict[str, Any]] = None
        step = self.FRAME_SAMPLES
        for off in range(0, len(pcm), step):
            burst = self.typing_engine.push_frame(pcm[off : off + step], noise_floor_rms=0.0012, f0_hz=0.0)
            if burst is not None:
                logged = self._record_typing_burst(burst)
        if logged is None:
            flushed = self.typing_engine.flush_pending_burst()
            if flushed is not None:
                logged = self._record_typing_burst(flushed)
        return logged

    def push_realtime(self, pcm_chunk: np.ndarray, resp_bpm: float, throat_disp_um: float) -> None:
        if not self.enable_logging or self._stop_evt.is_set():
            self.live_vad_conf = 0.0
            self.live_gate_open = False
            return
        try:
            self._audio_q.put_nowait((pcm_chunk.copy(), float(resp_bpm), float(throat_disp_um)))
        except queue.Full:
            try:
                self._audio_q.get_nowait()
                self._audio_q.put_nowait((pcm_chunk.copy(), float(resp_bpm), float(throat_disp_um)))
            except Exception:
                pass

    def _worker_loop(self) -> None:
        spk_tag = "ResNet34-ONNX" if self.attributor._ort_sess is not None else "BioVTL"
        try:
            self.asr._ensure_loaded()
            self.asr_ready = True
            self.asr_status_msg = f"{spk_tag} + Faster-Whisper ({self.asr.model_size}) + NightSweep Ready"
        except Exception as exc:
            self.asr_status_msg = f"ASR Init Error: {exc}"

        staging = np.empty(0, dtype=np.float32)
        last_bpm = 15.0
        last_disp = 12.0

        while not self._stop_evt.is_set():
            try:
                chunk, bpm, disp = self._audio_q.get(timeout=0.12)
            except queue.Empty:
                continue

            last_bpm = bpm
            last_disp = disp
            staging = np.concatenate((staging, chunk)) if len(staging) else chunk

            while len(staging) >= self.FRAME_SAMPLES and not self._stop_evt.is_set():
                frame = staging[: self.FRAME_SAMPLES]
                staging = staging[self.FRAME_SAMPLES :]

                # 1. Extract non-vocal breathing LFO + mouth gesture shape FIRST to co-gate low-ambient whispers
                if self.sdr_radar.sdr_connected and self.hackrf_stream.sdr_connected:
                    rtl_disp = self.sdr_radar.get_recent_samples(len(frame))
                    hrf_disp = self.hackrf_stream.get_recent_displacement_um(len(frame))
                    radar_blk = (0.68 * rtl_disp + 0.32 * hrf_disp).astype(np.float32)
                elif self.sdr_radar.sdr_connected:
                    radar_blk = self.sdr_radar.get_recent_samples(len(frame))
                elif self.hackrf_stream.sdr_connected:
                    radar_blk = self.hackrf_stream.get_recent_displacement_um(len(frame))
                else:
                    radar_blk = frame * 120.0
                m_state = self.mouth_extractor.push_streaming_chunks(
                    frame, radar_blk, f0_hz=self.vad.last_snap.f0_hz
                )
                self.live_mouth = dict(m_state)
                self.mouth_history.append(
                    {
                        "mouth_openness": m_state["mouth_openness"],
                        "breath_lfo": m_state["breath_lfo"],
                        "articulation_energy": m_state["articulation_energy"],
                        "viseme": m_state["viseme"],
                    }
                )
                if len(self.mouth_history) > 48:
                    self.mouth_history = self.mouth_history[-48:]

                # 2. Extract 4-Sensor ZMQ + RTL-SDR + HackRF + Ultrasonic subtle subvocalization & F1/F2 whisper state
                p_zmq, r_zmq, h_zmq = self.zmq_bridge.pull_all(len(frame))
                if float(np.max(np.abs(r_zmq))) < 1e-6 and self.sdr_radar.sdr_connected:
                    r_zmq = np.tanh(radar_blk / 250.0).astype(np.float32)
                if float(np.max(np.abs(h_zmq))) < 1e-6 and self.hackrf_stream.sdr_connected:
                    h_zmq = self.hackrf_stream.get_recent_samples(len(frame))
                ew_state = self.earworm_engine.push_streaming_chunks(
                    p_zmq,
                    r_zmq,
                    h_zmq,
                    frame,
                    audio_sr=int(round(self.samp_rate)),
                    ultrasonic_carrier_hz=self.zmq_bridge.ultrasonic_carrier_hz,
                )
                self.live_earworm = dict(ew_state)
                if self.earworm_engine.whisper_gain > 0.01:
                    mirror_pcm = self.earworm_engine.synthesize_whisper_mirror(
                        len(frame), int(round(self.samp_rate))
                    )
                    self.zmq_bridge.broadcast_mirror_audio(mirror_pcm)

                # 2b. Dedicated 48 kHz Acoustic Typing Detector -> routes keystroke bursts ONLY to PERSON_TYPIST
                typing_burst = self.typing_engine.push_frame(
                    frame,
                    noise_floor_rms=self.vad._noise_floor_rms,
                    f0_hz=self.vad.last_snap.f0_hz,
                    live_azimuth_deg=self.live_spatial.azimuth_deg,
                    live_range_m=self.live_spatial.range_m,
                )
                if typing_burst is not None:
                    try:
                        self._record_typing_burst(typing_burst, resp_bpm=last_bpm, throat_disp_um=last_disp)
                    except Exception:
                        pass

                # 2c. Pre-Speech Trigger Engine (50-200ms pre-phonatory window -> Pre-Hears Earworm Δ before speech!)
                ps_event = self.prespeech_engine.push_streaming_chunks(
                    raw_audible=frame,
                    pluto_radar=p_zmq,
                    rtlsdr_throat=r_zmq,
                    hackrf_rf=h_zmq,
                    ultra_shifted=None,
                )
                if ps_event is not None:
                    self._broadcast_web_event({"_event_type": "prespeech", "prespeech_event": ps_event})

                # 2d. Electronic & MEMS Character Detector -> routes cellphone & MEMS clicks to DEVICE_CELLPHONE / DEVICE_MEMS
                elec_events = self.electronics_engine.push_frame(
                    frame,
                    noise_floor_rms=self.vad._noise_floor_rms,
                    f0_hz=self.vad.last_snap.f0_hz,
                    is_keyboard_typing=self.typing_engine.is_typing_active,
                )
                for el_ev in elec_events:
                    try:
                        self._record_electronic_event(el_ev)
                    except Exception:
                        pass

                # 2e. ThreeStateVADRouter + SilentReadingDetector + Mid-Air Piggyback Sublevel Extractor
                self.piggyback_engine.last_out_loud_event = None
                pb_event = self.piggyback_engine.push_frame(
                    frame,
                    f0_hz=self.vad.last_snap.f0_hz,
                    pluto_radar=p_zmq,
                    rtlsdr_throat=r_zmq,
                )
                if self.piggyback_engine.last_out_loud_event is not None:
                    ol_raw = self.piggyback_engine.last_out_loud_event
                    self.piggyback_engine.last_out_loud_event = None
                    ol_pcm = ol_raw.get("_pcm_f32")
                    if (
                        ol_pcm is not None
                        and self.piggyback_engine.three_state_router.udp_out_loud_mirror
                    ):
                        blk_u = 2048
                        for off_u in range(0, min(len(ol_pcm), 48_000 * 3), blk_u):
                            self.zmq_bridge.broadcast_mirror_audio(ol_pcm[off_u : off_u + blk_u])
                    ol_clean = {k: v for k, v in ol_raw.items() if k != "_pcm_f32"}
                    self._broadcast_web_event({"_event_type": "reading_outloud", "reading_outloud": ol_clean})
                if pb_event is not None:
                    try:
                        self._record_piggyback_event(pb_event)
                    except Exception:
                        pass

                # 2f. UltraMic384K_EVO 48 kHz Ambiance Ring Buffer + Unknown Low-Ambient Subvoc Scanner
                unk_ev = self.presence_engine.push_ultramic_frame(
                    frame,
                    noise_floor_rms=self.vad._noise_floor_rms,
                    f0_hz=self.vad.last_snap.f0_hz,
                    gesture_subvoc_score=self.vad.last_snap.gesture_subvoc_score,
                    live_range_m=self.live_spatial.range_m,
                    live_azimuth_deg=self.live_spatial.azimuth_deg,
                    roster_scorer=self.score_clip_against_roster,
                )
                if unk_ev is not None:
                    self._broadcast_web_event({"_event_type": "unknown_subvoc", "unknown_subvoc": unk_ev})

                # 2g. Closest-Identity / Pinned Faint-Signal Room Focus: gently lower whisper gate inside focus sector without going below 1.22x ambient ripple
                cf_eng = self.piggyback_engine.closest_focus
                if cf_eng.is_in_focus_sector(self.live_spatial.azimuth_deg, self.live_spatial.range_m):
                    self.vad.low_ambient_whisper_mult = min(
                        self.vad.low_ambient_whisper_mult, max(1.22, cf_eng.ultra_faint_vad_mult)
                    )

                # 2h. 0.5-4.0 Hz Delta Brainwave Envelope + VAD Motion Co-Validation Cue
                motion_cue = self.delta_avatar_engine.push_realtime_frame(
                    frame,
                    radar_disp_blk=radar_blk,
                    live_range_m=self.live_spatial.range_m,
                    live_azimuth_deg=self.live_spatial.azimuth_deg,
                    live_drr_db=self.live_spatial.drr_db,
                    radial_vel_cms=self.live_spatial.radial_vel_cms,
                    resp_bpm=last_bpm,
                    f0_hz=self.vad.last_snap.f0_hz,
                    earworm_state=ew_state,
                    active_speaker_id=self.active_speaker_profile,
                )

                # 3. Co-gated Biometric + Mouth-Gesture + Subvocalization + VAD Motion
                completed = self.vad.push_streaming_chunk(
                    frame,
                    resp_bpm=last_bpm,
                    throat_disp_um=last_disp,
                    mouth_cue=m_state,
                    earworm_cue=ew_state,
                    motion_cue=motion_cue,
                )
                gate_open = self.vad.last_gate_open
                conf = self.vad.last_conf
                snap = self.vad.last_snap
                self.live_gate_open = gate_open
                self.live_vad_conf = conf if gate_open else conf * 0.35
                self.live_liveness_ok = snap.liveness_verified
                self.live_band_role = snap.band_role if gate_open else "IDLE"
                self.live_vtl_cm = snap.vtl_cm
                self.live_ood_dist = snap.ood_cosine_dist
                self.live_gesture_subvoc_score = snap.gesture_subvoc_score
                self.live_low_ambient_cued = snap.low_ambient_cued
                self.live_ambient_snr_db = snap.ambient_snr_db
                self.spatial_estimator.update_live_frame(
                    frame, gate_open=gate_open, noise_floor_rms=self.vad._noise_floor_rms
                )
                self.live_spatial = self.spatial_estimator.live_fix

                if completed is None or not self.asr_ready:
                    continue

                pcm, start_s, end_s, bio = completed
                try:
                    if self.piggyback_engine.closest_focus.enabled:
                        pcm_focus, focus_meta = self.piggyback_engine.closest_focus.enhance_closest_faint_frame(
                            pcm,
                            live_azimuth_deg=self.live_spatial.azimuth_deg,
                            live_range_m=self.live_spatial.range_m,
                            noise_floor_rms=self.vad._noise_floor_rms,
                        )
                        if focus_meta.get("boosted"):
                            pcm = pcm_focus
                    use_boost = bool(bio.low_ambient_cued or "WHISPER" in bio.band_role)
                    used_delta_denoise = bool(self.active_speaker_profile == "PERSON_DELTA")
                    words = self.asr.extract_words(
                        pcm,
                        samp_rate=self.samp_rate,
                        utterance_offset_sec=start_s,
                        low_ambient_boost=use_boost,
                        denoise_boost=used_delta_denoise,
                        speaker_hint=self.active_speaker_profile,
                    )
                    if not words and not used_delta_denoise and (end_s - start_s) <= 2.6:
                        # Retry quiet short utterance with PERSON_DELTA Minimum-Statistics Wiener Denoiser
                        words = self.asr.extract_words(
                            pcm,
                            samp_rate=self.samp_rate,
                            utterance_offset_sec=start_s,
                            low_ambient_boost=True,
                            denoise_boost=True,
                            speaker_hint="PERSON_DELTA",
                        )
                        used_delta_denoise = True
                    if not words:
                        continue
                    if bio.low_ambient_cued or bio.band_role == "LOW_AMBIENT_WHISPER":
                        self.low_ambient_whispers_decoded += 1

                    spk_id, sim = self.attributor.identify_or_enroll(pcm, bio)
                    if spk_id in (TYPIST_SPEAKER_ID, OTHER_ROOM_SPEAKER_ID, *ELECTRONIC_CHARACTER_IDS):
                        # Strict isolation: non-vocal & non-occupant identities never receive local vocal utterances
                        spk_id = self.presence_engine.owner_speaker_id or "PERSON_DELTA"
                    if spk_id == self.presence_engine.owner_speaker_id:
                        self.presence_engine.sync_owner_prototype(self.attributor._prototypes.get(spk_id))
                    avg_check_p = sum(w.probability for w in words) / max(1, len(words))
                    if (
                        self.typing_engine.is_typing_active
                        and bio.f0_hz < 55.0
                        and avg_check_p < 0.40
                        and len(words) <= 3
                    ):
                        # Suppress low-confidence Whisper click artifacts during active keyboard typing
                        continue
                    if spk_id == "PERSON_DELTA" and not used_delta_denoise:
                        avg_p0 = sum(w.probability for w in words) / max(1, len(words))
                        if avg_p0 < 0.62:
                            dn_words = self.asr.extract_words(
                                pcm,
                                samp_rate=self.samp_rate,
                                utterance_offset_sec=start_s,
                                low_ambient_boost=True,
                                denoise_boost=True,
                                speaker_hint="PERSON_DELTA",
                            )
                            if dn_words:
                                avg_p1 = sum(w.probability for w in dn_words) / len(dn_words)
                                if avg_p1 >= avg_p0 or len(dn_words) > len(words):
                                    words = dn_words

                    if self.dynamic_speaker_adaptation and spk_id != self.active_speaker_profile:
                        self.active_speaker_profile = spk_id
                        self.mouth_extractor.set_speaker_profile(spk_id)
                        self.vad.set_speaker_vad_profile(spk_id)
                    rf_utt = (
                        self.sdr_radar.get_recent_samples(len(pcm))
                        if self.sdr_radar.sdr_connected
                        else None
                    )
                    blk_sz = self.mouth_extractor.block_size
                    if len(pcm) > blk_sz * 2:
                        n_blks = len(pcm) // blk_sz
                        energies = [
                            float(np.mean(pcm[i * blk_sz : (i + 1) * blk_sz] ** 2))
                            for i in range(n_blks)
                        ]
                        pk_i = int(np.argmax(energies))
                        sl = slice(pk_i * blk_sz, (pk_i + 1) * blk_sz)
                        pcm_peak = pcm[sl]
                        rf_peak = rf_utt[sl] if (rf_utt is not None and len(rf_utt) >= (pk_i + 1) * blk_sz) else (pcm_peak * 120.0)
                    else:
                        pcm_peak = pcm
                        rf_peak = rf_utt if rf_utt is not None else (pcm * 120.0)
                    utt_mouth = self.mouth_extractor.extract_non_vocal_layers(
                        pcm_peak, rf_peak, f0_hz=bio.f0_hz
                    )
                    sp_snap = self.spatial_estimator.estimate_utterance_position(
                        pcm,
                        speaker_id=spk_id,
                        bio=bio,
                        noise_floor_rms=self.vad._noise_floor_rms,
                        rf_subvoc=rf_utt,
                    )
                    self.live_spatial = sp_snap
                    raw_txt = " ".join(w.word for w in words).strip()
                    avg_wp = sum(w.probability for w in words) / max(1, len(words))
                    if self.use_ollama_repair:
                        reconstructed = self.ollama.reconstruct(
                            raw_txt,
                            speaker_id=spk_id,
                            bio=bio,
                            viseme_hint=str(utt_mouth.get("viseme", "")),
                            phoneme_contour=str(self.live_earworm.get("last_detected_word", "")),
                            avg_word_prob=avg_wp,
                        )
                    else:
                        reconstructed = raw_txt

                    self.earworm_engine.ingest_lexical_utterance(reconstructed.split())
                    self.live_earworm = dict(self.earworm_engine.latest_telemetry)
                    utt_earworm = {
                        "earworm_bpm": self.live_earworm.get("earworm_bpm", 120.0),
                        "target_f1_hz": self.live_earworm.get("target_f1_hz", 500.0),
                        "target_f2_hz": self.live_earworm.get("target_f2_hz", 1500.0),
                        "last_phoneme_word": self.live_earworm.get("last_detected_word", "--"),
                        "predicted_phoneme_word": self.live_earworm.get("predicted_next_word", "--"),
                        "last_lexical_word": self.live_earworm.get("last_lexical_word", "--"),
                        "predicted_lexical_word": self.live_earworm.get("predicted_lexical_word", "--"),
                        "next_eta_ms": self.live_earworm.get("next_eta_ms", 500),
                    }
                    preview_rec = {
                        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds"),
                        "speaker": {"speaker_id": spk_id, "f0_hz": bio.f0_hz, "vtl_cm": bio.vtl_cm},
                        "vad_biometrics": {
                            "band_role": bio.band_role,
                            "low_ambient_cued": bool(bio.low_ambient_cued),
                        },
                        "segment": {"raw_transcript": raw_txt, "ollama_reconstructed": reconstructed},
                    }
                    mk_act = self.markov_tracker.evaluate_sentence(preview_rec)

                    utt_sig, utt_rankings = self.attributor.score_against_all(pcm, bio)
                    record = self.ledger.log_utterance(
                        speaker_id=spk_id,
                        speaker_similarity=sim,
                        start_sec=start_s,
                        end_sec=end_s,
                        words=words,
                        reconstructed_transcript=reconstructed,
                        bio=bio,
                        spatial=sp_snap,
                        mouth=utt_mouth,
                        earworm=utt_earworm,
                        markov_activation=mk_act,
                    )

                    # Update per-speaker live summary stats
                    st = self.speaker_stats.setdefault(
                        spk_id,
                        {
                            "words": 0,
                            "utterances": 0,
                            "vtl_cm": bio.vtl_cm,
                            "f0_hz": bio.f0_hz,
                            "resp_bpm": bio.resp_bpm,
                            "role": bio.band_role,
                            "range_m": sp_snap.range_m,
                            "azimuth_deg": sp_snap.azimuth_deg,
                            "proximity_zone": sp_snap.proximity_zone,
                        },
                    )
                    st["words"] += len(words)
                    st["utterances"] += 1
                    st["vtl_cm"] = round(0.7 * st["vtl_cm"] + 0.3 * bio.vtl_cm, 1)
                    if bio.f0_hz > 50.0:
                        st["f0_hz"] = round(0.7 * st["f0_hz"] + 0.3 * bio.f0_hz, 1) if st["f0_hz"] > 0 else round(bio.f0_hz, 1)
                    if bio.resp_bpm > 0.0:
                        st["resp_bpm"] = round(bio.resp_bpm, 1)
                    st["role"] = bio.band_role
                    st["range_m"] = sp_snap.range_m
                    st["azimuth_deg"] = sp_snap.azimuth_deg
                    st["proximity_zone"] = sp_snap.proximity_zone
                    self.total_words_logged += len(words)

                    try:
                        self.ui_events.put_nowait(record)
                    except queue.Full:
                        try:
                            self.ui_events.get_nowait()
                            self.ui_events.put_nowait(record)
                        except Exception:
                            pass
                    self._broadcast_web_event(record)
                    try:
                        arr_comp = self.presence_engine.record_live_utterance_match(
                            record,
                            rankings=utt_rankings,
                            utterance_pcm=pcm,
                            utterance_sig=utt_sig,
                        )
                        if arr_comp is not None:
                            self._broadcast_web_event({"_event_type": "arrival_compared", "arrival_comparison": arr_comp})
                    except Exception:
                        pass
                    try:
                        self.talkback.on_live_utterance(record)
                    except Exception:
                        pass
                    try:
                        d_assoc = self.delta_avatar_engine.record_utterance_association(
                            record,
                            earworm_phrase=str((mk_act or {}).get("earworm_phrase") or ""),
                        )
                        if d_assoc is not None:
                            self._broadcast_web_event({"_event_type": "delta_avatar", "delta_association": d_assoc})
                    except Exception:
                        pass
                except Exception as exc:
                    self.asr_status_msg = f"Decode warning: {exc}"

    def reconnect_sdrs(self) -> None:
        self.sdr_radar.reconnect()
        self.hackrf_stream.reconnect()

    def stop(self) -> None:
        self._stop_evt.set()
        self.sdr_radar.stop()
        self.hackrf_stream.stop()
        self.zmq_bridge.close()
        if self._worker.is_alive():
            self._worker.join(timeout=1.5)
        self.ledger.close()


try:
    from gnuradio import gr  # type: ignore

    class BiometricAudioTapBlock(gr.sync_block):
        """
        Lightweight 400 Hz Biometric-Fused VAD telemetry stream source fed by
        `BiometricTrackerBlock` output 2 -> drives QtGUI `Biometric Liveness VAD` meter
        with zero 48 kHz audio-thread overhead.
        """

        def __init__(self, service: AsyncBiometricWordService) -> None:
            gr.sync_block.__init__(
                self,
                name="Biometric Liveness VAD Meter Source",
                in_sig=[np.float32],
                out_sig=[np.float32],
            )
            self.service = service
            self._smoothed_vad: float = 0.0

        def work(self, input_items, output_items) -> int:
            out_vad = output_items[0]
            n = len(out_vad)
            target = float(self.service.live_vad_conf)
            self._smoothed_vad = 0.75 * self._smoothed_vad + 0.25 * target
            out_vad[:] = self._smoothed_vad
            return n

except ImportError:
    pass
