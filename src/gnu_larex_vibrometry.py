#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GNU-Larex: Live Room Audio, Sublevel Vocalization Autotune & RF Vibrometry Cockpit
==================================================================================
Compatible with GNU Radio 3.10+ (radioconda latest) & PyQt5.

Features:
  - Native 384 kHz wideband capture on Dodotronic UltraMic384K_EVO (auto-negotiates
    384k / 192k / 96k / 48k on any Windows microphone via PortAudio).
  - Automatic 1-second Room Noise Floor, Stationary Hum & Gain Calibration ('Autotune')
    on launch and via one-click 'Re-Autotune' button.
  - Real-time Harmonic Product Spectrum (HPS) Vocal Pitch Tracker (F0 Hz -> Musical Note)
    with adjustable Chromatic Pitch-Autotune Clarifier & Harmonic Comb Filter.
  - Side-by-side Live Room Audio vs. Isolated Sublevel Vocalization scopes, 0-4 kHz
    spectrogram waterfall, dual overlay FFT, and 0-192 kHz ultrasonic spectrum.
  - Full SoapySDR RF Micro-Doppler Vibrometry & 4-Channel WAV + CSV Session Recorder.
"""

from __future__ import annotations

import argparse
import math
import os
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import signal
import sys
import tempfile
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_LIB_BIN = REPO_ROOT / "radioconda" / "Library" / "bin"
if os.name == "nt" and _LIB_BIN.exists():
    try:
        os.add_dll_directory(str(_LIB_BIN))
    except Exception:
        pass
    os.environ["PATH"] = f"{_LIB_BIN};{os.environ.get('PATH', '')}"

# Ensure GNU Radio FFTW wisdom & Matplotlib cache directories are always writable
_gr_cache_test = Path(os.environ.get("APPDATA", "")) / ".cache" / "gnuradio"
try:
    _gr_cache_test.mkdir(parents=True, exist_ok=True)
except Exception:
    _rt = Path(tempfile.gettempdir()) / "gnu_larex_runtime"
    (_rt / ".cache" / "gnuradio").mkdir(parents=True, exist_ok=True)
    os.environ["APPDATA"] = str(_rt)
    os.environ.setdefault("MPLCONFIGDIR", str(_rt / "mpl"))

from PyQt5 import Qt, QtCore, QtGui  # type: ignore
import sip  # type: ignore
import numpy as np

from gnuradio import audio, blocks, filter as gr_filter, gr, qtgui  # type: ignore
from gnuradio.fft import window  # type: ignore
from gnuradio.filter import firdes  # type: ignore

from src.larex_biometric_logger import (
    AsyncBiometricWordService,
    BiometricAudioTapBlock,
)
from src.larex_web_backend import LarexEmbeddedWebServer
from src.larex_dsp import (
    BiometricTrackerBlock,
    InfrasonicSonifierBlock,
    MasterExperienceOutputBlock,
    RoomAndSublevelAutotuneBlock,
    SyncSDRFusionBlock,
    Tab3IQMonitorSource,
    UltraMicSourceBlock,
    UltraMicWASAPIDriver,
)

SPEAKER_BADGE_COLORS = {
    "PERSON_ALPHA": "#58a6ff",
    "PERSON_BETA": "#3fb950",
    "PERSON_GAMMA": "#d2a8ff",
    "PERSON_DELTA": "#f0883e",
}

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def freq_to_note_str(freq_hz: float) -> str:
    if freq_hz < 50.0:
        return "--"
    midi = int(round(69.0 + 12.0 * math.log2(freq_hz / 440.0)))
    note = NOTE_NAMES[midi % 12]
    octave = (midi // 12) - 1
    return f"{note}{octave}"


def probe_best_mic_rate(device_name: str = "", prefer_ultrasonic: bool = False) -> tuple[int, bool, bool, str]:
    """
    Negotiate live audio input hardware:
      1. Prefer `UltraMicWASAPIDriver` (WASAPI Exclusive @ 384 kHz for Dodotronic UltraMic384K_EVO,
         bypassing Windows Shared Mode's broken 8:1 downsampler with zero `aO` overruns).
      2. Fall back to GNU Radio `audio.source` for standard non-WASAPI microphones.
    Returns `(mic_samp_rate, has_live_mic, use_wasapi_driver, mic_label)`.
    """
    hw = UltraMicWASAPIDriver.probe_best_hardware(
        device_hint=device_name,
        prefer_ultrasonic=True if not prefer_ultrasonic else True,
    )
    if hw.get("available"):
        # Emit full 384 kHz wideband when UltraMic384K_EVO is attached (or --ultrasonic), else 48 kHz
        use_384k = bool(prefer_ultrasonic or hw.get("is_ultramic"))
        out_sr = int(hw["hw_sample_rate"]) if use_384k else min(48_000, int(hw["hw_sample_rate"]))
        if int(hw["hw_sample_rate"]) % out_sr != 0:
            out_sr = int(hw["hw_sample_rate"])
        lbl = f"{hw['device_name']} [{hw['host_api']}]"
        print(
            f"[GNU-Larex] Probed Live Microphone: {lbl} @ {hw['hw_sample_rate']} Hz (stream={out_sr} Hz)",
            flush=True,
        )
        return out_sr, True, True, lbl

    rates = (384_000, 192_000, 96_000, 48_000) if prefer_ultrasonic else (48_000, 96_000, 192_000, 384_000)
    for candidate_sr in rates:
        try:
            tb = gr.top_block()
            src = audio.source(candidate_sr, device_name, True)
            hd = blocks.head(gr.sizeof_float, max(256, candidate_sr // 50))
            snk = blocks.null_sink(gr.sizeof_float)
            tb.connect(src, hd, snk)
            tb.run()
            del tb
            print(f"[GNU-Larex] Connected Live Room Microphone @ {candidate_sr} Hz!")
            return candidate_sr, True, False, device_name or "PortAudio Default"
        except Exception:
            continue
    return 48_000, False, False, "Simulator (No Mic)"


class GnuLarexVibrometryWindow(gr.top_block, Qt.QWidget):
    """Main GNU Radio 3.10 + PyQt5 Cockpit for Live Room Audio, Sublevel Vocalizations & RF Vibrometry."""

    def __init__(
        self,
        sensor_mode: int = 1,
        mic_device: str = "",
        sdr_args: str = "",
        enable_cw_tx: bool = False,
        rf_freq_mhz: float = 915.0,
        rf_gain: float = 38.0,
        hackrf_freq_mhz: float = 2450.0,
        hackrf_gain: float = 44.0,
        record_enable: bool = False,
        mute_audio: bool = False,
        prefer_ultrasonic: bool = False,
        whisper_model: str = "small.en",
        ollama_model: str = "nightsweep-signalintelligence:latest",
        web_port: int = 8765,
    ) -> None:
        gr.top_block.__init__(
            self,
            "GNU-Larex: Live Room Audio, Sublevel Vocalization Autotune & Biometric Word Log",
            catch_exceptions=True,
        )
        Qt.QWidget.__init__(self)
        self.setWindowTitle(
            "GNU-Larex — Live Room Audio, Sublevel Vocalizations, Biometric VAD & Per-Person Word Log"
        )
        qtgui.util.check_set_qss()

        qss_path = REPO_ROOT / "themes" / "larex_obsidian.qss"
        if qss_path.exists():
            try:
                self.setStyleSheet(qss_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        self.resize(1860, 1060)

        # --------------------------------------------------------------------
        # Negotiate Live Microphone Hardware (e.g. UltraMic384K_EVO @ 384 kHz)
        # --------------------------------------------------------------------
        self.mic_device = str(mic_device)
        (
            self.mic_samp_rate,
            self.has_live_mic,
            self.use_wasapi_ultramic,
            self.mic_hw_label,
        ) = probe_best_mic_rate(self.mic_device, prefer_ultrasonic=prefer_ultrasonic)
        self.baseband_rate = 48_000
        self.decim_mic = max(1, self.mic_samp_rate // self.baseband_rate)

        self.rf_samp_rate = 960_000
        self.acoustic_view_rate = 8_000
        self.breath_rate = 400
        self.decim_rf = self.rf_samp_rate // self.baseband_rate          # 20
        self.decim_view = self.baseband_rate // self.acoustic_view_rate  # 6
        self.decim_breath = self.baseband_rate // self.breath_rate       # 120

        # Sensor Modes:
        #   0 = Live Microphone (Room Audio + Autotuned Sublevel Vocalizations)
        #   1 = Dual Fusion: Live Microphone + Dual SDR (RTL-SDR Blog V4 + HackRF One)
        #   2 = Physiological RF Micro-Doppler Simulator
        self.sensor_mode = int(sensor_mode) if self.has_live_mic else 2
        self.sdr_args = str(sdr_args)
        self.enable_cw_tx = bool(enable_cw_tx)
        self.rf_freq_mhz = float(rf_freq_mhz)
        self.rf_gain = float(rf_gain)
        self.hackrf_freq_mhz = float(hackrf_freq_mhz)
        self.hackrf_gain = float(hackrf_gain)
        self.rf_device_select = 0  # 0=Auto Dual-SDR, 1=RTL-SDR V4, 2=HackRF One

        # NightSweep Recommended Preset: 70% Pitch Autotune + +6.0 dB Sublevel Boost
        self.pitch_autotune_strength = 0.70
        self.sublevel_sensitivity_db = 6.0
        self.room_trim_offset_db = 0.0

        self.subvoc_low_hz = 70.0
        self.subvoc_high_hz = 2800.0
        self.gate_thresh_db = -42.0
        self.subvoc_gain_db = 18.0
        self.breath_carrier_hz = 168.0
        self.breath_mix_gain = 0.35
        # Audio Mix Modes:
        #   0 = Stereo Split (Left: Room Audio | Right: Sublevel Vocalizations)
        #   1 = Pure Autotuned Sublevel Vocalizations (Dual-Mono)
        #   2 = Sublevel Vocalizations + Sonified Breathing
        #   3 = Pure Live Room Audio
        self.audio_mix_mode = 0
        self.record_enable = bool(record_enable)
        self.mute_audio = bool(mute_audio)
        self.whisper_model = str(whisper_model)
        self.ollama_model = str(ollama_model)

        # Async LAREX-NSIG-1.0 Biometric VAD, Per-Person Diarizer, Dual-SDR (RTL-SDR + HackRF), Whisper & Ollama
        self.bio_word_service = AsyncBiometricWordService(
            samp_rate=self.baseband_rate,
            output_dir=str(REPO_ROOT / "recordings"),
            whisper_model=self.whisper_model,
            ollama_model=self.ollama_model,
            enable_logging=True,
            require_biometric_liveness=True,
            use_ollama_repair=True,
            rf_freq_mhz=self.rf_freq_mhz,
            rf_gain=self.rf_gain,
            sdr_args=self.sdr_args,
            hackrf_freq_mhz=self.hackrf_freq_mhz,
            hackrf_gain=self.hackrf_gain,
        )

        # --------------------------------------------------------------------
        # Build UI + DSP Flowgraph
        # --------------------------------------------------------------------
        self.root_layout = Qt.QVBoxLayout(self)
        self.root_layout.setContentsMargins(10, 8, 10, 8)
        self.root_layout.setSpacing(6)

        self._build_header_and_controls()
        self._build_visual_sinks()
        self._build_dsp_blocks()
        self._connect_flowgraph()

        # Start Embedded Flask + SSE Backend for Vue.js Words-Per-Hour, Radar & Ollama UI
        self.web_server = LarexEmbeddedWebServer(
            flowgraph=self,
            bio_service=self.bio_word_service,
            host="127.0.0.1",
            port=web_port,
            ollama_model=self.ollama_model,
        )
        self.web_url = self.web_server.start() or f"http://127.0.0.1:{web_port}"
        self.btn_vue_ui.setToolTip(f"Open Live Vue.js Words/Hour, Spatial Radar & Ollama UI ({self.web_url})")

        # Live Autotune Status Telemetry Timer (updates banner every 200 ms)
        self._status_timer = QtCore.QTimer(self)
        self._status_timer.timeout.connect(self._refresh_autotune_banner)
        self._status_timer.start(200)

    # ========================================================================
    # HEADER, AUTOTUNE TELEMETRY BANNER & CONTROL DECK
    # ========================================================================

    def _build_header_and_controls(self) -> None:
        top_bar = Qt.QHBoxLayout()
        title_lbl = Qt.QLabel(
            "GNU-LAREX  |  Live Room Audio & Autotuned Sublevel Vocalization Cockpit"
        )
        title_lbl.setStyleSheet("font-size: 13pt; font-weight: 700; color: #58a6ff;")
        top_bar.addWidget(title_lbl)
        top_bar.addStretch(1)

        self.btn_vue_ui = Qt.QPushButton("🌐 Vue.js WPH & Radar UI")
        self.btn_vue_ui.setStyleSheet(
            "background-color: #238636; color: #ffffff; font-weight: 700; padding: 6px 14px;"
        )
        self.btn_vue_ui.clicked.connect(lambda: webbrowser.open(self.web_url))
        top_bar.addWidget(self.btn_vue_ui)

        self.btn_autotune = Qt.QPushButton("⚡ Re-Autotune Room Floor & Pitch")
        self.btn_autotune.setStyleSheet(
            "background-color: #1f6feb; color: #ffffff; font-weight: 700; padding: 6px 16px;"
        )
        self.btn_autotune.clicked.connect(self._on_re_autotune_clicked)
        top_bar.addWidget(self.btn_autotune)

        self.chk_mute = Qt.QCheckBox("Mute Speakers (Visual Only)")
        self.chk_mute.setChecked(self.mute_audio)
        self.chk_mute.toggled.connect(self._on_mute_toggled)
        top_bar.addWidget(self.chk_mute)

        self.chk_record = Qt.QCheckBox("REC 4-Ch WAV + CSV")
        self.chk_record.setChecked(self.record_enable)
        self.chk_record.toggled.connect(self.set_record_enable)
        top_bar.addWidget(self.chk_record)

        self.root_layout.addLayout(top_bar)

        # Live Autotune Telemetry Strip
        self.lbl_autotune_status = Qt.QLabel("Initializing Live UltraMic / Room Autotune...")
        self.lbl_autotune_status.setStyleSheet(
            "background-color: #161b22; border: 1px solid #238636; border-radius: 5px; "
            "padding: 6px 12px; color: #3fb950; font-family: 'Consolas', monospace; font-size: 10pt;"
        )
        self.root_layout.addWidget(self.lbl_autotune_status)

        # Control Row
        ctrl_row = Qt.QHBoxLayout()
        ctrl_row.setSpacing(10)

        # --- Group 1: Sensor & Autotune Controls ---
        g1 = Qt.QGroupBox("1. Live Sensor & Vocal Autotune")
        g1_grid = Qt.QGridLayout(g1)

        g1_grid.addWidget(Qt.QLabel("Active Input:"), 0, 0)
        self.cmb_sensor = Qt.QComboBox()
        mic_tag = f"Live Mic ({self.mic_samp_rate // 1000} kHz Wideband)" if self.has_live_mic else "Live Mic (Unavailable)"
        self.cmb_sensor.addItems([
            f"{mic_tag} — Room + Sublevel",
            f"Dual Fusion: {mic_tag} + SDR RF",
            "Physiological RF Radar Simulator",
        ])
        self.cmb_sensor.setCurrentIndex(self.sensor_mode)
        self.cmb_sensor.currentIndexChanged.connect(self.set_sensor_mode)
        g1_grid.addWidget(self.cmb_sensor, 0, 1)

        g1_grid.addWidget(Qt.QLabel("Pitch Autotune:"), 1, 0)
        self.sld_autotune = self._make_slider(
            0, 100, int(self.pitch_autotune_strength * 100), self._on_autotune_slider
        )
        self.lbl_autotune = Qt.QLabel(f"{int(self.pitch_autotune_strength * 100)}%")
        at_h = Qt.QHBoxLayout()
        at_h.addWidget(self.sld_autotune)
        at_h.addWidget(self.lbl_autotune)
        g1_grid.addLayout(at_h, 1, 1)

        g1_grid.addWidget(Qt.QLabel("Sublevel Boost:"), 2, 0)
        self.sld_sub_sens = self._make_slider(
            -12, 24, int(self.sublevel_sensitivity_db), self._on_sub_sens_slider
        )
        self.lbl_sub_sens = Qt.QLabel(f"+{self.sublevel_sensitivity_db:.0f} dB")
        ss_h = Qt.QHBoxLayout()
        ss_h.addWidget(self.sld_sub_sens)
        ss_h.addWidget(self.lbl_sub_sens)
        g1_grid.addLayout(ss_h, 2, 1)

        ctrl_row.addWidget(g1, stretch=3)

        # --- Group 2: Room Trim & Headphone Monitor Matrix ---
        g2 = Qt.QGroupBox("2. Room Audio & Monitor Routing")
        g2_grid = Qt.QGridLayout(g2)

        g2_grid.addWidget(Qt.QLabel("Monitor Output:"), 0, 0)
        self.cmb_mix = Qt.QComboBox()
        self.cmb_mix.addItems([
            "Stereo Split (L: Room Audio | R: Sublevel)",
            "Isolated Sublevel Vocalizations Only",
            "Sublevel Vocalizations + Breath Sonifier",
            "Live Calibrated Room Audio Only",
        ])
        self.cmb_mix.setCurrentIndex(self.audio_mix_mode)
        self.cmb_mix.currentIndexChanged.connect(self.set_audio_mix_mode)
        g2_grid.addWidget(self.cmb_mix, 0, 1)

        g2_grid.addWidget(Qt.QLabel("Room Audio Trim:"), 1, 0)
        self.sld_room_trim = self._make_slider(
            -20, 20, int(self.room_trim_offset_db), self._on_room_trim_slider
        )
        self.lbl_room_trim = Qt.QLabel(f"{self.room_trim_offset_db:+.0f} dB")
        rt_h = Qt.QHBoxLayout()
        rt_h.addWidget(self.sld_room_trim)
        rt_h.addWidget(self.lbl_room_trim)
        g2_grid.addLayout(rt_h, 1, 1)

        g2_grid.addWidget(Qt.QLabel("Breath Sonifier:"), 2, 0)
        self.sld_breath_lvl = self._make_slider(
            0, 120, int(self.breath_mix_gain * 100), self._on_breath_lvl_slider
        )
        self.lbl_breath_lvl = Qt.QLabel(f"{int(self.breath_mix_gain * 100)}%")
        bl_h = Qt.QHBoxLayout()
        bl_h.addWidget(self.sld_breath_lvl)
        bl_h.addWidget(self.lbl_breath_lvl)
        g2_grid.addLayout(bl_h, 2, 1)

        ctrl_row.addWidget(g2, stretch=3)

        # --- Group 3: Dual-SDR RF Vibrometry (RTL-SDR Blog V4 + HackRF One) ---
        g3 = Qt.QGroupBox("3. Dual-SDR RF Vibrometry (RTL-SDR V4 + HackRF)")
        g3_grid = Qt.QGridLayout(g3)

        g3_grid.addWidget(Qt.QLabel("RTL-SDR / HackRF:"), 0, 0)
        freq_row = Qt.QHBoxLayout()
        self.spn_freq = Qt.QDoubleSpinBox()
        self.spn_freq.setRange(24.0, 1766.0)
        self.spn_freq.setDecimals(2)
        self.spn_freq.setSuffix(" MHz")
        self.spn_freq.setToolTip("RTL-SDR Blog V4 Carrier Frequency (MHz) -> RTLSDR_ZMQ :5556")
        self.spn_freq.setValue(self.rf_freq_mhz)
        self.spn_freq.valueChanged.connect(self.set_rf_freq_mhz)
        freq_row.addWidget(self.spn_freq)

        self.spn_hackrf_freq = Qt.QDoubleSpinBox()
        self.spn_hackrf_freq.setRange(1.0, 6000.0)
        self.spn_hackrf_freq.setDecimals(1)
        self.spn_hackrf_freq.setSuffix(" MHz")
        self.spn_hackrf_freq.setToolTip("HackRF One Wideband Carrier Frequency (MHz) -> HACKRF_ZMQ :5557")
        self.spn_hackrf_freq.setValue(self.hackrf_freq_mhz)
        self.spn_hackrf_freq.valueChanged.connect(self.set_hackrf_freq_mhz)
        freq_row.addWidget(self.spn_hackrf_freq)
        g3_grid.addLayout(freq_row, 0, 1)

        g3_grid.addWidget(Qt.QLabel("SDR Gain / Src:"), 1, 0)
        self.sld_rf_gain = self._make_slider(0, 60, int(self.rf_gain), self._on_rf_gain_slider)
        self.lbl_rf_gain = Qt.QLabel(f"{self.rf_gain:.0f} dB")
        self.cmb_rf_dev = Qt.QComboBox()
        self.cmb_rf_dev.addItems(["Dual-SDR", "RTL-SDR V4", "HackRF One"])
        self.cmb_rf_dev.setCurrentIndex(self.rf_device_select)
        self.cmb_rf_dev.currentIndexChanged.connect(self._on_rf_device_changed)
        self.btn_sdr_reconnect = Qt.QPushButton("↻")
        self.btn_sdr_reconnect.setFixedWidth(28)
        self.btn_sdr_reconnect.setToolTip("Hot-reconnect RTL-SDR Blog V4 & HackRF One USB streams")
        self.btn_sdr_reconnect.clicked.connect(self._on_reconnect_sdrs_clicked)
        rg_h = Qt.QHBoxLayout()
        rg_h.addWidget(self.sld_rf_gain)
        rg_h.addWidget(self.lbl_rf_gain)
        rg_h.addWidget(self.cmb_rf_dev)
        rg_h.addWidget(self.btn_sdr_reconnect)
        g3_grid.addLayout(rg_h, 1, 1)

        g3_grid.addWidget(Qt.QLabel("Breath Pitch:"), 2, 0)
        self.sld_carrier = self._make_slider(80, 360, int(self.breath_carrier_hz), self._on_carrier_slider)
        self.lbl_carrier = Qt.QLabel(f"{self.breath_carrier_hz:.0f} Hz")
        cp_h = Qt.QHBoxLayout()
        cp_h.addWidget(self.sld_carrier)
        cp_h.addWidget(self.lbl_carrier)
        g3_grid.addLayout(cp_h, 2, 1)

        ctrl_row.addWidget(g3, stretch=3)
        self.root_layout.addLayout(ctrl_row)

    @staticmethod
    def _make_slider(min_v: int, max_v: int, init_v: int, callback) -> Qt.QSlider:
        sld = Qt.QSlider(QtCore.Qt.Horizontal)
        sld.setRange(min_v, max_v)
        sld.setValue(init_v)
        sld.valueChanged.connect(callback)
        return sld

    # ========================================================================
    # DSP FLOWGRAPH CONSTRUCTION
    # ========================================================================

    def _build_dsp_blocks(self) -> None:
        # --- A. Live Microphone Pipeline (384 kHz UltraMic384K_EVO WASAPI Exclusive -> 48 kHz) ---
        self._null_mic_raw = None
        if self.has_live_mic and self.use_wasapi_ultramic:
            self.mic_src = UltraMicSourceBlock(
                device_hint=self.mic_device,
                output_rate=self.mic_samp_rate,
                chunk_ms=20.0,
            )
        elif self.has_live_mic:
            self.mic_src = audio.source(self.mic_samp_rate, self.mic_device, True)
        else:
            self._null_mic_raw = blocks.null_source(gr.sizeof_float)
            self.mic_src = blocks.throttle(gr.sizeof_float, self.mic_samp_rate, True)

        if self.decim_mic > 1:
            mic_lpf_taps = firdes.low_pass(
                1.0, self.mic_samp_rate, 18_000.0, 4_000.0, window.WIN_KAISER, 6.76
            )
            self.decim_mic_48k = gr_filter.fir_filter_fff(self.decim_mic, mic_lpf_taps)
        else:
            self.decim_mic_48k = blocks.multiply_const_ff(1.0)

        self.room_sublevel_autotune = RoomAndSublevelAutotuneBlock(
            samp_rate=self.baseband_rate,
            pitch_autotune_strength=self.pitch_autotune_strength,
            sublevel_sensitivity_db=self.sublevel_sensitivity_db,
            room_trim_offset_db=self.room_trim_offset_db,
        )

        # --- B. Single-Clock Synchronous Dual-SDR Fusion + Decoupled Tab 3 I/Q Monitor ---
        self.use_rf_chain = True
        self.rf_fusion = SyncSDRFusionBlock(
            samp_rate=self.baseband_rate,
            sensor_mode=self.sensor_mode,
            rf_device_select=self.rf_device_select,
            rf_freq_mhz=self.rf_freq_mhz,
            gate_thresh_db=self.gate_thresh_db,
            gain_db=self.subvoc_gain_db,
            enable_cw_tx=self.enable_cw_tx,
            shared_sdr_stream=self.bio_word_service.sdr_radar,
            shared_hackrf_stream=self.bio_word_service.hackrf_stream,
        )
        self.tab3_iq_src = Tab3IQMonitorSource(
            baseband_rate=self.baseband_rate,
            sensor_mode=self.sensor_mode,
            rf_device_select=self.rf_device_select,
            rf_freq_mhz=self.rf_freq_mhz,
            shared_sdr_stream=self.bio_word_service.sdr_radar,
            shared_hackrf_stream=self.bio_word_service.hackrf_stream,
        )

        # --- C. Sensor Fusion Weights (Mic Sublevel vs RF Doppler Sublevel) ---
        mic_w, rf_w = self._compute_fusion_weights(self.sensor_mode)
        self.weight_mic_sub = blocks.multiply_const_ff(mic_w)
        self.weight_rf_sub = blocks.multiply_const_ff(rf_w)
        self.sum_sublevel = blocks.add_ff()

        # --- D. 0 - 4000 Hz Zoom Decimators for Waterfall & Overlay FFT ---
        view_taps = firdes.low_pass(
            1.0, self.baseband_rate, 3_600.0, 400.0, window.WIN_HAMMING, 6.76
        )
        self.decim_view_room = gr_filter.fir_filter_fff(self.decim_view, view_taps)
        self.decim_view_sub = gr_filter.fir_filter_fff(self.decim_view, view_taps)

        # --- E. Infrasonic / Breathing Branch & Biometrics ---
        infra_taps = firdes.low_pass(
            1.0, self.baseband_rate, 16.0, 12.0, window.WIN_HAMMING, 6.76
        )
        self.lpf_infrasonic = gr_filter.fir_filter_fff(1, infra_taps)
        self.infra_sonifier = InfrasonicSonifierBlock(
            samp_rate=self.baseband_rate,
            carrier_hz=self.breath_carrier_hz,
            vad_thresh_db=self.gate_thresh_db,
        )
        self.null_infra_vad = blocks.null_sink(gr.sizeof_float)

        stage1_taps = firdes.low_pass(
            1.0, self.baseband_rate, 120.0, 80.0, window.WIN_HAMMING, 6.76
        )
        self.decim_breath_s1 = gr_filter.fir_filter_fff(self.decim_breath, stage1_taps)
        resp_taps = firdes.low_pass(
            1.0, self.breath_rate, 2.0, 1.2, window.WIN_KAISER, 6.76
        )
        self.lpf_resp_wave = gr_filter.fir_filter_fff(1, resp_taps)
        self.biometrics = BiometricTrackerBlock(samp_rate=self.breath_rate)
        self.bio_tap = BiometricAudioTapBlock(service=self.bio_word_service)

        # --- F. Master Monitor Router & 4-Channel WAV/CSV Recorder ---
        # Note: Input 0 = Sublevel Vocalizations, Input 1 = Secondary (Room Audio or Breath)
        # We route Room Audio vs Sonified Breath via dynamic multipliers into Master Matrix!
        r_mon_w, b_mon_w, m_mode = self._compute_monitor_routing(self.audio_mix_mode)
        self.weight_mon_room = blocks.multiply_const_ff(r_mon_w)
        self.weight_mon_breath = blocks.multiply_const_ff(b_mon_w)
        self.sum_aux_mon = blocks.add_ff()

        self.master_out = MasterExperienceOutputBlock(
            samp_rate=self.baseband_rate,
            audio_mix_mode=m_mode,
            breath_mix_gain=1.0,
            record_enable=self.record_enable,
            recordings_dir=str(REPO_ROOT / "recordings"),
        )
        self.master_out.bio_hook = self._on_audio_frame_for_biometric_asr
        self.bio_word_service.talkback.tx_audio_callback = self._emit_midair_talkback_pcm

        mute_gain = 0.0 if self.mute_audio else 1.0
        self.spk_gate_l = blocks.multiply_const_ff(mute_gain)
        self.spk_gate_r = blocks.multiply_const_ff(mute_gain)

        try:
            # ok_to_block=False when live mic paces graph (eliminates two-clock PortAudio overruns!)
            self.audio_out = audio.sink(self.baseband_rate, "", not self.has_live_mic)
            self.null_l = None
            self.null_r = None
        except Exception as exc:
            print(f"[GNU-Larex] Speaker output unavailable ({exc}) -> visual-only mode.")
            self.audio_out = None
            self.null_l = blocks.null_sink(gr.sizeof_float)
            self.null_r = blocks.null_sink(gr.sizeof_float)

    def _compute_fusion_weights(self, sensor_mode: int) -> tuple[float, float]:
        if sensor_mode == 0:
            return 1.0, 0.0
        if sensor_mode == 1:
            # Keep full 0 dB live microphone sublevel clarity when passive RX SDRs are used without CW TX
            return (0.72, 0.55) if self.enable_cw_tx else (1.0, 0.35)
        return 0.0, 1.0

    def _compute_monitor_routing(self, mix_idx: int) -> tuple[float, float, int]:
        # Maps UI Monitor Output dropdown -> (room_weight, breath_weight, MasterOutputCore.mode)
        if mix_idx == 0:
            # Stereo Split: Left = Calibrated Room Audio, Right = Autotuned Sublevel -> mode 4
            return 1.0, 0.0, 4
        if mix_idx == 1:
            # Isolated Sublevel Vocalizations Only (Dual-Mono)
            return 0.0, 0.0, 2
        if mix_idx == 2:
            # Sublevel + Sonified Breathing Blend
            return 0.0, self.breath_mix_gain, 1
        # Live Calibrated Room Audio Only
        return 1.0, 0.0, 3

    # ========================================================================
    # LIVE METERS & 3-TAB VISUALIZATION COCKPIT
    # ========================================================================

    def _build_visual_sinks(self) -> None:
        # Telemetry Number Meters Strip
        bio_box = Qt.QGroupBox("Live Room, Pitch & Sublevel Telemetry")
        bio_row = Qt.QHBoxLayout(bio_box)

        self.num_room_db = qtgui.number_sink(gr.sizeof_float, 0.15, qtgui.NUM_GRAPH_HORIZ, 1)
        self.num_room_db.set_update_time(0.12)
        self.num_room_db.set_title("Room Audio Level")
        self.num_room_db.set_label(0, "Mic Input")
        self.num_room_db.set_unit(0, "dBFS")
        self.num_room_db.set_min(0, -90.0)
        self.num_room_db.set_max(0, 0.0)
        self.num_room_db.set_color(0, "#58a6ff", "#161b22")
        bio_row.addWidget(sip.wrapinstance(self.num_room_db.qwidget(), Qt.QWidget))

        self.num_f0 = qtgui.number_sink(gr.sizeof_float, 0.15, qtgui.NUM_GRAPH_HORIZ, 1)
        self.num_f0.set_update_time(0.10)
        self.num_f0.set_title("Autotuned Vocal Pitch")
        self.num_f0.set_label(0, "Tracked F0")
        self.num_f0.set_unit(0, "Hz")
        self.num_f0.set_min(0, 0.0)
        self.num_f0.set_max(0, 400.0)
        self.num_f0.set_color(0, "#d2a8ff", "#161b22")
        bio_row.addWidget(sip.wrapinstance(self.num_f0.qwidget(), Qt.QWidget))

        self.num_vad = qtgui.number_sink(gr.sizeof_float, 0.10, qtgui.NUM_GRAPH_HORIZ, 1)
        self.num_vad.set_update_time(0.08)
        self.num_vad.set_title("Sublevel Vocal Activity")
        self.num_vad.set_label(0, "Subvoc VAD")
        self.num_vad.set_unit(0, "")
        self.num_vad.set_min(0, 0.0)
        self.num_vad.set_max(0, 1.0)
        self.num_vad.set_color(0, "#f0883e", "#161b22")
        bio_row.addWidget(sip.wrapinstance(self.num_vad.qwidget(), Qt.QWidget))

        self.num_bpm = qtgui.number_sink(gr.sizeof_float, 0.2, qtgui.NUM_GRAPH_HORIZ, 1)
        self.num_bpm.set_update_time(0.20)
        self.num_bpm.set_title("Respiration Rate")
        self.num_bpm.set_label(0, "Breathing")
        self.num_bpm.set_unit(0, "BPM")
        self.num_bpm.set_min(0, 0.0)
        self.num_bpm.set_max(0, 40.0)
        self.num_bpm.set_color(0, "#3fb950", "#161b22")
        bio_row.addWidget(sip.wrapinstance(self.num_bpm.qwidget(), Qt.QWidget))

        self.num_bio_vad = qtgui.number_sink(gr.sizeof_float, 0.10, qtgui.NUM_GRAPH_HORIZ, 1)
        self.num_bio_vad.set_update_time(0.08)
        self.num_bio_vad.set_title("Biometric Liveness VAD")
        self.num_bio_vad.set_label(0, "Bio-Fused")
        self.num_bio_vad.set_unit(0, "")
        self.num_bio_vad.set_min(0, 0.0)
        self.num_bio_vad.set_max(0, 1.0)
        self.num_bio_vad.set_color(0, "#2ea043", "#161b22")
        bio_row.addWidget(sip.wrapinstance(self.num_bio_vad.qwidget(), Qt.QWidget))

        self.root_layout.addWidget(bio_box)

        # Horizontal Splitter: Left = Multi-Tab DSP Scopes | Right = Per-Person Biometric Word Ledger
        self.main_splitter = Qt.QSplitter(QtCore.Qt.Horizontal)
        self.tabs = Qt.QTabWidget()
        self.main_splitter.addWidget(self.tabs)
        self.main_splitter.addWidget(self._build_biometric_word_panel())
        self.main_splitter.setStretchFactor(0, 63)
        self.main_splitter.setStretchFactor(1, 37)
        self.root_layout.addWidget(self.main_splitter, stretch=1)

        # --- TAB 1: LIVE ROOM AUDIO VS. SUBLEVEL VOCALIZATIONS (SPLIT COCKPIT) ---
        tab1 = Qt.QWidget()
        t1_vbox = Qt.QVBoxLayout(tab1)

        scopes_hbox = Qt.QHBoxLayout()

        self.time_room = qtgui.time_sink_f(
            2400,
            self.baseband_rate,
            "LIVE ROOM AUDIO WAVEFORM (Calibrated Room Microphone — 50 ms)",
            1,
        )
        self.time_room.set_update_time(0.05)
        self.time_room.set_y_axis(-1.0, 1.0)
        self.time_room.set_line_label(0, "Calibrated Room Audio")
        self.time_room.set_line_color(0, "cyan")
        scopes_hbox.addWidget(sip.wrapinstance(self.time_room.qwidget(), Qt.QWidget), stretch=1)

        self.time_subvoc = qtgui.time_sink_f(
            2400,
            self.baseband_rate,
            "ISOLATED SUBLEVEL VOCALIZATIONS & VAD GATE (Autotuned — 50 ms)",
            2,
        )
        self.time_subvoc.set_update_time(0.05)
        self.time_subvoc.set_y_axis(-1.0, 1.0)
        self.time_subvoc.set_line_label(0, "Autotuned Sublevel Vocalizations")
        self.time_subvoc.set_line_color(0, "yellow")
        self.time_subvoc.set_line_label(1, "Sublevel VAD Gate")
        self.time_subvoc.set_line_color(1, "red")
        self.time_subvoc.set_line_width(1, 2)
        scopes_hbox.addWidget(sip.wrapinstance(self.time_subvoc.qwidget(), Qt.QWidget), stretch=1)

        t1_vbox.addLayout(scopes_hbox, stretch=2)

        self.waterfall_subvoc = qtgui.waterfall_sink_f(
            1024,
            window.WIN_BLACKMAN_hARRIS,
            0.0,
            self.acoustic_view_rate,
            "SUBLEVEL VOCALIZATION SPECTROGRAM WATERFALL (0 - 4000 Hz)",
            1,
        )
        self.waterfall_subvoc.set_update_time(0.05)
        self.waterfall_subvoc.enable_axis_labels(True)
        self.waterfall_subvoc.set_intensity_range(-95.0, -5.0)
        self.waterfall_subvoc.set_color_map(
            0,
            qtgui.INTENSITY_COLOR_MAP_TYPE_VIRIDIS
            if hasattr(qtgui, "INTENSITY_COLOR_MAP_TYPE_VIRIDIS")
            else 0,
        )
        t1_vbox.addWidget(sip.wrapinstance(self.waterfall_subvoc.qwidget(), Qt.QWidget), stretch=3)

        self.freq_compare = qtgui.freq_sink_f(
            1024,
            window.WIN_BLACKMAN_hARRIS,
            0.0,
            self.acoustic_view_rate,
            "OVERLAY SPECTRUM: Cyan = Live Room Audio  |  Yellow = Isolated Sublevel Vocalizations (0 - 4000 Hz)",
            2,
        )
        self.freq_compare.set_update_time(0.06)
        self.freq_compare.set_y_axis(-105.0, 5.0)
        self.freq_compare.set_line_label(0, "Live Room Audio")
        self.freq_compare.set_line_color(0, "cyan")
        self.freq_compare.set_line_alpha(0, 0.65)
        self.freq_compare.set_line_label(1, "Autotuned Sublevel Vocalizations")
        self.freq_compare.set_line_color(1, "yellow")
        self.freq_compare.set_line_width(1, 2)
        t1_vbox.addWidget(sip.wrapinstance(self.freq_compare.qwidget(), Qt.QWidget), stretch=2)

        self.tabs.addTab(tab1, "1. Live Room Audio vs. Sublevel Vocalizations")

        # --- TAB 2: WIDEBAND ULTRAMIC SPECTRUM (0 - 192 kHz) & RESPIRATION MONITOR ---
        tab2 = Qt.QWidget()
        t2_vbox = Qt.QVBoxLayout(tab2)

        self.freq_wideband = qtgui.freq_sink_f(
            2048,
            window.WIN_BLACKMAN_hARRIS,
            0.0,
            self.mic_samp_rate,
            f"WIDEBAND ULTRAMIC / ACOUSTIC SPECTRUM (0 - {self.mic_samp_rate // 2000} kHz)",
            1,
        )
        self.freq_wideband.set_update_time(0.08)
        self.freq_wideband.set_y_axis(-130.0, -10.0)
        self.freq_wideband.set_line_label(0, f"Raw Wideband Mic ({self.mic_samp_rate // 1000} kHz)")
        self.freq_wideband.set_line_color(0, "cyan")
        t2_vbox.addWidget(sip.wrapinstance(self.freq_wideband.qwidget(), Qt.QWidget), stretch=1)

        self.time_resp = qtgui.time_sink_f(
            self.breath_rate * 10,
            self.breath_rate,
            "Respiration & Macro-Displacement Waveform (10-Second Window, um)",
            1,
        )
        self.time_resp.set_update_time(0.08)
        self.time_resp.enable_autoscale(True)
        self.time_resp.set_y_label("Displacement", "um")
        self.time_resp.set_line_label(0, "Respiration Wave (0.08 - 2.0 Hz)")
        self.time_resp.set_line_color(0, "green")
        self.time_resp.set_line_width(0, 2)
        t2_vbox.addWidget(sip.wrapinstance(self.time_resp.qwidget(), Qt.QWidget), stretch=1)

        self.tabs.addTab(
            tab2, f"2. Wideband Ultrasonic Spectrum (0-{self.mic_samp_rate // 2000} kHz) & Respiration"
        )

        # --- TAB 3: RF RADAR I/Q PHASOR & BASEBAND SPECTRUM ---
        tab3 = Qt.QWidget()
        t3_hbox = Qt.QHBoxLayout(tab3)

        self.const_iq = qtgui.const_sink_c(
            1024, "RF Radar I/Q Phasor Arc: Raw vs. Clutter-Cancelled", 2
        )
        self.const_iq.set_update_time(0.08)
        self.const_iq.set_x_axis(-1.5, 1.5)
        self.const_iq.set_y_axis(-1.5, 1.5)
        self.const_iq.set_line_label(0, "Raw Decimated I/Q")
        self.const_iq.set_line_color(0, "red")
        self.const_iq.set_line_label(1, "Centered Radar Arc")
        self.const_iq.set_line_color(1, "green")
        t3_hbox.addWidget(sip.wrapinstance(self.const_iq.qwidget(), Qt.QWidget), stretch=1)

        self.freq_rf = qtgui.freq_sink_c(
            1024,
            window.WIN_BLACKMAN_hARRIS,
            self.rf_freq_mhz * 1e6,
            self.baseband_rate,
            "Complex Baseband Micro-Doppler Spectrum",
            1,
        )
        self.freq_rf.set_update_time(0.08)
        self.freq_rf.set_y_axis(-120.0, 10.0)
        self.freq_rf.set_line_label(0, "Centered Baseband I/Q")
        t3_hbox.addWidget(sip.wrapinstance(self.freq_rf.qwidget(), Qt.QWidget), stretch=1)

        self.tabs.addTab(tab3, "3. RF Radar I/Q Phasor & Baseband")

    def _build_biometric_word_panel(self) -> Qt.QWidget:
        panel = Qt.QGroupBox("LAREX-NSIG-1.0  |  Per-Person Biometric Word Ledger")
        vbox = Qt.QVBoxLayout(panel)
        vbox.setSpacing(6)

        # Live Biometric VAD & ASR Liveness Banner
        self.lbl_bio_asr_status = Qt.QLabel("Initializing Faster-Whisper & NightSweep Biometric VAD...")
        self.lbl_bio_asr_status.setWordWrap(True)
        self.lbl_bio_asr_status.setStyleSheet(
            "background-color: #161b22; border: 1px solid #30363d; border-radius: 5px; "
            "padding: 5px 8px; color: #58a6ff; font-family: 'Consolas', monospace; font-size: 9pt;"
        )
        vbox.addWidget(self.lbl_bio_asr_status)

        # Toggle Bar
        ctrl_bar = Qt.QHBoxLayout()
        self.chk_word_log = Qt.QCheckBox("Log Words")
        self.chk_word_log.setChecked(True)
        self.chk_word_log.toggled.connect(self._on_word_log_toggled)
        ctrl_bar.addWidget(self.chk_word_log)

        self.chk_bio_pad = Qt.QCheckBox("Biometric Liveness PAD")
        self.chk_bio_pad.setChecked(True)
        self.chk_bio_pad.toggled.connect(self._on_bio_pad_toggled)
        ctrl_bar.addWidget(self.chk_bio_pad)

        self.chk_ollama_fix = Qt.QCheckBox("Ollama NightSweep")
        self.chk_ollama_fix.setChecked(True)
        self.chk_ollama_fix.toggled.connect(self._on_ollama_toggled)
        ctrl_bar.addWidget(self.chk_ollama_fix)

        self.btn_reset_spk = Qt.QPushButton("↺ Reset Persons")
        self.btn_reset_spk.setStyleSheet("padding: 3px 8px; font-weight: 600;")
        self.btn_reset_spk.clicked.connect(self._on_reset_speakers_clicked)
        ctrl_bar.addWidget(self.btn_reset_spk)
        vbox.addLayout(ctrl_bar)

        # Enrolled Speaker Biometric Roster Summary
        self.lbl_speaker_roster = Qt.QLabel(
            "Enrolled Persons: Waiting for live voiced or whispered speech..."
        )
        self.lbl_speaker_roster.setWordWrap(True)
        self.lbl_speaker_roster.setStyleSheet(
            "background-color: #0d1117; border: 1px solid #21262d; border-radius: 4px; "
            "padding: 5px 8px; color: #c9d1d9; font-family: 'Consolas', monospace; font-size: 9pt;"
        )
        vbox.addWidget(self.lbl_speaker_roster)

        # Live Per-Person Extracted Words Table
        self.tbl_words = Qt.QTableWidget(0, 5)
        self.tbl_words.setHorizontalHeaderLabels([
            "Time",
            "Person",
            "Bio / Mode",
            "Extracted Words (ASR)",
            "NightSweep Reconstructed",
        ])
        self.tbl_words.verticalHeader().setVisible(False)
        self.tbl_words.setEditTriggers(Qt.QAbstractItemView.NoEditTriggers)
        self.tbl_words.setSelectionBehavior(Qt.QAbstractItemView.SelectRows)
        self.tbl_words.setWordWrap(True)
        hdr = self.tbl_words.horizontalHeader()
        hdr.setSectionResizeMode(0, Qt.QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, Qt.QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, Qt.QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(3, Qt.QHeaderView.Stretch)
        hdr.setSectionResizeMode(4, Qt.QHeaderView.Stretch)
        vbox.addWidget(self.tbl_words, stretch=1)

        # Active Forensic Ledger Paths Footer
        led = self.bio_word_service.ledger
        self.lbl_ledger_paths = Qt.QLabel(
            f"🔒 Forensic Sinks: {led.jsonl_path.name}  |  {led.enc_path.name}  |  {led.db_path.name}"
        )
        self.lbl_ledger_paths.setStyleSheet("color: #8b949e; font-size: 8.5pt; font-family: 'Consolas', monospace;")
        vbox.addWidget(self.lbl_ledger_paths)
        return panel

    # ========================================================================
    # FLOWGRAPH CONNECTIONS
    # ========================================================================

    def _connect_flowgraph(self) -> None:
        # 1. Live Wideband Mic -> Wideband Spectrum + 48 kHz Room/Sublevel Autotune
        if self._null_mic_raw is not None:
            self.connect((self._null_mic_raw, 0), (self.mic_src, 0))
        self.connect((self.mic_src, 0), (self.freq_wideband, 0))
        self.connect((self.mic_src, 0), (self.decim_mic_48k, 0))
        self.connect((self.decim_mic_48k, 0), (self.room_sublevel_autotune, 0))

        # Room & Autotune Telemetry Meters + Room Scope
        self.connect((self.room_sublevel_autotune, 0), (self.time_room, 0))
        self.connect((self.room_sublevel_autotune, 2), (self.num_room_db, 0))
        self.connect((self.room_sublevel_autotune, 3), (self.num_f0, 0))
        self.connect((self.room_sublevel_autotune, 4), (self.num_vad, 0))

        # 2 & 3. Single-Clock Synchronous Dual-SDR Fusion + Decoupled Tab 3 I/Q Monitor
        self.connect((self.decim_mic_48k, 0), (self.rf_fusion, 0))
        self.connect((self.room_sublevel_autotune, 1), (self.weight_mic_sub, 0))
        self.connect((self.rf_fusion, 1), (self.weight_rf_sub, 0))
        self.connect((self.weight_mic_sub, 0), (self.sum_sublevel, 0))
        self.connect((self.weight_rf_sub, 0), (self.sum_sublevel, 1))
        disp_source = (self.rf_fusion, 0)

        self.connect((self.tab3_iq_src, 0), (self.const_iq, 0))
        self.connect((self.tab3_iq_src, 1), (self.const_iq, 1))
        self.connect((self.tab3_iq_src, 1), (self.freq_rf, 0))

        # 4. Tab 1 Sublevel Scope, Waterfall & Overlay FFT
        self.connect((self.sum_sublevel, 0), (self.time_subvoc, 0))
        self.connect((self.room_sublevel_autotune, 4), (self.time_subvoc, 1))

        self.connect((self.room_sublevel_autotune, 0), (self.decim_view_room, 0))
        self.connect((self.sum_sublevel, 0), (self.decim_view_sub, 0))

        self.connect((self.decim_view_sub, 0), (self.waterfall_subvoc, 0))
        self.connect((self.decim_view_room, 0), (self.freq_compare, 0))
        self.connect((self.decim_view_sub, 0), (self.freq_compare, 1))

        # 5. Infrasonic Breathing Sonifier, Respiration BPM & 400 Hz Biometric VAD Meter
        self.connect(disp_source, (self.lpf_infrasonic, 0))
        self.connect((self.lpf_infrasonic, 0), (self.infra_sonifier, 0))
        self.connect((self.sum_sublevel, 0), (self.infra_sonifier, 1))
        self.connect((self.infra_sonifier, 1), (self.null_infra_vad, 0))

        self.connect(disp_source, (self.decim_breath_s1, 0))
        self.connect((self.decim_breath_s1, 0), (self.lpf_resp_wave, 0))
        self.connect((self.lpf_resp_wave, 0), (self.biometrics, 0))
        self.connect((self.biometrics, 0), (self.time_resp, 0))
        self.connect((self.biometrics, 1), (self.num_bpm, 0))
        self.connect((self.biometrics, 2), (self.bio_tap, 0))
        self.connect((self.bio_tap, 0), (self.num_bio_vad, 0))

        # 6. Monitor Output Routing & 4-Channel WAV/CSV Recorder
        self.connect((self.room_sublevel_autotune, 0), (self.weight_mon_room, 0))
        self.connect((self.infra_sonifier, 0), (self.weight_mon_breath, 0))
        self.connect((self.weight_mon_room, 0), (self.sum_aux_mon, 0))
        self.connect((self.weight_mon_breath, 0), (self.sum_aux_mon, 1))

        self.connect((self.sum_sublevel, 0), (self.master_out, 0))
        self.connect((self.sum_aux_mon, 0), (self.master_out, 1))
        self.connect((self.room_sublevel_autotune, 0), (self.master_out, 2))
        self.connect((self.room_sublevel_autotune, 4), (self.master_out, 3))

        self.connect((self.master_out, 0), (self.spk_gate_l, 0))
        self.connect((self.master_out, 1), (self.spk_gate_r, 0))

        if self.audio_out is not None:
            self.connect((self.spk_gate_l, 0), (self.audio_out, 0))
            self.connect((self.spk_gate_r, 0), (self.audio_out, 1))
        else:
            self.connect((self.spk_gate_l, 0), (self.null_l, 0))
            self.connect((self.spk_gate_r, 0), (self.null_r, 0))

    # ========================================================================
    # LIVE CALLBACKS & AUTOTUNE STATUS REFRESH
    # ========================================================================

    def _refresh_autotune_banner(self) -> None:
        if self.mute_audio and not self.master_out.is_transmitting_talkback:
            self.spk_gate_l.set_k(0.0)
            self.spk_gate_r.set_k(0.0)
        self._poll_biometric_word_panel()

        c = self.room_sublevel_autotune.core
        if not self.has_live_mic and self.sensor_mode == 2:
            self.lbl_autotune_status.setText(
                "MODE: Physiological RF Micro-Doppler Simulator  |  Switch dropdown to connect Live Mic / SDR"
            )
            return

        if not c.autotune_complete:
            self.lbl_autotune_status.setText(
                f"⏳ AUTOTUNING LIVE SENSOR ({self.mic_samp_rate // 1000} kHz Wideband)... "
                "Profiling ambient room noise floor, stationary hum & optimal sublevel boost..."
            )
            return

        note_str = freq_to_note_str(c.current_f0_hz)
        snap_str = freq_to_note_str(c.snapped_f0_hz) if c.current_f0_hz >= 60.0 else "--"
        f0_disp = f"{c.current_f0_hz:5.1f} Hz ({note_str} -> {snap_str})" if c.current_f0_hz >= 60.0 else "Listening..."
        mic_info_str = f"Live {self.mic_samp_rate // 1000} kHz Mic"
        if self.use_wasapi_ultramic and hasattr(self.mic_src, "driver"):
            drv = self.mic_src.driver
            mic_info_str = (
                f"UltraMic {drv.hw_sample_rate // 1000} kHz WASAPI-Excl "
                f"(xrun:{drv.overrun_count} | US:{drv.ultrasonic_band_dbfs:.0f}dB@{drv.peak_ultrasonic_hz / 1000.0:.1f}kHz)"
            )

        self.lbl_autotune_status.setText(
            f"✅ AUTOTUNED  |  {mic_info_str}  |  "
            f"Room Floor: {c.room_floor_dbfs:5.1f} dBFS  |  "
            f"Live Room: {c.current_room_dbfs:5.1f} dBFS  |  "
            f"Room Trim: +{c.auto_room_gain_db:4.1f} dB  |  "
            f"Sublevel Gain: +{c.auto_subvoc_gain_db + self.sublevel_sensitivity_db:4.1f} dB  |  "
            f"Vocal F0: {f0_disp}"
        )

    def _poll_biometric_word_panel(self) -> None:
        svc = self.bio_word_service
        live_badge = "🟢 LIVENESS OK" if svc.live_liveness_ok else "🔴 PLAYBACK/NO BIO"
        gate_badge = f"🗣️ {svc.live_band_role}" if svc.live_gate_open else "IDLE"
        sp = svc.live_spatial
        mo = svc.live_mouth
        mouth_pct = int(round(float(mo.get("mouth_openness", 0.0)) * 100))
        viseme = str(mo.get("viseme", "REST_CLOSED"))
        b_lfo = float(mo.get("breath_lfo", 0.0))
        rtl_s = svc.sdr_radar
        hrf_s = svc.hackrf_stream
        rtl_badge = (
            f"🟢 RTL-SDR V4 @ {rtl_s.rf_freq_mhz:.1f}MHz ({rtl_s.rf_power_dbfs:.0f}dBFS)"
            if rtl_s.sdr_connected
            else f"🟡 {rtl_s.sdr_label}"
        )
        hrf_badge = (
            f"🟢 HackRF One @ {hrf_s.rf_freq_mhz:.0f}MHz ({hrf_s.rf_power_dbfs:.0f}dBFS)"
            if hrf_s.sdr_connected
            else f"🟡 {hrf_s.sdr_label}"
        )
        self.lbl_bio_asr_status.setText(
            f"{live_badge}  |  VAD: {gate_badge}  |  👄 Mouth: {mouth_pct}% ({viseme})  |  "
            f"Breath LFO: {b_lfo:.3f}  |  Pos: {sp.range_m:.2f}m ({sp.azimuth_deg:+.0f}°)\n"
            f"📡 {rtl_badge}  |  📡 {hrf_badge}  |  Words: {svc.total_words_logged}  |  Web: {self.web_url}"
        )

        # Drain completed per-person word records onto table
        added_rows = False
        while not svc.ui_events.empty():
            try:
                rec = svc.ui_events.get_nowait()
            except Exception:
                break

            row = self.tbl_words.rowCount()
            self.tbl_words.insertRow(row)

            ts_short = str(rec["timestamp_utc"])[11:19]
            spk_id = str(rec["speaker"]["speaker_id"])
            vtl = rec["speaker"]["vtl_cm"]
            role_short = "WHISPER" if "WHISPER" in rec["vad_biometrics"]["band_role"] else "VOICED"
            bpm = rec["vad_biometrics"]["resp_bpm"]
            sp_rec = rec.get("spatial") or {}
            pos_str = f" | {sp_rec.get('range_m', 1.1):.2f}m" if "range_m" in sp_rec else ""
            bio_tag = f"{role_short} {vtl:.1f}cm" + (f" | {bpm:.0f}BPM" if bpm > 0 else "") + pos_str

            words_list = rec["segment"]["words"]
            words_fmt = " ".join(
                f"{w['word']}({int(round(w['probability'] * 100))}%)" for w in words_list
            )
            recon_txt = str(rec["segment"]["ollama_reconstructed"])

            it_time = Qt.QTableWidgetItem(ts_short)
            it_spk = Qt.QTableWidgetItem(spk_id)
            color_hex = SPEAKER_BADGE_COLORS.get(spk_id, "#ffa657")
            it_spk.setForeground(QtGui.QBrush(QtGui.QColor(color_hex)))
            font_b = it_spk.font()
            font_b.setBold(True)
            it_spk.setFont(font_b)

            it_bio = Qt.QTableWidgetItem(bio_tag)
            it_words = Qt.QTableWidgetItem(words_fmt)
            it_recon = Qt.QTableWidgetItem(recon_txt)
            it_recon.setForeground(QtGui.QBrush(QtGui.QColor("#7ee787")))

            self.tbl_words.setItem(row, 0, it_time)
            self.tbl_words.setItem(row, 1, it_spk)
            self.tbl_words.setItem(row, 2, it_bio)
            self.tbl_words.setItem(row, 3, it_words)
            self.tbl_words.setItem(row, 4, it_recon)
            added_rows = True

        if added_rows:
            self.tbl_words.resizeRowsToContents()
            self.tbl_words.scrollToBottom()

            # Refresh speaker biometric roster summary
            if svc.speaker_stats:
                parts = []
                for sid, st in svc.speaker_stats.items():
                    f0_tag = f"{st['f0_hz']:.0f}Hz" if st["f0_hz"] > 0 else "unvoiced"
                    parts.append(
                        f"[{sid}: {st['words']}w | VTL {st['vtl_cm']:.1f}cm | {f0_tag}]"
                    )
                self.lbl_speaker_roster.setText("Enrolled Persons:  " + "   ".join(parts))

    def _emit_midair_talkback_pcm(self, pcm_48k: np.ndarray) -> bool:
        """Emits 48 kHz mid-air acoustic whisper talkback through GNU Radio audio.sink (with half-duplex echo blanking)."""
        if self.audio_out is not None:
            if self.mute_audio:
                # Temporarily open speaker gate for intentional outbound talkback; restored when TX finishes
                self.spk_gate_l.set_k(1.0)
                self.spk_gate_r.set_k(1.0)
            return self.master_out.enqueue_talkback_pcm(pcm_48k, echo_guard_ms=450.0)
        try:
            import io
            import wave
            import winsound  # type: ignore

            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.baseband_rate)
                wf.writeframes((np.clip(pcm_48k, -0.98, 0.98) * 32767.0).astype(np.int16).tobytes())
            winsound.PlaySound(buf.getvalue(), winsound.SND_MEMORY | winsound.SND_ASYNC)
            return True
        except Exception:
            return False

    def _on_audio_frame_for_biometric_asr(self, room: np.ndarray, subvoc: np.ndarray) -> None:
        blended = (0.76 * room + 0.24 * subvoc).astype(np.float32)
        bpm = float(self.biometrics._core.current_bpm)
        disp_pp_um = float(self.biometrics._core.current_disp_pp_um)
        if bpm <= 0.5 and disp_pp_um >= 4.0:
            bpm = 14.0
        # Vocal-band laryngeal/subvoc excursion (70-2800 Hz), physiologically bounded so idle chest breathing never locks VAD
        inst_um = min(85.0, float(np.sqrt(np.mean(subvoc * subvoc) + 1e-16)) * 180.0)
        self.bio_word_service.push_realtime(
            blended, resp_bpm=bpm, throat_disp_um=inst_um
        )

    def _on_word_log_toggled(self, enabled: bool) -> None:
        self.bio_word_service.enable_logging = bool(enabled)

    def _on_bio_pad_toggled(self, enabled: bool) -> None:
        self.bio_word_service.set_require_liveness(bool(enabled))

    def _on_ollama_toggled(self, enabled: bool) -> None:
        self.bio_word_service.use_ollama_repair = bool(enabled)

    def _on_reset_speakers_clicked(self) -> None:
        self.bio_word_service.reset_speakers()
        self.lbl_speaker_roster.setText(
            "Enrolled Persons: Cleared — next speaker will enroll as PERSON_DELTA..."
        )

    def _on_re_autotune_clicked(self) -> None:
        self.room_sublevel_autotune.trigger_autotune()
        self._refresh_autotune_banner()

    def set_sensor_mode(self, mode: int) -> None:
        self.sensor_mode = int(mode)
        mic_w, rf_w = self._compute_fusion_weights(self.sensor_mode)
        self.weight_mic_sub.set_k(mic_w)
        self.weight_rf_sub.set_k(rf_w)
        self.rf_fusion.set_sensor_mode(self.sensor_mode)
        self.tab3_iq_src.set_sensor_mode(self.sensor_mode)

    def _on_autotune_slider(self, val: int) -> None:
        self.pitch_autotune_strength = float(val) / 100.0
        self.lbl_autotune.setText(f"{val}%")
        self.room_sublevel_autotune.set_pitch_autotune_strength(self.pitch_autotune_strength)

    def _on_sub_sens_slider(self, val: int) -> None:
        self.sublevel_sensitivity_db = float(val)
        self.lbl_sub_sens.setText(f"{val:+d} dB")
        self.room_sublevel_autotune.set_sublevel_sensitivity_db(self.sublevel_sensitivity_db)

    def _on_room_trim_slider(self, val: int) -> None:
        self.room_trim_offset_db = float(val)
        self.lbl_room_trim.setText(f"{val:+d} dB")
        self.room_sublevel_autotune.set_room_trim_offset_db(self.room_trim_offset_db)

    def set_audio_mix_mode(self, idx: int) -> None:
        self.audio_mix_mode = int(idx)
        r_w, b_w, m_mode = self._compute_monitor_routing(self.audio_mix_mode)
        self.weight_mon_room.set_k(r_w)
        self.weight_mon_breath.set_k(b_w)
        self.master_out.set_audio_mix_mode(m_mode)

    def _on_mute_toggled(self, muted: bool) -> None:
        self.mute_audio = bool(muted)
        g = 0.0 if self.mute_audio else 1.0
        self.spk_gate_l.set_k(g)
        self.spk_gate_r.set_k(g)

    def _on_breath_lvl_slider(self, val: int) -> None:
        self.breath_mix_gain = float(val) / 100.0
        self.lbl_breath_lvl.setText(f"{val}%")
        if self.audio_mix_mode == 2:
            self.weight_mon_breath.set_k(self.breath_mix_gain)

    def set_rf_freq_mhz(self, freq_mhz: float) -> None:
        self.rf_freq_mhz = float(freq_mhz)
        self.bio_word_service.sdr_radar.set_rf_freq_mhz(self.rf_freq_mhz)
        self.rf_fusion.set_rf_freq_mhz(self.rf_freq_mhz)
        self.tab3_iq_src.set_rf_freq_mhz(self.rf_freq_mhz)
        if self.rf_device_select != 2:
            self.freq_rf.set_frequency_range(self.rf_freq_mhz * 1e6, self.baseband_rate)

    def set_hackrf_freq_mhz(self, freq_mhz: float) -> None:
        self.hackrf_freq_mhz = float(freq_mhz)
        self.bio_word_service.hackrf_stream.set_rf_freq_mhz(self.hackrf_freq_mhz)
        if self.rf_device_select == 2:
            self.freq_rf.set_frequency_range(self.hackrf_freq_mhz * 1e6, self.baseband_rate)

    def _on_rf_device_changed(self, idx: int) -> None:
        self.rf_device_select = int(idx)
        self.rf_fusion.set_rf_device_select(self.rf_device_select)
        self.tab3_iq_src.set_rf_device_select(self.rf_device_select)
        center_mhz = self.hackrf_freq_mhz if self.rf_device_select == 2 else self.rf_freq_mhz
        self.freq_rf.set_frequency_range(center_mhz * 1e6, self.baseband_rate)

    def _on_reconnect_sdrs_clicked(self) -> None:
        self.bio_word_service.reconnect_sdrs()

    def _on_rf_gain_slider(self, val: int) -> None:
        self.rf_gain = float(val)
        self.lbl_rf_gain.setText(f"{val} dB")
        self.bio_word_service.sdr_radar.set_rf_gain(self.rf_gain)
        self.bio_word_service.hackrf_stream.set_rf_gain(min(88.0, self.rf_gain + 6.0))

    def _on_carrier_slider(self, val: int) -> None:
        self.breath_carrier_hz = float(val)
        self.lbl_carrier.setText(f"{val} Hz")
        self.infra_sonifier.set_carrier_hz(self.breath_carrier_hz)

    def set_record_enable(self, enabled: bool) -> None:
        self.record_enable = bool(enabled)
        self.master_out.set_record_enable(self.record_enable)

    def closeEvent(self, event) -> None:
        self._status_timer.stop()
        self.web_server.stop()
        self.stop()
        self.wait()
        self.bio_word_service.stop()
        event.accept()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="GNU-Larex: Live Room Audio, Autotuned Sublevel Vocalizations & Biometric Word Log"
    )
    mode_grp = parser.add_mutually_exclusive_group()
    mode_grp.add_argument(
        "--room",
        action="store_true",
        help="Start in Live Room Mic + Sublevel Vocalization Autotune mode (default).",
    )
    mode_grp.add_argument(
        "--live",
        action="store_true",
        help="Start in Dual Sensor Fusion mode (Live Room Mic + Live SoapySDR RF Doppler).",
    )
    mode_grp.add_argument(
        "--sim",
        action="store_true",
        help="Start in Physiological RF Micro-Doppler Simulator mode.",
    )
    parser.add_argument("--mic-device", default="", help="Optional PortAudio microphone device name.")
    parser.add_argument("--sdr-args", default="", help="Optional SoapySDR device args.")
    parser.add_argument("--cw-tx", action="store_true", help="Enable Full-Duplex CW Radar TX.")
    parser.add_argument("--freq", type=float, default=915.0, help="RTL-SDR primary RF carrier frequency in MHz.")
    parser.add_argument("--gain", type=float, default=38.0, help="RTL-SDR RX gain in dB.")
    parser.add_argument("--hackrf-freq", type=float, default=2450.0, help="HackRF One wideband carrier frequency in MHz.")
    parser.add_argument("--hackrf-gain", type=float, default=44.0, help="HackRF One staged LNA+VGA RX gain in dB.")
    parser.add_argument("--record", action="store_true", help="Start 4-channel WAV + CSV recording.")
    parser.add_argument("--mute", action="store_true", help="Start with speakers muted (visual only).")
    parser.add_argument(
        "--ultrasonic",
        action="store_true",
        help="Capture UltraMic384K at full 384 kHz ultrasonic rate (0 - 192 kHz spectrum).",
    )
    parser.add_argument(
        "--whisper-model",
        default="small.en",
        help="Faster-Whisper ASR model size (e.g., small.en, base.en, distil-large-v3).",
    )
    parser.add_argument(
        "--ollama-model",
        default="nightsweep-signalintelligence:latest",
        help="Local Ollama model for contextual phonetic repair.",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=8765,
        help="Embedded Vue.js + SSE Web Backend port (default: 8765).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    qapp = Qt.QApplication(sys.argv)

    if args.sim:
        initial_mode = 2
    elif args.room:
        initial_mode = 0
    else:
        # Default to Live Dual-Sensor Fusion (Live Mic + RTL-SDR Blog V4 + HackRF One)
        initial_mode = 1

    tb = GnuLarexVibrometryWindow(
        sensor_mode=initial_mode,
        mic_device=args.mic_device,
        sdr_args=args.sdr_args,
        enable_cw_tx=args.cw_tx,
        rf_freq_mhz=args.freq,
        rf_gain=args.gain,
        hackrf_freq_mhz=args.hackrf_freq,
        hackrf_gain=args.hackrf_gain,
        record_enable=args.record,
        mute_audio=args.mute,
        prefer_ultrasonic=args.ultrasonic,
        whisper_model=args.whisper_model,
        ollama_model=args.ollama_model,
        web_port=args.web_port,
    )
    tb.show()
    qapp.processEvents()
    tb.start()

    def sig_handler(sig=None, frame=None):
        tb.web_server.stop()
        tb.stop()
        tb.wait()
        tb.bio_word_service.stop()
        Qt.QApplication.quit()

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    timer = Qt.QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    qapp.exec_()


if __name__ == "__main__":
    main()
