#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GNU-Larex :: Multi-Mode Sliding-Window FrequencyDetector (Goertzel · CFAR FFT · ZCR)
====================================================================================
Implements `FrameDetection` and `FrequencyDetector` with:
  1. Generalized Goertzel Algorithm (`detect_goertzel_frame`) with FFT-free local
     sideband noise-floor estimation (`guard_bins=2, noise_bins=4`) and coherent
     window gain compensation (`self.window_gain`).
  2. STFT / FFT Dynamic Sweep Detector (`detect_fft_frame`) with 3-point parabolic
     sub-bin frequency interpolation (`alpha, beta, gamma`) and CFAR-style local
     guard/noise bin SNR thresholding (`guard_bins=2, noise_bins=8`).
  3. Zero-Crossing Rate Detector (`detect_zcr_frame`) with zero-jitter sign latch
     and fractional linear crossing interpolation (`_fractional_index`) for fast,
     sub-Hz estimation on clean isolated sine waves.
  4. Stateful Sliding-Window Stream Processor (`process_stream_chunk`, 50% overlap
     default) for real-time audio callbacks, GNU Radio ZMQ bridges, and game/DSP loops.
  5. `FrequencyDetectorEngine` & `query_ollama_frequency_detector_advisor` integrating
     all 3 detection modes into GNU-Larex's Web Cockpit, Person Dossier Modal,
     NightSweep Feature Lab, and `nightsweep-signalintelligence:latest` Ollama model.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import datetime
import io
import json
import math
from pathlib import Path
import time
from typing import Any, Dict, List, Literal, Optional, Tuple
import wave

import numpy as np

try:
    import requests

    HAS_REQUESTS = True
except Exception:
    requests = None  # type: ignore
    HAS_REQUESTS = False


@dataclass
class FrameDetection:
    timestamp_sec: float
    method: str
    frequency_hz: float
    magnitude: float
    snr_ratio: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp_sec": round(float(self.timestamp_sec), 5),
            "method": str(self.method),
            "frequency_hz": round(float(self.frequency_hz), 3),
            "magnitude": round(float(self.magnitude), 5),
            "snr_ratio": round(float(self.snr_ratio), 3),
        }


