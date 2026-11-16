<template>
  <section id="fm-pirate-scanner-ext" class="card fm-ext-card">
    <!-- TOP HEADER -->
    <div class="fm-header">
      <div class="fm-head-left">
        <div class="fm-title-row">
          <h2 class="fm-title">
            📻 FMBandPirateScanner Extension · 88.0–108.0 MHz Superheterodyne IF &amp; MPX Subcarrier Station Viewer
          </h2>
          <span class="pill mono sdr-pill">
            📡 {{ statusData.driver || 'rtlsdr' }} · 2.0 MSPS → 200 kHz IF ({{ statusData.if_fir_taps || 101 }}-Tap 95 kHz FIR) · Gain {{ statusData.gain_db ?? 35 }} dB
          </span>
          <span class="pill mono pirate-pill">
            🚨 {{ kpis.flagged_pirate_count ?? 4 }} Flagged Pirate / Unlicensed · {{ kpis.over_deviation_count ?? 3 }} Over-Deviating (&gt;82 kHz)
          </span>
          <span class="pill mono bistatic-pill">
            📌 Bistatic Illuminator: {{ statusData.pinned_bistatic_freq_mhz ?? 100.1 }} MHz (RTL-SDR :5556)
          </span>
        </div>
        <div class="fm-sub">
          Sweeps <strong>88.0–108.0 MHz</strong> in 2.0 MHz windows (10× 200 kHz channels/step), performs digital superheterodyne downconversion,
          <strong>FM Polar Discrimination</strong> (<span class="mono">99.5th-percentile deviation vs. ±75 kHz FCC/ITU mask</span>), and 4th-order Butterworth inspection of the
          <strong>19 kHz Stereo Pilot</strong> (<span class="mono">18.8–19.2 kHz</span>) &amp; <strong>57 kHz RDS Data Subcarrier</strong> (<span class="mono">55.5–58.5 kHz</span>).
        </div>
      </div>

      <div class="fm-hdr-actions mono">
        <label class="ctrl-lbl">
          Driver:
          <select v-model="driverInput" class="ctrl-select" @change="applyConfigOnly">
            <option value="rtlsdr">rtlsdr (RTL-SDR V4)</option>
            <option value="hackrf">hackrf (HackRF One)</option>
            <option value="plutosdr">plutosdr (PlutoSDR)</option>
          </select>
        </label>
        <label class="ctrl-lbl">
          Gain (dB):
          <input
            v-model.number="gainInput"
            type="number"
            min="0"
            max="49.6"
            step="1.0"
            class="ctrl-num"
            @change="applyConfigOnly"
          />
        </label>
        <button
          type="button"
          class="btn btn-scan mono"
          :disabled="scanBusy"
          @click="runFullSweep"
        >
          {{ scanBusy ? '📡 Sweeping 88–108 MHz…' : '📡 Run 88–108 MHz Superheterodyne Sweep' }}
        </button>
        <button
          type="button"
          class="btn btn-ollama mono"
          :disabled="ollamaBusy"
          @click="consultOllamaModal(true)"
        >
          {{ ollamaBusy ? '🧠 Consulting Ollama Modal…' : '🧠 Consult Ollama Modal' }}
        </button>
      </div>
    </div>

    <div v-if="bannerMsg" class="fm-banner mono">
      ✅ {{ bannerMsg }}
    </div>

    <!-- NIGHTSWEEP OLLAMA MODAL ADVISOR DRAWER -->
    <div v-if="ollamaAdvice" class="ollama-drawer">
      <div class="od-top">
        <span class="mono od-badge">
          🧠 {{ ollamaAdvice.model || 'nightsweep-signalintelligence:latest' }} · FM &amp; Pirate Spectrum Modal Reference
          <strong v-if="ollamaAdvice.ollama_live" style="color: #7ee787"> · LIVE</strong>
        </span>
        <div style="display: flex; gap: 8px; align-items: center">
          <button
            v-if="ollamaAdvice.recommended_config"
            type="button"
            class="mini-btn mono"
            style="border-color: #3fb950; color: #7ee787"
            @click="applyRecommendedOllamaConfig"
          >
            ⚡ Lock Recommended {{ ollamaAdvice.recommended_config.pinned_bistatic_freq_mhz }} MHz Bistatic Carrier
          </button>
          <span class="mono od-ts">{{ ollamaAdvice.generated_at_utc }}</span>
        </div>
      </div>
      <p class="od-summary">{{ ollamaAdvice.overall_assessment }}</p>
      <div class="od-cols">
        <div class="od-col">
          <div class="od-col-hdr mono">🚨 Pirate &amp; Unlicensed Transmitter Findings</div>
          <ul>
            <li v-for="(it, idx) in (ollamaAdvice.pirate_transmitter_findings || [])" :key="'pf-' + idx">
              {{ it }}
            </li>
          </ul>
        </div>
        <div class="od-col">
          <div class="od-col-hdr mono">🔬 19 kHz Pilot, 57 kHz RDS &amp; Superhet IF</div>
          <ul>
            <li v-for="(it, idx) in (ollamaAdvice.mpx_and_superhet_insights || [])" :key="'mi-' + idx">
              {{ it }}
            </li>
          </ul>
        </div>
        <div class="od-col">
          <div class="od-col-hdr mono">📡 Passive Bistatic Radar Illuminator Advice</div>
          <ul>
            <li v-for="(it, idx) in (ollamaAdvice.bistatic_radar_recommendations || [])" :key="'br-' + idx">
              {{ it }}
            </li>
          </ul>
        </div>
      </div>
    </div>

    <!-- LIVE ALL-STATION FM BAND RECEIVER & MULTI-TUNER DECK -->
    <div class="live-wall-box">
      <div class="lw-top">
        <div>
          <div class="lw-title mono">
            🎧 LIVE ALL-STATION FM BAND RECEIVER &amp; MULTI-TUNER DECK (88.0–108.0 MHz)
            <span v-if="liveReceiverActive" class="pill mono live-on-pill">
              🔴 LIVE ON AIR · {{ liveModeLabel }}
            </span>
            <span v-else class="pill mono" style="color: #8b949e">STANDBY</span>
          </div>
          <div class="lw-sub">
            Listen to <strong>all 10 FM band stations simultaneously</strong> (panned across the stereo field from <span class="mono">88.3 MHz Left → 106.7 MHz Right</span> with <span class="mono">75 µs</span> de-emphasis &amp; <span class="mono">19 kHz</span> stereo decoding), isolate all <strong>4 Pirate / Micro-Bug exciters</strong>, or run the <strong>Continuous Auto-Stepping Band Scanner</strong>.
          </div>
        </div>

        <div class="lw-actions mono">
          <button
            type="button"
            class="btn lw-btn-all"
            :class="{ active: liveReceiverActive && liveMode === 'ALL_SPATIAL_MIX' }"
            @click="startLiveAllMode('ALL_SPATIAL_MIX')"
          >
            📻 Listen ALL 10 Stations Live (Spatial Wall)
          </button>
          <button
            type="button"
            class="btn lw-btn-pirate"
            :class="{ active: liveReceiverActive && liveMode === 'PIRATE_ONLY_MIX' }"
            @click="startLiveAllMode('PIRATE_ONLY_MIX')"
          >
            🚨 All 4 Pirate / Bug Stations Live
          </button>
          <button
            type="button"
            class="btn lw-btn-clean"
            :class="{ active: liveReceiverActive && liveMode === 'COMMERCIAL_ONLY_MIX' }"
            @click="startLiveAllMode('COMMERCIAL_ONLY_MIX')"
          >
            ✅ All 6 Commercial Stations Live
          </button>
          <button
            type="button"
            class="btn lw-btn-scan"
            :class="{ active: liveReceiverActive && liveMode === 'AUTO_STEP_SCANNER' }"
            @click="startAutoStepScanner()"
          >
            🔄 Auto-Step Live Band Scanner
          </button>
          <button
            type="button"
            class="btn lw-btn-webaudio"
            :class="{ active: webAudioActive }"
            @click="toggleWebAudioLiveWall"
          >
            🎹 Zero-Latency WebAudio Bank: {{ webAudioActive ? 'ON' : 'OFF' }}
          </button>
          <button
            v-if="liveReceiverActive || webAudioActive || activeAudioUrl"
            type="button"
            class="btn lw-btn-stop"
            @click="stopAllLiveListening"
          >
            ⏹️ Stop Live
          </button>
        </div>
      </div>

      <!-- LIVE STREAM PLAYER BAR (MULTI-STATION MIX OR AUTO-STEPPER) -->
      <div v-if="liveReceiverActive && liveAllWavUrl && liveMode !== 'AUTO_STEP_SCANNER'" class="fm-audio-bar mono" style="margin-top: 8px; border-color: rgba(63, 185, 80, 0.55)">
        <span>
          🔴 <strong>{{ liveModeLabel }}</strong> ({{ activeUnmutedStations.length }}/{{ stations.length }} stations active · 48 kHz Stereo Superhet + {{ deemphasisUs }} µs De-Emphasis):
        </span>
        <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap">
          <label class="ctrl-lbl">
            De-Emphasis:
            <select v-model.number="deemphasisUs" class="ctrl-select" @change="refreshLiveAllStream">
              <option :value="75">75 µs (Americas)</option>
              <option :value="50">50 µs (ITU/EU)</option>
            </select>
          </label>
          <button v-if="soloFreq !== null" type="button" class="mini-btn mono" style="border-color: #fbbf24; color: #fbbf24" @click="clearSolo">
            🎯 Clear Solo ({{ soloFreq }} MHz)
          </button>
          <audio :key="liveAllWavUrl" :src="liveAllWavUrl" controls autoplay loop class="fm-wav-player"></audio>
        </div>
      </div>

      <!-- AUTO-STEPPING BAND SCANNER BAR -->
      <div v-if="liveReceiverActive && liveMode === 'AUTO_STEP_SCANNER'" class="fm-audio-bar mono" style="margin-top: 8px; border-color: rgba(56, 189, 248, 0.55)">
        <span>
          🔄 <strong>Auto-Stepping FM Band Scanner</strong> → Tuned: <strong style="color: #38bdf8">{{ activeAudioStation?.frequency_mhz?.toFixed(1) }} MHz ({{ activeAudioStation?.callsign }})</strong> · Pwr {{ activeAudioStation?.power_dbfs }} dBFS · Dev ±{{ activeAudioStation?.peak_deviation_khz }} kHz
        </span>
        <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap">
          <button type="button" class="mini-btn mono" @click="stepPrevLiveStation">⏮️ Prev</button>
          <button
            type="button"
            class="mini-btn mono"
            :style="scannerHold ? { borderColor: '#fbbf24', color: '#fbbf24' } : { borderColor: '#3fb950', color: '#7ee787' }"
            @click="scannerHold = !scannerHold"
          >
            {{ scannerHold ? '🔒 Held on Station (Click to Resume)' : '⏸️ Hold Station' }}
          </button>
          <button type="button" class="mini-btn mono" @click="stepNextLiveStation">⏭️ Next</button>
          <label class="ctrl-lbl">
            Dwell:
            <select v-model.number="scannerDwellSec" class="ctrl-select" @change="restartCurrentAutoStepClip">
              <option :value="2.0">2.0 s</option>
              <option :value="3.2">3.2 s</option>
              <option :value="5.0">5.0 s</option>
              <option :value="7.5">7.5 s</option>
            </select>
          </label>
          <audio
            :key="activeAudioUrl"
            :src="activeAudioUrl"
            controls
            autoplay
            :loop="scannerHold"
            class="fm-wav-player"
            @ended="onAutoStepAudioEnded"
          ></audio>
        </div>
      </div>

      <!-- 10-STATION LIVE CHANNEL STRIP SOUNDBOARD -->
      <div class="live-strips-grid mono">
        <div
          v-for="st in stations"
          :key="'strip-' + st.frequency_mhz"
          class="st-strip"
          :class="{
            'strip-muted': !isStationAudible(st.frequency_mhz),
            'strip-solo': soloFreq === st.frequency_mhz,
            'strip-pirate': st.flags && st.flags.length > 0,
          }"
        >
          <div class="strip-top">
            <div style="display: flex; align-items: center; gap: 5px">
              <span class="st-dot" :style="{ background: stationColor(st) }"></span>
              <strong style="color: #f0f6fc; font-size: 0.8rem">{{ st.frequency_mhz.toFixed(1) }}</strong>
              <span class="pan-chip">{{ formatPan(st.frequency_mhz) }}</span>
            </div>
            <span class="call-chip">{{ st.callsign }}</span>
          </div>
          <div class="strip-meta">
            <span>{{ st.power_dbfs.toFixed(1) }} dB</span>
            <span :style="{ color: st.peak_deviation_khz > 82 ? '#ff7b72' : '#7ee787' }">±{{ st.peak_deviation_khz.toFixed(1) }}k</span>
            <span>{{ st.stereo_pilot_detected ? 'STEREO' : 'MONO' }}</span>
          </div>
          <div class="strip-vol">
            <span>Vol {{ Math.round((stationGains[st.frequency_mhz.toFixed(1)] ?? 0.85) * 100) }}%</span>
            <input
              type="range"
              min="0"
              max="1.2"
              step="0.05"
              :value="stationGains[st.frequency_mhz.toFixed(1)] ?? 0.85"
              @input="onStationGainInput(st.frequency_mhz, $event.target.value)"
              @change="syncLiveTunerToServer"
            />
          </div>
          <div class="strip-btns">
            <button
              type="button"
              class="strip-btn"
              :class="{ 'btn-on': !mutedFreqs.includes(st.frequency_mhz), 'btn-muted': mutedFreqs.includes(st.frequency_mhz) }"
              @click="toggleStationMute(st.frequency_mhz)"
            >
              {{ mutedFreqs.includes(st.frequency_mhz) ? '🔇 MUTED' : '🟢 ON AIR' }}
            </button>
            <button
              type="button"
              class="strip-btn"
              :class="{ 'btn-solo-on': soloFreq === st.frequency_mhz }"
              @click="toggleStationSolo(st.frequency_mhz)"
            >
              🎯 SOLO
            </button>
            <button
              type="button"
              class="strip-btn"
              @click="selectAndAuditionStation(st)"
            >
              🔊 Tune
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- AUDITION SINGLE STATION WAV BAR -->
    <div v-if="activeAudioUrl && liveMode !== 'AUTO_STEP_SCANNER'" class="fm-audio-bar mono">
      <span>
        🔊 Single-Station Superhet Demod Audio (<strong>{{ activeAudioStation?.frequency_mhz }} MHz · {{ activeAudioStation?.callsign }}</strong> · Dev {{ activeAudioStation?.peak_deviation_khz }} kHz):
      </span>
      <audio :key="activeAudioUrl" :src="activeAudioUrl" controls autoplay loop class="fm-wav-player"></audio>
    </div>

    <!-- INTERACTIVE 88.0 - 108.0 MHZ SPECTRUM & DEVIATION SVG VIEWER -->
    <div class="spectrum-box">
      <div class="spec-top mono">
        <span>📊 88.0–108.0 MHz Superheterodyne Spectrum &amp; Peak Deviation Mask (Click Any Station Carrier to Inspect / Audition)</span>
        <div class="filter-pills">
          <button
            v-for="f in filterOptions"
            :key="f.id"
            type="button"
            class="filt-btn mono"
            :class="{ active: activeFilter === f.id }"
            @click="activeFilter = f.id"
          >
            {{ f.label }}
          </button>
        </div>
      </div>

      <svg viewBox="0 0 920 210" class="spec-svg" role="img" aria-label="88 to 108 MHz FM Band Spectrum">
        <!-- Background Grid -->
        <line x1="55" y1="25" x2="895" y2="25" stroke="#1f2937" stroke-dasharray="3 3" />
        <line x1="55" y1="62" x2="895" y2="62" stroke="#f85149" stroke-width="1" stroke-dasharray="5 4" />
        <text x="60" y="58" fill="#ff7b72" font-size="9.5" font-family="monospace">
          82.0 kHz Pirate Over-Deviation Threshold
        </text>
        <line x1="55" y1="76" x2="895" y2="76" stroke="#3fb950" stroke-width="1" stroke-dasharray="4 4" />
        <text x="60" y="72" fill="#7ee787" font-size="9.5" font-family="monospace">
          ±75.0 kHz Commercial FCC/ITU Deviation Limit
        </text>
        <line x1="55" y1="175" x2="895" y2="175" stroke="#30363d" stroke-width="1.5" />

        <!-- Frequency Ticks (88 to 108 MHz) -->
        <g v-for="mhz in [88, 90, 92, 94, 96, 98, 100, 102, 104, 106, 108]" :key="'tk-' + mhz">
          <line :x1="freqToX(mhz)" y1="175" :x2="freqToX(mhz)" y2="181" stroke="#8b949e" />
          <text :x="freqToX(mhz)" y="196" fill="#8b949e" font-size="10" text-anchor="middle" font-family="monospace">
            {{ mhz }} MHz
          </text>
        </g>

        <!-- Station Carrier Bars -->
        <g
          v-for="st in stations"
          :key="'bar-' + st.frequency_mhz"
          class="st-bar-group"
          @click="selectAndAuditionStation(st)"
        >
          <line
            :x1="freqToX(st.frequency_mhz)"
            :y1="devToY(st.peak_deviation_khz)"
            :x2="freqToX(st.frequency_mhz)"
            y2="175"
            :stroke="stationColor(st)"
            :stroke-width="selectedStation?.frequency_mhz === st.frequency_mhz ? 11 : 7"
            stroke-linecap="round"
            opacity="0.88"
          />
          <circle
            :cx="freqToX(st.frequency_mhz)"
            :cy="devToY(st.peak_deviation_khz)"
            :r="selectedStation?.frequency_mhz === st.frequency_mhz ? 6.5 : 4.5"
            :fill="stationColor(st)"
            stroke="#0d1117"
            stroke-width="1.5"
          />
          <text
            :x="freqToX(st.frequency_mhz)"
            :y="devToY(st.peak_deviation_khz) - 9"
            :fill="stationColor(st)"
            font-size="9.5"
            font-weight="bold"
            text-anchor="middle"
            font-family="monospace"
          >
            {{ st.frequency_mhz }}
          </text>
          <text
            :x="freqToX(st.frequency_mhz)"
            :y="devToY(st.peak_deviation_khz) - 19"
            fill="#c9d1d9"
            font-size="8.5"
            text-anchor="middle"
            font-family="monospace"
          >
            {{ st.peak_deviation_khz }}k
          </text>
        </g>
      </svg>

      <!-- SELECTED STATION MPX SUBCARRIER & CARSON BANDWIDTH INSPECTOR -->
      <div v-if="selectedStation" class="mpx-inspector mono">
        <div class="mpx-insp-head">
          <div>
            <strong :style="{ color: stationColor(selectedStation), fontSize: '0.82rem' }">
              🔬 MPX Baseband &amp; Superhet IF Inspector · {{ selectedStation.frequency_mhz?.toFixed(1) }} MHz ({{ selectedStation.callsign }})
            </strong>
            <span class="call-chip" style="margin-left: 8px">{{ selectedStation.classification || 'STATION' }}</span>
          </div>
          <div style="display: flex; gap: 6px; align-items: center">
            <button type="button" class="mini-btn mono" @click="selectAndAuditionStation(selectedStation)">
              🔊 Audition {{ selectedStation.frequency_mhz?.toFixed(1) }} MHz WAV
            </button>
            <button type="button" class="mini-btn mono" @click="pinAsBistaticCarrier(selectedStation)">
              📌 Pin {{ selectedStation.frequency_mhz?.toFixed(1) }} MHz as Bistatic Carrier
            </button>
          </div>
        </div>
        <div class="mpx-insp-grid">
          <div class="mpx-cell">
            <div class="mpx-lbl">SUPERHET IF CHANNEL POWER</div>
            <div class="mpx-val" style="color: #79c0ff">{{ selectedStation.power_dbfs }} dBFS</div>
            <div class="mpx-sub">101-tap 95 kHz FIR · 200 kHz IF</div>
          </div>
          <div class="mpx-cell">
            <div class="mpx-lbl">PEAK POLAR DEVIATION (99.5%)</div>
            <div class="mpx-val" :style="{ color: selectedStation.peak_deviation_khz > 82 ? '#ff7b72' : '#7ee787' }">
              ±{{ selectedStation.peak_deviation_khz }} kHz
            </div>
            <div class="mpx-sub">
              {{ selectedStation.peak_deviation_khz > 82 ? '🚨 Exceeds 82 kHz Pirate Gate' : '✓ Within ±75 kHz Commercial Mask' }}
            </div>
          </div>
          <div class="mpx-cell">
            <div class="mpx-lbl">19 kHz STEREO PILOT (18.8–19.2 kHz)</div>
            <div class="mpx-val" :style="{ color: selectedStation.stereo_pilot_detected ? '#7ee787' : '#ffa657' }">
              {{ selectedStation.pilot_ratio_pct ?? 0 }}% RMS
              <span style="font-size: 0.68rem">({{ selectedStation.pilot_19k_rms_khz ?? 0 }} kHz)</span>
            </div>
            <div class="mpx-sub">{{ selectedStation.stereo_pilot_detected ? '✓ >2.5% Stereo Pilot Locked' : '✗ MONO_NO_PILOT (<2.5%)' }}</div>
          </div>
          <div class="mpx-cell">
            <div class="mpx-lbl">57 kHz RDS SUBCARRIER (55.5–58.5 kHz)</div>
            <div class="mpx-val" :style="{ color: selectedStation.rds_detected ? '#7ee787' : '#ffa657' }">
              {{ selectedStation.rds_ratio_pct ?? 0 }}% RMS
              <span style="font-size: 0.68rem">({{ selectedStation.rds_57k_rms_khz ?? 0 }} kHz)</span>
            </div>
            <div class="mpx-sub">{{ selectedStation.rds_detected ? '✓ >1.0% 57 kHz BPSK RDS Present' : '✗ MISSING_RDS (<1.0%)' }}</div>
          </div>
          <div class="mpx-cell">
            <div class="mpx-lbl">CARSON OCCUPIED BANDWIDTH B_T</div>
            <div class="mpx-val" :style="{ color: (selectedStation.carson_bandwidth_khz || 240) > 255 ? '#ff7b72' : '#d2a8ff' }">
              {{ selectedStation.carson_bandwidth_khz || Math.round(2 * (selectedStation.peak_deviation_khz + (selectedStation.rds_detected ? 57 : 15))) }} kHz
            </div>
            <div class="mpx-sub">2·(Δf + f_max) · MPX RMS {{ selectedStation.mpx_rms_khz ?? 32.4 }} kHz</div>
          </div>
        </div>
      </div>
    </div>

    <!-- STATION TABLE & SELECTED STATION MPX SUBCARRIER INSPECTOR -->
    <div class="table-wrap">
      <table class="fm-table mono">
        <thead>
          <tr>
            <th>Frequency / Callsign</th>
            <th>Channel Power</th>
            <th>Peak Deviation (99.5%)</th>
            <th>19 kHz Stereo Pilot</th>
            <th>57 kHz RDS Subcarrier</th>
            <th>Heuristic Pirate / MPX Flags</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="st in filteredStations"
            :key="st.frequency_mhz"
            :class="{
              'row-pirate': st.flags && st.flags.length > 0,
              'row-pinned': st.is_pinned_bistatic,
            }"
          >
            <td>
              <div style="display: flex; align-items: center; gap: 6px">
                <span class="st-dot" :style="{ background: stationColor(st) }"></span>
                <strong style="color: #e6edf3; font-size: 0.86rem">{{ st.frequency_mhz.toFixed(1) }} MHz</strong>
                <span class="call-chip">{{ st.callsign }}</span>
              </div>
              <div style="color: #8b949e; font-size: 0.69rem; margin-top: 2px">{{ st.label }}</div>
            </td>
            <td>
              <strong :style="{ color: st.power_dbfs > -15 ? '#7ee787' : '#79c0ff' }">
                {{ st.power_dbfs.toFixed(1) }} dBFS
              </strong>
            </td>
            <td>
              <div style="display: flex; align-items: center; gap: 6px">
                <strong :style="{ color: st.peak_deviation_khz > 82 ? '#ff7b72' : '#7ee787' }">
                  ±{{ st.peak_deviation_khz.toFixed(1) }} kHz
                </strong>
                <span style="color: #8b949e; font-size: 0.68rem">/ 75.0 kHz</span>
              </div>
              <div class="dev-bar-bg">
                <div
                  class="dev-bar-fill"
                  :style="{
                    width: Math.min(100, Math.round((st.peak_deviation_khz / 105) * 100)) + '%',
                    background: st.peak_deviation_khz > 82 ? '#f85149' : '#3fb950',
                  }"
                ></div>
              </div>
            </td>
            <td>
              <span v-if="st.stereo_pilot_detected" class="ok-badge">
                ✓ 19 kHz PILOT ({{ st.pilot_ratio_pct ?? 9.2 }}%)
              </span>
              <span v-else class="warn-badge">
                ✗ MONO_NO_PILOT ({{ st.pilot_ratio_pct ?? 0.1 }}%)
              </span>
            </td>
            <td>
              <span v-if="st.rds_detected" class="ok-badge">
                ✓ 57 kHz RDS ({{ st.rds_ratio_pct ?? 3.8 }}%)
              </span>
              <span v-else class="warn-badge">
                ✗ MISSING_RDS ({{ st.rds_ratio_pct ?? 0.2 }}%)
              </span>
            </td>
            <td>
              <div v-if="st.flags && st.flags.length" class="flag-list">
                <span
                  v-for="(fl, fidx) in st.flags"
                  :key="fidx"
                  class="flag-pill"
                  :class="{ 'flag-over': fl.startsWith('OVER_DEVIATION') }"
                >
                  🚨 {{ fl }}
                </span>
              </div>
              <span v-else class="clean-pill">✅ CLEAN_COMMERCIAL</span>
              <div style="color: #8b949e; font-size: 0.66rem; margin-top: 2px">{{ st.notes }}</div>
            </td>
            <td>
              <div style="display: flex; gap: 5px; flex-wrap: wrap">
                <button type="button" class="mini-btn mono" @click="selectAndAuditionStation(st)">
                  🔊 Audition WAV
                </button>
                <button
                  type="button"
                  class="mini-btn mono"
                  :style="st.is_pinned_bistatic ? { borderColor: '#38bdf8', color: '#38bdf8' } : {}"
                  @click="pinAsBistaticCarrier(st)"
                >
                  {{ st.is_pinned_bistatic ? '📌 Pinned Bistatic' : '📌 Pin Bistatic' }}
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

