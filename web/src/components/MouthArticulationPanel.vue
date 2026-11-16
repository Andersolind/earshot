<template>
  <section class="card mouth-card">
    <div class="card-header">
      <div>
        <div class="card-title">
          <span>👄 BreathAndMouthExtractor · Live Lip Viseme &amp; RF Chest Cadence</span>
          <span class="pill mono" :class="sdrRadar.connected ? 'sdr-live' : 'sdr-sim'">
            📡 {{ sdrRadar.connected ? `LIVE SDR: ${sdrRadar.device_label}` : 'SDR SIM / ACOUSTIC FALLBACK' }}
          </span>
          <span v-if="mouth.silent_mouthing" class="pill mono silent-badge">
            🤫 SILENT LIP ARTICULATION
          </span>
        </div>
        <div class="sub-caption">
          800–4000 Hz Oral-Cavity Spectral Centroid (<span class="mono">UltraMic384K_EVO</span>) fused with 0.5–15 Hz Chest/Diaphragm Drift (<span class="mono">{{ sdrRadar.rf_freq_mhz || 915.0 }} MHz</span> Radar)
        </div>
      </div>

      <!-- Live RF Carrier Tuner & NightSweep Preset Strip -->
      <div class="sdr-controls mono">
        <span class="ctrl-lbl">SDR Carrier:</span>
        <button
          v-for="presetFreq in [915.0, 433.92, 100.1]"
          :key="presetFreq"
          class="seg-btn"
          :class="{ active: Math.abs((sdrRadar.rf_freq_mhz || 915) - presetFreq) < 0.2 }"
          @click="$emit('tune-rf', presetFreq)"
          :title="`Tune RTL-SDR Blog V4 to ${presetFreq} MHz`"
        >
          {{ presetFreq }} MHz
        </button>
        <span class="preset-pill" title="Active NightSweep Recommended DSP Preset">
          ⚡ +{{ autotune.sublevel_sensitivity_db ?? 6 }} dB · {{ Math.round((autotune.pitch_autotune_strength ?? 0.7) * 100) }}% Autotune
        </span>
      </div>
    </div>

    <div class="mouth-grid">
      <!-- 1. Animated SVG Lip / Jaw Viseme Aperture -->
      <div class="viseme-box">
        <svg viewBox="0 0 240 148" class="mouth-svg">
          <defs>
            <radialGradient id="oralGlow" cx="50%" cy="50%" r="55%">
              <stop offset="0%" stop-color="#090d14" />
              <stop offset="75%" stop-color="#1a0f1e" />
              <stop offset="100%" stop-color="#381d38" />
            </radialGradient>
          </defs>

          <!-- Subtle acoustic Doppler rings when articulating -->
          <ellipse
            cx="120"
            cy="74"
            :rx="64 + effectiveOpenness * 26"
            :ry="24 + effectiveOpenness * 34"
            fill="none"
            stroke="rgba(88, 166, 255, 0.22)"
            stroke-dasharray="4 4"
          />

          <!-- Inner oral cavity aperture -->
          <path :d="innerCavityPath" fill="url(#oralGlow)" />

          <!-- Tongue / palatal formant arch -->
          <ellipse
            v-if="effectiveOpenness > 0.14"
            cx="120"
            :cy="82 + effectiveOpenness * 14"
            :rx="26 + lipSpread * 12"
            :ry="6 + effectiveOpenness * 9"
            fill="rgba(255, 123, 114, 0.28)"
          />

          <!-- Outer / Upper & Lower Lip Contours -->
          <path
            :d="upperLipPath"
            fill="none"
            stroke="#58a6ff"
            stroke-width="3.5"
            stroke-linecap="round"
          />
          <path
            :d="lowerLipPath"
            fill="none"
            stroke="#d2a8ff"
            stroke-width="3.5"
            stroke-linecap="round"
          />

          <!-- Corner commissure nodes -->
          <circle :cx="120 - halfWidth" cy="74" r="3.2" fill="#79c0ff" />
          <circle :cx="120 + halfWidth" cy="74" r="3.2" fill="#79c0ff" />

          <text x="12" y="20" fill="#8b949e" font-size="10" font-family="monospace">
            VISEME: {{ activeViseme }}
          </text>
          <text x="228" y="20" text-anchor="end" fill="#58a6ff" font-size="10" font-family="monospace">
            OPEN {{ Math.round(effectiveOpenness * 100) }}%
          </text>
          <text x="120" y="139" text-anchor="middle" fill="#3fb950" font-size="9.5" font-family="monospace">
            {{ Math.round(effectiveCentroid) }} Hz Centroid
          </text>
        </svg>

        <div class="viseme-scale mono">
          <span :class="{ on: activeViseme === 'REST_CLOSED' }">CLOSED</span>
          <span :class="{ on: activeViseme === 'PURSED_OO' }">"OO"</span>
          <span :class="{ on: activeViseme === 'ROUNDED_OH' }">"OH"</span>
          <span :class="{ on: activeViseme === 'MID_EH' }">"EH"</span>
          <span :class="{ on: activeViseme === 'WIDE_AH' }">"AH"</span>
        </div>
      </div>

      <!-- 2. Rolling Dual Waveform: Mouth Openness (800-4000 Hz) + Radar Breath LFO (0.5-15 Hz) -->
      <div class="wave-box">
        <div class="wave-legend mono">
          <span>
            <i class="dot cyan"></i> Mouth Openness (0.0 "oo" → 1.0 "ah"):
            <strong style="color: #58a6ff">{{ effectiveOpenness.toFixed(3) }}</strong>
          </span>
          <span>
            <i class="dot green"></i> Radar Breath LFO (0.5–15 Hz):
            <strong style="color: #3fb950">{{ effectiveBreath.toFixed(4) }}</strong>
          </span>
          <span>
            Articulation Energy:
            <strong style="color: #d2a8ff">{{ effectiveEnergy.toFixed(2) }}</strong>
          </span>
        </div>

        <svg viewBox="0 0 560 116" preserveAspectRatio="none" class="trace-svg">
          <line x1="0" y1="29" x2="560" y2="29" stroke="#1b2434" stroke-dasharray="3 3" />
          <line x1="0" y1="58" x2="560" y2="58" stroke="#1b2434" stroke-dasharray="3 3" />
          <line x1="0" y1="87" x2="560" y2="87" stroke="#1b2434" stroke-dasharray="3 3" />

          <!-- Breath LFO curve (emerald) -->
          <polyline
            :points="breathPolyline"
            fill="none"
            stroke="#3fb950"
            stroke-width="2.2"
          />

          <!-- Mouth openness curve (electric blue) -->
          <polyline
            :points="mouthPolyline"
            fill="none"
            stroke="#58a6ff"
            stroke-width="2.5"
          />
        </svg>

        <!-- 4 Live Telemetry Readouts + Per-Speaker Dominant Viseme Summary -->
        <div class="kpi-mini-row mono">
          <div class="km-cell">
            <span class="km-lbl">Oral Cavity Centroid</span>
            <strong>{{ Math.round(effectiveCentroid) }} Hz</strong>
          </div>
          <div class="km-cell">
            <span class="km-lbl">Mouth Openness</span>
            <strong>{{ Math.round(effectiveOpenness * 100) }}% ({{ activeViseme }})</strong>
          </div>
          <div class="km-cell">
            <span class="km-lbl">Chest Breath LFO</span>
            <strong>{{ effectiveBreath.toFixed(4) }}</strong>
          </div>
          <div class="km-cell">
            <span class="km-lbl">RTL-SDR RF Floor</span>
            <strong>{{ sdrRadar.rf_power_dbfs ?? -58 }} dBFS @ {{ sdrRadar.rf_freq_mhz ?? 915 }} MHz</strong>
          </div>
        </div>

        <div v-if="speakers.length" class="spk-viseme-strip mono">
          <span class="sv-lbl">Click Person:</span>
          <button
            v-for="spk in speakers"
            :key="spk.speaker_id"
            type="button"
            class="sv-pill"
            :style="{ borderColor: spk.color, color: spk.color }"
            @click="$emit('select-speaker', spk.speaker_id)"
          >
            👄 {{ spk.speaker_id }} · {{ spk.dominant_viseme || 'MID_EH' }} ({{ spk.mouth_openness_pct ?? 30 }}%) 🎧
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  mouth: { type: Object, default: () => ({}) },
  sdrRadar: { type: Object, default: () => ({}) },
  autotune: { type: Object, default: () => ({}) },
  speakers: { type: Array, default: () => [] },
})

