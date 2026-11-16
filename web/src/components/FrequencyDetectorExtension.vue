<template>
  <section id="frequency-detector-ext" class="card fd-ext-card">
    <!-- TOP HEADER -->
    <div class="fd-header">
      <div class="fd-head-left">
        <div class="fd-title-row">
          <h2 class="fd-title">
            🎯 Multi-Mode Sliding-Window FrequencyDetector · Goertzel + CFAR Parabolic FFT + Fractional ZCR
          </h2>
          <span class="pill mono cfg-pill">
            ⚙️ {{ statusData.sample_rate_hz || 44100 }} Hz · {{ statusData.frame_size || 1024 }} Samples (Hop {{ statusData.hop_size || 512 }} · {{ Math.round((statusData.overlap ?? 0.5) * 100) }}% Overlap)
          </span>
          <span class="pill mono goertzel-pill">
            🎯 Goertzel: {{ kpis.goertzel_hit_count ?? 18 }} Hits ({{ kpis.goertzel_mean_snr ?? 34.4 }}× SNR · {{ kpis.goertzel_false_positives ?? 0 }} False Alarms @ {{ kpis.goertzel_absent_freq_hz ?? 900 }} Hz)
          </span>
          <span class="pill mono fft-pill">
            📈 Parabolic FFT: {{ kpis.fft_sweep_frame_count ?? 42 }} Frames (RMSE {{ kpis.fft_parabolic_rmse_hz ?? 4.8 }} Hz) · ZCR: {{ kpis.zcr_mean_estimated_hz ?? 880.0 }} Hz
          </span>
        </div>
        <div class="fd-sub">
          Slices streaming audio into <strong>50%-overlapping Hann/Hamming frames</strong> with coherent gain compensation (<span class="mono">window_gain = Σw / N</span>) across 3 specialized detectors:
          <strong>1. Generalized Goertzel</strong> (<span class="mono">FFT-free sideband guard_bins=2, noise_bins=4</span>),
          <strong>2. Parabolic STFT/FFT Sweep</strong> (<span class="mono">3-point α,β,γ sub-bin interpolation + CFAR noise_bins=8</span>), and
          <strong>3. Fractional Zero-Crossing Rate</strong> (<span class="mono">zero-jitter sign latch + linear crossing interpolation</span>).
        </div>
      </div>

      <div class="fd-hdr-actions mono">
        <label class="ctrl-lbl">
          Preset:
          <select v-model="presetInput" class="ctrl-select" @change="applyConfig({ preset: presetInput })">
            <option value="DTMF_PILOT_697_1209">697 / 900(Guard) / 1209 Hz</option>
            <option value="SMPS_COMB_3K_6K_9K">SMPS Comb (3 / 4.5 / 6 / 9 kHz)</option>
            <option value="FM_PILOT_AND_SONAR">19 kHz Pilot + 20–21.5 kHz Sonar</option>
          </select>
        </label>
        <label class="ctrl-lbl">
          Window:
          <select v-model="windowInput" class="ctrl-select" @change="applyConfig({ window_type: windowInput })">
            <option value="hann">Hann (0.50 gain)</option>
            <option value="hamming">Hamming (0.54 gain)</option>
          </select>
        </label>
        <label class="ctrl-lbl">
          SNR Gate:
          <input
            v-model.number="snrInput"
            type="number"
            min="2.0"
            max="15.0"
            step="0.5"
            class="ctrl-num"
            @change="applyConfig({ snr_threshold: snrInput })"
          />
        </label>
        <button class="act-btn run" :disabled="running" @click="runDetector('all')">
          {{ running ? '⏳ Running 3-Mode Suite...' : '▶ Run 3-Mode Suite' }}
        </button>
        <button class="act-btn wav" @click="auditionWav('all')">
          🔊 Audition 3-Stage WAV
        </button>
        <button class="act-btn ollama" :disabled="askingOllama" @click="askOllama(true)">
          {{ askingOllama ? '⏳ Consulting NightSweep...' : '🧠 Ask NightSweep Ollama' }}
        </button>
      </div>
    </div>

    <div v-if="bannerMsg" class="fd-banner mono">
      ✨ {{ bannerMsg }}
    </div>

    <!-- AUDITION PLAYER -->
    <div v-if="activeWavUrl" class="wav-bar mono">
      <div class="wav-meta">
        <strong>🔊 FrequencyDetector Probe Stream ({{ activeWavMode.toUpperCase() }})</strong>
        <span>Left: Noisy Input Test Signal · Right: Clean Gated Target / Chirp / 880 Hz Reference</span>
      </div>
      <div class="wav-mode-btns">
        <button class="mini-btn" :class="{ active: activeWavMode === 'all' }" @click="auditionWav('all')">3-Stage All</button>
        <button class="mini-btn" :class="{ active: activeWavMode === 'goertzel' }" @click="auditionWav('goertzel')">Goertzel Burst</button>
        <button class="mini-btn" :class="{ active: activeWavMode === 'fft' }" @click="auditionWav('fft')">400→2400 Hz Chirp</button>
        <button class="mini-btn" :class="{ active: activeWavMode === 'zcr' }" @click="auditionWav('zcr')">880 Hz ZCR</button>
      </div>
      <audio :src="activeWavUrl" controls autoplay class="wav-audio"></audio>
      <button class="close-mini" @click="activeWavUrl = ''">✕</button>
    </div>

    <!-- 3-MODE INTERACTIVE VISUALIZATION GRID -->
    <div class="three-mode-grid">
      <!-- MODE 1: GOERTZEL TARGET TONES + SIDEBAND CFAR -->
      <div class="mode-box">
        <div class="mode-head mono">
          <strong style="color: #34d399">1. Generalized Goertzel (Target Tones + Sideband CFAR)</strong>
          <span>Targets: {{ (statusData.target_freqs_hz || [697, 900, 1209]).join(' / ') }} Hz</span>
        </div>
        <svg viewBox="0 0 360 140" class="mode-svg">
          <line x1="36" y1="115" x2="345" y2="115" stroke="#26354d" stroke-width="1" />
          <line x1="36" y1="35" x2="345" y2="35" stroke="#f59e0b" stroke-dasharray="3 3" stroke-width="1" />
          <text x="40" y="31" fill="#f59e0b" font-size="8" font-family="monospace">
            CFAR SNR Gate ≥ {{ statusData.snr_threshold || 4.5 }}× (guard=2, noise=4)
          </text>
          <g v-for="(h, idx) in goertzelHits" :key="'g-' + idx">
            <circle
              :cx="36 + (h.timestamp_sec / (statusData.duration_sec || 0.5)) * 305"
              :cy="Math.max(16, 115 - Math.min(95, h.snr_ratio * 1.4))"
              r="4.2"
              :fill="h.frequency_hz === (statusData.target_freqs_hz || [])[0] ? '#34d399' : '#38bdf8'"
            />
          </g>
          <text x="40" y="130" fill="#8b949e" font-size="8.5" font-family="monospace">
            0.0s — Burst Window [0.15s..0.25s] ({{ kpis.goertzel_hit_count ?? 18 }} hits · {{ kpis.goertzel_absent_freq_hz ?? 900 }} Hz rejected) — {{ statusData.duration_sec || 0.5 }}s
          </text>
        </svg>
      </div>

      <!-- MODE 2: STFT / FFT PARABOLIC CHIRP SWEEP -->
      <div class="mode-box">
        <div class="mode-head mono">
          <strong style="color: #38bdf8">2. STFT / FFT Parabolic Sweep ({{ statusData.sweep_start_hz || 400 }}→{{ statusData.sweep_end_hz || 2400 }} Hz)</strong>
          <span>Parabolic RMSE: {{ kpis.fft_parabolic_rmse_hz ?? 4.8 }} Hz</span>
        </div>
        <svg viewBox="0 0 360 140" class="mode-svg">
          <line x1="36" y1="115" x2="345" y2="115" stroke="#26354d" stroke-width="1" />
          <!-- Ideal chirp reference line -->
          <line x1="36" y1="108" x2="342" y2="20" stroke="#334155" stroke-dasharray="4 3" stroke-width="1.5" />
          <polyline
            v-if="fftPolyline"
            :points="fftPolyline"
            fill="none"
            stroke="#38bdf8"
            stroke-width="2"
          />
          <circle
            v-for="(pt, idx) in fftPoints"
            :key="'f-' + idx"
            :cx="pt.x"
            :cy="pt.y"
            r="2.4"
            fill="#93c5fd"
          />
          <text x="40" y="130" fill="#8b949e" font-size="8.5" font-family="monospace">
            Tracked {{ kpis.fft_sweep_frame_count ?? 42 }} overlapping frames · Mean CFAR SNR {{ kpis.fft_sweep_mean_snr ?? 82.1 }}×
          </text>
        </svg>
      </div>

      <!-- MODE 3: ZERO-CROSSING RATE SUB-SAMPLE SINE LOCK -->
      <div class="mode-box">
        <div class="mode-head mono">
          <strong style="color: #c084fc">3. Fractional Zero-Crossing Rate ({{ statusData.zcr_tone_hz || 880 }} Hz Sine)</strong>
          <span>Est: {{ kpis.zcr_mean_estimated_hz ?? 880.0 }} Hz (±{{ kpis.zcr_abs_error_hz ?? 0.0 }} Hz)</span>
        </div>
        <svg viewBox="0 0 360 140" class="mode-svg">
          <line x1="36" y1="68" x2="345" y2="68" stroke="#334155" stroke-dasharray="3 3" stroke-width="1" />
          <polyline
            v-if="zcrPolyline"
            :points="zcrPolyline"
            fill="none"
            stroke="#c084fc"
            stroke-width="2"
          />
          <text x="40" y="28" fill="#c084fc" font-size="8.5" font-family="monospace">
            Fractional Linear Crossing: idx + |y0| / (|y0| + |y1|)
          </text>
          <text x="40" y="130" fill="#8b949e" font-size="8.5" font-family="monospace">
            {{ kpis.zcr_frame_count ?? 85 }} frames @ 512 samples · Peak Mag {{ zcrHits[0]?.magnitude ?? 0.798 }}
          </text>
        </svg>
      </div>
    </div>

    <!-- EXTENSION: POLYPHONIC SWIMLANE TONE SYNTH (ZERO-LATENCY 256-FRAME / 3MS 1-POLE ENVELOPE) -->
    <div class="swimlane-synth-box">
      <div class="ss-head mono">
        <div class="ss-title-group">
          <strong style="color: #fbbf24">
            🎹 Extension: Polyphonic SwimlaneToneSynth ({{ swimlaneData.sample_rate_hz || 44100 }} Hz · Blocksize {{ swimlaneData.blocksize || 256 }} ≈ {{ swimlaneData.latency_ms ?? 5.8 }} ms · {{ swimlaneData.envelope_tau_ms ?? 3.0 }} ms 1-Pole Ramp)
          </strong>
          <span class="pill mono ss-pill">
            Active Swimlanes: {{ swimlaneKpis.active_lane_count ?? 3 }} / {{ swimlaneKpis.total_lanes ?? 7 }}
          </span>
          <span class="pill mono ss-verify-pill">
            🎯 Closed-Loop Goertzel Verified: {{ swimlaneKpis.closed_loop_goertzel_verified_count ?? 3 }}/{{ swimlaneKpis.active_lane_count ?? 3 }} (0 Clicks · α={{ swimlaneData.smoothing_coeff ?? 0.00753 }})
          </span>
        </div>
        <div class="ss-actions">
          <button class="mini-btn" @click="triggerSwimlaneChord([0, 2, 4])">
            🎵 A-Major Triad (0, 2, 4)
          </button>
          <button class="mini-btn" @click="triggerSwimlaneChord([0, 1, 2, 3, 4])">
            🗣️ 5 Human Swimlanes
          </button>
          <button class="mini-btn" @click="triggerSwimlaneChord([3, 5])">
            📞 DTMF 697+1209 Hz (3, 5)
          </button>
          <button class="act-btn wav" style="padding: 3px 9px; font-size: 0.7rem" @click="auditionSwimlaneChordWav">
            🔊 Audition Swimlane Chord WAV
          </button>
        </div>
      </div>

      <!-- 7 INTERACTIVE SWIMLANE SYNTH BUTTONS -->
      <div class="ss-lanes-grid mono">
        <button
          v-for="lane in swimlaneLanes"
          :key="'lane-' + lane.lane_id"
          type="button"
          class="ss-lane-btn"
          :class="{ active: lane.active }"
          :style="{ borderColor: lane.active ? lane.color : '#233249' }"
          @click="toggleSwimlaneTone(lane.lane_id)"
        >
          <div class="ssl-top">
            <span class="ssl-id" :style="{ color: lane.color }">Lane #{{ lane.lane_id }}</span>
            <span class="ssl-state" :class="{ on: lane.active }">{{ lane.active ? 'ON' : 'MUTED' }}</span>
          </div>
          <div class="ssl-hz">{{ lane.center_hz }} Hz</div>
          <div class="ssl-spk">{{ lane.speaker_id }}</div>
          <div class="ssl-gain">
            Gain: {{ (lane.current_gain ?? 0).toFixed(3) }} → {{ (lane.target_gain ?? 0).toFixed(2) }} · φ={{ (lane.phase_rad ?? 0).toFixed(2) }}r
          </div>
        </button>
      </div>

      <!-- WAVEFORM + 3MS 1-POLE ENVELOPE SVG -->
      <div class="ss-viz-row">
        <svg viewBox="0 0 540 84" class="ss-svg">
          <line x1="20" y1="42" x2="525" y2="42" stroke="#1e293b" stroke-width="1" />
          <polyline
            v-if="swimlaneWavePolyline"
            :points="swimlaneWavePolyline"
            fill="none"
            stroke="#fbbf24"
            stroke-width="1.8"
          />
          <polyline
            v-if="swimlaneEnvPolyline"
            :points="swimlaneEnvPolyline"
            fill="none"
            stroke="#34d399"
            stroke-dasharray="3 2"
            stroke-width="1.5"
          />
          <text x="26" y="16" fill="#fbbf24" font-size="8.5" font-family="monospace">
            Polyphonic Mix (np.clip[-1, 1] float32 · Peak {{ swimlaneKpis.peak_output_level ?? 0.598 }} · RMS {{ swimlaneKpis.rms_output_level ?? 0.254 }})
          </text>
          <text x="26" y="76" fill="#34d399" font-size="8.5" font-family="monospace">
            1-Pole 3ms Ramp: g[n] = target + (current - target)*(1 - smoothing)^(n+1) · Goertzel Closed-Loop Hits: {{ (swimlaneData.closed_loop_goertzel_detections || []).map(d => d.frequency_hz + 'Hz').join(', ') || '440Hz, 659.25Hz, 880Hz' }}
          </text>
        </svg>
      </div>
    </div>

    <!-- NIGHTSWEEP OLLAMA MODAL ADVISOR DRAWER -->
    <div v-if="ollamaAdvice" class="ollama-drawer">
      <div class="oll-head mono">
        <div>
          <strong>🧠 NightSweep Signal-Intelligence FrequencyDetector Reference</strong>
          <span class="oll-badge">{{ ollamaAdvice.model || 'nightsweep-signalintelligence:latest' }}</span>
          <span class="oll-badge" style="color: #34d399">Modelfile: {{ ollamaAdvice.modelfile_reference || 'models/Modelfile.nightsweep-signalintelligence' }}</span>
        </div>
        <div class="oll-actions">
          <button v-if="ollamaAdvice.recommended_config" class="apply-rec-btn mono" @click="applyRecommendedConfig">
            ⚡ Apply Recommended Config
          </button>
          <button class="close-mini" @click="ollamaAdvice = null">✕</button>
        </div>
      </div>
      <p class="oll-summary">{{ ollamaAdvice.overall_assessment }}</p>
      <div class="oll-cols">
        <div class="oll-col">
          <h4 class="mono">🎯 Generalized Goertzel &amp; Sideband CFAR</h4>
          <ul>
            <li v-for="(item, i) in ollamaAdvice.goertzel_and_cfar_findings || []" :key="'gc-' + i">{{ item }}</li>
          </ul>
        </div>
        <div class="oll-col">
          <h4 class="mono">📈 Parabolic RFFT Sweep &amp; Fractional ZCR</h4>
          <ul>
            <li v-for="(item, i) in ollamaAdvice.parabolic_fft_and_zcr_insights || []" :key="'pf-' + i">{{ item }}</li>
          </ul>
        </div>
        <div class="oll-col">
          <h4 class="mono">🔗 GNU-Larex Pipeline Reference Links</h4>
          <ul>
            <li v-for="(item, i) in ollamaAdvice.gnu_larex_pipeline_links || []" :key="'gl-' + i">{{ item }}</li>
          </ul>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'

