#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GNU-Larex :: Per-Sentence Markov -> Earworm Delta Inspector &
Dedicated `PERSON_TYPIST` 48 kHz Acoustic Keystroke Capture Engine
==================================================================
Provides:
  1. `SentenceMarkovDeltaTracker`:
     Evaluates 3 coupled Markov models after EVERY decoded sentence:
       - M1: Interpolated 2nd-Order Lexical Bigram/Unigram Markov (with temporal decay `gamma`
             and Kneser-Ney style discount `discount_d`)
       - M2: 2nd-Order Articulatory/Whisper Phoneme Contour Markov (`S/T`, `SH`, `EE`, `EH`, `AH`, `OO`)
       - M3: Earworm Delta Emergence State Machine (shows exact `from_state -> to_state` edges,
             probability `P`, Shannon entropy `H`, and whether the sentence seeded, reinforced,
             or shifted the active Earworm Delta).
  2. `AcousticTypingPersonEngine` (`PERSON_TYPIST` ONLY):
     Purely acoustic/vibrometric 48 kHz keystroke transient detector (3.8-19.5 kHz switch click +
     180-950 Hz plate bottom-out thock + sub-15 ms crest-factor gate + HPS vocal F0 rejection).
     Routes detected typing bursts EXCLUSIVELY to `PERSON_TYPIST` and never mixes speech/whispers
     into `PERSON_TYPIST`.
