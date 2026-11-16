<template>
  <section id="delta-avatar-studio" class="card da-card">
    <!-- HEADER -->
    <div class="da-header">
      <div class="da-head-left">
        <div class="da-title-row">
          <h2 class="da-title">
            🧘 PERSON_DELTA 0.5–4.0 Hz Brainwave Avatar · 🚶 VAD Motion Earworm Associator &amp; 📊 Feelings × Predictability × Movement
          </h2>
          <span class="pill mono delta-pill">
            🌊 Delta {{ deltaWave.peak_hz ?? 1.55 }} Hz ({{ deltaWave.band_lo_hz ?? 0.5 }}–{{ deltaWave.band_hi_hz ?? 4.0 }} Hz) · {{ deltaWave.emotional_reset_pct ?? 76 }}% Reset
          </span>
          <span class="pill mono delta-pill" style="border-color: rgba(88, 166, 255, 0.45); color: #79c0ff">
            🎧 Module 4 Synth: L={{ (statusData.integrated_entrainment?.freq_left_hz ?? 208.8).toFixed(1) }} Hz · R={{ (statusData.integrated_entrainment?.freq_right_hz ?? 211.2).toFixed(1) }} Hz · LFO m={{ statusData.integrated_entrainment?.mod_depth ?? 0.4 }}
          </span>
          <span class="pill mono motion-pill" :class="movementBadgeClass(vadMotion.movement_state)">
            {{ movementIcon(vadMotion.movement_state) }} {{ vadMotion.movement_state || 'STILL_ANCHORED' }} · VAD Motion {{ Math.round((vadMotion.vad_motion_score || 0) * 100) }}%
            <template v-if="(vadMotion.kinetic_hangover_bonus_ms || 0) > 0">
              (+{{ Math.round(vadMotion.kinetic_hangover_bonus_ms) }}ms)
            </template>
          </span>
        </div>
        <div class="da-sub">
          <strong>Delta brainwaves (0.5–4.0 Hz)</strong> are the slowest oscillations linked to emotional stability, stress recovery, subconscious processing, and resetting emotional control centers.
          Co-gates <span class="mono">BiometricFusedVAD</span> with spatial <strong>VAD Motion</strong>, binds every captured <strong>Earworm &amp; Whisper</strong> to live movement regimes, and cross-correlates
          <strong style="color: #3fb950">Feelings</strong> × <strong style="color: #58a6ff">Predictability</strong> × <strong style="color: #f0883e">Movement</strong>.
        </div>
      </div>

      <div class="da-hdr-actions">
        <button
          type="button"
          class="btn btn-ollama mono"
          :disabled="ollamaBusy"
          @click="consultOllama(true)"
        >
          {{ ollamaBusy ? '🧠 Consulting Ollama Modal…' : '🧠 Ask Ollama Modal for Reference & Improvements' }}
        </button>
        <button
          v-if="ollamaAdvice?.recommended_config"
          type="button"
          class="btn btn-apply mono"
          :disabled="configBusy"
          @click="applyOllamaConfig"
        >
          ⚡ Apply Recommended Config (Motion {{ Math.round((ollamaAdvice.recommended_config.vad_motion_weight || 0.26) * 100) }}% · +{{ Math.round(ollamaAdvice.recommended_config.kinetic_hangover_bonus_ms || 80) }}ms)
        </button>
      </div>
    </div>

    <div v-if="bannerMsg" class="da-banner mono">
      ✅ {{ bannerMsg }}
    </div>

    <!-- NIGHTSWEEP OLLAMA MODAL ADVISOR DRAWER (MATCHING REFERENCE ARCHITECTURE) -->
    <div v-if="ollamaAdvice" class="ollama-drawer">
      <div class="od-top">
        <span class="mono od-badge">
          🧠 {{ ollamaAdvice.model || 'nightsweep-signalintelligence:latest' }}
          <strong v-if="ollamaAdvice.ollama_live" style="color: #7ee787"> · LIVE MODAL</strong>
        </span>
        <span class="mono od-ts">{{ ollamaAdvice.generated_at_utc }}</span>
      </div>
      <p class="od-summary">{{ ollamaAdvice.overall_assessment }}</p>
      <div class="od-cols">
        <div class="od-col">
          <div class="od-col-hdr mono">🚶 VAD Motion &amp; Earworm-to-Movement</div>
          <ul>
            <li v-for="(it, idx) in (ollamaAdvice.vad_motion_earworm_advice || []).slice(0, 3)" :key="'vm-' + idx">
              {{ it }}
            </li>
          </ul>
        </div>
        <div class="od-col">
          <div class="od-col-hdr mono">🧘 0.5–4.0 Hz Delta Emotional Control Reset</div>
          <ul>
            <li v-for="(it, idx) in (ollamaAdvice.delta_brainwave_feelings_advice || []).slice(0, 3)" :key="'db-' + idx">
              {{ it }}
            </li>
          </ul>
        </div>
        <div class="od-col">
          <div class="od-col-hdr mono">📊 Feelings × Predictability × Movement</div>
          <ul>
            <li v-for="(it, idx) in (ollamaAdvice.cross_correlation_insights || []).slice(0, 3)" :key="'cc-' + idx">
              {{ it }}
            </li>
          </ul>
        </div>
      </div>
    </div>

    <!-- 3-COLUMN RESPONSIVE WORKBENCH -->
    <div class="da-grid">
      <!-- COLUMN 1: INTERACTIVE 0.5-4.0 HZ DELTA AVATAR + EARWORM & WHISPER BINDING -->
      <div class="da-panel">
        <div class="panel-hdr">
          <span class="mono panel-title">🧘 1. Interactive Delta Brainwave Avatar (0.5–4.0 Hz)</span>
          <button
            type="button"
            class="mini-btn mono"
            @click="$emit('select-speaker', activeAvatar.speaker_id || 'PERSON_DELTA')"
            title="Open full Shared Earworm & Biometric Dossier Modal"
          >
            🔍 Dossier Modal
          </button>
        </div>

        <!-- Speaker Avatar Tabs -->
        <div class="avatar-tabs">
          <button
            v-for="av in avatarList"
            :key="av.speaker_id"
            type="button"
            class="av-tab mono"
            :class="{ active: av.speaker_id === activeAvatar.speaker_id }"
            :style="av.speaker_id === activeAvatar.speaker_id ? { borderColor: av.color || '#f0883e', color: av.color || '#f0883e' } : {}"
            @click="selectPrimaryAvatar(av.speaker_id)"
          >
            <span class="av-dot" :style="{ background: av.color || '#f0883e' }"></span>
            {{ av.speaker_id }}
            <span class="av-mini-pct">{{ Math.round(av.emotional_reset_pct || 72) }}%</span>
          </button>
        </div>

        <!-- Animated SVG Delta Brainwave + Emotional Control Reset + Movement Vector Avatar -->
        <div class="avatar-stage">
          <svg viewBox="0 0 280 206" class="avatar-svg" role="img" aria-label="Delta Brainwave & Movement Avatar">
            <defs>
              <radialGradient id="deltaCoreGrad" cx="50%" cy="48%" r="52%">
                <stop offset="0%" :stop-color="activeAvatar.color || '#f0883e'" stop-opacity="0.45" />
                <stop offset="65%" stop-color="#3fb950" stop-opacity="0.16" />
                <stop offset="100%" stop-color="#0d131f" stop-opacity="0" />
              </radialGradient>
            </defs>

            <!-- Concentric 0.5-4.0 Hz Delta Brainwave Reset Rings -->
            <circle
              cx="140"
              cy="98"
              r="78"
              class="delta-ring outer"
              :style="{ animationDuration: pulsePeriodSec, stroke: activeAvatar.color || '#f0883e' }"
            />
            <circle
              cx="140"
              cy="98"
              r="58"
              class="delta-ring mid"
              :style="{ animationDuration: pulsePeriodSec }"
            />
            <circle cx="140" cy="98" r="50" fill="url(#deltaCoreGrad)" />

            <!-- Emotional Reset Arc Gauge -->
            <circle
              cx="140"
              cy="98"
              r="42"
              fill="none"
              stroke="rgba(63, 185, 80, 0.18)"
              stroke-width="5"
            />
            <circle
              cx="140"
              cy="98"
              r="42"
              fill="none"
              stroke="#3fb950"
              stroke-width="5"
              stroke-linecap="round"
              :stroke-dasharray="`${Math.round(((activeAvatar.emotional_reset_pct || 74) / 100) * 264)} 264`"
              transform="rotate(-90 140 98)"
            />

            <!-- Stylized Head + Emotional Control Center Node -->
            <circle
              cx="140"
              cy="88"
              r="20"
              fill="#111a2b"
              :stroke="activeAvatar.color || '#f0883e'"
              stroke-width="2.2"
            />
            <!-- Subconscious / Limbic Reset Glow -->
            <circle
              cx="140"
              cy="84"
              :r="5 + (deltaWave.power_ratio || 0.58) * 5"
              fill="#7ee787"
              opacity="0.82"
            />
            <!-- Shoulders -->
            <path
              d="M 108 126 Q 140 108 172 126"
              fill="none"
              :stroke="activeAvatar.color || '#f0883e'"
              stroke-width="2.5"
              stroke-linecap="round"
            />

            <!-- Live Movement Vector Arrow -->
            <g :transform="`translate(140, 98) rotate(${movementArrowDeg})`">
              <line
                x1="0"
                y1="-46"
                x2="0"
                :y2="-46 - movementArrowLen"
                stroke="#ffa657"
                stroke-width="2.6"
                stroke-linecap="round"
              />
              <polygon
                v-if="movementArrowLen > 4"
                :points="`0,${-52 - movementArrowLen} -5,${-44 - movementArrowLen} 5,${-44 - movementArrowLen}`"
                fill="#ffa657"
              />
            </g>

            <!-- Top & Bottom SVG Telemetry Labels -->
            <text x="14" y="18" class="svg-lbl mono" fill="#7ee787">
              {{ activeAvatar.dominant_feeling || deltaWave.dominant_feeling || 'CALM_COHERENT_RESET' }}
            </text>
            <text x="266" y="18" text-anchor="end" class="svg-lbl mono" fill="#79c0ff">
              {{ activeAvatar.delta_peak_hz ?? deltaWave.peak_hz ?? 1.55 }} Hz Delta
            </text>
            <text x="140" y="168" text-anchor="middle" class="svg-sub mono" fill="#e6edf3">
              Emotional Control Reset: {{ activeAvatar.emotional_reset_pct ?? 76 }}% · Whisper {{ activeAvatar.whisper_pct ?? 80 }}%
            </text>
            <text x="140" y="186" text-anchor="middle" class="svg-sub mono" fill="#9ecbff">
              {{ activeAvatar.movement_state || 'STILL_ANCHORED' }} · {{ activeAvatar.range_m ?? 0.72 }}m ({{ formatAz(activeAvatar.azimuth_deg) }}) · vR={{ activeAvatar.radial_vel_cms ?? 0 }}cm/s · vAz={{ activeAvatar.azimuth_vel_degs ?? 0 }}°/s
            </text>
          </svg>
        </div>

        <!-- Associated Earworm & Whisper Bubble -->
        <div class="assoc-bubble">
          <div class="ab-top mono">
            <span class="ab-tag">🎶 ASSOCIATED EARWORM &amp; WHISPER</span>
            <span class="ab-contour">{{ activeAvatar.whisper_contour || 'EE-AH-OO' }} · {{ activeAvatar.earworm_bpm ?? 110 }} BPM</span>
          </div>
          <div class="ab-phrase">
            "{{ activeAvatar.active_earworm || 'steady delta reset whisper' }}"
            <span class="ab-next mono">→ {{ activeAvatar.predicted_next_word || 'calm' }}</span>
          </div>
          <div class="ab-scores mono">
            <span style="color: #3fb950">💚 Feelings {{ Math.round((activeAvatar.feelings_score ?? 0.76) * 100) }}%</span>
            <span style="color: #58a6ff">🔮 Predictability {{ Math.round((activeAvatar.predictability_score ?? 0.72) * 100) }}%</span>
            <span style="color: #f0883e">🚶 Movement {{ Math.round((activeAvatar.movement_score ?? 0.16) * 100) }}%</span>
          </div>
        </div>

        <!-- Binaural 0.5-4.0 Hz Delta + VTL Whisper Audio Mirror -->
        <div class="audio-box">
          <div class="audio-top">
            <span class="mono audio-lbl">🔊 0.5–4 Hz Binaural Delta + Whisper WAV:</span>
            <button type="button" class="mini-btn play-btn mono" @click="playAvatarWav()">
              ▶ Audition Reset + Whisper
            </button>
          </div>
          <audio
            v-if="currentWavUrl"
            :key="currentWavUrl"
            :src="currentWavUrl"
            controls
            autoplay
            preload="metadata"
            class="wav-player"
          ></audio>
        </div>

        <!-- 3 Interactive Simulation Probes -->
        <div class="probe-strip">
          <button
            type="button"
            class="btn probe-btn mono"
            :disabled="simBusy"
            @click="runProbe('DELTA_CALM_WHISPER')"
            title="Simulate Deep 1.15 Hz Delta Emotional Control Reset + Anchored Whisper"
          >
            🧘 Delta Calm Whisper
          </button>
          <button
            type="button"
            class="btn probe-btn mono"
            :disabled="simBusy"
            @click="runProbe('PACING_EARWORM')"
            title="Simulate Lateral Pacing Motor-Entrained Earworm Loop"
          >
            🚶 Pacing Earworm
          </button>
          <button
            type="button"
            class="btn probe-btn mono"
            :disabled="simBusy"
            @click="runProbe('APPROACHING_SUBVOC')"
            title="Simulate Approaching Low-Ambient Subvocalization + VAD Motion Boost"
          >
            🎯 Approaching Subvoc
          </button>
        </div>
      </div>

      <!-- COLUMN 2: 0.5-4.0 HZ DELTA OSCILLOSCOPE & 3-WAY CROSS-CORRELATION MATRIX -->
      <div class="da-panel">
        <div class="panel-hdr">
          <span class="mono panel-title">📊 2. 0.5–4.0 Hz Delta Wave &amp; Feelings × Predictability × Movement</span>
          <span class="mono sub-pill">Window: {{ crossCorr.window_samples ?? 28 }} pts</span>
        </div>

        <!-- Top SVG: 0.5-4.0 Hz Slow Delta Brainwave Envelope -->
        <div class="scope-card">
          <div class="scope-hdr mono">
            <span style="color: #7ee787">🌊 Live 0.5–4.0 Hz Delta Brainwave Envelope</span>
            <span>
              Deep Reset (0.5–1.5 Hz): <strong>{{ Math.round((deltaWave.deep_reset_ratio ?? 0.38) * 100) }}%</strong> ·
              Total Delta: <strong>{{ Math.round((deltaWave.power_ratio ?? 0.6) * 100) }}%</strong>
            </span>
          </div>
          <svg viewBox="0 0 360 74" class="scope-svg" preserveAspectRatio="none">
            <line x1="0" y1="37" x2="360" y2="37" stroke="rgba(139, 148, 158, 0.22)" stroke-dasharray="3 3" />
            <polyline
              :points="deltaWaveformPoints"
              fill="none"
              stroke="#3fb950"
              stroke-width="2.3"
              stroke-linejoin="round"
            />
          </svg>
        </div>

        <!-- Bottom SVG: Overlaid Rolling Time-Series (Feelings, Predictability, Movement) -->
        <div class="scope-card">
          <div class="scope-hdr mono">
            <span>📈 Synchronized Neuro-Behavioral Trajectories</span>
            <span class="legend-inline">
              <i style="background: #3fb950"></i>Feelings
              <i style="background: #58a6ff"></i>Predictability
              <i style="background: #f0883e"></i>Movement
            </span>
          </div>
          <svg viewBox="0 0 360 92" class="scope-svg" preserveAspectRatio="none">
            <line x1="0" y1="23" x2="360" y2="23" stroke="rgba(139, 148, 158, 0.14)" />
            <line x1="0" y1="46" x2="360" y2="46" stroke="rgba(139, 148, 158, 0.2)" stroke-dasharray="3 3" />
            <line x1="0" y1="69" x2="360" y2="69" stroke="rgba(139, 148, 158, 0.14)" />
            <polyline :points="seriesPoints(timeSeries.feelings, 92)" fill="none" stroke="#3fb950" stroke-width="2.1" />
            <polyline :points="seriesPoints(timeSeries.predictability, 92)" fill="none" stroke="#58a6ff" stroke-width="2.0" />
            <polyline :points="seriesPoints(timeSeries.movement, 92)" fill="none" stroke="#f0883e" stroke-width="1.9" stroke-dasharray="4 2" />
          </svg>
        </div>

        <!-- 3 Pairwise Pearson + Lead/Lag Cross-Correlation Gauges -->
        <div class="corr-list">
          <div v-for="pair in correlationPairs" :key="pair.key" class="corr-row">
            <div class="corr-top mono">
              <span class="corr-label">{{ pair.label }}</span>
              <span :style="{ color: corrColor(pair.stats.r) }">
                r = {{ formatSigned(pair.stats.r) }}
                <small class="muted">(peak {{ formatSigned(pair.stats.peak_r) }} @ lag {{ pair.stats.best_lag ?? 0 }})</small>
              </span>
            </div>
            <div class="corr-bar-track">
              <div class="corr-zero"></div>
              <div
                class="corr-bar-fill"
                :style="corrBarStyle(pair.stats.r)"
              ></div>
            </div>
            <div class="corr-foot mono">
              <span class="muted">{{ pair.leftHint }}</span>
              <span class="corr-strength">{{ pair.stats.strength || 'BALANCED' }}</span>
              <span class="muted">{{ pair.rightHint }}</span>
            </div>
          </div>
        </div>

        <!-- Live Cross-Correlation Neuro-Behavioral Synthesis -->
        <ul class="interp-list">
          <li v-for="(line, idx) in (crossCorr.interpretations || [])" :key="'in-' + idx">
            {{ line }}
          </li>
        </ul>
      </div>

      <!-- COLUMN 3: MOVEMENT REGIME EARWORM MAP + ASSOCIATION FEED + VAD MOTION TUNING -->
      <div class="da-panel">
        <div class="panel-hdr">
          <span class="mono panel-title">🚶 3. Earworm ↔ Movement Regimes &amp; VAD Motion Gate</span>
          <span class="mono sub-pill">{{ recentAssociations.length }} linked</span>
        </div>

        <!-- 5 Movement Regimes Affinity Strip -->
        <div class="regime-grid">
          <div
            v-for="reg in movementRegimes"
            :key="reg.movement_state"
            class="regime-chip"
            :class="{ active: reg.movement_state === vadMotion.movement_state }"
          >
            <div class="reg-top mono">
              <span>{{ movementIcon(reg.movement_state) }} {{ shortRegime(reg.movement_state) }}</span>
              <strong>×{{ reg.count }}</strong>
            </div>
            <div class="reg-hook" :title="reg.top_earworm">
              {{ reg.top_earworm !== '--' ? `"${reg.top_earworm}"` : 'Awaiting motion hook' }}
            </div>
          </div>
        </div>

        <!-- Scrollable Recent Earworm + Whisper <-> Movement Associations -->
        <div class="assoc-feed-hdr mono">🔗 Live Earworm &amp; Whisper → Movement Ledger</div>
        <div class="assoc-feed">
          <div v-if="!recentAssociations.length" class="empty-feed mono">
            Click a probe button or speak/whisper into UltraMic to log Earworm ↔ Movement associations.
          </div>
          <div
            v-for="item in recentAssociations.slice(0, 8)"
            :key="item.id"
            class="assoc-item"
          >
            <div class="ai-top mono">
              <button
                type="button"
                class="spk-link mono"
                @click="$emit('select-speaker', { speakerId: item.speaker_id, phrase: item.earworm_phrase })"
              >
                🎧 {{ item.speaker_id }}
              </button>
              <span class="mov-tag" :class="movementBadgeClass(item.movement_state)">
                {{ movementIcon(item.movement_state) }} {{ shortRegime(item.movement_state) }}
              </span>
              <span class="muted">{{ item.delta_peak_hz }} Hz · {{ Math.round(item.emotional_reset_pct || 72) }}%</span>
              <button
                type="button"
                class="mini-play mono"
                title="Audition this associated Delta + Whisper WAV"
                @click="playAvatarWav(item.speaker_id, item.earworm_phrase)"
              >
                ▶
              </button>
            </div>
            <div class="ai-phrase">
              "{{ item.earworm_phrase }}"
              <span class="mono muted">({{ item.whisper_contour }} · → {{ item.predicted_next_word }})</span>
            </div>
            <div class="ai-metrics mono">
              <span style="color: #3fb950">F:{{ Math.round((item.feelings_score || 0) * 100) }}%</span>
              <span style="color: #58a6ff">P:{{ Math.round((item.predictability_score || 0) * 100) }}%</span>
              <span style="color: #f0883e">M:{{ Math.round((item.movement_score || 0) * 100) }}%</span>
              <span>vR:{{ item.radial_vel_cms }}cm/s</span>
              <span>{{ (item.timestamp_utc || '').slice(11, 19) }}Z</span>
            </div>
          </div>
        </div>

        <!-- Compact VAD Motion & Delta Band Live Controls -->
        <div class="tuning-box">
          <div class="tuning-hdr mono">⚙️ VAD Motion &amp; 0.5–4 Hz Delta Tuning</div>
          <div class="tuning-grid mono">
            <label>
              <span>VAD Motion Weight ({{ Math.round(localCfg.vad_motion_weight * 100) }}%)</span>
              <input v-model.number="localCfg.vad_motion_weight" type="range" min="0" max="0.55" step="0.02" @change="saveTuning" />
            </label>
            <label>
              <span>Motion Vel Gate ({{ localCfg.motion_vel_thresh_cms }} cm/s)</span>
              <input v-model.number="localCfg.motion_vel_thresh_cms" type="range" min="2" max="15" step="0.5" @change="saveTuning" />
            </label>
            <label>
              <span>Kinetic Hangover (+{{ localCfg.kinetic_hangover_bonus_ms }} ms)</span>
              <input v-model.number="localCfg.kinetic_hangover_bonus_ms" type="range" min="0" max="180" step="10" @change="saveTuning" />
            </label>
            <label>
              <span>Delta Drone Mix ({{ Math.round(localCfg.delta_drone_mix * 100) }}%)</span>
              <input v-model.number="localCfg.delta_drone_mix" type="range" min="0.1" max="0.8" step="0.05" @change="saveTuning" />
            </label>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'

