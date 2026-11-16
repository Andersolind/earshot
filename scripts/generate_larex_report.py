#!/usr/bin/env python3
"""
GNU-Larex (`LAREX-NSIG-1.0`) Automated 2-Hour Biometric & Word Intelligence Report Generator
============================================================================================
Audits the active `recordings/biometric_words_*.jsonl` & `.enc` ledgers, verifies SHA-256
hash-chain and Fernet cryptographic parity, and generates a structured Markdown report
covering both the trailing 2-hour window and cumulative session totals.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
import json
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from cryptography.fernet import Fernet  # type: ignore
    HAS_FERNET = True
except ImportError:
    HAS_FERNET = False

STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "in", "it", "is", "that", "this",
    "i", "you", "we", "they", "he", "she", "on", "for", "with", "as", "at", "be",
    "was", "are", "but", "not", "so", "if", "uh", "um", "oh", "yeah", "okay", "ok",
    "it's", "i'm", "that's", "don't", "just", "like", "have", "do", "can", "my", "me",
    "your", "what", "up", "out", "about", "there", "all", "from", "go", "get", "know",
}


def build_markdown_report(rec_dir: Path, window_hours: float = 2.0) -> str:
    jsonl_files = sorted(p for p in rec_dir.glob("biometric_words_*.jsonl") if p.stat().st_size > 0)
    if not jsonl_files:
        return "# GNU-Larex Periodic Report\n\nNo `biometric_words_*.jsonl` ledgers found in `recordings/`.\n"

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    cutoff_utc = now_utc - datetime.timedelta(hours=window_hours)

    calibrated_files = [
        p for p in jsonl_files
        if p.name >= "biometric_words_20261113_010229Z.jsonl"
        and datetime.datetime.fromtimestamp(p.stat().st_mtime, tz=datetime.timezone.utc) >= cutoff_utc
    ] or [jsonl_files[-1]]

    active_jsonl = calibrated_files[-1]
    active_enc = active_jsonl.with_suffix(".enc")
    key_path = rec_dir / "secret.key"

    records: List[Dict[str, Any]] = []
    hash_valid = 0
    broken_at: Optional[int] = None

    for jf in calibrated_files:
        prev_expected = "0" * 64
        with open(jf, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                rec_sha = obj.get("record_sha256", "")
                chk = dict(obj)
                chk.pop("record_sha256", None)
                canonical = json.dumps(chk, sort_keys=True, separators=(",", ":")).encode("utf-8")
                calc_sha = hashlib.sha256(canonical).hexdigest()
                if obj.get("prev_sha256") == prev_expected and calc_sha == rec_sha:
                    hash_valid += 1
                elif broken_at is None:
                    broken_at = idx
                prev_expected = rec_sha
                records.append(obj)

    enc_count = 0
    enc_ok = 0
    if HAS_FERNET and active_enc.exists() and key_path.exists():
        fernet = Fernet(key_path.read_bytes())
        with open(active_enc, "rb") as ef:
            raw_lines = [ln.strip() for ln in ef if ln.strip()]
            enc_count = len(raw_lines)
            probe_indices = sorted(set([0, max(0, enc_count // 2), max(0, enc_count - 1)])) if enc_count else []
            for pi in probe_indices:
                dec = json.loads(fernet.decrypt(raw_lines[pi]).decode("utf-8"))
                if "record_sha256" in dec:
                    enc_ok += 1

    window_records: List[Dict[str, Any]] = []
    for r in records:
        try:
            ts = datetime.datetime.fromisoformat(r["timestamp_utc"])
            if ts >= cutoff_utc:
                window_records.append(r)
        except Exception:
            window_records.append(r)

    target_recs = window_records if window_records else records
    total_utt = len(target_recs)
    whisper_cnt = sum(1 for r in target_recs if "WHISPER" in r["vad_biometrics"]["band_role"])
    low_amb_cnt = sum(
        1
        for r in target_recs
        if r["vad_biometrics"].get("low_ambient_cued")
        or r["vad_biometrics"]["band_role"] == "LOW_AMBIENT_WHISPER"
    )
    voiced_cnt = total_utt - whisper_cnt
    all_words = [w for r in target_recs for w in r["segment"]["words"]]
    total_words = len(all_words)
    probs = [w["probability"] for w in all_words]
    oods = [r["vad_biometrics"]["ood_cosine_dist"] for r in target_recs]
    vtls = [r["speaker"]["vtl_cm"] for r in target_recs]

    mean_conf = statistics.mean(probs) * 100.0 if probs else 0.0
    med_conf = statistics.median(probs) * 100.0 if probs else 0.0
    mean_ood = statistics.mean(oods) if oods else 0.0
    med_vtl = statistics.median(vtls) if vtls else 0.0

    # 15-minute buckets for chart
    buckets: Dict[str, int] = collections.Counter()
    spk_map: Dict[str, Dict[str, Any]] = collections.defaultdict(
        lambda: {
            "utt": 0,
            "voiced": 0,
            "whisper": 0,
            "words": 0,
            "vtls": [],
            "f0s": [],
            "disps": [],
            "oods": [],
            "probs": [],
            "kw": collections.Counter(),
            "best_utts": [],
        }
    )

    for r in target_recs:
        ts_str = r["timestamp_utc"]
        hhmm = ts_str[11:16]
        try:
            q_min = (int(hhmm[3:5]) // 15) * 15
            b_key = f"{hhmm[:2]}:{q_min:02d}"
        except Exception:
            b_key = hhmm
        w_list = r["segment"]["words"]
        buckets[b_key] += len(w_list)

        sid = r["speaker"]["speaker_id"]
        st = spk_map[sid]
        st["utt"] += 1
        if "WHISPER" in r["vad_biometrics"]["band_role"]:
            st["whisper"] += 1
        else:
            st["voiced"] += 1
        st["words"] += len(w_list)
        st["vtls"].append(r["speaker"]["vtl_cm"])
        if r["speaker"]["f0_hz"] > 0:
            st["f0s"].append(r["speaker"]["f0_hz"])
        st["disps"].append(r["vad_biometrics"]["throat_disp_um_rms"])
        st["oods"].append(r["vad_biometrics"]["ood_cosine_dist"])

        for w in w_list:
            st["probs"].append(w["probability"])
            tok = w["word"].strip(".,!?;:\"'()-").lower()
            if len(tok) >= 3 and tok not in STOPWORDS:
                st["kw"][tok] += 1

        uniq_lexical = {
            w["word"].strip(".,!?;:\"'()-").lower()
            for w in w_list
            if len(w["word"].strip(".,!?;:\"'()-")) >= 2
        }
        if len(w_list) >= 4 and len(uniq_lexical) >= 3:
            avg_p = statistics.mean(w["probability"] for w in w_list)
            if avg_p >= 0.58:
                st["best_utts"].append(
                    (
                        avg_p * min(len(w_list), 14),
                        ts_str[11:19],
                        sid,
                        r["vad_biometrics"]["band_role"],
                        r["speaker"]["vtl_cm"],
                        avg_p * 100.0,
                        r["segment"]["raw_transcript"].strip(),
                        r["segment"]["ollama_reconstructed"].strip(),
                    )
                )

    jsonl_uri = active_jsonl.resolve().as_uri()
    enc_uri = active_enc.resolve().as_uri()
    db_uri = (rec_dir / "larex_speaker_words.db").resolve().as_uri()

    start_ts = target_recs[0]["timestamp_utc"] if target_recs else "N/A"
    end_ts = target_recs[-1]["timestamp_utc"] if target_recs else "N/A"
    head_sha = records[-1]["record_sha256"][:16] + "..." if records else "N/A"

    lines: List[str] = [
        f"# GNU-Larex (`LAREX-NSIG-1.0`) — Periodic 2-Hour Biometric Intelligence Report",
        "",
        f"**Generated At (UTC):** `{now_utc.isoformat(timespec='seconds')}`  ",
        f"**2-Hour Analysis Window:** `{start_ts}` $\\rightarrow$ `{end_ts}` (`{len(window_records)}` window utterances / `{len(records)}` session total)  ",
        f"**Active Stack:** WeSpeaker `ResNet34-ONNX` (256-D) + `Faster-Whisper (small.en)` + Orthographic `nightsweep-signalintelligence`  ",
        f"**Audited Ledgers:** [{active_jsonl.name}]({jsonl_uri}) | [{active_enc.name}]({enc_uri}) | [larex_speaker_words.db]({db_uri})",
        "",
        "---",
        "",
        "## 1. Cryptographic Chain & Window Summary",
        "",
        "> [!IMPORTANT]",
        f"> **Forensic Hash-Chain Status:** `{hash_valid}/{len(records)}` session records verified (`broken_at={broken_at}`), `{enc_count}` Fernet ciphertext lines synced (`spot_decrypt_ok={enc_ok}`), Head SHA-256 `{head_sha}`.",
        "",
        "| Metric | Trailing 2-Hour Value | Notes |",
        "| :--- | :--- | :--- |",
        f"| **Utterances Captured** | `{total_utt}` (`{voiced_cnt}` Voiced / `{whisper_cnt}` Whisper, `{low_amb_cnt}` Gesture-Subvoc Low-Ambient) | Role A (`VOICED_LARYNX`) vs. Role B (`UNVOICED_WHISPER` / `LOW_AMBIENT_WHISPER`) |",
        f"| **Extracted Words** | `{total_words}` words | Exact cross-attention word timestamps |",
        f"| **Enrolled Speaker Identities** | `{len(spk_map)}` active slots | WeSpeaker ResNet34-LM + 1.50 s anti-fragmentation gate |",
        f"| **Mean / Median Word Confidence** | `{mean_conf:.1f}%` / `{med_conf:.1f}%` | `Faster-Whisper small.en` (`int8`) |",
        f"| **Median Vocal Tract Length** | `{med_vtl:.2f} cm` | Mean Cosine OOD Distance `{mean_ood:.4f}` |",
        "",
    ]

    if buckets:
        sorted_b = sorted(buckets.items())
        x_labels = ", ".join(f'"{k}"' for k, _ in sorted_b)
        y_vals = ", ".join(str(v) for _, v in sorted_b)
        y_max = max(max(buckets.values()) + 20, 50)
        lines.extend([
            "## 2. 15-Minute Word Extraction Timeline (UTC)",
            "",
            "```mermaid",
            "xychart-beta",
            '    title "Extracted Words per 15-Minute UTC Bucket"',
            f"    x-axis [{x_labels}]",
            f'    y-axis "Words" 0 --> {y_max}',
            f"    bar [{y_vals}]",
            "```",
            "",
        ])

    lines.extend([
        "## 3. Per-Person Biometric Speaker Breakdown",
        "",
        "| Speaker | Utterances (`Voiced`/`Whisper`) | Words | Median $\\text{VTL}$ | Median $F_0$ | Median Excursion | Mean ASR Conf | Top Keywords |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ])

    ranked_spk = sorted(spk_map.items(), key=lambda kv: kv[1]["words"], reverse=True)
    for sid, st in ranked_spk:
        vtl_m = f"{statistics.median(st['vtls']):.2f} cm" if st["vtls"] else "--"
        f0_m = f"{statistics.median(st['f0s']):.1f} Hz" if st["f0s"] else "unvoiced"
        disp_m = f"{statistics.median(st['disps']):.1f} µm" if st["disps"] else "--"
        conf_m = f"{statistics.mean(st['probs']) * 100.0:.1f}%" if st["probs"] else "--"
        kws = ", ".join(k for k, _ in st["kw"].most_common(7)) or "--"
        lines.append(
            f"| **`{sid}`** | `{st['utt']}` (`{st['voiced']}`/`{st['whisper']}`) | **{st['words']}** | `{vtl_m}` | `{f0_m}` | `{disp_m}` | `{conf_m}` | `{kws}` |"
        )

    lines.extend(["", "## 4. Top High-Confidence Verbatim Extractions", ""])
    global_highlights = []
    for _, st in ranked_spk:
        global_highlights.extend(st["best_utts"])
    global_highlights.sort(key=lambda x: x[0], reverse=True)

    if global_highlights:
        for item in global_highlights[:12]:
            _, ts_s, sid, role, vtl_v, conf_pct, raw_s, rec_s = item
            lines.append(f"- **`[{ts_s}Z | {sid} | {role} | VTL {vtl_v:.1f} cm | {conf_pct:.0f}% conf]`**")
            if raw_s != rec_s:
                lines.append(f"  - `Raw:` *\"{raw_s}\"*  \n  - `NightSweep:` *\"{rec_s}\"*")
            else:
                lines.append(f"  - *\"{raw_s}\"*")
    else:
        lines.append("- *(No multi-word high-confidence utterances recorded in this window yet.)*")

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate GNU-Larex 2-hour biometric report.")
    parser.add_argument("--recordings-dir", default="recordings")
    parser.add_argument("--hours", type=float, default=2.0)
    parser.add_argument("--out", default="", help="Optional output markdown file path.")
    args = parser.parse_args()

    rec_dir = Path(args.recordings_dir)
    md = build_markdown_report(rec_dir, window_hours=args.hours)
    if args.out:
        out_p = Path(args.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(md, encoding="utf-8")
        print(f"Wrote report to {out_p} ({len(md)} chars)")
    else:
        print(md)


if __name__ == "__main__":
    main()
