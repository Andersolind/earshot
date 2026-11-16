<template>
  <section id="prespeech-electronics-studio" class="card pse-card">
    <div class="card-header">
      <div>
        <div class="card-title">
          <span>⚡ Pre-Speech Earworm Pre-Hear (50–200 ms) &amp; 📱🔬 Electronic / MEMS Characters</span>
          <span class="pill mono cyan-pill">
            ⚡ {{ prespeech.total_pre_speech_onsets ?? 0 }} Pre-Speech · 📡 {{ prespeech.total_ambient_precursors ?? 0 }} RF Precursors
          </span>
          <span
            class="pill mono click-pill pink-pill"
            title="Click to open DEVICE_CELLPHONE dossier & audible preview"
            @click="$emit('select-speaker', 'DEVICE_CELLPHONE')"
          >
            📱 CELLPHONE: {{ cellChar.clicks_captured ?? 0 }} clicks ↗
          </span>
          <span
            class="pill mono click-pill gold-pill"
            title="Click to open DEVICE_MEMS dossier & heterodyned ultrasonic WAV"
            @click="$emit('select-speaker', 'DEVICE_MEMS')"
          >
            🔬 MEMS: {{ memsChar.clicks_captured ?? 0 }} clicks ↗
          </span>
        </div>
        <div class="sub-caption">
          First-derivative cricothyroid larynx (<span class="mono">60–250 Hz</span>) + ultrasonic lip velocity (<span class="mono">300–1800 Hz</span>) pre-hears the Markov Earworm Δ before audible phonation · Strictly isolated <span class="mono">DEVICE_CELLPHONE</span> &amp; <span class="mono">DEVICE_MEMS</span> characters
        </div>
      </div>

      <div class="hdr-actions">
        <label class="toggle-chip mono" :class="{ on: localCfg.auto_play_pre_hear }">
          <input
            type="checkbox"
            v-model="localCfg.auto_play_pre_hear"
            @change="pushConfig({ auto_play_pre_hear: localCfg.auto_play_pre_hear })"
          />
          <span>{{ localCfg.auto_play_pre_hear ? '🔊 Pre-Hear Audio: ON' : '🔈 Pre-Hear Audio: MANUAL' }}</span>
        </label>
        <button class="btn btn-ollama mono" :disabled="ollamaBusy" @click="askOllamaAdvisor">
          {{ ollamaBusy ? '🧠 Consulting NightSweep…' : '🧠 Ask Ollama to Advise' }}
        </button>
      </div>
    </div>

    <!-- NIGHTSWEEP OLLAMA ADVISOR DRAWER -->
    <div v-if="advisor" class="ollama-drawer">
      <div class="od-top">
        <div class="mono od-title">
          🧠 <strong>{{ advisor.model || 'nightsweep-signalintelligence:latest' }}</strong>
          <span class="pill mono" :style="{ color: advisor.ollama_live ? '#3fb950' : '#d2a8ff' }">
            {{ advisor.ollama_live ? 'LIVE OLLAMA RESPONSE' : 'CALIBRATED PROFILE' }}
          </span>
        </div>
        <button class="btn btn-apply mono" :disabled="applyBusy" @click="applyOllamaRecommended">
          ⚡ Apply Recommended Pre-Speech &amp; MEMS Config Live
        </button>
      </div>
      <p class="od-summary">{{ advisor.overall_assessment }}</p>
      <div class="od-cols">
        <div class="od-col">
          <div class="sec-lbl mono">⚡ Pre-Hear Earworm &amp; Pre-Speech Advice</div>
          <ul>
            <li v-for="(tip, i) in advisor.prespeech_earworm_advice || []" :key="'ps-' + i">{{ tip }}</li>
          </ul>
        </div>
        <div class="od-col">
          <div class="sec-lbl mono">📱🔬 Cellphone &amp; MEMS Acoustic/RF Advice</div>
          <ul>
            <li v-for="(tip, i) in advisor.electronic_mems_advice || []" :key="'el-' + i">{{ tip }}</li>
          </ul>
        </div>
      </div>
    </div>

    <div v-if="statusBanner" class="status-banner mono">
      ✅ {{ statusBanner }}
    </div>

    <!-- 2-COLUMN BODY -->
    <div class="pse-grid">
      <!-- LEFT COLUMN: PRE-SPEECH TRIGGER & PRE-HEAR THE EARWORM -->
      <div class="pse-box">
        <div class="box-hdr">
          <div class="box-title mono">⚡ PreSpeechTriggerEngine · Pre-Hear Anticipated Earworm Δ</div>
          <span class="badge-lead mono">50–200 ms Pre-Phonatory Window</span>
        </div>

        <!-- Anticipated Pre-Hear Hero -->
        <div class="prehear-hero">
          <div class="ph-left">
            <div class="ph-lbl mono">🎧 ARMED PRE-HEAR EARWORM PREVIEW (FIRES BEFORE SPEECH STARTS)</div>
            <div class="ph-hook">
              "{{ preview.pre_heard_hook || 'see you next time' }}"
              <span v-if="preview.predicted_next_token" class="ph-next mono">
                → +{{ preview.predicted_next_token }}
              </span>
            </div>
            <div class="ph-meta mono">
              <span class="m-chip">Order-{{ preview.markov_order || 3 }} {{ preview.is_promoted_chain ? 'Promoted M4' : 'Markov' }}</span>
              <span class="m-chip">{{ preview.phoneme_contour || 'S/T-EE-OO' }}</span>
              <span class="m-chip">{{ preview.earworm_bpm || 118 }} BPM</span>
              <span class="m-chip">Lead Bias: {{ localCfg.lead_time_bias_ms }} ms</span>
            </div>
          </div>
          <div class="ph-btns">
            <button class="btn btn-trig mono" :disabled="simBusy" @click="simulateEvent('PRE_SPEECH_ONSET')">
              ⚡ Pre-Hear Onset (120ms)
            </button>
            <button class="btn btn-rf mono" :disabled="simBusy" @click="simulateEvent('AMBIENT_DEVICE_PRECURSOR')">
              📡 HackRF Precursor (80ms)
            </button>
          </div>
        </div>

        <!-- First-Derivative Physics Gate Telemetry -->
        <div class="gate-strip mono">
          <div class="g-cell">
            <span class="g-lbl">Larynx Prep (60–250 Hz)</span>
            <strong>{{ Number(prespeech.last_larynx_prep || 0).toFixed(4) }}</strong>
          </div>
          <div class="g-cell">
            <span class="g-lbl">d(Tension)/dt</span>
            <strong :style="{ color: (prespeech.last_tension_velocity || 0) > 0 ? '#7ee787' : '#8b949e' }">
              {{ Number(prespeech.last_tension_velocity || 0).toFixed(5) }}
            </strong>
          </div>
          <div class="g-cell">
            <span class="g-lbl">d(Lip Doppler)/dt</span>
            <strong :style="{ color: (prespeech.last_lip_velocity || 0) > 0 ? '#58a6ff' : '#8b949e' }">
              {{ Number(prespeech.last_lip_velocity || 0).toFixed(5) }}
            </strong>
          </div>
          <div class="g-cell">
            <span class="g-lbl">Posture Sway (1–18 Hz)</span>
            <strong>{{ Number(prespeech.last_posture_energy || 0).toFixed(4) }}</strong>
          </div>
          <div class="g-cell">
            <span class="g-lbl">Quiet Gate (&lt;{{ localCfg.quiet_rms_ceiling }})</span>
            <strong :style="{ color: (prespeech.last_audible_rms || 0) < localCfg.quiet_rms_ceiling ? '#3fb950' : '#f0883e' }">
              RMS {{ Number(prespeech.last_audible_rms || 0).toFixed(4) }}
            </strong>
          </div>
        </div>

        <!-- Pre-Speech Sliders -->
        <div class="sliders-grid mono">
          <label>
            <span>Tension Vel Mult: <b>{{ localCfg.tension_vel_mult.toFixed(2) }}×</b></span>
            <input
              type="range" min="0.90" max="4.00" step="0.05"
              v-model.number="localCfg.tension_vel_mult"
              @change="pushConfig({ tension_vel_mult: localCfg.tension_vel_mult })"
            />
          </label>
          <label>
            <span>Posture Reject: <b>{{ localCfg.posture_reject_ratio.toFixed(2) }}×</b></span>
            <input
              type="range" min="1.80" max="6.50" step="0.05"
              v-model.number="localCfg.posture_reject_ratio"
              @change="pushConfig({ posture_reject_ratio: localCfg.posture_reject_ratio })"
            />
          </label>
          <label>
            <span>HackRF Spike: <b>{{ localCfg.hackrf_spike_thresh.toFixed(2) }}</b></span>
            <input
              type="range" min="0.05" max="0.45" step="0.01"
              v-model.number="localCfg.hackrf_spike_thresh"
              @change="pushConfig({ hackrf_spike_thresh: localCfg.hackrf_spike_thresh })"
            />
          </label>
          <label>
            <span>Lead Bias: <b>{{ localCfg.lead_time_bias_ms }} ms</b></span>
            <input
              type="range" min="65" max="195" step="5"
              v-model.number="localCfg.lead_time_bias_ms"
              @change="pushConfig({ lead_time_bias_ms: localCfg.lead_time_bias_ms })"
            />
          </label>
        </div>

        <!-- Recent Pre-Heard Earworm Triggers + Inline WAV Player -->
        <div class="feed-hdr mono">
          <span>🔊 Pre-Heard Earworm Cue Stream (48 kHz Whisper Preview WAV)</span>
          <span>{{ (prespeech.recent_events || []).length }} recent</span>
        </div>
        <div v-if="prespeech.recent_events?.length" class="ev-list">
          <div v-for="ev in prespeech.recent_events.slice(0, 5)" :key="ev.id" class="ev-row">
            <div class="ev-top mono">
              <span
                class="ev-tag"
                :class="ev.event === 'AMBIENT_DEVICE_PRECURSOR' ? 'rf-tag' : 'onset-tag'"
              >
                {{ ev.event }} (-{{ ev.lead_time_est_ms }}ms)
              </span>
              <span class="ev-hook">
                "{{ ev.pre_heard_hook }}"
                <strong v-if="ev.predicted_next_token" style="color: #7ee787">→ {{ ev.predicted_next_token }}</strong>
              </span>
              <span class="ev-ts">{{ (ev.timestamp_utc || '').slice(11, 19) }}</span>
            </div>
            <div class="ev-audio-row mono">
              <span>ΔTension {{ ev.tension_velocity }} · ΔLip {{ ev.lip_velocity }} · {{ ev.phoneme_contour }}</span>
              <audio :src="ev.audio_url" controls preload="none" class="mini-audio"></audio>
            </div>
          </div>
        </div>
        <div v-else class="empty-note mono">
          Listening for silent 50–200 ms larynx + lip snaps or click "⚡ Pre-Hear Onset (120ms)" to audition the anticipated Earworm Δ.
        </div>
      </div>

      <!-- RIGHT COLUMN: CLICKABLE ELECTRONIC & MEMS CHARACTERS -->
      <div class="pse-box">
        <div class="box-hdr">
          <div class="box-title mono">📱🔬 Clickable Electronic &amp; MEMS Characters (48 kHz Acoustic + Ultrasonic)</div>
          <span class="badge-iso mono">M5 Isolated · Zero Vocal Δ Drift</span>
        </div>

        <div class="char-cards">
          <!-- DEVICE_CELLPHONE CARD -->
          <div
            class="char-card cell-card"
            title="Click to inspect DEVICE_CELLPHONE dossier & play LRA/UI/PMIC WAV"
            @click="$emit('select-speaker', 'DEVICE_CELLPHONE')"
          >
            <div class="cc-top">
              <div class="cc-id mono" style="color: #f778ba">
                📱 DEVICE_CELLPHONE
                <span class="open-tag">Click Character ↗</span>
              </div>
              <button
                type="button"
                class="btn btn-cell mono"
                :disabled="simBusy"
                @click.stop="simulateEvent('DEVICE_CELLPHONE')"
              >
                📱 Simulate Cellphone Click
              </button>
            </div>
            <div class="cc-desc">
              135–235 Hz LRA / Taptic buzz + 1.8–4.8 kHz capacitive glass tick + 17.2–21.2 kHz OLED/PMIC switching
            </div>
            <div class="cc-stats mono">
              <span>Clicks: <b style="color: #f778ba">{{ cellChar.clicks_captured ?? 0 }}</b></span>
              <span>Bursts: <b>{{ cellChar.bursts_captured ?? 0 }}</b></span>
              <span>Pos: <b>{{ cellChar.range_m ?? 0.54 }}m ({{ formatAz(cellChar.azimuth_deg ?? 22) }})</b></span>
              <span>Tokens: <code>[HAPTIC_TAP] [UI_TICK] [PMIC_WAKE]</code></span>
            </div>
          </div>

          <!-- DEVICE_MEMS CARD -->
          <div
            class="char-card mems-card"
            title="Click to inspect DEVICE_MEMS dossier & play 16 kHz heterodyned ultrasonic WAV"
            @click="$emit('select-speaker', 'DEVICE_MEMS')"
          >
            <div class="cc-top">
              <div class="cc-id mono" style="color: #eab308">
                🔬 DEVICE_MEMS
                <span class="open-tag gold-open">Click Character ↗</span>
              </div>
              <button
                type="button"
                class="btn btn-mems mono"
                :disabled="simBusy"
                @click.stop="simulateEvent('DEVICE_MEMS')"
              >
                🔬 Simulate MEMS Click
              </button>
            </div>
            <div class="cc-desc">
              14.5–23.8 kHz high-Q MEMS transducer pings, smartwatch/earbud piezo clicks &amp; camera OIS voice-coils
            </div>
            <div class="cc-stats mono">
              <span>Clicks: <b style="color: #eab308">{{ memsChar.clicks_captured ?? 0 }}</b></span>
              <span>Bursts: <b>{{ memsChar.bursts_captured ?? 0 }}</b></span>
              <span>Pos: <b>{{ memsChar.range_m ?? 0.76 }}m ({{ formatAz(memsChar.azimuth_deg ?? -24) }})</b></span>
              <span>Tokens: <code>[MEMS_PING] [PIEZO_CLICK] [COIL_SWITCH]</code></span>
            </div>
          </div>
        </div>

        <!-- Electronics Threshold & Spatial Sliders -->
        <div class="sliders-grid mono">
          <label>
            <span>Cellphone Crest: <b>{{ localCfg.cellphone_crest_thresh.toFixed(2) }}</b></span>
            <input
              type="range" min="2.50" max="6.50" step="0.05"
              v-model.number="localCfg.cellphone_crest_thresh"
              @change="pushConfig({ cellphone_crest_thresh: localCfg.cellphone_crest_thresh })"
            />
          </label>
          <label>
            <span>MEMS Ultra Ratio: <b>{{ localCfg.mems_ultra_ratio.toFixed(2) }}×</b></span>
            <input
              type="range" min="0.80" max="3.20" step="0.05"
              v-model.number="localCfg.mems_ultra_ratio"
              @change="pushConfig({ mems_ultra_ratio: localCfg.mems_ultra_ratio })"
            />
          </label>
          <label>
            <span>📱 Bearing: <b>{{ formatAz(localCfg.cellphone_azimuth_deg) }}</b></span>
            <input
              type="range" min="-75" max="75" step="1"
              v-model.number="localCfg.cellphone_azimuth_deg"
              @change="pushConfig({ cellphone_azimuth_deg: localCfg.cellphone_azimuth_deg })"
            />
          </label>
          <label>
            <span>🔬 Bearing: <b>{{ formatAz(localCfg.mems_azimuth_deg) }}</b></span>
            <input
              type="range" min="-75" max="75" step="1"
              v-model.number="localCfg.mems_azimuth_deg"
              @change="pushConfig({ mems_azimuth_deg: localCfg.mems_azimuth_deg })"
            />
          </label>
        </div>

        <!-- Captured Electronic / MEMS Click Feed -->
        <div class="feed-hdr mono">
          <span>📡 Captured Electronic &amp; MEMS Character Stream (Click Row to Open Dossier)</span>
          <span>{{ (electronics.recent_events || []).length }} clusters</span>
        </div>
        <div v-if="electronics.recent_events?.length" class="ev-list">
          <div
            v-for="(cev, idx) in electronics.recent_events.slice(0, 6)"
            :key="'el-' + idx"
            class="ev-row clickable-ev"
            @click="$emit('select-speaker', cev.speaker_id)"
          >
            <div class="ev-top mono">
              <strong :style="{ color: cev.speaker_id === 'DEVICE_MEMS' ? '#eab308' : '#f778ba' }">
                {{ cev.speaker_id === 'DEVICE_MEMS' ? '🔬' : '📱' }} {{ cev.speaker_id }}
              </strong>
              <span>Peak {{ cev.mean_peak_hz }} Hz · {{ cev.click_count }}× clicks</span>
              <span class="ev-ts">{{ (cev.timestamp_utc || '').slice(11, 19) }}</span>
            </div>
            <div class="ev-tokens mono">{{ cev.transcript }}</div>
          </div>
        </div>
        <div v-else class="empty-note mono">
          Scanning 0–24 kHz UltraMic stream for smartphone LRA/PMIC clicks and high-Q ultrasonic MEMS transients.
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'