const props = defineProps({
  data: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['select-speaker', 'updated'])

const ollamaBusy = ref(false)
const configBusy = ref(false)
const simBusy = ref(false)
const ollamaAdvice = ref(null)
const bannerMsg = ref('')
const currentWavUrl = ref('')

const localCfg = reactive({
  vad_motion_weight: 0.24,
  motion_vel_thresh_cms: 4.5,
  kinetic_hangover_bonus_ms: 75,
  delta_drone_mix: 0.38,
})

watch(
  () => props.data?.config,
  (cfg) => {
    if (!cfg) return
    if (cfg.vad_motion_weight !== undefined) localCfg.vad_motion_weight = Number(cfg.vad_motion_weight)
    if (cfg.motion_vel_thresh_cms !== undefined) localCfg.motion_vel_thresh_cms = Number(cfg.motion_vel_thresh_cms)
    if (cfg.kinetic_hangover_bonus_ms !== undefined) localCfg.kinetic_hangover_bonus_ms = Number(cfg.kinetic_hangover_bonus_ms)
    if (cfg.delta_drone_mix !== undefined) localCfg.delta_drone_mix = Number(cfg.delta_drone_mix)
  },
  { immediate: true, deep: true }
)

const deltaWave = computed(() => props.data?.delta_wave || {})
const vadMotion = computed(() => props.data?.vad_motion || {})
const crossCorr = computed(() => props.data?.cross_correlations || {})
const timeSeries = computed(() => props.data?.time_series || {})
const avatarList = computed(() => {
  const list = props.data?.avatars || []
  return list.length ? list : [{ speaker_id: 'PERSON_DELTA', color: '#f0883e', emotional_reset_pct: 76 }]
})
const activeAvatar = computed(() => props.data?.primary_avatar || avatarList.value[0] || {})
const recentAssociations = computed(() => props.data?.recent_associations || [])
const movementRegimes = computed(() => {
  const list = props.data?.movement_regime_earworms || []
  if (list.length) return list
  return [
    { movement_state: 'STILL_ANCHORED', count: 0, top_earworm: '--' },
    { movement_state: 'MICRO_SWAY', count: 0, top_earworm: '--' },
    { movement_state: 'APPROACHING', count: 0, top_earworm: '--' },
    { movement_state: 'RETREATING', count: 0, top_earworm: '--' },
    { movement_state: 'LATERAL_PACING', count: 0, top_earworm: '--' },
  ]
})

const pulsePeriodSec = computed(() => {
  const hz = Math.min(4.0, Math.max(0.5, Number(activeAvatar.value?.delta_peak_hz || deltaWave.value?.peak_hz || 1.55)))
  return `${(1.0 / hz).toFixed(2)}s`
})

const movementArrowDeg = computed(() => {
  const st = activeAvatar.value?.movement_state || vadMotion.value?.movement_state || 'STILL_ANCHORED'
  if (st === 'APPROACHING') return 180
  if (st === 'RETREATING') return 0
  if (st === 'LATERAL_PACING') return (Number(activeAvatar.value?.azimuth_vel_degs || 0) >= 0 ? 90 : -90)
  if (st === 'MICRO_SWAY') return 45
  return 0
})

const movementArrowLen = computed(() => {
  const m = Number(activeAvatar.value?.movement_score ?? vadMotion.value?.vad_motion_score ?? 0.12)
  const st = activeAvatar.value?.movement_state || vadMotion.value?.movement_state || 'STILL_ANCHORED'
  if (st === 'STILL_ANCHORED') return 0
  return Math.min(26, Math.max(8, Math.round(m * 32)))
})

const deltaWaveformPoints = computed(() => {
  const arr = deltaWave.value?.waveform_64 || []
  if (!arr.length) return '0,37 360,37'
  const n = arr.length
  return arr
    .map((v, i) => {
      const x = ((i / Math.max(1, n - 1)) * 360).toFixed(1)
      const y = (37 - Math.max(-1, Math.min(1, Number(v) || 0)) * 29).toFixed(1)
      return `${x},${y}`
    })
    .join(' ')
})

const correlationPairs = computed(() => [
  {
    key: 'fp',
    label: '💚 Feelings × 🔮 Predictability',
    stats: crossCorr.value?.feelings_vs_predictability || { r: 0, peak_r: 0, best_lag: 0, strength: 'STEADY' },
    leftHint: '-1 Novelty Shift',
    rightHint: '+1 Coherent Loop',
  },
  {
    key: 'fm',
    label: '💚 Feelings × 🚶 Movement',
    stats: crossCorr.value?.feelings_vs_movement || { r: 0, peak_r: 0, best_lag: 0, strength: 'STEADY' },
    leftHint: '-1 Stillness Reset',
    rightHint: '+1 Kinetic Release',
  },
  {
    key: 'pm',
    label: '🔮 Predictability × 🚶 Movement',
    stats: crossCorr.value?.predictability_vs_movement || { r: 0, peak_r: 0, best_lag: 0, strength: 'STEADY' },
    leftHint: '-1 Anchored Whisper',
    rightHint: '+1 Pacing Earworm',
  },
])

function seriesPoints(arr, height = 92) {
  const list = Array.isArray(arr) && arr.length ? arr : [0.5, 0.5]
  const n = list.length
  const pad = 8
  const usable = height - pad * 2
  return list
    .map((v, i) => {
      const x = ((i / Math.max(1, n - 1)) * 360).toFixed(1)
      const clamped = Math.max(0, Math.min(1, Number(v) || 0))
      const y = (height - pad - clamped * usable).toFixed(1)
      return `${x},${y}`
    })
    .join(' ')
}

function formatSigned(val) {
  const n = Number(val) || 0
  return (n >= 0 ? '+' : '') + n.toFixed(2)
}

function formatAz(az) {
  const n = Math.round(Number(az) || 0)
  return (n >= 0 ? '+' : '') + n + '°'
}

function corrColor(r) {
  const n = Number(r) || 0
  if (n >= 0.25) return '#7ee787'
  if (n <= -0.25) return '#79c0ff'
  return '#d2a8ff'
}

function corrBarStyle(r) {
  const clamped = Math.max(-1, Math.min(1, Number(r) || 0))
  const widthPct = Math.abs(clamped) * 50
  if (clamped >= 0) {
    return {
      left: '50%',
      width: `${widthPct}%`,
      background: 'linear-gradient(90deg, #2ea043, #7ee787)',
    }
  }
  return {
    left: `${50 - widthPct}%`,
    width: `${widthPct}%`,
    background: 'linear-gradient(90deg, #58a6ff, #a371f7)',
  }
}

function movementIcon(st) {
  if (st === 'APPROACHING') return '🎯'
  if (st === 'RETREATING') return '↩️'
  if (st === 'LATERAL_PACING') return '🚶'
  if (st === 'MICRO_SWAY') return '〰️'
  return '🧘'
}

function shortRegime(st) {
  if (st === 'STILL_ANCHORED') return 'STILL'
  if (st === 'LATERAL_PACING') return 'PACING'
  if (st === 'MICRO_SWAY') return 'SWAY'
  return st || 'STILL'
}

function movementBadgeClass(st) {
  if (st === 'LATERAL_PACING' || st === 'APPROACHING') return 'mov-kinetic'
  if (st === 'MICRO_SWAY' || st === 'RETREATING') return 'mov-sway'
  return 'mov-still'
}

function flash(msg) {
  bannerMsg.value = msg
  setTimeout(() => {
    if (bannerMsg.value === msg) bannerMsg.value = ''
  }, 5500)
}

async function selectPrimaryAvatar(speakerId) {
  try {
    const res = await fetch('/api/delta-avatar/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ primary_avatar_id: speakerId }),
    })
    if (res.ok) {
      flash(`Switched 0.5–4.0 Hz Delta Brainwave Avatar to ${speakerId}`)
      emit('updated')
    }
  } catch (e) {
    console.error(e)
  }
}

