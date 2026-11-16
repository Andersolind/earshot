<template>
  <section class="card advisor-card">
    <div class="card-header">
      <div>
        <div class="card-title">
          <span>🧠 Ollama Signal Refiner &amp; Live Self-Improvement Studio</span>
          <span class="pill mono" :class="report?.ollama_live ? 'live-pill' : 'fallback-pill'">
            {{ report?.model || 'nightsweep-signalintelligence:latest' }}
            <template v-if="report?.ollama_live"> · LIVE ({{ report.latency_ms }} ms)</template>
            <template v-else-if="report"> · CALIBRATED ENGINE</template>
          </span>
          <span class="pill mono hook-pill" title="Gemini CLI + Antigravity CLI PostToolUse Auto-Build Hook">
            ⚡ CLI Auto-Build Hook:
            {{ selfStatus?.autobuild_hook?.agy_hook_installed && selfStatus?.autobuild_hook?.gemini_hook_installed ? 'ARMED' : 'READY' }}
          </span>
        </div>
        <div class="sub-caption">
          Per-speaker DSP/VAD refinement (<span class="mono">ALPHA · BETA · DELTA · GAMMA</span>), 3D Closest-Identity Faint Focus,
          <span class="mono">ThreeStateVADRouter</span> Silent Reading Out-Loud &amp; 1-click persisted UI self-improvements
        </div>
      </div>

      <div class="query-controls">
        <input
          v-model="focusPrompt"
          class="focus-input"
          type="text"
          placeholder="Ask NightSweep Ollama to focus closest faint identity, tune ThreeStateVADRouter Reading Out-Loud, or refine speakers..."
          @keyup.enter="runQuery(true)"
        />
        <button class="btn btn-primary" :disabled="loading" @click="runQuery(true)">
          {{ loading ? '⏳ Querying Ollama...' : '✨ Query & Refine' }}
        </button>
        <button type="button" class="btn mono" style="border-color: rgba(88,166,255,0.45); color: #79c0ff" @click="emit('open-starter-guide')">
          🧰 Starter Guide &amp; Deps
        </button>
      </div>
    </div>

    <div v-if="appliedMsg" class="applied-banner mono">
      ✅ {{ appliedMsg }}
    </div>

    <div v-if="report" class="advisor-body">
      <div class="exec-box">
        <div class="exec-label mono">EXECUTIVE SIGNAL SYNTHESIS ({{ report.queried_at_utc }})</div>
        <p>{{ report.executive_summary }}</p>
      </div>

      <!-- PERSON_GAMMA EMPIRICAL MID-FIELD PACE INVESTIGATION CALLOUT -->
      <div v-if="gammaInfo" class="gamma-callout">
        <div class="gamma-head">
          <div
            class="gamma-title mono spk-clickable"
            title="Click to inspect & share PERSON_GAMMA's earworm"
            @click="$emit('select-speaker', 'PERSON_GAMMA')"
          >
            🔬 PERSON_GAMMA DIAGNOSTIC: Why Minimal Utterances ({{ gammaInfo.utterances_observed }} turns) Yet Fastest Active Pace ({{ gammaInfo.active_speaking_pace_wph }} WPH)? 🎧
          </div>
          <span class="pill mono" style="color: #d2a8ff; border-color: rgba(210,168,255,0.45)">
            Range {{ gammaInfo.median_range_m }}m (max {{ gammaInfo.max_range_m }}m) · DRR {{ gammaInfo.median_drr_db }} dB · {{ gammaInfo.median_throat_excursion_um }} µm
          </span>
        </div>
        <p class="gamma-text">{{ gammaInfo.root_cause }}</p>
        <div class="gamma-fix mono">
          <strong>Applied Engine Fix:</strong> {{ gammaInfo.applied_tuning }}
        </div>
      </div>

      <!-- 3-COLUMN REFINED FINDINGS, DSP/VAD & SPATIAL RECOMMENDATIONS -->
      <div class="rec-columns">
        <div class="rec-col">
          <h4>🔍 Refined Speaker &amp; Lexical Findings</h4>
          <ul>
            <li v-for="(item, idx) in report.refined_findings" :key="'f-' + idx">
              {{ item }}
            </li>
          </ul>
        </div>

        <div class="rec-col">
          <h4>🎛️ GNU Radio DSP &amp; Biometric VAD Tuning</h4>
          <ul>
            <li v-for="(item, idx) in report.dsp_and_vad_recommendations" :key="'d-' + idx">
              {{ item }}
            </li>
          </ul>
        </div>

        <div class="rec-col">
          <h4>📡 Spatial DRR Polar &amp; GCC-PHAT-Beta</h4>
          <ul>
            <li v-for="(item, idx) in report.spatial_position_recommendations" :key="'s-' + idx">
              {{ item }}
            </li>
          </ul>
        </div>
      </div>

      <!-- OLLAMA RECOMMENDED UI SELF-IMPROVEMENT WORKFLOW + 1-CLICK CARDS -->
      <div class="studio-section">
        <div class="studio-header">
          <div>
            <div class="studio-title">🚀 Recommended UI Self-Improvements (1-Click Apply &amp; Persist)</div>
            <div class="studio-sub">
              Applies immediately to the live 48 kHz GNU Radio / VAD / Wiener / Spatial engine and persists to
              <span class="mono">recordings/self_improvements_registry.json</span>
            </div>
          </div>
          <button
            v-if="report.recommended_controls"
            class="btn"
            @click="applyRecommendedControls"
          >
            🎛️ Apply Global Controls (+{{ report.recommended_controls.sublevel_sensitivity_db }}dB · β={{ report.recommended_controls.gcc_phat_beta || 0.78 }})
          </button>
        </div>

        <div v-if="report.ui_self_improvement_workflow?.length" class="workflow-strip">
          <div
            v-for="(step, sIdx) in report.ui_self_improvement_workflow"
            :key="'wf-' + sIdx"
            class="wf-step"
          >
            {{ step }}
          </div>
        </div>

        <div class="si-cards-grid">
          <div
            v-for="card in report.self_improvements || []"
            :key="card.id"
            class="si-card"
          >
            <div class="si-card-top">
              <button
                type="button"
                class="spk-tag spk-clickable mono"
                :class="'spk-' + card.speaker_id"
                :title="`Click to open & share ${card.speaker_id}'s earworm`"
                @click="$emit('select-speaker', card.speaker_id)"
              >
                🎧 {{ card.speaker_id }}
              </button>
              <span class="cat-tag mono">{{ card.category }}</span>
            </div>
            <div class="si-card-title">{{ card.title }}</div>
            <p class="si-card-desc">{{ card.rationale }}</p>
            <button class="btn btn-apply-si" :disabled="applyingId === card.id" @click="applySelfImprovementCard(card)">
              {{ applyingId === card.id ? '⏳ Applying...' : '⚡ Apply & Persist to Engine' }}
            </button>
          </div>
        </div>
      </div>

      <!-- CUSTOM PER-SPEAKER SELF-IMPROVEMENT COMPOSER + LIVE AUTO-BUILD HOOK BAR -->
      <div class="composer-box">
        <div class="composer-title mono">🛠️ Add Custom Per-Speaker Self-Improvement Rule</div>
        <div class="composer-row">
          <label class="field-item">
            <span class="mono">Speaker</span>
            <select v-model="customRule.speaker_id" @change="syncSpeakerDefaults">
              <option value="PERSON_ALPHA">PERSON_ALPHA (High Whisper)</option>
              <option value="PERSON_BETA">PERSON_BETA (High Speech)</option>
              <option value="PERSON_DELTA">PERSON_DELTA (Quiet Short)</option>
              <option value="PERSON_GAMMA">PERSON_GAMMA (Mid-Field Fast)</option>
            </select>
          </label>
          <label class="field-item">
            <span class="mono">VAD Mult (x)</span>
            <input v-model.number="customRule.dyn_thresh_mult" type="number" step="0.05" min="1.6" max="5.5" />
          </label>
          <label class="field-item">
            <span class="mono">Low-Amb (x)</span>
            <input v-model.number="customRule.low_ambient_whisper_mult" type="number" step="0.02" min="1.04" max="2.2" />
          </label>
          <label class="field-item">
            <span class="mono">Mouth Hi (Hz)</span>
            <input v-model.number="customRule.mouth_hi_hz" type="number" step="100" min="2800" max="8000" />
          </label>
          <label class="field-item">
            <span class="mono">Wiener Denoise</span>
            <input v-model.number="customRule.delta_denoise_strength" type="number" step="0.05" min="0.8" max="2.8" />
          </label>
          <label class="field-item">
            <span class="mono">Polar Anchor (°)</span>
            <input v-model.number="customRule.anchor_az_deg" type="number" step="1" min="-75" max="75" />
          </label>
          <label class="field-item">
            <span class="mono">DRR Trim (dB)</span>
            <input v-model.number="customRule.drr_trim_db" type="number" step="0.2" min="-5" max="5" />
          </label>
          <label class="field-item">
            <span class="mono">GCC-PHAT β</span>
            <input v-model.number="customRule.gcc_phat_beta" type="number" step="0.02" min="0.50" max="0.98" />
          </label>
          <button class="btn btn-primary" :disabled="savingCustom" @click="saveCustomImprovement">
            {{ savingCustom ? 'Saving...' : '➕ Add & Persist' }}
          </button>
        </div>

        <!-- PERSISTED REGISTRY + GEMINI CLI AUTO-BUILD STATUS -->
        <div class="autobuild-bar">
          <div class="persisted-list">
            <span class="mono persisted-lbl">Persisted Rules ({{ persistedList.length }}):</span>
            <button
              v-for="item in persistedList.slice(0, 5)"
              :key="item.id"
              type="button"
              class="persisted-pill spk-clickable mono"
              :title="(item.applied_changes || []).join(', ')"
              @click="$emit('select-speaker', item.speaker_id)"
            >
              ✓ {{ item.speaker_id }} · {{ shortTitle(item.title) }}
            </button>
          </div>
          <div class="autobuild-actions">
            <span v-if="selfStatus?.autobuild_hook?.last_build?.built_at_utc" class="mono build-meta">
              Last Auto-Build: {{ selfStatus.autobuild_hook.last_build.built_at_utc }}
              ({{ selfStatus.autobuild_hook.last_build.duration_ms }}ms)
            </span>
            <button class="btn" :disabled="buildingUi" @click="triggerLiveBuild">
              {{ buildingUi ? '🔨 Building Vite UI...' : '🔨 Trigger Live UI Build' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'

const props = defineProps({
  hours: { type: Number, default: 6 },
  scope: { type: String, default: 'active' },
})

const emit = defineEmits(['apply-preset', 'select-speaker', 'open-starter-guide'])

const focusPrompt = ref('')
const loading = ref(false)
const report = ref(null)
const selfStatus = ref(null)
const applyingId = ref('')
const savingCustom = ref(false)
const buildingUi = ref(false)
const appliedMsg = ref('')

const SPEAKER_DEFAULTS = {
  PERSON_ALPHA: { dyn_thresh_mult: 3.15, low_ambient_whisper_mult: 1.14, mouth_hi_hz: 5200, delta_denoise_strength: 1.65, anchor_az_deg: -45, drr_trim_db: 0.5, gcc_phat_beta: 0.78 },
  PERSON_BETA: { dyn_thresh_mult: 3.60, low_ambient_whisper_mult: 1.20, mouth_hi_hz: 4000, delta_denoise_strength: 1.50, anchor_az_deg: 48, drr_trim_db: 0.8, gcc_phat_beta: 0.78 },
  PERSON_DELTA: { dyn_thresh_mult: 2.85, low_ambient_whisper_mult: 1.10, mouth_hi_hz: 4800, delta_denoise_strength: 1.75, anchor_az_deg: 36, drr_trim_db: 2.8, gcc_phat_beta: 0.78 },
  PERSON_GAMMA: { dyn_thresh_mult: 2.55, low_ambient_whisper_mult: 1.12, mouth_hi_hz: 4400, delta_denoise_strength: 1.60, anchor_az_deg: -15, drr_trim_db: -1.5, gcc_phat_beta: 0.80 },
}

const customRule = reactive({
  speaker_id: 'PERSON_ALPHA',
  ...SPEAKER_DEFAULTS.PERSON_ALPHA,
})

function syncSpeakerDefaults() {
  const preset = SPEAKER_DEFAULTS[customRule.speaker_id]
  if (preset) Object.assign(customRule, preset)
}

const gammaInfo = computed(() => {
  return selfStatus.value?.gamma_investigation || report.value?.gamma_investigation || null
})

const persistedList = computed(() => {
  return selfStatus.value?.persisted_improvements || []
})

function shortTitle(t) {
  const s = String(t || '')
  return s.length > 34 ? s.slice(0, 32) + '…' : s
}

function flashBanner(msg) {
  appliedMsg.value = msg
  setTimeout(() => {
    if (appliedMsg.value === msg) appliedMsg.value = ''
  }, 6000)
}

async function fetchSelfStatus() {
  try {
    const res = await fetch('/api/self-improve/status')
    if (res.ok) selfStatus.value = await res.json()
  } catch (err) {
    console.error('Self-improve status error:', err)
  }
}

async function runQuery(force = true) {
  loading.value = true
  try {
    const res = await fetch('/api/ollama/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        focus: focusPrompt.value,
        hours: props.hours,
        scope: props.scope,
        force,
      }),
    })
    if (res.ok) {
      report.value = await res.json()
    }
    await fetchSelfStatus()
  } catch (err) {
    console.error('Ollama advisor error:', err)
  } finally {
    loading.value = false
  }
}

