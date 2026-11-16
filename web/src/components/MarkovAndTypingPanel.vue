<template>
  <section id="markov-typing-studio" class="panel mt-panel">
    <!-- TOP HEADER -->
    <div class="panel-hdr">
      <div>
        <div class="title-row">
          <h2>🧬 Per-Sentence Markov → Earworm Δ Inspector &amp; ⌨️ Dedicated <code>PERSON_TYPIST</code> Capture</h2>
          <span class="badge badge-cyan mono">
            M4 Auto-Promoted 3rd/4th-Order Phrase + M1/M2 Bigram + M3 Keystroke
          </span>
          <button
            type="button"
            class="badge badge-typist mono"
            @click="$emit('select-speaker', 'PERSON_TYPIST')"
            title="Click to inspect dedicated PERSON_TYPIST dossier"
          >
            ⌨️ PERSON_TYPIST: STRICT TYPING ONLY ({{ typing.total_bursts_captured ?? 0 }} bursts · {{ typing.live_wpm ?? 0 }} WPM · {{ tConfig.desk_azimuth_deg ?? -8 }}°/{{ tConfig.desk_range_m ?? 0.68 }}m)
          </button>
        </div>
        <p class="sub">
          Automatically promotes locked low-entropy 2nd-order hooks into <strong>3rd &amp; 4th-order phrase chains</strong>
          to trace full multi-word <strong>Earworm Δ</strong> loops, while isolating 48 kHz acoustic keystroke transients into
          <code>PERSON_TYPIST</code>.
        </p>
      </div>

      <div class="hdr-actions mono">
        <button
          type="button"
          class="btn btn-typist"
          :disabled="busySim"
          @click="simulateTypingBurst"
          title="Synthesizes 48 kHz mechanical switch clicks + plate thocks and runs them through AcousticTypingPersonEngine"
        >
          {{ busySim ? '⌨️ Capturing...' : '⌨️ Capture Test Typing Burst (75 WPM)' }}
        </button>
        <button
          type="button"
          class="btn btn-ollama"
          :disabled="busyOllama"
          @click="askOllamaImprovements"
        >
          {{ busyOllama ? '🧠 Querying NightSweep...' : '🧠 Ask Ollama for Markov & Typing Improvements' }}
        </button>
      </div>
    </div>

    <!-- KPI SUMMARY STRIP -->
    <div class="kpi-row mono">
      <div class="kpi-card">
        <span class="k-lbl">SENTENCES EVALUATED</span>
        <strong class="k-val">{{ kpis.total_sentences_evaluated ?? 0 }}</strong>
        <span class="k-sub">{{ kpis.lexical_bigram_states ?? 0 }} bi · {{ kpis.lexical_trigram_states ?? 0 }} tri · {{ kpis.lexical_quadgram_states ?? 0 }} quad</span>
      </div>
      <div class="kpi-card promoted-kpi">
        <span class="k-lbl">🚀 3RD/4TH-ORDER PROMOTIONS</span>
        <strong class="k-val violet">{{ kpis.higher_order_activation_pct ?? 0 }}% ({{ kpis.promoted_chains_count ?? 0 }} chains)</strong>
        <span class="k-sub">Gate: H ≤ {{ mConfig.promotion_entropy_max_bits ?? 1.65 }}b · {{ mConfig.auto_promote_higher_order !== false ? 'AUTO ON' : 'OFF' }}</span>
      </div>
      <div class="kpi-card">
        <span class="k-lbl">2ND-ORDER BIGRAM ACTIVATION</span>
        <strong class="k-val cyan">{{ kpis.bigram_activation_pct ?? 0 }}%</strong>
        <span class="k-sub">1st-Order Backoff: {{ kpis.unigram_backoff_pct ?? 0 }}%</span>
      </div>
      <div class="kpi-card">
        <span class="k-lbl">EMERGENT EARWORM Δ</span>
        <strong class="k-val green">{{ kpis.current_earworm_delta ? `"${kpis.current_earworm_delta}"` : 'warming up' }}</strong>
        <span class="k-sub">Δ Shifts: {{ kpis.delta_shifts_count ?? 0 }} (γ_eff={{ kpis.effective_decay_gamma ?? mConfig.decay_gamma ?? 0.988 }})</span>
      </div>
      <div class="kpi-card typist-kpi" @click="$emit('select-speaker', 'PERSON_TYPIST')">
        <span class="k-lbl">⌨️ PERSON_TYPIST (ISOLATED)</span>
        <strong class="k-val teal">{{ typing.total_keystrokes_captured ?? 0 }} keys ({{ typing.live_wpm ?? 0 }} WPM)</strong>
        <span class="k-sub">
          {{ tConfig.desk_sector_preset || 'CENTER_DESK' }}: {{ tConfig.desk_azimuth_deg ?? -8 }}°±{{ tConfig.directional_hysteresis_deg ?? 22 }}° · Z-Vib {{ typing.last_z_vibro_score ?? 0 }}
        </span>
      </div>
    </div>

    <div v-if="bannerMsg" class="banner mono">
      {{ bannerMsg }}
    </div>

    <!-- OLLAMA MARKOV + TYPING ADVISOR DRAWER -->
    <div v-if="ollamaReport" class="ollama-box">
      <div class="ob-hdr">
        <div class="mono">
          <strong>🧠 NightSweep Signal-Intelligence Markov &amp; Acoustic Typing Advisor</strong>
          <span class="ob-tag">{{ ollamaReport.ollama_live ? '🟢 LIVE OLLAMA' : '⚡ CALIBRATED PROFILE' }} · {{ ollamaReport.model }}</span>
        </div>
        <button
          v-if="ollamaReport.recommended_config"
          type="button"
          class="btn btn-apply mono"
          :disabled="busyCfg"
          @click="applyRecommendedConfig(ollamaReport.recommended_config)"
        >
          ⚡ Apply Recommended Markov + Typing Config Live
        </button>
      </div>
      <p class="ob-summary">{{ ollamaReport.markov_analysis }}</p>
      <div class="ob-cols">
        <div>
          <div class="ob-sub mono">🧬 Markov → Earworm Δ Enhancements</div>
          <ul>
            <li v-for="(item, i) in ollamaReport.markov_improvements || []" :key="i">{{ item }}</li>
          </ul>
        </div>
        <div>
          <div class="ob-sub mono">⌨️ 48 kHz Live Typing &amp; PERSON_TYPIST Isolation</div>
          <ul>
            <li v-for="(item, i) in ollamaReport.typing_capture_recommendations || []" :key="i">{{ item }}</li>
          </ul>
        </div>
      </div>
    </div>

    <!-- MAIN 2-COLUMN INSPECTOR -->
    <div class="main-cols">
      <!-- LEFT COLUMN: PER-SENTENCE MARKOV ACTIVATION TRACE -->
      <div class="sub-panel">
        <div class="sp-hdr mono">
          <span>🔍 Sentence-by-Sentence Markov Activation Trace</span>
          <div class="filter-pills">
            <button
              type="button"
              class="f-pill"
              :class="{ active: filterMode === 'ALL' }"
              @click="filterMode = 'ALL'"
            >
              All ({{ activations.length }})
            </button>
            <button
              type="button"
              class="f-pill"
              :class="{ active: filterMode === 'PROMOTED' }"
              @click="filterMode = 'PROMOTED'"
            >
              🚀 3rd/4th-Order
            </button>
            <button
              type="button"
              class="f-pill"
              :class="{ active: filterMode === 'DELTA' }"
              @click="filterMode = 'DELTA'"
            >
              🔥 Δ Shifts &amp; Locks
            </button>
            <button
              type="button"
              class="f-pill"
              :class="{ active: filterMode === 'TYPIST' }"
              @click="filterMode = 'TYPIST'"
            >
              ⌨️ PERSON_TYPIST Only
            </button>
          </div>
        </div>

        <!-- Auto-Promoted 3rd/4th-Order Phrase Chains -->
        <div v-if="(markov.promoted_chains || []).length" class="hook-leaderboard promoted-bar mono">
          <span class="hl-lbl violet-txt">🚀 Promoted 3rd/4th-Order Chains:</span>
          <span
            v-for="pc in markov.promoted_chains.slice(0, 5)"
            :key="pc.phrase"
            class="hl-chip promoted-chip"
            :class="{ winner: pc.is_active_delta }"
          >
            [Order {{ pc.order }}] "{{ pc.phrase }}" (×{{ pc.activations }}, H={{ pc.lock_entropy_bits }}b)
          </span>
        </div>

        <!-- Active Weighted Hook Scores -->
        <div v-if="(markov.top_delta_hooks || []).length" class="hook-leaderboard mono">
          <span class="hl-lbl">Weighted Δ Candidates:</span>
          <span
            v-for="hk in markov.top_delta_hooks.slice(0, 5)"
            :key="hk.hook"
            class="hl-chip"
            :class="{ winner: hk.is_active_delta }"
          >
            {{ hk.is_active_delta ? '👑 ' : '' }}"{{ hk.hook }}" (×{{ hk.repeats }}, w={{ hk.weight }})
          </span>
        </div>

        <div class="act-feed">
          <div
            v-for="act in filteredActivations"
            :key="act.id"
            class="act-card"
            :class="{
              shifted: act.delta_outcome === 'EARWORM_DELTA_SHIFTED',
              reinforced: act.delta_outcome === 'EARWORM_DELTA_REINFORCED',
              promoted: (act.markov_order || 0) >= 3 || (act.promoted_this_sentence || []).length > 0,
              typist: act.speaker_id === 'PERSON_TYPIST',
            }"
          >
            <div class="ac-top mono">
              <div class="ac-left">
                <button
                  type="button"
                  class="spk-pill mono"
                  :class="{ typist: act.speaker_id === 'PERSON_TYPIST' }"
                  @click="$emit('select-speaker', act.speaker_id)"
                >
                  {{ act.speaker_id === 'PERSON_TYPIST' ? '⌨️' : '🎧' }} {{ act.speaker_id }}
                </button>
                <span class="model-tag" :class="{ high: (act.markov_order || 0) >= 3 }">
                  {{ (act.markov_order || 0) >= 3 ? '🚀' : '⚡' }} {{ act.active_model }}
                </span>
                <span class="ent-tag" title="Shannon transition entropy (lower = tighter earworm loop)">
                  H={{ act.entropy_bits }}b
                </span>
              </div>
              <span class="outcome-pill" :class="outcomeClass(act.delta_outcome)">
                {{ formatOutcome(act) }}
              </span>
            </div>

            <div class="ac-sentence">"{{ act.sentence_text }}"</div>

            <div v-if="(act.promoted_this_sentence || []).length" class="promo-callout mono">
              🚀 Locked 2nd-Order Hook Auto-Promoted ➔ 3rd/4th-Order Phrase Chain:
              <strong v-for="(phStr, pIdx) in act.promoted_this_sentence.slice(0, 2)" :key="pIdx">
                "{{ phStr }}"{{ pIdx < Math.min(act.promoted_this_sentence.length, 2) - 1 ? ', ' : '' }}
              </strong>
            </div>

            <div v-if="act.phoneme_sequence" class="ac-contour mono">
              Contour Chain: <span>{{ act.phoneme_sequence }}</span>
            </div>

            <!-- Activated Markov Edges inside this sentence -->
            <div v-if="(act.activated_edges || []).length" class="edges-row mono">
              <span class="e-lbl">Activated Edges:</span>
              <span
                v-for="(ed, eIdx) in act.activated_edges.slice(-3)"
                :key="eIdx"
                class="edge-chip"
              >
                {{ ed.from_state }} ➔ <strong>{{ ed.to_state }}</strong> (P={{ ed.prob }})
              </span>
            </div>

            <!-- Outgoing Next-Token Markov Predictions + Delta Transition -->
            <div class="preds-row mono">
              <div v-if="(act.top_next_predictions || []).length">
                <span class="e-lbl">Next State P(wₜ₊₁|S):</span>
                <span
                  v-for="(pr, pIdx) in act.top_next_predictions.slice(0, 3)"
                  :key="pIdx"
                  class="pred-chip"
                >
                  "{{ pr.token }}" ({{ Math.round(pr.prob * 100) }}%)
                </span>
              </div>
              <div v-if="act.delta_shift_triggered" class="delta-trans">
                Δ Transition: "{{ act.earworm_delta_before || 'none' }}" ➔ <strong>"{{ act.earworm_delta_after }}"</strong>
              </div>
            </div>
          </div>

          <div v-if="!filteredActivations.length" class="empty-msg mono">
            No matching Markov activations in this filter yet.
          </div>
        </div>
      </div>

      <!-- RIGHT COLUMN: DEDICATED PERSON_TYPIST ENGINE & LIVE TUNING -->
      <div class="sub-panel typist-panel">
        <div class="sp-hdr mono">
          <span style="color: #2dd4bf">⌨️ Dedicated Identity: <code>PERSON_TYPIST</code> (Live Acoustic Typing)</span>
          <label class="chk-lbl">
            <input
              type="checkbox"
              :checked="typing.enabled !== false"
              @change="pushConfig({ enabled: $event.target.checked })"
            />
            Capture Active
          </label>
        </div>

        <!-- HOW ACOUSTIC TYPING CAPTURE WORKS -->
        <div class="how-box mono">
          <div class="how-title">How GNU-Larex Captures Live Typing Without OS Keyloggers (48 kHz DSP):</div>
          <div class="how-grid">
            <div class="how-step">
              <strong>1. 10.7ms Impulsive Crest Gate</strong>
              <span>Detects 2–12 ms mechanical/scissor switch transients (Peak/RMS ≥ {{ tConfig.crest_threshold ?? 3.85 }}) above ambient floor.</span>
            </div>
            <div class="how-step">
              <strong>2. 3.8–19.5 kHz Switch Click + Thock</strong>
              <span>Classifies <code>[ALPHA]</code>, <code>[SPACE/RET]</code>, and <code>[MOD/BKSP]</code> via spectral centroid while HPS F0 blanking rejects all human speech.</span>
            </div>
            <div class="how-step">
              <strong>3. Strict <code>PERSON_TYPIST</code> Isolation &amp; Desk Sector</strong>
              <span>Routes keystroke bursts ONLY to <code>PERSON_TYPIST</code> ({{ tConfig.desk_azimuth_deg ?? -8 }}°, {{ tConfig.desk_range_m ?? 0.68 }}m desk sector) with 5-tap zero-phase FIR pre-emphasis.</span>
            </div>
          </div>
        </div>

        <!-- 1-CLICK DESK SECTOR PRESETS & DIRECTIONAL HYSTERESIS LOCK -->
        <div class="desk-preset-bar mono">
          <div class="dp-top">
            <span style="color: #5eead4; font-weight: 700">📡 Desk Spatial Sector Presets (2D Radar Cone):</span>
            <label class="chk-lbl">
              <input
                type="checkbox"
                :checked="tConfig.spatial_sector_lock !== false"
                @change="pushConfig({ spatial_sector_lock: $event.target.checked })"
              />
              Cone Lock (±{{ tConfig.directional_hysteresis_deg ?? 22 }}°)
            </label>
          </div>
          <div class="dp-btns">
            <button
              v-for="pr in deskPresetButtons"
              :key="pr.id"
              type="button"
              class="dp-btn mono"
              :class="{ active: (tConfig.desk_sector_preset || 'CENTER_DESK') === pr.id }"
              @click="pushConfig({ desk_sector_preset: pr.id })"
            >
              {{ pr.label }} ({{ pr.sub }})
            </button>
          </div>
        </div>

        <!-- LIVE SLIDERS FOR MARKOV PROMOTION & TYPING DSP / DESK SECTOR -->
        <div class="sliders-grid mono">
          <div class="sl-item">
            <label class="chk-lbl" style="color: #d2a8ff">
              <input
                type="checkbox"
                :checked="mConfig.auto_promote_higher_order !== false"
                @change="pushConfig({ auto_promote_higher_order: $event.target.checked })"
              />
              Auto-Promote 2nd ➔ 3rd/4th Order
            </label>
            <span>Entropy Gate H ≤ {{ mConfig.promotion_entropy_max_bits ?? 1.65 }}b</span>
            <input
              type="range"
              min="0.40"
              max="2.60"
              step="0.05"
              :value="mConfig.promotion_entropy_max_bits ?? 1.65"
              @change="pushConfig({ promotion_entropy_max_bits: Number($event.target.value) })"
            />
          </div>
          <div class="sl-item">
            <label>Markov Hook Decay γ ({{ mConfig.decay_gamma ?? 0.988 }})</label>
            <input
              type="range"
              min="0.940"
              max="0.999"
              step="0.002"
              :value="mConfig.decay_gamma ?? 0.988"
              @change="pushConfig({ decay_gamma: Number($event.target.value) })"
            />
          </div>
          <div class="sl-item">
            <label>Keystroke Crest Gate ({{ tConfig.crest_threshold ?? 3.85 }})</label>
            <input
              type="range"
              min="2.60"
              max="6.00"
              step="0.05"
              :value="tConfig.crest_threshold ?? 3.85"
              @change="pushConfig({ crest_threshold: Number($event.target.value) })"
            />
          </div>
          <div class="sl-item">
            <label>3.8–19.5kHz Click Ratio ({{ tConfig.min_hf_click_ratio ?? 0.58 }})</label>
            <input
              type="range"
              min="0.30"
              max="1.40"
              step="0.02"
              :value="tConfig.min_hf_click_ratio ?? 0.58"
              @change="pushConfig({ min_hf_click_ratio: Number($event.target.value) })"
            />
          </div>
          <div class="sl-item">
            <label>⌨️ Desk Azimuth ({{ tConfig.desk_azimuth_deg ?? -8 }}°)</label>
            <input
              type="range"
              min="-75"
              max="75"
              step="1"
              :value="tConfig.desk_azimuth_deg ?? -8"
              @change="pushConfig({ desk_azimuth_deg: Number($event.target.value) })"
            />
          </div>
          <div class="sl-item">
            <label>⌨️ Desk Range ({{ tConfig.desk_range_m ?? 0.62 }}m) &amp; Hysteresis (±{{ tConfig.directional_hysteresis_deg ?? 22 }}°)</label>
            <input
              type="range"
              min="8"
              max="50"
              step="1"
              :value="tConfig.directional_hysteresis_deg ?? 22"
              @change="pushConfig({ directional_hysteresis_deg: Number($event.target.value) })"
              title="Directional Hysteresis Cone Half-Width (±degrees)"
            />
          </div>
        </div>

        <!-- RECENT PERSON_TYPIST BURSTS -->
        <div class="sp-hdr mono" style="margin-top: 4px">
          <span>📜 Captured <code>PERSON_TYPIST</code> Keystroke Bursts</span>
          <button
            type="button"
            class="link-btn mono"
            @click="$emit('select-speaker', 'PERSON_TYPIST')"
          >
            Open PERSON_TYPIST Dossier ➔
          </button>
        </div>

        <div class="burst-list">
          <div
            v-for="(b, idx) in typing.recent_bursts || []"
            :key="idx"
            class="burst-card mono"
          >
            <div class="bc-top">
              <strong style="color: #2dd4bf">⌨️ PERSON_TYPIST</strong>
              <span>{{ b.key_count }} keys · <strong>{{ b.wpm }} WPM</strong> ({{ b.kpm }} KPM)</span>
              <span>IKI {{ b.mean_iki_ms }}±{{ b.iki_std_ms }} ms</span>
              <span>{{ (b.timestamp_utc || '').slice(11, 19) }} UTC</span>
            </div>
            <div class="bc-classes">
              <span class="kc alpha">[ALPHA] ×{{ b.key_classes?.ALPHA ?? 0 }}</span>
              <span class="kc space">[SPACE/RET] ×{{ b.key_classes?.SPACE_RET ?? 0 }}</span>
              <span class="kc mod">[MOD/BKSP] ×{{ b.key_classes?.MOD_BKSP ?? 0 }}</span>
              <span v-if="b.z_vibro_score !== undefined" class="kc zvib">Z-Vibro {{ b.z_vibro_score }}</span>
              <span v-if="b.click_pop_ratio !== undefined" class="kc zvib">Click/Pop {{ b.click_pop_ratio }}×</span>
            </div>
            <div class="bc-seq">{{ (b.tokens || []).slice(0, 14).join(' ') }}</div>
          </div>

          <div v-if="!(typing.recent_bursts || []).length" class="empty-msg mono">
            Listening on 48 kHz UltraMic (3.8–19.5 kHz transient gate) for physical keyboard typing...
            Click <strong>⌨️ Capture Test Typing Burst</strong> above to test <code>PERSON_TYPIST</code> anytime!
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'