function playAvatarWav(speakerId = '', phrase = '') {
  const spk = speakerId || activeAvatar.value?.speaker_id || 'PERSON_DELTA'
  const ph = phrase || activeAvatar.value?.active_earworm || 'steady delta whisper'
  currentWavUrl.value = `/api/delta-avatar/audio/${encodeURIComponent(spk)}.wav?phrase=${encodeURIComponent(ph)}&t=${Date.now()}`
}

async function runProbe(mode) {
  simBusy.value = true
  try {
    const res = await fetch('/api/delta-avatar/simulate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mode,
        speaker_id: activeAvatar.value?.speaker_id || 'PERSON_DELTA',
      }),
    })
    if (res.ok) {
      const j = await res.json()
      const assoc = j.association || {}
      flash(
        `Simulated ${mode}: "${assoc.earworm_phrase || ''}" → ${assoc.movement_state || mode} (Reset ${assoc.emotional_reset_pct ?? 78}%)`
      )
      emit('updated')
    }
  } catch (e) {
    console.error(e)
  } finally {
    simBusy.value = false
  }
}

async function saveTuning() {
  configBusy.value = true
  try {
    const res = await fetch('/api/delta-avatar/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...localCfg }),
    })
    if (res.ok) {
      flash('Updated live VAD Motion & 0.5–4.0 Hz Delta Avatar parameters')
      emit('updated')
    }
  } catch (e) {
    console.error(e)
  } finally {
    configBusy.value = false
  }
}

