#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GNU-Larex :: Comprehensive All-Features Unit Test Suite
=======================================================
Verifies every DSP, Biometric VAD, Speaker Diarization, Forensic Ledger,
Presence/VoiceMatch, UltraMic 4-Mode Ambiance, Markov + PERSON_TYPIST,
Pre-Speech + Electronic/MEMS Characters, Silent Reading + Mid-Air Piggyback,
Closest Faint Focus, 4-Sensor Whisper Earworm, Mid-Air Talkback, 3-Tier Spatial
Radar, and Embedded Vue/Flask Web API feature in isolated temporary directories.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.larex_dsp import (
    HAS_GNURADIO,
    BiometricTrackerCore,
    BreathAndMouthExtractor,
    IQClutterCancellerCore,
    MasterExperienceOutputCore,
    PhaseVibrometerCore,
    PhysiologicalRadarSimulatorCore,
    RoomAndSublevelAutotuneCore,
    WhisperEarwormEngine,
)
if HAS_GNURADIO:
    from src.larex_dsp import SyncSDRFusionBlock

from src.larex_biometric_logger import (
    BiometricFusedVAD,
    BiometricSnapshot,
    BiometricSpeakerAttributor,
    ExtractedWord,
    FasterWhisperWordExtractor,
    ForensicWordLedger,
    OllamaNightSweepReconstructor,
    SpatialPositionEstimator,
)
from src.larex_delta_avatar import DeltaMotionAndAvatarEngine, query_ollama_delta_avatar_advisor
from src.larex_markov_typing import (
    TYPIST_SPEAKER_ID,
    AcousticTypingPersonEngine,
    SentenceMarkovDeltaTracker,
)
from src.larex_presence_voicematch import PresenceVoiceMatchAndUltraMicEngine
from src.larex_prespeech_electronics import (
    CELLPHONE_SPEAKER_ID,
    MEMS_SPEAKER_ID,
    ElectronicCharacterEngine,
    PreSpeechTriggerEngine,
)
from src.larex_reading_piggyback import (
    OTHER_ROOM_SPEAKER_ID,
    ClosestIdentityFocusEngine,
    MidAirPiggybackSublevelEngine,
    SilentReadingDetector,
)
from src.larex_talkback import EarwormTalkbackOrchestrator
from src.larex_web_backend import LarexAnalyticsEngine, create_larex_flask_app


