#!/usr/bin/env python3
"""
Unit tests for PERSON_DELTA (Primary Room Owner) biometric speaker attribution,
persistent 271-D ResNet34-ONNX + VTL voiceprints across restarts, multi-speaker
separation, and live Departure -> Away -> Arrival voiceprint verification.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
for _p in (str(REPO_ROOT), str(SRC_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from larex_biometric_logger import (  # noqa: E402
    BiometricFusedVAD,
    BiometricSnapshot,
    BiometricSpeakerAttributor,
    BreathAndMouthExtractor,
)
from larex_presence_voicematch import PresenceVoiceMatchAndUltraMicEngine  # noqa: E402


def _synthesize_formant_voice(
    sr: int = 48_000,
    dur_sec: float = 1.65,
    f0_hz: float = 168.0,
    vtl_cm: float = 14.85,
    whisper: bool = False,
    seed: int = 42,
) -> np.ndarray:
    """Synthesizes a realistic multi-syllable glottal/whispered vocal-tract waveform for a physical VTL."""
    rng = np.random.default_rng(seed)
    n = int(round(sr * dur_sec))
    t = np.arange(n, dtype=np.float64) / sr

    # Quarter-wave vocal-tract resonances F1, F2, F3, F4 from physical VTL (cm)
    c_cm_s = 34_300.0
    f1 = (1.0 * c_cm_s) / (4.0 * vtl_cm)
    f2 = (3.0 * c_cm_s) / (4.0 * vtl_cm)
    f3 = (5.0 * c_cm_s) / (4.0 * vtl_cm)
    f4 = (7.0 * c_cm_s) / (4.0 * vtl_cm)

    syll_env = 0.25 + 0.75 * (np.sin(2.0 * np.pi * 3.4 * t) ** 2)
    if whisper:
        source = rng.normal(0.0, 0.35, n) * syll_env
    else:
        glottal = np.zeros(n, dtype=np.float64)
        max_harm = min(38, int((sr * 0.45) // max(f0_hz, 60.0)))
        vibrato = 1.0 + 0.008 * np.sin(2.0 * np.pi * 5.3 * t)
        phase = 2.0 * np.pi * f0_hz * np.cumsum(vibrato) / sr
        for h in range(1, max_harm + 1):
            glottal += (1.0 / (h ** 1.15)) * np.sin(h * phase + rng.uniform(0.0, 0.3))
        source = (glottal + rng.normal(0.0, 0.03, n)) * syll_env

    spec = np.fft.rfft(source)
    freqs = np.fft.rfftfreq(n, d=1.0 / sr)
    vt_transfer = (
        1.0 * np.exp(-0.5 * ((freqs - f1) / 85.0) ** 2)
        + 0.78 * np.exp(-0.5 * ((freqs - f2) / 140.0) ** 2)
        + 0.55 * np.exp(-0.5 * ((freqs - f3) / 210.0) ** 2)
        + 0.32 * np.exp(-0.5 * ((freqs - f4) / 290.0) ** 2)
        + 0.05
    )
    shaped = np.fft.irfft(spec * vt_transfer, n=n)
    peak = float(np.max(np.abs(shaped)) + 1e-9)
    return (0.25 * shaped / peak).astype(np.float32)


class TestPersonDelta(unittest.TestCase):
    def test_01_owner_enrolls_as_person_delta_and_persists_across_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            vp_path = Path(tmpdir) / "speaker_voiceprints.json"
            att1 = BiometricSpeakerAttributor(
                samp_rate=48_000.0,
                owner_speaker_id="PERSON_DELTA",
                storage_path=vp_path,
            )

            pcm_owner_1 = _synthesize_formant_voice(f0_hz=172.0, vtl_cm=14.85, seed=101)
            bio_owner_1 = BiometricSnapshot(
                resp_bpm=15.2,
                throat_disp_um_rms=28.0,
                f0_hz=172.0,
                vtl_cm=14.85,
                liveness_verified=True,
                band_role="VOICED_LARYNX",
            )
            spk1, sim1 = att1.identify_or_enroll(pcm_owner_1, bio_owner_1)
            self.assertEqual(spk1, "PERSON_DELTA", "First enrolled speaker must be PERSON_DELTA (Room Owner)")
            self.assertAlmostEqual(sim1, 1.0, places=3)
            self.assertTrue(vp_path.exists(), "speaker_voiceprints.json must be persisted immediately on enrollment")

            saved = json.loads(vp_path.read_text(encoding="utf-8"))
            self.assertIn("PERSON_DELTA", saved["prototypes"])
            self.assertEqual(len(saved["prototypes"]["PERSON_DELTA"]), att1.signature_dim)

            # Simulate full application restart with a brand-new BiometricSpeakerAttributor instance
            att2 = BiometricSpeakerAttributor(
                samp_rate=48_000.0,
                owner_speaker_id="PERSON_DELTA",
                storage_path=vp_path,
            )
            self.assertIn("PERSON_DELTA", att2._prototypes)

            pcm_owner_2 = _synthesize_formant_voice(f0_hz=169.0, vtl_cm=14.92, seed=202)
            bio_owner_2 = BiometricSnapshot(
                resp_bpm=15.8,
                throat_disp_um_rms=26.5,
                f0_hz=169.0,
                vtl_cm=14.92,
                liveness_verified=True,
                band_role="VOICED_LARYNX",
            )
            spk2, sim2 = att2.identify_or_enroll(pcm_owner_2, bio_owner_2)
            self.assertEqual(spk2, "PERSON_DELTA", "Owner voice after restart must match persisted PERSON_DELTA")
            self.assertGreaterEqual(sim2, att2.similarity_threshold)

            # Whispered utterance from same vocal tract (VTL ~ 14.9 cm) also attributes to PERSON_DELTA
            pcm_whisper = _synthesize_formant_voice(f0_hz=0.0, vtl_cm=14.88, whisper=True, dur_sec=0.95, seed=303)
            bio_whisper = BiometricSnapshot(
                resp_bpm=15.5,
                throat_disp_um_rms=11.0,
                f0_hz=0.0,
                vtl_cm=14.88,
                liveness_verified=True,
                band_role="UNVOICED_WHISPER",
            )
            spk_w, sim_w = att2.identify_or_enroll(pcm_whisper, bio_whisper)
            self.assertEqual(spk_w, "PERSON_DELTA", f"Owner whisper should stay on PERSON_DELTA (got {spk_w}, sim={sim_w})")

    def test_02_distinct_second_speaker_enrolls_as_person_alpha(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            vp_path = Path(tmpdir) / "speaker_voiceprints.json"
            att = BiometricSpeakerAttributor(
                samp_rate=48_000.0,
                owner_speaker_id="PERSON_DELTA",
                storage_path=vp_path,
            )

            # Speaker 1 (Owner -> PERSON_DELTA): VTL 14.75 cm, F0 235 Hz
            pcm_delta = _synthesize_formant_voice(f0_hz=235.0, vtl_cm=14.75, dur_sec=1.70, seed=11)
            bio_delta = BiometricSnapshot(resp_bpm=15.0, throat_disp_um_rms=30.0, f0_hz=235.0, vtl_cm=14.75)
            spk_a, _ = att.identify_or_enroll(pcm_delta, bio_delta)
            self.assertEqual(spk_a, "PERSON_DELTA")

            # Speaker 2 (Distinct baritone -> PERSON_ALPHA): VTL 20.2 cm, F0 92 Hz, noisy/breathy harmonic slope
            rng = np.random.default_rng(99)
            t = np.arange(int(48_000 * 1.75), dtype=np.float64) / 48_000.0
            # Square/pulse-like low baritone with sharp 92 Hz fundamental + low formants
            pulse = np.sign(np.sin(2.0 * np.pi * 92.0 * t)) * (0.3 + 0.7 * np.abs(np.sin(2.0 * np.pi * 1.9 * t)))
            spec = np.fft.rfft(pulse + rng.normal(0.0, 0.08, len(t)))
            freqs = np.fft.rfftfreq(len(t), d=1.0 / 48_000.0)
            low_vt = np.exp(-0.5 * ((freqs - 380.0) / 55.0) ** 2) + 0.4 * np.exp(-0.5 * ((freqs - 980.0) / 95.0) ** 2)
            pcm_other = (0.25 * np.fft.irfft(spec * low_vt, n=len(t))).astype(np.float32)
            bio_other = BiometricSnapshot(resp_bpm=11.0, throat_disp_um_rms=55.0, f0_hz=92.0, vtl_cm=20.2)

            spk_b, _ = att.identify_or_enroll(pcm_other, bio_other)
            self.assertEqual(spk_b, "PERSON_ALPHA", "Second distinct speaker must enroll into PERSON_ALPHA")

            sep = att.compute_separation_matrix()
            self.assertEqual(len(sep), 1)
            self.assertGreater(sep[0]["separation_pct"], 35.0)

    def test_03_presence_departure_sync_and_live_arrival_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pres = PresenceVoiceMatchAndUltraMicEngine(sample_rate=48_000, storage_dir=tmpdir)
            att = BiometricSpeakerAttributor(
                samp_rate=48_000.0,
                owner_speaker_id=pres.owner_speaker_id,
                storage_path=Path(tmpdir) / "speaker_voiceprints.json",
            )

            pcm_owner = _synthesize_formant_voice(f0_hz=178.0, vtl_cm=14.80, dur_sec=1.60, seed=55)
            bio_owner = BiometricSnapshot(resp_bpm=15.2, throat_disp_um_rms=32.0, f0_hz=178.0, vtl_cm=14.80)
            proto, sim = att.enroll_speaker_clip("PERSON_DELTA", pcm_owner, bio_owner, blend_weight=1.0)
            self.assertGreaterEqual(sim, 0.99)

            # Sync owner prototype & mark departure
            dep = pres.mark_departure(
                speaker_profile_summary={"vtl_cm": 14.80, "f0_hz": 178.0, "throat_disp_um": 32.0, "resp_bpm": 15.2},
                prototype_vec=proto,
                speaker_id="PERSON_DELTA",
            )
            self.assertIsNotNone(dep["prototype_vec"])
            self.assertEqual(len(dep["prototype_vec"]), att.signature_dim)

            # Fast-forward away clock by 65 seconds and feed live PERSON_DELTA utterance
            pres.departure_checkpoint["departed_epoch"] = time.time() - 65.0
            pcm_return = _synthesize_formant_voice(f0_hz=175.0, vtl_cm=14.86, dur_sec=1.60, seed=56)
            bio_return = BiometricSnapshot(resp_bpm=17.4, throat_disp_um_rms=35.0, f0_hz=175.0, vtl_cm=14.86)
            ret_sig, rankings = att.score_against_all(pcm_return, bio_return)
            self.assertEqual(rankings[0]["speaker_id"], "PERSON_DELTA")

            rec = {
                "timestamp_utc": "2026-11-14T07:15:00Z",
                "speaker": {
                    "speaker_id": "PERSON_DELTA",
                    "biometric_match_score": rankings[0]["similarity"],
                    "vtl_cm": 14.86,
                    "f0_hz": 175.0,
                },
                "vad_biometrics": {"band_role": "VOICED_LARYNX", "throat_disp_um_rms": 35.0, "resp_bpm": 17.4},
                "spatial": {"range_m": 0.68, "azimuth_deg": 32.0},
                "segment": {"raw_transcript": "One two three four."},
            }
            arr_comp = pres.record_live_utterance_match(
                rec,
                rankings=rankings,
                utterance_pcm=pcm_return,
                utterance_sig=ret_sig,
            )
            self.assertIsNotNone(arr_comp, "Auto-arrival verification must trigger when PERSON_DELTA speaks after >=45s away")
            self.assertEqual(arr_comp["verdict"], "VERIFIED_SAME_PERSON")
            self.assertTrue(arr_comp["verified_same_person"])
            self.assertGreaterEqual(arr_comp["voiceprint_similarity_pct"], 74.0)

    def test_04_person_delta_vad_and_mouth_profiles_active(self) -> None:
        vad = BiometricFusedVAD(samp_rate=48_000.0)
        vp = vad.set_speaker_vad_profile("PERSON_DELTA")
        self.assertEqual(vp["speaker_id"], "PERSON_DELTA")
        self.assertAlmostEqual(vp["low_ambient_whisper_mult"], 1.10, places=2)
        self.assertAlmostEqual(vp["hangover_ms"], 420.0, places=1)

        mouth = BreathAndMouthExtractor(sample_rate=48_000, block_size=2048)
        mp = mouth.set_speaker_profile("PERSON_DELTA")
        self.assertEqual(mp["speaker_id"], "PERSON_DELTA")


if __name__ == "__main__":
    unittest.main(verbosity=2)