async function consultOllama(force = true) {
  ollamaBusy.value = true
  try {
    const res = await fetch('/api/ollama/delta-avatar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force }),
    })
    if (res.ok) {
      ollamaAdvice.value = await res.json()
      if (force) {
        flash('NightSweep Ollama Modal synthesized 0.5–4 Hz Delta & VAD Motion reference + improvements!')
      }
    }
  } catch (e) {
    console.error(e)
  } finally {
    ollamaBusy.value = false
  }
}

async function applyOllamaConfig() {
  const rc = ollamaAdvice.value?.recommended_config
  if (!rc) return
  configBusy.value = true
  try {
    const res = await fetch('/api/delta-avatar/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(rc),
    })
    if (res.ok) {
      flash('Applied NightSweep Ollama Modal recommended VAD Motion & 0.5–4 Hz Delta tuning!')
      emit('updated')
    }
  } catch (e) {
    console.error(e)
  } finally {
    configBusy.value = false
  }
}

onMounted(() => {
  consultOllama(false)
})
</script>

<style scoped>
.da-card {
  container-type: inline-size;
  background: linear-gradient(180deg, rgba(16, 23, 36, 0.96), rgba(11, 16, 26, 0.98));
  border: 1px solid rgba(63, 185, 80, 0.34);
  border-radius: 12px;
  padding: 15px 18px;
  display: flex;
  flex-direction: column;
  gap: 13px;
  box-sizing: border-box;
  min-width: 0;
}