class TestAllLarexFeatures(unittest.TestCase):
    """End-to-end deterministic unit tests covering all 10 GNU-Larex feature domains."""

    def test_01_core_dsp_and_passive_sdr_guard(self) -> None:
        """Coherent CW radar tracks ~15 BPM while passive non-CW SDR noise never phase-walks or leaks static."""
        # 1A. Coherent CW physiological radar simulation -> accurate BPM + high coherence
        sim = PhysiologicalRadarSimulatorCore(
            rf_samp_rate=960_000.0,
            baseband_rate=48_000.0,
            rf_freq_mhz=915.0,
            resp_bpm=15.0,
        )
        clutter = IQClutterCancellerCore(alpha=0.005, mode=0)
        vibro = PhaseVibrometerCore(samp_rate=48_000.0, rf_freq_mhz=915.0)
        tracker = BiometricTrackerCore(samp_rate=400.0)

        for _ in range(150):  # 15.0 seconds @ 96k RF samples / chunk (100 ms)
            iq_960k = sim.generate_iq(96_000)
            iq_48k = iq_960k.reshape(-1, 20).mean(axis=1).astype(np.complex64)
            centered = clutter.process(iq_48k)
            disp_um = vibro.process(centered)
            # Decimate 48 kHz -> 400 Hz (120x) for respiration tracker
            resp_400 = disp_um.reshape(-1, 120).mean(axis=1).astype(np.float32)
            tracker.process(resp_400)

        self.assertGreaterEqual(vibro.last_coherence, 0.70)
        self.assertAlmostEqual(tracker.current_bpm, 15.0, delta=1.5)

        # 1B. Passive non-CW SDR thermal RX noise (both centered 0+0j AND +0.32 virtual clutter offset)
        rng = np.random.default_rng(1234)
        passive_vibro = PhaseVibrometerCore(samp_rate=48_000.0, rf_freq_mhz=915.0)
        max_passive_um = 0.0
        for step in range(120):
            offset = 0.32 if step < 40 else 0.0
            iq_noise = (
                offset
                + rng.normal(0.0, 0.015, 4096)
                + 1j * rng.normal(0.0, 0.015, 4096)
            ).astype(np.complex64)
            d_um = passive_vibro.process(iq_noise)
            max_passive_um = max(max_passive_um, float(np.max(np.abs(d_um))))

        self.assertLess(passive_vibro.last_coherence, 0.35)
        self.assertLessEqual(max_passive_um, 45.0, "Passive RX noise must never phase-walk to millions of um!")

        # 1C. SyncSDRFusionBlock must mute `out_sub` completely when passive RX SDR has no CW carrier
        if HAS_GNURADIO:
            class _MockPassiveSDR:
                connected = True
                phase_coherence = 0.08

                @staticmethod
                def read_stream_disp_um(n: int) -> np.ndarray:
                    return np.full(n, 14.0, dtype=np.float32)

                @staticmethod
                def get_recent_samples(n: int) -> np.ndarray:
                    return np.full(n, 14.0, dtype=np.float32)

            fusion = SyncSDRFusionBlock(
                samp_rate=48_000.0,
                sensor_mode=1,
                rf_device_select=0,
                enable_cw_tx=False,
                shared_sdr_stream=_MockPassiveSDR(),
                shared_hackrf_stream=None,
            )
            in_mic = np.zeros(2048, dtype=np.float32)
            out_disp = np.ones(2048, dtype=np.float32)
            out_sub = np.ones(2048, dtype=np.float32)
            n_ret = fusion.work([in_mic], [out_disp, out_sub])
            self.assertEqual(n_ret, 2048)
            self.assertEqual(float(np.max(np.abs(out_sub))), 0.0)
            self.assertGreater(float(np.max(np.abs(out_disp))), 0.0)

    def test_02_room_sublevel_autotune_and_master_output(self) -> None:
        """RoomAndSublevelAutotuneCore calibrates floor/F0 and MasterExperienceOutputCore splits L:Room/R:Sublevel."""
        sr = 48_000
        autotune = RoomAndSublevelAutotuneCore(samp_rate=sr, pitch_autotune_strength=0.65)
        rng = np.random.default_rng(77)

        # Warm up 1.2s ambient floor so autotune_complete triggers
        for _ in range(30):
            hiss = rng.normal(0.0, 0.0005, 2048).astype(np.float32)
            autotune.process(hiss)
        self.assertTrue(autotune.autotune_complete)

        # Feed a clean 220 Hz (A3) voiced harmonic tone
        n_tot = sr  # 1.0s
        t = np.arange(n_tot, dtype=np.float64) / sr
        voiced = (
            0.03 * np.sin(2 * np.pi * 220.0 * t)
            + 0.02 * np.sin(2 * np.pi * 440.0 * t)
            + 0.012 * np.sin(2 * np.pi * 660.0 * t)
        ).astype(np.float32)
        for off in range(0, n_tot, 2048):
            autotune.process(voiced[off : off + 2048])
        self.assertAlmostEqual(autotune.current_f0_hz, 220.0, delta=12.0)

        # MasterExperienceOutputCore mode=4 (L: Room Audio | R: Sublevel) + talkback echo guard
        master = MasterExperienceOutputCore(
            samp_rate=sr,
            audio_mix_mode=4,
            breath_mix_gain=1.0,
            record_enable=False,
        )
        sub_sig = np.full(1024, 0.50, dtype=np.float32)
        room_sig = np.full(1024, 0.20, dtype=np.float32)
        disp_sig = np.zeros(1024, dtype=np.float32)
        left, right = master.process(sub_sig, room_sig, disp_sig)
        # Left = room(0.20) + 0.12*sub(0.06) = 0.26; Right = sub(0.50) + 0.12*room(0.024) = 0.524
        self.assertAlmostEqual(float(np.mean(left)), 0.26, places=2)
        self.assertAlmostEqual(float(np.mean(right)), 0.524, places=2)

        self.assertFalse(master.is_echo_suppressed)
        self.assertTrue(master.enqueue_talkback_pcm(np.full(2048, 0.1, dtype=np.float32)))
        self.assertTrue(master.is_echo_suppressed)

    def test_03_biometric_vad_idle_rejection_and_mouth_visemes(self) -> None:
        """BiometricFusedVAD never locks open on stationary room hiss + chest breathing, and segments real speech."""
        sr = 48_000
        vad = BiometricFusedVAD(samp_rate=sr, require_biometric_liveness=True)
        rng = np.random.default_rng(99)

        # 1. Stream 9.0 seconds of stationary room hiss while breathing silently: must produce ZERO false utterances!
        false_utterances = 0
        for _ in range(int((9.0 * sr) / 2048)):
            hiss = rng.normal(0.0, 0.0012, 2048).astype(np.float32)
            seg = vad.push_streaming_chunk(
                hiss,
                resp_bpm=15.2,
                throat_disp_um=1.8,
                mouth_cue={"mouth_openness": 0.02, "viseme": "REST_CLOSED", "silent_mouthing": False},
            )
            if seg is not None:
                false_utterances += 1

        self.assertEqual(false_utterances, 0, "Stationary room hiss must never trigger 7s runaway VAD segments!")
        self.assertFalse(vad.last_gate_open)
        self.assertAlmostEqual(vad._noise_floor_rms, 0.0012, delta=0.0010)

        # 2. Stream a 0.65s speech-like harmonic + fricative burst followed by 0.6s quiet hangover -> 1 clean segment
        completed_segments = []
        t_frame = np.arange(2048, dtype=np.float64) / sr
        for idx in range(16):
            speech_frame = (
                0.045 * np.sin(2 * np.pi * 165.0 * (t_frame + idx * 2048 / sr))
                + 0.028 * np.sin(2 * np.pi * 620.0 * (t_frame + idx * 2048 / sr))
                + 0.015 * np.sin(2 * np.pi * 1480.0 * (t_frame + idx * 2048 / sr))
                + rng.normal(0.0, 0.004, 2048)
            ).astype(np.float32)
            seg = vad.push_streaming_chunk(
                speech_frame,
                resp_bpm=15.2,
                throat_disp_um=24.0,
                mouth_cue={"mouth_openness": 0.55, "viseme": "MID_EH", "silent_mouthing": False},
            )
            if seg is not None:
                completed_segments.append(seg)

        for _ in range(18):
            quiet = rng.normal(0.0, 0.0010, 2048).astype(np.float32)
            seg = vad.push_streaming_chunk(quiet, resp_bpm=15.2, throat_disp_um=1.2)
            if seg is not None:
                completed_segments.append(seg)

        self.assertEqual(len(completed_segments), 1)

        # 3. Verify FasterWhisperWordExtractor hallucination phrase filter
        self.assertIn("for watching!", FasterWhisperWordExtractor.HALLUCINATION_PHRASES)
        self.assertIn("see you next time", FasterWhisperWordExtractor.HALLUCINATION_PHRASES)

        # 4. BreathAndMouthExtractor viseme classification (REST_CLOSED on quiet vs WIDE_AH on high-centroid formant)
        mouth = BreathAndMouthExtractor(sample_rate=sr, block_size=2048)
        z = np.zeros(2048, dtype=np.float32)
        st_quiet = mouth.push_streaming_chunks(z, z, f0_hz=0.0)
        self.assertEqual(st_quiet["viseme"], "REST_CLOSED")

        t_b = np.arange(2048, dtype=np.float64) / sr
        ah_burst = (0.35 * np.sin(2 * np.pi * 3400.0 * t_b)).astype(np.float32)
        st_open = mouth.push_streaming_chunks(ah_burst, z, f0_hz=150.0)
        self.assertIn(st_open["viseme"], ("WIDE_AH", "MID_EH"))
        self.assertGreater(st_open["mouth_openness"], 0.45)

    def test_04_speaker_diarization_person_delta_and_forensic_ledger(self) -> None:
        """First speaker enrolls as PERSON_DELTA, second distinct speaker as PERSON_ALPHA, and ledger triple-writes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vp_file = Path(tmpdir) / "speaker_voiceprints.json"
            attributor = BiometricSpeakerAttributor(
                samp_rate=48_000.0,
                similarity_threshold=0.78,
                storage_path=str(vp_file),
                owner_speaker_id="PERSON_DELTA",
            )
            t = np.arange(60_000, dtype=np.float64) / 48_000.0

            pcm_delta = (
                0.22 * np.sin(2 * np.pi * 125.0 * t) + 0.14 * np.sin(2 * np.pi * 460.0 * t)
            ).astype(np.float32)
            bio_delta = BiometricSnapshot(resp_bpm=15.0, throat_disp_um_rms=28.0, f0_hz=125.0, vtl_cm=18.2)
            spk1, sim1 = attributor.identify_or_enroll(pcm_delta, bio_delta)
            self.assertEqual(spk1, "PERSON_DELTA")
            self.assertEqual(sim1, 1.0)
            self.assertTrue(vp_file.exists())

            # Distinct high-pitched shorter-VTL voice (>= 1.25s) -> PERSON_ALPHA
            rng = np.random.default_rng(7)
            pcm_alpha = (
                0.18 * rng.normal(0.0, 0.3, len(t)) + 0.22 * np.sin(2 * np.pi * 285.0 * t) + 0.24 * np.sin(2 * np.pi * 2650.0 * t)
            ).astype(np.float32)
            bio_alpha = BiometricSnapshot(resp_bpm=21.5, throat_disp_um_rms=12.0, f0_hz=285.0, vtl_cm=13.2)
            spk2, _ = attributor.identify_or_enroll(pcm_alpha, bio_alpha)
            self.assertEqual(spk2, "PERSON_ALPHA")

            sep_matrix = attributor.compute_separation_matrix()
            self.assertEqual(len(sep_matrix), 1)
            self.assertGreater(sep_matrix[0]["separation_pct"], 5.0)

            # Ollama orthographic guardrail test
            self.assertTrue(
                OllamaNightSweepReconstructor._is_valid_orthographic_repair(
                    "check the perimeter signal", "Check the perimeter signal."
                )
            )
            self.assertFalse(
                OllamaNightSweepReconstructor._is_valid_orthographic_repair(
                    "see you next time", "cee yoo nxt tyme"
                )
            )

            # Triple-sink ForensicWordLedger test (.jsonl + .enc + SQLite WAL)
            ledger = ForensicWordLedger(output_dir=tmpdir, encrypt_fernet=True)
            words = [
                ExtractedWord(word="perimeter", start_sec=0.10, end_sec=0.48, probability=0.93),
                ExtractedWord(word="clear", start_sec=0.50, end_sec=0.82, probability=0.96),
            ]
            rec = ledger.log_utterance(
                speaker_id="PERSON_DELTA",
                speaker_similarity=0.98,
                start_sec=0.10,
                end_sec=0.82,
                words=words,
                reconstructed_transcript="Perimeter clear.",
                bio=bio_delta,
            )
            self.assertEqual(rec["speaker"]["speaker_id"], "PERSON_DELTA")
            self.assertEqual(len(rec["record_sha256"]), 64)
            self.assertTrue(ledger.jsonl_path.exists())
            self.assertTrue(ledger.db_path.exists())

            conn = sqlite3.connect(str(ledger.db_path))
            try:
                cnt_u = conn.execute("SELECT COUNT(*) FROM utterances").fetchone()[0]
                cnt_w = conn.execute("SELECT COUNT(*) FROM speaker_words").fetchone()[0]
            finally:
                conn.close()
                ledger._conn.close()
            self.assertEqual(cnt_u, 1)
            self.assertEqual(cnt_w, 2)

    def test_05_presence_voicematch_and_ultramic_4_modes(self) -> None:
        """Presence departure/away/arrival biometric diff + UNKNOWN_SUBVOC isolation + 4 UltraMic WAV modes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            eng = PresenceVoiceMatchAndUltraMicEngine(sample_rate=48_000, storage_dir=tmpdir)
            proto = np.ones(271, dtype=np.float64)
            proto /= np.linalg.norm(proto)

            dep = eng.mark_departure(
                speaker_profile_summary={"vtl_cm": 16.8, "f0_hz": 142.0, "throat_disp_um": 28.0, "resp_bpm": 15.0},
                prototype_vec=proto,
                speaker_id="PERSON_DELTA",
            )
            self.assertEqual(dep["speaker_id"], "PERSON_DELTA")
            self.assertEqual(eng.presence_state, "AWAY_MONITORING")

            # Trigger UNKNOWN_SUBVOC probe while away
            unk = eng.simulate_unknown_subvoc_probe()
            self.assertTrue(unk.get("id", "").startswith("usub-"))
            unk_wav = eng.get_unknown_subvoc_wav(unk["id"])
            self.assertEqual(unk_wav[:4], b"RIFF")

            # Verify Arrival comparison matches same person
            arr = eng.compare_arrival(
                arrival_summary={"speaker_id": "PERSON_DELTA", "vtl_cm": 16.9, "f0_hz": 144.0, "resp_bpm": 16.0},
                arrival_vec=proto,
            )
            self.assertTrue(arr["verified_same_person"])
            self.assertEqual(arr["verdict"], "VERIFIED_SAME_PERSON")
            self.assertEqual(eng.presence_state, "ARRIVED_COMPARED")

            # Verify all 4 UltraMic384K_EVO DSP listening modes produce valid RIFF WAV streams
            for mode in ("FULL_AMBIANCE", "SUBVOC_ISOLATOR", "ULTRASONIC_HETERODYNE", "DEPARTURE_ANOMALY_DIFF"):
                wav_bytes = eng.render_live_ambiance_wav(mode=mode, duration_sec=0.6)
                self.assertEqual(wav_bytes[:4], b"RIFF", f"Invalid WAV header for mode={mode}")
                self.assertGreater(len(wav_bytes), 10_000)

    def test_06_markov_order_promotion_and_person_typist_acoustics(self) -> None:
        """SentenceMarkovDeltaTracker promotes recurring hooks and AcousticTypingPersonEngine isolates PERSON_TYPIST."""
        tracker = SentenceMarkovDeltaTracker(delta_min_repeats=2)
        for idx in range(3):
            act = tracker.evaluate_sentence(
                {
                    "timestamp_utc": f"2026-11-14T02:00:0{idx}Z",
                    "speaker": {"speaker_id": "PERSON_DELTA", "f0_hz": 0.0, "vtl_cm": 16.8},
                    "vad_biometrics": {"band_role": "LOW_AMBIENT_WHISPER", "low_ambient_cued": True},
                    "segment": {
                        "raw_transcript": "check the perimeter signal now",
                        "ollama_reconstructed": "check the perimeter signal now",
                    },
                }
            )
            self.assertIn("markov_order", act)

        snap = tracker.get_snapshot()
        self.assertGreaterEqual(snap["kpis"]["total_sentences_evaluated"], 3)
        self.assertTrue(len(snap["kpis"]["current_earworm_delta"]) > 0)
        self.assertGreaterEqual(snap["kpis"]["promoted_chains_count"], 1)

        # Dedicated PERSON_TYPIST 48 kHz acoustic keystroke capture + voiced speech rejection
        typist = AcousticTypingPersonEngine(samp_rate=48_000.0, spatial_sector_lock=False, min_burst_keys=3)
        demo_pcm = typist.synthesize_demo_typing_pcm(
            pattern="ALPHA ALPHA SPACE ALPHA MOD ALPHA RET",
            wpm=72.0,
        )
        completed_burst = None
        for off in range(0, len(demo_pcm), 2048):
            res = typist.push_frame(demo_pcm[off : off + 2048], noise_floor_rms=0.0008, f0_hz=0.0)
            if res is not None:
                completed_burst = res
        if completed_burst is None:
            completed_burst = typist.flush_pending_burst()

        self.assertIsNotNone(completed_burst)
        assert completed_burst is not None
        self.assertGreaterEqual(len(completed_burst["keys"]), 3)
        self.assertGreater(completed_burst["wpm"], 10.0)

        # Voiced human speech (150 Hz F0) must NOT register as keystrokes
        before_keys = typist.total_keystrokes_captured
        t_v = np.arange(4096, dtype=np.float64) / 48_000.0
        voiced_chunk = (0.25 * np.sin(2 * np.pi * 150.0 * t_v)).astype(np.float32)
        typist.push_frame(voiced_chunk, noise_floor_rms=0.0008, f0_hz=150.0)
        self.assertEqual(typist.total_keystrokes_captured, before_keys)

    def test_07_prespeech_trigger_and_electronic_mems_characters(self) -> None:
        """PreSpeechTriggerEngine pre-hears earworms and ElectronicCharacterEngine separates CELLPHONE vs MEMS."""
        prespeech = PreSpeechTriggerEngine(sample_rate=48_000, block_size=2048)
        for mode in ("PRE_SPEECH_ONSET", "AMBIENT_DEVICE_PRECURSOR"):
            ev = prespeech.simulate_pre_speech_trigger(mode=mode)
            self.assertIn("id", ev)
            wav_b = prespeech.get_wav_bytes(ev["id"])
            self.assertIsNotNone(wav_b)
            assert wav_b is not None
            self.assertEqual(wav_b[:4], b"RIFF")

        elec = ElectronicCharacterEngine(samp_rate=48_000.0, enabled=True)
        for target_cid in (CELLPHONE_SPEAKER_ID, MEMS_SPEAKER_ID):
            pcm = elec.synthesize_character_pcm(target_cid)
            captured = []
            for off in range(0, len(pcm), 2048):
                captured.extend(elec.push_frame(pcm[off : off + 2048], noise_floor_rms=0.0010, f0_hz=0.0))
            if not captured:
                captured.extend(elec.flush_all())
            self.assertTrue(any(e["speaker_id"] == target_cid for e in captured), f"Expected {target_cid} capture")
            wav_dos, _ = elec.synthesize_audible_dossier_wav(target_cid)
            self.assertEqual(wav_dos[:4], b"RIFF")

    def test_08_silent_reading_piggyback_and_closest_focus(self) -> None:
        """SilentReadingDetector + ThreeState Reading Out-Loud + MidAirPiggyback + ClosestIdentityFocusEngine."""
        reader = SilentReadingDetector(sample_rate=48_000, block_size=2048)
        quiet = np.zeros(2048, dtype=np.float32)
        st = reader.detect_reading_state(quiet, quiet, quiet)
        self.assertTrue(st["is_physically_still"])

        piggy = MidAirPiggybackSublevelEngine(samp_rate=48_000.0, reading_detector=reader)
        # 1. Three-State Silent Reading Out-Loud simulation + WAV verification
        outloud_ev = piggy.three_state_router.simulate_three_state_reading_outloud(
            syllable_hz=4.5,
            custom_text="silent reading verification phrase",
        )
        self.assertIn("id", outloud_ev)
        outloud_wav = piggy.three_state_router.get_outloud_wav_bytes(outloud_ev["id"])
        self.assertEqual(outloud_wav[:4], b"RIFF")

        # 2. Mid-Air 19.2 kHz Piggybacked Other-Room Sublevel 3-Gate Capture
        pb_ev = piggy.simulate_piggyback_capture(with_silent_reading=False)
        self.assertEqual(pb_ev["speaker_id"], OTHER_ROOM_SPEAKER_ID)
        pb_wav = piggy.get_wav_bytes(pb_ev["id"])
        self.assertEqual(pb_wav[:4], b"RIFF")

        # 3. ClosestIdentityFocusEngine (`AUTO` / `PINNED` / `BOTH`) near-field boost vs far-field attenuation
        focus = ClosestIdentityFocusEngine(sample_rate=48_000)
        focus.update_from_targets(
            [
                {"speaker_id": "PERSON_ALPHA", "range_m": 0.52, "azimuth_deg": -40.0, "drr_db": 9.5},
                {"speaker_id": "PERSON_DELTA", "range_m": 0.78, "azimuth_deg": 36.0, "drr_db": 8.2},
            ]
        )
        faint = (np.random.default_rng(5).normal(0.0, 0.0025, 2048)).astype(np.float32)
        _, meta_in = focus.enhance_closest_faint_frame(
            faint, live_azimuth_deg=-40.0, live_range_m=0.52, noise_floor_rms=0.0010
        )
        self.assertTrue(meta_in["in_focus_zone"])
        self.assertGreater(meta_in["applied_gain_db"], 0.0)

        _, meta_out = focus.enhance_closest_faint_frame(
            faint, live_azimuth_deg=85.0, live_range_m=2.60, noise_floor_rms=0.0010
        )
        self.assertFalse(meta_out["in_focus_zone"])
        self.assertLessEqual(meta_out["applied_gain_db"], 0.0)

    def test_09_whisper_earworm_4sensor_and_midair_talkback(self) -> None:
        """WhisperEarwormEngine 4-sensor fusion/mirror and EarwormTalkbackOrchestrator opt-in whisper transceiver."""
        ew = WhisperEarwormEngine(sr=48_000, block_size=2048)
        ew.ingest_lexical_utterance(["alpha", "signal", "alpha", "signal", "alpha"])
        self.assertEqual(ew.predicted_lexical_word, "signal")

        rng = np.random.default_rng(21)
        t = np.arange(2048, dtype=np.float64) / 48_000.0
        sib_whisper = (0.08 * np.sin(2 * np.pi * 4600.0 * t) + rng.normal(0.0, 0.02, 2048)).astype(np.float32)
        z = np.zeros(2048, dtype=np.float32)
        tel = ew.process_whisper_stream(z, z, z, sib_whisper)
        self.assertTrue(tel["is_whispering"])
        mirror_pcm = ew.synthesize_whisper_mirror(1024, 48_000)
        self.assertEqual(len(mirror_pcm), 1024)

        with tempfile.TemporaryDirectory() as tmpdir:
            emitted_chunks = []
            tb = EarwormTalkbackOrchestrator(
                recordings_dir=Path(tmpdir),
                tx_audio_callback=lambda pcm: (emitted_chunks.append(len(pcm)) or True),
            )
            self.assertFalse(tb.talkback_enabled)

            # Armed queue when delta not yet confirmed and force_now=False
            res_armed = tb.send_user_chat_payload(
                "holding until earworm confirmed",
                require_delta_confirmation=True,
                force_now=False,
            )
            self.assertEqual(res_armed["action"], "ARMED_WAITING_FOR_EARWORM_DELTA")

            # Immediate transmit when force_now=True
            res_tx = tb.send_user_chat_payload(
                "testing mid air whisper link",
                target_speaker="PERSON_DELTA",
                force_now=True,
            )
            self.assertEqual(res_tx["action"], "TRANSMITTED")
            msg_id = res_tx["message"]["id"]
            wav_tb = tb.get_wav_bytes(msg_id)
            self.assertIsNotNone(wav_tb)
            assert wav_tb is not None
            self.assertEqual(wav_tb[:4], b"RIFF")
            self.assertEqual(len(emitted_chunks), 1)

    def test_10_spatial_estimator_and_embedded_web_api_endpoints(self) -> None:
        """SpatialPositionEstimator (Tiers 1-3) + Embedded Flask Web API end-to-end HTTP verification."""
        sr = 48_000.0
        sp = SpatialPositionEstimator(samp_rate=sr, mic_spacing_m=0.18)
        t = np.arange(12_000, dtype=np.float64) / sr
        burst = np.zeros_like(t)
        burst[1000:4200] = 0.25 * np.sin(2 * np.pi * 480.0 * t[:3200]) + 0.12 * np.sin(2 * np.pi * 1650.0 * t[:3200])
        burst_f32 = burst.astype(np.float32)
        bio = BiometricSnapshot(resp_bpm=15.0, throat_disp_um_rms=22.0, f0_hz=150.0, vtl_cm=16.9)

        # Tier 1 single-mic DRR/C50 + polar fix
        fix1 = sp.estimate_utterance_position(burst_f32, "PERSON_DELTA", bio, noise_floor_rms=0.0008)
        self.assertGreater(fix1.range_m, 0.20)
        self.assertIn(fix1.proximity_zone, ("NEAR_FIELD", "MID_FIELD", "FAR_FIELD"))

        # Tier 3 dual-mic stereo GCC-PHAT-Beta TDOA (delay right channel by 8 samples -> positive azimuth)
        right_delayed = np.roll(burst_f32, 8)
        az_deg, conf = sp.estimate_gcc_phat_azimuth(burst_f32, right_delayed)
        self.assertNotEqual(az_deg, 0.0)
        self.assertGreater(conf, 0.20)

        # Embedded Flask Web Backend HTTP endpoint verification in isolated tempdir
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = LarexAnalyticsEngine(
                flowgraph=None,
                bio_service=None,
                recordings_dir=Path(tmpdir),
            )
            app = create_larex_flask_app(engine)
            client = app.test_client()

            json_get_routes = [
                "/api/status",
                "/api/analytics/words-per-hour?hours=6&scope=active",
                "/api/spatial/radar?hours=6&scope=active",
                "/api/spatial/focus-closest",
                "/api/presence-voicematch/status",
                "/api/markov-typing/status",
                "/api/prespeech-electronics/status",
                "/api/reading-piggyback/status",
                "/api/talkback/status",
                "/api/self-improve/status",
                "/api/earworm/shared?hours=6",
            ]
            for route in json_get_routes:
                resp = client.get(route)
                self.assertEqual(resp.status_code, 200, f"GET {route} failed with {resp.status_code}")
                data = json.loads(resp.data.decode("utf-8"))
                self.assertIsInstance(data, dict)

            # POST endpoints: Departure -> Probe -> Arrival -> Typing Sim -> PreSpeech Sim -> Piggyback Sim
            r_dep = client.post("/api/presence-voicematch/depart", json={"speaker_id": "PERSON_DELTA"})
            self.assertEqual(r_dep.status_code, 200)

            r_prb = client.post("/api/presence-voicematch/probe", json={"probe_type": "UNKNOWN_SUBVOC"})
            self.assertEqual(r_prb.status_code, 200)

            r_arr = client.post("/api/presence-voicematch/arrive", json={"simulate": True})
            self.assertEqual(r_arr.status_code, 200)

            r_typ = client.post("/api/typing/simulate", json={"wpm": 65})
            self.assertEqual(r_typ.status_code, 200)

            r_pre = client.post("/api/prespeech-electronics/simulate", json={"target": "PRE_SPEECH_ONSET"})
            self.assertEqual(r_pre.status_code, 200)

            r_pig = client.post("/api/reading-piggyback/simulate", json={"mode": "PIGGYBACK"})
            self.assertEqual(r_pig.status_code, 200)

            # Playable WAV streaming routes
            r_wav = client.get("/api/ultramic/ambiance.wav?mode=SUBVOC_ISOLATOR&sec=0.8")
            self.assertEqual(r_wav.status_code, 200)
            self.assertEqual(r_wav.mimetype, "audio/wav")
            self.assertEqual(r_wav.data[:4], b"RIFF")

            r_ew_wav = client.get("/api/earworm/audio/PERSON_DELTA.wav?phrase=perimeter+clear&bpm=118")
            self.assertEqual(r_ew_wav.status_code, 200)
            self.assertEqual(r_ew_wav.data[:4], b"RIFF")

    def test_11_vad_motion_delta_avatar_and_cross_correlation(self) -> None:
        """VAD Motion co-gating + 0.5-4.0 Hz Delta Brainwave Avatar + Feelings x Predictability x Movement + Flask routes."""
        sr = 48_000
        rng = np.random.default_rng(314)

        # 1. VAD Motion co-validation vs. <55 Hz non-vocal footstep/thump rejection
        vad = BiometricFusedVAD(samp_rate=sr, require_biometric_liveness=True)
        for _ in range(20):
            vad.push_streaming_chunk(rng.normal(0.0, 0.0010, 2048).astype(np.float32), resp_bpm=15.0)

        t_f = np.arange(2048, dtype=np.float64) / sr
        # Low-frequency 32 Hz non-vocal footstep thump with high motion_cue MUST NOT open speech gate
        thump = (0.08 * np.sin(2 * np.pi * 32.0 * t_f)).astype(np.float32)
        gate_thump, _, snap_thump = vad.evaluate_frame(
            thump,
            resp_bpm=15.0,
            throat_disp_um=2.0,
            motion_cue={"vad_motion_score": 0.85, "vad_motion_weight": 0.30, "movement_state": "LATERAL_PACING"},
        )
        self.assertFalse(gate_thump, "Non-vocal <55 Hz footstep thumps must never trigger VAD Motion!")
        self.assertEqual(snap_thump.movement_state, "LATERAL_PACING")

        # Faint moving whisper with vocal formant/fricative energy gets boosted by motion_cue
        faint_whisper = (
            0.0032 * np.sin(2 * np.pi * 1650.0 * t_f)
            + 0.0028 * np.sin(2 * np.pi * 3800.0 * t_f)
            + rng.normal(0.0, 0.0012, 2048)
        ).astype(np.float32)
        _, conf_no_mov, _ = vad.evaluate_frame(faint_whisper, resp_bpm=15.0, throat_disp_um=4.0)
        _, conf_with_mov, snap_mov = vad.evaluate_frame(
            faint_whisper,
            resp_bpm=15.0,
            throat_disp_um=4.0,
            motion_cue={
                "vad_motion_score": 0.72,
                "vad_motion_weight": 0.30,
                "movement_state": "APPROACHING",
                "kinetic_hangover_bonus_ms": 80.0,
            },
        )
        self.assertGreater(conf_with_mov, conf_no_mov)
        self.assertEqual(snap_mov.movement_state, "APPROACHING")

        # 2. DeltaMotionAndAvatarEngine 0.5-4.0 Hz envelope, 5 movement regimes, probes & cross-correlations
        with tempfile.TemporaryDirectory() as tmpdir:
            da = DeltaMotionAndAvatarEngine(sample_rate=sr, storage_dir=tmpdir)
            self.assertEqual(da.classify_movement_state(0.2, 0.3, 0.05), "STILL_ANCHORED")
            self.assertEqual(da.classify_movement_state(-9.5, 1.0, 0.1), "APPROACHING")
            self.assertEqual(da.classify_movement_state(9.5, 1.0, 0.1), "RETREATING")
            self.assertEqual(da.classify_movement_state(1.5, 14.0, 0.1), "LATERAL_PACING")
            self.assertEqual(da.classify_movement_state(2.2, 0.5, 0.1), "MICRO_SWAY")

            # Stream 7.0 seconds of a 1.56 Hz slow-modulated whisper envelope -> verify 0.5-4.0 Hz Delta lock
            n_tot = sr * 7
            t_all = np.arange(n_tot, dtype=np.float64) / sr
            env_1p5 = 0.55 + 0.45 * np.sin(2 * np.pi * 1.56 * t_all)
            whisper_mod = (env_1p5 * (0.04 * np.sin(2 * np.pi * 1800.0 * t_all))).astype(np.float32)
            for off in range(0, n_tot, 4096):
                da.push_realtime_frame(
                    whisper_mod[off : off + 4096],
                    live_range_m=0.75,
                    live_azimuth_deg=25.0,
                    radial_vel_cms=-6.2,
                    resp_bpm=14.2,
                )
            self.assertGreaterEqual(da.live_delta_peak_hz, 0.5)
            self.assertLessEqual(da.live_delta_peak_hz, 4.0)
            self.assertGreater(da.live_delta_power_ratio, 0.25)

            # Run all 3 interactive probes and verify Earworm <-> Movement associations & cross-correlations
            for probe_mode, expected_state in (
                ("DELTA_CALM_WHISPER", "STILL_ANCHORED"),
                ("PACING_EARWORM", "LATERAL_PACING"),
                ("APPROACHING_SUBVOC", "APPROACHING"),
            ):
                res = da.simulate_delta_motion_probe(mode=probe_mode, speaker_id="PERSON_DELTA")
                self.assertTrue(res["ok"])
                self.assertEqual(res["association"]["movement_state"], expected_state)

            snap = da.get_status()
            cc = snap["cross_correlations"]
            for k in ("feelings_vs_predictability", "feelings_vs_movement", "predictability_vs_movement"):
                self.assertGreaterEqual(cc[k]["r"], -1.0)
                self.assertLessEqual(cc[k]["r"], 1.0)
            self.assertEqual(len(snap["delta_wave"]["waveform_64"]), 64)
            self.assertGreaterEqual(len(snap["recent_associations"]), 3)

            wav_delta = da.render_delta_avatar_wav("PERSON_DELTA", phrase="deep delta reset", duration_sec=1.4)
            self.assertEqual(wav_delta[:4], b"RIFF")
            self.assertGreater(len(wav_delta), 40_000)

            # 3. Verify Flask /api/delta-avatar/* and /api/ollama/delta-avatar routes
            engine = LarexAnalyticsEngine(flowgraph=None, bio_service=None, recordings_dir=Path(tmpdir))
            app = create_larex_flask_app(engine)
            client = app.test_client()

            r_st = client.get("/api/delta-avatar/status")
            self.assertEqual(r_st.status_code, 200)
            st_json = json.loads(r_st.data.decode("utf-8"))
            self.assertTrue(st_json["ok"])
            self.assertIn("cross_correlations", st_json)

            r_cfg = client.post(
                "/api/delta-avatar/config",
                json={"vad_motion_weight": 0.28, "kinetic_hangover_bonus_ms": 85.0},
            )
            self.assertEqual(r_cfg.status_code, 200)
            self.assertGreaterEqual(len(json.loads(r_cfg.data.decode("utf-8"))["applied"]), 2)

            r_sim = client.post(
                "/api/delta-avatar/simulate",
                json={"mode": "PACING_EARWORM", "speaker_id": "PERSON_DELTA"},
            )
            self.assertEqual(r_sim.status_code, 200)
            self.assertEqual(
                json.loads(r_sim.data.decode("utf-8"))["association"]["movement_state"],
                "LATERAL_PACING",
            )

            r_dwav = client.get("/api/delta-avatar/audio/PERSON_DELTA.wav?phrase=delta+calm+whisper")
            self.assertEqual(r_dwav.status_code, 200)
            self.assertEqual(r_dwav.mimetype, "audio/wav")
            self.assertEqual(r_dwav.data[:4], b"RIFF")

            r_oll = client.post("/api/ollama/delta-avatar", json={"force": False})
            self.assertEqual(r_oll.status_code, 200)
            oll_json = json.loads(r_oll.data.decode("utf-8"))
            self.assertTrue(oll_json["ok"])
            self.assertIn("recommended_config", oll_json)

    def test_12_nightsweep_data_intelligence_and_hallucination_firewall(self) -> None:
        """NightSweep Sec. 1/9/11/13/26/27/31 Hallucination Firewall, Orphan Merger, Phase Clamp & Feature Lab."""
        from src.larex_data_intelligence import (
            clamp_physiological_um,
            consolidate_ephemeral_speaker,
            is_corpus_hallucination,
        )

        # 1. Hallucination firewall catches YouTube outro phrases while keeping real whispers
        self.assertTrue(FasterWhisperWordExtractor.is_hallucination_transcript("See you the next video!", 0.55, 0.94))
        self.assertTrue(FasterWhisperWordExtractor.is_hallucination_transcript("Comment and subscribe!", 0.62, 1.1))
        self.assertTrue(is_corpus_hallucination("You very much.", avg_prob=0.58, dur_sec=3.9))
        self.assertFalse(FasterWhisperWordExtractor.is_hallucination_transcript("Check the stairwell sensor now.", 0.65, 1.4))

        # 2. Orphan cluster consolidation maps PERSON_13 -> core occupant & clamps >500 um phase drift
        mapped_spk, conf = consolidate_ephemeral_speaker("PERSON_13", vtl_cm=14.55, azimuth_deg=-44.0, f0_hz=153.0)
        self.assertEqual(mapped_spk, "PERSON_ALPHA")
        self.assertGreater(conf, 0.70)
        self.assertLessEqual(clamp_physiological_um(133_265_341.3), 500.0)

        # 3. ForensicWordLedger clamps outlier throat_disp_um_rms and /api/forensics/* + /api/ollama/data-intelligence work
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = ForensicWordLedger(output_dir=tmpdir, encrypt_fernet=False)
            words_clean = [
                ExtractedWord("check", 0.1, 0.4, 0.88),
                ExtractedWord("sensor", 0.4, 0.8, 0.85),
                ExtractedWord("now", 0.8, 1.1, 0.90),
            ]
            words_halluc = [
                ExtractedWord("see", 0.1, 0.3, 0.40),
                ExtractedWord("you", 0.3, 0.5, 0.50),
                ExtractedWord("next", 0.5, 0.7, 0.48),
                ExtractedWord("video", 0.7, 0.95, 0.62),
            ]
            bio_spike = BiometricSnapshot(resp_bpm=14.8, throat_disp_um_rms=9_500_000.0, f0_hz=155.0, vtl_cm=14.6)
            rec1 = ledger.log_utterance("PERSON_13", 0.92, 0.0, 1.1, words_clean, "Check sensor now.", bio_spike)
            self.assertLessEqual(rec1["vad_biometrics"]["throat_disp_um_rms"], 500.0)
            ledger.log_utterance("PERSON_DELTA", 0.91, 2.0, 2.95, words_halluc, "See you the next video!", bio_spike)
            ledger.close()

            engine = LarexAnalyticsEngine(flowgraph=None, bio_service=None, recordings_dir=Path(tmpdir))
            app = create_larex_flask_app(engine)
            client = app.test_client()

            r_for = client.get("/api/forensics/corpus?refresh=1")
            self.assertEqual(r_for.status_code, 200)
            f_json = json.loads(r_for.data.decode("utf-8"))
            self.assertEqual(f_json["summary"]["total_utterances"], 2)
            self.assertEqual(f_json["summary"]["hallucination_utterances"], 1)
            self.assertEqual(f_json["summary"]["orphan_ephemeral_clusters"], 1)

            wph = engine.compute_words_per_hour(hours=6.0, scope="all")
            self.assertEqual(wph["kpis"]["total_utterances"], 1, "Scrubber must hide hallucinated utterance from WPH")
            self.assertIn("PERSON_ALPHA", wph["speaker_ids"], "PERSON_13 must consolidate into PERSON_ALPHA")

            r_cfg = client.post("/api/forensics/config", json={"active_entrainment_band": "THETA"})
            self.assertEqual(r_cfg.status_code, 200)
            self.assertEqual(json.loads(r_cfg.data.decode("utf-8"))["config"]["active_entrainment_band"], "THETA")

            r_di = client.get("/api/ollama/data-intelligence")
            self.assertEqual(r_di.status_code, 200)
            di_json = json.loads(r_di.data.decode("utf-8"))
            self.assertTrue(di_json["ok"])
            self.assertGreaterEqual(len(di_json["feature_cards"]), 7)

    def test_13_nextgen_kalman_lomb_scargle_evt_binaural_and_biomacro(self) -> None:
        """Next-Gen NightSweep Sec. 1/9/11/13/27/31/40: Ultrasonic/SMPS Comb Gate, EVT Post-Cluster, 3σ Kalman + Lomb-Scargle, 3D Virtual Mics & Hilbert SSB WAV."""
        from src.larex_data_intelligence import (
            BreathBioMacroController,
            HybridNeuralVTLPostClusterer,
            LombScargleAndKalmanTracker,
            UltrasonicAndAcousticOODPreGate,
            VirtualPersonalMicAndBinauralEngine,
        )

        # 1. Ultrasonic (>14.2 kHz) + 3 kHz SMPS Comb Filter & Pre-ASR Syllabic Modulation Context Gate
        sr = 48_000.0
        t = np.arange(24_000, dtype=np.float64) / sr
        sig_comb = (
            0.15 * np.sin(2.0 * np.pi * 450.0 * t)
            + 0.40 * np.sin(2.0 * np.pi * 3000.0 * t)
            + 0.35 * np.sin(2.0 * np.pi * 18_500.0 * t)
        ).astype(np.float32)
        y_filt, meta = UltrasonicAndAcousticOODPreGate.filter_ultrasonic_and_smps_comb(sig_comb, samp_rate=sr)
        self.assertEqual(len(y_filt), len(sig_comb))
        self.assertTrue(meta["smps_comb_notched"])

        # Syllabic speech envelope (5 Hz modulation) vs flat white hiss at 16 kHz
        rng = np.random.default_rng(99)
        t16 = np.arange(16_000, dtype=np.float64) / 16_000.0
        syl_speech = ((1.0 + 0.85 * np.sin(2.0 * np.pi * 5.0 * t16)) * np.sin(2.0 * np.pi * 620.0 * t16)).astype(np.float32)
        flat_hiss = rng.normal(0.0, 0.05, 16_000).astype(np.float32)
        ctx_speech = UltrasonicAndAcousticOODPreGate.evaluate_pre_asr_context(syl_speech)
        ctx_hiss = UltrasonicAndAcousticOODPreGate.evaluate_pre_asr_context(flat_hiss)
        self.assertFalse(ctx_speech["is_stationary_noise_ood"])
        self.assertTrue(ctx_hiss["is_stationary_noise_ood"])

        # 2. Hybrid Neural + VTL Live Prototype Post-Clusterer merges PERSON_07 into PERSON_ALPHA
        v_alpha = np.ones(32, dtype=np.float64)
        v_alpha /= np.linalg.norm(v_alpha)
        v_eph = v_alpha.copy()
        protos = {"PERSON_ALPHA": v_alpha, "PERSON_07": v_eph}
        counts = {"PERSON_ALPHA": 10, "PERSON_07": 2}
        merged = HybridNeuralVTLPostClusterer.recluster_live_prototypes(protos, counts)
        self.assertEqual(merged.get("PERSON_07"), "PERSON_ALPHA")
        self.assertNotIn("PERSON_07", protos)
        self.assertEqual(counts["PERSON_ALPHA"], 12)

        # 3. 3-Sigma Innovation-Gated Kalman Phase Tracker & Lomb-Scargle Respiratory Periodogram
        um_series = [24.0, 26.5, 25.0, 133_265_341.3, 27.0, 25.5, 950_000.0, 26.0]
        kal = LombScargleAndKalmanTracker.run_innovation_gated_kalman(um_series)
        self.assertEqual(kal["spikes_gated_count"], 2)
        self.assertLess(kal["kalman_rms_um"], 60.0)
        self.assertLessEqual(kal["peak_kalman_um"], 500.0)

        t_irr = np.cumsum(rng.uniform(0.6, 2.2, 80)).tolist()
        y_resp = [15.0 + 1.8 * math.sin(2.0 * math.pi * (15.0 / 60.0) * ti) for ti in t_irr]
        ls = LombScargleAndKalmanTracker.compute_lomb_scargle_periodogram(t_irr, y_resp)
        self.assertEqual(len(ls["spectrum"]), 24)
        self.assertGreater(ls["rsa_coherence"], 0.50)

        # 4. Hilbert SSB Binaural WAV + 3D Virtual Personal Mics + Breath BioMacro Trigger Routes
        wav_ssb = VirtualPersonalMicAndBinauralEngine.render_hilbert_ssb_binaural_wav("THETA", "PERSON_DELTA", 1.6)
        self.assertEqual(wav_ssb[:4], b"RIFF")

        bm = BreathBioMacroController()
        bm.push_phase_or_trigger(phase="INHALE")
        bm.push_phase_or_trigger(phase="INHALE")
        res_bm = bm.push_phase_or_trigger(phase="EXHALE")
        self.assertTrue(res_bm["triggered"])
        self.assertEqual(res_bm["macro"]["command"], "SPOTLIGHT_CLOSEST")

        with tempfile.TemporaryDirectory() as tmpdir:
            engine = LarexAnalyticsEngine(flowgraph=None, bio_service=None, recordings_dir=Path(tmpdir))
            app = create_larex_flask_app(engine)
            client = app.test_client()

            r_ssb = client.get("/api/forensics/binaural.wav?band=THETA&speaker_id=PERSON_GAMMA&sec=1.5")
            self.assertEqual(r_ssb.status_code, 200)
            self.assertEqual(r_ssb.mimetype, "audio/wav")
            self.assertEqual(r_ssb.data[:4], b"RIFF")

            r_trig = client.post("/api/forensics/biomacro/trigger", json={"command": "THETA_WHISPER_BOOST"})
            self.assertEqual(r_trig.status_code, 200)
            trig_json = json.loads(r_trig.data.decode("utf-8"))
            self.assertTrue(trig_json["triggered"])
            self.assertEqual(trig_json["forensics"]["config"]["active_entrainment_band"], "THETA")

            r_bio = client.get("/api/forensics/biometrics-and-sublevel")
            self.assertEqual(r_bio.status_code, 200)
            bio_json = json.loads(r_bio.data.decode("utf-8"))
            self.assertTrue(bio_json["ok"])
            self.assertIn("voice_biometrics", bio_json)

            r_dig = client.get("/api/forensics/sublevel-digitalize.wav?utterance_id=9780")
            self.assertEqual(r_dig.status_code, 200)
            self.assertEqual(r_dig.mimetype, "audio/wav")
            self.assertEqual(r_dig.data[:4], b"RIFF")

            r_hap = client.get("/api/forensics/haptic-sentences")
            self.assertEqual(r_hap.status_code, 200)
            hap_json = json.loads(r_hap.data.decode("utf-8"))
            self.assertTrue(hap_json["ok"])
            self.assertIn("sentences", hap_json)

            r_hap_wav = client.get("/api/forensics/haptic-sentence.wav?win_id=5")
            self.assertEqual(r_hap_wav.status_code, 200)
            self.assertEqual(r_hap_wav.mimetype, "audio/wav")
            self.assertEqual(r_hap_wav.data[:4], b"RIFF")

    def test_14_integrated_entrainment_synthesizer_and_ten_nightsweep_features(self) -> None:
        """Module 4 IntegratedEntrainmentSynthesizer phase continuity + 10 NightSweep Features + Modal Reference API."""
        from src.larex_data_intelligence import IntegratedEntrainmentSynthesizer

        # 1. Verify exact cross-block phase continuity of IntegratedEntrainmentSynthesizer
        synth_two = IntegratedEntrainmentSynthesizer(sample_rate=44100)
        self.assertEqual(synth_two.sample_rate, 44100)
        self.assertEqual(synth_two.phase_left, 0.0)
        self.assertEqual(synth_two.phase_right, 0.0)
        self.assertEqual(synth_two.phase_lfo, 0.0)

        blk1 = synth_two.generate_modulated_block(1024, carrier_freq=210.0, target_brainwave_freq=2.4, mod_depth=0.4, base_amplitude=0.5)
        blk2 = synth_two.generate_modulated_block(1024, carrier_freq=210.0, target_brainwave_freq=2.4, mod_depth=0.4, base_amplitude=0.5)
        self.assertEqual(blk1.shape, (1024, 2))
        self.assertEqual(blk1.dtype, np.float32)

        synth_one = IntegratedEntrainmentSynthesizer(sample_rate=44100)
        blk_full = synth_one.generate_modulated_block(2048, carrier_freq=210.0, target_brainwave_freq=2.4, mod_depth=0.4, base_amplitude=0.5)
        np.testing.assert_allclose( np.vstack([blk1, blk2]), blk_full, atol=1e-5 )

        wav_bytes = synth_two.render_wav_bytes(duration_sec=1.0, carrier_freq=210.0, target_brainwave_freq=2.4)
        self.assertEqual(wav_bytes[:4], b"RIFF")

        # 2. Verify all 10 new NightSweep features & Dossier Modal Reference via Flask endpoints
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = LarexAnalyticsEngine(flowgraph=None, bio_service=None, recordings_dir=Path(tmpdir))
            app = create_larex_flask_app(engine)
            client = app.test_client()

            r_tf = client.get("/api/forensics/ten-features?refresh=1")
            self.assertEqual(r_tf.status_code, 200)
            tf_json = json.loads(r_tf.data.decode("utf-8"))
            self.assertTrue(tf_json["ok"])
            ten = tf_json["ten_new_features"]
            for required_key in (
                "cardio_vocal_bcg_pwtt",
                "cyclostationary_clock_skew",
                "bistatic_cross_ambiguity",
                "wakita_vocal_tract_inversion",
                "conformal_asr_calibrator",
                "mimo_wpe_dereverberation",
                "lombard_spectral_tilt",
                "dispersive_flexural_keystroke",
                "ultrasonic_saccade_sonar",
                "merkle_zk_audit_verifier",
                "integrated_entrainment_synth",
                "fm_band_pirate_scanner",
                "fhss_sonar_bridge",
                "frequency_detector",
                "swimlane_tone_synth",
            ):
                self.assertIn(required_key, ten, f"Missing {required_key} in ten_new_features")

            r_es_wav = client.get("/api/forensics/entrainment-synth.wav?carrier_freq=210&target_brainwave_freq=2.4&mod_depth=0.4&sec=1.0")
            self.assertEqual(r_es_wav.status_code, 200)
            self.assertEqual(r_es_wav.mimetype, "audio/wav")
            self.assertEqual(r_es_wav.data[:4], b"RIFF")

            r_sh = client.get("/api/earworm/shared?hours=6")
            self.assertEqual(r_sh.status_code, 200)
            sh_json = json.loads(r_sh.data.decode("utf-8"))
            self.assertIn("ten_new_features_summary", sh_json)

    def test_15_fm_band_pirate_scanner_and_ollama_modal_reference(self) -> None:
        """FMBandPirateScanner 88-108 MHz superheterodyne sweep + 19 kHz Pilot / 57 kHz RDS + Flask & Ollama Modal routes."""
        from src.larex_fm_pirate_scanner import FMBandPirateScanner, query_ollama_fm_pirate_advisor

        with tempfile.TemporaryDirectory() as tmpdir:
            scanner = FMBandPirateScanner(driver="rtlsdr", sample_rate=2.0e6, gain=35.0, recordings_dir=Path(tmpdir))
            self.assertEqual(scanner.if_fs, 200_000.0)
            self.assertEqual(len(scanner.if_taps), 101)

            stations = scanner.run_full_band_sweep(output_file=str(Path(tmpdir) / "fm_scan_results.json"))
            self.assertEqual(len(stations), 10)
            flagged = [s for s in stations if s.get("flags")]
            self.assertEqual(len(flagged), 4)
            self.assertTrue(all("MISSING_RDS" in s["flags"] for s in flagged))
            self.assertTrue(any(any(f.startswith("OVER_DEVIATION") for f in s["flags"]) for s in flagged))
            self.assertTrue(all("carson_bandwidth_khz" in s for s in stations))

            wav_fm = scanner.render_station_demod_wav(freq_mhz=91.5, duration_sec=1.0)
            self.assertEqual(wav_fm[:4], b"RIFF")

            adv = query_ollama_fm_pirate_advisor(scanner, force=False)
            self.assertTrue(adv["ok"])
            self.assertIn("pirate_transmitter_findings", adv)

            engine = LarexAnalyticsEngine(flowgraph=None, bio_service=None, recordings_dir=Path(tmpdir))
            app = create_larex_flask_app(engine)
            client = app.test_client()

            r_st = client.get("/api/fm-scanner/status")
            self.assertEqual(r_st.status_code, 200)
            st_json = json.loads(r_st.data.decode("utf-8"))
            self.assertTrue(st_json["ok"])
            self.assertGreaterEqual(st_json["kpis"]["total_stations"], 8)

            r_wav = client.get("/api/fm-scanner/audio/91.5.wav?sec=1.0")
            self.assertEqual(r_wav.status_code, 200)
            self.assertEqual(r_wav.mimetype, "audio/wav")
            self.assertEqual(r_wav.data[:4], b"RIFF")

            r_oll = client.post("/api/ollama/fm-scanner", json={"force": False})
            self.assertEqual(r_oll.status_code, 200)
            self.assertTrue(json.loads(r_oll.data.decode("utf-8"))["ok"])

    def test_16_fhss_sonar_bridge_and_ollama_modal_reference(self) -> None:
        """FrequencyHoppingSonarBridge 19-22 kHz 7-channel FHSS + modulo-2pi phase continuity + I/Q 50 Hz LPF + Flask & Ollama Modal routes."""
        from src.larex_fhss_sonar_bridge import FrequencyHoppingSonarBridge, query_ollama_fhss_sonar_advisor

        with tempfile.TemporaryDirectory() as tmpdir:
            bridge = FrequencyHoppingSonarBridge(sample_rate=48_000, chunk_size=1024)
            self.assertEqual(bridge.fs, 48_000)
            self.assertEqual(bridge.chunk_size, 1024)
            self.assertEqual(len(bridge.frequency_pool), 7)

            # 1. Verify coprime LCG visits all 7 ultrasonic channels (19.0-22.0 kHz) without degeneracy
            sched = bridge.get_hop_schedule(steps=7)
            visited_freqs = {h["frequency_hz"] for h in sched}
            self.assertEqual(visited_freqs, set(bridge.frequency_pool))
            self.assertEqual(sched[0]["frequency_hz"], 20_500.0)

            # 2. Verify modulo-2pi phase_accumulator continuity and stateful I/Q 50 Hz Butterworth demodulation
            res_chunk = bridge.process_transceiver_chunk()
            self.assertEqual(len(res_chunk["tx_wave"]), 1024)
            self.assertGreaterEqual(bridge.phase_accumulator, 0.0)
            self.assertLess(bridge.phase_accumulator, 2.0 * math.pi)
            self.assertGreater(res_chunk["quadrature_iq_energy"], 0.008)
            self.assertTrue(res_chunk["target_active"])
            self.assertGreater(res_chunk["muscle_displacement_um"], 0.0)

            # 3. Verify 7-hop sequence sweep and 48 kHz stereo WAV synthesis (Ch0=19-22 kHz carrier, Ch1=het+demod)
            sweep = bridge.run_hop_sequence_sweep(num_hops=7, reset_index=True)
            self.assertEqual(len(sweep), 7)
            wav_fhss = bridge.render_fhss_sonar_wav(duration_sec=1.4)
            self.assertEqual(wav_fhss[:4], b"RIFF")
            self.assertGreater(len(wav_fhss), 100_000)

            # 4. Verify NightSweep Ollama Modal advisor
            adv = query_ollama_fhss_sonar_advisor(bridge, force=False)
            self.assertTrue(adv["ok"])
            self.assertIn("fhss_security_and_lcg_findings", adv)
            self.assertIn("recommended_config", adv)

            # 5. Verify Flask /api/fhss-sonar/*, /api/ollama/fhss-sonar, and Dossier Modal Reference
            ledger = ForensicWordLedger(output_dir=tmpdir, encrypt_fernet=False)
            ledger.log_utterance(
                "PERSON_DELTA",
                0.94,
                0.0,
                1.2,
                [ExtractedWord("ultrasonic", 0.1, 0.5, 0.91), ExtractedWord("sonar", 0.5, 1.0, 0.93)],
                "Ultrasonic sonar.",
                BiometricSnapshot(resp_bpm=14.6, throat_disp_um_rms=24.0, f0_hz=152.0, vtl_cm=16.8),
            )
            ledger.close()

            engine = LarexAnalyticsEngine(flowgraph=None, bio_service=None, recordings_dir=Path(tmpdir))
            app = create_larex_flask_app(engine)
            client = app.test_client()

            r_st = client.get("/api/fhss-sonar/status")
            self.assertEqual(r_st.status_code, 200)
            st_json = json.loads(r_st.data.decode("utf-8"))
            self.assertTrue(st_json["ok"])
            self.assertEqual(len(st_json["frequency_pool_hz"]), 7)
            self.assertAlmostEqual(st_json["kpis"]["entropy_bits_per_hop"], 2.81, places=1)

            r_hop = client.post("/api/fhss-sonar/hop", json={"sweep": False})
            self.assertEqual(r_hop.status_code, 200)
            self.assertTrue(json.loads(r_hop.data.decode("utf-8"))["ok"])

            r_cfg = client.post(
                "/api/fhss-sonar/config",
                json={"lcg_multiplier": 3, "reflection_threshold": 0.008, "lpf_cutoff_hz": 50.0},
            )
            self.assertEqual(r_cfg.status_code, 200)
            self.assertGreaterEqual(len(json.loads(r_cfg.data.decode("utf-8"))["applied"]), 2)

            r_wav = client.get("/api/fhss-sonar/audio/hop_stream.wav?sec=1.2")
            self.assertEqual(r_wav.status_code, 200)
            self.assertEqual(r_wav.mimetype, "audio/wav")
            self.assertEqual(r_wav.data[:4], b"RIFF")

            r_oll = client.post("/api/ollama/fhss-sonar", json={"force": False})
            self.assertEqual(r_oll.status_code, 200)
            self.assertTrue(json.loads(r_oll.data.decode("utf-8"))["ok"])

            r_sh = client.get("/api/earworm/shared?hours=6")
            self.assertEqual(r_sh.status_code, 200)
            sh_json = json.loads(r_sh.data.decode("utf-8"))
            self.assertIn("fhss_sonar_bridge", sh_json["ten_new_features_summary"])
            self.assertIn("fhss_sonar_bridge", sh_json["speakers"]["PERSON_DELTA"]["nightsweep_modal_reference"])

    def test_17_frequency_detector_and_ollama_modal_reference(self) -> None:
        """FrequencyDetector (Goertzel + CFAR Parabolic FFT + Fractional ZCR) + Modelfile + Flask & Ollama Modal routes."""
        from src.larex_frequency_detector import (
            FrameDetection,
            FrequencyDetector,
            FrequencyDetectorEngine,
            query_ollama_frequency_detector_advisor,
        )

        sr = 44100
        duration = 0.5
        t = np.linspace(0, duration, int(sr * duration), endpoint=False)
        rng = np.random.default_rng(42)

        # 1. Goertzel Test: 697 Hz & 1209 Hz tone burst in noise, 900 Hz absent
        tone_burst = np.zeros_like(t)
        burst_mask = (t >= 0.15) & (t <= 0.25)
        tone_burst[burst_mask] = 0.6 * np.sin(2 * np.pi * 697 * t[burst_mask]) + 0.5 * np.sin(
            2 * np.pi * 1209 * t[burst_mask]
        )
        noisy_game_audio = tone_burst + 0.12 * rng.normal(size=t.shape)

        g_det = FrequencyDetector(
            sample_rate=sr, frame_size=1024, overlap=0.5, window_type="hann", snr_threshold=4.5
        )
        g_hits = g_det.process_stream_chunk(
            noisy_game_audio, mode="goertzel", target_freqs=[697.0, 900.0, 1209.0]
        )
        self.assertGreaterEqual(len(g_hits), 10)
        self.assertIsInstance(g_hits[0], FrameDetection)
        detected_freqs = {h.frequency_hz for h in g_hits}
        self.assertIn(697.0, detected_freqs)
        self.assertIn(1209.0, detected_freqs)
        self.assertNotIn(900.0, detected_freqs)

        # 2. STFT/FFT Sweep Test: Linear chirp 400 -> 2400 Hz with Hamming + parabolic sub-bin interpolation
        f_start, f_end = 400.0, 2400.0
        sweep_phase = 2 * np.pi * (f_start * t + 0.5 * ((f_end - f_start) / duration) * t**2)
        sweep_audio = 0.7 * np.sin(sweep_phase) + 0.10 * rng.normal(size=t.shape)
        fft_det = FrequencyDetector(
            sample_rate=sr, frame_size=1024, overlap=0.5, window_type="hamming", snr_threshold=5.0
        )
        sweep_hits = fft_det.process_stream_chunk(sweep_audio, mode="fft", freq_range=(200.0, 4000.0))
        self.assertGreaterEqual(len(sweep_hits), 35)
        self.assertLess(sweep_hits[0].frequency_hz, 600.0)
        self.assertGreater(sweep_hits[-1].frequency_hz, 2100.0)

        # 3. ZCR Test: Clean 880 Hz sine wave with fractional zero-crossing interpolation
        clean_sine = 0.8 * np.sin(2 * np.pi * 880.0 * t)
        zcr_det = FrequencyDetector(sample_rate=sr, frame_size=512, overlap=0.5)
        zcr_hits = zcr_det.process_stream_chunk(clean_sine, mode="zcr")
        self.assertGreaterEqual(len(zcr_hits), 40)
        self.assertAlmostEqual(zcr_hits[0].frequency_hz, 880.0, delta=0.5)

        # 4. Verify FrequencyDetectorEngine, Modelfile reference, and Flask / Ollama endpoints
        self.assertTrue(Path("models/Modelfile.nightsweep-signalintelligence").exists())
        with tempfile.TemporaryDirectory() as tmpdir:
            fd_engine = FrequencyDetectorEngine(recordings_dir=Path(tmpdir))
            adv = query_ollama_frequency_detector_advisor(fd_engine, force=False)
            self.assertTrue(adv["ok"])
            self.assertTrue(adv["modelfile_exists"])
            self.assertIn("goertzel_and_cfar_findings", adv)

            ledger = ForensicWordLedger(output_dir=tmpdir, encrypt_fernet=False)
            ledger.log_utterance(
                "PERSON_DELTA",
                0.95,
                0.0,
                1.1,
                [ExtractedWord("goertzel", 0.1, 0.5, 0.92), ExtractedWord("sweep", 0.5, 1.0, 0.94)],
                "Goertzel sweep.",
                BiometricSnapshot(resp_bpm=14.8, throat_disp_um_rms=22.0, f0_hz=150.0, vtl_cm=16.8),
            )
            ledger.close()

            engine = LarexAnalyticsEngine(flowgraph=None, bio_service=None, recordings_dir=Path(tmpdir))
            app = create_larex_flask_app(engine)
            client = app.test_client()

            r_st = client.get("/api/frequency-detector/status")
            self.assertEqual(r_st.status_code, 200)
            st_json = json.loads(r_st.data.decode("utf-8"))
            self.assertTrue(st_json["ok"])
            self.assertEqual(st_json["kpis"]["goertzel_false_positives"], 0)

            r_run = client.post("/api/frequency-detector/run", json={"mode": "all"})
            self.assertEqual(r_run.status_code, 200)
            self.assertTrue(json.loads(r_run.data.decode("utf-8"))["ok"])

            r_cfg = client.post(
                "/api/frequency-detector/config",
                json={"window_type": "hamming", "snr_threshold": 4.5, "preset": "SMPS_COMB_3K_6K_9K"},
            )
            self.assertEqual(r_cfg.status_code, 200)
            self.assertGreaterEqual(len(json.loads(r_cfg.data.decode("utf-8"))["applied"]), 2)

            r_wav = client.get("/api/frequency-detector/audio/all.wav?sec=1.2")
            self.assertEqual(r_wav.status_code, 200)
            self.assertEqual(r_wav.mimetype, "audio/wav")
            self.assertEqual(r_wav.data[:4], b"RIFF")

            r_oll = client.post("/api/ollama/frequency-detector", json={"force": False})
            self.assertEqual(r_oll.status_code, 200)
            self.assertTrue(json.loads(r_oll.data.decode("utf-8"))["ok"])

            r_sh = client.get("/api/earworm/shared?hours=6")
            self.assertEqual(r_sh.status_code, 200)
            sh_json = json.loads(r_sh.data.decode("utf-8"))
            self.assertIn("frequency_detector", sh_json["ten_new_features_summary"])
            self.assertIn("frequency_detector", sh_json["speakers"]["PERSON_DELTA"]["nightsweep_modal_reference"])

    def test_18_swimlane_tone_synth_and_closed_loop_goertzel(self) -> None:
        """SwimlaneToneSynth & SwimlaneSpec (3ms 1-pole gain ramp, modulo-2pi phase continuity, context manager) + closed-loop Goertzel + Flask & Ollama Modal routes."""
        from src.larex_frequency_detector import FrequencyDetector
        from src.larex_swimlane_tone_synth import (
            SwimlaneSpec,
            SwimlaneToneSynth,
            SwimlaneToneSynthEngine,
            query_ollama_swimlane_synth_advisor,
        )

        sr = 44100
        lanes = [
            SwimlaneSpec(lane_id=0, center_hz=440.0, label="Lane 0", speaker_id="PERSON_ALPHA"),
            SwimlaneSpec(lane_id=1, center_hz=697.0, label="Lane 1", speaker_id="PERSON_DELTA"),
            SwimlaneSpec(lane_id=2, center_hz=1209.0, label="Lane 2", speaker_id="DEVICE_CELLPHONE"),
        ]

        # 1. Verify SwimlaneToneSynth context manager, set_lane_tone, 3ms 1-pole ramp, and modulo-2pi phase continuity
        with SwimlaneToneSynth(lanes=lanes, sample_rate=sr) as synth:
            self.assertEqual(synth.sample_rate, sr)
            self.assertEqual(len(synth.freqs), 3)
            synth.set_lane_tone(0, active=True, volume=0.25)
            synth.set_lane_tone(1, active=False)
            synth.set_lane_tone(2, active=True, volume=0.20)

            out_block_1 = np.zeros((256, 1), dtype=np.float32)
            synth._audio_out_callback(out_block_1, 256, None, None)
            # First sample starts smoothly from 0 via 1-pole ramp (no step discontinuity click)
            self.assertLess(abs(float(out_block_1[0, 0])), 0.02)
            self.assertGreater(float(np.max(np.abs(out_block_1))), 0.15)
            self.assertTrue(all(0.0 <= float(p) < 2.0 * math.pi for p in synth._phases))

            # Synthesize 4096 samples so 3ms envelope reaches steady state, then verify with FrequencyDetector(mode="goertzel")
            steady = synth.synthesize_frames(4096)
            self.assertEqual(steady.shape, (4096,))
            self.assertEqual(steady.dtype, np.float32)

            det = FrequencyDetector(sample_rate=sr, frame_size=1024, overlap=0.5, window_type="hann", snr_threshold=4.0)
            hits = det.detect_goertzel_frame(steady[-1024:].astype(np.float64), target_freqs=[440.0, 697.0, 1209.0])
            hit_freqs = {round(h.frequency_hz, 1) for h in hits}
            self.assertIn(440.0, hit_freqs)
            self.assertIn(1209.0, hit_freqs)
            self.assertNotIn(697.0, hit_freqs, "Inactive Lane #1 (697 Hz) must not trigger Goertzel!")

        # 2. Verify SwimlaneToneSynthEngine, WAV synthesis, NightSweep Ollama advisor, and Flask routes
        with tempfile.TemporaryDirectory() as tmpdir:
            sw_engine = SwimlaneToneSynthEngine(recordings_dir=Path(tmpdir))
            st0 = sw_engine.get_status()
            self.assertTrue(st0["ok"])
            self.assertEqual(st0["kpis"]["total_lanes"], 7)
            self.assertEqual(
                st0["kpis"]["closed_loop_goertzel_verified_count"],
                st0["kpis"]["active_lane_count"],
            )

            wav_chord = sw_engine.render_swimlane_wav(duration_sec=1.2)
            self.assertEqual(wav_chord[:4], b"RIFF")

            adv = query_ollama_swimlane_synth_advisor(sw_engine, force=False)
            self.assertTrue(adv["ok"])
            self.assertIn("envelope_and_phase_findings", adv)

            ledger = ForensicWordLedger(output_dir=tmpdir, encrypt_fernet=False)
            ledger.log_utterance(
                "PERSON_DELTA",
                0.95,
                0.0,
                1.1,
                [ExtractedWord("swimlane", 0.1, 0.5, 0.92), ExtractedWord("synth", 0.5, 1.0, 0.94)],
                "Swimlane synth.",
                BiometricSnapshot(resp_bpm=14.8, throat_disp_um_rms=22.0, f0_hz=150.0, vtl_cm=16.8),
            )
            ledger.close()

            engine = LarexAnalyticsEngine(flowgraph=None, bio_service=None, recordings_dir=Path(tmpdir))
            app = create_larex_flask_app(engine)
            client = app.test_client()

            r_st = client.get("/api/swimlane-synth/status")
            self.assertEqual(r_st.status_code, 200)
            self.assertTrue(json.loads(r_st.data.decode("utf-8"))["ok"])

            r_tr = client.post("/api/swimlane-synth/trigger", json={"active_lane_ids": [0, 3, 5], "volume": 0.22})
            self.assertEqual(r_tr.status_code, 200)
            tr_json = json.loads(r_tr.data.decode("utf-8"))
            self.assertEqual(tr_json["kpis"]["active_lane_count"], 3)
            self.assertEqual(tr_json["kpis"]["closed_loop_goertzel_verified_count"], 3)

            r_tg = client.post("/api/swimlane-synth/toggle", json={"lane_id": 1, "volume": 0.22})
            self.assertEqual(r_tg.status_code, 200)
            self.assertEqual(json.loads(r_tg.data.decode("utf-8"))["kpis"]["active_lane_count"], 4)

            r_wav = client.get("/api/swimlane-synth/audio/chord.wav?lanes=0,2,4&sec=1.2")
            self.assertEqual(r_wav.status_code, 200)
            self.assertEqual(r_wav.mimetype, "audio/wav")
            self.assertEqual(r_wav.data[:4], b"RIFF")

            r_oll = client.post("/api/ollama/swimlane-synth", json={"force": False})
            self.assertEqual(r_oll.status_code, 200)
            self.assertTrue(json.loads(r_oll.data.decode("utf-8"))["ok"])

            r_sh = client.get("/api/earworm/shared?hours=6")
            self.assertEqual(r_sh.status_code, 200)
            sh_json = json.loads(r_sh.data.decode("utf-8"))
            self.assertIn("swimlane_tone_synth", sh_json["ten_new_features_summary"])
            self.assertIn("swimlane_tone_synth", sh_json["speakers"]["PERSON_DELTA"]["nightsweep_modal_reference"])

    def test_19_nightsweep_starter_guide_and_empty_ledger_modals(self) -> None:
        """Starter Guide dependency matrix, empty-ledger NightSweep modal fallback, and 1-click demo ledger seeding."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = LarexAnalyticsEngine(flowgraph=None, bio_service=None, recordings_dir=Path(tmpdir))
            app = create_larex_flask_app(engine)
            client = app.test_client()

            # 1. Starter guide status returns full dependency inventory & 5-step checklist
            r_sg = client.get("/api/starter-guide/status?refresh=1")
            self.assertEqual(r_sg.status_code, 200)
            sg_json = json.loads(r_sg.data.decode("utf-8"))
            self.assertTrue(sg_json["ok"])
            self.assertGreaterEqual(len(sg_json["dependencies"]), 17)
            self.assertEqual(len(sg_json["starter_steps"]), 5)
            self.assertFalse(sg_json["summary"]["ledger_seeded"])

            # 2. Even on a fresh GitHub clone (empty recordings/), all 8 NightSweep modal dossiers are populated
            r_sh = client.get("/api/earworm/shared?hours=6")
            self.assertEqual(r_sh.status_code, 200)
            sh_json = json.loads(r_sh.data.decode("utf-8"))
            for spk_id in ("PERSON_DELTA", "PERSON_ALPHA", "PERSON_BETA", "PERSON_GAMMA", "PERSON_TYPIST"):
                self.assertIn(spk_id, sh_json["speakers"])
                self.assertIn("nightsweep_modal_reference", sh_json["speakers"][spk_id])

            # 3. 1-click bootstrap seeds the demo ledger and verifies DSP
            r_boot = client.post("/api/starter-guide/bootstrap", json={"action": "seed_demo_ledger"})
            self.assertEqual(r_boot.status_code, 200)
            boot_json = json.loads(r_boot.data.decode("utf-8"))
            self.assertTrue(boot_json["ok"])
            self.assertTrue(boot_json["starter_guide"]["summary"]["ledger_seeded"])

            r_wph = client.get("/api/analytics/words-per-hour?hours=6")
            self.assertEqual(r_wph.status_code, 200)
            wph_json = json.loads(r_wph.data.decode("utf-8"))
            self.assertGreaterEqual(wph_json["kpis"]["total_utterances"], 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