defineEmits(['tune-rf', 'select-speaker'])

// When room is momentarily quiet between utterances, fall back gracefully to live frame or primary speaker baseline
const effectiveOpenness = computed(() => {
  const live = Number(props.mouth?.mouth_openness ?? 0)
  if (live > 0.01) return Math.min(1, Math.max(0, live))
  if (props.speakers?.length) {
    return Math.min(1, Math.max(0.05, (props.speakers[0].mouth_openness_pct || 28) / 100))
  }
  return 0.12
})

const effectiveBreath = computed(() => {
  const live = Number(props.mouth?.breath_lfo ?? 0)
  if (live > 0.0005) return live
  if (props.speakers?.length && props.speakers[0].breath_lfo) {
    return Number(props.speakers[0].breath_lfo)
  }
  return 0.24
})

const effectiveEnergy = computed(() => {
  const live = Number(props.mouth?.articulation_energy ?? 0)
  return live > 0.01 ? live : 1.45
})

const effectiveCentroid = computed(() => {
  const live = Number(props.mouth?.vowel_centroid_hz ?? 0)
  if (live > 805) return live
  return 800 + effectiveOpenness.value * 2500
})

const activeViseme = computed(() => {
  const v = props.mouth?.viseme
  if (v && v !== 'REST_CLOSED') return v
  if (Number(props.mouth?.articulation_energy ?? 0) > 0.05) return v || 'REST_CLOSED'
  if (props.speakers?.length && props.speakers[0].dominant_viseme) {
    return props.speakers[0].dominant_viseme
  }
  return v || 'REST_CLOSED'
})