const props = defineProps({
  data: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['updated'])

const localStatus = ref({})
const scanBusy = ref(false)
const ollamaBusy = ref(false)
const ollamaAdvice = ref(null)
const bannerMsg = ref('')
const activeFilter = ref('ALL')
const selectedStation = ref(null)
const activeAudioUrl = ref('')
const activeAudioStation = ref(null)
const driverInput = ref('rtlsdr')
const gainInput = ref(35.0)

// Live All-Station FM Band Receiver & Multi-Tuner state
const liveReceiverActive = ref(false)
const liveMode = ref('ALL_SPATIAL_MIX')
const liveAllWavUrl = ref('')
const deemphasisUs = ref(75)
const mutedFreqs = ref([])
const soloFreq = ref(null)
const stationGains = reactive({
  '88.3': 0.85,
  '89.9': 0.85,
  '91.5': 0.85,
  '93.9': 0.85,
  '95.9': 0.85,
  '97.1': 0.85,
  '100.1': 0.90,
  '101.7': 0.85,
  '104.3': 0.85,
  '106.7': 0.85,
})
const scannerHold = ref(false)
const scannerDwellSec = ref(3.2)
const autoStepIdx = ref(0)

// Zero-latency WebAudio 10-Station Polyphonic Bank
const webAudioActive = ref(false)
let audioCtx = null
let stationNodes = {}

const statusData = computed(() => {
  return Object.keys(localStatus.value).length ? localStatus.value : props.data || {}
})

const kpis = computed(() => statusData.value.kpis || {})
const stations = computed(() => statusData.value.stations || [])

const filterOptions = computed(() => [
  { id: 'ALL', label: `ALL STATIONS (${stations.value.length})` },
  {
    id: 'PIRATE',
    label: `🚨 PIRATE / FLAGGED (${stations.value.filter((s) => s.flags?.length).length})`,
  },
  {
    id: 'OVER_DEV',
    label: `⚡ OVER-DEVIATING >82 kHz (${stations.value.filter((s) => (s.flags || []).some((f) => f.startsWith('OVER_DEVIATION'))).length})`,
  },
  {
    id: 'CLEAN',
    label: `✅ CLEAN COMMERCIAL (${stations.value.filter((s) => !s.flags?.length).length})`,
  },
])

const filteredStations = computed(() => {
  if (activeFilter.value === 'PIRATE') {
    return stations.value.filter((s) => s.flags && s.flags.length > 0)
  }
  if (activeFilter.value === 'OVER_DEV') {
    return stations.value.filter((s) => (s.flags || []).some((f) => f.startsWith('OVER_DEVIATION')))
  }
  if (activeFilter.value === 'CLEAN') {
    return stations.value.filter((s) => !s.flags || s.flags.length === 0)
  }
  return stations.value
})

watch(
  () => statusData.value,
  (st) => {
    if (st.driver) driverInput.value = st.driver
    if (st.gain_db !== undefined) gainInput.value = st.gain_db
    if (!selectedStation.value && st.stations?.length) {
      selectedStation.value = st.stations[0]
    }
  },
  { immediate: true }
)

function freqToX(mhz) {
  const clamped = Math.max(88.0, Math.min(108.0, Number(mhz) || 88.0))
  return 65 + ((clamped - 88.0) / 20.0) * 820
}

function devToY(devKhz) {
  const clamped = Math.max(20.0, Math.min(105.0, Number(devKhz) || 60.0))
  return 175 - ((clamped - 20.0) / 85.0) * 140
}

function stationColor(st) {
  if (st.is_pinned_bistatic) return '#38bdf8'
  const flags = st.flags || []
  if (flags.some((f) => f.startsWith('OVER_DEVIATION'))) return '#f85149'
  if (flags.length > 0) return '#f0883e'
  return '#3fb950'
}

function flash(msg) {
  bannerMsg.value = msg
  setTimeout(() => {
    if (bannerMsg.value === msg) bannerMsg.value = ''
  }, 6000)
}

async function fetchScannerStatus() {
  try {
    const res = await fetch('/api/fm-scanner/status')
    if (res.ok) {
      localStatus.value = await res.json()
    }
  } catch (e) {
    console.error('FM scanner status error:', e)
  }
}

async function runFullSweep() {
  scanBusy.value = true
  try {
    const res = await fetch('/api/fm-scanner/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        driver: driverInput.value,
        gain: Number(gainInput.value || 35.0),
      }),
    })
    if (res.ok) {
      localStatus.value = await res.json()
      flash(
        `Completed 88–108 MHz Superheterodyne Sweep: ${localStatus.value.kpis?.total_stations || 10} stations (${localStatus.value.kpis?.flagged_pirate_count || 4} pirate/flagged)!`
      )
      emit('updated')
    }
  } catch (e) {
    console.error('FM sweep error:', e)
  } finally {
    scanBusy.value = false
  }
}

