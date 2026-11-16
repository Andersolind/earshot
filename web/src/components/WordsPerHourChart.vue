<template>
  <section class="card">
    <div class="card-header">
      <div>
        <div class="card-title">
          <span>📊 Per-Speaker Words Per Hour (WPH) Velocity</span>
          <span class="pill mono" style="color: var(--cyan)">
            {{ kpis.sha256_verified }}/{{ kpis.sha256_total }} SHA-256 Verified
          </span>
        </div>
        <div class="sub-caption">
          Normalized hourly word rate (<span class="mono">words/hr</span>) stacked by enrolled biometric speaker identity
        </div>
      </div>

      <div class="controls-inline">
        <div class="seg-group">
          <button
            v-for="bm in [5, 15, 60]"
            :key="bm"
            class="seg-btn"
            :class="{ active: bucketMinutes === bm }"
            @click="$emit('update:bucketMinutes', bm)"
          >
            {{ bm === 60 ? '1h Hourly' : bm + 'm Velocity' }}
          </button>
        </div>

        <div class="seg-group">
          <button
            class="seg-btn"
            :class="{ active: colorMode === 'speaker' }"
            @click="colorMode = 'speaker'"
          >
            By Speaker
          </button>
          <button
            class="seg-btn"
            :class="{ active: colorMode === 'phonation' }"
            @click="colorMode = 'phonation'"
          >
            Voiced vs Whisper
          </button>
        </div>
      </div>
    </div>

    <!-- KPI Strip -->
    <div class="kpi-grid">
      <div class="kpi-box accent-blue">
        <div class="kpi-label">Session Words / Hr</div>
        <div class="kpi-val mono">{{ formatNum(kpis.session_wph) }}</div>
        <div class="kpi-sub">{{ kpis.active_duration_min }}m active window</div>
      </div>
      <div class="kpi-box accent-green">
        <div class="kpi-label">Live 15m Velocity</div>
        <div class="kpi-val mono">{{ formatNum(kpis.rolling_15m_wph) }} <small>WPH</small></div>
        <div class="kpi-sub">Active pace {{ formatNum(kpis.active_speaking_wph) }} WPH</div>
      </div>
      <div class="kpi-box">
        <div class="kpi-label">Extracted Words</div>
        <div class="kpi-val mono">{{ formatNum(kpis.total_words) }}</div>
        <div class="kpi-sub">{{ kpis.total_utterances }} biometric utterances</div>
      </div>
      <div class="kpi-box accent-purple">
        <div class="kpi-label">Sublevel Whisper Share</div>
        <div class="kpi-val mono">{{ kpis.whisper_share_pct }}%</div>
        <div class="kpi-sub">Role B unvoiced fricatives</div>
      </div>
      <div class="kpi-box accent-amber">
        <div class="kpi-label">Mean Word Confidence</div>
        <div class="kpi-val mono">{{ kpis.mean_asr_conf_pct }}%</div>
        <div class="kpi-sub">Faster-Whisper small.en</div>
      </div>
    </div>

    <!-- Interactive SVG Stacked Bar Chart -->
    <div class="chart-wrap" v-if="buckets.length">
      <svg :viewBox="`0 0 ${svgW} ${svgH}`" class="wph-svg">
        <!-- Horizontal Y gridlines -->
        <g v-for="tick in yTicks" :key="tick.val">
          <line
            :x1="padL"
            :x2="svgW - padR"
            :y1="tick.y"
            :y2="tick.y"
            stroke="#1e2736"
            stroke-dasharray="4 4"
          />
          <text :x="padL - 8" :y="tick.y + 4" text-anchor="end" class="axis-txt mono">
            {{ tick.val }}
          </text>
        </g>

        <!-- Stacked Bars -->
        <g
          v-for="(b, idx) in stackedBuckets"
          :key="b.epoch"
          class="bar-col"
          @mouseenter="hoveredIdx = idx"
          @mouseleave="hoveredIdx = -1"
        >
          <rect
            :x="b.x - 3"
            :y="padT"
            :width="b.w + 6"
            :height="plotH"
            fill="transparent"
          />
          <rect
            v-for="seg in b.segments"
            :key="seg.key"
            :x="b.x"
            :y="seg.y"
            :width="b.w"
            :height="Math.max(0, seg.h)"
            :fill="seg.color"
            rx="3"
            :opacity="hoveredIdx === -1 || hoveredIdx === idx ? 0.92 : 0.48"
            @click="colorMode === 'speaker' ? $emit('select-speaker', seg.key) : null"
          />
          <!-- Value top label on hovered or peak bar -->
          <text
            v-if="(hoveredIdx === idx || b.isPeak) && b.wph_rate > 0"
            :x="b.x + b.w / 2"
            :y="Math.max(12, b.topY - 6)"
            text-anchor="middle"
            class="bar-val mono"
          >
            {{ Math.round(b.wph_rate) }}
          </text>
          <!-- X-axis time label -->
          <text
            v-if="idx % labelStride === 0 || idx === stackedBuckets.length - 1"
            :x="b.x + b.w / 2"
            :y="svgH - 8"
            text-anchor="middle"
            class="axis-txt mono"
          >
            {{ b.label }}
          </text>
        </g>
      </svg>

      <!-- Legend + Hover Inspector -->
      <div class="legend-bar">
        <div class="legend-items" v-if="colorMode === 'speaker'">
          <button
            v-for="spk in speakers"
            :key="spk.speaker_id"
            type="button"
            class="legend-chip clickable-person"
            :title="`Click to inspect & share ${spk.speaker_id}'s earworm`"
            @click="$emit('select-speaker', spk.speaker_id)"
          >
            <span class="dot" :style="{ background: spk.color }"></span>
            <strong class="mono">{{ spk.speaker_id }}</strong>
            <span class="muted">({{ spk.wph }} WPH · {{ spk.words }}w)</span>
            <span class="earworm-icon">🎧</span>
          </button>
        </div>
        <div class="legend-items" v-else>
          <span class="legend-chip">
            <span class="dot" style="background: #58a6ff"></span>
            <strong>Voiced Larynx (Role A)</strong>
          </span>
          <span class="legend-chip">
            <span class="dot" style="background: #d2a8ff"></span>
            <strong>Sublevel Whisper (Role B)</strong>
          </span>
        </div>

        <div v-if="hoveredBucket" class="hover-readout mono">
          <span>🕒 {{ hoveredBucket.label }}</span>
          <span>⚡ <strong>{{ hoveredBucket.wph_rate }} WPH</strong> ({{ hoveredBucket.total_words }} words)</span>
          <span>🗣️ {{ hoveredBucket.voiced_words }} voiced / 🤫 {{ hoveredBucket.whisper_words }} whisper</span>
        </div>
      </div>
    </div>

    <div v-else class="empty-chart">
      Listening on live GNU Radio audio tap — speak or whisper near the microphone to populate Words/Hour bars.
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  buckets: { type: Array, default: () => [] },
  speakers: { type: Array, default: () => [] },
  kpis: { type: Object, default: () => ({}) },
  bucketMinutes: { type: Number, default: 15 },
})

