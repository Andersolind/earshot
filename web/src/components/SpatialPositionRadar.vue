<template>
  <section class="card radar-card">
    <div class="card-header">
      <div>
        <div class="card-title">
          <span>🧊 3D Three.js Avatar Room vs 📡 2D Polar Spatial Radar</span>
          <span class="pill mono" style="color: #3fb950">
            {{ liveSpatial.positioning_mode || 'TIER1_DRR_POLAR' }}
          </span>
          <span v-if="focusState.enabled && (focusState.focus_mode === 'AUTO' || focusState.focus_mode === 'BOTH')" class="pill mono focus-pill">
            🎯 Closest: {{ focusState.closest_speaker_id }} ({{ focusState.closest_range_m }}m)
          </span>
          <span v-if="focusState.enabled && (focusState.focus_mode === 'PINNED' || focusState.focus_mode === 'BOTH') && focusState.pinned_speaker_id" class="pill mono pin-pill">
            📌 Pinned: {{ focusState.pinned_speaker_id }} ({{ focusState.pinned_range_m }}m)
          </span>
        </div>
        <div class="sub-caption">
          Showcase all enrolled 3D/2D avatars (<span class="mono">DRR / Sabine C50 / RF ToF</span>) &amp; fine-tune near-field focus on the closest faint identity
        </div>
      </div>

      <div class="seg-group">
        <button class="seg-btn" :class="{ active: activeView === '3d' }" @click="activeView = '3d'">
          🧊 3D Avatar Room
        </button>
        <button class="seg-btn" :class="{ active: activeView === 'radar' }" @click="activeView = 'radar'">
          📡 2D Polar Radar
        </button>
        <button class="seg-btn" :class="{ active: activeView === 'guide' }" @click="activeView = 'guide'">
          📐 How Faint-Focus Works
        </button>
      </div>
    </div>

    <div v-if="focusBanner" class="focus-banner mono">✅ {{ focusBanner }}</div>

    <!-- VIEW 1 (3D) OR VIEW 2 (2D) -->
    <div v-if="activeView === '3d' || activeView === 'radar'" class="radar-body">
      <!-- 3D THREE.JS AVATAR ROOM -->
      <ThreeSpatialAvatarStage
        v-if="activeView === '3d'"
        :targets="targets"
        :roomCriticalDist="localRc"
        :gateOpen="gateOpen"
        :typistSector="typistSector"
        :closestFocus="focusState"
        :threeStateVad="threeStateVad"
        @select-speaker="$emit('select-speaker', $event)"
      />

      <!-- 2D POLAR SVG RADAR -->
      <div v-else class="radar-canvas-box">
        <svg viewBox="0 0 420 275" class="radar-svg">
          <defs>
            <radialGradient id="beamGrad" cx="50%" cy="92%" r="85%">
              <stop offset="0%" stop-color="#2f81f7" stop-opacity="0.24" />
              <stop offset="60%" stop-color="#2f81f7" stop-opacity="0.06" />
              <stop offset="100%" stop-color="#2f81f7" stop-opacity="0.0" />
            </radialGradient>
            <radialGradient id="typistConeGrad" cx="50%" cy="92%" r="65%">
              <stop offset="0%" stop-color="#2dd4bf" stop-opacity="0.30" />
              <stop offset="75%" stop-color="#2dd4bf" stop-opacity="0.11" />
              <stop offset="100%" stop-color="#2dd4bf" stop-opacity="0.02" />
            </radialGradient>
            <radialGradient id="closestSpotGrad" cx="50%" cy="92%" r="65%">
              <stop offset="0%" stop-color="#3fb950" stop-opacity="0.34" />
              <stop offset="80%" stop-color="#3fb950" stop-opacity="0.12" />
              <stop offset="100%" stop-color="#3fb950" stop-opacity="0.02" />
            </radialGradient>
            <radialGradient id="pinnedSpotGrad" cx="50%" cy="92%" r="65%">
              <stop offset="0%" stop-color="#a371f7" stop-opacity="0.34" />
              <stop offset="80%" stop-color="#a371f7" stop-opacity="0.12" />
              <stop offset="100%" stop-color="#a371f7" stop-opacity="0.02" />
            </radialGradient>
          </defs>

          <!-- Polar Sector Fill -->
          <path :d="sectorPath(4.0, -80, 80)" fill="url(#beamGrad)" />

          <!-- Closest-Identity Faint-Signal Spotlight Cone in 2D -->
          <g v-if="focusState.enabled && (focusState.focus_mode === 'AUTO' || focusState.focus_mode === 'BOTH')">
            <path
              :d="sectorPath(
                Math.min(3.2, focusCfg.focus_cutoff_m),
                Math.max(-79, focusState.closest_azimuth_deg - focusCfg.focus_beamwidth_deg),
                Math.min(79, focusState.closest_azimuth_deg + focusCfg.focus_beamwidth_deg)
              )"
              fill="url(#closestSpotGrad)"
              stroke="#3fb950"
              stroke-width="1.35"
              stroke-dasharray="5 3"
            />
          </g>

          <!-- Pinned-Identity Spotlight Cone in 2D -->
          <g v-if="focusState.enabled && (focusState.focus_mode === 'PINNED' || focusState.focus_mode === 'BOTH') && focusState.pinned_speaker_id">
            <path
              :d="sectorPath(
                Math.min(3.3, Math.max(focusCfg.focus_cutoff_m, (focusState.pinned_range_m || 0.9) + 0.25)),
                Math.max(-79, focusState.pinned_azimuth_deg - focusCfg.focus_beamwidth_deg),
                Math.min(79, focusState.pinned_azimuth_deg + focusCfg.focus_beamwidth_deg)
              )"
              fill="url(#pinnedSpotGrad)"
              stroke="#a371f7"
              stroke-width="1.35"
              stroke-dasharray="4 3"
            />
          </g>

          <!-- PERSON_TYPIST Desk Spatial Sector Cone -->
          <g
            v-if="deskCone.enabled"
            class="radar-target"
            @click="$emit('select-speaker', 'PERSON_TYPIST')"
          >
            <title>
              PERSON_TYPIST Desk Sector Cone ({{ deskCone.preset }}): {{ formatAz(deskCone.az) }} ±{{ deskCone.hyst }}° @ {{ deskCone.range }}m
            </title>
            <path
              :d="sectorPath(deskCone.outerR, deskCone.minAz, deskCone.maxAz)"
              fill="url(#typistConeGrad)"
              stroke="#2dd4bf"
              stroke-width="1.25"
              stroke-dasharray="4 3"
              stroke-opacity="0.82"
            />
            <text
              :x="polarToXY(deskCone.outerR + 0.22, deskCone.az).x"
              :y="polarToXY(deskCone.outerR + 0.22, deskCone.az).y"
              text-anchor="middle"
              fill="#5eead4"
              font-size="9.2"
              font-weight="700"
              class="mono"
            >
              ⌨️ Desk Cone ({{ formatAz(deskCone.az) }}±{{ Math.round(deskCone.hyst) }}°)
            </text>
          </g>

          <!-- Range Rings (1m, 2m, 3m, 4m) -->
          <g v-for="r in [1, 2, 3, 4]" :key="r">
            <path
              :d="arcPath(r, -80, 80)"
              fill="none"
              stroke="#223046"
              stroke-width="1"
              stroke-dasharray="3 3"
            />
            <text :x="originX + 6" :y="originY - r * scaleM + 11" class="ring-lbl mono">
              {{ r }}m
            </text>
          </g>

          <!-- Calibrated Room Critical Distance Ring r_c -->
          <path
            :d="arcPath(localRc, -80, 80)"
            fill="none"
            stroke="#f0883e"
            stroke-width="1.2"
            stroke-dasharray="6 4"
            opacity="0.7"
          />
          <text
            :x="originX - 72"
            :y="originY - localRc * scaleM - 4"
            fill="#f0883e"
            font-size="9.5"
            class="mono"
          >
            r_c={{ localRc.toFixed(2) }}m
          </text>

          <!-- Azimuth Rays (-60, -30, 0, +30, +60) -->
          <g v-for="ang in [-60, -30, 0, 30, 60]" :key="ang">
            <line
              :x1="originX"
              :y1="originY"
              :x2="polarToXY(4.05, ang).x"
              :y2="polarToXY(4.05, ang).y"
              stroke="#1c2739"
              stroke-width="1"
            />
            <text
              :x="polarToXY(4.22, ang).x"
              :y="polarToXY(4.22, ang).y"
              text-anchor="middle"
              class="ring-lbl mono"
            >
              {{ ang > 0 ? '+' + ang : ang }}°
            </text>
          </g>

          <!-- Breadcrumb Trails per Speaker -->
          <g v-for="t in targets" :key="'trail-' + t.speaker_id">
            <polyline
              v-if="t.trail && t.trail.length > 1"
              :points="trailPoints(t.trail)"
              fill="none"
              :stroke="t.color"
              stroke-width="1.5"
              stroke-opacity="0.35"
            />
          </g>

          <!-- Live VAD Instantaneous Cursor -->
          <g v-if="gateOpen">
            <circle
              :cx="polarToXY(liveSpatial.range_m || 1.1, liveSpatial.azimuth_deg || 0).x"
              :cy="polarToXY(liveSpatial.range_m || 1.1, liveSpatial.azimuth_deg || 0).y"
              r="18"
              fill="none"
              stroke="#3fb950"
              stroke-width="1.8"
              opacity="0.75"
            />
          </g>

          <!-- Enrolled Speaker Targets (Clickable) -->
          <g
            v-for="t in targets"
            :key="t.speaker_id"
            class="radar-target"
            @click="$emit('select-speaker', t.speaker_id)"
          >
            <title>Click to open {{ t.speaker_id }}'s Shared Earworm &amp; Biometric Dossier</title>
            <circle
              :cx="polarToXY(t.range_m, t.azimuth_deg).x"
              :cy="polarToXY(t.range_m, t.azimuth_deg).y"
              :r="focusState.enabled && t.speaker_id === focusState.locked_speaker_id ? 17 : 14"
              :fill="t.color"
              :fill-opacity="focusState.enabled && t.speaker_id === focusState.locked_speaker_id ? 0.30 : 0.18"
              :stroke="focusState.enabled && t.speaker_id === focusState.locked_speaker_id ? '#3fb950' : 'none'"
              stroke-width="1.5"
            />
            <circle
              :cx="polarToXY(t.range_m, t.azimuth_deg).x"
              :cy="polarToXY(t.range_m, t.azimuth_deg).y"
              r="6.5"
              :fill="t.color"
              stroke="#0a0e14"
              stroke-width="1.5"
            />
            <text
              :x="polarToXY(t.range_m, t.azimuth_deg).x"
              :y="polarToXY(t.range_m, t.azimuth_deg).y - 12"
              text-anchor="middle"
              :fill="t.color"
              font-size="10.5"
              font-weight="700"
              class="mono"
            >
              {{ t.speaker_id }} ({{ t.range_m }}m, {{ formatAz(t.azimuth_deg) }})
            </text>
          </g>

          <!-- Sensor Origin (UltraMic384K_EVO + SDR) -->
          <circle :cx="originX" :cy="originY" r="7" fill="#58a6ff" />
          <text :x="originX" :y="originY + 16" text-anchor="middle" fill="#8b949e" font-size="10" class="mono">
            🎙️ UltraMic384K_EVO (0, 0)
          </text>
        </svg>
      </div>

      <!-- ROOM CRITICAL DISTANCE + CLOSEST & PINNED FAINT IDENTITY FINE-TUNING BAR -->
      <div class="focus-panel">
        <div class="fp-top">
          <div class="fp-title mono">
            🎯 Room Faint-Signal Focus: Auto-Closest &amp; Pinned Identity
          </div>
          <div class="fp-controls mono">
            <label class="chk-lbl">
              <input
                type="checkbox"
                v-model="focusCfg.focus_closest_enabled"
                @change="pushFocusConfig({ focus_closest_enabled: focusCfg.focus_closest_enabled })"
              />
              Spotlight Active
            </label>
            <div class="mode-seg mono">
              <button
                type="button"
                class="m-btn"
                :class="{ active: focusCfg.focus_mode === 'BOTH' }"
                @click="setFocusMode('BOTH')"
                title="Focus simultaneously on BOTH the closest speaker AND your pinned enrolled identity"
              >
                ⚡ Both (Closest + Pin)
              </button>
              <button
                type="button"
                class="m-btn"
                :class="{ active: focusCfg.focus_mode === 'AUTO' }"
                @click="setFocusMode('AUTO')"
                title="Auto-lock onto whichever enrolled speaker is closest in real time"
              >
                🔄 Auto-Closest
              </button>
              <button
                type="button"
                class="m-btn"
                :class="{ active: focusCfg.focus_mode === 'PINNED' }"
                @click="setFocusMode('PINNED')"
                title="Pin exclusive room focus onto the selected enrolled identity"
              >
                📌 Pin Only
              </button>
            </div>
          </div>
        </div>

        <!-- 1-Click Enrolled Identity Pin Selector Row -->
        <div class="pin-pills-row mono">
          <span class="pin-lbl">📌 Pin Enrolled Identity:</span>
          <button
            v-for="v in vocalTargets"
            :key="'pin-pill-' + v.speaker_id"
            type="button"
            class="pin-id-pill"
            :class="{ active: focusState.pinned_speaker_id === v.speaker_id && (focusCfg.focus_mode === 'PINNED' || focusCfg.focus_mode === 'BOTH') }"
            @click="pinSpeakerId(v.speaker_id)"
          >
            {{ v.speaker_id }} ({{ v.range_m }}m)
          </button>
        </div>

        <div class="fp-sliders mono">
          <label>
            <span>Cutoff Radius: <b>{{ focusCfg.focus_cutoff_m.toFixed(2) }} m</b></span>
            <input
              type="range" min="0.40" max="2.40" step="0.05"
              v-model.number="focusCfg.focus_cutoff_m"
              @change="pushFocusConfig({ focus_cutoff_m: focusCfg.focus_cutoff_m })"
            />
          </label>
          <label>
            <span>Faint Make-Up Gain: <b style="color: #3fb950">+{{ focusCfg.faint_makeup_gain_db.toFixed(0) }} dB</b></span>
            <input
              type="range" min="8" max="28" step="1"
              v-model.number="focusCfg.faint_makeup_gain_db"
              @change="pushFocusConfig({ faint_makeup_gain_db: focusCfg.faint_makeup_gain_db })"
            />
          </label>
          <label>
            <span>Polar Lobe: <b>±{{ focusCfg.focus_beamwidth_deg }}°</b></span>
            <input
              type="range" min="12" max="55" step="2"
              v-model.number="focusCfg.focus_beamwidth_deg"
              @change="pushFocusConfig({ focus_beamwidth_deg: focusCfg.focus_beamwidth_deg })"
            />
          </label>
          <label>
            <span>Sabine Critical (r_c): <b style="color: #f0883e">{{ localRc.toFixed(2) }} m</b></span>
            <input
              type="range" min="0.60" max="3.20" step="0.05"
              v-model.number="localRc"
              @change="$emit('calibrate-rc', localRc)"
            />
          </label>
        </div>

        <div class="fp-sub mono">
          <span>Ultra-Faint VAD Floor: <b>{{ focusState.ultra_faint_vad_mult ?? 1.06 }}×</b></span>
          <span>Off-Axis Null: <b>-{{ focusState.off_axis_null_db ?? 13.5 }} dB</b></span>
          <span>C50 Dereverb: <b>{{ Math.round((focusState.dereverb_strength ?? 0.68) * 100) }}%</b></span>
          <span>Faint Frames Boosted: <b>{{ focusState.faint_frames_boosted ?? 0 }}</b></span>
        </div>
      </div>

      <!-- Per-Speaker Spatial Telemetry Table -->
      <div class="spatial-list">
        <div class="live-fix-banner mono">
          <span>🎯 Live Acoustic Fix: <strong>{{ (liveSpatial.range_m || 1.15).toFixed(2) }} m</strong></span>
          <span>Bearing: <strong>{{ formatAz(liveSpatial.azimuth_deg || 0) }}</strong></span>
          <span>DRR: <strong>{{ (liveSpatial.drr_db || 4.5).toFixed(1) }} dB</strong></span>
          <span>Zone: <strong>{{ liveSpatial.proximity_zone || 'MID_FIELD' }}</strong></span>
        </div>

        <div
          v-for="t in targets"
          :key="'row-' + t.speaker_id"
          class="target-row clickable-row"
          :class="{
            'locked-row':
              focusState.enabled &&
              (((focusState.focus_mode === 'AUTO' || focusState.focus_mode === 'BOTH') && t.speaker_id === focusState.closest_speaker_id) ||
                ((focusState.focus_mode === 'PINNED' || focusState.focus_mode === 'BOTH') && t.speaker_id === focusState.pinned_speaker_id)),
          }"
          :title="`Click to open & share ${t.speaker_id}'s earworm`"
          @click="$emit('select-speaker', t.speaker_id)"
        >
          <div class="target-head">
            <span class="mono" :style="{ color: t.color, fontWeight: 700 }">
              {{ avatarIcon(t.speaker_id) }} {{ t.speaker_id }}
              <span
                v-if="focusState.enabled && (focusState.focus_mode === 'AUTO' || focusState.focus_mode === 'BOTH') && t.speaker_id === focusState.closest_speaker_id"
                class="lock-chip"
              >
                🎯 CLOSEST LOCK
              </span>
              <span
                v-if="focusState.enabled && (focusState.focus_mode === 'PINNED' || focusState.focus_mode === 'BOTH') && t.speaker_id === focusState.pinned_speaker_id"
                class="lock-chip"
                style="background: rgba(163, 113, 247, 0.25); color: #e9d5ff; border: 1px solid rgba(163, 113, 247, 0.55)"
              >
                📌 PINNED FOCUS
              </span>
            </span>
            <div class="head-badges">
              <span class="share-hint mono">Share Earworm ↗</span>
              <span class="zone-badge mono">{{ t.proximity_zone }}</span>
            </div>
          </div>
          <div class="target-metrics mono">
            <span>Range: <strong>{{ t.range_m }} m</strong></span>
            <span>Azimuth: <strong>{{ formatAz(t.azimuth_deg) }}</strong></span>
            <span>DRR: <strong>{{ t.drr_db }} dB</strong></span>
            <span>C50: <strong>{{ t.c50_db }} dB</strong></span>
          </div>
        </div>
      </div>
    </div>

    <!-- VIEW 3: 3-TIER POSITIONING + HOW TO FINE-TUNE CLOSEST FAINT IDENTITY -->
    <div v-else class="tiers-stack">
      <div class="tier-box highlight-tier">
        <div class="tier-top">
          <span class="tier-badge live mono">HOW TO FINE-TUNE FOR CLOSEST FAINT IDENTITIES</span>
          <span class="tier-acc mono">1.06× Floor · +22 dB Soft-Knee · -13.5 dB Off-Axis Null</span>
        </div>
        <div class="tier-title">4-Step Room Calibration for Ultra-Faint Closest Whispers</div>
        <ul class="faint-steps">
          <li v-for="(stepTxt, i) in focusState.how_to_fine_tune || defaultFineTuneSteps" :key="i">
            {{ stepTxt }}
          </li>
        </ul>
      </div>

      <div v-for="tg in tiersGuide" :key="tg.code" class="tier-box">
        <div class="tier-top">
          <span class="tier-badge mono" :class="{ live: tg.code === 'TIER1_DRR_POLAR' || tg.code === 'CLOSEST_IDENTITY_FAINT_LOCK' }">
            {{ tg.tier }}
          </span>
          <span class="tier-acc mono">{{ tg.accuracy }}</span>
        </div>
        <div class="tier-title">{{ tg.title }}</div>
        <div class="tier-hw mono">Hardware: {{ tg.hardware }}  |  Math: {{ tg.formula }}</div>
        <p class="tier-desc">{{ tg.how_it_works }}</p>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import ThreeSpatialAvatarStage from './ThreeSpatialAvatarStage.vue'