async function applyConfigOnly() {
  try {
    const res = await fetch('/api/fm-scanner/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        driver: driverInput.value,
        gain: Number(gainInput.value || 35.0),
      }),
    })
    if (res.ok) {
      localStatus.value = await res.json()
      flash(`Updated FMBandPirateScanner hardware config (${driverInput.value} · ${gainInput.value} dB)`)
    }
  } catch (e) {
    console.error(e)
  }
}

function selectAndAuditionStation(st) {
  selectedStation.value = st
  activeAudioStation.value = st
  activeAudioUrl.value = `/api/fm-scanner/audio/${st.frequency_mhz.toFixed(1)}.wav?t=${Date.now()}`
  const flagTxt = st.flags?.length ? st.flags.join(', ') : 'CLEAN_COMMERCIAL'
  flash(`Auditioning ${st.frequency_mhz.toFixed(1)} MHz (${st.callsign}) · Dev ±${st.peak_deviation_khz} kHz · [${flagTxt}]`)
}

async function pinAsBistaticCarrier(st) {
  try {
    const res = await fetch('/api/fm-scanner/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pinned_bistatic_freq_mhz: st.frequency_mhz,
      }),
    })
    if (res.ok) {
      localStatus.value = await res.json()
      flash(`Pinned ${st.frequency_mhz.toFixed(1)} MHz (${st.callsign}) as RTL-SDR :5556 Passive Bistatic Radar Illuminator!`)
      emit('updated')
    }
  } catch (e) {
    console.error(e)
  }
}