defineEmits(['update:bucketMinutes', 'select-speaker'])

const colorMode = ref('speaker')
const hoveredIdx = ref(-1)

const svgW = 860
const svgH = 235
const padL = 52
const padR = 16
const padT = 22
const padB = 28
const plotW = svgW - padL - padR
const plotH = svgH - padT - padB

const speakerColorMap = computed(() => {
  const m = {}
  props.speakers.forEach((s) => {
    m[s.speaker_id] = s.color
  })
  return m
})

const maxWph = computed(() => {
  const m = Math.max(100, ...props.buckets.map((b) => b.wph_rate || 0))
  return Math.ceil(m / 100) * 100
})

const yTicks = computed(() => {
  const top = maxWph.value
  return [0, 0.25, 0.5, 0.75, 1].map((frac) => {
    const val = Math.round(top * frac)
    const y = padT + plotH * (1 - frac)
    return { val, y }
  })
})

const labelStride = computed(() => Math.max(1, Math.ceil(props.buckets.length / 9)))

const stackedBuckets = computed(() => {
  const n = props.buckets.length
  if (!n) return []
  const step = plotW / n
  const barW = Math.max(8, Math.min(44, step * 0.68))
  const scaleFactor = 60 / Math.max(1, props.bucketMinutes)
  const peakVal = Math.max(...props.buckets.map((b) => b.wph_rate || 0))

  return props.buckets.map((b, i) => {
    const x = padL + i * step + (step - barW) / 2
    let curY = padT + plotH
    const segments = []

    if (colorMode.value === 'speaker') {
      const entries = Object.entries(b.by_speaker || {})
      entries.forEach(([sid, obj]) => {
        const wph = obj.wph || 0
        const h = (wph / maxWph.value) * plotH
        curY -= h
        segments.push({
          key: sid,
          y: curY,
          h,
          color: speakerColorMap.value[sid] || '#58a6ff',
        })
      })
    } else {
      const vWph = (b.voiced_words || 0) * scaleFactor
      const wWph = (b.whisper_words || 0) * scaleFactor
      ;[
        { key: 'voiced', val: vWph, color: '#58a6ff' },
        { key: 'whisper', val: wWph, color: '#d2a8ff' },
      ].forEach((part) => {
        const h = (part.val / maxWph.value) * plotH
        curY -= h
        segments.push({ key: part.key, y: curY, h, color: part.color })
      })
    }

    return {
      ...b,
      x,
      w: barW,
      topY: curY,
      isPeak: peakVal > 0 && b.wph_rate === peakVal,
      segments,
    }
  })
})