const props = defineProps({
  markovTyping: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['select-speaker', 'updated'])

const localStatus = ref(null)
const ollamaReport = ref(null)
const filterMode = ref('ALL')
const busySim = ref(false)
const busyOllama = ref(false)
const busyCfg = ref(false)
const bannerMsg = ref('')

const deskPresetButtons = [
  { id: 'LEFT_DESK', label: '↖ Left Desk', sub: '-32° · 0.68m' },
  { id: 'CENTER_DESK', label: '⬆ Center Desk', sub: '-8° · 0.62m' },
  { id: 'RIGHT_DESK', label: '↗ Right Desk', sub: '+28° · 0.70m' },
  { id: 'LAPTOP_NEAR', label: '💻 Near Laptop', sub: '0° · 0.46m' },
]

watch(
  () => props.markovTyping,
  (val) => {
    if (val && Object.keys(val).length) {
      localStatus.value = val
      if (val.last_ollama_advisor && !ollamaReport.value) {
        ollamaReport.value = val.last_ollama_advisor
      }
    }
  },
  { immediate: true, deep: true }
)

const statusObj = computed(() => localStatus.value || props.markovTyping || {})
const markov = computed(() => statusObj.value.markov || {})
const kpis = computed(() => markov.value.kpis || {})
const mConfig = computed(() => markov.value.config || {})
const typing = computed(() => statusObj.value.typing_person || {})
const tConfig = computed(() => typing.value.config || {})
const activations = computed(() => markov.value.sentence_activations || [])

const filteredActivations = computed(() => {
  if (filterMode.value === 'TYPIST') {
    return activations.value.filter((a) => a.speaker_id === 'PERSON_TYPIST')
  }
  if (filterMode.value === 'PROMOTED') {
    return activations.value.filter(
      (a) => (a.markov_order || 0) >= 3 || (a.promoted_this_sentence || []).length > 0
    )
  }
  if (filterMode.value === 'DELTA') {
    return activations.value.filter((a) =>
      ['EARWORM_DELTA_SHIFTED', 'EARWORM_DELTA_REINFORCED', 'CANDIDATE_HOOK_SEEDED'].includes(a.delta_outcome)
    )
  }
  return activations.value
})

function flash(msg) {
  bannerMsg.value = msg
  setTimeout(() => {
    if (bannerMsg.value === msg) bannerMsg.value = ''
  }, 5500)
}

function outcomeClass(outcome) {
  if (outcome === 'EARWORM_DELTA_SHIFTED') return 'out-shift'
  if (outcome === 'EARWORM_DELTA_REINFORCED') return 'out-lock'
  if (outcome === 'CANDIDATE_HOOK_SEEDED') return 'out-seed'
  if (outcome === 'TYPING_ISOLATED_EVENT') return 'out-typist'
  return 'out-passive'
}

function formatOutcome(act) {
  const o = act.delta_outcome
  if (o === 'EARWORM_DELTA_SHIFTED') return `🔥 Δ SHIFTED → "${act.earworm_delta_after}"`
  if (o === 'EARWORM_DELTA_REINFORCED') return `✅ Δ REINFORCED (×${act.hook_repeats})`
  if (o === 'CANDIDATE_HOOK_SEEDED') return `🌱 SEEDED "${act.sentence_hook}" (1×)`
  if (o === 'TYPING_ISOLATED_EVENT') return '⌨️ PERSON_TYPIST ISOLATED'
  return '📈 LEXICAL GRAPH STEP'
}

async function pushConfig(patch) {
  busyCfg.value = true
  try {
    const res = await fetch('/api/markov-typing/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
    if (res.ok) {
      const data = await res.json()
      if (data.status) localStatus.value = data.status
      flash(`Applied live config: ${(data.applied || []).join(', ')}`)
      emit('updated')
    }
  } catch (e) {
    console.error('Markov/Typing config error:', e)
  } finally {
    busyCfg.value = false
  }
}

async function applyRecommendedConfig(recCfg) {
  await pushConfig(recCfg)
}

async function simulateTypingBurst() {
  busySim.value = true
  try {
    const res = await fetch('/api/typing/simulate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pattern: 'ALPHA ALPHA ALPHA SPACE ALPHA ALPHA ALPHA ALPHA MOD ALPHA ALPHA ALPHA SPACE ALPHA ALPHA RET',
        wpm: 75,
      }),
    })
    if (res.ok) {
      const data = await res.json()
      if (data.status) localStatus.value = data.status
      flash('⌨️ Captured 48 kHz keystroke burst exclusively under PERSON_TYPIST!')
      emit('updated')
    }
  } catch (e) {
    console.error('Simulate typing error:', e)
  } finally {
    busySim.value = false
  }
}