async function applySelfImprovementCard(card) {
  applyingId.value = card.id
  try {
    const res = await fetch('/api/self-improve/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: card.id,
        title: card.title,
        speaker_id: card.speaker_id,
        category: card.category,
        source: 'Ollama 1-Click Self-Improvement',
        payload: card.payload,
      }),
    })
    if (res.ok) {
      const data = await res.json()
      if (data.self_improvement) selfStatus.value = data.self_improvement
      flashBanner(`Persisted & applied ${card.speaker_id}: ${(data.applied || []).join(' · ')}`)
      emit('apply-preset', {})
    }
  } catch (err) {
    console.error('Apply self-improvement card error:', err)
  } finally {
    applyingId.value = ''
  }
}

async function saveCustomImprovement() {
  savingCustom.value = true
  try {
    const spk = customRule.speaker_id
    const payload = {
      speaker_id: spk,
      activate_speaker_profile: true,
      gcc_phat_beta: customRule.gcc_phat_beta,
      delta_denoise_strength: customRule.delta_denoise_strength,
      mouth_overrides: { mouth_hi_hz: customRule.mouth_hi_hz },
      vad_overrides: {
        dyn_thresh_mult: customRule.dyn_thresh_mult,
        low_ambient_whisper_mult: customRule.low_ambient_whisper_mult,
      },
      polar_overrides: {
        anchor_az_deg: customRule.anchor_az_deg,
        drr_trim_db: customRule.drr_trim_db,
      },
    }
    const res = await fetch('/api/self-improve/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: `${spk} Custom UI Tuning (VAD ${customRule.dyn_thresh_mult}x, Az ${customRule.anchor_az_deg}°, β=${customRule.gcc_phat_beta})`,
        speaker_id: spk,
        category: 'CUSTOM_UI_TUNING',
        source: 'Vue Live Self-Improvement Composer',
        payload,
      }),
    })
    if (res.ok) {
      const data = await res.json()
      if (data.self_improvement) selfStatus.value = data.self_improvement
      flashBanner(`Saved custom ${spk} self-improvement to registry (${(data.applied || []).join(' · ')})`)
      emit('apply-preset', {})
    }
  } catch (err) {
    console.error('Custom self-improvement save error:', err)
  } finally {
    savingCustom.value = false
  }
}