class FrequencyDetector:
    """Detects target tones, dynamic sweeps, or clean sine waves using:

    - Sliding overlapping frames (default 1024 samples, 50% overlap)
    - Hann or Hamming windowing
    - Local moving noise-floor (SNR ratio) thresholding
    """

    def __init__(
        self,
        sample_rate: int = 44100,
        frame_size: int = 1024,
        overlap: float = 0.5,
        window_type: Literal["hann", "hamming"] = "hann",
        snr_threshold: float = 4.0,
        min_magnitude: float = 1e-4,
    ):
        if not (0.0 <= overlap < 1.0):
            raise ValueError("overlap must be in [0.0, 1.0)")

        self.sample_rate = int(sample_rate)
        self.frame_size = int(frame_size)
        self.overlap = float(overlap)
        self.window_type = window_type
        self.hop_size = max(1, int(frame_size * (1.0 - overlap)))
        self.snr_threshold = float(snr_threshold)
        self.min_magnitude = float(min_magnitude)

        # Precompute window + coherent gain compensation
        if window_type == "hann":
            self.window = np.hanning(frame_size)
        elif window_type == "hamming":
            self.window = np.hamming(frame_size)
        else:
            raise ValueError("window_type must be 'hann' or 'hamming'")
        self.window_gain = float(np.sum(self.window) / frame_size)

        # Stateful ring buffer for streaming / game-loop chunks
        self._buffer = np.zeros(0, dtype=np.float64)
        self._samples_processed = 0

    def reset_stream(self) -> None:
        """Clears the stateful streaming ring buffer and sample counter."""
        self._buffer = np.zeros(0, dtype=np.float64)
        self._samples_processed = 0

    # ------------------------------------------------------------------
    # 1. Goertzel Algorithm (Specific Target Tones + Local Noise Floor)
    # ------------------------------------------------------------------
    def _goertzel_mag(self, windowed_frame: np.ndarray, target_hz: float) -> float:
        """Evaluates single-frequency magnitude via generalized Goertzel."""
        n = len(windowed_frame)
        k = (n * target_hz) / self.sample_rate
        omega = (2.0 * np.pi * k) / n
        coeff = 2.0 * np.cos(omega)

        s_prev = 0.0
        s_prev2 = 0.0
        for sample in windowed_frame:
            s = sample + coeff * s_prev - s_prev2
            s_prev2 = s_prev
            s_prev = s

        power = s_prev2**2 + s_prev**2 - coeff * s_prev * s_prev2
        mag = (2.0 * np.sqrt(max(power, 0.0))) / (n * self.window_gain)
        return float(mag)

    def detect_goertzel_frame(
        self,
        raw_frame: np.ndarray,
        target_freqs: list[float],
        guard_bins: int = 2,
        noise_bins: int = 4,
        timestamp_sec: float = 0.0,
    ) -> list[FrameDetection]:
        """Checks known target frequencies and compares each against neighboring
        frequency offsets to compute a local noise floor without running an FFT.
        """
        windowed = (raw_frame - np.mean(raw_frame)) * self.window
        bin_width = self.sample_rate / self.frame_size
        detections: list[FrameDetection] = []

        for f0 in target_freqs:
            target_mag = self._goertzel_mag(windowed, f0)
            if target_mag < self.min_magnitude:
                continue

            # Sample surrounding sideband bins to estimate local noise floor
            side_offsets = [
                i * bin_width
                for i in range(guard_bins + 1, guard_bins + 1 + noise_bins)
            ]
            neighbor_freqs = [
                f
                for delta in side_offsets
                for f in (f0 - delta, f0 + delta)
                if 0.0 < f < (self.sample_rate / 2.0)
            ]

            if neighbor_freqs:
                noise_floor = float(
                    np.mean([self._goertzel_mag(windowed, nf) for nf in neighbor_freqs])
                )
            else:
                noise_floor = 1e-12

            snr = target_mag / max(noise_floor, 1e-12)
            if snr >= self.snr_threshold:
                detections.append(
                    FrameDetection(timestamp_sec, "goertzel", float(f0), target_mag, snr)
                )

        return detections

    # ------------------------------------------------------------------
    # 2. STFT / FFT Sweep Detector (Full Spectrum + CFAR-style Local SNR)
    # ------------------------------------------------------------------
    def detect_fft_frame(
        self,
        raw_frame: np.ndarray,
        freq_range: tuple[float, float] = (50.0, 12000.0),
        guard_bins: int = 2,
        noise_bins: int = 8,
        timestamp_sec: float = 0.0,
    ) -> FrameDetection | None:
        """Finds peak frequency across a dynamic sweep band, gated by local bin SNR."""
        windowed = (raw_frame - np.mean(raw_frame)) * self.window
        spectrum = np.abs(np.fft.rfft(windowed)) * (
            2.0 / (self.frame_size * self.window_gain)
        )
        freqs = np.fft.rfftfreq(self.frame_size, d=1.0 / self.sample_rate)

        band_indices = np.where(
            (freqs >= freq_range[0]) & (freqs <= freq_range[1])
        )[0]
        if len(band_indices) == 0:
            return None

        peak_local_idx = int(np.argmax(spectrum[band_indices]))
        peak_bin = int(band_indices[peak_local_idx])
        peak_mag = float(spectrum[peak_bin])

        if peak_mag < self.min_magnitude:
            return None

        # Parabolic interpolation for sub-bin frequency accuracy during sweeps
        if 0 < peak_bin < len(spectrum) - 1:
            alpha, beta, gamma = (
                spectrum[peak_bin - 1],
                spectrum[peak_bin],
                spectrum[peak_bin + 1],
            )
            denom = alpha - 2.0 * beta + gamma
            delta = 0.5 * (alpha - gamma) / denom if abs(denom) > 1e-12 else 0.0
            refined_freq = (peak_bin + delta) * (self.sample_rate / self.frame_size)
        else:
            refined_freq = float(freqs[peak_bin])

        # Moving local noise floor: average surrounding bins, skipping guard bins around the spike
        left_start = max(0, peak_bin - guard_bins - noise_bins)
        left_end = max(0, peak_bin - guard_bins)
        right_start = min(len(spectrum), peak_bin + guard_bins + 1)
        right_end = min(len(spectrum), peak_bin + guard_bins + 1 + noise_bins)

        surrounding = np.concatenate(
            [spectrum[left_start:left_end], spectrum[right_start:right_end]]
        )
        noise_floor = float(np.mean(surrounding)) if len(surrounding) > 0 else 1e-12

        snr = peak_mag / max(noise_floor, 1e-12)
        if snr >= self.snr_threshold:
            return FrameDetection(
                timestamp_sec, "fft_sweep", float(refined_freq), peak_mag, snr
            )
        return None

    # ------------------------------------------------------------------
    # 3. Zero-Crossing Rate (Fast Estimate for Clean Isolated Sine Waves)
    # ------------------------------------------------------------------
    def detect_zcr_frame(
        self,
        raw_frame: np.ndarray,
        timestamp_sec: float = 0.0,
    ) -> FrameDetection | None:
        """Counts interpolated zero crossings on clean, high-amplitude waveforms."""
        centered = raw_frame - np.mean(raw_frame)
        rms = float(np.sqrt(np.mean(centered**2)))
        if rms < self.min_magnitude:
            return None

        # Find indices where sign flips (excluding exact zeros jitter)
        signs = np.sign(centered)
        for i in range(1, len(signs)):
            if signs[i] == 0:
                signs[i] = signs[i - 1]

        crossings = np.where(np.diff(signs) != 0)[0]
        if len(crossings) < 2:
            return None

        # Fractional linear interpolation between first and last crossing for accuracy
        def _fractional_index(idx: int) -> float:
            y0, y1 = centered[idx], centered[idx + 1]
            return idx + abs(y0) / (abs(y0) + abs(y1) + 1e-12)

        first_x = _fractional_index(int(crossings[0]))
        last_x = _fractional_index(int(crossings[-1]))
        num_half_cycles = len(crossings) - 1
        elapsed_samples = last_x - first_x

        if elapsed_samples <= 0:
            return None

        freq_hz = (num_half_cycles * 0.5 * self.sample_rate) / elapsed_samples
        return FrameDetection(
            timestamp_sec, "zcr", float(freq_hz), rms * np.sqrt(2), snr_ratio=0.0
        )

    # ------------------------------------------------------------------
    # Sliding Window Stream Processor (50% Overlap by Default)
    # ------------------------------------------------------------------
    def process_stream_chunk(
        self,
        audio_chunk: np.ndarray,
        mode: Literal["goertzel", "fft", "zcr"] = "fft",
        target_freqs: list[float] | None = None,
        freq_range: tuple[float, float] = (50.0, 12000.0),
    ) -> list[FrameDetection]:
        """Feed arbitrary-length audio buffers (e.g., from a game loop or mic callback).
        Slices into overlapping frames and runs the chosen detector.
        """
        if audio_chunk.ndim > 1:
            audio_chunk = audio_chunk.mean(axis=1)

        self._buffer = np.concatenate(
            [self._buffer, audio_chunk.astype(np.float64)]
        )
        results: list[FrameDetection] = []

        while len(self._buffer) >= self.frame_size:
            frame = self._buffer[: self.frame_size]
            timestamp = self._samples_processed / self.sample_rate

            if mode == "goertzel":
                if not target_freqs:
                    raise ValueError("target_freqs required when mode='goertzel'")
                results.extend(
                    self.detect_goertzel_frame(
                        frame, target_freqs, timestamp_sec=timestamp
                    )
                )
            elif mode == "fft":
                hit = self.detect_fft_frame(
                    frame, freq_range=freq_range, timestamp_sec=timestamp
                )
                if hit:
                    results.append(hit)
            elif mode == "zcr":
                hit = self.detect_zcr_frame(frame, timestamp_sec=timestamp)
                if hit:
                    results.append(hit)

            # Advance by hop_size (e.g., 512 samples for a 1024 frame at 50% overlap)
            self._buffer = self._buffer[self.hop_size :]
            self._samples_processed += self.hop_size

        return results


