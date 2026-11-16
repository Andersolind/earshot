#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GNU-Larex :: Live Auto-Build Hook for Gemini CLI & Antigravity CLI
==================================================================
Triggered automatically after file edits (`PostToolUse` in `.agents/hooks.json`
and `AfterTool` in `.gemini/settings.json`):
  - Rebuilds `web/dist` via Vite whenever `web/src/**` or `web/index.html` changes.
  - Verifies Python bytecode compilation whenever `src/*.py` changes.
  - Persists build telemetry to `recordings/live_autobuild_status.json` and notifies
    the live GNU-Larex server (`http://127.0.0.1:8765/api/self-improve/notify-build`).
  - Emits `{}` on stdout and exits 0 per the CLI lifecycle hook specification.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parent.parent
RECORDINGS_DIR = REPO_ROOT / "recordings"
STATUS_FILE = RECORDINGS_DIR / "live_autobuild_status.json"
NOTIFY_URL = "http://127.0.0.1:8765/api/self-improve/notify-build"


def _extract_target_path(hook_input: Dict[str, Any], cli_file: str = "") -> str:
    if cli_file:
        return cli_file
    # Antigravity CLI PostToolUse format (camelCase)
    tc = hook_input.get("toolCall")
    if isinstance(tc, dict):
        args = tc.get("args")
        if isinstance(args, dict):
            for k in ("Path", "TargetFile", "file_path", "path"):
                if args.get(k):
                    return str(args[k])
    # Gemini CLI AfterTool format (snake_case)
    ti = hook_input.get("tool_input")
    if isinstance(ti, dict):
        for k in ("file_path", "path", "Path", "target_file"):
            if ti.get(k):
                return str(ti[k])
    return ""


def _record_and_notify(event: Dict[str, Any], status_override: str = "") -> None:
    target_status = Path(status_override) if status_override else STATUS_FILE
    try:
        target_status.parent.mkdir(parents=True, exist_ok=True)
        target_status.write_text(json.dumps(event, indent=2), encoding="utf-8")
    except Exception as exc:
        sys.stderr.write(f"status_write_err: {exc}\n")
    try:
        data = json.dumps(event).encode("utf-8")
        req = urllib.request.Request(
            NOTIFY_URL,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=1.5):
            pass
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--file", default="")
    parser.add_argument("--status-file", default="")
    parser.add_argument("--force-ui", action="store_true")
    args, _ = parser.parse_known_args()

    hook_payload: Dict[str, Any] = {}
    if not args.file and not args.force_ui:
        buf_holder = [""]

        def _read_in() -> None:
            try:
                buf_holder[0] = sys.stdin.read()
            except Exception:
                pass

        rd = threading.Thread(target=_read_in, daemon=True)
        rd.start()
        rd.join(timeout=0.35)
        raw_in = buf_holder[0]
        if raw_in and raw_in.strip():
            try:
                hook_payload = json.loads(raw_in)
            except Exception:
                hook_payload = {}

    target_str = _extract_target_path(hook_payload, cli_file=args.file)
    rel_norm = ""
    if target_str:
        t_clean = target_str.strip()
        root_norm = os.path.normcase(os.path.abspath(str(REPO_ROOT)))
        cand_abs = (
            os.path.abspath(t_clean)
            if os.path.isabs(t_clean)
            else os.path.abspath(os.path.join(str(REPO_ROOT), t_clean))
        )
        if os.path.normcase(cand_abs).startswith(root_norm):
            rel_norm = os.path.relpath(cand_abs, str(REPO_ROOT)).replace("\\", "/")
        else:
            rel_norm = t_clean.replace("\\", "/")

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    low_rel = rel_norm.lower()
    is_web_edit = args.force_ui or (
        low_rel.startswith("web/")
        and not low_rel.startswith("web/dist/")
        and not low_rel.startswith("web/node_modules/")
    )
    is_py_edit = low_rel.startswith("src/") and low_rel.endswith(".py")

    if is_web_edit:
        vite_cli = REPO_ROOT / "web" / "node_modules" / "vite" / "bin" / "vite.js"
        if vite_cli.exists():
            t0 = time.perf_counter()
            proc = subprocess.run(
                ["node", str(vite_cli), "build", str(REPO_ROOT / "web")],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=40,
            )
            dur_ms = int(round((time.perf_counter() - t0) * 1000))
            ok = proc.returncode == 0
            lines = (proc.stdout or proc.stderr or "").strip().splitlines()
            summary = " | ".join(lines[-2:]) if lines else ("Vite live build complete" if ok else "Vite build error")
            _record_and_notify(
                {
                    "ok": ok,
                    "trigger": "gemini_cli_live_hook",
                    "changed_file": rel_norm or "web/",
                    "duration_ms": dur_ms,
                    "built_at_utc": now_iso,
                    "summary": summary,
                },
                status_override=args.status_file,
            )
    elif is_py_edit:
        t0 = time.perf_counter()
        ok = True
        summary = f"Syntax verified: {rel_norm}"
        try:
            py_src = (REPO_ROOT / rel_norm).read_text(encoding="utf-8")
            compile(py_src, rel_norm, "exec")
        except Exception as exc:
            ok = False
            summary = f"Syntax check warning: {exc}"
        dur_ms = int(round((time.perf_counter() - t0) * 1000))
        _record_and_notify(
            {
                "ok": ok,
                "trigger": "gemini_cli_py_verify_hook",
                "changed_file": rel_norm,
                "duration_ms": dur_ms,
                "built_at_utc": now_iso,
                "summary": summary,
            },
            status_override=args.status_file,
        )

    # Required PostToolUse / AfterTool JSON response on stdout
    sys.stdout.write("{}\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