async function consultOllamaModal(force = false) {
  ollamaBusy.value = true
  try {
    const res = await fetch('/api/ollama/fm-scanner', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force }),
    })
    if (res.ok) {
      ollamaAdvice.value = await res.json()
      if (force) {
        flash('NightSweep Ollama Modal analyzed 88–108 MHz FM & Pirate Station telemetry!')
      }
    }
  } catch (e) {
    console.error(e)
  } finally {
    ollamaBusy.value = false
  }
}

async function applyRecommendedOllamaConfig() {
  const rc = ollamaAdvice.value?.recommended_config
  if (!rc) return
  try {
    const res = await fetch('/api/fm-scanner/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(rc),
    })
    if (res.ok) {
      localStatus.value = await res.json()
      flash(`Applied Ollama Modal FM Config: Pinned ${rc.pinned_bistatic_freq_mhz} MHz Bistatic Carrier!`)
      emit('updated')
    }
  } catch (e) {
    console.error(e)
  }
}

// =========================================================================
// LIVE ALL-STATION FM BAND RECEIVER & MULTI-TUNER FUNCTIONS
// =========================================================================

const liveModeLabel = computed(() => {
  if (liveMode.value === 'PIRATE_ONLY_MIX') return '4 Pirate / Micro-Bug Stations Spatial Wall'
  if (liveMode.value === 'COMMERCIAL_ONLY_MIX') return '6 Clean Commercial Stations Spatial Wall'
  if (liveMode.value === 'AUTO_STEP_SCANNER') return 'Continuous Auto-Stepping Band Scanner'
  return 'All 10 FM Stations Simultaneous Spatial Stereo Wall'
})