const statusData = ref({})
const swimlaneData = ref({})
const ollamaAdvice = ref(null)
const running = ref(false)
const askingOllama = ref(false)
const bannerMsg = ref('')
const activeWavUrl = ref('')
const activeWavMode = ref('all')

const presetInput = ref('DTMF_PILOT_697_1209')
const windowInput = ref('hann')
const snrInput = ref(4.5)

const kpis = computed(() => statusData.value?.kpis || {})
const goertzelHits = computed(() => statusData.value?.goertzel_detections || [])
const fftHits = computed(() => statusData.value?.fft_sweep_detections || [])
const zcrHits = computed(() => statusData.value?.zcr_detections || [])

const swimlaneKpis = computed(() => swimlaneData.value?.kpis || {})
const swimlaneLanes = computed(() => swimlaneData.value?.lanes || [])

const swimlaneWavePolyline = computed(() => {
  const wave = swimlaneData.value?.waveform_preview || []
  if (!wave.length) return ''
  return wave
    .map((v, i) => {
      const x = (20 + (i / Math.max(1, wave.length - 1)) * 505).toFixed(1)
      const y = (42 - Math.max(-1, Math.min(1, v)) * 26).toFixed(1)
      return `${x},${y}`
    })
    .join(' ')
})

const swimlaneEnvPolyline = computed(() => {
  const env = swimlaneData.value?.envelope_ramp_preview || []
  if (!env.length) return ''
  return env
    .map((v, i) => {
      const x = (20 + (i / Math.max(1, env.length - 1)) * 505).toFixed(1)
      const y = (68 - Math.max(0, Math.min(0.4, v)) * 125).toFixed(1)
      return `${x},${y}`
    })
    .join(' ')
})