async function triggerLiveBuild() {
  buildingUi.value = true
  try {
    const res = await fetch('/api/self-improve/build-ui', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: 'Vue Studio Live Build Button' }),
    })
    if (res.ok) {
      const data = await res.json()
      await fetchSelfStatus()
      flashBanner(`Live Vite UI bundle rebuilt in ${data.duration_ms || 0} ms`)
    }
  } catch (err) {
    console.error('Trigger UI build error:', err)
  } finally {
    buildingUi.value = false
  }
}

function applyRecommendedControls() {
  if (!report.value?.recommended_controls) return
  emit('apply-preset', report.value.recommended_controls)
  flashBanner('Applied recommended GNU Radio & GCC-PHAT-Beta controls live')
}

onMounted(() => {
  fetchSelfStatus()
  runQuery(false)
})
</script>

<style scoped>
.advisor-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.live-pill {
  color: #7ee787;
  border-color: rgba(63, 185, 80, 0.45);
  background: rgba(46, 160, 67, 0.14);
}

.fallback-pill {
  color: #58a6ff;
}

.hook-pill {
  color: #f0883e;
  border-color: rgba(240, 136, 62, 0.4);
  background: rgba(240, 136, 62, 0.1);
}

.applied-banner {
  background: rgba(46, 160, 67, 0.16);
  border: 1px solid rgba(63, 185, 80, 0.48);
  color: #7ee787;
  padding: 7px 12px;
  border-radius: 8px;
  font-size: 0.77rem;
}