const activeUnmutedStations = computed(() => {
  let list = stations.value
  if (liveMode.value === 'PIRATE_ONLY_MIX') {
    list = list.filter((s) => s.flags && s.flags.length > 0)
  } else if (liveMode.value === 'COMMERCIAL_ONLY_MIX') {
    list = list.filter((s) => !s.flags || s.flags.length === 0)
  }
  if (soloFreq.value !== null) {
    return list.filter((s) => Math.abs(s.frequency_mhz - soloFreq.value) < 0.05)
  }
  return list.filter((s) => !mutedFreqs.value.includes(s.frequency_mhz))
})

function isStationAudible(freqMhz) {
  if (soloFreq.value !== null) {
    return Math.abs(freqMhz - soloFreq.value) < 0.05
  }
  if (mutedFreqs.value.includes(freqMhz)) return false
  if (liveMode.value === 'PIRATE_ONLY_MIX') {
    const st = stations.value.find((s) => Math.abs(s.frequency_mhz - freqMhz) < 0.05)
    return Boolean(st?.flags?.length)
  }
  if (liveMode.value === 'COMMERCIAL_ONLY_MIX') {
    const st = stations.value.find((s) => Math.abs(s.frequency_mhz - freqMhz) < 0.05)
    return !st?.flags?.length
  }
  return true
}

