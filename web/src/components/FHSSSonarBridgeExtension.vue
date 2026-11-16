<template>
  <section id="fhss-sonar-bridge-ext" class="card fhss-ext-card">
    <!-- TOP HEADER -->
    <div class="fhss-header">
      <div class="fhss-head-left">
        <div class="fhss-title-row">
          <h2 class="fhss-title">
            🔊 FrequencyHoppingSonarBridge · 19.0–22.0 kHz FHSS Anti-Intercept Ultrasonic Transceiver &amp; Quadrature I/Q Reflection Loop
          </h2>
          <span class="pill mono carrier-pill">
            📡 Active Hop #{{ statusData.current_hop_idx ?? 0 }}: {{ kpis.active_carrier_khz ?? 20.5 }} kHz ({{ statusData.sample_rate_hz || 48000 }} Hz · {{ statusData.chunk_size || 1024 }} blk)
          </span>
          <span class="pill mono iq-pill">
            🧬 I/Q Energy: {{ kpis.mean_quadrature_iq_energy ?? 0.0186 }} (Gate &gt;{{ statusData.reflection_threshold ?? 0.008 }}) · Muscle Δd={{ kpis.mean_muscle_displacement_um ?? 42.8 }} µm
          </span>
          <span class="pill mono guard-pill">
            🛡️ Anti-Intercept Guard: +{{ kpis.intercept_guard_db ?? 31.4 }} dB · {{ kpis.entropy_bits_per_hop ?? 2.81 }} bits/hop
          </span>
        </div>
        <div class="fhss-sub">
          Safeguards the <strong>19.0–22.0 kHz</strong> active ultrasonic pilot tracking loop against reverse-intercept &amp; stationary notch vectors via
          <strong>Coprime LCG Hop Scheduling</strong> (<span class="mono">7 channels · 500 Hz spacing</span>),
          <strong>Modulo-2π Phase-Continuous Synthesis</strong> (<span class="mono">phase_accumulator</span>), and stateful 2nd-order
          <strong>50 Hz Butterworth Quadrature (I/Q) Coherent Demodulation</strong>.
        </div>
      </div>

      <div class="fhss-hdr-actions mono">
        <label class="ctrl-lbl">
          Hop Window (s):
          <input
            v-model.number="hopIntervalInput"
            type="number"
            min="0.25"
            max="10.0"
            step="0.25"
            class="ctrl-num"
            @change="applyConfigOnly"
          />
        </label>
        <label class="ctrl-lbl">
          LCG Stride:
          <select v-model.number="lcgMultiplierInput" class="ctrl-select" @change="applyConfigOnly">
            <option :value="3">3 (Coprime Full-7)</option>
            <option :value="5">5 (Coprime Reverse)</option>
            <option :value="2">2 (Coprime Step-1k)</option>
          </select>
        </label>
        <label class="ctrl-lbl">
          LPF (Hz):
          <input
            v-model.number="lpfCutoffInput"
            type="number"
            min="15"
            max="150"
            step="5"
            class="ctrl-num"
            @change="applyConfigOnly"
          />
        </label>
        <button
          type="button"
          class="btn btn-hop mono"
          :disabled="hopBusy"
          @click="triggerSingleHop"
        >
          {{ hopBusy ? '🔀 Hopping…' : '🔀 Step Next FHSS Hop' }}
        </button>
        <button
          type="button"
          class="btn btn-cycle mono"
          :disabled="hopBusy"
          @click="triggerFullCycle"
        >
          🔄 Run 7-Channel Hop Sweep
        </button>
        <button
          type="button"
          class="btn btn-wav mono"
          @click="auditionHopStreamWav"
        >
          🔊 Audition FHSS + I/Q WAV
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

    <div v-if="bannerMsg" class="fhss-banner mono">
      ✅ {{ bannerMsg }}
    </div>

    <!-- NIGHTSWEEP OLLAMA MODAL ADVISOR DRAWER -->
    <div v-if="ollamaAdvice" class="ollama-drawer">
      <div class="od-top">
        <span class="mono od-badge">
          🧠 {{ ollamaAdvice.model || 'nightsweep-signalintelligence:latest' }} · FHSS Ultrasonic Sonar Modal Reference
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
            ⚡ Apply Recommended LCG Stride={{ ollamaAdvice.recommended_config.lcg_multiplier }} &amp; {{ ollamaAdvice.recommended_config.lpf_cutoff_hz }} Hz I/Q LPF
          </button>
          <span class="mono od-ts">{{ ollamaAdvice.generated_at_utc }}</span>
        </div>
      </div>
      <p class="od-summary">{{ ollamaAdvice.overall_assessment }}</p>
      <div class="od-cols">
        <div class="od-col">
          <div class="od-col-hdr mono">🛡️ FHSS Anti-Intercept &amp; LCG Permutation</div>
          <ul>
            <li v-for="(it, idx) in (ollamaAdvice.fhss_security_and_lcg_findings || [])" :key="'fs-' + idx">
              {{ it }}
            </li>
          </ul>
        </div>
        <div class="od-col">
          <div class="od-col-hdr mono">🔬 Stateful 50 Hz Quadrature (I/Q) &amp; Phase</div>
          <ul>
            <li v-for="(it, idx) in (ollamaAdvice.quadrature_iq_and_phase_insights || [])" :key="'qi-' + idx">
              {{ it }}
            </li>
          </ul>
        </div>
        <div class="od-col">
          <div class="od-col-hdr mono">🔗 GNU-Larex Somatic &amp; Saccade Integration</div>
          <ul>
            <li v-for="(it, idx) in (ollamaAdvice.application_integration_links || [])" :key="'al-' + idx">
              {{ it }}
            </li>
          </ul>
        </div>
      </div>
    </div>

    <!-- AUDITION WAV BAR -->
    <div v-if="activeAudioUrl" class="fhss-audio-bar mono">
      <span>
        🔊 48 kHz Stereo FHSS Transceiver Stream (<strong>L: 19–22 kHz Ultrasonic + Heterodyned Pilot Monitor · R: &lt;50 Hz Demodulated I/Q Muscle Reflection</strong>):
      </span>
      <audio :key="activeAudioUrl" :src="activeAudioUrl" controls autoplay class="fhss-wav-player"></audio>
    </div>

    <!-- INTERACTIVE 19.0–22.0 KHZ 7-CHANNEL HOP TRAJECTORY & QUADRATURE REFLECTION SVG -->
    <div class="spectrum-box">
      <div class="spec-top mono">
        <span>
          📈 19.0–22.0 kHz Phase-Continuous FHSS Hop Trajectory &amp; Coherent Quadrature (I/Q) Muscle Reflection Envelope
        </span>
        <span>
          Phase Accumulator: <strong style="color: #7ee787">{{ statusData.phase_accumulator_rad ?? 0 }} rad</strong> ·
          Gate: <strong style="color: #38bdf8">&gt;{{ statusData.reflection_threshold ?? 0.008 }} RMS</strong>
        </span>
      </div>

      <svg viewBox="0 0 920 195" class="spec-svg" role="img" aria-label="19 to 22 kHz FHSS Hop Trajectory">
        <!-- Horizontal Channel Lines (19.0 to 22.0 kHz) -->
        <g v-for="freq in [19000, 19500, 20000, 20500, 21000, 21500, 22000]" :key="'ch-' + freq">
          <line
            x1="85"
            :y1="freqToY(freq)"
            x2="885"
            :y2="freqToY(freq)"
            :stroke="Math.abs((statusData.active_carrier_hz || 20500) - freq) < 50 ? '#3fb950' : '#1f2937'"
            :stroke-width="Math.abs((statusData.active_carrier_hz || 20500) - freq) < 50 ? 1.6 : 1"
            stroke-dasharray="4 4"
          />
          <text
            x="76"
            :y="freqToY(freq) + 3.5"
            :fill="Math.abs((statusData.active_carrier_hz || 20500) - freq) < 50 ? '#7ee787' : '#8b949e'"
            font-size="10"
            text-anchor="end"
            font-family="monospace"
          >
            {{ (freq / 1000).toFixed(1) }} kHz
          </text>
        </g>

        <!-- Trajectory Polyline Connecting Hops -->
        <polyline
          v-if="hopPolylinePoints"
          :points="hopPolylinePoints"
          fill="none"
          stroke="#38bdf8"
          stroke-width="2.4"
          stroke-linejoin="round"
        />

        <!-- Hop Nodes -->
        <g
          v-for="(hop, idx) in hopTelemetry"
          :key="'hn-' + idx"
          class="hop-node"
          @click="selectedHop = hop"
        >
          <circle
            :cx="hopIdxToX(idx)"
            :cy="freqToY(hop.active_carrier_hz)"
            :r="selectedHop?.hop_idx === hop.hop_idx ? 8 : 6"
            :fill="hop.target_active ? '#3fb950' : '#f0883e'"
            stroke="#0d1117"
            stroke-width="2"
          />
          <text
            :x="hopIdxToX(idx)"
            :y="freqToY(hop.active_carrier_hz) - 10"
            fill="#e6edf3"
            font-size="9.5"
            font-weight="bold"
            text-anchor="middle"
            font-family="monospace"
          >
            {{ hop.active_carrier_khz }}k
          </text>
          <text
            :x="hopIdxToX(idx)"
            y="186"
            fill="#8b949e"
            font-size="9.5"
            text-anchor="middle"
            font-family="monospace"
          >
            Hop #{{ hop.hop_idx }} ({{ hop.muscle_displacement_um }}µm)
          </text>
        </g>
      </svg>
    </div>

    <!-- HOP TELEMETRY & SOMATIC REFLECTION TABLE -->
    <div class="table-wrap">
      <table class="fhss-table mono">
        <thead>
          <tr>
            <th>Hop Order / Seed</th>
            <th>Ultrasonic Channel</th>
            <th>Phase Continuity (Start → End)</th>
            <th>In-Phase (I) vs. Quadrature (I/Q) RMS</th>
            <th>Muscle Δd &amp; Micro-Doppler</th>
            <th>Anti-Intercept OOB Guard</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(hop, idx) in hopTelemetry"
            :key="'row-' + idx"
            :class="{ 'row-active': idx === hopTelemetry.length - 1 }"
          >
            <td>
              <strong style="color: #79c0ff">Hop #{{ hop.hop_idx }}</strong>
              <span class="seed-chip" style="margin-left: 6px">Step {{ hop.hop_sequence_order || idx + 1 }}</span>
            </td>
            <td>
              <strong style="color: #7ee787; font-size: 0.85rem">{{ hop.active_carrier_khz?.toFixed(1) }} kHz</strong>
              <span style="color: #8b949e; font-size: 0.69rem; margin-left: 6px">
                (λ={{ (343 / (hop.active_carrier_khz || 20.5)).toFixed(2) }} mm)
              </span>
            </td>
            <td>
              <code>{{ hop.phase_start_rad?.toFixed(3) }} rad → {{ hop.phase_end_rad?.toFixed(3) }} rad</code>
              <div style="color: #3fb950; font-size: 0.66rem">✓ Modulo-2π Continuous (No Click)</div>
            </td>
            <td>
              <div>
                I: <strong>{{ hop.reflection_energy?.toFixed(4) }}</strong> ·
                I/Q: <strong style="color: #7ee787">{{ hop.quadrature_iq_energy?.toFixed(4) }}</strong>
              </div>
              <div style="color: #8b949e; font-size: 0.66rem">
                {{ hop.target_active ? '✓ >0.008 Muscle Reflection Gate Active' : 'Idle Floor' }}
              </div>
            </td>
            <td>
              <strong style="color: #d2a8ff">{{ hop.muscle_displacement_um }} µm</strong>
              <span style="color: #8b949e"> · {{ hop.micro_doppler_mms }} mm/s</span>
            </td>
            <td>
              <span class="guard-badge">
                🛡️ +{{ hop.intercept_guard_db }} dB ({{ hop.security_verdict || 'ANTI_INTERCEPT_LOCKED' }})
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'