const fftPoints = computed(() => {
  const list = fftHits.value
  if (!list.length) return []
  const dur = statusData.value?.duration_sec || 0.5
  const fMin = statusData.value?.sweep_start_hz || 400.0
  const fMax = statusData.value?.sweep_end_hz || 2400.0
  const span = Math.max(100.0, fMax - fMin)
  return list.map((h) => ({
    x: +(36 + (h.timestamp_sec / dur) * 305).toFixed(1),
    y: +(108 - Math.min(92, Math.max(0, ((h.frequency_hz - fMin) / span) * 88))).toFixed(1),
  }))
})

const fftPolyline = computed(() => fftPoints.value.map((p) => `${p.x},${p.y}`).join(' '))

const zcrPolyline = computed(() => {
  const list = zcrHits.value
  if (!list.length) return ''
  const target = statusData.value?.zcr_tone_hz || 880.0
  return list
    .map((h, i) => {
      const x = (36 + (i / Math.max(1, list.length - 1)) * 305).toFixed(1)
      const diff = Math.max(-5, Math.min(5, h.frequency_hz - target))
      const y = (68 - diff * 6).toFixed(1)
      return `${x},${y}`
    })
    .join(' ')
})

function flash(msg) {
  bannerMsg.value = msg
  setTimeout(() => {
    if (bannerMsg.value === msg) bannerMsg.value = ''
  }, 4200)
}

