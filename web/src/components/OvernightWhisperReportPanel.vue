<template>
  <section class="panel overnight-whisper-panel">
    <div class="panel-header">
      <div>
        <h2>🤫 Gesture + Subvocalization Low-Ambient Whisper Decode &amp; Overnight Intelligence</h2>
        <p class="subtitle">
          Co-gates <strong>Mouth Gestures</strong> (800–4000 Hz viseme openness) +
          <strong>Subtle Subvocalizations</strong> (&ge;2.2 &micro;m RTL-SDR larynx tension &amp; 4-sensor F1/F2)
          to unlock <strong>1.18&times; (+1.4 dB)</strong> ultra-low ambient live word decoding &bull; +8.5 dB formant lift
        </p>
      </div>
      <div class="header-controls mono">
        <span class="badge" :class="gestureDecode.low_ambient_cued ? 'badge-active' : 'badge-ready'">
          {{ gestureDecode.low_ambient_cued ? '🟢 LOW-AMBIENT WHISPER GATE OPEN' : '⚡ CO-GATE ARMED (' + (gestureDecode.low_ambient_whisper_mult || 1.18) + '× FLOOR)' }}
        </span>
        <button class="btn-mini" @click="$emit('apply-sensitivity', { low_ambient_whisper_mult: 1.12, gesture_cue_threshold: 0.36 })">
          Ultra-Quiet Night Mode (1.12&times;)
        </button>
        <button class="btn-mini" @click="$emit('apply-sensitivity', { low_ambient_whisper_mult: 1.18, gesture_cue_threshold: 0.42 })">
          Balanced Co-Gate (1.18&times;)
        </button>
      </div>
    </div>

    <!-- LIVE CO-GATE TELEMETRY STRIP + OVERNIGHT KPI CARDS -->
    <div class="kpi-row">
      <div class="kpi-box highlight-box">
        <div class="kpi-label">LIVE GESTURE + SUBVOC CUE</div>
        <div class="kpi-val mono" :style="{ color: cueScorePct >= 42 ? '#3fb950' : '#58a6ff' }">
          {{ cueScorePct }}%
        </div>
        <div class="meter-track">
          <div class="meter-fill" :style="{ width: Math.min(100, cueScorePct) + '%' }"></div>
          <div class="meter-thresh" :style="{ left: Math.round((gestureDecode.gesture_cue_threshold || 0.42) * 100) + '%' }"></div>
        </div>
        <div class="kpi-sub mono">
          Mouth: {{ mouth.viseme || 'REST_CLOSED' }} ({{ Math.round((mouth.mouth_openness || 0) * 100) }}%) &bull;
          SNR: {{ gestureDecode.ambient_snr_db ?? 0 }} dB
        </div>
      </div>

      <div class="kpi-box">
        <div class="kpi-label">OVERNIGHT WHISPERS</div>
        <div class="kpi-val mono" style="color: #d2a8ff">
          {{ report.kpis?.whisper_utterances ?? 0 }}
          <span class="kpi-unit">/ {{ report.kpis?.total_utterances ?? 0 }} utts</span>
        </div>
        <div class="kpi-sub mono">
          {{ report.kpis?.whisper_share_pct ?? 0 }}% whisper share &bull; {{ report.kpis?.strict_unvoiced_utterances ?? 0 }} strict unvoiced
        </div>
      </div>

      <div class="kpi-box">
        <div class="kpi-label">WHISPERED WORDS OVERNIGHT</div>
        <div class="kpi-val mono" style="color: #79c0ff">
          {{ report.kpis?.whisper_words ?? 0 }}
        </div>
        <div class="kpi-sub mono">
          Subtlest throat motion: <strong>{{ report.kpis?.min_throat_disp_um ?? 5.0 }} &micro;m</strong>
        </div>
      </div>

      <div class="kpi-box">
        <div class="kpi-label">LOW-AMBIENT CONDITIONER</div>
        <div class="kpi-val mono" style="color: #3fb950">
          +8.5 dB
          <span class="kpi-unit">0.85–6.2 kHz</span>
        </div>
        <div class="kpi-sub mono">
          115 Hz hum cut &bull; {{ gestureDecode.low_ambient_whispers_decoded ?? 0 }} live boost decodes
        </div>
      </div>
    </div>

    <div class="three-col">
      <!-- COL 1: MOST WHISPERED WORDS & REPEATED WHISPER PHRASES OVERNIGHT -->
      <div class="sub-card">
        <h3>🏆 Most Whispered Words &amp; Phrases Overnight</h3>
        <div class="word-cloud">
          <span
            v-for="(item, idx) in (report.top_whisper_words || []).slice(0, 18)"
            :key="item.word"
            class="whisper-chip mono"
            :class="{ top3: idx < 3 }"
          >
            {{ item.word }} <strong>{{ item.count }}</strong>
          </span>
        </div>

        <h4 class="sub-heading">Top Repeated Whispered Phrases</h4>
        <div class="phrase-list">
          <div
            v-for="ph in (report.top_whisper_phrases || []).slice(0, 8)"
            :key="ph.phrase"
            class="phrase-row mono"
          >
            <span class="phrase-count">{{ ph.count }}&times;</span>
            <span class="phrase-txt">"{{ ph.phrase }}"</span>
          </div>
        </div>
      </div>

      <!-- COL 2: HOURLY OVERNIGHT WHISPER CADENCE + PER-SPEAKER BREAKDOWN -->
      <div class="sub-card">
        <h3>🌙 Hourly Overnight Whisper Cadence</h3>
        <div class="hourly-bars">
          <div
            v-for="h in report.hourly_cadence || []"
            :key="h.hour_key"
            class="hour-row mono"
          >
            <span class="hr-lbl">{{ h.label }}</span>
            <div class="hr-bar-bg">
              <div
                class="hr-bar-whisper"
                :style="{ width: barPct(h.whisper_words) + '%' }"
                :title="`Whisper words: ${h.whisper_words}`"
              ></div>
            </div>
            <span class="hr-num">{{ h.whisper_utts }}u / {{ h.whisper_words }}w</span>
          </div>
        </div>

        <h4 class="sub-heading">Per-Speaker Overnight Whispers (Click Person to Share Earworm)</h4>
        <div class="spk-mini-list">
          <button
            v-for="s in report.speakers || []"
            :key="s.speaker_id"
            type="button"
            class="spk-mini-row clickable-spk mono"
            @click="$emit('select-speaker', s.speaker_id)"
          >
            <strong :style="{ color: s.color }">🎧 {{ s.speaker_id }}</strong>
            <span>{{ s.whisper_utts }} utts ({{ s.whisper_words }}w)</span>
            <span>min {{ s.min_disp_um }}&micro;m ↗</span>
          </button>
        </div>
      </div>

      <!-- COL 3: SUBTLEST MICRO-DISPLACEMENT & HIGH-INFO OVERNIGHT WHISPERS -->
      <div class="sub-card">
        <div class="tab-head">
          <h3>🔬 Overnight Whisper Captures</h3>
          <div class="mini-tabs">
            <button :class="{ active: mode === 'subtle' }" @click="mode = 'subtle'">Subtlest (&micro;m)</button>
            <button :class="{ active: mode === 'sentences' }" @click="mode = 'sentences'">Full Sentences</button>
          </div>
        </div>

        <div class="utterance-feed">
          <div
            v-for="(u, idx) in displayedWhispers"
            :key="idx"
            class="utt-item"
          >
            <div class="utt-meta mono">
              <strong
                class="spk-inline-btn"
                :style="{ color: u.color }"
                title="Click to inspect & share this speaker's earworm"
                @click="$emit('select-speaker', u.speaker_id)"
              >
                🎧 {{ u.speaker_id }}
              </strong>
              <span>{{ u.time_local }}</span>
              <span class="disp-pill">{{ u.throat_disp_um }} &micro;m</span>
              <span>{{ u.viseme }}</span>
              <span>{{ u.range_m }}m</span>
            </div>
            <div class="utt-text">"{{ u.transcript }}"</div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  report: { type: Object, default: () => ({}) },
  gestureDecode: { type: Object, default: () => ({}) },
  mouth: { type: Object, default: () => ({}) },
})