const props = defineProps({
  data: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['updated'])

const localStatus = ref({})
const hopBusy = ref(false)
const ollamaBusy = ref(false)
const ollamaAdvice = ref(null)
const bannerMsg = ref('')
const selectedHop = ref(null)
const activeAudioUrl = ref('')
const hopIntervalInput = ref(2.0)
const lcgMultiplierInput = ref(3)
const lpfCutoffInput = ref(50.0)

const statusData = computed(() => {
  return Object.keys(localStatus.value).length ? localStatus.value : props.data || {}
})

const kpis = computed(() => statusData.value.kpis || {})
const hopTelemetry = computed(() => statusData.value.hop_telemetry || [])

watch(
  () => statusData.value,
  (st) => {
    if (st.hop_interval_sec !== undefined) hopIntervalInput.value = st.hop_interval_sec
    if (st.lcg_effective_stride !== undefined) lcgMultiplierInput.value = st.lcg_effective_stride
    if (st.lpf_cutoff_hz !== undefined) lpfCutoffInput.value = st.lpf_cutoff_hz
    if (!selectedHop.value && st.hop_telemetry?.length) {
      selectedHop.value = st.hop_telemetry[st.hop_telemetry.length - 1]
    }
  },
  { immediate: true }
)

function freqToY(freqHz) {
  const clamped = Math.max(19000, Math.min(22000, Number(freqHz) || 20500))
  return 155 - ((clamped - 19000) / 3000) * 125
}

function hopIdxToX(idx) {
  const n = Math.max(1, hopTelemetry.value.length - 1)
  return 125 + (idx / n) * 720
}

const hopPolylinePoints = computed(() => {
  if (!hopTelemetry.value.length) return ''
  return hopTelemetry.value
    .map((h, idx) => `${hopIdxToX(idx)},${freqToY(h.active_carrier_hz)}`)
    .join(' ')
})

function flash(msg) {
  bannerMsg.value = msg
  setTimeout(() => {
    if (bannerMsg.value === msg) bannerMsg.value = ''
  }, 6000)
}

async function fetchSonarStatus() {
  try {
    const res = await fetch('/api/fhss-sonar/status')
    if (res.ok) {
      localStatus.value = await res.json()
    }
  } catch (e) {
    console.error('FHSS sonar status error:', e)
  }
}

async function triggerSingleHop() {
  hopBusy.value = true
  try {
    const res = await fetch('/api/fhss-sonar/hop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: 'single' }),
    })
    if (res.ok) {
      localStatus.value = await res.json()
      flash(
        `[FHSS SECURE TRIGGER] Hopped to ${localStatus.value.active_carrier_khz} kHz · Phase=${localStatus.value.phase_accumulator_rad} rad · Muscle Δd=${localStatus.value.kpis?.mean_muscle_displacement_um} µm!`
      )
      emit('updated')
    }
  } catch (e) {
    console.error(e)
  } finally {
    hopBusy.value = false
  }
}