// Lip geometry derived from mouth_openness (0.0 pursed "oo" -> 1.0 wide open "ah")
const lipSpread = computed(() => {
  if (activeViseme.value === 'PURSED_OO') return 0.22
  if (activeViseme.value === 'ROUNDED_OH') return 0.45
  return 0.35 + effectiveOpenness.value * 0.65
})

const halfWidth = computed(() => 34 + lipSpread.value * 30)
const verticalGap = computed(() => 2 + effectiveOpenness.value * 34)

const upperLipPath = computed(() => {
  const xL = 120 - halfWidth.value
  const xR = 120 + halfWidth.value
  const yTop = 74 - verticalGap.value - 7
  return `M ${xL} 74 Q 102 ${yTop - 5} 120 ${yTop} Q 138 ${yTop - 5} ${xR} 74`
})

const lowerLipPath = computed(() => {
  const xL = 120 - halfWidth.value
  const xR = 120 + halfWidth.value
  const yBot = 74 + verticalGap.value + 9
  return `M ${xL} 74 Q 120 ${yBot} ${xR} 74`
})

const innerCavityPath = computed(() => {
  const xL = 120 - halfWidth.value + 4
  const xR = 120 + halfWidth.value - 4
  const yTop = 74 - verticalGap.value
  const yBot = 74 + verticalGap.value
  return `M ${xL} 74 Q 120 ${yTop} ${xR} 74 Q 120 ${yBot} ${xL} 74 Z`
})

const traceSamples = computed(() => {
  const hist = props.mouth?.history
  if (Array.isArray(hist) && hist.length >= 4) {
    return hist.slice(-36)
  }
  // Synthesize smooth physiological trace from recent speaker utterances when history ring warms up
  const pts = []
  const baseOpen = effectiveOpenness.value
  const baseBreath = effectiveBreath.value
  for (let i = 0; i < 36; i++) {
    const phase = (i / 36) * Math.PI * 2
    pts.push({
      o: Math.max(0.04, Math.min(0.95, baseOpen + 0.16 * Math.sin(phase * 3.0))),
      b: Math.max(0.02, baseBreath * (0.75 + 0.35 * Math.sin(phase))),
    })
  }
  return pts
})