.query-controls {
  display: flex;
  gap: 8px;
  flex: 1;
  max-width: 560px;
}

.focus-input {
  flex: 1;
  background: #0b0f17;
  border: 1px solid var(--border);
  border-radius: 7px;
  padding: 7px 11px;
  color: var(--text-main);
  font-size: 0.8rem;
}

.focus-input:focus {
  outline: none;
  border-color: var(--accent);
}

.advisor-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.exec-box {
  background: linear-gradient(90deg, rgba(47, 129, 247, 0.1), rgba(18, 25, 38, 0.85));
  border: 1px solid #263959;
  border-radius: 8px;
  padding: 11px 14px;
}

.exec-label {
  font-size: 0.69rem;
  color: #79c0ff;
  margin-bottom: 4px;
}

.exec-box p {
  margin: 0;
  font-size: 0.84rem;
  line-height: 1.48;
  color: #e6edf3;
}

.gamma-callout {
  background: linear-gradient(90deg, rgba(210, 168, 255, 0.1), rgba(16, 22, 34, 0.92));
  border: 1px solid rgba(210, 168, 255, 0.36);
  border-radius: 8px;
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.gamma-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.gamma-title {
  font-size: 0.77rem;
  font-weight: 700;
  color: #d2a8ff;
}

.gamma-text {
  margin: 0;
  font-size: 0.78rem;
  line-height: 1.44;
  color: #c9d1d9;
}

.gamma-fix {
  font-size: 0.73rem;
  color: #7ee787;
}

.rec-columns {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

@media (max-width: 1100px) {
  .rec-columns {
    grid-template-columns: 1fr;
  }
}

.rec-col {
  background: var(--bg-panel-alt);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 11px 13px;
}

.rec-col h4 {
  margin: 0 0 8px;
  font-size: 0.81rem;
  color: #e6edf3;
}

.rec-col ul {
  margin: 0;
  padding-left: 17px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.rec-col li {
  font-size: 0.77rem;
  color: #b1bac4;
  line-height: 1.42;
}

.studio-section {
  background: #0d131f;
  border: 1px solid #24334a;
  border-radius: 9px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.studio-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.studio-title {
  font-size: 0.85rem;
  font-weight: 700;
  color: #e6edf3;
}

.studio-sub {
  font-size: 0.74rem;
  color: #8b949e;
}

.workflow-strip {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

@media (max-width: 1100px) {
  .workflow-strip {
    grid-template-columns: 1fr;
  }
}

.wf-step {
  background: rgba(47, 129, 247, 0.07);
  border: 1px dashed #294166;
  border-radius: 6px;
  padding: 7px 10px;
  font-size: 0.74rem;
  color: #9ecbff;
  line-height: 1.38;
}

.si-cards-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

@media (max-width: 1250px) {
  .si-cards-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 680px) {
  .si-cards-grid {
    grid-template-columns: 1fr;
  }
  .composer-row .field-item {
    flex: 1 1 calc(50% - 8px);
    min-width: 120px;
  }
  .field-item select,
  .field-item input {
    width: 100%;
    min-width: 0;
    box-sizing: border-box;
  }
}

.si-card {
  background: #111927;
  border: 1px solid #24334d;
  border-radius: 8px;
  padding: 10px 11px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 7px;
  min-width: 0;
}

.si-card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.spk-tag {
  font-size: 0.68rem;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 99px;
  border: 1px solid rgba(88, 166, 255, 0.35);
  background: rgba(88, 166, 255, 0.14);
  color: #58a6ff;
}
.spk-clickable {
  cursor: pointer;
}
.spk-clickable:hover {
  filter: brightness(1.18);
}

.spk-PERSON_BETA {
  background: rgba(63, 185, 80, 0.15);
  color: #3fb950;
}

.spk-PERSON_DELTA {
  background: rgba(240, 136, 62, 0.15);
  color: #f0883e;
}

.spk-PERSON_GAMMA {
  background: rgba(210, 168, 255, 0.15);
  color: #d2a8ff;
}

.cat-tag {
  font-size: 0.64rem;
  color: #8b949e;
}

.si-card-title {
  font-size: 0.78rem;
  font-weight: 600;
  color: #e6edf3;
  line-height: 1.34;
}

.si-card-desc {
  margin: 0;
  font-size: 0.73rem;
  color: #9ca3af;
  line-height: 1.38;
}

.btn-apply-si {
  width: 100%;
  justify-content: center;
  border-color: rgba(63, 185, 80, 0.45);
  color: #7ee787;
  font-size: 0.74rem;
}

.composer-box {
  background: var(--bg-panel-alt);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 13px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.composer-title {
  font-size: 0.75rem;
  color: #79c0ff;
  font-weight: 600;
}

.composer-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: flex-end;
}

.field-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 0.68rem;
  color: #8b949e;
}

.field-item select,
.field-item input {
  background: #0b0f17;
  border: 1px solid #283548;
  border-radius: 6px;
  color: #e6edf3;
  padding: 5px 7px;
  font-size: 0.75rem;
  min-width: 82px;
}

.autobuild-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding-top: 8px;
  border-top: 1px solid #1e293b;
}

.persisted-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.persisted-lbl {
  font-size: 0.7rem;
  color: #8b949e;
}

.persisted-pill {
  font-size: 0.68rem;
  background: rgba(56, 139, 253, 0.12);
  border: 1px solid rgba(56, 139, 253, 0.3);
  color: #9ecbff;
  padding: 2px 8px;
  border-radius: 99px;
}

.autobuild-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.build-meta {
  font-size: 0.7rem;
  color: #7ee787;
}
</style>