async function triggerFullCycle() {
  hopBusy.value = true
  try {
    const res = await fetch('/api/fhss-sonar/hop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: 'cycle', num_hops: 7 }),
    })
    if (res.ok) {
      localStatus.value = await res.json()
      flash('Completed 7-Channel 19.0–22.0 kHz Phase-Continuous FHSS Ultrasonic Sweep!')
      emit('updated')
    }
  } catch (e) {
    console.error(e)
  } finally {
    hopBusy.value = false
  }
}

async function applyConfigOnly() {
  try {
    const res = await fetch('/api/fhss-sonar/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        hop_interval_sec: Number(hopIntervalInput.value || 2.0),
        lcg_multiplier: Number(lcgMultiplierInput.value || 3),
        lpf_cutoff_hz: Number(lpfCutoffInput.value || 50.0),
        resweep: true,
      }),
    })
    if (res.ok) {
      localStatus.value = await res.json()
      flash(
        `Updated FrequencyHoppingSonarBridge (Hop=${hopIntervalInput.value}s · LCG=${lcgMultiplierInput.value} · LPF=${lpfCutoffInput.value} Hz)`
      )
      emit('updated')
    }
  } catch (e) {
    console.error(e)
  }
}

function auditionHopStreamWav() {
  activeAudioUrl.value = `/api/fhss-sonar/audio/hop_stream.wav?t=${Date.now()}`
  flash('Auditioning 48 kHz Stereo FHSS Hop Sequence (L: 19–22 kHz + Heterodyne Monitor · R: <50 Hz I/Q Muscle Reflection)!')
}