"""

from __future__ import annotations

import collections
import datetime
import hashlib
import json
import math
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np  # type: ignore

try:
    import requests  # type: ignore

    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

TYPIST_SPEAKER_ID = "PERSON_TYPIST"

STOP_GLUE = {
    "the",
    "and",
    "for",
    "that",
    "this",
    "with",
    "from",
    "have",
    "going",
    "to",
    "watching",
    "thank",
    "thanks",
    "subtitles",
}

HALLUCINATION_EXACT = {
    "thank you",
    "for watching",
    "thank you for watching",
    "thanks for watching",
    "you",
}


def word_to_phoneme_state(word: str) -> str:
    """Maps a single lexical word (or typing key token) to its compact articulatory/acoustic Markov symbol."""
    w = (word or "").strip().lower()
    if not w:
        return "OO"
    if w.startswith("[") and w.endswith("]"):
        if "space" in w or "ret" in w:
            return "THOCK"
        if "mod" in w or "bksp" in w:
            return "TAK"
        return "TIK"
    seq: List[str] = []
    i = 0
    while i < len(w):
        if w[i : i + 2] in ("sh", "ch", "th"):
            ph = "SH"
            i += 2
        elif w[i] in ("s", "t", "z", "k", "c", "x"):
            ph = "S/T"
            i += 1
        elif w[i] in ("i", "y"):
            ph = "EE"
            i += 1
        elif w[i] == "e":
            ph = "EH"
            i += 1
        elif w[i] == "a":
            ph = "AH"
            i += 1
        elif w[i] in ("o", "u", "w"):
            ph = "OO"
            i += 1
        else:
            i += 1
            continue
        if not seq or seq[-1] != ph:
            seq.append(ph)
        if len(seq) >= 3:
            break
    return "-".join(seq) if seq else "AH"


def extract_sentence_earworm_hooks(text: str) -> List[str]:
    norm = re.sub(r"[^a-zA-Z0-9'\[\]/\s\-]", " ", (text or "").lower()).strip()
    if not norm or norm in HALLUCINATION_EXACT:
        return []
    tokens = [t.strip("'") for t in norm.split() if len(t.strip("'")) >= 2]
    if not tokens:
        return []
    hooks: List[str] = []
    for n_len in (4, 3, 2, 5):
        if len(tokens) < n_len:
            continue
        for idx in range(len(tokens) - n_len + 1):
            gram = " ".join(tokens[idx : idx + n_len])
            if gram in HALLUCINATION_EXACT or len(gram) < 6:
                continue
            if all(tok in STOP_GLUE for tok in tokens[idx : idx + n_len]):
                continue
            hooks.append(gram)
    seen = set()
    dedup: List[str] = []
    for hk in hooks:
        if hk not in seen:
            seen.add(hk)
            dedup.append(hk)
    return dedup[:8]


class SentenceMarkovDeltaTracker:
    """
    Tracks exact per-sentence Markov state activations across:
      - M1: Interpolated 2nd-Order Lexical Markov Chain (`(w_{t-2}, w_{t-1}) -> w_t`)
      - M2: 2nd-Order Articulatory Phoneme Contour Markov Chain (`(c_{t-2}, c_{t-1}) -> c_t`)
      - M3: Typing Cadence Key-Class Markov Chain (`PERSON_TYPIST` isolated graph)
      - M4: Auto-Promoted 3rd-Order & 4th-Order Phrase Markov Chains (`(w_{t-3..t-1}) -> w_t`
            and `(w_{t-4..t-1}) -> w_t`), automatically promoted whenever a 2nd-order bigram
            locks (`prior_bi >= promotion_min_lock_weight` and branch entropy `H <= promotion_entropy_max_bits`).
    and records how each sentence brings forth, reinforces, or shifts the room's Earworm Delta.
    """

    def __init__(
        self,
        decay_gamma: float = 0.988,
        bigram_interp_lambda: float = 0.74,
        kneser_ney_discount: float = 0.35,
        delta_min_repeats: int = 2,
        delta_prob_threshold: float = 0.22,
        auto_promote_higher_order: bool = True,
        promotion_entropy_max_bits: float = 1.65,
        promotion_min_lock_weight: float = 1.0,
        adaptive_gamma_enabled: bool = True,
        sliding_window_sentences: int = 12,
    ) -> None:
        self.decay_gamma = float(np.clip(decay_gamma, 0.90, 1.0))
        self.bigram_interp_lambda = float(np.clip(bigram_interp_lambda, 0.20, 0.95))
        self.kneser_ney_discount = float(np.clip(kneser_ney_discount, 0.0, 0.90))
        self.delta_min_repeats = max(1, int(delta_min_repeats))
        self.delta_prob_threshold = float(np.clip(delta_prob_threshold, 0.05, 0.85))
        self.auto_promote_higher_order = bool(auto_promote_higher_order)
        self.promotion_entropy_max_bits = float(np.clip(promotion_entropy_max_bits, 0.25, 3.50))
        self.promotion_min_lock_weight = float(np.clip(promotion_min_lock_weight, 0.5, 5.0))
        self.adaptive_gamma_enabled = bool(adaptive_gamma_enabled)
        self.sliding_window_sentences = max(4, min(40, int(sliding_window_sentences)))
        self.effective_decay_gamma: float = self.decay_gamma
        self._recent_hook_density: float = 0.35

        self._lock = threading.Lock()

        # Vocal/Whisper Lexical & Phoneme Markov Graphs (excludes PERSON_TYPIST)
        self.lex_uni: Dict[str, Dict[str, float]] = collections.defaultdict(
            lambda: collections.defaultdict(float)
        )
        self.lex_bi: Dict[Tuple[str, str], Dict[str, float]] = collections.defaultdict(
            lambda: collections.defaultdict(float)
        )
        # Auto-promoted 3rd-order & 4th-order phrase-chain tables (M4)
        self.lex_tri: Dict[Tuple[str, str, str], Dict[str, float]] = collections.defaultdict(
            lambda: collections.defaultdict(float)
        )
        self.lex_quad: Dict[Tuple[str, str, str, str], Dict[str, float]] = collections.defaultdict(
            lambda: collections.defaultdict(float)
        )
        self.ph_uni: Dict[str, Dict[str, float]] = collections.defaultdict(
            lambda: collections.defaultdict(float)
        )
        self.ph_bi: Dict[Tuple[str, str], Dict[str, float]] = collections.defaultdict(
            lambda: collections.defaultdict(float)
        )
        self.ph_tri: Dict[Tuple[str, str, str], Dict[str, float]] = collections.defaultdict(
            lambda: collections.defaultdict(float)
        )
        self.promoted_phrase_chains: Dict[str, Dict[str, Any]] = {}

        # Isolated PERSON_TYPIST Rhythm/Key-Class Markov Graph
        self.typist_uni: Dict[str, Dict[str, float]] = collections.defaultdict(
            lambda: collections.defaultdict(float)
        )
        self.typist_bi: Dict[Tuple[str, str], Dict[str, float]] = collections.defaultdict(
            lambda: collections.defaultdict(float)
        )

        # Rolling Earworm Delta Hook Weights + Local Sliding Context Window
        self.hook_weights: Dict[str, float] = collections.defaultdict(float)
        self.hook_raw_counts: Dict[str, int] = collections.defaultdict(int)
        self.hook_speakers: Dict[str, set] = collections.defaultdict(set)
        self._sliding_hook_window: collections.deque[List[str]] = collections.deque(
            maxlen=self.sliding_window_sentences
        )
        self.current_earworm_delta: str = ""
        self.previous_earworm_delta: str = ""

        # Stats & sentence activation log
        self.total_sentences_evaluated: int = 0
        self.higher_order_hits: int = 0
        self.bigram_hits: int = 0
        self.unigram_backoffs: int = 0
        self.delta_shifts_count: int = 0
        self._sentence_activations: collections.deque[Dict[str, Any]] = collections.deque(maxlen=60)

    def reset(self) -> None:
        with self._lock:
            self.lex_uni.clear()
            self.lex_bi.clear()
            self.lex_tri.clear()
            self.lex_quad.clear()
            self.ph_uni.clear()
            self.ph_bi.clear()
            self.ph_tri.clear()
            self.promoted_phrase_chains.clear()
            self.typist_uni.clear()
            self.typist_bi.clear()
            self.hook_weights.clear()
            self.hook_raw_counts.clear()
            self.hook_speakers.clear()
            self._sliding_hook_window.clear()
            self.current_earworm_delta = ""
            self.previous_earworm_delta = ""
            self.total_sentences_evaluated = 0
            self.higher_order_hits = 0
            self.bigram_hits = 0
            self.unigram_backoffs = 0
            self.delta_shifts_count = 0
            self._sentence_activations.clear()

    def apply_config(self, cfg: Dict[str, Any]) -> List[str]:
        applied: List[str] = []
        with self._lock:
            if "decay_gamma" in cfg:
                self.decay_gamma = float(np.clip(float(cfg["decay_gamma"]), 0.90, 1.0))
                self.effective_decay_gamma = self.decay_gamma
                applied.append(f"markov.decay_gamma={self.decay_gamma:.3f}")
            if "bigram_interp_lambda" in cfg:
                self.bigram_interp_lambda = float(np.clip(float(cfg["bigram_interp_lambda"]), 0.20, 0.95))
                applied.append(f"markov.bigram_interp_lambda={self.bigram_interp_lambda:.2f}")
            if "kneser_ney_discount" in cfg:
                self.kneser_ney_discount = float(np.clip(float(cfg["kneser_ney_discount"]), 0.0, 0.90))
                applied.append(f"markov.kneser_ney_discount={self.kneser_ney_discount:.2f}")
            if "delta_min_repeats" in cfg:
                self.delta_min_repeats = max(1, min(8, int(cfg["delta_min_repeats"])))
                applied.append(f"markov.delta_min_repeats={self.delta_min_repeats}")
            if "delta_prob_threshold" in cfg:
                self.delta_prob_threshold = float(np.clip(float(cfg["delta_prob_threshold"]), 0.05, 0.85))
                applied.append(f"markov.delta_prob_threshold={self.delta_prob_threshold:.2f}")
            if "auto_promote_higher_order" in cfg:
                self.auto_promote_higher_order = bool(cfg["auto_promote_higher_order"])
                applied.append(f"markov.auto_promote_higher_order={self.auto_promote_higher_order}")
            if "promotion_entropy_max_bits" in cfg:
                self.promotion_entropy_max_bits = float(
                    np.clip(float(cfg["promotion_entropy_max_bits"]), 0.25, 3.50)
                )
                applied.append(f"markov.promotion_entropy_max_bits={self.promotion_entropy_max_bits:.2f}b")
            if "adaptive_gamma_enabled" in cfg:
                self.adaptive_gamma_enabled = bool(cfg["adaptive_gamma_enabled"])
                applied.append(f"markov.adaptive_gamma_enabled={self.adaptive_gamma_enabled}")
        return applied

    def _apply_decay_locked(self, sentence_had_recurrent_hook: bool = False) -> None:
        if self.adaptive_gamma_enabled:
            target = 1.0 if sentence_had_recurrent_hook else 0.0
            self._recent_hook_density = 0.82 * self._recent_hook_density + 0.18 * target
            # Modulate effective gamma around base decay_gamma: faster flush during diffuse speech,
            # tighter retention when repetitive low-ambient hooks are locking
            shift = (self._recent_hook_density - 0.35) * 0.014
            self.effective_decay_gamma = float(np.clip(self.decay_gamma + shift, 0.92, 0.997))
        else:
            self.effective_decay_gamma = self.decay_gamma

        if self.effective_decay_gamma >= 0.9999:
            return
        g = self.effective_decay_gamma
        for hk in list(self.hook_weights.keys()):
            self.hook_weights[hk] *= g
            if self.hook_weights[hk] < 0.15:
                del self.hook_weights[hk]

    @staticmethod
    def _raw_branch_entropy(dist: Dict[str, float]) -> float:
        tot = sum(dist.values())
        if tot <= 0.0:
            return 0.0
        val = -sum((v / tot) * math.log2(max(v / tot, 1e-12)) for v in dist.values() if v > 0)
        return 0.0 if abs(val) < 1e-9 else val

    def _register_promoted_chain_locked(
        self,
        phrase_tokens: Tuple[str, ...],
        order: int,
        branch_entropy: float,
        spk_id: str,
        ts_utc: str,
    ) -> Tuple[str, bool]:
        clean_tokens = tuple(t for t in phrase_tokens if t != "<s>")
        phrase = " ".join(clean_tokens)
        existing = self.promoted_phrase_chains.get(phrase)
        is_new = existing is None
        if existing is None:
            self.promoted_phrase_chains[phrase] = {
                "phrase": phrase,
                "order": int(order),
                "lock_entropy_bits": round(float(branch_entropy), 3),
                "activations": 1,
                "speakers": {spk_id},
                "contour": " → ".join(word_to_phoneme_state(w) for w in clean_tokens),
                "promoted_at_utc": ts_utc,
                "last_seen_utc": ts_utc,
            }
        else:
            existing["order"] = max(int(existing["order"]), int(order))
            existing["lock_entropy_bits"] = round(
                min(float(existing["lock_entropy_bits"]), float(branch_entropy)), 3
            )
            existing["activations"] = int(existing["activations"]) + 1
            existing["speakers"].add(spk_id)
            existing["last_seen_utc"] = ts_utc
        return phrase, is_new

    @classmethod
    def _hierarchical_probs_and_entropy(
        cls,
        quad_dist: Dict[str, float],
        tri_dist: Dict[str, float],
        bi_dist: Dict[str, float],
        uni_dist: Dict[str, float],
        lam: float,
        discount_d: float,
    ) -> Tuple[List[Dict[str, Any]], float, int]:
        """
        Recursive Kneser-Ney discounted + interpolated transition distribution across
        Order 4 (4-gram) -> Order 3 (Trigram) -> Order 2 (Bigram) -> Order 1 (Unigram).
        Returns `(top_predictions, shannon_entropy_bits, highest_order_used)`.
        """
        candidates = set(quad_dist.keys()) | set(tri_dist.keys()) | set(bi_dist.keys()) | set(uni_dist.keys())
        if not candidates:
            return [], 0.0, 0

        uni_sum = sum(uni_dist.values())
        bi_sum = sum(bi_dist.values())
        tri_sum = sum(tri_dist.values())
        quad_sum = sum(quad_dist.values())

        highest_order = 4 if quad_sum > 0 else (3 if tri_sum > 0 else (2 if bi_sum > 0 else 1))

        def kn_step(high_d: Dict[str, float], h_sum: float, low_probs: Dict[str, float], blend_lam: float) -> Dict[str, float]:
            if h_sum <= 0.0:
                return low_probs
            n_pos = sum(1 for v in high_d.values() if v > 0)
            alpha_bow = (discount_d * n_pos) / max(h_sum, 1e-9)
            out_p: Dict[str, float] = {}
            for tok in candidates:
                c_h = high_d.get(tok, 0.0)
                p_low = low_probs.get(tok, 1.0 / len(candidates))
                p_kn = (max(c_h - discount_d, 0.0) / max(h_sum, 1e-9)) + alpha_bow * p_low
                out_p[tok] = blend_lam * p_kn + (1.0 - blend_lam) * p_low
            return out_p

        p1 = {
            tok: (uni_dist.get(tok, 0.0) / uni_sum) if uni_sum > 0 else (1.0 / len(candidates))
            for tok in candidates
        }
        p2 = kn_step(bi_dist, bi_sum, p1, lam)
        p3 = kn_step(tri_dist, tri_sum, p2, min(0.92, lam + 0.08))
        p4 = kn_step(quad_dist, quad_sum, p3, min(0.95, lam + 0.12))

        norm_s = sum(p4.values()) + 1e-12
        probs = {k: v / norm_s for k, v in p4.items()}
        entropy = -sum(p * math.log2(max(p, 1e-12)) for p in probs.values())
        ranked = sorted(probs.items(), key=lambda kv: -kv[1])[:4]
        out = [
            {
                "token": k,
                "prob": round(float(p), 3),
                "contour": word_to_phoneme_state(k),
                "quad_weight": round(float(quad_dist.get(k, 0.0)), 2),
                "tri_weight": round(float(tri_dist.get(k, 0.0)), 2),
                "bi_weight": round(float(bi_dist.get(k, 0.0)), 2),
                "uni_weight": round(float(uni_dist.get(k, 0.0)), 2),
            }
            for k, p in ranked
        ]
        return out, round(float(entropy), 3), highest_order

    @staticmethod
    def _dist_probs_and_entropy(
        bi_dist: Dict[str, float],
        uni_dist: Dict[str, float],
        lam: float,
        discount_d: float,
    ) -> Tuple[List[Dict[str, Any]], float, bool]:
        """Computes Kneser-Ney discounted + interpolated transition distribution & Shannon entropy (bits)."""
        candidates = set(bi_dist.keys()) | set(uni_dist.keys())
        if not candidates:
            return [], 0.0, False

        bi_sum = sum(bi_dist.values())
        uni_sum = sum(uni_dist.values())
        used_bi = bi_sum > 0.0

        scores: Dict[str, float] = {}
        for tok in candidates:
            p_uni = (uni_dist.get(tok, 0.0) / uni_sum) if uni_sum > 0 else (1.0 / len(candidates))
            if used_bi:
                c_bi = bi_dist.get(tok, 0.0)
                n_pos = sum(1 for v in bi_dist.values() if v > 0)
                alpha_bow = (discount_d * n_pos) / max(bi_sum, 1e-9)
                p_bi = (max(c_bi - discount_d, 0.0) / max(bi_sum, 1e-9)) + alpha_bow * p_uni
                scores[tok] = lam * p_bi + (1.0 - lam) * p_uni
            else:
                scores[tok] = p_uni

        norm_s = sum(scores.values()) + 1e-12
        probs = {k: v / norm_s for k, v in scores.items()}
        entropy = -sum(p * math.log2(max(p, 1e-12)) for p in probs.values())
        ranked = sorted(probs.items(), key=lambda kv: -kv[1])[:4]
        out = [
            {
                "token": k,
                "prob": round(float(p), 3),
                "contour": word_to_phoneme_state(k),
                "bi_weight": round(float(bi_dist.get(k, 0.0)), 2),
                "uni_weight": round(float(uni_dist.get(k, 0.0)), 2),
            }
            for k, p in ranked
        ]
        return out, round(float(entropy), 3), used_bi

    def evaluate_sentence(self, rec: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluates a newly decoded (or replayed) sentence, updates the appropriate Markov chains,
        and returns the complete `markov_activation` trace explaining which Markov model activated
        and how it brought forth or reinforced an Earworm Delta.
        """
        seg = rec.get("segment") or {}
        txt = str(seg.get("ollama_reconstructed") or seg.get("raw_transcript") or "").strip()
        spk_id = str((rec.get("speaker") or {}).get("speaker_id") or "PERSON_ALPHA").upper()
        vb = rec.get("vad_biometrics") or {}
        role = str(vb.get("band_role") or "VOICED_LARYNX").upper()
        ts_utc = str(
            rec.get("timestamp_utc")
            or datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")
        )

        is_other_room = spk_id == "OTHER_ROOM_SUBLEVEL" or role == "OTHER_ROOM_PIGGYBACK"
        is_electronic = spk_id in ("DEVICE_CELLPHONE", "DEVICE_MEMS") or role.startswith("ELECTRONIC_")
        is_typist = spk_id == TYPIST_SPEAKER_ID or role == "ACOUSTIC_TYPING" or is_electronic or is_other_room
        if is_typist:
            raw_tokens = [t for t in txt.split() if t.startswith("[") or len(t) >= 2]
        else:
            raw_tokens = [
                re.sub(r"[^a-zA-Z0-9']", "", w).lower()
                for w in txt.split()
                if len(re.sub(r"[^a-zA-Z0-9']", "", w)) >= 2
            ]

        with self._lock:
            self.total_sentences_evaluated += 1
            delta_before = self.current_earworm_delta

            if is_typist:
                # Isolated M3/M5/M6 Non-Vocal / Non-Occupant Markov Chain (never touches vocal Earworm Delta!)
                activated_edges: List[Dict[str, Any]] = []
                used_bi_any = False
                edge_chain_bi = (
                    "OTHER_ROOM_PIGGYBACK_BIGRAM"
                    if is_other_room
                    else ("ELECTRONIC_CLICK_BIGRAM" if is_electronic else "TYPING_KEY_BIGRAM")
                )
                edge_chain_uni = (
                    "OTHER_ROOM_PIGGYBACK_UNIGRAM"
                    if is_other_room
                    else ("ELECTRONIC_CLICK_UNIGRAM" if is_electronic else "TYPING_KEY_UNIGRAM")
                )
                for idx in range(len(raw_tokens)):
                    tok = raw_tokens[idx]
                    if idx >= 1:
                        prev1 = raw_tokens[idx - 1]
                        self.typist_uni[prev1][tok] += 1.0
                        if idx >= 2:
                            prev2 = raw_tokens[idx - 2]
                            self.typist_bi[(prev2, prev1)][tok] += 1.0
                            total_b = sum(self.typist_bi[(prev2, prev1)].values())
                            used_bi_any = True
                            activated_edges.append(
                                {
                                    "chain": edge_chain_bi,
                                    "from_state": f"{prev2} → {prev1}",
                                    "to_state": tok,
                                    "prob": round(self.typist_bi[(prev2, prev1)][tok] / max(total_b, 1.0), 3),
                                    "weight": round(self.typist_bi[(prev2, prev1)][tok], 1),
                                }
                            )
                        else:
                            total_u = sum(self.typist_uni[prev1].values())
                            activated_edges.append(
                                {
                                    "chain": edge_chain_uni,
                                    "from_state": prev1,
                                    "to_state": tok,
                                    "prob": round(self.typist_uni[prev1][tok] / max(total_u, 1.0), 3),
                                    "weight": round(self.typist_uni[prev1][tok], 1),
                                }
                            )

                last1 = raw_tokens[-1] if raw_tokens else "[ALPHA]"
                last2 = raw_tokens[-2] if len(raw_tokens) >= 2 else ""
                preds, ent, bi_hit = self._dist_probs_and_entropy(
                    self.typist_bi.get((last2, last1), {}) if last2 else {},
                    self.typist_uni.get(last1, {}),
                    self.bigram_interp_lambda,
                    self.kneser_ney_discount,
                )
                if is_other_room:
                    mod_lbl = (
                        "M6_OTHER_ROOM_PIGGYBACK_MARKOV (2nd-Order Boundary)"
                        if (bi_hit or used_bi_any)
                        else "M6_OTHER_ROOM_PIGGYBACK_MARKOV (1st-Order Boundary)"
                    )
                elif is_electronic:
                    mod_lbl = (
                        "M5_ELECTRONIC_MEMS_MARKOV (2nd-Order Click)"
                        if (bi_hit or used_bi_any)
                        else "M5_ELECTRONIC_MEMS_MARKOV (1st-Order Click)"
                    )
                else:
                    mod_lbl = (
                        "M3_TYPING_CADENCE_MARKOV (2nd-Order Key-Class)"
                        if (bi_hit or used_bi_any)
                        else "M3_TYPING_CADENCE_MARKOV (1st-Order Key-Class)"
                    )
                act = {
                    "id": "mk-" + hashlib.sha256(f"{ts_utc}:{spk_id}:{txt}".encode("utf-8")).hexdigest()[:10],
                    "timestamp_utc": ts_utc,
                    "speaker_id": spk_id if (is_electronic or is_other_room) else TYPIST_SPEAKER_ID,
                    "band_role": role if (is_electronic or is_other_room) else "ACOUSTIC_TYPING",
                    "sentence_text": txt,
                    "active_model": mod_lbl,
                    "markov_order": 2 if (bi_hit or used_bi_any) else 1,
                    "phoneme_sequence": " → ".join(word_to_phoneme_state(t) for t in raw_tokens[:6]),
                    "activated_edges": activated_edges[-5:],
                    "top_next_predictions": preds,
                    "entropy_bits": ent,
                    "delta_outcome": (
                        "OTHER_ROOM_ISOLATED_EVENT"
                        if is_other_room
                        else ("ELECTRONIC_ISOLATED_EVENT" if is_electronic else "TYPING_ISOLATED_EVENT")
                    ),
                    "earworm_delta_before": delta_before,
                    "earworm_delta_after": delta_before,
                    "sentence_hook": (
                        "other-room piggyback"
                        if is_other_room
                        else ("electronic click" if is_electronic else "typing burst")
                    ),
                    "hook_repeats": 0,
                    "delta_shift_triggered": False,
                }
                self._sentence_activations.append(act)
                return act

            # Vocal / Whisper Sentence Evaluation (M1/M2 -> M4 Auto-Promoted 3rd/4th-Order Phrase Markov -> Earworm Delta)
            hooks = extract_sentence_earworm_hooks(txt)
            had_recurrent_hook = any(self.hook_raw_counts.get(hk, 0) > 0 for hk in hooks)
            self._apply_decay_locked(sentence_had_recurrent_hook=had_recurrent_hook)

            ph_tokens = [word_to_phoneme_state(t) for t in raw_tokens]
            activated_edges = []
            sentence_bi_hits = 0
            sentence_tri_hits = 0
            sentence_quad_hits = 0
            promoted_this_sentence: List[str] = []

            for idx in range(len(raw_tokens)):
                tok = raw_tokens[idx]
                ph = ph_tokens[idx]
                if idx >= 1:
                    p1 = raw_tokens[idx - 1]
                    ph1 = ph_tokens[idx - 1]
                    if idx >= 2:
                        p2 = raw_tokens[idx - 2]
                        ph2 = ph_tokens[idx - 2]
                        p3_anc = raw_tokens[idx - 3] if idx >= 3 else "<s>"
                        ph3_anc = ph_tokens[idx - 3] if idx >= 3 else "BOS"
                        p4_anc = raw_tokens[idx - 4] if idx >= 4 else ("<s>" if idx == 3 else "")

                        prior_bi = self.lex_bi.get((p2, p1), {}).get(tok, 0.0)
                        prior_tri = self.lex_tri.get((p3_anc, p2, p1), {}).get(tok, 0.0)
                        prior_quad = (
                            self.lex_quad.get((p4_anc, p3_anc, p2, p1), {}).get(tok, 0.0)
                            if p4_anc
                            else 0.0
                        )

                        # Update 2nd-order tables
                        self.lex_bi[(p2, p1)][tok] += 1.0
                        self.ph_bi[(ph2, ph1)][ph] += 1.0
                        tot_bi = sum(self.lex_bi[(p2, p1)].values())
                        if prior_bi > 0:
                            sentence_bi_hits += 1

                        # Automatic Promotion of Locked 2nd-Order Hooks into 3rd & 4th-Order Phrase Chains (M4)
                        bi_branch_ent = self._raw_branch_entropy(self.lex_bi[(p2, p1)])
                        bi_locked = (
                            self.auto_promote_higher_order
                            and prior_bi >= self.promotion_min_lock_weight
                            and bi_branch_ent <= self.promotion_entropy_max_bits
                        )

                        edge_recorded = False
                        if p4_anc and self.auto_promote_higher_order:
                            prev_bi_locked = (
                                idx >= 3
                                and self.lex_bi.get((p3_anc, p2), {}).get(p1, 0.0) >= self.promotion_min_lock_weight
                            )
                            if prior_quad > 0 or prior_tri >= 1.0 or (bi_locked and prev_bi_locked):
                                self.lex_quad[(p4_anc, p3_anc, p2, p1)][tok] += 1.0
                                tot_q = sum(self.lex_quad[(p4_anc, p3_anc, p2, p1)].values())
                                phrase_str, is_new_p = self._register_promoted_chain_locked(
                                    (p4_anc, p3_anc, p2, p1, tok), 4, bi_branch_ent, spk_id, ts_utc
                                )
                                if is_new_p and phrase_str not in promoted_this_sentence:
                                    promoted_this_sentence.append(phrase_str)
                                if prior_quad > 0:
                                    sentence_quad_hits += 1
                                    ctx_lbl = " ".join(x for x in (p4_anc, p3_anc, p2, p1) if x != "<s>")
                                    activated_edges.append(
                                        {
                                            "chain": "M4_PROMOTED_4TH_ORDER",
                                            "from_state": ctx_lbl,
                                            "to_state": f"{tok} ({ph})",
                                            "prob": round(self.lex_quad[(p4_anc, p3_anc, p2, p1)][tok] / max(tot_q, 1.0), 3),
                                            "weight": round(self.lex_quad[(p4_anc, p3_anc, p2, p1)][tok], 2),
                                        }
                                    )
                                    edge_recorded = True

                        if self.auto_promote_higher_order and (prior_tri > 0 or bi_locked):
                            self.lex_tri[(p3_anc, p2, p1)][tok] += 1.0
                            self.ph_tri[(ph3_anc, ph2, ph1)][ph] += 1.0
                            tot_t = sum(self.lex_tri[(p3_anc, p2, p1)].values())
                            phrase_str3, is_new_p3 = self._register_promoted_chain_locked(
                                (p3_anc, p2, p1, tok), 3, bi_branch_ent, spk_id, ts_utc
                            )
                            if is_new_p3 and phrase_str3 not in promoted_this_sentence:
                                promoted_this_sentence.append(phrase_str3)
                            if prior_tri > 0:
                                sentence_tri_hits += 1
                                if not edge_recorded:
                                    ctx3_lbl = " ".join(x for x in (p3_anc, p2, p1) if x != "<s>")
                                    activated_edges.append(
                                        {
                                            "chain": "M4_PROMOTED_3RD_ORDER",
                                            "from_state": ctx3_lbl,
                                            "to_state": f"{tok} ({ph})",
                                            "prob": round(self.lex_tri[(p3_anc, p2, p1)][tok] / max(tot_t, 1.0), 3),
                                            "weight": round(self.lex_tri[(p3_anc, p2, p1)][tok], 2),
                                        }
                                    )
                                    edge_recorded = True

                        if not edge_recorded:
                            activated_edges.append(
                                {
                                    "chain": "M1_LEXICAL_2ND_ORDER" if prior_bi > 0 else "M2_PHONEME_2ND_ORDER",
                                    "from_state": f"{p2} {p1} ({ph2}→{ph1})",
                                    "to_state": f"{tok} ({ph})",
                                    "prob": round(self.lex_bi[(p2, p1)][tok] / max(tot_bi, 1.0), 3),
                                    "weight": round(self.lex_bi[(p2, p1)][tok], 2),
                                }
                            )
                    else:
                        self.lex_uni[p1][tok] += 1.0
                        self.ph_uni[ph1][ph] += 1.0
                        tot_u = sum(self.lex_uni[p1].values())
                        activated_edges.append(
                            {
                                "chain": "M1_LEXICAL_1ST_ORDER",
                                "from_state": f"{p1} ({ph1})",
                                "to_state": f"{tok} ({ph})",
                                "prob": round(self.lex_uni[p1][tok] / max(tot_u, 1.0), 3),
                                "weight": round(self.lex_uni[p1][tok], 2),
                            }
                        )
                    self.lex_uni[p1][tok] += 1.0
                    self.ph_uni[ph1][ph] += 1.0

            last_w1 = raw_tokens[-1] if raw_tokens else ""
            last_w2 = raw_tokens[-2] if len(raw_tokens) >= 2 else ""
            last_w3 = raw_tokens[-3] if len(raw_tokens) >= 3 else ""
            last_w4 = raw_tokens[-4] if len(raw_tokens) >= 4 else ""

            lex_preds, lex_ent, term_order = self._hierarchical_probs_and_entropy(
                self.lex_quad.get((last_w4, last_w3, last_w2, last_w1), {})
                if (self.auto_promote_higher_order and last_w4)
                else {},
                self.lex_tri.get((last_w3, last_w2, last_w1), {})
                if (self.auto_promote_higher_order and last_w3)
                else {},
                self.lex_bi.get((last_w2, last_w1), {}) if (last_w2 and last_w1) else {},
                self.lex_uni.get(last_w1, {}) if last_w1 else {},
                self.bigram_interp_lambda,
                self.kneser_ney_discount,
            )

            last_ph1 = ph_tokens[-1] if ph_tokens else "OO"
            last_ph2 = ph_tokens[-2] if len(ph_tokens) >= 2 else ""
            ph_preds, ph_ent, ph_bi_used = self._dist_probs_and_entropy(
                self.ph_bi.get((last_ph2, last_ph1), {}) if (last_ph2 and last_ph1) else {},
                self.ph_uni.get(last_ph1, {}),
                self.bigram_interp_lambda,
                self.kneser_ney_discount,
            )

            if self.auto_promote_higher_order and sentence_quad_hits > 0:
                self.higher_order_hits += 1
                self.bigram_hits += 1
                active_model = "M4 PROMOTED 4TH-ORDER PHRASE MARKOV"
                order_used = 4
            elif self.auto_promote_higher_order and sentence_tri_hits > 0:
                self.higher_order_hits += 1
                self.bigram_hits += 1
                active_model = "M4 PROMOTED 3RD-ORDER PHRASE MARKOV"
                order_used = 3
            elif term_order >= 2 or sentence_bi_hits > 0:
                self.bigram_hits += 1
                active_model = "M1+M2 INTERPOLATED 2ND-ORDER BIGRAM MARKOV"
                order_used = 2
            elif ph_bi_used:
                self.bigram_hits += 1
                active_model = "M2 PHONEME CONTOUR 2ND-ORDER MARKOV (Lexical Backoff)"
                order_used = 2
            else:
                self.unigram_backoffs += 1
                active_model = "M1+M2 1ST-ORDER UNIGRAM BACKOFF MARKOV"
                order_used = 1

            # Evaluate Earworm Delta Emergence from sentence hooks + promoted 3rd/4th-order boost + sliding context
            is_whisper = "WHISPER" in role or bool(vb.get("low_ambient_cued", False))
            whisper_boost = 1.35 if is_whisper else 0.85
            top_pred_prob = float(lex_preds[0]["prob"]) if lex_preds else (float(ph_preds[0]["prob"]) if ph_preds else 0.0)

            recent_local_counts: collections.Counter[str] = collections.Counter()
            for prev_hks in self._sliding_hook_window:
                recent_local_counts.update(prev_hks)
            self._sliding_hook_window.append(list(hooks))

            best_sent_hook = ""
            best_sent_repeats = 0
            for hk in hooks:
                self.hook_raw_counts[hk] += 1
                self.hook_speakers[hk].add(spk_id)
                n_words_hk = len(hk.split())
                promoted_bonus = 1.0
                if self.auto_promote_higher_order and n_words_hk >= 4 and (
                    hk in self.promoted_phrase_chains or order_used >= 3
                ):
                    promoted_bonus = 1.45
                elif self.auto_promote_higher_order and n_words_hk == 3 and order_used >= 3:
                    promoted_bonus = 1.22
                local_window_bonus = 1.0 + min(0.30, 0.10 * recent_local_counts.get(hk, 0))
                # Weight combines repetition + whisper bonus + Markov transition lock + 3rd/4th-order phrase bonus
                self.hook_weights[hk] += (
                    whisper_boost * (0.75 + 0.50 * top_pred_prob) * promoted_bonus * local_window_bonus
                )
                if (
                    self.hook_raw_counts[hk] > best_sent_repeats
                    or (self.hook_raw_counts[hk] == best_sent_repeats and len(hk) > len(best_sent_hook))
                ):
                    best_sent_repeats = self.hook_raw_counts[hk]
                    best_sent_hook = hk

            # Determine winning Earworm Delta across room
            qualified = [
                (hk, wt)
                for hk, wt in self.hook_weights.items()
                if self.hook_raw_counts.get(hk, 0) >= self.delta_min_repeats
            ]
            delta_outcome = "PASSIVE_LEXICAL_STEP"
            delta_shifted = False

            if qualified:
                qualified.sort(key=lambda kv: (-kv[1], -self.hook_raw_counts[kv[0]], -len(kv[0])))
                top_hook, _ = qualified[0]
                if top_hook != self.current_earworm_delta:
                    if self.current_earworm_delta:
                        self.previous_earworm_delta = self.current_earworm_delta
                    self.current_earworm_delta = top_hook
                    self.delta_shifts_count += 1
                    delta_shifted = True
                    delta_outcome = "EARWORM_DELTA_SHIFTED"
                elif top_hook in hooks:
                    delta_outcome = "EARWORM_DELTA_REINFORCED"
                else:
                    delta_outcome = "SUB_THRESHOLD_ACCUMULATING" if hooks else "PASSIVE_LEXICAL_STEP"
            elif hooks:
                delta_outcome = "CANDIDATE_HOOK_SEEDED"

            act = {
                "id": "mk-" + hashlib.sha256(f"{ts_utc}:{spk_id}:{txt}:{self.total_sentences_evaluated}".encode("utf-8")).hexdigest()[:10],
                "timestamp_utc": ts_utc,
                "speaker_id": spk_id,
                "band_role": role,
                "sentence_text": txt,
                "active_model": active_model,
                "markov_order": order_used,
                "promoted_this_sentence": promoted_this_sentence,
                "phoneme_sequence": " → ".join(ph_tokens[:7]),
                "activated_edges": activated_edges[-5:],
                "top_next_predictions": lex_preds if lex_preds else ph_preds,
                "phoneme_next_predictions": ph_preds[:3],
                "entropy_bits": lex_ent if lex_preds else ph_ent,
                "delta_outcome": delta_outcome,
                "delta_shift_triggered": delta_shifted,
                "earworm_delta_before": delta_before,
                "earworm_delta_after": self.current_earworm_delta,
                "sentence_hook": best_sent_hook or (hooks[0] if hooks else ""),
                "hook_repeats": int(best_sent_repeats),
                "hook_speakers": sorted(self.hook_speakers.get(best_sent_hook, [])) if best_sent_hook else [spk_id],
            }
            self._sentence_activations.append(act)
            return act

    def get_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            acts = list(reversed(self._sentence_activations))
            top_hooks = sorted(
                [
                    {
                        "hook": hk,
                        "weight": round(float(wt), 2),
                        "repeats": int(self.hook_raw_counts.get(hk, 0)),
                        "speakers": sorted(self.hook_speakers.get(hk, [])),
                        "contour": " → ".join(word_to_phoneme_state(w) for w in hk.split()[:5]),
                        "is_active_delta": hk == self.current_earworm_delta,
                        "is_promoted_chain": hk in self.promoted_phrase_chains,
                        "promoted_order": int(self.promoted_phrase_chains[hk]["order"])
                        if hk in self.promoted_phrase_chains
                        else 2,
                    }
                    for hk, wt in self.hook_weights.items()
                ],
                key=lambda x: (-x["weight"], -x["repeats"]),
            )[:8]
            promoted_list = sorted(
                [
                    {
                        "phrase": v["phrase"],
                        "order": int(v["order"]),
                        "lock_entropy_bits": float(v["lock_entropy_bits"]),
                        "activations": int(v["activations"]),
                        "speakers": sorted(v["speakers"]),
                        "contour": v["contour"],
                        "is_active_delta": v["phrase"] == self.current_earworm_delta,
                    }
                    for v in self.promoted_phrase_chains.values()
                ],
                key=lambda x: (-x["activations"], -x["order"], x["lock_entropy_bits"]),
            )[:10]
            total_eval = max(1, self.total_sentences_evaluated)
            return {
                "config": {
                    "decay_gamma": self.decay_gamma,
                    "effective_decay_gamma": round(self.effective_decay_gamma, 4),
                    "adaptive_gamma_enabled": self.adaptive_gamma_enabled,
                    "bigram_interp_lambda": self.bigram_interp_lambda,
                    "kneser_ney_discount": self.kneser_ney_discount,
                    "delta_min_repeats": self.delta_min_repeats,
                    "delta_prob_threshold": self.delta_prob_threshold,
                    "auto_promote_higher_order": self.auto_promote_higher_order,
                    "promotion_entropy_max_bits": self.promotion_entropy_max_bits,
                },
                "kpis": {
                    "total_sentences_evaluated": self.total_sentences_evaluated,
                    "higher_order_activation_pct": round(100.0 * self.higher_order_hits / total_eval, 1),
                    "promoted_chains_count": len(self.promoted_phrase_chains),
                    "bigram_activation_pct": round(100.0 * self.bigram_hits / total_eval, 1),
                    "unigram_backoff_pct": round(100.0 * self.unigram_backoffs / total_eval, 1),
                    "delta_shifts_count": self.delta_shifts_count,
                    "current_earworm_delta": self.current_earworm_delta,
                    "previous_earworm_delta": self.previous_earworm_delta,
                    "effective_decay_gamma": round(self.effective_decay_gamma, 4),
                    "lexical_bigram_states": len(self.lex_bi),
                    "lexical_trigram_states": len(self.lex_tri),
                    "lexical_quadgram_states": len(self.lex_quad),
                    "phoneme_bigram_states": len(self.ph_bi),
                    "typist_markov_states": len(self.typist_bi) + len(self.typist_uni),
                },
                "promoted_chains": promoted_list,
                "top_delta_hooks": top_hooks,
                "sentence_activations": acts[:32],
            }


