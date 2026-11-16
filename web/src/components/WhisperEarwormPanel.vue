<template>
  <section class="card earworm-card">
    <div class="card-header">
      <div>
        <div class="card-title">
          <span>🎧 WhisperEarwormEngine · 4-Sensor ZMQ Phoneme &amp; Markov Word Predictor</span>
          <span class="pill mono" :class="earworm.is_whispering ? 'active-whisp' : 'idle-whisp'">
            {{ earworm.is_whispering ? `🤫 WHISPERING (${earworm.active_phoneme})` : `PHONEME: ${earworm.active_phoneme || 'IDLE'}` }}
          </span>
          <span class="pill mono bpm-pill">
            🎵 Earworm Tempo: {{ earworm.earworm_bpm ?? 120 }} BPM (~{{ earworm.next_eta_ms ?? 500 }} ms)
          </span>
        </div>
        <div class="sub-caption">
          F1/F2 Whisper Formant Classifier + 2nd-Order Bigram Markov Predictor + ZeroMQ (<span class="mono">:5555 / :5556 / :5557</span>) + Stateful UDP <span class="mono">:5005</span> Vocal Mirror
        </div>
      </div>

      <div class="ew-actions">
        <button
          class="seg-btn mono"
          :class="{ active: zmq.udp_mirror_enabled !== false }"
          @click="toggleUdpMirror"
          title="Toggle Stateful Butterworth F1/F2 Formant Vocal Mirror on UDP Port 5005"
        >
          🔊 UDP :{{ zmq.mixer_port || 5005 }} {{ zmq.udp_mirror_enabled !== false ? 'ON' : 'MUTED' }} ({{ zmq.udp_sent_pkts || 0 }} pkts)
        </button>

        <button class="btn btn-primary" :disabled="loadingCfg" @click="askModelConfig(true)">
          {{ loadingCfg ? '⏳ Asking NightSweep...' : '🧠 Ask Model for Enhanced Configs' }}
        </button>
      </div>
    </div>

    <!-- 4-SENSOR ZMQ & ULTRASONIC TELEMETRY BAR -->
    <div class="zmq-strip mono">
      <span class="z-chip" :class="{ live: true }">
        🎙️ Carrier: {{ Math.round((zmq.ultrasonic_carrier_hz || 40000) / 1000) }} kHz LO
      </span>
      <span class="z-chip" :class="{ live: (zmq.rtlsdr_pkts || 0) > 0 || zmq.rtlsdr_zmq_pub_active }">
        📡 RTLSDR_ZMQ (:5556): {{ zmq.rtlsdr_zmq_pub_active ? 'LIVE PUB+SUB' : 'SUB' }} · {{ zmq.rtlsdr_pkts || 0 }} pkts
      </span>
      <span class="z-chip" :class="{ live: (zmq.pluto_pkts || 0) > 0 }">
        📡 PLUTO_ZMQ (:5555 · 2.45 GHz): {{ zmq.pluto_pkts || 0 }} pkts
      </span>
      <span class="z-chip" :class="{ live: (zmq.hackrf_pkts || 0) > 0 || zmq.hackrf_zmq_pub_active }">
        📡 HACKRF_ZMQ (:5557 · Wideband): {{ zmq.hackrf_zmq_pub_active ? 'LIVE PUB+SUB' : 'SUB' }} · {{ zmq.hackrf_pkts || zmq.hackrf_pub_pkts || 0 }} pkts
      </span>
      <span class="z-chip">
        ⚙️ Trigger {{ cfg.whisper_trigger_mult ?? 2.15 }}× · Hangover {{ cfg.silence_hangover_blocks ?? 5 }} blks · Markov-{{ cfg.markov_order ?? 2 }}
      </span>
    </div>

    <!-- MAIN 2-COLUMN VISUALIZER: F1xF2 VOWEL SPACE + EARWORM MARKOV PREDICTOR -->
    <div class="ew-grid">
      <!-- 1. 2D Acoustic F1 x F2 Whisper Vowel Formant Map -->
      <div class="formant-box">
        <div class="sec-hdr mono">
          <span>F1 × F2 Whisper Formant Map</span>
          <span style="color: #58a6ff">F1 {{ f1Hz }} Hz · F2 {{ f2Hz }} Hz</span>
        </div>

        <svg viewBox="0 0 280 164" class="vowel-svg">
          <!-- Grid & Vowel Quadrant Zones -->
          <rect x="28" y="14" width="236" height="128" rx="7" fill="#080c13" stroke="#1b2638" />
          <line x1="146" y1="14" x2="146" y2="142" stroke="#162030" stroke-dasharray="3 3" />
          <line x1="28" y1="78" x2="264" y2="78" stroke="#162030" stroke-dasharray="3 3" />

          <!-- Classical Vowel Trapezoid Reference (Front F2 left, Back F2 right; Closed F1 top, Open F1 bottom) -->
          <polygon
            points="54,32 232,36 212,126 98,128"
            fill="rgba(88, 166, 255, 0.05)"
            stroke="rgba(88, 166, 255, 0.25)"
            stroke-width="1.2"
          />

          <!-- Phoneme Anchor Labels -->
          <text x="58" y="44" fill="#79c0ff" font-size="10" font-weight="700" font-family="monospace">EE ("see")</text>
          <text x="72" y="84" fill="#a5d6ff" font-size="9.5" font-family="monospace">EH ("let")</text>
          <text x="128" y="124" fill="#ffa657" font-size="10" font-weight="700" font-family="monospace">AH ("heart")</text>
          <text x="192" y="46" fill="#d2a8ff" font-size="10" font-weight="700" font-family="monospace">OO ("move")</text>
          <text x="194" y="135" fill="#3fb950" font-size="9" font-family="monospace">S/T · SH (>3.5kHz)</text>

          <!-- Live F1/F2 Crosshair Target -->
          <circle :cx="formantDot.x" :cy="formantDot.y" r="12" fill="rgba(63, 185, 80, 0.16)" />
          <circle :cx="formantDot.x" :cy="formantDot.y" r="5.2" fill="#3fb950" stroke="#ffffff" stroke-width="1.4" />

          <!-- Axis Captions -->
          <text x="146" y="157" text-anchor="middle" fill="#8b949e" font-size="8.8" font-family="monospace">
            ← Front Tongue (F2 2800 Hz) · Back Tongue (F2 900 Hz) →
          </text>
          <text x="12" y="78" text-anchor="middle" fill="#8b949e" font-size="8.5" font-family="monospace" transform="rotate(-90 12 78)">
            F1 Jaw Open →
          </text>
        </svg>

        <div class="mirror-bar mono">
          <span>Mirror Gain: <strong>{{ (earworm.whisper_gain ?? 0).toFixed(2) }}</strong></span>
          <span>Quiet Floor: <strong>{{ (earworm.whisper_floor ?? 0.005).toFixed(4) }}</strong></span>
        </div>
      </div>

      <!-- 2. Earworm Phoneme & Lexical Sequence Forecast Cards -->
      <div class="predict-box">
        <div class="pred-cards">
          <!-- Whisper Phoneme Contour Predictor -->
          <div class="pred-card">
            <div class="pc-lbl mono">🤫 WHISPER PHONEME SEQUENCE PREDICTOR</div>
            <div class="pc-flow mono">
              <div class="pc-node">
                <span class="nd-sub">Last Whisper Contour</span>
                <strong>{{ earworm.last_detected_word || 'EE-S/T' }}</strong>
              </div>
              <span class="arrow">➔</span>
              <div class="pc-node next">
                <span class="nd-sub">Predicted Next (~{{ earworm.next_eta_ms ?? 500 }}ms)</span>
                <strong>{{ earworm.predicted_next_word || 'AH-OO' }}</strong>
              </div>
            </div>
            <div class="syll-line mono">
              Active Syllable Buffer:
              <span v-if="earworm.current_word_phonemes?.length" class="ph-chip">
                {{ earworm.current_word_phonemes.join(' - ') }}
              </span>
              <span v-else class="muted">Listening for 400–6000 Hz whisper airflow...</span>
            </div>
          </div>

          <!-- Lexical Earworm Markov Predictor -->
          <div class="pred-card">
            <div class="pc-lbl mono">🗣️ LEXICAL EARWORM NEXT-WORD FORECAST</div>
            <div class="pc-flow mono">
              <div class="pc-node">
                <span class="nd-sub">Last Spoken/Whispered Word</span>
                <strong style="color: #79c0ff">"{{ earworm.last_lexical_word || '--' }}"</strong>
              </div>
              <span class="arrow">➔</span>
              <div class="pc-node next-lex">
                <span class="nd-sub">Markov-{{ cfg.markov_order ?? 2 }} Forecast</span>
                <strong style="color: #7ee787">"{{ earworm.predicted_lexical_word || '--' }}"</strong>
              </div>
            </div>
            <div class="edges-row mono" v-if="earworm.top_lexical_transitions?.length">
              <span
                v-for="(ed, idx) in earworm.top_lexical_transitions.slice(0, 4)"
                :key="idx"
                class="edge-chip"
              >
                {{ ed.from }} → <b>{{ ed.to }}</b> (×{{ ed.count }})
              </span>
            </div>
          </div>
        </div>

        <!-- NIGHTSWEEP MODEL ENHANCED CONFIGURATION BRIEFING -->
        <div v-if="modelCfg" class="cfg-advisor">
          <div class="cfg-top">
            <div>
              <span class="cfg-badge mono">🧠 NIGHTSWEEP ENHANCED CONFIG: {{ modelCfg.config_profile_name }}</span>
              <span v-if="modelCfg.ollama_live" class="live-tag mono">Live Ollama · {{ modelCfg.latency_ms }}ms</span>
            </div>
            <button class="btn btn-green btn-sm" @click="applyEnhancedConfig">
              ✅ Apply Enhanced Config to Engine
            </button>
          </div>

          <p class="cfg-rat">{{ modelCfg.executive_rationale }}</p>

          <div class="cfg-cols">
            <div>
              <div class="mini-title">🔧 DSP &amp; Formant Upgrades</div>
              <ul>
                <li v-for="(item, i) in modelCfg.dsp_enhancements?.slice(0, 3)" :key="i">{{ item }}</li>
              </ul>
            </div>
            <div>
              <div class="mini-title">📡 Multi-SDR ZMQ &amp; Ultrasonic Tuning</div>
              <ul>
                <li v-for="(item, i) in modelCfg.sensor_and_zmq_configs?.slice(0, 3)" :key="i">{{ item }}</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- CROSS-SPEAKER SHARED EARWORMS (CONTAGION LOOPS ECHOED ACROSS PEOPLE) -->
    <div v-if="crossShared.length" class="shared-contagion-box">
      <div class="contagion-hdr">
        <div class="contagion-title mono">
          🔗 Cross-Speaker Shared Earworms (Echoed Across Multiple People · Click Any Person or Share)
        </div>
        <span class="pill mono">{{ crossShared.length }} Shared Room Hooks</span>
      </div>
      <div class="contagion-grid">
        <div v-for="(ce, cIdx) in crossShared.slice(0, 6)" :key="cIdx" class="contagion-card">
          <div class="cc-top">
            <span class="cc-phrase">"{{ ce.phrase }}"</span>
            <span class="cc-contour mono">{{ ce.phoneme_contour }} · ×{{ ce.total_occurrences }}</span>
          </div>
          <div class="cc-sharers">
            <button
              v-for="sb in ce.shared_by"
              :key="sb.speaker_id"
              type="button"
              class="sharer-pill mono"
              :style="{ borderColor: sb.color, color: sb.color }"
              :title="`Click to open ${sb.speaker_id}'s Shared Earworm Studio`"
              @click="$emit('select-speaker', { speakerId: sb.speaker_id, phrase: ce.phrase })"
            >
              🎧 {{ sb.speaker_id }} (×{{ sb.count }})
            </button>
            <button
              type="button"
              class="share-mini-btn mono"
              @click="$emit('select-speaker', { speakerId: ce.origin_speaker, phrase: ce.phrase })"
            >
              🔗 Share Earworm
            </button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'