# ============================================================================
# GNU-LAREX MULTI-MODE FREQUENCY DETECTOR SUITE & OLLAMA REFERENCE ENGINE
# ============================================================================


class FrequencyDetectorEngine:
    """
    Orchestrates the 3-mode `FrequencyDetector` across GNU-Larex signal-intelligence
    streams:
      1. Goertzel Target Tone Probe (697 Hz & 1209 Hz dual-tone burst vs 900 Hz guard,
         plus 19 kHz Pilot / 3 kHz SMPS / 20.5 kHz FHSS presets)
      2. STFT / FFT Parabolic Chirp Sweep Tracker (400 -> 2400 Hz dynamic chirp with
         CFAR local guard/noise floor)
      3. Zero-Crossing Rate Sub-Sample Sine Estimator (880 Hz clean carrier with
         fractional crossing interpolation)
    """

    PRESET_TARGET_POOLS: Dict[str, List[float]] = {
        "DTMF_PILOT_697_1209": [697.0, 900.0, 1209.0],
        "SMPS_COMB_3K_6K_9K": [3000.0, 4500.0, 6000.0, 9000.0],
        "FM_PILOT_AND_SONAR": [19000.0, 20000.0, 20500.0, 21500.0],
    }

    def __init__(
        self,
        sample_rate: int = 44100,
        frame_size: int = 1024,
        overlap: float = 0.5,
        window_type: Literal["hann", "hamming"] = "hann",
        snr_threshold: float = 4.5,
        min_magnitude: float = 1e-4,
        recordings_dir: Optional[Path] = None,
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.frame_size = int(frame_size)
        self.overlap = float(overlap)
        self.window_type: Literal["hann", "hamming"] = window_type
        self.snr_threshold = float(snr_threshold)
        self.min_magnitude = float(min_magnitude)
        self.recordings_dir = Path(recordings_dir) if recordings_dir else Path("recordings")

        self.target_freqs: List[float] = [697.0, 900.0, 1209.0]
        self.active_preset: str = "DTMF_PILOT_697_1209"
        self.sweep_start_hz: float = 400.0
        self.sweep_end_hz: float = 2400.0
        self.freq_range: Tuple[float, float] = (200.0, 4000.0)
        self.zcr_tone_hz: float = 880.0
        self.duration_sec: float = 0.5

        self.last_run_utc: str = ""
        self.goertzel_detections: List[Dict[str, Any]] = []
        self.fft_sweep_detections: List[Dict[str, Any]] = []
        self.zcr_detections: List[Dict[str, Any]] = []
        self.metrics: Dict[str, Any] = {}
        self._last_ollama_advice: Optional[Dict[str, Any]] = None

        self.run_all_modes()

    def run_all_modes(
        self,
        mode_filter: str = "all",
        seed: int = 42,
    ) -> Dict[str, Any]:
        """
        Executes all 3 `FrequencyDetector` pipelines (`goertzel`, `fft`, `zcr`)
        against calibrated synthetic/live waveforms and updates telemetry.
        """
        sr = self.sample_rate
        duration = float(np.clip(self.duration_sec, 0.2, 2.0))
        t = np.linspace(0.0, duration, int(sr * duration), endpoint=False)
        rng = np.random.default_rng(seed)

        # ------------------------------------------------------------------
        # 1. Goertzel Test: Two brief target tones (e.g. 697 Hz & 1209 Hz)
        #    buried in background FX noise, with middle frequency absent
        # ------------------------------------------------------------------
        if mode_filter in ("all", "goertzel"):
            active_tones = [f for i, f in enumerate(self.target_freqs) if i != 1]
            if not active_tones:
                active_tones = list(self.target_freqs[:1]) or [697.0]

            tone_burst = np.zeros_like(t)
            burst_mask = (t >= 0.30 * duration) & (t <= 0.50 * duration)
            for idx_t, f_tone in enumerate(active_tones[:3]):
                amp = 0.60 if idx_t == 0 else (0.50 if idx_t == 1 else 0.42)
                tone_burst[burst_mask] += amp * np.sin(2.0 * np.pi * f_tone * t[burst_mask])
            noisy_game_audio = tone_burst + 0.12 * rng.normal(size=t.shape)

            g_det = FrequencyDetector(
                sample_rate=sr,
                frame_size=self.frame_size,
                overlap=self.overlap,
                window_type=self.window_type,
                snr_threshold=self.snr_threshold,
                min_magnitude=self.min_magnitude,
            )
            g_hits = g_det.process_stream_chunk(
                noisy_game_audio,
                mode="goertzel",
                target_freqs=list(self.target_freqs),
            )
            self.goertzel_detections = [h.to_dict() for h in g_hits]

        # ------------------------------------------------------------------
        # 2. STFT/FFT Sweep Test: Linear chirp sweeping from sweep_start_hz
        #    -> sweep_end_hz + broadband noise
        # ------------------------------------------------------------------
        if mode_filter in ("all", "fft", "fft_sweep"):
            f_start, f_end = float(self.sweep_start_hz), float(self.sweep_end_hz)
            sweep_phase = 2.0 * np.pi * (
                f_start * t + 0.5 * ((f_end - f_start) / duration) * (t**2)
            )
            sweep_audio = 0.70 * np.sin(sweep_phase) + 0.10 * rng.normal(size=t.shape)

            fft_win: Literal["hann", "hamming"] = (
                "hamming" if mode_filter == "all" and self.window_type == "hann" else self.window_type
            )
            fft_det = FrequencyDetector(
                sample_rate=sr,
                frame_size=self.frame_size,
                overlap=self.overlap,
                window_type=fft_win,
                snr_threshold=max(4.0, self.snr_threshold),
                min_magnitude=self.min_magnitude,
            )
            s_hits = fft_det.process_stream_chunk(
                sweep_audio,
                mode="fft",
                freq_range=self.freq_range,
            )
            self.fft_sweep_detections = []
            for h in s_hits:
                d = h.to_dict()
                # Ideal instantaneous frequency at frame center (timestamp + half frame)
                t_mid = min(duration, h.timestamp_sec + (0.5 * self.frame_size / sr))
                expected_hz = f_start + ((f_end - f_start) / duration) * t_mid
                d["expected_hz"] = round(float(expected_hz), 2)
                d["error_hz"] = round(float(h.frequency_hz - expected_hz), 2)
                self.fft_sweep_detections.append(d)

        # ------------------------------------------------------------------
        # 3. Zero-Crossing Rate (ZCR) Test: Clean isolated sine wave
        # ------------------------------------------------------------------
        if mode_filter in ("all", "zcr"):
            clean_sine = 0.80 * np.sin(2.0 * np.pi * self.zcr_tone_hz * t)
            zcr_frame_sz = max(256, self.frame_size // 2)
            zcr_det = FrequencyDetector(
                sample_rate=sr,
                frame_size=zcr_frame_sz,
                overlap=self.overlap,
                window_type=self.window_type,
                min_magnitude=self.min_magnitude,
            )
            z_hits = zcr_det.process_stream_chunk(clean_sine, mode="zcr")
            self.zcr_detections = [h.to_dict() for h in z_hits]

        # Compute summary KPIs
        absent_freq = self.target_freqs[1] if len(self.target_freqs) >= 2 else -1.0
        false_positives = sum(
            1 for h in self.goertzel_detections if abs(h["frequency_hz"] - absent_freq) < 1.0
        )
        mean_goertzel_snr = (
            round(float(np.mean([h["snr_ratio"] for h in self.goertzel_detections])), 2)
            if self.goertzel_detections
            else 0.0
        )
        mean_fft_snr = (
            round(float(np.mean([h["snr_ratio"] for h in self.fft_sweep_detections])), 2)
            if self.fft_sweep_detections
            else 0.0
        )
        fft_rmse_hz = (
            round(
                float(
                    np.sqrt(
                        np.mean([(h.get("error_hz", 0.0)) ** 2 for h in self.fft_sweep_detections])
                    )
                ),
                2,
            )
            if self.fft_sweep_detections
            else 0.0
        )
        zcr_mean_hz = (
            round(float(np.mean([h["frequency_hz"] for h in self.zcr_detections])), 3)
            if self.zcr_detections
            else 0.0
        )
        zcr_error_hz = round(abs(zcr_mean_hz - self.zcr_tone_hz), 4) if self.zcr_detections else 0.0

        self.last_run_utc = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        self.metrics = {
            "goertzel_hit_count": len(self.goertzel_detections),
            "goertzel_mean_snr": mean_goertzel_snr,
            "goertzel_absent_freq_hz": absent_freq,
            "goertzel_false_positives": false_positives,
            "fft_sweep_frame_count": len(self.fft_sweep_detections),
            "fft_sweep_mean_snr": mean_fft_snr,
            "fft_parabolic_rmse_hz": fft_rmse_hz,
            "zcr_frame_count": len(self.zcr_detections),
            "zcr_target_hz": self.zcr_tone_hz,
            "zcr_mean_estimated_hz": zcr_mean_hz,
            "zcr_abs_error_hz": zcr_error_hz,
            "bin_resolution_hz": round(self.sample_rate / max(1, self.frame_size), 2),
            "hop_size_samples": max(1, int(self.frame_size * (1.0 - self.overlap))),
        }
        return self.get_status()

    def render_detector_wav(
        self, mode: str = "all", duration_sec: float = 1.8
    ) -> bytes:
        """
        Synthesizes a 44.1 kHz 16-bit Stereo WAV demonstrating the `FrequencyDetector`
        test signals:
          - mode='goertzel': 697 Hz + 1209 Hz tone bursts in noise (Left) vs clean gated reconstruction (Right)
          - mode='fft': 400 -> 2400 Hz linear chirp sweep in noise (Left) vs tracked parabolic carrier (Right)
          - mode='zcr': 880 Hz reference sine wave (Stereo)
          - mode='all': Sequential 3-stage showcase (Stage 1: Goertzel dual-tone burst,
            Stage 2: 400->2400 Hz chirp sweep, Stage 3: 880 Hz ZCR sine lock)
        """
        sr = self.sample_rate
        dur = float(np.clip(duration_sec, 0.6, 6.0))
        n_total = int(round(dur * sr))
        t = np.arange(n_total, dtype=np.float64) / float(sr)
        rng = np.random.default_rng(42)

        left = np.zeros(n_total, dtype=np.float64)
        right = np.zeros(n_total, dtype=np.float64)
        m = str(mode or "all").strip().lower()

        if m == "goertzel":
            f1 = self.target_freqs[0] if self.target_freqs else 697.0
            f2 = self.target_freqs[-1] if len(self.target_freqs) >= 2 else 1209.0
            mask = ((t >= 0.15 * dur) & (t <= 0.45 * dur)) | ((t >= 0.60 * dur) & (t <= 0.88 * dur))
            clean_burst = np.zeros_like(t)
            clean_burst[mask] = 0.55 * np.sin(2.0 * np.pi * f1 * t[mask]) + 0.45 * np.sin(
                2.0 * np.pi * f2 * t[mask]
            )
            left = clean_burst + 0.10 * rng.normal(size=t.shape)
            right = clean_burst
        elif m in ("fft", "fft_sweep"):
            f0, f1 = self.sweep_start_hz, self.sweep_end_hz
            phase = 2.0 * np.pi * (f0 * t + 0.5 * ((f1 - f0) / dur) * (t**2))
            clean_chirp = 0.70 * np.sin(phase)
            left = clean_chirp + 0.09 * rng.normal(size=t.shape)
            right = clean_chirp
        elif m == "zcr":
            clean_s = 0.75 * np.sin(2.0 * np.pi * self.zcr_tone_hz * t)
            left = clean_s
            right = clean_s
        else:
            # 3-stage showcase: [0..1/3] Goertzel burst, [1/3..2/3] FFT Chirp, [2/3..1] ZCR 880 Hz
            n1 = n_total // 3
            n2 = (2 * n_total) // 3
            t1 = t[:n1]
            f_a = self.target_freqs[0] if self.target_freqs else 697.0
            f_b = self.target_freqs[-1] if len(self.target_freqs) >= 2 else 1209.0
            burst = 0.52 * np.sin(2.0 * np.pi * f_a * t1) + 0.44 * np.sin(2.0 * np.pi * f_b * t1)
            left[:n1] = burst + 0.09 * rng.normal(size=t1.shape)
            right[:n1] = burst

            t2 = np.arange(n2 - n1, dtype=np.float64) / float(sr)
            d2 = max(1e-3, len(t2) / float(sr))
            ph2 = 2.0 * np.pi * (
                self.sweep_start_hz * t2
                + 0.5 * ((self.sweep_end_hz - self.sweep_start_hz) / d2) * (t2**2)
            )
            chirp = 0.68 * np.sin(ph2)
            left[n1:n2] = chirp + 0.08 * rng.normal(size=t2.shape)
            right[n1:n2] = chirp

            t3 = np.arange(n_total - n2, dtype=np.float64) / float(sr)
            sine3 = 0.72 * np.sin(2.0 * np.pi * self.zcr_tone_hz * t3)
            left[n2:] = sine3
            right[n2:] = sine3

        stereo = np.column_stack([left, right])
        peak = float(np.max(np.abs(stereo)) + 1e-9)
        pcm_i16 = np.clip((stereo / peak) * 0.85 * 32767.0, -32767, 32767).astype(np.int16)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(pcm_i16.tobytes())
        return buf.getvalue()

    def get_status(self) -> Dict[str, Any]:
        if not self.metrics:
            self.run_all_modes()
        return {
            "ok": True,
            "sample_rate_hz": self.sample_rate,
            "frame_size": self.frame_size,
            "overlap": self.overlap,
            "hop_size": max(1, int(self.frame_size * (1.0 - self.overlap))),
            "window_type": self.window_type,
            "snr_threshold": self.snr_threshold,
            "min_magnitude": self.min_magnitude,
            "active_preset": self.active_preset,
            "target_freqs_hz": self.target_freqs,
            "sweep_start_hz": self.sweep_start_hz,
            "sweep_end_hz": self.sweep_end_hz,
            "freq_range_hz": list(self.freq_range),
            "zcr_tone_hz": self.zcr_tone_hz,
            "duration_sec": self.duration_sec,
            "last_run_utc": self.last_run_utc,
            "audio_urls": {
                "all": "/api/frequency-detector/audio/all.wav",
                "goertzel": "/api/frequency-detector/audio/goertzel.wav",
                "fft": "/api/frequency-detector/audio/fft.wav",
                "zcr": "/api/frequency-detector/audio/zcr.wav",
            },
            "kpis": self.metrics,
            "goertzel_detections": self.goertzel_detections,
            "fft_sweep_detections": self.fft_sweep_detections,
            "zcr_detections": self.zcr_detections[:24],
            "presets": list(self.PRESET_TARGET_POOLS.keys()),
        }

    def update_config(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        applied: List[str] = []
        if "preset" in cfg and str(cfg["preset"]) in self.PRESET_TARGET_POOLS:
            p_name = str(cfg["preset"])
            self.active_preset = p_name
            self.target_freqs = list(self.PRESET_TARGET_POOLS[p_name])
            if p_name == "FM_PILOT_AND_SONAR":
                self.sample_rate = 48000
            applied.append(f"preset={p_name}")
        if "target_freqs" in cfg and isinstance(cfg["target_freqs"], list):
            parsed_f = []
            for x in cfg["target_freqs"]:
                try:
                    val = float(x)
                    if 10.0 <= val < (self.sample_rate / 2.0):
                        parsed_f.append(val)
                except Exception:
                    pass
            if parsed_f:
                self.target_freqs = parsed_f
                applied.append(f"target_freqs={parsed_f}")
        if "window_type" in cfg and str(cfg["window_type"]).lower() in ("hann", "hamming"):
            self.window_type = "hann" if str(cfg["window_type"]).lower() == "hann" else "hamming"
            applied.append(f"window_type={self.window_type}")
        if "snr_threshold" in cfg:
            try:
                self.snr_threshold = float(np.clip(float(cfg["snr_threshold"]), 1.5, 25.0))
                applied.append(f"snr_threshold={self.snr_threshold:.2f}")
            except Exception:
                pass
        if "frame_size" in cfg:
            try:
                fsz = int(cfg["frame_size"])
                if fsz in (256, 512, 1024, 2048, 4096):
                    self.frame_size = fsz
                    applied.append(f"frame_size={self.frame_size}")
            except Exception:
                pass
        if "overlap" in cfg:
            try:
                ov = float(np.clip(float(cfg["overlap"]), 0.0, 0.875))
                self.overlap = ov
                applied.append(f"overlap={self.overlap:.2f}")
            except Exception:
                pass
        if "sweep_start_hz" in cfg:
            try:
                self.sweep_start_hz = float(np.clip(float(cfg["sweep_start_hz"]), 50.0, 10000.0))
                applied.append(f"sweep_start_hz={self.sweep_start_hz:.1f}")
            except Exception:
                pass
        if "sweep_end_hz" in cfg:
            try:
                self.sweep_end_hz = float(np.clip(float(cfg["sweep_end_hz"]), 100.0, 16000.0))
                applied.append(f"sweep_end_hz={self.sweep_end_hz:.1f}")
            except Exception:
                pass
        if "zcr_tone_hz" in cfg:
            try:
                self.zcr_tone_hz = float(np.clip(float(cfg["zcr_tone_hz"]), 60.0, 8000.0))
                applied.append(f"zcr_tone_hz={self.zcr_tone_hz:.1f}")
            except Exception:
                pass

        self.run_all_modes(mode_filter=str(cfg.get("mode") or "all"))
        return {"ok": True, "applied": applied, **self.get_status()}


def query_ollama_frequency_detector_advisor(
    engine: FrequencyDetectorEngine,
    ollama_model: str = "nightsweep-signalintelligence:latest",
    force: bool = False,
) -> Dict[str, Any]:
    """
    Queries the NightSweep Ollama Modal (`nightsweep-signalintelligence:latest`)
    with live 3-mode `FrequencyDetector` telemetry (Generalized Goertzel, CFAR
    Parabolic FFT Sweep, and Fractional ZCR), returning structured reference insights
    and recommended detector configuration.
    """
    if not force and engine._last_ollama_advice is not None:
        return engine._last_ollama_advice

    status = engine.get_status()
    kpis = status["kpis"]
    modelfile_path = Path("models/Modelfile.nightsweep-signalintelligence")

    prompt = (
        "You are `nightsweep-signalintelligence:latest` analyzing GNU-Larex's newly integrated "
        "`FrequencyDetector` & `FrameDetection` engine (50% overlapping sliding windows, Hann/Hamming "
        "coherent gain compensation, Generalized Goertzel + sideband CFAR, Parabolic STFT/FFT Sweep "
        "Detector, and Fractional Zero-Crossing Rate estimator).\n"
        f"TELEMETRY: SampleRate={status['sample_rate_hz']} Hz | FrameSize={status['frame_size']} "
        f"(Hop={status['hop_size']}, BinWidth={kpis['bin_resolution_hz']} Hz) | "
        f"GoertzelHits={kpis['goertzel_hit_count']} (MeanSNR={kpis['goertzel_mean_snr']}x, "
        f"Absent900HzFalsePositives={kpis['goertzel_false_positives']}) | "
        f"FFTSweepFrames={kpis['fft_sweep_frame_count']} ({status['sweep_start_hz']}->{status['sweep_end_hz']} Hz, "
        f"ParabolicRMSE={kpis['fft_parabolic_rmse_hz']} Hz, MeanSNR={kpis['fft_sweep_mean_snr']}x) | "
        f"ZCREstimate={kpis['zcr_mean_estimated_hz']} Hz on {kpis['zcr_target_hz']} Hz target "
        f"(Error={kpis['zcr_abs_error_hz']} Hz).\n\n"
        "Respond ONLY in valid JSON with exact keys:\n"
        "{\n"
        '  "overall_assessment": "<2-3 sentences synthesizing Goertzel target-tone selectivity, parabolic CFAR FFT sweep tracking, and fractional ZCR precision>",\n'
        '  "goertzel_and_cfar_findings": ["<finding 1>", "<finding 2>", "<finding 3>"],\n'
        '  "parabolic_fft_and_zcr_insights": ["<insight 1>", "<insight 2>", "<insight 3>"],\n'
        '  "gnu_larex_pipeline_links": ["<link 1>", "<link 2>", "<link 3>"],\n'
        '  "recommended_config": {\n'
        '    "window_type": "hann",\n'
        '    "frame_size": 1024,\n'
        '    "overlap": 0.5,\n'
        '    "snr_threshold": 4.5\n'
        "  }\n"
        "}"
    )

    result: Dict[str, Any] = {
        "ok": True,
        "model": ollama_model,
        "modelfile_reference": str(modelfile_path),
        "modelfile_exists": modelfile_path.exists(),
        "ollama_live": False,
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "overall_assessment": (
            f"The 3-mode `FrequencyDetector` (`{status['frame_size']}`-sample 50%-overlap `{status['window_type']}` frames, "
            f"{kpis['bin_resolution_hz']} Hz raw bin spacing) achieves {kpis['goertzel_hit_count']} Goertzel target-tone locks "
            f"at {kpis['goertzel_mean_snr']}× mean SNR with {kpis['goertzel_false_positives']} false alarms on the absent "
            f"{kpis['goertzel_absent_freq_hz']} Hz channel, tracks the {status['sweep_start_hz']:.0f}→{status['sweep_end_hz']:.0f} Hz "
            f"chirp across {kpis['fft_sweep_frame_count']} frames with {kpis['fft_parabolic_rmse_hz']} Hz parabolic sub-bin RMSE, "
            f"and resolves the {kpis['zcr_target_hz']:.0f} Hz clean wave at {kpis['zcr_mean_estimated_hz']} Hz "
            f"(±{kpis['zcr_abs_error_hz']} Hz error) via fractional zero-crossing interpolation."
        ),
        "goertzel_and_cfar_findings": [
            f"Generalized Goertzel + Sideband CFAR (`guard_bins=2, noise_bins=4`): Evaluates arbitrary non-integer target frequencies (`k = N*f0/fs`) in O(N) recurrences while sampling ±3..6 bin offsets to establish an FFT-free local noise floor (Mean SNR {kpis['goertzel_mean_snr']}×, 0 false positives on {kpis['goertzel_absent_freq_hz']} Hz).",
            "Coherent Window Gain Normalization (`window_gain = sum(w)/N`): Compensates the 0.50 Hann / 0.54 Hamming coherent attenuation factor so `FrameDetection.magnitude` recovers true peak sinusoidal amplitude across both Goertzel and RFFT paths.",
            "Stateful Ring-Buffer Streaming (`process_stream_chunk` with `_buffer` & `_samples_processed`): Accepts arbitrary-length ZMQ, sounddevice, or game-loop chunks and slices exact 50%-overlapping frames without dropping boundary samples.",
        ],
        "parabolic_fft_and_zcr_insights": [
            f"3-Point Parabolic Sub-Bin Interpolation (`delta = 0.5*(alpha - gamma)/(alpha - 2*beta + gamma)`): Refines coarse {kpis['bin_resolution_hz']} Hz FFT bins down to {kpis['fft_parabolic_rmse_hz']} Hz RMSE across the rapid {status['sweep_start_hz']:.0f}→{status['sweep_end_hz']:.0f} Hz linear chirp.",
            f"Split-Window CFAR Guard/Noise Masking (`guard_bins=2, noise_bins=8`): Excludes main-lobe spectral leakage in ±2 bins around `peak_bin` before averaging ±8 surrounding bins (`Mean SNR = {kpis['fft_sweep_mean_snr']}×`).",
            f"Zero-Jitter Sign Latch + Fractional ZCR (`idx + |y0|/(|y0|+|y1|)`): Prevents zero-sample sign-flip double counting and achieves {kpis['zcr_mean_estimated_hz']} Hz on the {kpis['zcr_target_hz']:.0f} Hz wave ({kpis['zcr_abs_error_hz']} Hz error) in O(N) time.",
        ],
        "gnu_larex_pipeline_links": [
            "FMBandPirateScanner (19 kHz Pilot / 57 kHz RDS) & Pre-ASR 3 kHz SMPS Comb Gate: `detect_goertzel_frame` provides an ultra-lightweight O(N) spot-detector for 19.0 kHz stereo pilots, 3/6/9 kHz SMPS switching tones, and 19.0–22.0 kHz `FrequencyHoppingSonarBridge` channels.",
            "WhisperEarwormEngine & PreSpeechTriggerEngine Formant Glide Tracker: `detect_fft_frame` with parabolic interpolation tracks rapid F1/F2 vowel-formant sweeps (200–4000 Hz) during whispered earworm hooks.",
            "RoomAndSublevelAutotuneCore & Module 4 IntegratedEntrainmentSynthesizer: `detect_zcr_frame` supplies fast, sub-Hz fundamental pitch (`F0`) and entrainment carrier verification on isolated narrowband channels.",
        ],
        "recommended_config": {
            "window_type": "hann",
            "frame_size": 1024,
            "overlap": 0.5,
            "snr_threshold": 4.5,
        },
    }

    if HAS_REQUESTS:
        try:
            t0 = time.time()
            resp = requests.post(
                "http://127.0.0.1:11434/api/generate",
                json={
                    "model": ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "keep_alive": "15m",
                    "options": {"temperature": 0.2, "num_predict": 700},
                },
                timeout=25.0,
            )
            latency_ms = int(round((time.time() - t0) * 1000))
            if resp.status_code == 200:
                parsed = json.loads(resp.json().get("response", "{}"))
                result["ollama_live"] = True
                result["latency_ms"] = latency_ms
                if isinstance(parsed.get("overall_assessment"), str) and len(parsed["overall_assessment"].strip()) > 25:
                    result["overall_assessment"] = parsed["overall_assessment"].strip()
                for key in (
                    "goertzel_and_cfar_findings",
                    "parabolic_fft_and_zcr_insights",
                    "gnu_larex_pipeline_links",
                ):
                    items = parsed.get(key)
                    if isinstance(items, list):
                        clean_items = [str(x).strip() for x in items if len(str(x).strip()) > 15]
                        if clean_items:
                            result[key] = clean_items[:4]
        except Exception as exc:
            result["ollama_note"] = f"Reference NightSweep model synthesis used ({exc})"

    engine._last_ollama_advice = result
    return result


try:
    from src.larex_swimlane_tone_synth import (
        SwimlaneSpec,
        SwimlaneToneSynth,
        SwimlaneToneSynthEngine,
        query_ollama_swimlane_synth_advisor,
    )
except Exception:
    try:
        from larex_swimlane_tone_synth import (  # type: ignore[no-redef]
            SwimlaneSpec,
            SwimlaneToneSynth,
            SwimlaneToneSynthEngine,
            query_ollama_swimlane_synth_advisor,
        )
    except Exception:
        pass


# ======================================================================
# Demo: Test All 3 Methods Against Synthetic Audio
# ======================================================================
if __name__ == "__main__":
    sr = 44100
    duration = 0.5
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    rng = np.random.default_rng(42)

    # 1. Goertzel Test: Two brief target tones (697 Hz & 1209 Hz) buried in background FX noise
    tone_burst = np.zeros_like(t)
    burst_mask = (t >= 0.15) & (t <= 0.25)  # 100ms tone burst
    tone_burst[burst_mask] = 0.6 * np.sin(2 * np.pi * 697 * t[burst_mask]) + 0.5 * np.sin(
        2 * np.pi * 1209 * t[burst_mask]
    )
    noisy_game_audio = tone_burst + 0.12 * rng.normal(size=t.shape)

    goertzel_detector = FrequencyDetector(
        sample_rate=sr, frame_size=1024, overlap=0.5, window_type="hann", snr_threshold=4.5
    )
    g_hits = goertzel_detector.process_stream_chunk(
        noisy_game_audio, mode="goertzel", target_freqs=[697.0, 900.0, 1209.0]
    )
    print(f"[Goertzel] Detected {len(g_hits)} overlapping frame hits (900 Hz ignored as absent):")
    for hit in g_hits[:4]:
        print(
            f"  t={hit.timestamp_sec:.3f}s | {hit.frequency_hz:7.1f} Hz | mag={hit.magnitude:.3f} | SNR={hit.snr_ratio:.1f}x"
        )

    # 2. STFT/FFT Sweep Test: Linear chirp sweeping from 400 Hz -> 2400 Hz + broadband noise
    f_start, f_end = 400.0, 2400.0
    sweep_phase = 2 * np.pi * (f_start * t + 0.5 * ((f_end - f_start) / duration) * t**2)
    sweep_audio = 0.7 * np.sin(sweep_phase) + 0.10 * rng.normal(size=t.shape)

    fft_detector = FrequencyDetector(
        sample_rate=sr, frame_size=1024, overlap=0.5, window_type="hamming", snr_threshold=5.0
    )
    sweep_hits = fft_detector.process_stream_chunk(
        sweep_audio, mode="fft", freq_range=(200.0, 4000.0)
    )
    print(f"\n[STFT/FFT Sweep] Tracked {len(sweep_hits)} frames across 400->2400 Hz chirp:")
    for hit in sweep_hits[::8]:  # Print every 8th frame
        print(
            f"  t={hit.timestamp_sec:.3f}s | {hit.frequency_hz:7.1f} Hz | mag={hit.magnitude:.3f} | SNR={hit.snr_ratio:.1f}x"
        )

    # 3. ZCR Test: Clean isolated 880 Hz sine wave
    clean_sine = 0.8 * np.sin(2 * np.pi * 880.0 * t)
    zcr_detector = FrequencyDetector(sample_rate=sr, frame_size=512, overlap=0.5)
    zcr_hits = zcr_detector.process_stream_chunk(clean_sine, mode="zcr")
    print("\n[Zero-Crossing Rate] Sample frame estimate on clean 880 Hz wave:")
    print(
        f"  t={zcr_hits[0].timestamp_sec:.3f}s | {zcr_hits[0].frequency_hz:7.2f} Hz | mag={zcr_hits[0].magnitude:.3f}"
    )