function formatPan(freqMhz) {
  const pan = Math.round(((Number(freqMhz) - 98.0) / 10.0) * 100)
  if (pan < -5) return `L${Math.min(95, Math.abs(pan))}%`
  if (pan > 5) return `R${Math.min(95, pan)}%`
  return 'CTR'
}

function refreshLiveAllStream() {
  const freqs = activeUnmutedStations.value.map((s) => s.frequency_mhz.toFixed(1)).join(',')
  liveAllWavUrl.value = `/api/fm-scanner/live-all.wav?mode=${liveMode.value}&freqs=${freqs}&deemphasis_us=${deemphasisUs.value}&sec=6.0&t=${Date.now()}`
  updateWebAudioGains()
}

async function syncLiveTunerToServer() {
  try {
    await fetch('/api/fm-scanner/live-tuner', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        listening_active: liveReceiverActive.value,
        live_mode: liveMode.value === 'AUTO_STEP_SCANNER' ? 'SEQUENTIAL_SWEEP' : liveMode.value,
        solo_freq: soloFreq.value,
        muted_freqs: mutedFreqs.value,
        station_gains: { ...stationGains },
        deemphasis_us: deemphasisUs.value,
        dwell_sec: scannerDwellSec.value,
      }),
    })
  } catch (_) {}
  if (liveReceiverActive.value && liveMode.value !== 'AUTO_STEP_SCANNER') {
    refreshLiveAllStream()
  }
}

function startLiveAllMode(mode = 'ALL_SPATIAL_MIX') {
  liveMode.value = mode
  liveReceiverActive.value = true
  activeAudioUrl.value = ''
  if (mode === 'PIRATE_ONLY_MIX') {
    activeFilter.value = 'PIRATE'
  } else if (mode === 'COMMERCIAL_ONLY_MIX') {
    activeFilter.value = 'CLEAN'
  } else {
    activeFilter.value = 'ALL'
  }
  refreshLiveAllStream()
  syncLiveTunerToServer()
  flash(`Started Live FM Band Receiver: ${liveModeLabel.value} (${activeUnmutedStations.value.length} stations)!`)
}

function startAutoStepScanner() {
  liveMode.value = 'AUTO_STEP_SCANNER'
  liveReceiverActive.value = true
  scannerHold.value = false
  liveAllWavUrl.value = ''
  const pool = filteredStations.value.length ? filteredStations.value : stations.value
  if (!pool.length) return
  autoStepIdx.value = 0
  tuneAutoStepStation(pool[0])
  syncLiveTunerToServer()
}

function tuneAutoStepStation(st) {
  if (!st) return
  selectedStation.value = st
  activeAudioStation.value = st
  activeAudioUrl.value = `/api/fm-scanner/audio/${st.frequency_mhz.toFixed(1)}.wav?sec=${scannerDwellSec.value}&t=${Date.now()}`
}

function stepNextLiveStation() {
  const pool = filteredStations.value.length ? filteredStations.value : stations.value
  if (!pool.length) return
  autoStepIdx.value = (autoStepIdx.value + 1) % pool.length
  tuneAutoStepStation(pool[autoStepIdx.value])
}

function stepPrevLiveStation() {
  const pool = filteredStations.value.length ? filteredStations.value : stations.value
  if (!pool.length) return
  autoStepIdx.value = (autoStepIdx.value - 1 + pool.length) % pool.length
  tuneAutoStepStation(pool[autoStepIdx.value])
}

function restartCurrentAutoStepClip() {
  if (activeAudioStation.value) {
    tuneAutoStepStation(activeAudioStation.value)
  }
}

function onAutoStepAudioEnded() {
  if (!liveReceiverActive.value || liveMode.value !== 'AUTO_STEP_SCANNER') return
  if (scannerHold.value) {
    restartCurrentAutoStepClip()
  } else {
    stepNextLiveStation()
  }
}

function toggleStationMute(freqMhz) {
  const idx = mutedFreqs.value.indexOf(freqMhz)
  if (idx >= 0) {
    mutedFreqs.value.splice(idx, 1)
  } else {
    mutedFreqs.value.push(freqMhz)
  }
  updateWebAudioGains()
  syncLiveTunerToServer()
}

function toggleStationSolo(freqMhz) {
  if (soloFreq.value === freqMhz) {
    soloFreq.value = null
  } else {
    soloFreq.value = freqMhz
  }
  updateWebAudioGains()
  syncLiveTunerToServer()
}

function clearSolo() {
  soloFreq.value = null
  updateWebAudioGains()
  syncLiveTunerToServer()
}

function onStationGainInput(freqMhz, val) {
  stationGains[freqMhz.toFixed(1)] = Number(val)
  updateWebAudioGains()
}

const STATION_BASE_AUDIO_HZ = {
  '88.3': 440.0,
  '89.9': 528.0,
  '91.5': 610.0,
  '93.9': 480.0,
  '95.9': 740.0,
  '97.1': 392.0,
  '100.1': 432.0,
  '101.7': 660.0,
  '104.3': 587.3,
  '106.7': 512.0,
}