defineEmits(['apply-sensitivity', 'select-speaker'])

const mode = ref('sentences')

const cueScorePct = computed(() =>
  Math.round(Number(props.gestureDecode?.gesture_subvoc_score || 0) * 100)
)

const maxHourWords = computed(() => {
  const arr = props.report?.hourly_cadence || []
  return Math.max(20, ...arr.map((h) => Number(h.whisper_words || 0)))
})

function barPct(words) {
  return Math.min(100, Math.round((Number(words || 0) / maxHourWords.value) * 100))
}

const displayedWhispers = computed(() => {
  if (mode.value === 'subtle') {
    return (props.report?.subtlest_whispers || []).slice(0, 8)
  }
  return (props.report?.high_info_whispers || []).slice(0, 8)
})
</script>

<style scoped>
.overnight-whisper-panel {
  background: linear-gradient(180deg, rgba(19, 25, 37, 0.96), rgba(13, 17, 25, 0.96));
  border: 1px solid rgba(210, 168, 255, 0.28);
  border-radius: 12px;
  padding: 16px 18px;
}
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.panel-header h2 {
  font-size: 1.02rem;
  color: #e6edf3;
  margin: 0 0 4px;
}
.subtitle {
  font-size: 0.78rem;
  color: #8b949e;
  margin: 0;
}
.header-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.badge {
  padding: 5px 10px;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 700;
}
.badge-ready {
  background: rgba(88, 166, 255, 0.14);
  border: 1px solid rgba(88, 166, 255, 0.4);
  color: #79c0ff;
}
.badge-active {
  background: rgba(63, 185, 80, 0.18);
  border: 1px solid rgba(63, 185, 80, 0.55);
  color: #3fb950;
}
.btn-mini {
  background: rgba(210, 168, 255, 0.12);
  border: 1px solid rgba(210, 168, 255, 0.35);
  color: #e2c5ff;
  border-radius: 7px;
  padding: 5px 10px;
  font-size: 0.72rem;
  cursor: pointer;
}
.btn-mini:hover {
  background: rgba(210, 168, 255, 0.24);
}
.kpi-row {
  display: grid;
  grid-template-columns: 1.3fr 1fr 1fr 1fr;
  gap: 12px;
  margin-bottom: 14px;
}
.kpi-box {
  background: rgba(10, 14, 21, 0.72);
  border: 1px solid rgba(48, 54, 61, 0.8);
  border-radius: 10px;
  padding: 10px 12px;
}
.highlight-box {
  border-color: rgba(88, 166, 255, 0.4);
}
.kpi-label {
  font-size: 0.68rem;
  font-weight: 700;
  color: #8b949e;
  letter-spacing: 0.04em;
}
.kpi-val {
  font-size: 1.32rem;
  font-weight: 800;
  margin: 3px 0;
}
.kpi-unit {
  font-size: 0.74rem;
  font-weight: 500;
  color: #8b949e;
}
.kpi-sub {
  font-size: 0.7rem;
  color: #8b949e;
}
.meter-track {
  position: relative;
  height: 7px;
  background: #161b22;
  border-radius: 4px;
  overflow: hidden;
  margin: 5px 0;
}
.meter-fill {
  height: 100%;
  background: linear-gradient(90deg, #58a6ff, #d2a8ff, #3fb950);
  transition: width 0.25s ease;
}
.meter-thresh {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 2px;
  background: #f0883e;
}
.three-col {
  display: grid;
  grid-template-columns: 1.05fr 0.95fr 1.2fr;
  gap: 12px;
}
.sub-card {
  background: rgba(11, 15, 23, 0.78);
  border: 1px solid rgba(48, 54, 61, 0.75);
  border-radius: 10px;
  padding: 12px;
}
.sub-card h3 {
  font-size: 0.84rem;
  color: #e6edf3;
  margin: 0 0 9px;
}
.sub-heading {
  font-size: 0.75rem;
  color: #8b949e;
  margin: 11px 0 6px;
}
.word-cloud {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.whisper-chip {
  background: rgba(88, 166, 255, 0.1);
  border: 1px solid rgba(88, 166, 255, 0.28);
  border-radius: 6px;
  padding: 3px 7px;
  font-size: 0.72rem;
  color: #c9d1d9;
}
.whisper-chip.top3 {
  background: rgba(210, 168, 255, 0.18);
  border-color: rgba(210, 168, 255, 0.5);
  color: #f0d8ff;
}
.whisper-chip strong {
  color: #79c0ff;
}
.phrase-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.phrase-row {
  display: flex;
  gap: 8px;
  font-size: 0.73rem;
  padding: 3px 6px;
  background: rgba(22, 27, 34, 0.65);
  border-radius: 5px;
}
.phrase-count {
  color: #d2a8ff;
  font-weight: 700;
  min-width: 28px;
}
.phrase-txt {
  color: #e6edf3;
}
.hourly-bars {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.hour-row {
  display: grid;
  grid-template-columns: 48px 1fr 82px;
  align-items: center;
  gap: 7px;
  font-size: 0.7rem;
}
.hr-lbl {
  color: #8b949e;
}
.hr-bar-bg {
  height: 8px;
  background: #161b22;
  border-radius: 4px;
  overflow: hidden;
}
.hr-bar-whisper {
  height: 100%;
  background: linear-gradient(90deg, #8957e5, #d2a8ff);
  border-radius: 4px;
}
.hr-num {
  text-align: right;
  color: #c9d1d9;
}
.spk-mini-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.spk-mini-row {
  display: flex;
  justify-content: space-between;
  width: 100%;
  border: 1px solid transparent;
  font-size: 0.72rem;
  padding: 5px 8px;
  background: rgba(22, 27, 34, 0.65);
  border-radius: 5px;
  color: #c9d1d9;
}
.clickable-spk {
  cursor: pointer;
  transition: border-color 0.15s ease;
}
.clickable-spk:hover {
  border-color: #d2a8ff;
  background: rgba(210, 168, 255, 0.12);
}
.spk-inline-btn {
  cursor: pointer;
  text-decoration: underline;
  text-decoration-style: dotted;
}
.tab-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.tab-head h3 {
  margin: 0;
}
.mini-tabs {
  display: flex;
  gap: 4px;
}
.mini-tabs button {
  background: #161b22;
  border: 1px solid #30363d;
  color: #8b949e;
  border-radius: 5px;
  padding: 2px 7px;
  font-size: 0.68rem;
  cursor: pointer;
}
.mini-tabs button.active {
  background: rgba(88, 166, 255, 0.2);
  border-color: #58a6ff;
  color: #e6edf3;
}
.utterance-feed {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 270px;
  overflow-y: auto;
}
.utt-item {
  background: rgba(22, 27, 34, 0.72);
  border-left: 3px solid #d2a8ff;
  border-radius: 6px;
  padding: 6px 9px;
}
.utt-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 0.68rem;
  color: #8b949e;
  margin-bottom: 2px;
}
.disp-pill {
  color: #7ee787;
}
.utt-text {
  font-size: 0.77rem;
  color: #e6edf3;
}
@media (max-width: 1200px) {
  .kpi-row,
  .three-col {
    grid-template-columns: 1fr;
  }
}
</style>