const props = defineProps({
  data: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['select-speaker', 'updated'])

const ollamaBusy = ref(false)
const applyBusy = ref(false)
const simBusy = ref(false)
const statusBanner = ref('')
const localAdvisor = ref(null)

const prespeech = computed(() => props.data?.prespeech || {})
const electronics = computed(() => props.data?.electronics || {})
const preview = computed(() => prespeech.value?.next_pre_hear_preview || {})
const cellChar = computed(() => electronics.value?.characters?.DEVICE_CELLPHONE || {})
const memsChar = computed(() => electronics.value?.characters?.DEVICE_MEMS || {})
const advisor = computed(() => localAdvisor.value || props.data?.last_ollama_advisor || null)

const localCfg = reactive({
  tension_vel_mult: 1.80,
  posture_reject_ratio: 3.50,
  quiet_rms_ceiling: 0.030,
  hackrf_spike_thresh: 0.15,
  lead_time_bias_ms: 120,
  auto_play_pre_hear: false,
  cellphone_crest_thresh: 3.55,
  mems_ultra_ratio: 1.35,
  cellphone_azimuth_deg: 22,
  mems_azimuth_deg: -24,
})

watch(
  () => [prespeech.value?.config, electronics.value?.config],
  ([psC, elC]) => {
    if (psC) {
      if (psC.tension_vel_mult !== undefined) localCfg.tension_vel_mult = Number(psC.tension_vel_mult)
      if (psC.posture_reject_ratio !== undefined) localCfg.posture_reject_ratio = Number(psC.posture_reject_ratio)
      if (psC.quiet_rms_ceiling !== undefined) localCfg.quiet_rms_ceiling = Number(psC.quiet_rms_ceiling)
      if (psC.hackrf_spike_thresh !== undefined) localCfg.hackrf_spike_thresh = Number(psC.hackrf_spike_thresh)
      if (psC.lead_time_bias_ms !== undefined) localCfg.lead_time_bias_ms = Number(psC.lead_time_bias_ms)
      if (psC.auto_play_pre_hear !== undefined) localCfg.auto_play_pre_hear = Boolean(psC.auto_play_pre_hear)
    }
    if (elC) {
      if (elC.cellphone_crest_thresh !== undefined) localCfg.cellphone_crest_thresh = Number(elC.cellphone_crest_thresh)
      if (elC.mems_ultra_ratio !== undefined) localCfg.mems_ultra_ratio = Number(elC.mems_ultra_ratio)
      if (elC.cellphone_azimuth_deg !== undefined) localCfg.cellphone_azimuth_deg = Number(elC.cellphone_azimuth_deg)
      if (elC.mems_azimuth_deg !== undefined) localCfg.mems_azimuth_deg = Number(elC.mems_azimuth_deg)
    }
  },
  { immediate: true, deep: true }
)

function formatAz(az) {
  const v = Number(az || 0)
  return (v > 0 ? '+' : '') + v.toFixed(0) + '°'
}

function flashBanner(msg) {
  statusBanner.value = msg
  setTimeout(() => {
    if (statusBanner.value === msg) statusBanner.value = ''
  }, 5000)
}

async function pushConfig(patch) {
  try {
    const res = await fetch('/api/prespeech-electronics/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
    if (res.ok) {
      const j = await res.json()
      flashBanner('Applied live: ' + (j.applied || []).join(', '))
      emit('updated')
    }
  } catch (e) {
    console.error(e)
  }
}

async function simulateEvent(target) {
  simBusy.value = true
  try {
    const res = await fetch('/api/prespeech-electronics/simulate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target }),
    })
    if (res.ok) {
      const j = await res.json()
      if (j.kind === 'PRESPEECH' && j.event) {
        flashBanner(`Pre-Heard Earworm (-${j.event.lead_time_est_ms}ms): "${j.event.pre_heard_hook}"`)
        if (j.event.audio_url) {
          try {
            const aud = new Audio(j.event.audio_url)
            aud.volume = 0.7
            aud.play().catch(() => {})
          } catch (_) {}
        }
      } else {
        flashBanner(`Captured ${j.speaker_id} electronic transient cluster!`)
      }
      emit('updated')
    }
  } catch (e) {
    console.error(e)
  } finally {
    simBusy.value = false
  }
}

async function askOllamaAdvisor() {
  ollamaBusy.value = true
  try {
    const res = await fetch('/api/ollama/prespeech-electronics', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force: true }),
    })
    if (res.ok) {
      localAdvisor.value = await res.json()
      flashBanner('NightSweep Ollama advisor updated pre-speech & MEMS recommendations.')
    }
  } catch (e) {
    console.error(e)
  } finally {
    ollamaBusy.value = false
  }
}