async function askOllamaImprovements() {
  busyOllama.value = true
  try {
    const res = await fetch('/api/ollama/markov-typing', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force: true }),
    })
    if (res.ok) {
      ollamaReport.value = await res.json()
      flash('🧠 Received NightSweep Ollama improvements for Markov Earworm Δ & PERSON_TYPIST!')
    }
  } catch (e) {
    console.error('Ollama markov-typing error:', e)
  } finally {
    busyOllama.value = false
  }
}

onMounted(async () => {
  try {
    const res = await fetch('/api/markov-typing/status')
    if (res.ok) {
      const d = await res.json()
      localStatus.value = d
      if (d.last_ollama_advisor) ollamaReport.value = d.last_ollama_advisor
    }
  } catch (_) {}
})
</script>

<style scoped>
.mt-panel {
  background: #161b22;
  border: 1px solid rgba(45, 212, 191, 0.35);
  border-radius: 12px;
  padding: 16px 18px;
}
.panel-hdr {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.title-row {
  display: flex;
  align-items: center;
  gap: 9px;
  flex-wrap: wrap;
}
h2 {
  margin: 0;
  font-size: 1.02rem;
  color: #f0f6fc;
}
.sub {
  margin: 4px 0 0;
  font-size: 0.79rem;
  color: #8b949e;
}
.badge {
  font-size: 0.7rem;
  padding: 3px 9px;
  border-radius: 999px;
  font-weight: 600;
}
.badge-cyan {
  background: rgba(88, 166, 255, 0.14);
  color: #79c0ff;
  border: 1px solid rgba(88, 166, 255, 0.4);
}
.badge-typist {
  background: rgba(45, 212, 191, 0.15);
  color: #2dd4bf;
  border: 1px solid rgba(45, 212, 191, 0.55);
  cursor: pointer;
}
.hdr-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.btn {
  border-radius: 8px;
  padding: 7px 12px;
  font-size: 0.74rem;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid #30363d;
}
.btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.btn-typist {
  background: rgba(45, 212, 191, 0.16);
  border-color: rgba(45, 212, 191, 0.55);
  color: #5eead4;
}
.btn-ollama {
  background: rgba(210, 168, 255, 0.16);
  border-color: rgba(210, 168, 255, 0.55);
  color: #d2a8ff;
}
.btn-apply {
  background: #238636;
  border-color: #2ea043;
  color: #fff;
}

.kpi-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}
.kpi-card {
  background: #0d1117;
  border: 1px solid #21262d;
  border-radius: 9px;
  padding: 9px 12px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.typist-kpi {
  border-color: rgba(45, 212, 191, 0.4);
  cursor: pointer;
}
.promoted-kpi {
  border-color: rgba(210, 168, 255, 0.45);
}
.k-lbl {
  font-size: 0.67rem;
  color: #8b949e;
}
.k-val {
  font-size: 1.02rem;
  color: #f0f6fc;
}
.k-val.cyan {
  color: #58a6ff;
}
.k-val.green {
  color: #3fb950;
}
.k-val.teal {
  color: #2dd4bf;
}
.k-val.violet {
  color: #d2a8ff;
}
.k-sub {
  font-size: 0.69rem;
  color: #8b949e;
}

.banner {
  background: rgba(45, 212, 191, 0.12);
  border: 1px solid rgba(45, 212, 191, 0.45);
  color: #5eead4;
  border-radius: 7px;
  padding: 7px 11px;
  font-size: 0.75rem;
  margin-bottom: 12px;
}

.ollama-box {
  background: rgba(210, 168, 255, 0.07);
  border: 1px solid rgba(210, 168, 255, 0.38);
  border-radius: 9px;
  padding: 11px 14px;
  margin-bottom: 12px;
}
.ob-hdr {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.ob-tag {
  margin-left: 8px;
  font-size: 0.7rem;
  color: #d2a8ff;
}
.ob-summary {
  margin: 7px 0;
  font-size: 0.81rem;
  color: #e6edf3;
}
.ob-cols {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  font-size: 0.77rem;
  color: #c9d1d9;
}
.ob-sub {
  font-size: 0.72rem;
  color: #79c0ff;
  font-weight: 700;
  margin-bottom: 4px;
}
.ollama-box ul {
  margin: 0;
  padding-left: 18px;
}
.ollama-box li {
  margin-bottom: 4px;
}

.main-cols {
  display: grid;
  grid-template-columns: 1.25fr 1fr;
  gap: 14px;
}
@media (max-width: 1060px) {
  .main-cols,
  .ob-cols {
    grid-template-columns: 1fr;
  }
}
.sub-panel {
  background: #0d1117;
  border: 1px solid #21262d;
  border-radius: 9px;
  padding: 11px 12px;
  display: flex;
  flex-direction: column;
  gap: 9px;
}
.typist-panel {
  border-color: rgba(45, 212, 191, 0.3);
}
.sp-hdr {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 0.76rem;
  font-weight: 700;
  color: #e6edf3;
}
.filter-pills {
  display: flex;
  gap: 4px;
}
.f-pill {
  background: #161b22;
  color: #8b949e;
  border: 1px solid #30363d;
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 0.68rem;
  cursor: pointer;
}
.f-pill.active {
  background: rgba(88, 166, 255, 0.18);
  color: #58a6ff;
  border-color: #58a6ff;
}

.hook-leaderboard {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 0.7rem;
}
.hl-lbl {
  color: #8b949e;
}
.hl-chip {
  background: #161b22;
  border: 1px solid #30363d;
  color: #c9d1d9;
  padding: 2px 7px;
  border-radius: 999px;
}
.hl-chip.winner {
  border-color: #3fb950;
  color: #7ee787;
  background: rgba(46, 160, 67, 0.14);
}

.act-feed,
.burst-list {
  max-height: 330px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.act-card {
  background: #161b22;
  border: 1px solid #21262d;
  border-left: 3px solid #58a6ff;
  border-radius: 8px;
  padding: 8px 10px;
}
.act-card.shifted {
  border-left-color: #f0883e;
  background: rgba(240, 136, 62, 0.08);
}
.act-card.reinforced {
  border-left-color: #3fb950;
}
.act-card.promoted {
  border-left-color: #d2a8ff;
  background: rgba(210, 168, 255, 0.06);
}
.act-card.typist {
  border-left-color: #2dd4bf;
  background: rgba(45, 212, 191, 0.06);
}
.promoted-bar {
  background: rgba(210, 168, 255, 0.07);
  border: 1px solid rgba(210, 168, 255, 0.28);
  border-radius: 7px;
  padding: 4px 8px;
}
.violet-txt {
  color: #d2a8ff;
  font-weight: 700;
}
.promoted-chip {
  border-color: rgba(210, 168, 255, 0.45);
  color: #e2c5ff;
}
.promo-callout {
  font-size: 0.69rem;
  color: #d2a8ff;
  background: rgba(210, 168, 255, 0.11);
  border: 1px solid rgba(210, 168, 255, 0.35);
  border-radius: 5px;
  padding: 2px 7px;
  margin-bottom: 4px;
}
.model-tag.high {
  color: #f0c6ff;
  font-weight: 700;
}
.ac-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 0.69rem;
}
.ac-left {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.spk-pill {
  background: rgba(88, 166, 255, 0.14);
  border: 1px solid rgba(88, 166, 255, 0.45);
  color: #58a6ff;
  border-radius: 999px;
  padding: 1px 7px;
  font-size: 0.68rem;
  cursor: pointer;
}
.spk-pill.typist {
  background: rgba(45, 212, 191, 0.16);
  border-color: rgba(45, 212, 191, 0.55);
  color: #2dd4bf;
}
.model-tag {
  color: #d2a8ff;
}
.ent-tag {
  color: #8b949e;
}
.outcome-pill {
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 0.67rem;
  font-weight: 700;
}
.out-shift {
  background: rgba(240, 136, 62, 0.22);
  color: #ffa657;
}
.out-lock {
  background: rgba(63, 185, 80, 0.2);
  color: #7ee787;
}
.out-seed {
  background: rgba(88, 166, 255, 0.16);
  color: #79c0ff;
}
.out-typist {
  background: rgba(45, 212, 191, 0.2);
  color: #5eead4;
}
.out-passive {
  background: #21262d;
  color: #8b949e;
}
.ac-sentence {
  font-size: 0.82rem;
  color: #f0f6fc;
  margin: 4px 0;
}
.ac-contour {
  font-size: 0.69rem;
  color: #8b949e;
  margin-bottom: 3px;
}
.ac-contour span {
  color: #79c0ff;
}
.edges-row,
.preds-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 0.68rem;
  margin-top: 3px;
}
.e-lbl {
  color: #8b949e;
  margin-right: 4px;
}
.edge-chip {
  background: #0d1117;
  border: 1px solid #30363d;
  color: #c9d1d9;
  padding: 1px 6px;
  border-radius: 5px;
}
.pred-chip {
  background: rgba(63, 185, 80, 0.12);
  border: 1px solid rgba(63, 185, 80, 0.35);
  color: #7ee787;
  padding: 1px 6px;
  border-radius: 5px;
  margin-right: 4px;
}
.delta-trans {
  color: #ffa657;
}

.how-box {
  background: #161b22;
  border: 1px solid #21262d;
  border-radius: 8px;
  padding: 8px 10px;
}
.how-title {
  font-size: 0.71rem;
  color: #5eead4;
  font-weight: 700;
  margin-bottom: 6px;
}
.how-grid {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.how-step {
  font-size: 0.7rem;
  color: #c9d1d9;
  display: flex;
  flex-direction: column;
}
.how-step span {
  color: #8b949e;
}

.sliders-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  background: #161b22;
  border: 1px solid #21262d;
  border-radius: 8px;
  padding: 8px 10px;
}
.sl-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 0.68rem;
  color: #8b949e;
}
.chk-lbl {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 0.71rem;
  color: #5eead4;
  cursor: pointer;
}
.link-btn {
  background: transparent;
  border: none;
  color: #2dd4bf;
  cursor: pointer;
  font-size: 0.71rem;
}

.burst-card {
  background: #161b22;
  border: 1px solid rgba(45, 212, 191, 0.32);
  border-radius: 7px;
  padding: 7px 9px;
  font-size: 0.7rem;
}
.bc-top {
  display: flex;
  justify-content: space-between;
  gap: 6px;
  flex-wrap: wrap;
  color: #c9d1d9;
  margin-bottom: 4px;
}
.bc-classes {
  display: flex;
  gap: 6px;
  margin-bottom: 4px;
}
.kc {
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 0.66rem;
}
.kc.alpha {
  background: rgba(45, 212, 191, 0.15);
  color: #5eead4;
}
.kc.space {
  background: rgba(88, 166, 255, 0.15);
  color: #79c0ff;
}
.kc.mod {
  background: rgba(210, 168, 255, 0.15);
  color: #d2a8ff;
}
.kc.zvib {
  background: rgba(240, 136, 62, 0.16);
  color: #ffa657;
}
.desk-preset-bar {
  background: rgba(45, 212, 191, 0.06);
  border: 1px solid rgba(45, 212, 191, 0.28);
  border-radius: 7px;
  padding: 7px 9px;
  font-size: 0.7rem;
}
.dp-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.dp-btns {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
}
.dp-btn {
  background: #161b22;
  border: 1px solid rgba(45, 212, 191, 0.35);
  color: #c9d1d9;
  border-radius: 6px;
  padding: 3px 8px;
  font-size: 0.67rem;
  cursor: pointer;
}
.dp-btn.active {
  background: rgba(45, 212, 191, 0.22);
  border-color: #2dd4bf;
  color: #5eead4;
  font-weight: 700;
}
.bc-seq {
  color: #8b949e;
  font-size: 0.67rem;
}
.empty-msg {
  color: #8b949e;
  font-size: 0.74rem;
  padding: 10px 4px;
}
</style>