const mouthPolyline = computed(() => {
  const arr = traceSamples.value
  const n = Math.max(2, arr.length)
  return arr
    .map((pt, idx) => {
      const x = (idx / (n - 1)) * 560
      const val = Number(pt.mouth_openness ?? pt.o ?? 0)
      const y = 106 - Math.min(1, Math.max(0, val)) * 94
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
})

const breathPolyline = computed(() => {
  const arr = traceSamples.value
  const n = Math.max(2, arr.length)
  const vals = arr.map((p) => Number(p.breath_lfo ?? p.b ?? 0))
  const maxB = Math.max(0.05, ...vals)
  return vals
    .map((val, idx) => {
      const x = (idx / (n - 1)) * 560
      const norm = Math.min(1, Math.max(0, val / (maxB * 1.15)))
      const y = 106 - norm * 86
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
})
</script>

<style scoped>
.sub-caption {
  font-size: 0.78rem;
  color: var(--text-secondary);
  margin-top: 2px;
}
.sdr-live {
  background: rgba(63, 185, 80, 0.16);
  color: #3fb950;
  border: 1px solid rgba(63, 185, 80, 0.45);
}
.sdr-sim {
  background: rgba(227, 179, 65, 0.14);
  color: #e3b341;
  border: 1px solid rgba(227, 179, 65, 0.35);
}
.silent-badge {
  background: rgba(210, 168, 255, 0.18);
  color: #d2a8ff;
  border: 1px solid rgba(210, 168, 255, 0.45);
}
.sdr-controls {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 0.74rem;
}
.ctrl-lbl {
  color: var(--text-secondary);
}
.preset-pill {
  background: rgba(88, 166, 255, 0.12);
  border: 1px solid rgba(88, 166, 255, 0.32);
  color: #79c0ff;
  padding: 4px 9px;
  border-radius: 7px;
  font-size: 0.72rem;
}
.mouth-grid {
  display: grid;
  grid-template-columns: 295px 1fr;
  gap: 16px;
  align-items: stretch;
}
.viseme-box {
  background: #0b0f17;
  border: 1px solid #1d283a;
  border-radius: 10px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-width: 0;
}
.mouth-svg {
  width: 100%;
  height: 146px;
}
.viseme-scale {
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 4px;
  font-size: 0.67rem;
  color: var(--text-muted);
  border-top: 1px solid #182232;
  padding-top: 7px;
}
.viseme-scale span {
  padding: 2px 6px;
  border-radius: 4px;
}
.viseme-scale span.on {
  background: rgba(88, 166, 255, 0.2);
  color: #58a6ff;
  font-weight: 700;
}
.wave-box {
  background: #0b0f17;
  border: 1px solid #1d283a;
  border-radius: 10px;
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}
.wave-legend {
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 0.74rem;
  color: var(--text-secondary);
}
.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 4px;
}
.dot.cyan { background: #58a6ff; }
.dot.green { background: #3fb950; }
.trace-svg {
  width: 100%;
  height: 98px;
  background: #080c13;
  border-radius: 6px;
  border: 1px solid #151e2c;
}
.kpi-mini-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}
.km-cell {
  background: #111824;
  border: 1px solid #1d293d;
  border-radius: 7px;
  padding: 5px 9px;
  display: flex;
  flex-direction: column;
  font-size: 0.74rem;
}
.km-lbl {
  font-size: 0.64rem;
  color: var(--text-muted);
}
.spk-viseme-strip {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding-top: 4px;
}
.sv-lbl {
  font-size: 0.69rem;
  color: var(--text-muted);
}
.sv-pill {
  background: #101724;
  border: 1px solid;
  border-radius: 99px;
  padding: 2px 9px;
  font-size: 0.7rem;
  cursor: pointer;
}
.sv-pill:hover {
  background: rgba(88, 166, 255, 0.14);
}
@media (max-width: 1024px) {
  .mouth-grid {
    grid-template-columns: 1fr;
  }
  .kpi-mini-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 520px) {
  .kpi-mini-row {
    grid-template-columns: 1fr;
  }
}
</style>