async function applyOllamaRecommended() {
  if (!advisor.value?.recommended_config) return
  applyBusy.value = true
  try {
    await pushConfig(advisor.value.recommended_config)
  } finally {
    applyBusy.value = false
  }
}
</script>

<style scoped>
.pse-card {
  border: 1px solid #26354d;
  background: linear-gradient(180deg, #0d1420 0%, #0a0f18 100%);
}
.cyan-pill {
  color: #58a6ff;
  border-color: rgba(88, 166, 255, 0.35);
}
.click-pill {
  cursor: pointer;
  transition: transform 0.12s ease, filter 0.12s ease;
}
.click-pill:hover {
  transform: translateY(-1px);
  filter: brightness(1.18);
}
.pink-pill {
  color: #f778ba;
  border-color: rgba(247, 120, 186, 0.45);
  background: rgba(247, 120, 186, 0.09);
}
.gold-pill {
  color: #eab308;
  border-color: rgba(234, 179, 8, 0.45);
  background: rgba(234, 179, 8, 0.09);
}
.hdr-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.toggle-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: 6px;
  border: 1px solid #30363d;
  background: #111824;
  font-size: 11.5px;
  color: #8b949e;
  cursor: pointer;
}
.toggle-chip.on {
  border-color: #3fb950;
  color: #7ee787;
  background: rgba(63, 185, 80, 0.1);
}
.btn-ollama {
  background: linear-gradient(135deg, #6e40c9, #8957e5);
  color: #fff;
  border: none;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
}
.ollama-drawer {
  margin-top: 12px;
  padding: 12px 14px;
  border-radius: 8px;
  border: 1px solid rgba(163, 113, 247, 0.4);
  background: rgba(137, 87, 229, 0.08);
}
.od-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.od-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: #e6edf3;
}
.btn-apply {
  background: #238636;
  color: #fff;
  border: none;
  padding: 5px 11px;
  border-radius: 6px;
  font-size: 11.5px;
  cursor: pointer;
}
.od-summary {
  margin: 8px 0;
  font-size: 12.5px;
  color: #c9d1d9;
  line-height: 1.45;
}
.od-cols {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.od-col ul {
  margin: 4px 0 0;
  padding-left: 18px;
  font-size: 12px;
  color: #b1bac4;
  line-height: 1.45;
}
.status-banner {
  margin-top: 10px;
  padding: 6px 11px;
  border-radius: 6px;
  background: rgba(63, 185, 80, 0.12);
  border: 1px solid rgba(63, 185, 80, 0.4);
  color: #7ee787;
  font-size: 12px;
}
.pse-grid {
  margin-top: 14px;
  display: grid;
  grid-template-columns: 1.05fr 0.95fr;
  gap: 14px;
}
.pse-box {
  border: 1px solid #1f2a3c;
  border-radius: 9px;
  padding: 12px;
  background: #0b111b;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.box-hdr {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.box-title {
  font-size: 12.5px;
  font-weight: 700;
  color: #e6edf3;
}
.badge-lead {
  font-size: 10.5px;
  padding: 2px 7px;
  border-radius: 99px;
  background: rgba(88, 166, 255, 0.14);
  color: #79c0ff;
}
.badge-iso {
  font-size: 10.5px;
  padding: 2px 7px;
  border-radius: 99px;
  background: rgba(63, 185, 80, 0.14);
  color: #7ee787;
}
.prehear-hero {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 11px 12px;
  border-radius: 8px;
  background: linear-gradient(135deg, rgba(47, 129, 247, 0.13), rgba(63, 185, 80, 0.08));
  border: 1px solid rgba(88, 166, 255, 0.32);
}
.ph-lbl {
  font-size: 10px;
  color: #79c0ff;
  letter-spacing: 0.04em;
}
.ph-hook {
  margin-top: 3px;
  font-size: 16px;
  font-weight: 700;
  color: #f0f6fc;
}
.ph-next {
  font-size: 13px;
  color: #7ee787;
  margin-left: 6px;
}
.ph-meta {
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.m-chip {
  font-size: 10.5px;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(13, 17, 23, 0.75);
  border: 1px solid #283548;
  color: #9ecbff;
}
.ph-btns {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.btn-trig {
  background: #1f6feb;
  color: #fff;
  border: none;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 11.5px;
  cursor: pointer;
  white-space: nowrap;
}
.btn-rf {
  background: #21262d;
  color: #d2a8ff;
  border: 1px solid rgba(210, 168, 255, 0.4);
  padding: 5px 10px;
  border-radius: 6px;
  font-size: 11.5px;
  cursor: pointer;
  white-space: nowrap;
}
.gate-strip {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 6px;
}
.g-cell {
  background: #101725;
  border: 1px solid #1d293b;
  border-radius: 6px;
  padding: 6px 7px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.g-lbl {
  font-size: 9.5px;
  color: #8b949e;
}
.g-cell strong {
  font-size: 11.5px;
  color: #e6edf3;
}
.sliders-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px 12px;
  padding: 8px 10px;
  border-radius: 7px;
  background: #0e1522;
  border: 1px solid #1a2436;
}
.sliders-grid label {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 11px;
  color: #8b949e;
}
.sliders-grid b {
  color: #e6edf3;
}
.feed-hdr {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: #8b949e;
}
.ev-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 225px;
  overflow-y: auto;
}
.ev-row {
  padding: 7px 9px;
  border-radius: 6px;
  background: #101826;
  border: 1px solid #1e2b3e;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.clickable-ev {
  cursor: pointer;
  transition: border-color 0.12s ease;
}
.clickable-ev:hover {
  border-color: #58a6ff;
}
.ev-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-size: 11.5px;
}
.ev-tag {
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 700;
}
.onset-tag {
  background: rgba(56, 139, 253, 0.2);
  color: #79c0ff;
}
.rf-tag {
  background: rgba(210, 168, 255, 0.2);
  color: #d2a8ff;
}
.ev-hook {
  color: #f0f6fc;
  flex: 1;
}
.ev-ts {
  color: #6e7681;
  font-size: 10.5px;
}
.ev-audio-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-size: 10.5px;
  color: #8b949e;
}
.mini-audio {
  height: 26px;
  width: 210px;
}
.char-cards {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.char-card {
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: transform 0.12s ease, border-color 0.12s ease;
}
.char-card:hover {
  transform: translateY(-1px);
}
.cell-card {
  background: rgba(247, 120, 186, 0.06);
  border: 1px solid rgba(247, 120, 186, 0.35);
}
.mems-card {
  background: rgba(234, 179, 8, 0.06);
  border: 1px solid rgba(234, 179, 8, 0.35);
}
.cc-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.cc-id {
  font-size: 13px;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 7px;
}
.open-tag {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 99px;
  border: 1px solid rgba(247, 120, 186, 0.45);
  color: #f778ba;
}
.gold-open {
  border-color: rgba(234, 179, 8, 0.45);
  color: #eab308;
}
.btn-cell {
  background: rgba(247, 120, 186, 0.18);
  color: #ff9bce;
  border: 1px solid rgba(247, 120, 186, 0.5);
  padding: 4px 9px;
  border-radius: 6px;
  font-size: 11px;
  cursor: pointer;
}
.btn-mems {
  background: rgba(234, 179, 8, 0.18);
  color: #fde047;
  border: 1px solid rgba(234, 179, 8, 0.5);
  padding: 4px 9px;
  border-radius: 6px;
  font-size: 11px;
  cursor: pointer;
}
.cc-desc {
  margin-top: 4px;
  font-size: 11.5px;
  color: #9ca3af;
}
.cc-stats {
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 11px;
  color: #c9d1d9;
}
.cc-stats code {
  color: #79c0ff;
  font-size: 10.5px;
}
.ev-tokens {
  font-size: 11px;
  color: #c9d1d9;
}
.empty-note {
  padding: 12px;
  border-radius: 6px;
  background: #0e1521;
  color: #8b949e;
  font-size: 11.5px;
  text-align: center;
}
@media (max-width: 1150px) {
  .pse-grid,
  .od-cols {
    grid-template-columns: 1fr;
  }
  .gate-strip {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