const hoveredBucket = computed(() =>
  hoveredIdx.value >= 0 && hoveredIdx.value < props.buckets.length
    ? props.buckets[hoveredIdx.value]
    : null
)

function formatNum(n) {
  if (n === undefined || n === null) return '0'
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 })
}
</script>

<style scoped>
.sub-caption {
  font-size: 0.78rem;
  color: var(--text-secondary);
  margin-top: 2px;
}
.controls-inline {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}
.kpi-box {
  background: #0d121a;
  border: 1px solid var(--border-subtle);
  border-radius: 9px;
  padding: 10px 12px;
}
.kpi-box.accent-blue { border-left: 3px solid var(--blue); }
.kpi-box.accent-green { border-left: 3px solid var(--green); }
.kpi-box.accent-purple { border-left: 3px solid var(--purple); }
.kpi-box.accent-amber { border-left: 3px solid var(--amber); }
.kpi-label {
  font-size: 0.72rem;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.kpi-val {
  font-size: 1.35rem;
  font-weight: 700;
  margin: 3px 0 2px;
}
.kpi-val small {
  font-size: 0.75rem;
  color: var(--text-secondary);
}
.kpi-sub {
  font-size: 0.72rem;
  color: var(--text-muted);
}
.chart-wrap {
  background: #0b0f17;
  border: 1px solid #1b2434;
  border-radius: 10px;
  padding: 10px 12px 8px;
}
.wph-svg {
  width: 100%;
  height: auto;
  display: block;
}
.axis-txt {
  fill: #7d8590;
  font-size: 10.5px;
}
.bar-val {
  fill: #e6edf3;
  font-size: 10.5px;
  font-weight: 700;
}
.bar-col {
  cursor: pointer;
}
.legend-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #192231;
  font-size: 0.76rem;
}
.legend-items {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
}
.legend-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.clickable-person {
  background: #101724;
  border: 1px solid #223149;
  border-radius: 99px;
  padding: 3px 10px;
  color: inherit;
  cursor: pointer;
  transition: border-color 0.15s ease, transform 0.12s ease;
}
.clickable-person:hover {
  border-color: #58a6ff;
  transform: translateY(-1px);
}
.earworm-icon {
  font-size: 0.72rem;
}
.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
}
.muted {
  color: var(--text-secondary);
}
.hover-readout {
  display: flex;
  gap: 12px;
  color: #79c0ff;
  font-size: 0.75rem;
}
.empty-chart {
  padding: 36px;
  text-align: center;
  color: var(--text-secondary);
  font-size: 0.85rem;
}
</style>