.da-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
}

.da-head-left {
  flex: 1 1 540px;
  min-width: 0;
}

.da-title-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.da-title {
  margin: 0;
  font-size: 1rem;
  font-weight: 800;
  color: #e6edf3;
}

.da-sub {
  margin-top: 5px;
  font-size: 0.76rem;
  color: #9ca3af;
  line-height: 1.45;
}

.delta-pill {
  background: rgba(46, 160, 67, 0.16);
  border: 1px solid rgba(63, 185, 80, 0.5);
  color: #7ee787;
}

.motion-pill {
  border-radius: 99px;
  padding: 3px 10px;
  font-size: 0.71rem;
}

.mov-still {
  background: rgba(56, 189, 248, 0.14);
  border: 1px solid rgba(56, 189, 248, 0.45);
  color: #79c0ff;
}

.mov-sway {
  background: rgba(210, 168, 255, 0.15);
  border: 1px solid rgba(210, 168, 255, 0.45);
  color: #d2a8ff;
}

.mov-kinetic {
  background: rgba(240, 136, 62, 0.18);
  border: 1px solid rgba(240, 136, 62, 0.55);
  color: #ffa657;
}

.da-hdr-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.btn-ollama {
  background: linear-gradient(135deg, #0284c7, #6e40c9);
  border: 1px solid rgba(121, 192, 255, 0.45);
  color: #ffffff;
  font-size: 0.73rem;
}

.btn-apply {
  background: rgba(46, 160, 67, 0.22);
  border: 1px solid rgba(63, 185, 80, 0.6);
  color: #7ee787;
  font-size: 0.73rem;
}

.da-banner {
  background: rgba(46, 160, 67, 0.18);
  border: 1px solid rgba(63, 185, 80, 0.5);
  color: #7ee787;
  padding: 7px 12px;
  border-radius: 8px;
  font-size: 0.75rem;
}

/* OLLAMA MODAL DRAWER (REFERENCE STYLE) */
.ollama-drawer {
  background: linear-gradient(135deg, rgba(14, 26, 43, 0.94), rgba(22, 19, 39, 0.94));
  border: 1px solid rgba(88, 166, 255, 0.4);
  border-radius: 10px;
  padding: 11px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.od-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 0.73rem;
}

.od-badge {
  color: #79c0ff;
  font-weight: 700;
}

.od-ts {
  color: #8b949e;
  font-size: 0.69rem;
}

.od-summary {
  margin: 0;
  font-size: 0.77rem;
  color: #e6edf3;
  line-height: 1.45;
}

.od-cols {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr));
  gap: 10px;
}