const props = defineProps({
  targets: { type: Array, default: () => [] },
  liveSpatial: { type: Object, default: () => ({}) },
  tiersGuide: { type: Array, default: () => [] },
  roomCriticalDist: { type: Number, default: 1.45 },
  gateOpen: { type: Boolean, default: false },
  typistSector: { type: Object, default: () => ({}) },
  closestFocus: { type: Object, default: () => ({}) },
  threeStateVad: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['calibrate-rc', 'select-speaker', 'focus-updated'])

const activeView = ref('3d')
const localRc = ref(props.roomCriticalDist || 1.45)
const focusBanner = ref('')
const selectedPin = ref('AUTO')

const NON_VOCAL_SET = new Set([
  'PERSON_TYPIST',
  'DEVICE_CELLPHONE',
  'DEVICE_MEMS',
  'OTHER_ROOM_SUBLEVEL',
])

const defaultFineTuneSteps = [
  '1. Set Cutoff Radius below Room Critical Distance r_c (0.85–1.20 m) so diffuse room reverberation from distant speakers is gated out.',
  '2. Narrow Polar Lobe (±22°–28°) around the closest identity to null off-axis chatter by -13.5 dB.',
  '3. Engage +22 dB Soft-Knee Upward Make-Up Gain + 1.06× Biometric VAD gate so -48 dBFS breaths/whispers open Faster-Whisper.',
  '4. Keep Sabine C50 Dereverberation (68%) active to strip >28 ms room reflections.',
]

const focusCfg = reactive({
  focus_closest_enabled: true,
  focus_mode: 'BOTH',
  pinned_speaker_id: 'PERSON_DELTA',
  focus_cutoff_m: 1.15,
  faint_makeup_gain_db: 22,
  focus_beamwidth_deg: 28,
})

const vocalTargets = computed(() =>
  (props.targets || [])
    .filter((t) => !NON_VOCAL_SET.has(t.speaker_id))
    .slice()
    .sort((a, b) => Number(a.range_m || 9) - Number(b.range_m || 9))
)

const focusState = computed(() => {
  const cf = props.closestFocus || {}
  const firstVocal = vocalTargets.value[0]
  const pinId = cf.pinned_speaker_id ?? focusCfg.pinned_speaker_id ?? 'PERSON_DELTA'
  const pinTarget = vocalTargets.value.find((t) => t.speaker_id === pinId)
  return {
    enabled: cf.enabled !== false && focusCfg.focus_closest_enabled,
    focus_mode: String(cf.focus_mode || focusCfg.focus_mode || 'BOTH').toUpperCase(),
    closest_speaker_id: cf.closest_speaker_id || cf.locked_speaker_id || firstVocal?.speaker_id || 'PERSON_BETA',
    closest_range_m: cf.closest_range_m ?? cf.locked_range_m ?? firstVocal?.range_m ?? 0.35,
    closest_azimuth_deg: cf.closest_azimuth_deg ?? cf.locked_azimuth_deg ?? firstVocal?.azimuth_deg ?? 48,
    pinned_speaker_id: pinId,
    pinned_range_m: cf.pinned_range_m ?? pinTarget?.range_m ?? 0.72,
    pinned_azimuth_deg: cf.pinned_azimuth_deg ?? pinTarget?.azimuth_deg ?? -36,
    locked_speaker_id: cf.locked_speaker_id || firstVocal?.speaker_id || 'PERSON_BETA',
    locked_range_m: cf.locked_range_m ?? firstVocal?.range_m ?? 0.35,
    locked_azimuth_deg: cf.locked_azimuth_deg ?? firstVocal?.azimuth_deg ?? 48,
    focus_cutoff_m: cf.focus_cutoff_m ?? focusCfg.focus_cutoff_m,
    focus_beamwidth_deg: cf.focus_beamwidth_deg ?? focusCfg.focus_beamwidth_deg,
    faint_makeup_gain_db: cf.faint_makeup_gain_db ?? focusCfg.faint_makeup_gain_db,
    ultra_faint_vad_mult: cf.ultra_faint_vad_mult ?? 1.06,
    off_axis_null_db: cf.off_axis_null_db ?? 13.5,
    dereverb_strength: cf.dereverb_strength ?? 0.68,
    faint_frames_boosted: cf.faint_frames_boosted ?? 0,
    how_to_fine_tune: cf.how_to_fine_tune,
  }
})

watch(
  () => props.closestFocus,
  (cf) => {
    if (!cf) return
    if (cf.enabled !== undefined) focusCfg.focus_closest_enabled = Boolean(cf.enabled)
    if (cf.focus_mode) focusCfg.focus_mode = String(cf.focus_mode).toUpperCase()
    if (cf.pinned_speaker_id !== undefined) focusCfg.pinned_speaker_id = cf.pinned_speaker_id
    if (cf.focus_cutoff_m !== undefined) focusCfg.focus_cutoff_m = Number(cf.focus_cutoff_m)
    if (cf.faint_makeup_gain_db !== undefined) focusCfg.faint_makeup_gain_db = Number(cf.faint_makeup_gain_db)
    if (cf.focus_beamwidth_deg !== undefined) focusCfg.focus_beamwidth_deg = Number(cf.focus_beamwidth_deg)
    selectedPin.value = cf.pinned_speaker_id || 'PERSON_DELTA'
  },
  { immediate: true, deep: true }
)

const deskCone = computed(() => {
  const s = props.typistSector || {}
  const az = Number(s.desk_azimuth_deg ?? -8)
  const range = Number(s.desk_range_m ?? 0.62)
  const hyst = Number(s.directional_hysteresis_deg ?? 22)
  return {
    enabled: s.spatial_sector_lock !== false,
    preset: s.desk_sector_preset || 'CENTER_DESK',
    az,
    range,
    hyst,
    outerR: Math.min(2.15, Math.max(0.55, range + 0.36)),
    minAz: Math.max(-79, az - hyst),
    maxAz: Math.min(79, az + hyst),
  }
})

watch(
  () => props.roomCriticalDist,
  (v) => {
    if (v) localRc.value = v
  }
)

function avatarIcon(id) {
  if (id === 'PERSON_TYPIST') return '⌨️'
  if (id === 'DEVICE_CELLPHONE') return '📱'
  if (id === 'DEVICE_MEMS') return '🔬'
  if (id === 'OTHER_ROOM_SUBLEVEL') return '🧱'
  return '🎧'
}

async function pushFocusConfig(patch) {
  try {
    const res = await fetch('/api/spatial/focus-closest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
    if (res.ok) {
      const j = await res.json()
      focusBanner.value = 'Room Focus Tuned: ' + (j.applied || []).join(', ')
      setTimeout(() => {
        focusBanner.value = ''
      }, 4500)
      emit('focus-updated')
    }
  } catch (err) {
    console.error('Focus config error:', err)
  }
}

function setFocusMode(mode) {
  focusCfg.focus_mode = mode
  const patch = {
    focus_closest_enabled: true,
    focus_mode: mode,
  }
  if ((mode === 'PINNED' || mode === 'BOTH') && !focusCfg.pinned_speaker_id) {
    focusCfg.pinned_speaker_id = vocalTargets.value[1]?.speaker_id || vocalTargets.value[0]?.speaker_id || 'PERSON_DELTA'
    patch.pinned_speaker_id = focusCfg.pinned_speaker_id
  }
  pushFocusConfig(patch)
}

function pinSpeakerId(spkId) {
  focusCfg.pinned_speaker_id = spkId
  if (focusCfg.focus_mode === 'AUTO') {
    focusCfg.focus_mode = 'BOTH'
  }
  pushFocusConfig({
    focus_closest_enabled: true,
    focus_mode: focusCfg.focus_mode,
    pinned_speaker_id: spkId,
  })
}

const originX = 210
const originY = 248
const scaleM = 54

function polarToXY(rangeM, azDeg) {
  const r = Math.min(4.15, Math.max(0.15, Number(rangeM) || 1.0)) * scaleM
  const rad = ((Number(azDeg) || 0) * Math.PI) / 180
  return {
    x: originX + r * Math.sin(rad),
    y: originY - r * Math.cos(rad),
  }
}

function arcPath(rangeM, startDeg, endDeg) {
  const p1 = polarToXY(rangeM, startDeg)
  const p2 = polarToXY(rangeM, endDeg)
  const rPx = rangeM * scaleM
  return `M ${p1.x} ${p1.y} A ${rPx} ${rPx} 0 0 1 ${p2.x} ${p2.y}`
}

function sectorPath(rangeM, startDeg, endDeg) {
  const p1 = polarToXY(rangeM, startDeg)
  const p2 = polarToXY(rangeM, endDeg)
  const rPx = rangeM * scaleM
  return `M ${originX} ${originY} L ${p1.x} ${p1.y} A ${rPx} ${rPx} 0 0 1 ${p2.x} ${p2.y} Z`
}

function trailPoints(trail) {
  return trail
    .map((pt) => {
      const xy = polarToXY(pt.range_m, pt.azimuth_deg)
      return `${xy.x.toFixed(1)},${xy.y.toFixed(1)}`
    })
    .join(' ')
}

function formatAz(az) {
  const n = Math.round(Number(az) || 0)
  return (n >= 0 ? '+' : '') + n + '°'
}
</script>

<style scoped>
.sub-caption {
  font-size: 0.78rem;
  color: var(--text-secondary);
  margin-top: 2px;
}
.focus-pill {
  color: #7ee787;
  border-color: rgba(63, 185, 80, 0.45);
  background: rgba(63, 185, 80, 0.12);
}
.focus-banner {
  margin-bottom: 8px;
  padding: 6px 10px;
  border-radius: 6px;
  background: rgba(63, 185, 80, 0.14);
  border: 1px solid rgba(63, 185, 80, 0.4);
  color: #7ee787;
  font-size: 0.74rem;
}
.radar-canvas-box {
  background: #090d14;
  border: 1px solid #1c2739;
  border-radius: 10px;
  padding: 8px 10px;
}
.radar-svg {
  width: 100%;
  height: auto;
  display: block;
}
.ring-lbl {
  fill: #5f6c7e;
  font-size: 9.5px;
}
.focus-panel {
  margin-top: 9px;
  padding: 9px 11px;
  border-radius: 9px;
  background: linear-gradient(180deg, rgba(16, 33, 25, 0.55) 0%, #0b111b 100%);
  border: 1px solid rgba(63, 185, 80, 0.35);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.fp-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.fp-title {
  font-size: 0.76rem;
  font-weight: 700;
  color: #7ee787;
}
.fp-controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 0.72rem;
}
.chk-lbl {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: #e6edf3;
  cursor: pointer;
}
.pin-select {
  background: #0d1522;
  color: #c9d1d9;
  border: 1px solid #263850;
  border-radius: 5px;
  padding: 3px 7px;
  font-size: 0.7rem;
}
.pin-pill {
  color: #d2a8ff;
  border-color: rgba(163, 113, 247, 0.5);
  background: rgba(163, 113, 247, 0.14);
}
.mode-seg {
  display: inline-flex;
  border: 1px solid #263850;
  border-radius: 6px;
  overflow: hidden;
  background: #0b121e;
}
.m-btn {
  background: transparent;
  color: #9ca3af;
  border: none;
  border-right: 1px solid #1e2d42;
  padding: 3px 8px;
  font-size: 0.68rem;
  cursor: pointer;
}
.m-btn:last-child {
  border-right: none;
}
.m-btn.active {
  background: rgba(63, 185, 80, 0.22);
  color: #7ee787;
  font-weight: 700;
}
.pin-pills-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 0.68rem;
  padding: 4px 0 2px;
}
.pin-lbl {
  color: #d2a8ff;
  font-weight: 700;
}
.pin-id-pill {
  background: #101827;
  color: #9ca3af;
  border: 1px solid #28374e;
  border-radius: 99px;
  padding: 2px 8px;
  font-size: 0.66rem;
  cursor: pointer;
}
.pin-id-pill:hover {
  border-color: #a371f7;
  color: #e6edf3;
}
.pin-id-pill.active {
  background: rgba(163, 113, 247, 0.24);
  border-color: #a371f7;
  color: #f3e8ff;
  font-weight: 700;
}
.fp-sliders {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 7px 12px;
  font-size: 0.7rem;
  color: #9ca3af;
}
.fp-sliders label {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.fp-sliders b {
  color: #e6edf3;
}
.fp-sliders input[type='range'] {
  accent-color: #3fb950;
}
.fp-sub {
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  padding-top: 5px;
  border-top: 1px solid rgba(63, 185, 80, 0.2);
  font-size: 0.68rem;
  color: #8b949e;
}
.fp-sub b {
  color: #c9d1d9;
}
.spatial-list {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 7px;
  max-height: 250px;
  overflow-y: auto;
}
.live-fix-banner {
  background: #0e1724;
  border: 1px solid #223552;
  border-radius: 7px;
  padding: 7px 10px;
  font-size: 0.74rem;
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}
.target-row {
  background: #0d121a;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 8px 11px;
}
.locked-row {
  border-color: rgba(63, 185, 80, 0.6);
  background: rgba(15, 34, 24, 0.55);
}
.lock-chip {
  font-size: 0.62rem;
  background: rgba(63, 185, 80, 0.2);
  color: #7ee787;
  border: 1px solid rgba(63, 185, 80, 0.45);
  padding: 1px 6px;
  border-radius: 99px;
  margin-left: 5px;
}
.radar-target {
  cursor: pointer;
}
.radar-target:hover circle:first-of-type {
  fill-opacity: 0.35;
}
.clickable-row {
  cursor: pointer;
  transition: border-color 0.15s ease, transform 0.12s ease;
}
.clickable-row:hover {
  border-color: #58a6ff;
  transform: translateY(-1px);
}
.head-badges {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}
.share-hint {
  font-size: 0.65rem;
  color: #d2a8ff;
  background: rgba(210, 168, 255, 0.12);
  border: 1px solid rgba(210, 168, 255, 0.32);
  padding: 1px 7px;
  border-radius: 99px;
}
.target-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 4px;
  font-size: 0.8rem;
}
.zone-badge {
  font-size: 0.68rem;
  padding: 2px 7px;
  border-radius: 99px;
  background: #172132;
  color: #79c0ff;
}
.target-metrics {
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 0.74rem;
  color: var(--text-secondary);
}
.tiers-stack {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.tier-box {
  background: #0d121a;
  border: 1px solid var(--border-subtle);
  border-radius: 9px;
  padding: 11px 13px;
}
.highlight-tier {
  border-color: rgba(63, 185, 80, 0.45);
  background: rgba(14, 30, 22, 0.55);
}
.faint-steps {
  margin: 6px 0 0;
  padding-left: 18px;
  font-size: 0.77rem;
  color: #c9d1d9;
  line-height: 1.5;
}
.tier-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
  flex-wrap: wrap;
  gap: 6px;
}
.tier-badge {
  font-size: 0.7rem;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 5px;
  background: #1c2638;
  color: #79c0ff;
}
.tier-badge.live {
  background: rgba(63, 185, 80, 0.18);
  color: #3fb950;
  border: 1px solid rgba(63, 185, 80, 0.4);
}
.tier-acc {
  font-size: 0.72rem;
  color: #f0883e;
}
.tier-title {
  font-weight: 700;
  font-size: 0.88rem;
  margin-bottom: 3px;
}
.tier-hw {
  font-size: 0.72rem;
  color: #8b949e;
  margin-bottom: 5px;
}
.tier-desc {
  font-size: 0.78rem;
  color: #c9d1d9;
}

@media (max-width: 640px) {
  .fp-sliders {
    grid-template-columns: 1fr;
  }
}
</style>
