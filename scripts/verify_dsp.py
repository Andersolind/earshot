#!/usr/bin/env python3
"""
GNU-Larex End-to-End DSP Verification & Calibration Benchmark
=============================================================
Simulates 16 seconds of 960 kSps RF micro-Doppler reflections (with static TX-RX
clutter, 15.0 BPM chest respiration, carotid pulse, and laryngeal subvocalization
bursts), passes them through every GNU-Larex DSP stage, and validates accuracy.
"""

from __future__ import annotations

import math
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.larex_dsp import (
    BiometricTrackerCore,
    IQClutterCancellerCore,
    InfrasonicSonifierCore,
    MasterExperienceOutputCore,
    PhaseVibrometerCore,
    PhysiologicalRadarSimulatorCore,
    SubvocSpectralEnhancerCore,
)


def run_verification() -> int:
    print("[Verify] Starting 16-second end-to-end RF Vibrometry & Subvocalization DSP test...")
    t0 = time.perf_counter()

    rf_fs = 960_000.0
    base_fs = 48_000.0
    breath_fs = 400.0
    decim_rf = int(rf_fs // base_fs)          # 20
    decim_breath = int(base_fs // breath_fs)  # 120

    sim = PhysiologicalRadarSimulatorCore(
        rf_samp_rate=rf_fs,
        baseband_rate=base_fs,
        rf_freq_mhz=915.0,
        resp_bpm=15.0,
        subvoc_um_rms=22.0,
        resp_um_peak=650.0,
    )
    clutter = IQClutterCancellerCore(alpha=0.01, mode=0)
    demod = PhaseVibrometerCore(samp_rate=base_fs, rf_freq_mhz=915.0)
    enhancer = SubvocSpectralEnhancerCore(samp_rate=base_fs, gate_thresh_db=-42.0, gain_db=18.0)
    sonifier = InfrasonicSonifierCore(samp_rate=base_fs, carrier_hz=168.0, vad_thresh_db=-42.0)
    bio = BiometricTrackerCore(samp_rate=breath_fs)

    with tempfile.TemporaryDirectory() as tmpdir:
        master = MasterExperienceOutputCore(
            samp_rate=base_fs,
            audio_mix_mode=0,
            breath_mix_gain=0.45,
            record_enable=True,
            recordings_dir=tmpdir,
        )

        # Simple FIR boxcar/Hann anti-aliasing kernels for standalone NumPy verification
        rf_kernel = np.hanning(decim_rf * 2)
        rf_kernel /= rf_kernel.sum()

        # Simple 1st-order high-pass (70 Hz) for subvocalization branch & low-pass (14 Hz) for infrasonic
        hp_alpha = math.exp(-2.0 * math.pi * 70.0 / base_fs)
        lp_infra_alpha = 1.0 - math.exp(-2.0 * math.pi * 14.0 / base_fs)
        lp_resp_alpha = 1.0 - math.exp(-2.0 * math.pi * 1.8 / breath_fs)

        hp_prev_x = 0.0
        hp_prev_y = 0.0
        infra_state = 0.0
        resp_state = 0.0

        total_seconds = 16
        chunks_per_sec = 20
        rf_chunk_len = int(rf_fs // chunks_per_sec)  # 48,000 RF samples = 50 ms

        vad_in_phrase = []
        vad_quiet = []

        for step in range(total_seconds * chunks_per_sec):
            iq_rf = sim.generate_iq(rf_chunk_len)
            # Decimate 960 kHz -> 48 kHz via block averaging (anti-aliased)
            iq_base = iq_rf.reshape(-1, decim_rf).mean(axis=1).astype(np.complex64)

            iq_centered = clutter.process(iq_base)
            disp_um = demod.process(iq_centered)

            # High-pass > 70 Hz for subvocalization branch
            sub_band = np.empty_like(disp_um)
            px, py = hp_prev_x, hp_prev_y
            for i in range(len(disp_um)):
                x_cur = float(disp_um[i])
                py = hp_alpha * (py + x_cur - px)
                px = x_cur
                sub_band[i] = py
            hp_prev_x, hp_prev_y = px, py

            enh_audio = enhancer.process(sub_band)

            # Infrasonic < 14 Hz branch
            infra_sig = np.empty_like(disp_um)
            iz = infra_state
            for i in range(len(disp_um)):
                iz += lp_infra_alpha * (float(disp_um[i]) - iz)
                infra_sig[i] = iz
            infra_state = iz

            breath_audio, vad = sonifier.process(infra_sig, enh_audio)

            # Decimate 48 kHz -> 400 Hz for respiration biometrics
            resp_dec = disp_um.reshape(-1, decim_breath).mean(axis=1)
            resp_clean = np.empty_like(resp_dec)
            rz = resp_state
            for i in range(len(resp_dec)):
                rz += lp_resp_alpha * (float(resp_dec[i]) - rz)
                resp_clean[i] = rz
            resp_state = rz

            _, bpm_vec, disp_vec = bio.process(resp_clean)
            master.process(enh_audio, breath_audio, disp_um, vad)

            t_sec = (step + 0.5) / chunks_per_sec
            phrase_mod = t_sec % 3.2
            if 0.8 <= phrase_mod <= 2.2:
                vad_in_phrase.append(float(np.mean(vad)))
            elif phrase_mod >= 2.8 or phrase_mod <= 0.2:
                vad_quiet.append(float(np.mean(vad)))

        master.close()
        wav_path = Path(master.active_wav_path)
        assert wav_path.exists(), "4-channel WAV recording was not created!"
        with wave.open(str(wav_path), "rb") as wf:
            n_ch = wf.getnchannels()
            sr = wf.getframerate()
            n_fr = wf.getnframes()

    dt = time.perf_counter() - t0
    est_bpm = bio.current_bpm
    est_disp = bio.current_disp_pp_um
    mean_vad_active = float(np.mean(vad_in_phrase))
    mean_vad_quiet = float(np.mean(vad_quiet))

    print(f"[Verify] 16.0 s of 960 kSps RF Radar DSP processed in {dt:.2f} s ({16.0/max(dt, 1e-6):.1f}x real-time!)")
    print(f"[Verify] Estimated Respiration Rate : {est_bpm:.2f} BPM  (Target: 15.00 BPM)")
    print(f"[Verify] Estimated Neck Excursion   : {est_disp:.1f} um P-P")
    print(f"[Verify] Subvocalization VAD        : active={mean_vad_active:.2f} vs quiet={mean_vad_quiet:.2f}")
    print(f"[Verify] Multi-Track WAV Verified   : {n_ch} channels @ {sr} Hz ({n_fr} frames)")

    assert 13.5 <= est_bpm <= 16.5, f"BPM out of expected tolerance: {est_bpm}"
    assert est_disp > 400.0, f"Displacement unexpectedly small: {est_disp}"
    assert mean_vad_active > mean_vad_quiet + 0.15, "Subvocalization VAD did not discriminate bursts!"
    assert n_ch == 4 and sr == 48_000 and n_fr == 16 * 48_000, "WAV header/frame mismatch!"

    print("[Verify] ALL DSP & RECORDING CHECKS PASSED SUCCESSFULLY.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_verification())