.od-col {
  background: rgba(9, 14, 22, 0.72);
  border: 1px solid rgba(48, 64, 92, 0.6);
  border-radius: 8px;
  padding: 8px 10px;
}

.od-col-hdr {
  font-size: 0.72rem;
  font-weight: 700;
  color: #d2a8ff;
  margin-bottom: 5px;
}

.od-col ul {
  margin: 0;
  padding-left: 16px;
  font-size: 0.72rem;
  color: #b1bac4;
  line-height: 1.42;
}

/* 3-COLUMN RESPONSIVE GRID */
.da-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 13px;
  align-items: start;
}

@container (max-width: 1180px) {
  .da-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@container (max-width: 780px) {
  .da-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 960px) {
  .da-grid {
    grid-template-columns: 1fr;
  }
}

.da-panel {
  background: #0c121e;
  border: 1px solid #1e2c44;
  border-radius: 10px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
  box-sizing: border-box;
}

.panel-hdr {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.panel-title {
  font-size: 0.77rem;
  font-weight: 700;
  color: #79c0ff;
}

.sub-pill {
  font-size: 0.68rem;
  color: #8b949e;
  background: #111927;
  border: 1px solid #23324b;
  padding: 2px 8px;
  border-radius: 99px;
}

.mini-btn {
  background: #131d2e;
  border: 1px solid #2b3e5e;
  color: #9ecbff;
  border-radius: 6px;
  padding: 3px 8px;
  font-size: 0.69rem;
  cursor: pointer;
}

.play-btn {
  border-color: rgba(63, 185, 80, 0.55);
  color: #7ee787;
}

.avatar-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.av-tab {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: #111826;
  border: 1px solid #23314a;
  color: #9ca3af;
  border-radius: 99px;
  padding: 3px 9px;
  font-size: 0.7rem;
  cursor: pointer;
}

.av-tab.active {
  background: rgba(240, 136, 62, 0.14);
  font-weight: 700;
}

.av-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.av-mini-pct {
  opacity: 0.85;
  font-size: 0.66rem;
}

.avatar-stage {
  background: radial-gradient(circle at 50% 45%, rgba(28, 43, 68, 0.5), rgba(8, 12, 20, 0.95));
  border: 1px solid #1b2840;
  border-radius: 9px;
  padding: 6px;
}

.avatar-svg {
  width: 100%;
  height: auto;
  max-height: 210px;
  display: block;
}

.delta-ring {
  fill: none;
  stroke-width: 1.6;
  transform-origin: 140px 98px;
  animation: deltaPulse 0.65s ease-in-out infinite alternate;
}

.delta-ring.outer {
  stroke-dasharray: 5 4;
  opacity: 0.55;
}

.delta-ring.mid {
  stroke: #3fb950;
  opacity: 0.45;
}

@keyframes deltaPulse {
  0% {
    transform: scale(0.94);
    opacity: 0.32;
  }
  100% {
    transform: scale(1.05);
    opacity: 0.78;
  }
}

.svg-lbl {
  font-size: 9.5px;
  font-weight: 700;
}

.svg-sub {
  font-size: 8.6px;
}

.assoc-bubble {
  background: linear-gradient(135deg, rgba(88, 166, 255, 0.09), rgba(63, 185, 80, 0.08));
  border: 1px solid rgba(88, 166, 255, 0.34);
  border-radius: 8px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.ab-top {
  display: flex;
  justify-content: space-between;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 0.67rem;
}

.ab-tag {
  color: #79c0ff;
  font-weight: 700;
}

.ab-contour {
  color: #d2a8ff;
}

.ab-phrase {
  font-size: 0.88rem;
  font-weight: 700;
  color: #ffffff;
  overflow-wrap: anywhere;
}

.ab-next {
  font-size: 0.74rem;
  color: #7ee787;
  margin-left: 6px;
}

.ab-scores {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  font-size: 0.69rem;
}

.audio-box {
  background: #080d15;
  border: 1px solid #1b283d;
  border-radius: 8px;
  padding: 7px 9px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.audio-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.audio-lbl {
  font-size: 0.69rem;
  color: #9ecbff;
}

.wav-player {
  width: 100%;
  height: 30px;
}

.probe-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.probe-btn {
  flex: 1 1 115px;
  font-size: 0.69rem;
  padding: 5px 8px;
  text-align: center;
  justify-content: center;
}

/* SCOPES & CORRELATIONS */
.scope-card {
  background: #080d15;
  border: 1px solid #1b283e;
  border-radius: 8px;
  padding: 7px 9px;
}

.scope-hdr {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 0.68rem;
  color: #9ca3af;
  margin-bottom: 4px;
}

.scope-svg {
  width: 100%;
  height: 68px;
  display: block;
}

.legend-inline {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.legend-inline i {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 2px;
}

.corr-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.corr-row {
  background: #090f19;
  border: 1px solid #1c2a42;
  border-radius: 8px;
  padding: 7px 9px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.corr-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 0.71rem;
}

.corr-label {
  color: #e6edf3;
  font-weight: 700;
}

.corr-bar-track {
  position: relative;
  height: 7px;
  background: #141e30;
  border-radius: 99px;
  overflow: hidden;
}

.corr-zero {
  position: absolute;
  left: 50%;
  top: 0;
  bottom: 0;
  width: 1px;
  background: #8b949e;
  z-index: 2;
}

.corr-bar-fill {
  position: absolute;
  top: 0;
  bottom: 0;
  border-radius: 99px;
}

.corr-foot {
  display: flex;
  justify-content: space-between;
  font-size: 0.64rem;
  gap: 6px;
}

.corr-strength {
  color: #c9d1d9;
}

.interp-list {
  margin: 0;
  padding-left: 16px;
  font-size: 0.71rem;
  color: #b1bac4;
  line-height: 1.42;
}

/* REGIMES, FEED & TUNING */
.regime-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 118px), 1fr));
  gap: 6px;
}

.regime-chip {
  background: #090f19;
  border: 1px solid #1c2940;
  border-radius: 7px;
  padding: 6px 8px;
  min-width: 0;
}

.regime-chip.active {
  border-color: #ffa657;
  background: rgba(240, 136, 62, 0.11);
}

.reg-top {
  display: flex;
  justify-content: space-between;
  font-size: 0.67rem;
  color: #9ecbff;
}

.reg-hook {
  margin-top: 3px;
  font-size: 0.69rem;
  color: #e6edf3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.assoc-feed-hdr {
  font-size: 0.71rem;
  font-weight: 700;
  color: #7ee787;
}

.assoc-feed {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 225px;
  overflow-y: auto;
}

.empty-feed {
  font-size: 0.71rem;
  color: #8b949e;
  padding: 8px;
}

.assoc-item {
  background: #080d16;
  border: 1px solid #1a263b;
  border-radius: 7px;
  padding: 6px 8px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.ai-top {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 0.68rem;
}

.spk-link {
  background: none;
  border: none;
  color: #58a6ff;
  padding: 0;
  cursor: pointer;
  font-weight: 700;
}

.mov-tag {
  padding: 1px 6px;
  border-radius: 99px;
  font-size: 0.64rem;
}

.mini-play {
  margin-left: auto;
  background: rgba(46, 160, 67, 0.2);
  border: 1px solid rgba(63, 185, 80, 0.5);
  color: #7ee787;
  border-radius: 5px;
  padding: 1px 6px;
  cursor: pointer;
  font-size: 0.66rem;
}

.ai-phrase {
  font-size: 0.75rem;
  color: #e6edf3;
  overflow-wrap: anywhere;
}

.ai-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 0.65rem;
  color: #8b949e;
}

.tuning-box {
  background: #090e17;
  border: 1px solid #1c2940;
  border-radius: 8px;
  padding: 8px 10px;
}

.tuning-hdr {
  font-size: 0.69rem;
  font-weight: 700;
  color: #d2a8ff;
  margin-bottom: 6px;
}

.tuning-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 150px), 1fr));
  gap: 7px 10px;
  font-size: 0.66rem;
  color: #b1bac4;
}

.tuning-grid label {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.tuning-grid input[type='range'] {
  width: 100%;
  accent-color: #3fb950;
}

.muted {
  color: #8b949e;
}
</style>