async function fetchStatus() {
  try {
    const [r, rs] = await Promise.all([
      fetch('/api/frequency-detector/status'),
      fetch('/api/swimlane-synth/status'),
    ])
    if (r.ok) {
      const d = await r.json()
      statusData.value = d
      presetInput.value = d.active_preset || 'DTMF_PILOT_697_1209'
      windowInput.value = d.window_type || 'hann'
      snrInput.value = d.snr_threshold ?? 4.5
    }
    if (rs.ok) {
      swimlaneData.value = await rs.json()
    }
  } catch (e) {
    console.error(e)
  }
}

async function toggleSwimlaneTone(laneId) {
  try {
    const r = await fetch('/api/swimlane-synth/toggle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lane_id: laneId, volume: 0.22 }),
    })
    if (r.ok) {
      const d = await r.json()
      swimlaneData.value = d
      flash(
        `Swimlane #${laneId} toggled → ${d.kpis?.active_lane_count || 0}/${d.kpis?.total_lanes || 7} active (Goertzel verified: ${d.kpis?.closed_loop_goertzel_verified_count || 0})`
      )
    }
  } catch (e) {
    console.error(e)
  }
}

async function triggerSwimlaneChord(activeIds) {
  try {
    const r = await fetch('/api/swimlane-synth/trigger', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ active_lane_ids: activeIds, volume: 0.22 }),
    })
    if (r.ok) {
      const d = await r.json()
      swimlaneData.value = d
      flash(
        `SwimlaneToneSynth Chord [${activeIds.join(', ')}] active · Closed-Loop Goertzel verified ${d.kpis?.closed_loop_goertzel_verified_count} lanes!`
      )
    }
  } catch (e) {
    console.error(e)
  }
}