const props = defineProps({
  earworm: { type: Object, default: () => ({}) },
  sharedEarworms: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['apply-config', 'select-speaker'])

const loadingCfg = ref(false)
const modelCfg = ref(null)

const zmq = computed(() => props.earworm?.zmq || {})
const cfg = computed(() => props.earworm?.config || {})
const crossShared = computed(() => props.sharedEarworms?.cross_speaker_earworms || [])
const f1Hz = computed(() => Math.round(Number(props.earworm?.target_f1_hz || 500)))
const f2Hz = computed(() => Math.round(Number(props.earworm?.target_f2_hz || 1500)))

// Map F2 [2800 -> 900 Hz] onto X [46 -> 244] and F1 [300 -> 900 Hz] onto Y [28 -> 128]
const formantDot = computed(() => {
  const f1 = Math.min(900, Math.max(300, f1Hz.value))
  const f2 = Math.min(2800, Math.max(900, f2Hz.value))
  const x = 46 + ((2800 - f2) / (2800 - 900)) * 198
  const y = 28 + ((f1 - 300) / (900 - 300)) * 100
  return { x: Number(x.toFixed(1)), y: Number(y.toFixed(1)) }
})

async function askModelConfig(force = false) {
  loadingCfg.value = true
  try {
    const res = await fetch('/api/ollama/earworm-config', {
      method: force ? 'POST' : 'GET',
      headers: { 'Content-Type': 'application/json' },
      body: force ? JSON.stringify({ force: true }) : undefined,
    })
    if (res.ok) {
      modelCfg.value = await res.json()
    }
  } catch (e) {
    console.error('Earworm config query error:', e)
  } finally {
    loadingCfg.value = false
  }
}

function toggleUdpMirror() {
  const nextVal = !(zmq.value.udp_mirror_enabled !== false)
  emit('apply-config', { udp_mirror_enabled: nextVal })
}

function applyEnhancedConfig() {
  const rp = modelCfg.value?.recommended_parameters || {}
  emit('apply-config', {
    whisper_trigger_mult: rp.whisper_trigger_mult ?? 2.15,
    silence_hangover_blocks: rp.silence_hangover_blocks ?? 5,
    sibilant_ratio: rp.sibilant_ratio ?? 1.45,
    markov_order: rp.markov_order ?? 2,
    pink_noise_alpha: rp.pink_noise_alpha ?? 0.82,
    ultrasonic_carrier_hz: rp.ultrasonic_carrier_hz ?? 40000,
    udp_host: rp.udp_host ?? '127.0.0.1',
  })
}

onMounted(() => {
  askModelConfig(false)
})
</script>

<style scoped>
.sub-caption {
  font-size: 0.78rem;
  color: var(--text-secondary);
  margin-top: 2px;
}
.active-whisp {
  background: rgba(63, 185, 80, 0.2);
  color: #7ee787;
  border: 1px solid rgba(63, 185, 80, 0.5);
}
.idle-whisp {
  background: rgba(139, 148, 158, 0.14);
  color: #8b949e;
  border: 1px solid rgba(139, 148, 158, 0.3);
}
.bpm-pill {
  background: rgba(210, 168, 255, 0.14);
  color: #d2a8ff;
  border: 1px solid rgba(210, 168, 255, 0.35);
}
.ew-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.zmq-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
.z-chip {
  font-size: 0.71rem;
  padding: 3px 9px;
  border-radius: 6px;
  background: #0b0f17;
  border: 1px solid #1d2738;
  color: var(--text-secondary);
}
.z-chip.live {
  border-color: rgba(63, 185, 80, 0.4);
  color: #c9d1d9;
}
.ew-grid {
  display: grid;
  grid-template-columns: 315px 1fr;
  gap: 14px;
  align-items: stretch;
}
.formant-box {
  background: #0b0f17;
  border: 1px solid #1d283a;
  border-radius: 10px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 6px;
}
.sec-hdr {
  display: flex;
  justify-content: space-between;
  font-size: 0.72rem;
  color: var(--text-secondary);
}
.vowel-svg {
  width: 100%;
  height: 168px;
}
.mirror-bar {
  display: flex;
  justify-content: space-between;
  font-size: 0.72rem;
  color: var(--text-secondary);
  border-top: 1px solid #172131;
  padding-top: 6px;
}
.predict-box {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.pred-cards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.pred-card {
  background: #0b0f17;
  border: 1px solid #1d283a;
  border-radius: 10px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.pc-lbl {
  font-size: 0.68rem;
  font-weight: 700;
  color: var(--text-secondary);
  letter-spacing: 0.04em;
}
.pc-flow {
  display: flex;
  align-items: center;
  gap: 10px;
}
.pc-node {
  flex: 1;
  background: #111824;
  border: 1px solid #1e2b40;
  border-radius: 8px;
  padding: 6px 10px;
  display: flex;
  flex-direction: column;
}
.pc-node.next {
  border-color: rgba(210, 168, 255, 0.45);
  color: #d2a8ff;
}
.pc-node.next-lex {
  border-color: rgba(63, 185, 80, 0.45);
}
.nd-sub {
  font-size: 0.63rem;
  color: var(--text-muted);
}
.arrow {
  color: #58a6ff;
  font-size: 1.05rem;
}
.syll-line {
  font-size: 0.71rem;
  color: var(--text-secondary);
}
.ph-chip {
  background: rgba(88, 166, 255, 0.16);
  color: #79c0ff;
  padding: 1px 7px;
  border-radius: 4px;
}
.muted {
  color: var(--text-muted);
}
.edges-row {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.edge-chip {
  font-size: 0.68rem;
  background: #131c2b;
  border: 1px solid #22324a;
  padding: 2px 7px;
  border-radius: 99px;
}
.edge-chip b {
  color: #7ee787;
}
.cfg-advisor {
  background: rgba(20, 29, 43, 0.72);
  border: 1px solid rgba(88, 166, 255, 0.32);
  border-radius: 10px;
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.cfg-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.cfg-badge {
  font-size: 0.74rem;
  font-weight: 700;
  color: #79c0ff;
  margin-right: 8px;
}
.live-tag {
  font-size: 0.68rem;
  background: rgba(63, 185, 80, 0.16);
  color: #3fb950;
  padding: 2px 7px;
  border-radius: 99px;
}
.btn-sm {
  padding: 4px 10px;
  font-size: 0.74rem;
}
.cfg-rat {
  font-size: 0.78rem;
  color: #c9d1d9;
  line-height: 1.4;
}
.cfg-cols {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  font-size: 0.74rem;
  color: var(--text-secondary);
}
.mini-title {
  font-weight: 700;
  color: #e6edf3;
  margin-bottom: 4px;
  font-size: 0.73rem;
}
.cfg-cols ul {
  padding-left: 16px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.shared-contagion-box {
  margin-top: 12px;
  background: linear-gradient(135deg, rgba(88, 166, 255, 0.06), rgba(210, 168, 255, 0.07));
  border: 1px solid rgba(210, 168, 255, 0.3);
  border-radius: 10px;
  padding: 10px 13px;
  display: flex;
  flex-direction: column;
  gap: 9px;
}
.contagion-hdr {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.contagion-title {
  font-size: 0.75rem;
  font-weight: 700;
  color: #d2a8ff;
}
.contagion-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 9px;
}
.contagion-card {
  background: #0b0f17;
  border: 1px solid #1e2b40;
  border-radius: 8px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.cc-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.cc-phrase {
  font-size: 0.82rem;
  font-weight: 700;
  color: #ffffff;
}
.cc-contour {
  font-size: 0.67rem;
  color: #79c0ff;
}
.cc-sharers {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.sharer-pill {
  background: #111826;
  border: 1px solid;
  border-radius: 99px;
  padding: 2px 8px;
  font-size: 0.68rem;
  cursor: pointer;
}
.sharer-pill:hover {
  background: rgba(88, 166, 255, 0.14);
}
.share-mini-btn {
  margin-left: auto;
  background: rgba(63, 185, 80, 0.15);
  border: 1px solid rgba(63, 185, 80, 0.45);
  color: #7ee787;
  border-radius: 99px;
  padding: 2px 9px;
  font-size: 0.68rem;
  cursor: pointer;
}
.share-mini-btn:hover {
  background: rgba(63, 185, 80, 0.28);
}
@media (max-width: 1120px) {
  .ew-grid,
  .pred-cards,
  .cfg-cols {
    grid-template-columns: 1fr;
  }
}
</style>