function toggleWebAudioLiveWall() {
  if (webAudioActive.value) {
    stopWebAudioBank()
    flash('Stopped Zero-Latency WebAudio 10-Station Polyphonic Bank.')
    return
  }
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext
    audioCtx = new Ctx()
    stationNodes = {}
    for (const st of stations.value) {
      const fKey = st.frequency_mhz.toFixed(1)
      const baseHz = STATION_BASE_AUDIO_HZ[fKey] || 440.0
      const osc1 = audioCtx.createOscillator()
      const osc2 = audioCtx.createOscillator()
      const lfo = audioCtx.createOscillator()
      const lfoGain = audioCtx.createGain()
      const stGain = audioCtx.createGain()
      const panner = audioCtx.createStereoPanner()

      const isPirate = st.peak_deviation_khz > 82
      osc1.type = isPirate ? 'sawtooth' : 'sine'
      osc1.frequency.value = baseHz
      osc2.type = 'triangle'
      osc2.frequency.value = baseHz * 1.25

      lfo.type = 'sine'
      lfo.frequency.value = 1.4 + ((st.frequency_mhz - 88.0) / 20.0) * 1.8
      lfoGain.gain.value = 0.025

      panner.pan.value = Math.max(-0.92, Math.min(0.92, (st.frequency_mhz - 98.0) / 10.0))
      stGain.gain.value = 0.0

      osc1.connect(stGain)
      osc2.connect(stGain)
      lfo.connect(lfoGain)
      lfoGain.connect(stGain.gain)
      stGain.connect(panner)
      panner.connect(audioCtx.destination)

      osc1.start()
      osc2.start()
      lfo.start()
      stationNodes[fKey] = { osc1, osc2, lfo, stGain, panner }
    }
    webAudioActive.value = true
    updateWebAudioGains()
    flash('Started Zero-Latency WebAudio 10-Station Polyphonic FM Bank (toggle any station ON/MUTE/SOLO in 0 ms)!')
  } catch (e) {
    console.error('WebAudio error:', e)
  }
}

function updateWebAudioGains() {
  if (!webAudioActive.value || !audioCtx) return
  for (const st of stations.value) {
    const fKey = st.frequency_mhz.toFixed(1)
    const node = stationNodes[fKey]
    if (!node) continue
    const audible = isStationAudible(st.frequency_mhz)
    const userGain = stationGains[fKey] ?? 0.85
    const target = audible ? 0.045 * userGain : 0.0
    node.stGain.gain.setTargetAtTime(target, audioCtx.currentTime, 0.015)
  }
}

function stopWebAudioBank() {
  webAudioActive.value = false
  if (audioCtx) {
    try {
      audioCtx.close()
    } catch (_) {}
    audioCtx = null
    stationNodes = {}
  }
}

function stopAllLiveListening() {
  liveReceiverActive.value = false
  liveAllWavUrl.value = ''
  activeAudioUrl.value = ''
  stopWebAudioBank()
  syncLiveTunerToServer()
  flash('Stopped Live FM Band Receiver.')
}

onBeforeUnmount(() => {
  stopWebAudioBank()
})

onMounted(async () => {
  await fetchScannerStatus()
  consultOllamaModal(false)
})
</script>