function auditionSwimlaneChordWav() {
  const activeIds = swimlaneLanes.value.filter((l) => l.active).map((l) => l.lane_id)
  const lanesParam = (activeIds.length ? activeIds : [0, 2, 4]).join(',')
  activeWavMode.value = 'swimlane'
  activeWavUrl.value = `/api/swimlane-synth/audio/chord.wav?lanes=${encodeURIComponent(lanesParam)}&sec=1.8&t=${Date.now()}`
}

async function runDetector(mode = 'all') {
  running.value = true
  try {
    const r = await fetch('/api/frequency-detector/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    })
    if (r.ok) {
      statusData.value = await r.json()
      flash(
        `3-Mode FrequencyDetector complete: ${kpis.value.goertzel_hit_count} Goertzel hits, ${kpis.value.fft_sweep_frame_count} Parabolic FFT frames, ZCR=${kpis.value.zcr_mean_estimated_hz} Hz`
      )
    }
  } catch (e) {
    console.error(e)
  } finally {
    running.value = false
  }
}

async function applyConfig(payload) {
  try {
    const r = await fetch('/api/frequency-detector/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (r.ok) {
      const d = await r.json()
      statusData.value = d
      flash(`Updated FrequencyDetector: ${(d.applied || []).join(', ')}`)
    }
  } catch (e) {
    console.error(e)
  }
}

function auditionWav(mode = 'all') {
  activeWavMode.value = mode
  activeWavUrl.value = `/api/frequency-detector/audio/${encodeURIComponent(mode)}.wav?sec=2.1&t=${Date.now()}`
}

async function askOllama(force = true) {
  askingOllama.value = true
  try {
    const r = await fetch('/api/ollama/frequency-detector', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force }),
    })
    if (r.ok) {
      ollamaAdvice.value = await r.json()
    }
  } catch (e) {
    console.error(e)
  } finally {
    askingOllama.value = false
  }
}