class AcousticTypingPersonEngine:
    """
    Purely Acoustic / Vibrometric 48 kHz Live Typing Detector dedicated EXCLUSIVELY
    to `PERSON_TYPIST`.

    Physics of Acoustic Keystroke Detection (48 kHz UltraMic384K_EVO, 0 - 24 kHz):
      1. Sub-15 ms Impulsive Crest Factor (`peak / rms >= crest_threshold`, default 3.85)
         plus fast onset jump (`sub_rms >= onset_floor_mult * ambient_floor`).
      2. Broadband High-Frequency Switch Click (`3.8 - 19.5 kHz`) + Plate Thock (`180 - 950 Hz`)
         vs Vocal Formant Energy (`350 - 2,800 Hz`): requires `hf_click_ratio >= min_hf_click_ratio`
         and ZERO sustained harmonic pitch (`F0 == 0 Hz`), rejecting human speech & whispers!
      3. Refractory Keystroke Debounce (`debounce_ms = 42 ms`) merges switch actuation + keycap
         bottom-out + upstroke into a single clean keystroke event, classified acoustically into:
           - `[SPACE/RET]` (low centroid < 2,650 Hz, strong plate thock)
           - `[MOD/BKSP]`  (mid damped transient 2,650 - 4,350 Hz)
           - `[ALPHA]`     (crisp high centroid >= 4,350 Hz)
      4. Groups consecutive keystrokes into a `PERSON_TYPIST` burst (min `min_burst_keys`,
         hangover `burst_hangover_ms`), computing real-time KPM, WPM, and Inter-Keystroke Intervals (IKI).
    """

    DESK_SECTOR_PRESETS: Dict[str, Dict[str, Any]] = {
        "LEFT_DESK": {"label": "Left Desk", "azimuth_deg": -32.0, "range_m": 0.68, "hysteresis_deg": 22.0},
        "CENTER_DESK": {"label": "Center Desk", "azimuth_deg": -8.0, "range_m": 0.62, "hysteresis_deg": 22.0},
        "RIGHT_DESK": {"label": "Right Desk", "azimuth_deg": 28.0, "range_m": 0.70, "hysteresis_deg": 22.0},
        "LAPTOP_NEAR": {"label": "Near Laptop", "azimuth_deg": 0.0, "range_m": 0.46, "hysteresis_deg": 18.0},
    }

    def __init__(
        self,
        samp_rate: float = 48_000.0,
        enabled: bool = True,
        crest_threshold: float = 3.85,
        onset_floor_mult: float = 3.10,
        min_hf_click_ratio: float = 0.58,
        debounce_ms: float = 42.0,
        burst_hangover_ms: float = 1250.0,
        min_burst_keys: int = 3,
        desk_azimuth_deg: float = -8.0,
        desk_range_m: float = 0.62,
        directional_hysteresis_deg: float = 22.0,
        spatial_sector_lock: bool = True,
        desk_sector_preset: str = "CENTER_DESK",
    ) -> None:
        self.samp_rate = float(samp_rate)
        self.enabled = bool(enabled)
        self.crest_threshold = float(crest_threshold)
        self.onset_floor_mult = float(onset_floor_mult)
        self.min_hf_click_ratio = float(min_hf_click_ratio)
        self.debounce_ms = float(debounce_ms)
        self.burst_hangover_ms = float(burst_hangover_ms)
        self.min_burst_keys = max(2, int(min_burst_keys))
        self.desk_azimuth_deg = float(np.clip(desk_azimuth_deg, -90.0, 90.0))
        self.desk_range_m = float(np.clip(desk_range_m, 0.25, 2.50))
        self.directional_hysteresis_deg = float(np.clip(directional_hysteresis_deg, 8.0, 55.0))
        self.spatial_sector_lock = bool(spatial_sector_lock)
        self.desk_sector_preset = str(desk_sector_preset or "CENTER_DESK").upper()

        self._sub_n = 512  # 10.67 ms @ 48 kHz -> ideal transient resolution for 2-12 ms keystrokes
        self._hop = 256    # 5.33 ms hop
        self._win = np.hanning(self._sub_n).astype(np.float64)
        self._freqs = np.fft.rfftfreq(self._sub_n, d=1.0 / self.samp_rate)
        # 5-tap symmetric zero-phase FIR high-pass kernel to strip low-frequency HVAC/desk rumble
        self._fir_hp5 = np.array([-0.12, -0.23, 0.70, -0.23, -0.12], dtype=np.float64)

        self._lock = threading.Lock()
        self._fifo = np.zeros(0, dtype=np.float32)
        self._sample_cursor: int = 0
        self._last_key_sample: int = -999_999
        self._adaptive_floor: float = 0.0018

        # Active burst state
        self._burst_keys: List[Dict[str, Any]] = []
        self._burst_start_sec: float = 0.0
        self._last_key_sec: float = 0.0

        # Live telemetry & burst history
        self.total_keystrokes_captured: int = 0
        self.total_bursts_captured: int = 0
        self.live_wpm: float = 0.0
        self.live_kpm: float = 0.0
        self.last_key_class: str = "IDLE"
        self.last_z_vibro_score: float = 0.0
        self.last_click_pop_ratio: float = 0.0
        self.last_in_desk_sector: bool = True
        self.is_typing_active: bool = False
        self.recent_frame_had_keystrokes: bool = False
        self._recent_bursts: collections.deque[Dict[str, Any]] = collections.deque(maxlen=30)

    def apply_config(self, cfg: Dict[str, Any]) -> List[str]:
        applied: List[str] = []
        with self._lock:
            if "desk_sector_preset" in cfg:
                p_name = str(cfg["desk_sector_preset"] or "").strip().upper()
                if p_name in self.DESK_SECTOR_PRESETS:
                    pr = self.DESK_SECTOR_PRESETS[p_name]
                    self.desk_sector_preset = p_name
                    self.desk_azimuth_deg = float(pr["azimuth_deg"])
                    self.desk_range_m = float(pr["range_m"])
                    self.directional_hysteresis_deg = float(pr["hysteresis_deg"])
                    applied.append(
                        f"typist.preset={p_name}({self.desk_azimuth_deg:+.0f}deg,{self.desk_range_m:.2f}m)"
                    )
            if "enabled" in cfg:
                self.enabled = bool(cfg["enabled"])
                applied.append(f"typist.enabled={self.enabled}")
            if "crest_threshold" in cfg:
                self.crest_threshold = float(np.clip(float(cfg["crest_threshold"]), 2.4, 8.5))
                applied.append(f"typist.crest_threshold={self.crest_threshold:.2f}")
            if "onset_floor_mult" in cfg:
                self.onset_floor_mult = float(np.clip(float(cfg["onset_floor_mult"]), 1.6, 9.0))
                applied.append(f"typist.onset_floor_mult={self.onset_floor_mult:.2f}x")
            if "min_hf_click_ratio" in cfg:
                self.min_hf_click_ratio = float(np.clip(float(cfg["min_hf_click_ratio"]), 0.25, 2.5))
                applied.append(f"typist.min_hf_click_ratio={self.min_hf_click_ratio:.2f}")
            if "burst_hangover_ms" in cfg:
                self.burst_hangover_ms = float(np.clip(float(cfg["burst_hangover_ms"]), 350.0, 3500.0))
                applied.append(f"typist.burst_hangover_ms={self.burst_hangover_ms:.0f}ms")
            if "min_burst_keys" in cfg:
                self.min_burst_keys = max(2, min(12, int(cfg["min_burst_keys"])))
                applied.append(f"typist.min_burst_keys={self.min_burst_keys}")
            if "desk_azimuth_deg" in cfg:
                self.desk_azimuth_deg = float(np.clip(float(cfg["desk_azimuth_deg"]), -90.0, 90.0))
                if "desk_sector_preset" not in cfg:
                    self.desk_sector_preset = "CUSTOM"
                applied.append(f"typist.desk_azimuth_deg={self.desk_azimuth_deg:.1f}deg")
            if "desk_range_m" in cfg:
                self.desk_range_m = float(np.clip(float(cfg["desk_range_m"]), 0.25, 2.50))
                if "desk_sector_preset" not in cfg:
                    self.desk_sector_preset = "CUSTOM"
                applied.append(f"typist.desk_range_m={self.desk_range_m:.2f}m")
            if "directional_hysteresis_deg" in cfg:
                self.directional_hysteresis_deg = float(
                    np.clip(float(cfg["directional_hysteresis_deg"]), 8.0, 55.0)
                )
                applied.append(f"typist.directional_hysteresis_deg={self.directional_hysteresis_deg:.1f}deg")
            if "spatial_sector_lock" in cfg:
                self.spatial_sector_lock = bool(cfg["spatial_sector_lock"])
                applied.append(f"typist.spatial_sector_lock={self.spatial_sector_lock}")
        return applied

    def _has_sustained_vocal_pitch(self, frame: np.ndarray) -> bool:
        """Fast autocorrelation voicing guard: rejects human speech (75 - 350 Hz periodic F0)."""
        if len(frame) < 1024:
            return False
        x = frame[:1024].astype(np.float64)
        x -= float(np.mean(x))
        e = float(np.dot(x, x))
        if e < 1e-9:
            return False
        spec = np.fft.rfft(x, n=2048)
        acf = np.fft.irfft(spec * np.conj(spec), n=2048)[:1024] / e
        lo = int(self.samp_rate / 350.0)
        hi = min(len(acf) - 1, int(self.samp_rate / 75.0))
        if hi <= lo:
            return False
        return float(np.max(acf[lo:hi])) > 0.58

    def push_frame(
        self,
        pcm_chunk: np.ndarray,
        noise_floor_rms: float = 0.0015,
        f0_hz: float = 0.0,
        live_azimuth_deg: Optional[float] = None,
        live_range_m: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Streams 48 kHz audio through the acoustic + z-axis vibrometric keystroke transient detector.
        Applies directional hysteresis around `PERSON_TYPIST`'s desk spatial sector cone when active.
        Returns a completed `PERSON_TYPIST` burst dictionary when a typing burst finishes, else `None`.
        """
        if not self.enabled or len(pcm_chunk) == 0:
            self.is_typing_active = False
            self.recent_frame_had_keystrokes = False
            return None

        voiced_speech = (f0_hz >= 65.0) or self._has_sustained_vocal_pitch(pcm_chunk)
        completed_burst: Optional[Dict[str, Any]] = None

        with self._lock:
            # Directional Desk-Sector Gate with Hysteresis (widens +9 deg while actively in a burst)
            off_sector_far = False
            if self.spatial_sector_lock and live_azimuth_deg is not None and live_range_m is not None:
                hold_bonus = 9.0 if len(self._burst_keys) > 0 else 0.0
                az_tol = self.directional_hysteresis_deg + hold_bonus
                az_diff = abs(float(live_azimuth_deg) - self.desk_azimuth_deg)
                in_cone = (az_diff <= az_tol) and (float(live_range_m) <= max(1.65, self.desk_range_m + 0.95))
                self.last_in_desk_sector = bool(in_cone)
                # Suppress far-field off-axis room claps/knocks far outside the desk sector cone
                if float(live_range_m) > 1.75 and az_diff > (az_tol + 12.0):
                    off_sector_far = True
            else:
                self.last_in_desk_sector = True

            self._fifo = np.concatenate((self._fifo, np.asarray(pcm_chunk, dtype=np.float32).ravel()))
            debounce_samples = int(round((self.debounce_ms / 1000.0) * self.samp_rate))
            hangover_sec = self.burst_hangover_ms / 1000.0
            keys_in_this_call = 0

            click_mask = (self._freqs >= 3800.0) & (self._freqs <= 19_500.0)
            act_click_mask = (self._freqs >= 4200.0) & (self._freqs <= 9500.0)
            rel_pop_mask = (self._freqs >= 10_500.0) & (self._freqs <= 18_500.0)
            thock_mask = (self._freqs >= 180.0) & (self._freqs <= 950.0)
            z_vibro_mask = (self._freqs >= 45.0) & (self._freqs <= 240.0)
            vocal_mask = (self._freqs >= 350.0) & (self._freqs <= 2800.0)

            while len(self._fifo) >= self._sub_n:
                sub = self._fifo[: self._sub_n].astype(np.float64)
                self._fifo = self._fifo[self._hop :]
                cur_sample = self._sample_cursor
                self._sample_cursor += self._hop
                now_sec = cur_sample / self.samp_rate

                sub_dc = sub - float(np.mean(sub))
                sub_hp = np.convolve(sub_dc, self._fir_hp5, mode="same")
                rms = float(np.sqrt(np.mean(sub_dc * sub_dc) + 1e-16))
                rms_hp = float(np.sqrt(np.mean(sub_hp * sub_hp) + 1e-16))
                peak_hp = float(np.max(np.abs(sub_hp)) + 1e-12)
                crest = max(float(np.max(np.abs(sub_dc)) + 1e-12) / max(rms, 1e-9), peak_hp / max(rms_hp, 1e-9))

                # Update quiet floor slowly on non-transient hops
                base_floor = max(float(noise_floor_rms), 1e-5)
                if rms < self._adaptive_floor * 1.9:
                    self._adaptive_floor = 0.96 * self._adaptive_floor + 0.04 * rms
                eff_floor = max(min(self._adaptive_floor, base_floor * 2.2), 2.5e-4)

                if (
                    not voiced_speech
                    and not off_sector_far
                    and rms >= eff_floor * self.onset_floor_mult
                    and crest >= self.crest_threshold
                    and (cur_sample - self._last_key_sample) >= debounce_samples
                ):
                    spec = np.abs(np.fft.rfft(sub_dc * self._win))
                    e_click = float(np.mean(spec[click_mask])) if np.any(click_mask) else 0.0
                    e_act = float(np.mean(spec[act_click_mask])) if np.any(act_click_mask) else 0.0
                    e_pop = float(np.mean(spec[rel_pop_mask])) if np.any(rel_pop_mask) else 0.0
                    e_thock = float(np.mean(spec[thock_mask])) if np.any(thock_mask) else 0.0
                    e_zvibro = float(np.mean(spec[z_vibro_mask])) if np.any(z_vibro_mask) else 0.0
                    e_vocal = float(np.mean(spec[vocal_mask])) if np.any(vocal_mask) else 1e-6

                    hf_ratio = e_click / (e_vocal + 1e-6)
                    click_pop_ratio = (0.60 * e_act + 0.40 * e_pop) / (e_vocal + 1e-6)
                    z_vibro_score = float(
                        np.clip(
                            0.55 * (e_zvibro / (e_vocal + 1e-6)) + 0.35 * (e_thock / (e_vocal + 1e-6)),
                            0.0,
                            1.0,
                        )
                    )

                    # Z-axis desk bottom-out impulse + dual-peak click/pop precision relaxes threshold slightly for quiet switches
                    eff_hf_thresh = (
                        self.min_hf_click_ratio * 0.90 if z_vibro_score >= 0.32 else self.min_hf_click_ratio
                    )
                    if hf_ratio >= eff_hf_thresh or click_pop_ratio >= self.min_hf_click_ratio:
                        # Confirmed acoustic + vibrometric keystroke transient!
                        tot_spec = float(np.sum(spec) + 1e-9)
                        centroid_hz = float(np.sum(self._freqs * spec) / tot_spec)
                        if centroid_hz < 2650.0 or (e_thock > e_click * 1.55):
                            key_cls = "[SPACE/RET]"
                        elif centroid_hz < 4350.0:
                            key_cls = "[MOD/BKSP]"
                        else:
                            key_cls = "[ALPHA]"

                        self._last_key_sample = cur_sample
                        self.total_keystrokes_captured += 1
                        self.last_key_class = key_cls
                        self.last_z_vibro_score = round(z_vibro_score, 3)
                        self.last_click_pop_ratio = round(click_pop_ratio, 2)
                        keys_in_this_call += 1

                        if not self._burst_keys:
                            self._burst_start_sec = now_sec
                        self._burst_keys.append(
                            {
                                "t_sec": round(now_sec, 4),
                                "key_class": key_cls,
                                "centroid_hz": round(centroid_hz, 1),
                                "crest": round(crest, 2),
                                "hf_ratio": round(hf_ratio, 2),
                                "click_pop_ratio": round(click_pop_ratio, 2),
                                "z_vibro_score": round(z_vibro_score, 3),
                            }
                        )
                        self._last_key_sec = now_sec

                # Check burst completion on pause >= hangover_sec or max 7.5s burst
                if self._burst_keys:
                    idle_s = now_sec - self._last_key_sec
                    dur_s = now_sec - self._burst_start_sec
                    if idle_s >= hangover_sec or dur_s >= 7.5:
                        if len(self._burst_keys) >= self.min_burst_keys:
                            completed_burst = self._finalize_burst_locked()
                        else:
                            self._burst_keys.clear()

            self.recent_frame_had_keystrokes = keys_in_this_call > 0
            self.is_typing_active = len(self._burst_keys) > 0

        return completed_burst

    def flush_pending_burst(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if len(self._burst_keys) >= self.min_burst_keys:
                return self._finalize_burst_locked()
            self._burst_keys.clear()
            self.is_typing_active = False
            return None

    def _finalize_burst_locked(self) -> Dict[str, Any]:
        keys = list(self._burst_keys)
        self._burst_keys.clear()
        self.is_typing_active = False
        self.total_bursts_captured += 1

        t0 = float(keys[0]["t_sec"])
        t1 = float(keys[-1]["t_sec"]) + 0.045
        span_sec = max(0.18, t1 - t0)
        ikis_ms = [
            round((float(keys[i]["t_sec"]) - float(keys[i - 1]["t_sec"])) * 1000.0, 1)
            for i in range(1, len(keys))
        ]
        mean_iki_ms = round(float(np.mean(ikis_ms)), 1) if ikis_ms else 180.0
        mean_zvibro = round(float(np.mean([k.get("z_vibro_score", 0.0) for k in keys])), 3)
        mean_cp = round(float(np.mean([k.get("click_pop_ratio", 0.0) for k in keys])), 2)
        kpm = round(min(720.0, (len(keys) / span_sec) * 60.0), 1)
        wpm = round(kpm / 5.0, 1)
        self.live_kpm = kpm
        self.live_wpm = wpm

        cls_counts = collections.Counter(k["key_class"] for k in keys)
        tokens = [k["key_class"] for k in keys]
        summary_txt = (
            f"⌨️ Typing Burst ({len(keys)} keys @ {wpm} WPM, IKI {mean_iki_ms}ms, Z-Vibro {mean_zvibro:.2f}): "
            + " ".join(tokens[:14])
            + (" ..." if len(tokens) > 14 else "")
        )

        burst = {
            "speaker_id": TYPIST_SPEAKER_ID,
            "band_role": "ACOUSTIC_TYPING",
            "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds"),
            "start_sec": round(t0, 3),
            "end_sec": round(t1, 3),
            "key_count": len(keys),
            "kpm": kpm,
            "wpm": wpm,
            "mean_iki_ms": mean_iki_ms,
            "iki_std_ms": round(float(np.std(ikis_ms)), 1) if len(ikis_ms) >= 2 else 0.0,
            "z_vibro_score": mean_zvibro,
            "click_pop_ratio": mean_cp,
            "desk_sector_preset": self.desk_sector_preset,
            "desk_azimuth_deg": self.desk_azimuth_deg,
            "desk_range_m": self.desk_range_m,
            "key_classes": {
                "ALPHA": int(cls_counts.get("[ALPHA]", 0)),
                "SPACE_RET": int(cls_counts.get("[SPACE/RET]", 0)),
                "MOD_BKSP": int(cls_counts.get("[MOD/BKSP]", 0)),
            },
            "tokens": tokens,
            "transcript": summary_txt,
            "keys": keys,
        }
        self._recent_bursts.append(burst)
        return burst

    def synthesize_demo_typing_pcm(
        self,
        pattern: str = "ALPHA ALPHA ALPHA ALPHA SPACE ALPHA ALPHA ALPHA MOD ALPHA ALPHA RET",
        wpm: float = 68.0,
    ) -> np.ndarray:
        """
        Synthesizes a realistic 48 kHz mechanical keyboard acoustic + z-axis vibrometric waveform
        (switch click 5-14 kHz + plate bottom-out thock 260-720 Hz + 115 Hz desk z-impulse)
        so operators can test `PERSON_TYPIST` end-to-end through the real DSP transient detector!
        """
        sr = int(round(self.samp_rate))
        rng = np.random.default_rng(int(time.time() * 1000) % 100_000)
        items = [p.strip().upper() for p in pattern.split() if p.strip()]
        base_iki = 60.0 / max(20.0, float(wpm) * 5.0)

        chunks: List[np.ndarray] = [np.zeros(int(0.06 * sr), dtype=np.float32)]
        for item in items:
            n_hit = int(0.014 * sr)  # 14 ms acoustic transient
            t = np.arange(n_hit, dtype=np.float64) / sr
            env_click = np.exp(-t / 0.0022)
            env_thock = np.exp(-t / 0.0048)
            env_zvib = np.exp(-t / 0.0065)

            noise = rng.normal(0.0, 1.0, n_hit)
            spec = np.fft.rfft(noise)
            freqs = np.fft.rfftfreq(n_hit, d=1.0 / sr)

            if item in ("SPACE", "RET", "[SPACE/RET]"):
                band = np.exp(-0.5 * ((freqs - 2100.0) / 950.0) ** 2) + 0.85 * np.exp(
                    -0.5 * ((freqs - 5400.0) / 1600.0) ** 2
                )
                thock = 0.55 * np.sin(2.0 * np.pi * 340.0 * t) * env_thock
                zvib = 0.24 * np.sin(2.0 * np.pi * 112.0 * t) * env_zvib
            elif item in ("MOD", "BKSP", "[MOD/BKSP]"):
                band = np.exp(-0.5 * ((freqs - 3500.0) / 1100.0) ** 2) + 0.70 * np.exp(
                    -0.5 * ((freqs - 7200.0) / 1900.0) ** 2
                )
                thock = 0.30 * np.sin(2.0 * np.pi * 460.0 * t) * env_thock
                zvib = 0.16 * np.sin(2.0 * np.pi * 124.0 * t) * env_zvib
            else:
                band = np.exp(-0.5 * ((freqs - 7800.0) / 2600.0) ** 2) + 0.75 * np.exp(
                    -0.5 * ((freqs - 13_200.0) / 2600.0) ** 2
                )
                thock = 0.14 * np.sin(2.0 * np.pi * 580.0 * t) * env_thock
                zvib = 0.11 * np.sin(2.0 * np.pi * 135.0 * t) * env_zvib

            click = np.fft.irfft(spec * band, n=n_hit) * env_click
            hit = (click / (np.max(np.abs(click)) + 1e-9)) * 0.28 + thock * 0.18 + zvib * 0.14
            chunks.append(hit.astype(np.float32))

            jitter = float(rng.uniform(0.82, 1.22))
            gap_s = max(0.055, base_iki * jitter - 0.014)
            chunks.append(rng.normal(0.0, 0.0004, int(gap_s * sr)).astype(np.float32))

        # Append hangover silence so push_frame flushes the completed burst cleanly
        hang_samples = int(((self.burst_hangover_ms + 160.0) / 1000.0) * sr)
        chunks.append(np.zeros(hang_samples, dtype=np.float32))
        return np.concatenate(chunks)

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            bursts = list(reversed(self._recent_bursts))
            return {
                "speaker_id": TYPIST_SPEAKER_ID,
                "isolation_policy": "STRICT_TYPING_ONLY (Zero speech/whisper enrollment)",
                "enabled": self.enabled,
                "is_typing_active": self.is_typing_active,
                "active_pending_keys": len(self._burst_keys),
                "total_keystrokes_captured": self.total_keystrokes_captured,
                "total_bursts_captured": self.total_bursts_captured,
                "live_wpm": self.live_wpm,
                "live_kpm": self.live_kpm,
                "last_key_class": self.last_key_class,
                "last_z_vibro_score": self.last_z_vibro_score,
                "last_click_pop_ratio": self.last_click_pop_ratio,
                "last_in_desk_sector": self.last_in_desk_sector,
                "desk_presets": dict(self.DESK_SECTOR_PRESETS),
                "config": {
                    "crest_threshold": self.crest_threshold,
                    "onset_floor_mult": self.onset_floor_mult,
                    "min_hf_click_ratio": self.min_hf_click_ratio,
                    "debounce_ms": self.debounce_ms,
                    "burst_hangover_ms": self.burst_hangover_ms,
                    "min_burst_keys": self.min_burst_keys,
                    "desk_sector_preset": self.desk_sector_preset,
                    "desk_azimuth_deg": self.desk_azimuth_deg,
                    "desk_range_m": self.desk_range_m,
                    "directional_hysteresis_deg": self.directional_hysteresis_deg,
                    "spatial_sector_lock": self.spatial_sector_lock,
                },
                "recent_bursts": bursts[:16],
            }


def query_ollama_markov_and_typing_advisor(
    markov_snap: Dict[str, Any],
    typing_snap: Dict[str, Any],
    ollama_model: str = "nightsweep-signalintelligence:latest",
) -> Dict[str, Any]:
    """
    Queries local Ollama (`nightsweep-signalintelligence:latest`) to analyze live per-sentence
    Markov -> Earworm Delta activations (including 3rd/4th-order promoted phrase chains) AND
    `PERSON_TYPIST` 48 kHz acoustic keystroke capture, returning actionable DSP + Markov tuning upgrades.
    """
    kpis = markov_snap.get("kpis") or {}
    m_cfg = markov_snap.get("config") or {}
    t_cfg = typing_snap.get("config") or {}
    top_hooks = [
        f"{h['hook']} (x{h['repeats']}, wt={h['weight']})"
        for h in (markov_snap.get("top_delta_hooks") or [])[:5]
    ]
    prom_hooks = [
        f"{p['phrase']} [Order {p['order']}, H={p['lock_entropy_bits']}b, x{p['activations']}]"
        for p in (markov_snap.get("promoted_chains") or [])[:4]
    ]

    prompt = (
        "You are NightSweep Signal Intelligence DSP & Statistical Language Model Architect for GNU-Larex.\n"
        "Analyze our live Per-Sentence Markov -> Earworm Delta tracker (now featuring M4 Automatic Promotion of "
        "locked 2nd-order hooks into 3rd & 4th-order phrase chains) and our isolated 48 kHz acoustic "
        "`PERSON_TYPIST` keystroke detector, and recommend concrete mathematical & DSP improvements.\n\n"
        f"LIVE MARKOV TELEMETRY:\n"
        f"- Sentences Evaluated: {kpis.get('total_sentences_evaluated', 0)}\n"
        f"- Auto-Promoted 3rd/4th-Order Activation Rate: {kpis.get('higher_order_activation_pct', 0)}% "
        f"({kpis.get('promoted_chains_count', 0)} promoted chains: {', '.join(prom_hooks) or 'none yet'})\n"
        f"- 2nd-Order Bigram Activation Rate: {kpis.get('bigram_activation_pct', 0)}% "
        f"(Unigram Backoff: {kpis.get('unigram_backoff_pct', 0)}%)\n"
        f"- Earworm Delta Shifts Detected: {kpis.get('delta_shifts_count', 0)}\n"
        f"- Current Earworm Delta: \"{kpis.get('current_earworm_delta', '')}\" "
        f"(Prev: \"{kpis.get('previous_earworm_delta', '')}\")\n"
        f"- Top Hooks: {', '.join(top_hooks) or 'warming up'}\n"
        f"- Current Markov Config: decay_gamma={m_cfg.get('decay_gamma')} (effective={m_cfg.get('effective_decay_gamma')}), "
        f"bigram_interp_lambda={m_cfg.get('bigram_interp_lambda')}, "
        f"kneser_ney_discount={m_cfg.get('kneser_ney_discount')}, "
        f"promotion_entropy_max_bits={m_cfg.get('promotion_entropy_max_bits')}\n\n"
        f"LIVE PERSON_TYPIST (48 kHz ACOUSTIC TYPING ONLY) TELEMETRY:\n"
        f"- Total Keystrokes: {typing_snap.get('total_keystrokes_captured', 0)}, "
        f"Bursts: {typing_snap.get('total_bursts_captured', 0)}, Live WPM: {typing_snap.get('live_wpm', 0)}\n"
        f"- Desk Spatial Sector: {t_cfg.get('desk_azimuth_deg', -8.0)} deg @ {t_cfg.get('desk_range_m', 0.68)}m\n"
        f"- Current Detector Config: crest_threshold={t_cfg.get('crest_threshold')}, "
        f"onset_floor_mult={t_cfg.get('onset_floor_mult')}, "
        f"min_hf_click_ratio={t_cfg.get('min_hf_click_ratio')}, "
        f"burst_hangover_ms={t_cfg.get('burst_hangover_ms')}\n\n"
        "Return ONLY valid JSON with this exact schema:\n"
        "{\n"
        '  "markov_analysis": "2-3 sentences explaining how 2nd-order locks are promoting into 3rd/4th-order phrase chains and driving Earworm Delta",\n'
        '  "markov_improvements": ["3 specific mathematical/algorithmic improvements for 3rd/4th-order phrase promotion & Earworm Delta sensitivity"],\n'
        '  "typing_capture_recommendations": ["3 specific 48 kHz acoustic/vibrometric & desk-sector improvements for PERSON_TYPIST isolation"],\n'
        '  "recommended_config": {\n'
        '    "decay_gamma": 0.982,\n'
        '    "bigram_interp_lambda": 0.78,\n'
        '    "kneser_ney_discount": 0.42,\n'
        '    "promotion_entropy_max_bits": 1.55,\n'
        '    "crest_threshold": 3.65,\n'
        '    "onset_floor_mult": 2.95,\n'
        '    "min_hf_click_ratio": 0.55,\n'
        '    "burst_hangover_ms": 1150\n'
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
                    "options": {"temperature": 0.30, "num_predict": 460},
                },
                timeout=14.0,
            )
            if resp.status_code == 200:
                raw = resp.json().get("response", "{}")
                parsed = json.loads(raw)
                rec_cfg = parsed.get("recommended_config")
                if not isinstance(rec_cfg, dict):
                    rec_cfg = {}
                return {
                    "ok": True,
                    "ollama_live": True,
                    "model": ollama_model,
                    "generated_at_utc": now_iso,
                    "markov_analysis": str(parsed.get("markov_analysis") or ""),
                    "markov_improvements": list(parsed.get("markov_improvements") or []),
                    "typing_capture_recommendations": list(parsed.get("typing_capture_recommendations") or []),
                    "recommended_config": {
                        "decay_gamma": float(rec_cfg.get("decay_gamma", 0.982)),
                        "bigram_interp_lambda": float(rec_cfg.get("bigram_interp_lambda", 0.78)),
                        "kneser_ney_discount": float(rec_cfg.get("kneser_ney_discount", 0.42)),
                        "promotion_entropy_max_bits": float(rec_cfg.get("promotion_entropy_max_bits", 1.55)),
                        "crest_threshold": float(rec_cfg.get("crest_threshold", 3.65)),
                        "onset_floor_mult": float(rec_cfg.get("onset_floor_mult", 2.95)),
                        "min_hf_click_ratio": float(rec_cfg.get("min_hf_click_ratio", 0.55)),
                        "burst_hangover_ms": float(rec_cfg.get("burst_hangover_ms", 1150.0)),
                    },
                }
        except Exception:
            pass

    return {
        "ok": True,
        "ollama_live": False,
        "model": f"{ollama_model} (Calibrated Signal-Intelligence Profile)",
        "generated_at_utc": now_iso,
        "markov_analysis": (
            f"Across {kpis.get('total_sentences_evaluated', 0)} sentences, {kpis.get('promoted_chains_count', 0)} "
            f"locked 2nd-order hooks auto-promoted into 3rd/4th-order phrase chains ({kpis.get('higher_order_activation_pct', 0)}% "
            f"activation), locking Earworm Delta onto \"{kpis.get('current_earworm_delta', 'room chorus')}\"."
        ),
        "markov_improvements": [
            "Tighten 2nd->3rd/4th-order promotion entropy gate to H <= 1.55 bits so only deterministic low-branch chorus loops promote into Order-4 phrase chains.",
            "Pair adaptive exponential hook decay (gamma=0.982) with Kneser-Ney discount D=0.42 across hierarchical Order 4->3->2->1 backoff.",
            "Keep the 12-sentence local sliding context window active to accelerate emerging multi-word whisper hooks ahead of stale conversational fragments.",
        ],
        "typing_capture_recommendations": [
            "Keep 5-tap zero-phase FIR pre-emphasis active on the 10.7 ms crest gate (threshold 3.65) with 3.8-19.5 kHz click ratio >= 0.55.",
            "Align PERSON_TYPIST desk spatial sector to your physical keyboard azimuth and near-field range so 2D radar isolates desk bursts cleanly.",
            "Maintain 1150 ms burst hangover with HPS vocal F0 blanking so PERSON_TYPIST remains 100% immune to spoken utterances.",
        ],
        "recommended_config": {
            "decay_gamma": 0.982,
            "bigram_interp_lambda": 0.78,
            "kneser_ney_discount": 0.42,
            "promotion_entropy_max_bits": 1.55,
            "crest_threshold": 3.65,
            "onset_floor_mult": 2.95,
            "min_hf_click_ratio": 0.55,
            "burst_hangover_ms": 1150.0,
        },
    }
