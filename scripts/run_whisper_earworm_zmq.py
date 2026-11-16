#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GNU-Larex :: Standalone 4-Sensor Whisper & Earworm Word Prediction Engine
(`WhisperEarwormEnhanced` NightSweep Configuration)
========================================================================
Fuses:
  - Dodotronic UltraMic384K_EVO / Wideband Audio (`96 kHz` / `192 kHz` / `48 kHz`)
    with 40 kHz Ultrasonic Carrier Heterodyne Downconversion
  - `PLUTO_ZMQ  = "tcp://127.0.0.1:5555"` (2.45 GHz Lip/Larynx Micro-Doppler)
  - `RTLSDR_ZMQ = "tcp://127.0.0.1:5556"` (VHF/ISM Throat Tension Microphonics)
  - `HACKRF_ZMQ = "tcp://127.0.0.1:5557"` (Wideband RF Envelope)
  - Real-Time Stateful Butterworth F1/F2 Formant Vocal Mirror -> UDP Port `5005`

Automatically uses `sounddevice` if installed, or falls back seamlessly to
GNU Radio's native PortAudio `audio.source` in `radioconda`.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.larex_dsp import WhisperEarwormEngine, ZMQWhisperSensorBridge

# --- NIGHTSWEEP ENHANCED CONFIGURATION DEFAULTS ---
AUDIO_SR = 96000
SDR_SR = 48000
BLOCK_SIZE = 2048
ULTRASONIC_CARRIER = 40000.0

PLUTO_ZMQ = "tcp://127.0.0.1:5555"   # 2.45 GHz Lip/Larynx Micro-Doppler
RTLSDR_ZMQ = "tcp://127.0.0.1:5556"  # VHF Throat Tension Microphonics
HACKRF_ZMQ = "tcp://127.0.0.1:5557"  # Wideband RF Envelope

UDP_HOST = "127.0.0.1"               # Use --broadcast for 255.255.255.255
MIXER_PORT = 5005


def main() -> None:
    parser = argparse.ArgumentParser(description="GNU-Larex Whisper & Earworm ZMQ Engine")
    parser.add_argument("--audio-sr", type=int, default=AUDIO_SR)
    parser.add_argument("--sdr-sr", type=int, default=SDR_SR)
    parser.add_argument("--block-size", type=int, default=BLOCK_SIZE)
    parser.add_argument("--carrier-hz", type=float, default=ULTRASONIC_CARRIER)
    parser.add_argument("--trigger-mult", type=float, default=2.15)
    parser.add_argument("--hangover-blocks", type=int, default=5)
    parser.add_argument("--broadcast", action="store_true", help="Broadcast UDP to 255.255.255.255")
    parser.add_argument("--mixer-port", type=int, default=MIXER_PORT)
    args = parser.parse_args()

    target_ip = "255.255.255.255" if args.broadcast else UDP_HOST
    engine = WhisperEarwormEngine(
        sr=args.sdr_sr,
        block_size=args.block_size,
        whisper_trigger_mult=args.trigger_mult,
        silence_hangover_blocks=args.hangover_blocks,
    )
    bridge = ZMQWhisperSensorBridge(
        pluto_zmq=PLUTO_ZMQ,
        rtlsdr_zmq=RTLSDR_ZMQ,
        hackrf_zmq=HACKRF_ZMQ,
        udp_host=target_ip,
        mixer_port=args.mixer_port,
        udp_mirror_enabled=True,
        ultrasonic_carrier_hz=args.carrier_hz,
    )

    print(
        f"[GNU-Larex] Whisper & Earworm Word Prediction Engine Active "
        f"(Audio={args.audio_sr} Hz, SDR={args.sdr_sr} Hz, Carrier={args.carrier_hz:.0f} Hz, UDP={target_ip}:{args.mixer_port})"
    )

    try:
        import sounddevice as sd  # type: ignore

        decim = max(1, args.audio_sr // args.sdr_sr)

        def callback(indata, frames, time_info, status):
            p_blk, r_blk, h_blk = bridge.pull_all(args.block_size)
            engine.push_streaming_chunks(
                p_blk,
                r_blk,
                h_blk,
                indata[:, 0],
                audio_sr=args.audio_sr,
                ultrasonic_carrier_hz=args.carrier_hz,
            )
            mirror_audio = engine.synthesize_whisper_mirror(frames, args.audio_sr)
            bridge.broadcast_mirror_audio(mirror_audio)

        with sd.InputStream(
            samplerate=args.audio_sr,
            blocksize=args.block_size * decim,
            channels=1,
            callback=callback,
        ):
            while True:
                time.sleep(0.1)
    except ImportError:
        from gnuradio import audio, gr  # type: ignore

        class _EarwormSink(gr.sync_block):
            def __init__(self, actual_sr: int) -> None:
                gr.sync_block.__init__(self, name="WhisperEarwormSink", in_sig=[np.float32], out_sig=None)
                self.actual_sr = actual_sr

            def work(self, input_items, output_items) -> int:
                x = input_items[0]
                p_blk, r_blk, h_blk = bridge.pull_all(args.block_size)
                engine.push_streaming_chunks(
                    p_blk,
                    r_blk,
                    h_blk,
                    x,
                    audio_sr=self.actual_sr,
                    ultrasonic_carrier_hz=args.carrier_hz,
                )
                mirror = engine.synthesize_whisper_mirror(len(x), self.actual_sr)
                bridge.broadcast_mirror_audio(mirror)
                return len(x)

        tb = gr.top_block("LarexWhisperEarwormStandalone")
        actual_sr = args.audio_sr
        for cand_sr in (args.audio_sr, 192000, 96000, 48000):
            try:
                src = audio.source(cand_sr, "", True)
                actual_sr = cand_sr
                break
            except Exception:
                continue
        tb.connect(src, _EarwormSink(actual_sr))
        tb.start()
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            tb.stop()
            tb.wait()
            bridge.close()


if __name__ == "__main__":
    main()