<style scoped>
.fm-ext-card {
  border: 1px solid rgba(248, 81, 73, 0.38);
  background: linear-gradient(180deg, rgba(20, 26, 36, 0.98) 0%, rgba(12, 16, 23, 0.98) 100%);
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.fm-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 14px;
  flex-wrap: wrap;
}
.fm-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.fm-title {
  margin: 0;
  font-size: 1.02rem;
  color: #f0f6fc;
}
.sdr-pill {
  color: #79c0ff;
  border-color: rgba(88, 166, 255, 0.4);
  background: rgba(56, 139, 253, 0.1);
}
.pirate-pill {
  color: #ff7b72;
  border-color: rgba(248, 81, 73, 0.45);
  background: rgba(248, 81, 73, 0.12);
}
.bistatic-pill {
  color: #38bdf8;
  border-color: rgba(56, 189, 248, 0.45);
  background: rgba(56, 189, 248, 0.12);
}
.fm-sub {
  margin-top: 6px;
  font-size: 0.78rem;
  color: #8b949e;
  line-height: 1.45;
}
.fm-hdr-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.ctrl-lbl {
  font-size: 0.73rem;
  color: #8b949e;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.ctrl-select,
.ctrl-num {
  background: #0d1117;
  color: #e6edf3;
  border: 1px solid #30363d;
  border-radius: 6px;
  padding: 4px 7px;
  font-size: 0.75rem;
}
.ctrl-num {
  width: 62px;
}
.btn-scan {
  background: rgba(248, 81, 73, 0.18);
  border: 1px solid rgba(248, 81, 73, 0.55);
  color: #ff7b72;
  font-size: 0.75rem;
}
.btn-ollama {
  background: linear-gradient(135deg, #0284c7, #6e40c9);
  border: none;
  color: #fff;
  font-size: 0.75rem;
}
.fm-banner {
  background: rgba(46, 160, 67, 0.16);
  border: 1px solid rgba(63, 185, 80, 0.45);
  color: #7ee787;
  padding: 7px 12px;
  border-radius: 7px;
  font-size: 0.78rem;
}
.ollama-drawer {
  background: rgba(56, 189, 248, 0.06);
  border: 1px solid rgba(56, 189, 248, 0.35);
  border-radius: 9px;
  padding: 10px 13px;
}
.od-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.od-badge {
  font-size: 0.75rem;
  color: #79c0ff;
  font-weight: 700;
}
.od-ts {
  font-size: 0.69rem;
  color: #8b949e;
}
.od-summary {
  margin: 6px 0 8px;
  font-size: 0.79rem;
  color: #e6edf3;
}
.od-cols {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 10px;
}
.od-col {
  background: rgba(13, 17, 23, 0.75);
  border: 1px solid #21262d;
  border-radius: 7px;
  padding: 8px 10px;
}
.od-col-hdr {
  font-size: 0.72rem;
  color: #79c0ff;
  font-weight: 700;
  margin-bottom: 5px;
}
.od-col ul {
  margin: 0;
  padding-left: 16px;
  font-size: 0.73rem;
  color: #b1bac4;
  line-height: 1.42;
}
.fm-audio-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  background: #090e16;
  border: 1px solid #263854;
  border-radius: 8px;
  padding: 7px 12px;
  font-size: 0.75rem;
  color: #79c0ff;
}
.fm-wav-player {
  height: 32px;
  min-width: 250px;
}
.spectrum-box {
  background: #0b1018;
  border: 1px solid #1f2b3e;
  border-radius: 9px;
  padding: 10px 12px;
}
.spec-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 0.74rem;
  color: #9ecbff;
  margin-bottom: 6px;
}
.filter-pills {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.filt-btn {
  background: #121a28;
  border: 1px solid #26354d;
  color: #8b949e;
  border-radius: 99px;
  padding: 3px 10px;
  font-size: 0.69rem;
  cursor: pointer;
}
.filt-btn.active {
  background: rgba(88, 166, 255, 0.16);
  border-color: #58a6ff;
  color: #fff;
}
.spec-svg {
  width: 100%;
  height: 195px;
  display: block;
}
.st-bar-group {
  cursor: pointer;
}
.table-wrap {
  max-height: 340px;
  overflow-y: auto;
  border: 1px solid #1f2937;
  border-radius: 8px;
}
.fm-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.74rem;
}
.fm-table th,
.fm-table td {
  padding: 7px 10px;
  text-align: left;
  border-bottom: 1px solid #1b2432;
}
.fm-table th {
  background: #101722;
  color: #8b949e;
  position: sticky;
  top: 0;
}
.row-pirate {
  background: rgba(248, 81, 73, 0.05);
}
.row-pinned {
  background: rgba(56, 189, 248, 0.07);
}
.st-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.call-chip {
  background: #161f2e;
  border: 1px solid #2b3c56;
  color: #9ecbff;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 0.67rem;
}
.dev-bar-bg {
  width: 110px;
  height: 5px;
  background: #161f2c;
  border-radius: 99px;
  margin-top: 3px;
  overflow: hidden;
}
.dev-bar-fill {
  height: 100%;
}
.ok-badge {
  color: #7ee787;
  font-size: 0.69rem;
}
.warn-badge {
  color: #ffa657;
  font-size: 0.69rem;
}
.flag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.flag-pill {
  background: rgba(240, 136, 62, 0.14);
  border: 1px solid rgba(240, 136, 62, 0.45);
  color: #ffa657;
  padding: 1px 6px;
  border-radius: 99px;
  font-size: 0.66rem;
}
.flag-over {
  background: rgba(248, 81, 73, 0.16);
  border-color: rgba(248, 81, 73, 0.55);
  color: #ff7b72;
}
.clean-pill {
  color: #7ee787;
  font-size: 0.68rem;
}
.mini-btn {
  background: #141d2b;
  border: 1px solid #2b3c58;
  color: #c9d1d9;
  border-radius: 5px;
  padding: 3px 8px;
  font-size: 0.68rem;
  cursor: pointer;
}
.mini-btn:hover {
  border-color: #58a6ff;
  color: #fff;
}
.mpx-inspector {
  margin-top: 8px;
  padding: 9px 11px;
  background: rgba(13, 19, 30, 0.92);
  border: 1px solid #26354d;
  border-radius: 8px;
}
.mpx-insp-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.mpx-insp-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 8px;
}
.mpx-cell {
  background: #0d1117;
  border: 1px solid #1f2937;
  border-radius: 6px;
  padding: 6px 8px;
}
.mpx-lbl {
  font-size: 0.63rem;
  color: #8b949e;
}
.mpx-val {
  font-size: 0.85rem;
  font-weight: 700;
  margin: 2px 0;
}
.mpx-sub {
  font-size: 0.64rem;
  color: #8b949e;
}
.live-wall-box {
  background: linear-gradient(135deg, rgba(16, 26, 40, 0.96), rgba(11, 16, 26, 0.96));
  border: 1px solid rgba(56, 189, 248, 0.42);
  border-radius: 9px;
  padding: 11px 13px;
}
.lw-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
}
.lw-title {
  font-size: 0.85rem;
  font-weight: 700;
  color: #e6edf3;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.live-on-pill {
  background: rgba(248, 81, 73, 0.18);
  border-color: rgba(248, 81, 73, 0.65);
  color: #ff7b72;
}
.lw-sub {
  font-size: 0.74rem;
  color: #8b949e;
  margin-top: 4px;
  line-height: 1.4;
}
.lw-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.lw-btn-all {
  background: rgba(63, 185, 80, 0.16);
  border: 1px solid rgba(63, 185, 80, 0.55);
  color: #7ee787;
  font-size: 0.72rem;
}
.lw-btn-all.active {
  background: #238636;
  color: #fff;
}
.lw-btn-pirate {
  background: rgba(248, 81, 73, 0.16);
  border: 1px solid rgba(248, 81, 73, 0.55);
  color: #ff7b72;
  font-size: 0.72rem;
}
.lw-btn-pirate.active {
  background: #da3633;
  color: #fff;
}
.lw-btn-clean {
  background: rgba(56, 189, 248, 0.15);
  border: 1px solid rgba(56, 189, 248, 0.5);
  color: #7dd3fc;
  font-size: 0.72rem;
}
.lw-btn-clean.active {
  background: #0284c7;
  color: #fff;
}
.lw-btn-scan {
  background: rgba(210, 168, 255, 0.14);
  border: 1px solid rgba(210, 168, 255, 0.5);
  color: #e9d5ff;
  font-size: 0.72rem;
}
.lw-btn-scan.active {
  background: #6e40c9;
  color: #fff;
}
.lw-btn-webaudio {
  background: rgba(251, 191, 36, 0.14);
  border: 1px solid rgba(251, 191, 36, 0.5);
  color: #fbbf24;
  font-size: 0.72rem;
}
.lw-btn-webaudio.active {
  background: #b45309;
  color: #fff;
}
.lw-btn-stop {
  background: #21262d;
  border: 1px solid #30363d;
  color: #f85149;
  font-size: 0.72rem;
}
.live-strips-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(168px, 1fr));
  gap: 8px;
  margin-top: 10px;
}
.st-strip {
  background: #0c121d;
  border: 1px solid #223047;
  border-radius: 7px;
  padding: 7px 9px;
  display: flex;
  flex-direction: column;
  gap: 5px;
  transition: opacity 0.15s ease, border-color 0.15s ease;
}
.st-strip.strip-pirate {
  border-color: rgba(248, 81, 73, 0.38);
}
.st-strip.strip-solo {
  border-color: #fbbf24;
  box-shadow: 0 0 8px rgba(251, 191, 36, 0.25);
}
.st-strip.strip-muted {
  opacity: 0.48;
}
.strip-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 4px;
}
.pan-chip {
  font-size: 0.61rem;
  color: #38bdf8;
  background: rgba(56, 189, 248, 0.12);
  padding: 1px 4px;
  border-radius: 3px;
}
.strip-meta {
  display: flex;
  justify-content: space-between;
  font-size: 0.65rem;
  color: #8b949e;
}
.strip-vol {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 0.64rem;
  color: #8b949e;
}
.strip-vol input {
  width: 100%;
  height: 4px;
}
.strip-btns {
  display: flex;
  gap: 4px;
}
.strip-btn {
  flex: 1;
  background: #141d2b;
  border: 1px solid #2b3c58;
  color: #c9d1d9;
  border-radius: 4px;
  padding: 2px 4px;
  font-size: 0.62rem;
  cursor: pointer;
}
.strip-btn.btn-on {
  border-color: rgba(63, 185, 80, 0.5);
  color: #7ee787;
}
.strip-btn.btn-muted {
  border-color: rgba(248, 81, 73, 0.45);
  color: #ff7b72;
}
.strip-btn.btn-solo-on {
  background: rgba(251, 191, 36, 0.2);
  border-color: #fbbf24;
  color: #fbbf24;
}
</style>