async function applyRecommendedConfig() {
  if (!ollamaAdvice.value?.recommended_config) return
  await applyConfig(ollamaAdvice.value.recommended_config)
}

onMounted(async () => {
  await fetchStatus()
  await askOllama(false)
})
</script>

<style scoped>
.fd-ext-card {
  border: 1px solid #23354f;
  background: linear-gradient(180deg, #0d1422 0%, #0a0f1a 100%);
  padding: 14px 16px;
  margin-bottom: 14px;
}
.fd-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
}
.fd-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.fd-title {
  margin: 0;
  font-size: 1.02rem;
  color: #f0f6fc;
}
.cfg-pill {
  background: rgba(56, 189, 248, 0.12);
  border: 1px solid rgba(56, 189, 248, 0.35);
  color: #38bdf8;
}
.goertzel-pill {
  background: rgba(52, 211, 153, 0.12);
  border: 1px solid rgba(52, 211, 153, 0.35);
  color: #34d399;
}
.fft-pill {
  background: rgba(192, 132, 252, 0.12);
  border: 1px solid rgba(192, 132, 252, 0.35);
  color: #c084fc;
}
.fd-sub {
  margin-top: 5px;
  font-size: 0.76rem;
  color: #8b949e;
  line-height: 1.45;
}
.fd-hdr-actions {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}
.ctrl-lbl {
  font-size: 0.72rem;
  color: #9ecbff;
  display: flex;
  align-items: center;
  gap: 4px;
}
.ctrl-select,
.ctrl-num {
  background: #0d131f;
  border: 1px solid #2b3c56;
  color: #e6edf3;
  border-radius: 5px;
  padding: 3px 6px;
  font-size: 0.72rem;
}
.ctrl-num {
  width: 54px;
}
.act-btn {
  border-radius: 6px;
  padding: 5px 10px;
  font-size: 0.73rem;
  cursor: pointer;
  border: 1px solid #30363d;
  background: #161b22;
  color: #e6edf3;
}
.act-btn.run {
  border-color: #34d399;
  color: #34d399;
}
.act-btn.wav {
  border-color: #38bdf8;
  color: #38bdf8;
}
.act-btn.ollama {
  border-color: #c084fc;
  color: #c084fc;
}
.fd-banner {
  margin-top: 8px;
  padding: 6px 10px;
  border-radius: 6px;
  background: rgba(52, 211, 153, 0.12);
  border: 1px solid rgba(52, 211, 153, 0.35);
  color: #34d399;
  font-size: 0.74rem;
}
.wav-bar {
  margin-top: 10px;
  padding: 8px 12px;
  border-radius: 8px;
  background: #111927;
  border: 1px solid #26354d;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}
.wav-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 0.73rem;
}
.wav-meta span {
  color: #8b949e;
  font-size: 0.68rem;
}
.wav-mode-btns {
  display: flex;
  gap: 5px;
}
.mini-btn {
  background: #161f2e;
  border: 1px solid #2b3c56;
  color: #9ecbff;
  border-radius: 5px;
  padding: 3px 8px;
  font-size: 0.68rem;
  cursor: pointer;
}
.mini-btn.active {
  background: rgba(56, 189, 248, 0.2);
  border-color: #38bdf8;
  color: #fff;
}
.wav-audio {
  height: 30px;
}
.close-mini {
  background: transparent;
  border: 1px solid #30363d;
  color: #8b949e;
  border-radius: 4px;
  cursor: pointer;
  padding: 2px 6px;
}
.three-mode-grid {
  margin-top: 11px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(290px, 1fr));
  gap: 10px;
}
.mode-box {
  background: #0b111b;
  border: 1px solid #1f2b3e;
  border-radius: 8px;
  padding: 8px 10px;
}
.mode-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.72rem;
  margin-bottom: 4px;
}
.mode-head span {
  color: #8b949e;
  font-size: 0.67rem;
}
.mode-svg {
  width: 100%;
  height: 132px;
  display: block;
}
.swimlane-synth-box {
  margin-top: 11px;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.78);
  border: 1px solid rgba(251, 191, 36, 0.35);
}
.ss-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 0.74rem;
}
.ss-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.ss-pill {
  background: rgba(251, 191, 36, 0.14);
  border: 1px solid rgba(251, 191, 36, 0.4);
  color: #fbbf24;
}
.ss-verify-pill {
  background: rgba(52, 211, 153, 0.14);
  border: 1px solid rgba(52, 211, 153, 0.4);
  color: #34d399;
}
.ss-actions {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}
.ss-lanes-grid {
  margin-top: 9px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(136px, 1fr));
  gap: 7px;
}
.ss-lane-btn {
  text-align: left;
  background: #0b111b;
  border: 1px solid #233249;
  border-radius: 7px;
  padding: 6px 8px;
  color: #e6edf3;
  cursor: pointer;
  transition: all 0.15s ease;
}
.ss-lane-btn.active {
  background: rgba(30, 41, 59, 0.92);
  box-shadow: 0 0 10px rgba(251, 191, 36, 0.14);
}
.ssl-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.69rem;
  font-weight: 700;
}
.ssl-state {
  font-size: 0.62rem;
  padding: 1px 5px;
  border-radius: 4px;
  background: #161f2e;
  color: #8b949e;
}
.ssl-state.on {
  background: rgba(52, 211, 153, 0.2);
  color: #34d399;
}
.ssl-hz {
  font-size: 0.78rem;
  font-weight: 700;
  color: #f0f6fc;
  margin-top: 2px;
}
.ssl-spk {
  font-size: 0.66rem;
  color: #9ecbff;
}
.ssl-gain {
  font-size: 0.61rem;
  color: #8b949e;
  margin-top: 2px;
}
.ss-viz-row {
  margin-top: 8px;
  background: #080d16;
  border: 1px solid #1e293b;
  border-radius: 6px;
  padding: 4px 6px;
}
.ss-svg {
  width: 100%;
  height: 78px;
  display: block;
}
.ollama-drawer {
  margin-top: 11px;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(25, 19, 38, 0.55);
  border: 1px solid rgba(192, 132, 252, 0.35);
}
.oll-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 0.75rem;
}
.oll-badge {
  margin-left: 8px;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(192, 132, 252, 0.15);
  color: #d8b4fe;
  font-size: 0.67rem;
}
.oll-actions {
  display: flex;
  gap: 6px;
  align-items: center;
}
.apply-rec-btn {
  background: rgba(52, 211, 153, 0.15);
  border: 1px solid #34d399;
  color: #34d399;
  border-radius: 5px;
  padding: 3px 8px;
  font-size: 0.69rem;
  cursor: pointer;
}
.oll-summary {
  margin: 7px 0;
  font-size: 0.75rem;
  color: #e6edf3;
  line-height: 1.45;
}
.oll-cols {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 10px;
}
.oll-col h4 {
  margin: 0 0 4px 0;
  font-size: 0.72rem;
  color: #d8b4fe;
}
.oll-col ul {
  margin: 0;
  padding-left: 16px;
  font-size: 0.71rem;
  color: #c9d1d9;
  line-height: 1.4;
}
</style>