async function consultOllamaModal(force = false) {
  ollamaBusy.value = true
  try {
    const res = await fetch('/api/ollama/fhss-sonar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force }),
    })
    if (res.ok) {
      ollamaAdvice.value = await res.json()
      if (force) {
        flash('NightSweep Ollama Modal analyzed 19.0–22.0 kHz FHSS Ultrasonic Sonar & Quadrature I/Q telemetry!')
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
    const res = await fetch('/api/fhss-sonar/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...rc, resweep: true }),
    })
    if (res.ok) {
      localStatus.value = await res.json()
      flash('Applied NightSweep Ollama Modal FHSS Sonar Configuration!')
      emit('updated')
    }
  } catch (e) {
    console.error(e)
  }
}

onMounted(async () => {
  await fetchSonarStatus()
  consultOllamaModal(false)
})
</script>

<style scoped>
.fhss-ext-card {
  border: 1px solid rgba(56, 189, 248, 0.4);
  background: linear-gradient(180deg, rgba(16, 26, 38, 0.98) 0%, rgba(11, 16, 24, 0.98) 100%);
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.fhss-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 14px;
  flex-wrap: wrap;
}
.fhss-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.fhss-title {
  margin: 0;
  font-size: 1.01rem;
  color: #f0f6fc;
}
.carrier-pill {
  color: #38bdf8;
  border-color: rgba(56, 189, 248, 0.45);
  background: rgba(56, 189, 248, 0.12);
}
.iq-pill {
  color: #7ee787;
  border-color: rgba(63, 185, 80, 0.45);
  background: rgba(46, 160, 67, 0.12);
}
.guard-pill {
  color: #d2a8ff;
  border-color: rgba(163, 113, 247, 0.45);
  background: rgba(163, 113, 247, 0.12);
}
.fhss-sub {
  margin-top: 6px;
  font-size: 0.78rem;
  color: #8b949e;
  line-height: 1.45;
}
.fhss-hdr-actions {
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
  width: 60px;
}
.btn-hop {
  background: rgba(56, 189, 248, 0.16);
  border: 1px solid rgba(56, 189, 248, 0.5);
  color: #38bdf8;
  font-size: 0.74rem;
}
.btn-cycle {
  background: rgba(63, 185, 80, 0.16);
  border: 1px solid rgba(63, 185, 80, 0.5);
  color: #7ee787;
  font-size: 0.74rem;
}
.btn-wav {
  background: rgba(163, 113, 247, 0.16);
  border: 1px solid rgba(163, 113, 247, 0.5);
  color: #d2a8ff;
  font-size: 0.74rem;
}
.btn-ollama {
  background: linear-gradient(135deg, #0284c7, #6e40c9);
  border: none;
  color: #fff;
  font-size: 0.74rem;
}
.fhss-banner {
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
.fhss-audio-bar {
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
.fhss-wav-player {
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
.spec-svg {
  width: 100%;
  height: 185px;
  display: block;
}
.hop-node {
  cursor: pointer;
}
.table-wrap {
  max-height: 280px;
  overflow-y: auto;
  border: 1px solid #1f2937;
  border-radius: 8px;
}
.fhss-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.74rem;
}
.fhss-table th,
.fhss-table td {
  padding: 7px 10px;
  text-align: left;
  border-bottom: 1px solid #1b2432;
}
.fhss-table th {
  background: #101722;
  color: #8b949e;
  position: sticky;
  top: 0;
}
.row-active {
  background: rgba(56, 189, 248, 0.08);
}
.seed-chip {
  background: #161f2e;
  border: 1px solid #2b3c56;
  color: #9ecbff;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 0.67rem;
}
.guard-badge {
  color: #d2a8ff;
  font-size: 0.7rem;
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
</style>
