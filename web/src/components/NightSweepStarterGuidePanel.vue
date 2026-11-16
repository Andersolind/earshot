<template>
  <section id="nightsweep-starter-guide" class="card starter-card" :class="{ 'has-missing': summary.any_nightsweep_missing }">
    <div class="card-header">
      <div>
        <div class="card-title">
          <span>🧰 NightSweep Models, Modals &amp; Full Dependency Starter Guide</span>
          <span
            class="pill mono"
            :class="summary.missing_count > 0 ? 'miss-pill' : (summary.any_nightsweep_missing ? 'warn-pill' : 'ok-pill')"
          >
            {{ summary.ready_count ?? 0 }}/{{ summary.total_dependencies ?? dependencies.length }} READY
            <template v-if="summary.fallback_count"> · {{ summary.fallback_count }} FALLBACK</template>
            <template v-if="summary.missing_count"> · {{ summary.missing_count }} MISSING</template>
          </span>
          <span class="pill mono" :class="summary.nightsweep_ollama_live ? 'ok-pill' : 'warn-pill'">
            🧠 Ollama NightSweep: {{ summary.nightsweep_ollama_live ? 'LIVE (:11434)' : 'CALIBRATED ENGINE' }}
          </span>
          <span class="pill mono" :class="summary.faster_whisper_ready ? 'ok-pill' : 'warn-pill'">
            🎙️ Faster-Whisper: {{ summary.faster_whisper_ready ? 'CACHED' : 'SETUP NEEDED' }}
          </span>
          <span class="pill mono" :class="summary.speaker_onnx_ready ? 'ok-pill' : 'warn-pill'">
            🧬 ResNet34-ONNX: {{ summary.speaker_onnx_ready ? '271-D ACTIVE' : '15-D VTL FALLBACK' }}
          </span>
        </div>
        <div class="sub-caption">
          Complete dependency inventory &amp; GitHub clone starter guide for <span class="mono">models/Modelfile.nightsweep-signalintelligence</span>,
          <span class="mono">Faster-Whisper</span>, <span class="mono">WeSpeaker ResNet34-ONNX</span>, <span class="mono">Radioconda GNU Radio 3.10+</span>,
          <span class="mono">Vue.js 3 + Three.js</span> &amp; all 8 Interactive NightSweep Person/Device Modals
        </div>
      </div>

      <div class="header-btns mono">
        <button type="button" class="btn btn-action" :disabled="busyAction !== ''" @click="runBootstrap('seed_demo_ledger')">
          {{ busyAction === 'seed_demo_ledger' ? '⏳ Seeding...' : '🌱 Seed Demo Ledger & Modals' }}
        </button>
        <button type="button" class="btn btn-action" :disabled="busyAction !== ''" @click="runBootstrap('build_ollama_model')">
          {{ busyAction === 'build_ollama_model' ? '⏳ Building...' : '⚡ Build Ollama NightSweep' }}
        </button>
        <button type="button" class="btn btn-action" :disabled="busyAction !== ''" @click="runBootstrap('verify_dsp')">
          {{ busyAction === 'verify_dsp' ? '⏳ Verifying...' : '🔬 Verify DSP & Modals' }}
        </button>
        <button type="button" class="btn" :disabled="busyAction !== ''" @click="fetchStatus(true)">
          🔄 Re-Check All
        </button>
        <button type="button" class="btn btn-toggle" @click="expanded = !expanded">
          {{ expanded ? '▲ Hide Guide' : '▼ Show All Dependencies (' + dependencies.length + ')' }}
        </button>
      </div>
    </div>

    <!-- ALERT CALLOUT WHEN NIGHTSWEEP MODELS / GITIGNORED DEPENDENCIES ARE MISSING -->
    <div v-if="summary.any_nightsweep_missing" class="missing-callout mono">
      <div class="mc-left">
        <strong>⚠️ Starter Setup Notice (GitHub Clone / Missing NightSweep Models or Modals):</strong>
        <span>
          Large runtime artifacts (<span class="code-inline">/radioconda/</span>, <span class="code-inline">/models/faster-whisper/</span>,
          <span class="code-inline">/models/speaker-onnx/</span>, <span class="code-inline">/web/node_modules/</span>, and
          <span class="code-inline">/recordings/*</span>) are excluded by <span class="code-inline">.gitignore</span>.
          Use the 1-click bootstrap buttons above or follow the step-by-step commands below to get every model, modal, and dependency online.
        </span>
      </div>
      <button v-if="!expanded" type="button" class="btn btn-action" @click="expanded = true">
        📘 Open Starter Guide
      </button>
    </div>

    <div v-if="toastMsg" class="toast-banner mono">
      ✅ {{ toastMsg }}
    </div>

    <div v-if="expanded" class="starter-body">
      <!-- 1. 3-COLUMN CORE NIGHTSWEEP AI & NEURAL MODEL CARDS -->
      <div class="models-grid">
        <div class="model-card" :class="models.ollama_nightsweep?.status?.toLowerCase()">
          <div class="m-top mono">
            <span class="m-title">🧠 1. NightSweep Signal-Intelligence LLM</span>
            <span class="status-badge" :class="models.ollama_nightsweep?.status?.toLowerCase()">
              {{ models.ollama_nightsweep?.status || 'FALLBACK' }}
            </span>
          </div>
          <div class="m-detail mono">
            <div><strong>Model:</strong> {{ models.ollama_nightsweep?.model_name || 'nightsweep-signalintelligence:latest' }}</div>
            <div><strong>Modelfile:</strong> {{ models.ollama_nightsweep?.modelfile_path }} ({{ models.ollama_nightsweep?.modelfile_exists ? 'Present · 16 Modules' : 'Missing' }})</div>
            <div><strong>Daemon (:11434):</strong> {{ models.ollama_nightsweep?.daemon_online ? 'Online' : 'Offline (Calibrated Engine Active)' }}</div>
          </div>
          <div class="cmd-row mono">
            <code>{{ models.ollama_nightsweep?.setup_cmd }}</code>
            <button type="button" class="copy-btn" @click="copyCmd(models.ollama_nightsweep?.setup_cmd, 'Ollama NightSweep build command')">
              📋 Copy
            </button>
          </div>
        </div>

        <div class="model-card" :class="models.faster_whisper?.status?.toLowerCase()">
          <div class="m-top mono">
            <span class="m-title">🎙️ 2. Faster-Whisper ASR Model Cache</span>
            <span class="status-badge" :class="models.faster_whisper?.status?.toLowerCase()">
              {{ models.faster_whisper?.status || 'READY' }}
            </span>
          </div>
          <div class="m-detail mono">
            <div><strong>Models:</strong> {{ models.faster_whisper?.model_name || 'Systran/faster-whisper-small.en & base.en' }}</div>
            <div><strong>Cache Path:</strong> {{ models.faster_whisper?.cache_dir || 'models/faster-whisper' }}</div>
            <div>
              <strong>Cached Weights:</strong>
              {{ models.faster_whisper?.cached_models?.length ? models.faster_whisper.cached_models.join(', ') : 'None (Will auto-download on first run)' }}
            </div>
          </div>
          <div class="cmd-row mono">
            <code>{{ models.faster_whisper?.setup_cmd }}</code>
            <button type="button" class="copy-btn" @click="copyCmd(models.faster_whisper?.setup_cmd, 'Faster-Whisper cache command')">
              📋 Copy
            </button>
          </div>
        </div>

        <div class="model-card" :class="models.speaker_onnx?.status?.toLowerCase()">
          <div class="m-top mono">
            <span class="m-title">🧬 3. WeSpeaker ResNet34-LM 256-D ONNX</span>
            <span class="status-badge" :class="models.speaker_onnx?.status?.toLowerCase()">
              {{ models.speaker_onnx?.status || 'READY' }}
            </span>
          </div>
          <div class="m-detail mono">
            <div><strong>Model:</strong> {{ models.speaker_onnx?.model_name || 'voxceleb_resnet34_LM.onnx' }}</div>
            <div><strong>Path:</strong> {{ models.speaker_onnx?.model_path || 'models/speaker-onnx/voxceleb_resnet34_LM.onnx' }}</div>
            <div>
              <strong>Embedding Mode:</strong>
              {{ models.speaker_onnx?.onnx_exists ? `${models.speaker_onnx.size_mb} MB · ${models.speaker_onnx.signature_dim}-D Neural+VTL` : '15-D Biometric VTL Fallback' }}
            </div>
          </div>
          <div class="cmd-row mono">
            <code>{{ models.speaker_onnx?.setup_cmd }}</code>
            <button type="button" class="copy-btn" @click="copyCmd(models.speaker_onnx?.setup_cmd, 'Speaker ONNX download command')">
              📋 Copy
            </button>
          </div>
        </div>
      </div>

      <!-- 2. INTERACTIVE NIGHTSWEEP MODAL LAUNCHER STRIP (ALL 8 IDENTITIES) -->
      <div class="modals-launcher mono">
        <div class="ml-left">
          <span class="ml-lbl">🪟 Open Any NightSweep 16-Module Dossier Modal:</span>
          <button
            v-for="spkId in modalIdentities"
            :key="spkId"
            type="button"
            class="modal-pill"
            @click="$emit('select-speaker', spkId)"
          >
            {{ iconFor(spkId) }} {{ spkId }}
          </button>
        </div>
        <span class="ml-hint">All 8 Person &amp; Device Modals include 16 NightSweep Reference Modules + Playable WAV Synthesizers</span>
      </div>

      <!-- 3. 5-STEP GITHUB CLONE QUICK-START CHECKLIST -->
      <div class="steps-box">
        <div class="sec-head mono">
          <span>🚀 Step-by-Step Starter Checklist (Fresh GitHub Clone → Full Live Cockpit)</span>
          <span class="muted">Click any command to copy for PowerShell</span>
        </div>
        <div class="steps-grid">
          <div
            v-for="st in starterSteps"
            :key="st.step"
            class="step-card"
            :class="{ done: st.done }"
          >
            <div class="st-top mono">
              <span class="st-num">STEP {{ st.step }}</span>
              <span class="st-badge" :class="st.done ? 'ok' : 'todo'">
                {{ st.done ? '✓ COMPLETE' : '⏳ ACTION NEEDED' }}
              </span>
            </div>
            <div class="st-title">{{ st.title }}</div>
            <p class="st-desc">{{ st.description }}</p>
            <div class="cmd-row mono">
              <code>{{ st.command }}</code>
              <button type="button" class="copy-btn" @click="copyCmd(st.command, `Step ${st.step} command`)">
                📋 Copy
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 4. COMPLETE FRONTEND & BACKEND DEPENDENCY INVENTORY TABLE -->
      <div class="deps-box">
        <div class="deps-header mono">
          <div class="deps-title">
            📦 All GNU-Larex &amp; NightSweep Dependencies ({{ filteredDeps.length }}/{{ dependencies.length }} Shown)
          </div>
          <div class="cat-tabs">
            <button
              v-for="cat in categoryTabs"
              :key="cat.key"
              type="button"
              class="cat-tab mono"
              :class="{ active: activeCategory === cat.key }"
              @click="activeCategory = cat.key"
            >
              {{ cat.label }} ({{ cat.count }})
            </button>
          </div>
        </div>

        <div class="table-wrap">
          <table class="deps-table mono">
            <thead>
              <tr>
                <th>Status</th>
                <th>Dependency / Model</th>
                <th>Category</th>
                <th>Version / Active Detail</th>
                <th>Path / Module</th>
                <th>Frontend Panel / NightSweep Modal Role</th>
                <th>Setup / Install Command</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="dep in filteredDeps" :key="dep.id">
                <td>
                  <span class="status-badge" :class="dep.status.toLowerCase()">
                    {{ dep.status === 'READY' ? '🟢 READY' : (dep.status === 'FALLBACK' ? '🟡 FALLBACK' : '🔴 MISSING') }}
                  </span>
                </td>
                <td>
                  <strong style="color: #e6edf3">{{ dep.name }}</strong>
                </td>
                <td>
                  <span class="cat-chip">{{ dep.category_label }}</span>
                </td>
                <td style="color: #79c0ff">{{ dep.version_or_detail }}</td>
                <td style="color: #8b949e">{{ dep.path_or_module }}</td>
                <td style="max-width: 280px; color: #c9d1d9">{{ dep.required_for }}</td>
                <td>
                  <div class="tbl-cmd">
                    <code>{{ dep.install_cmd }}</code>
                    <button type="button" class="copy-btn" @click="copyCmd(dep.install_cmd, dep.name)">
                      📋
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'

const props = defineProps({
  initialData: { type: Object, default: () => ({}) },
  forceOpen: { type: Boolean, default: false },
})

const emit = defineEmits(['select-speaker', 'updated'])

const localData = ref({})
const expanded = ref(true)
const activeCategory = ref('ALL')
const busyAction = ref('')
const toastMsg = ref('')

const merged = computed(() => {
  if (localData.value && Array.isArray(localData.value.dependencies) && localData.value.dependencies.length) {
    return localData.value
  }
  return props.initialData || {}
})

const summary = computed(() => merged.value?.summary || {})
const models = computed(() => merged.value?.nightsweep_models || {})
const dependencies = computed(() => merged.value?.dependencies || [])
const starterSteps = computed(() => merged.value?.starter_steps || [])
const modalIdentities = computed(
  () =>
    merged.value?.modal_identities || [
      'PERSON_DELTA',
      'PERSON_ALPHA',
      'PERSON_BETA',
      'PERSON_GAMMA',
      'PERSON_TYPIST',
      'DEVICE_CELLPHONE',
      'DEVICE_MEMS',
      'OTHER_ROOM_SUBLEVEL',
    ]
)

const categoryTabs = computed(() => {
  const all = dependencies.value
  return [
    { key: 'ALL', label: 'All Dependencies', count: all.length },
    {
      key: 'NIGHTSWEEP_MODELS',
      label: '🧠 NightSweep Models',
      count: all.filter((d) => d.category === 'NIGHTSWEEP_MODELS').length,
    },
    {
      key: 'PYTHON_DSP_STACK',
      label: '🐍 Python & Radioconda DSP',
      count: all.filter((d) => d.category === 'PYTHON_DSP_STACK').length,
    },
    {
      key: 'FRONTEND_WEB_STACK',
      label: '🌐 Vue 3 & Three.js Web',
      count: all.filter((d) => d.category === 'FRONTEND_WEB_STACK').length,
    },
    {
      key: 'FORENSIC_MODALS_DATA',
      label: '🪟 Forensic Modals & Ledgers',
      count: all.filter((d) => d.category === 'FORENSIC_MODALS_DATA').length,
    },
  ]
})

const filteredDeps = computed(() => {
  if (activeCategory.value === 'ALL') return dependencies.value
  return dependencies.value.filter((d) => d.category === activeCategory.value)
})

function iconFor(id) {
  if (id === 'PERSON_TYPIST') return '⌨️'
  if (id === 'DEVICE_CELLPHONE') return '📱'
  if (id === 'DEVICE_MEMS') return '🔬'
  if (id === 'OTHER_ROOM_SUBLEVEL') return '🧱'
  return '🎧'
}

function flash(msg) {
  toastMsg.value = msg
  setTimeout(() => {
    if (toastMsg.value === msg) toastMsg.value = ''
  }, 6000)
}

async function copyCmd(cmd, label) {
  if (!cmd) return
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(cmd)
      flash(`Copied ${label} to clipboard!`)
      return
    }
  } catch (_) {}
  flash(`Command for ${label}: ${cmd}`)
}

async function fetchStatus(force = false) {
  busyAction.value = 'check_all'
  try {
    const res = await fetch(`/api/starter-guide/status?refresh=${force ? '1' : '0'}`)
    if (res.ok) {
      localData.value = await res.json()
      if (force) {
        flash(
          `Verified ${localData.value.summary?.ready_count}/${localData.value.summary?.total_dependencies} dependencies READY!`
        )
      }
    }
  } catch (e) {
    console.error('Starter guide status error:', e)
  } finally {
    busyAction.value = ''
  }
}

async function runBootstrap(action) {
  busyAction.value = action
  try {
    const res = await fetch('/api/starter-guide/bootstrap', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    })
    if (res.ok) {
      const data = await res.json()
      if (data.starter_guide) localData.value = data.starter_guide
      flash(data.message || `Completed starter guide action: ${action}`)
      emit('updated')
    }
  } catch (e) {
    console.error('Starter guide bootstrap error:', e)
  } finally {
    busyAction.value = ''
  }
}

watch(
  () => props.forceOpen,
  (val) => {
    if (val) expanded.value = true
  }
)

onMounted(() => {
  fetchStatus(false)
})
</script>

<style scoped>
.starter-card {
  background: linear-gradient(180deg, rgba(16, 22, 35, 0.96), rgba(11, 16, 26, 0.96));
  border: 1px solid rgba(88, 166, 255, 0.38);
  border-radius: 12px;
  padding: 14px 16px;
}
.starter-card.has-missing {
  border-color: rgba(240, 136, 62, 0.65);
  box-shadow: 0 0 18px rgba(240, 136, 62, 0.12);
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 12px;
}
.card-title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 0.98rem;
  font-weight: 800;
  color: #e6edf3;
}
.sub-caption {
  font-size: 0.74rem;
  color: #8b949e;
  margin-top: 4px;
}
.pill {
  padding: 2px 9px;
  border-radius: 99px;
  font-size: 0.69rem;
  border: 1px solid #30363d;
}
.ok-pill {
  background: rgba(46, 160, 67, 0.16);
  border-color: rgba(63, 185, 80, 0.5);
  color: #7ee787;
}
.warn-pill {
  background: rgba(210, 153, 34, 0.16);
  border-color: rgba(240, 136, 62, 0.55);
  color: #ffa657;
}
.miss-pill {
  background: rgba(248, 81, 73, 0.16);
  border-color: rgba(248, 81, 73, 0.55);
  color: #ff7b72;
}
.header-btns {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.btn-action {
  background: rgba(56, 139, 253, 0.16);
  border: 1px solid rgba(88, 166, 255, 0.5);
  color: #79c0ff;
}
.btn-action:hover {
  background: rgba(56, 139, 253, 0.28);
}
.btn-toggle {
  background: rgba(110, 118, 129, 0.16);
  border: 1px solid #30363d;
  color: #c9d1d9;
}
.missing-callout {
  margin-top: 10px;
  background: rgba(210, 153, 34, 0.12);
  border: 1px solid rgba(240, 136, 62, 0.45);
  border-radius: 8px;
  padding: 9px 12px;
  font-size: 0.74rem;
  color: #f0883e;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.mc-left {
  display: flex;
  flex-direction: column;
  gap: 3px;
  color: #e6edf3;
}
.mc-left strong {
  color: #ffa657;
}
.code-inline {
  background: rgba(13, 17, 23, 0.75);
  padding: 1px 5px;
  border-radius: 4px;
  color: #79c0ff;
}
.toast-banner {
  margin-top: 10px;
  background: rgba(46, 160, 67, 0.18);
  border: 1px solid rgba(63, 185, 80, 0.5);
  border-radius: 8px;
  padding: 7px 12px;
  font-size: 0.75rem;
  color: #7ee787;
}
.starter-body {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.models-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
@media (max-width: 1180px) {
  .models-grid {
    grid-template-columns: 1fr;
  }
}
.model-card {
  background: #0d1117;
  border: 1px solid #21262d;
  border-radius: 9px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.model-card.ready {
  border-color: rgba(63, 185, 80, 0.4);
}
.model-card.fallback {
  border-color: rgba(240, 136, 62, 0.45);
}
.model-card.missing {
  border-color: rgba(248, 81, 73, 0.5);
}
.m-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.m-title {
  font-size: 0.78rem;
  font-weight: 700;
  color: #58a6ff;
}
.status-badge {
  padding: 2px 7px;
  border-radius: 99px;
  font-size: 0.65rem;
  font-weight: 700;
}
.status-badge.ready {
  background: rgba(46, 160, 67, 0.18);
  color: #7ee787;
  border: 1px solid rgba(63, 185, 80, 0.45);
}
.status-badge.fallback {
  background: rgba(210, 153, 34, 0.18);
  color: #ffa657;
  border: 1px solid rgba(240, 136, 62, 0.45);
}
.status-badge.missing {
  background: rgba(248, 81, 73, 0.18);
  color: #ff7b72;
  border: 1px solid rgba(248, 81, 73, 0.45);
}
.m-detail {
  font-size: 0.71rem;
  color: #8b949e;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.m-detail strong {
  color: #c9d1d9;
}
.cmd-row {
  background: #06090f;
  border: 1px solid #21262d;
  border-radius: 6px;
  padding: 5px 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-top: auto;
}
.cmd-row code {
  font-size: 0.67rem;
  color: #7ee787;
  overflow-x: auto;
  white-space: nowrap;
}
.copy-btn {
  background: #161b22;
  border: 1px solid #30363d;
  color: #c9d1d9;
  border-radius: 5px;
  padding: 2px 7px;
  font-size: 0.66rem;
  cursor: pointer;
  flex-shrink: 0;
}
.copy-btn:hover {
  border-color: #58a6ff;
  color: #58a6ff;
}
.modals-launcher {
  background: rgba(22, 27, 34, 0.85);
  border: 1px solid rgba(163, 113, 247, 0.35);
  border-radius: 8px;
  padding: 8px 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 0.72rem;
}
.ml-left {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}
.ml-lbl {
  color: #d2a8ff;
  font-weight: 700;
}
.modal-pill {
  background: #0d1117;
  border: 1px solid rgba(163, 113, 247, 0.45);
  color: #e9d5ff;
  border-radius: 99px;
  padding: 2px 9px;
  font-size: 0.69rem;
  cursor: pointer;
}
.modal-pill:hover {
  background: rgba(163, 113, 247, 0.2);
}
.ml-hint {
  color: #8b949e;
  font-size: 0.68rem;
}
.steps-box,
.deps-box {
  background: #0d1117;
  border: 1px solid #21262d;
  border-radius: 9px;
  padding: 10px 12px;
}
.sec-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 0.76rem;
  font-weight: 700;
  color: #79c0ff;
  margin-bottom: 8px;
}
.muted {
  color: #8b949e;
  font-weight: 400;
  font-size: 0.69rem;
}
.steps-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 8px;
}
@media (max-width: 1320px) {
  .steps-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
@media (max-width: 780px) {
  .steps-grid {
    grid-template-columns: 1fr;
  }
}
.step-card {
  background: #121821;
  border: 1px solid #21262d;
  border-radius: 8px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.step-card.done {
  border-color: rgba(63, 185, 80, 0.38);
}
.st-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.66rem;
}
.st-num {
  color: #58a6ff;
  font-weight: 700;
}
.st-badge.ok {
  color: #7ee787;
}
.st-badge.todo {
  color: #ffa657;
}
.st-title {
  font-size: 0.75rem;
  font-weight: 700;
  color: #e6edf3;
}
.st-desc {
  font-size: 0.68rem;
  color: #8b949e;
  line-height: 1.35;
}
.deps-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}
.deps-title {
  font-size: 0.78rem;
  font-weight: 700;
  color: #e6edf3;
}
.cat-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.cat-tab {
  background: #161b22;
  border: 1px solid #30363d;
  color: #8b949e;
  border-radius: 6px;
  padding: 3px 9px;
  font-size: 0.68rem;
  cursor: pointer;
}
.cat-tab.active {
  background: rgba(56, 139, 253, 0.18);
  border-color: #58a6ff;
  color: #79c0ff;
}
.table-wrap {
  overflow-x: auto;
}
.deps-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.7rem;
}
.deps-table th,
.deps-table td {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid #161b22;
  vertical-align: middle;
}
.deps-table th {
  color: #8b949e;
  font-weight: 600;
  background: #090d13;
}
.cat-chip {
  background: rgba(110, 118, 129, 0.15);
  border: 1px solid #30363d;
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 0.64rem;
  color: #c9d1d9;
}
.tbl-cmd {
  display: flex;
  align-items: center;
  gap: 6px;
  max-width: 290px;
}
.tbl-cmd code {
  background: #06090f;
  border: 1px solid #21262d;
  border-radius: 4px;
  padding: 2px 6px;
  color: #7ee787;
  font-size: 0.65rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
