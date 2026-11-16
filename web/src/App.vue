<template>
  <div class="cockpit-shell">
    <!-- TOP LIVE GNU RADIO TELEMETRY HEADER -->
    <header class="top-nav">
      <div class="brand">
        <span class="pulse-dot" :class="{ online: sseConnected }"></span>
        <div>
          <h1>GNU-LAREX <span class="thin">Vue.js Intelligence &amp; Spatial Cockpit</span></h1>
          <div class="telemetry-strip mono">
            <span>🎙️ {{ liveStatus.sensor?.sensor_label || 'Connecting GNU Radio...' }}</span>
            <span
              v-if="liveStatus.sdr_radar"
              :style="{ color: liveStatus.sdr_radar.connected ? '#3fb950' : '#f0883e', cursor: 'pointer' }"
              title="Click to hot-reconnect RTL-SDR Blog V4 (:5556) & HackRF One (:5557)"
              @click="sendControl({ reconnect_sdrs: true })"
            >
              📡 {{ liveStatus.sdr_radar.connected ? `${liveStatus.sdr_radar.device_label} (${liveStatus.sdr_radar.rf_freq_mhz} MHz)` : liveStatus.sdr_radar.device_label }}
            </span>
            <span
              v-if="liveStatus.hackrf_radar"
              :style="{ color: liveStatus.hackrf_radar.connected ? '#3fb950' : '#f0883e', cursor: 'pointer' }"
              title="Click to hot-reconnect HackRF One Wideband Stream (:5557)"
              @click="sendControl({ reconnect_sdrs: true })"
            >
              📡 {{ liveStatus.hackrf_radar.connected ? `${liveStatus.hackrf_radar.device_label} (${liveStatus.hackrf_radar.rf_freq_mhz} MHz)` : liveStatus.hackrf_radar.device_label }}
            </span>
            <span>👄 Mouth: {{ Math.round((liveStatus.mouth_articulation?.mouth_openness || 0) * 100) }}% ({{ liveStatus.mouth_articulation?.viseme || 'REST' }})</span>
            <span :style="{ color: liveStatus.gesture_whisper_decode?.low_ambient_cued ? '#3fb950' : '#d2a8ff' }">
              🤫 Subvoc Cue: {{ Math.round((liveStatus.gesture_whisper_decode?.gesture_subvoc_score || 0) * 100) }}%
            </span>
            <span>Floor: {{ liveStatus.autotune?.room_floor_dbfs ?? '--' }} dBFS</span>
            <span>F0: {{ liveStatus.autotune?.current_f0_hz || 0 }} Hz ({{ liveStatus.autotune?.musical_note || '--' }})</span>
            <span>Resp: {{ liveStatus.biometrics?.resp_bpm ?? '--' }} BPM</span>
            <span
              v-if="liveStatus.speaker_tuning?.active_speaker_profile"
              style="color: #58a6ff; cursor: pointer"
              title="Click to inspect & share active speaker's earworm"
              @click="openPersonEarworm(liveStatus.speaker_tuning.active_speaker_profile)"
            >
              🎯 Profile: {{ liveStatus.speaker_tuning.active_speaker_profile }} · β={{ liveStatus.spatial_calibration?.gcc_phat_beta ?? 0.78 }}
            </span>
            <span :style="{ color: liveStatus.biometrics?.gate_open ? '#3fb950' : '#8b949e' }">
              VAD: {{ liveStatus.biometrics?.gate_open ? liveStatus.biometrics?.band_role : 'IDLE' }}
            </span>
            <span
              :style="{ color: liveStatus.talkback?.talkback_enabled ? '#3fb950' : '#f0883e', cursor: 'pointer' }"
              @click="scrollToTalkback"
              title="Click to jump to Mid-Air Whisper Talkback Studio"
            >
              {{ liveStatus.talkback?.talkback_enabled ? '🔊 Talkback: ACTIVE' : '🔇 Talkback: OFF (Option)' }}
            </span>
            <span
              style="color: #2dd4bf; cursor: pointer"
              @click="openPersonEarworm('PERSON_TYPIST')"
              title="Click to inspect dedicated PERSON_TYPIST (48 kHz Acoustic Typing Only)"
            >
              ⌨️ PERSON_TYPIST: {{ liveStatus.markov_typing?.typing_person?.total_keystrokes_captured ?? 0 }} keys ({{ liveStatus.markov_typing?.typing_person?.live_wpm ?? 0 }} WPM)
            </span>
            <span
              style="color: #f778ba; cursor: pointer"
              @click="openPersonEarworm('DEVICE_CELLPHONE')"
              title="Click to inspect clickable DEVICE_CELLPHONE character (LRA Haptic + UI Tick + PMIC)"
            >
              📱 CELLPHONE: {{ liveStatus.prespeech_electronics?.electronics?.characters?.DEVICE_CELLPHONE?.clicks_captured ?? 0 }} clicks
            </span>
            <span
              style="color: #eab308; cursor: pointer"
              @click="openPersonEarworm('DEVICE_MEMS')"
              title="Click to inspect clickable DEVICE_MEMS character (14.5-23.8 kHz Ultrasonic MEMS)"
            >
              🔬 MEMS: {{ liveStatus.prespeech_electronics?.electronics?.characters?.DEVICE_MEMS?.clicks_captured ?? 0 }} clicks
            </span>
            <span
              style="color: #38bdf8; cursor: pointer"
              @click="openPersonEarworm('OTHER_ROOM_SUBLEVEL')"
              title="Click to inspect OTHER_ROOM_SUBLEVEL (Mid-Air Piggybacked Non-Occupant Acoustics + SilentReadingDetector)"
            >
              🧱 OTHER-ROOM: {{ liveStatus.reading_piggyback?.piggyback?.total_piggyback_captures ?? 0 }} · 📖 {{ liveStatus.reading_piggyback?.piggyback?.silent_reading?.state || 'IDLE' }}
            </span>
            <span
              :style="{
                color: (liveStatus.reading_piggyback?.piggyback?.three_state_vad?.config?.auto_play_out_loud ?? true) ? '#3fb950' : '#f0883e',
                cursor: 'pointer',
              }"
              title="Click to toggle Auto-Speak in Browser whenever ThreeStateVADRouter enters READING"
              @click="toggleHeaderAutoSpeak"
            >
              🎧 Auto-Speak Reading: {{ (liveStatus.reading_piggyback?.piggyback?.three_state_vad?.config?.auto_play_out_loud ?? true) ? 'ON' : 'MANUAL' }}
            </span>
            <span
              style="color: #d2a8ff; cursor: pointer"
              title="Click to cycle Room Faint-Focus Spotlight Mode: BOTH (Auto-Closest + Pinned) -> AUTO -> PINNED"
              @click="cycleHeaderFocusMode"
            >
              🎯 Spotlight: {{ liveStatus.reading_piggyback?.piggyback?.closest_focus?.focus_mode || 'BOTH' }}
              ({{ liveStatus.reading_piggyback?.piggyback?.closest_focus?.closest_speaker_id || 'PERSON_BETA' }}
              <template v-if="(liveStatus.reading_piggyback?.piggyback?.closest_focus?.focus_mode || 'BOTH') !== 'AUTO' && liveStatus.reading_piggyback?.piggyback?.closest_focus?.pinned_speaker_id">
                + 📌{{ liveStatus.reading_piggyback?.piggyback?.closest_focus?.pinned_speaker_id }}
              </template>)
            </span>
            <span
              :style="{
                color: (liveStatus.presence_voicematch?.presence_state || presenceVoicematchFallback.presence_state) === 'ARRIVED_COMPARED' ? '#3fb950' : '#ffa657',
                cursor: 'pointer',
              }"
              title="Click to jump to PERSON_DELTA Departure/Arrival Biometric Diff, Who-Is-Who Voice Match & UltraMic Ambiance Monitor"
              @click="scrollToPresence"
            >
              🚪 {{ liveStatus.presence_voicematch?.owner_speaker_id || 'PERSON_DELTA' }}:
              {{
                (liveStatus.presence_voicematch?.presence_state || presenceVoicematchFallback.presence_state) === 'ARRIVED_COMPARED'
                  ? `ARRIVED (${liveStatus.presence_voicematch?.arrival_comparison?.voiceprint_similarity_pct ?? 95}% MATCH)`
                  : 'AWAY · ARMED'
              }}
            </span>
            <span
              style="color: #7ee787; cursor: pointer"
              title="Click to jump to 0.5–4.0 Hz Delta Brainwave Avatar, VAD Motion Earworm Associator & Feelings × Predictability × Movement Correlator"
              @click="scrollToDeltaAvatar"
            >
              🧘 Delta: {{ liveStatus.delta_avatar?.delta_wave?.peak_hz ?? deltaAvatarFallback.delta_wave?.peak_hz ?? 1.55 }} Hz
              ({{ liveStatus.delta_avatar?.delta_wave?.emotional_reset_pct ?? deltaAvatarFallback.delta_wave?.emotional_reset_pct ?? 76 }}% Reset ·
              {{ liveStatus.delta_avatar?.vad_motion?.movement_state || deltaAvatarFallback.vad_motion?.movement_state || 'STILL_ANCHORED' }})
            </span>
            <span
              style="color: #58a6ff; cursor: pointer"
              title="Click to jump to NightSweep Data Forensics, Hallucination Firewall & Feature Recommendation Lab"
              @click="scrollToNightSweepLab"
            >
              🛰️ NightSweep Lab: {{ liveStatus.forensics_config?.scrub_hallucinations !== false ? 'FIREWALL ON' : 'RAW' }}
              · {{ liveStatus.forensics_config?.active_entrainment_band || 'DELTA' }} SSB
            </span>
            <span
              style="color: #ff7b72; cursor: pointer"
              title="Click to jump to 88–108 MHz Superheterodyne FM Band & Pirate Station Scanner Extension"
              @click="scrollToFmScanner"
            >
              📻 FM Scanner: {{ liveStatus.fm_scanner?.kpis?.total_stations ?? 10 }} st ({{ liveStatus.fm_scanner?.kpis?.flagged_pirate_count ?? 4 }} pirate)
              · {{ liveStatus.fm_scanner?.pinned_bistatic_freq_mhz ?? 100.1 }} MHz
            </span>
            <span
              style="color: #38bdf8; cursor: pointer"
              title="Click to jump to 19.0–22.0 kHz FHSS Phase-Continuous Ultrasonic Sonar Bridge & Quadrature I/Q Reflection Loop"
              @click="scrollToFhssSonar"
            >
              🔊 FHSS Sonar: {{ liveStatus.fhss_sonar?.active_carrier_khz ?? 20.5 }} kHz
              (Hop #{{ liveStatus.fhss_sonar?.current_hop_idx ?? 6 }} · Δd={{ liveStatus.fhss_sonar?.kpis?.mean_muscle_displacement_um ?? 42.8 }}µm)
            </span>
            <span
              style="color: #34d399; cursor: pointer"
              title="Click to jump to Multi-Mode Sliding-Window FrequencyDetector (Goertzel + CFAR Parabolic FFT + Fractional ZCR)"
              @click="scrollToFreqDetector"
            >
              🎯 FreqDetector: {{ liveStatus.frequency_detector?.kpis?.goertzel_hit_count ?? 18 }} Goertzel
              · {{ liveStatus.frequency_detector?.kpis?.fft_sweep_frame_count ?? 42 }} FFT ({{ liveStatus.frequency_detector?.kpis?.zcr_mean_estimated_hz ?? 880.0 }} Hz ZCR)
            </span>
            <span
              :style="{
                color: liveStatus.starter_guide?.summary?.any_nightsweep_missing ? '#ffa657' : '#7ee787',
                cursor: 'pointer',
              }"
              title="Click to jump to NightSweep Models, Modals & Full Dependency Starter Guide"
              @click="scrollToStarterGuide"
            >
              🧰 Starter Guide &amp; Deps: {{ liveStatus.starter_guide?.summary?.ready_count ?? 16 }}/{{ liveStatus.starter_guide?.summary?.total_dependencies ?? 17 }} READY
            </span>
          </div>
        </div>
      </div>

      <div class="header-actions">
        <div class="seg-group">
          <button
            class="seg-btn"
            :class="{ active: scope === 'active' }"
            @click="setScope('active')"
            title="Clean enrolled roster from current active GNU Radio session"
          >
            Current Session
          </button>
          <button
            class="seg-btn"
            :class="{ active: scope === 'all' }"
            @click="setScope('all')"
            title="Include all historical session files in window"
          >
            All Ledgers
          </button>
        </div>

        <div class="seg-group">
          <button
            v-for="h in [2, 6, 24]"
            :key="h"
            class="seg-btn"
            :class="{ active: hours === h }"
            @click="setHours(h)"
          >
            {{ h }}h
          </button>
        </div>

        <button class="btn btn-primary" @click="triggerAutotune">
          ⚡ Re-Autotune GNU Radio
        </button>
      </div>
    </header>

    <!-- LIVE TOAST BANNER WHEN NEW UTTERANCE DECODED -->
    <div v-if="lastToast" class="live-toast mono">
      <span>🟢 LIVE WORD DECODE</span>
      <strong
        style="color: #58a6ff; cursor: pointer; text-decoration: underline"
        @click="openPersonEarworm(lastToast.speaker_id)"
      >
        🎧 {{ lastToast.speaker_id }}
      </strong>
      <span>({{ lastToast.range_m }}m, {{ lastToast.role }}):</span>
      <span style="color: #7ee787">"{{ lastToast.text }}"</span>
      <button
        v-if="lastToast.audio_url"
        type="button"
        class="seg-btn mono"
        style="margin-left: auto; border-color: #3fb950; color: #7ee787"
        @click="playToastAudio(lastToast.audio_url)"
      >
        ▶ Replay Out-Loud WAV
      </button>
    </div>

    <!-- QUICK PERSON SWITCHER & RECENT SHARED EARWORMS BAR -->
    <div v-if="quickbarSpeakers.length" class="person-quickbar mono">
      <div class="pq-left">
        <span class="pq-lbl">👥 Click Any Person to Inspect &amp; Share Earworm:</span>
        <button
          v-for="spk in quickbarSpeakers"
          :key="spk.speaker_id"
          type="button"
          class="pq-pill"
          :style="{ borderColor: spk.color, color: spk.color }"
          @click="openPersonEarworm(spk.speaker_id)"
        >
          {{ characterIcon(spk.speaker_id) }} {{ spk.speaker_id }}
          <span v-if="spk.speaker_id === 'PERSON_TYPIST'" class="pq-hook" style="color: #2dd4bf">
            (TYPING ONLY)
          </span>
          <span v-else-if="spk.speaker_id === 'DEVICE_CELLPHONE'" class="pq-hook" style="color: #f778ba">
            (CELLPHONE CLICK)
          </span>
          <span v-else-if="spk.speaker_id === 'DEVICE_MEMS'" class="pq-hook" style="color: #eab308">
            (MEMS ULTRASONIC)
          </span>
          <span v-else-if="spk.speaker_id === 'OTHER_ROOM_SUBLEVEL'" class="pq-hook" style="color: #38bdf8">
            (MID-AIR PIGGYBACK)
          </span>
          <span v-else-if="sharedEarwormData.speakers?.[spk.speaker_id]?.primary_earworm_phrase" class="pq-hook">
            "{{ sharedEarwormData.speakers[spk.speaker_id].primary_earworm_phrase }}"
          </span>
        </button>
      </div>
      <div v-if="sharedEarwormData.recent_shares?.length" class="pq-right">
        <span class="pq-lbl">🔗 Shared ({{ sharedEarwormData.recent_shares.length }}):</span>
        <button
          type="button"
          class="pq-share-last"
          @click="openSavedShare(sharedEarwormData.recent_shares[0])"
        >
          {{ sharedEarwormData.recent_shares[0].speaker_id }}: "{{ sharedEarwormData.recent_shares[0].earworm_phrase }}"
        </button>
      </div>
    </div>

    <!-- MAIN 2-COLUMN ANALYTICS + SPATIAL RADAR GRID -->
    <main class="main-grid">
      <!-- NIGHTSWEEP MODELS, MODALS & FULL DEPENDENCY STARTER GUIDE -->
      <NightSweepStarterGuidePanel
        :initialData="liveStatus.starter_guide || {}"
        :forceOpen="starterGuideForceOpen"
        @select-speaker="openPersonEarworm"
        @updated="refreshAnalytics"
      />

      <!-- NIGHTSWEEP SIGNAL-INTELLIGENCE EMPIRICAL DATA FORENSICS & FEATURE RECOMMENDATION LAB -->
      <NightSweepFeatureLabPanel
        @select-speaker="openPersonEarworm"
        @open-starter-guide="scrollToStarterGuide"
        @updated="refreshAnalytics"
      />

      <!-- 88-108 MHZ SUPERHETERODYNE FM BAND & PIRATE STATION SCANNER EXTENSION -->
      <FMPirateScannerExtension
        :data="liveStatus.fm_scanner || {}"
        @updated="refreshAnalytics"
      />

      <!-- 19.0-22.0 KHZ FHSS PHASE-CONTINUOUS ULTRASONIC SONAR TRANSCEIVER BRIDGE -->
      <FHSSSonarBridgeExtension
        :data="liveStatus.fhss_sonar || {}"
        @updated="refreshAnalytics"
      />

      <!-- MULTI-MODE SLIDING-WINDOW FREQUENCY DETECTOR (GOERTZEL + CFAR PARABOLIC FFT + FRACTIONAL ZCR) -->
      <FrequencyDetectorExtension
        :data="liveStatus.frequency_detector || {}"
        @updated="refreshAnalytics"
      />

      <!-- PERSON_DELTA DEPARTURE / ARRIVAL BIOMETRIC DIFF, "WHO IS WHO" VOICE MATCH & ULTRAMIC AMBIANCE / UNKNOWN SUBVOC -->
      <PresenceAndVoiceMatchPanel
        :data="liveStatus.presence_voicematch || presenceVoicematchFallback"
        @select-speaker="openPersonEarworm"
        @updated="refreshAnalytics"
      />

      <!-- 0.5–4.0 HZ DELTA BRAINWAVE AVATAR, VAD MOTION EARWORM ASSOCIATOR & FEELINGS × PREDICTABILITY × MOVEMENT CORRELATOR -->
      <DeltaAvatarWidget
        :data="liveStatus.delta_avatar || deltaAvatarFallback"
        @select-speaker="openPersonEarworm"
        @updated="refreshAnalytics"
      />

      <!-- TOP SPLIT: WORDS-PER-HOUR + 3D THREE.JS AVATAR ROOM / 2D POLAR RADAR & CLOSEST FAINT FOCUS -->
      <div class="top-split">
        <WordsPerHourChart
          :buckets="wphData.buckets"
          :speakers="wphData.speakers"
          :kpis="wphData.kpis"
          v-model:bucketMinutes="bucketMinutes"
          @select-speaker="openPersonEarworm"
        />

        <SpatialPositionRadar
          :targets="radarData.targets"
          :liveSpatial="liveStatus.live_spatial || {}"
          :tiersGuide="radarData.tiers_guide"
          :roomCriticalDist="liveStatus.spatial_calibration?.room_critical_dist_m || 1.45"
          :gateOpen="Boolean(liveStatus.biometrics?.gate_open)"
          :typistSector="radarData.typist_desk_sector || liveStatus.markov_typing?.typing_person?.config || {}"
          :closestFocus="radarData.closest_focus || liveStatus.reading_piggyback?.piggyback?.closest_focus || {}"
          :threeStateVad="radarData.three_state_vad || liveStatus.reading_piggyback?.piggyback?.three_state_vad || {}"
          @calibrate-rc="onCalibrateRc"
          @select-speaker="openPersonEarworm"
          @focus-updated="refreshAnalytics"
        />
      </div>

      <!-- SILENT READING DETECTOR (OCCUPANT STILLNESS VETO) & MID-AIR PIGGYBACKED OTHER-ROOM SUBLEVEL CAPTURE -->
      <SilentReadingAndPiggybackPanel
        :data="liveStatus.reading_piggyback || readingPiggybackFallback"
        @select-speaker="openPersonEarworm"
        @updated="refreshAnalytics"
      />

      <!-- PRE-SPEECH EARWORM PRE-HEAR (50-200 MS) & CLICKABLE ELECTRONIC / MEMS CHARACTERS -->
      <PreSpeechAndElectronicsPanel
        :data="liveStatus.prespeech_electronics || prespeechElectronicsFallback"
        @select-speaker="openPersonEarworm"
        @updated="refreshAnalytics"
      />

      <!-- PER-SENTENCE MARKOV -> EARWORM DELTA INSPECTOR & DEDICATED PERSON_TYPIST CAPTURE -->
      <MarkovAndTypingPanel
        :markovTyping="liveStatus.markov_typing || markovTypingFallback"
        @select-speaker="openPersonEarworm"
        @updated="refreshAnalytics"
      />

      <!-- OPT-IN MID-AIR WHISPER TALKBACK & EARWORM DELTA AUTO-CONVERSATION STUDIO -->
      <WhisperTalkbackPanel
        :talkback="liveStatus.talkback || talkbackFallback"
        :prefillDraft="talkbackPrefill"
        @select-speaker="openPersonEarworm"
      />

      <!-- LIVE BREATH & MOUTH ARTICULATION + RTL-SDR RADAR PANEL -->
      <MouthArticulationPanel
        :mouth="liveStatus.mouth_articulation || {}"
        :sdrRadar="liveStatus.sdr_radar || {}"
        :autotune="liveStatus.autotune || {}"
        :speakers="wphData.speakers"
        @tune-rf="onTuneRf"
        @select-speaker="openPersonEarworm"
      />

      <!-- MOUTH-GESTURE + SUBVOCALIZATION LOW-AMBIENT WHISPER DECODE & OVERNIGHT REPORT -->
      <OvernightWhisperReportPanel
        :report="overnightWhisperData"
        :gestureDecode="liveStatus.gesture_whisper_decode || {}"
        :mouth="liveStatus.mouth_articulation || {}"
        @apply-sensitivity="onApplyPreset"
        @select-speaker="openPersonEarworm"
      />

      <!-- 4-SENSOR ZMQ WHISPER PHONEME & EARWORM PREDICTOR + NIGHTSWEEP ENHANCED CONFIGS -->
      <WhisperEarwormPanel
        :earworm="liveStatus.whisper_earworm || {}"
        :sharedEarworms="sharedEarwormData"
        @apply-config="onApplyPreset"
        @select-speaker="openPersonEarworm"
      />

      <!-- OLLAMA SIGNAL INTELLIGENCE REFINER & ENHANCEMENT ADVISOR -->
      <OllamaAdvisorPanel
        :hours="hours"
        :scope="scope"
        @apply-preset="onApplyPreset"
        @select-speaker="openPersonEarworm"
        @open-starter-guide="scrollToStarterGuide"
      />

      <!-- PER-SPEAKER BIOMETRIC & WORD SHOWCASE -->
      <SpeakerShowcaseGrid
        :speakers="wphData.speakers"
        :sharedEarworms="sharedEarwormData"
        @select-speaker="openPersonEarworm"
      />
    </main>

    <!-- CLICKABLE PERSON DOSSIER & SHARED EARWORM STUDIO MODAL -->
    <PersonEarwormModal
      :speakerId="selectedSpeakerId"
      :sharedData="sharedEarwormData"
      :speakers="wphData.speakers"
      :initialSharePacket="initialSharePacket"
      :initialPhrase="selectedPhrase"
      :starterGuide="liveStatus.starter_guide || {}"
      @close="closePersonEarworm"
      @select-speaker="openPersonEarworm"
      @shared-created="refreshAnalytics"
      @talkback-speaker="onTalkbackSpeaker"
      @open-starter-guide="onModalOpenStarterGuide"
    />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import WordsPerHourChart from './components/WordsPerHourChart.vue'
import SpatialPositionRadar from './components/SpatialPositionRadar.vue'
import MouthArticulationPanel from './components/MouthArticulationPanel.vue'
import OvernightWhisperReportPanel from './components/OvernightWhisperReportPanel.vue'
import WhisperEarwormPanel from './components/WhisperEarwormPanel.vue'
import SpeakerShowcaseGrid from './components/SpeakerShowcaseGrid.vue'
import OllamaAdvisorPanel from './components/OllamaAdvisorPanel.vue'
import PersonEarwormModal from './components/PersonEarwormModal.vue'
import WhisperTalkbackPanel from './components/WhisperTalkbackPanel.vue'
import MarkovAndTypingPanel from './components/MarkovAndTypingPanel.vue'
import PreSpeechAndElectronicsPanel from './components/PreSpeechAndElectronicsPanel.vue'
import SilentReadingAndPiggybackPanel from './components/SilentReadingAndPiggybackPanel.vue'
import PresenceAndVoiceMatchPanel from './components/PresenceAndVoiceMatchPanel.vue'
import DeltaAvatarWidget from './components/DeltaAvatarWidget.vue'
import NightSweepFeatureLabPanel from './components/NightSweepFeatureLabPanel.vue'
import NightSweepStarterGuidePanel from './components/NightSweepStarterGuidePanel.vue'
import FMPirateScannerExtension from './components/FMPirateScannerExtension.vue'
import FHSSSonarBridgeExtension from './components/FHSSSonarBridgeExtension.vue'
import FrequencyDetectorExtension from './components/FrequencyDetectorExtension.vue'

const hours = ref(6)
const bucketMinutes = ref(15)
const scope = ref('active')
const sseConnected = ref(false)
const liveStatus = ref({})
const lastToast = ref(null)

const wphData = ref({
  kpis: {},
  buckets: [],
  speakers: [],
})

const radarData = ref({
  targets: [],
  tiers_guide: [],
})

const overnightWhisperData = ref({})
const sharedEarwormData = ref({
  cross_speaker_earworms: [],
  speakers: {},
  recent_shares: [],
})
const selectedSpeakerId = ref('')
const selectedPhrase = ref('')
const initialSharePacket = ref(null)
const talkbackFallback = ref({})
const talkbackPrefill = ref(null)
const markovTypingFallback = ref({})
const prespeechElectronicsFallback = ref({})
const readingPiggybackFallback = ref({})
const presenceVoicematchFallback = ref({})
const deltaAvatarFallback = ref({})
const starterGuideForceOpen = ref(false)

const quickbarSpeakers = computed(() => {
  if (wphData.value?.speakers?.length) return wphData.value.speakers
  const map = sharedEarwormData.value?.speakers || {}
  return Object.values(map)
})

function characterIcon(id) {
  if (id === 'PERSON_TYPIST') return '⌨️'
  if (id === 'DEVICE_CELLPHONE') return '📱'
  if (id === 'DEVICE_MEMS') return '🔬'
  if (id === 'OTHER_ROOM_SUBLEVEL') return '🧱'
  return '🎧'
}

let evtSource = null
let pollTimer = null

function scrollToTalkback() {
  const el = document.getElementById('whisper-talkback-studio')
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function scrollToPresence() {
  const el = document.getElementById('presence-voicematch-studio')
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function scrollToDeltaAvatar() {
  const el = document.getElementById('delta-avatar-studio')
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function scrollToNightSweepLab() {
  const el = document.getElementById('nightsweep-feature-lab')
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function scrollToFmScanner() {
  const el = document.getElementById('fm-pirate-scanner-ext')
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function scrollToFhssSonar() {
  const el = document.getElementById('fhss-sonar-bridge-ext')
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function scrollToFreqDetector() {
  const el = document.getElementById('frequency-detector-ext')
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function scrollToStarterGuide() {
  starterGuideForceOpen.value = false
  setTimeout(() => {
    starterGuideForceOpen.value = true
    const el = document.getElementById('nightsweep-starter-guide')
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, 30)
}

function onModalOpenStarterGuide() {
  closePersonEarworm()
  scrollToStarterGuide()
}

function onTalkbackSpeaker(payload) {
  closePersonEarworm()
  talkbackPrefill.value = payload
  setTimeout(scrollToTalkback, 80)
}

function openPersonEarworm(payload) {
  if (!payload) return
  if (typeof payload === 'string') {
    selectedSpeakerId.value = payload
    selectedPhrase.value = ''
    initialSharePacket.value = null
  } else if (typeof payload === 'object' && payload.speakerId) {
    selectedSpeakerId.value = payload.speakerId
    selectedPhrase.value = payload.phrase || ''
    initialSharePacket.value = null
  }
}

function openSavedShare(pkt) {
  if (!pkt) return
  initialSharePacket.value = pkt
  selectedPhrase.value = pkt.earworm_phrase || ''
  selectedSpeakerId.value = pkt.speaker_id || 'PERSON_ALPHA'
}

function closePersonEarworm() {
  selectedSpeakerId.value = ''
  selectedPhrase.value = ''
  initialSharePacket.value = null
}

async function refreshAnalytics() {
  try {
    const [wRes, rRes, oRes, sRes, tbRes, mtRes, pseRes, rpbRes, pvmRes, daRes] = await Promise.all([
      fetch(`/api/analytics/words-per-hour?hours=${hours.value}&bucket_minutes=${bucketMinutes.value}&scope=${scope.value}`),
      fetch(`/api/spatial/radar?hours=${hours.value}&scope=${scope.value}`),
      fetch(`/api/analytics/overnight-whispers?hours=16&scope=${scope.value}`),
      fetch(`/api/earworm/shared?hours=16&scope=${scope.value}`),
      fetch('/api/talkback/status'),
      fetch('/api/markov-typing/status'),
      fetch('/api/prespeech-electronics/status'),
      fetch('/api/reading-piggyback/status'),
      fetch('/api/presence-voicematch/status'),
      fetch('/api/delta-avatar/status'),
    ])
    if (wRes.ok) wphData.value = await wRes.json()
    if (rRes.ok) {
      const rJson = await rRes.json()
      radarData.value = rJson
      if (rJson.status) liveStatus.value = rJson.status
    }
    if (oRes.ok) overnightWhisperData.value = await oRes.json()
    if (sRes.ok) sharedEarwormData.value = await sRes.json()
    if (tbRes.ok) talkbackFallback.value = await tbRes.json()
    if (mtRes.ok) markovTypingFallback.value = await mtRes.json()
    if (pseRes.ok) prespeechElectronicsFallback.value = await pseRes.json()
    if (rpbRes.ok) readingPiggybackFallback.value = await rpbRes.json()
    if (pvmRes.ok) presenceVoicematchFallback.value = await pvmRes.json()
    if (daRes.ok) deltaAvatarFallback.value = await daRes.json()
  } catch (err) {
    console.error('Analytics fetch error:', err)
  }
}

function connectSSE() {
  try {
    evtSource = new EventSource('/api/stream')
    evtSource.onopen = () => {
      sseConnected.value = true
    }
    evtSource.addEventListener('telemetry', (ev) => {
      sseConnected.value = true
      liveStatus.value = JSON.parse(ev.data)
    })
    evtSource.addEventListener('utterance', (ev) => {
      const rec = JSON.parse(ev.data)
      lastToast.value = {
        speaker_id: rec.speaker?.speaker_id || 'PERSON_ALPHA',
        range_m: rec.spatial?.range_m ?? 1.1,
        role: (rec.vad_biometrics?.band_role || '').includes('WHISPER') ? 'WHISPER' : 'VOICED',
        text: rec.segment?.ollama_reconstructed || rec.segment?.raw_transcript || '',
      }
      refreshAnalytics()
    })
    evtSource.addEventListener('talkback', (ev) => {
      const msg = JSON.parse(ev.data)
      if (msg.direction === 'OUTBOUND_TALKBACK') {
        lastToast.value = {
          speaker_id: msg.speaker_id || 'PERSON_DELTA',
          range_m: 1.0,
          role: 'MID-AIR TALKBACK',
          text: msg.text || '',
        }
        const autoPlay = liveStatus.value?.talkback?.auto_play_browser !== false
        if (autoPlay && msg.audio_url) {
          try {
            const aud = new Audio(msg.audio_url)
            aud.volume = 0.65
            aud.play().catch(() => {})
          } catch (_) {}
        }
      }
      fetch('/api/talkback/status')
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => {
          if (d) talkbackFallback.value = d
        })
        .catch(() => {})
    })
    evtSource.addEventListener('prespeech', (ev) => {
      const ps = JSON.parse(ev.data)
      lastToast.value = {
        speaker_id: 'PRE-HEAR EARWORM',
        range_m: 0.9,
        role: `${ps.event || 'PRE_SPEECH'} (-${ps.lead_time_est_ms || 120}ms)`,
        text: `${ps.pre_heard_hook || ''} ${ps.predicted_next_token ? '→ ' + ps.predicted_next_token : ''}`.trim(),
      }
      const autoPlay = Boolean(liveStatus.value?.prespeech_electronics?.prespeech?.config?.auto_play_pre_hear)
      if (autoPlay && ps.audio_url) {
        try {
          const aud = new Audio(ps.audio_url)
          aud.volume = 0.65
          aud.play().catch(() => {})
        } catch (_) {}
      }
      fetch('/api/prespeech-electronics/status')
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => {
          if (d) prespeechElectronicsFallback.value = d
        })
        .catch(() => {})
    })
    evtSource.addEventListener('reading_outloud', (ev) => {
      const ol = JSON.parse(ev.data)
      lastToast.value = {
        speaker_id: ol.speaker_id || 'PERSON_ALPHA',
        range_m: 0.55,
        role: `READING OUT-LOUD (~${ol.estimated_wpm || 200} WPM)`,
        text: ol.spoken_text || '',
        audio_url: ol.audio_url || '',
      }
      const autoPlay =
        liveStatus.value?.reading_piggyback?.piggyback?.three_state_vad?.config?.auto_play_out_loud !== false
      if (autoPlay && ol.audio_url) {
        try {
          const aud = new Audio(ol.audio_url)
          aud.volume = 0.8
          aud.play().catch(() => {
            if (typeof window !== 'undefined' && window.speechSynthesis && ol.spoken_text) {
              const utt = new SpeechSynthesisUtterance(ol.spoken_text)
              utt.rate = Math.min(1.8, Math.max(0.85, (ol.estimated_wpm || 200) / 185))
              window.speechSynthesis.speak(utt)
            }
          })
        } catch (_) {}
      }
      fetch('/api/reading-piggyback/status')
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => {
          if (d) readingPiggybackFallback.value = d
        })
        .catch(() => {})
    })
    evtSource.addEventListener('unknown_subvoc', (ev) => {
      const us = JSON.parse(ev.data)
      lastToast.value = {
        speaker_id: 'UNKNOWN_SUBVOC',
        range_m: us.range_m ?? 1.4,
        role: `OOD NOVELTY ${us.ood_novelty_pct || 52}%`,
        text: `Low-ambient subvoc (~${us.estimated_vtl_cm || 16}cm VTL, ${us.peak_subvoc_hz || 2800} Hz)`,
        audio_url: us.audio_url || '',
      }
      fetch('/api/presence-voicematch/status')
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => {
          if (d) presenceVoicematchFallback.value = d
        })
        .catch(() => {})
    })
    evtSource.addEventListener('arrival_compared', (ev) => {
      const ac = JSON.parse(ev.data)
      lastToast.value = {
        speaker_id: ac.speaker_id || 'PERSON_DELTA',
        range_m: ac.arrival?.range_m ?? 0.68,
        role: `${ac.verdict || 'ARRIVAL_VERIFIED'} (${ac.voiceprint_similarity_pct || 95}%)`,
        text: (ac.forensic_notes || [])[0] || 'Welcome back — biometric arrival comparison complete!',
      }
      fetch('/api/presence-voicematch/status')
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => {
          if (d) presenceVoicematchFallback.value = d
        })
        .catch(() => {})
    })
    evtSource.addEventListener('delta_avatar', (ev) => {
      const dm = JSON.parse(ev.data)
      lastToast.value = {
        speaker_id: dm.speaker_id || 'PERSON_DELTA',
        range_m: dm.range_m ?? 0.72,
        role: `DELTA ${dm.delta_peak_hz || 1.5}Hz · ${dm.movement_state || 'STILL'}`,
        text: `"${dm.earworm_phrase || ''}" (${dm.emotional_reset_pct || 76}% Emotional Reset)`,
        audio_url: dm.audio_url || '',
      }
      fetch('/api/delta-avatar/status')
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => {
          if (d) deltaAvatarFallback.value = d
        })
        .catch(() => {})
    })
    evtSource.onerror = () => {
      sseConnected.value = false
    }
  } catch (e) {
    sseConnected.value = false
  }
}

async function sendControl(payload) {
  try {
    const res = await fetch('/api/gnuradio/control', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (res.ok) {
      const data = await res.json()
      if (data.status) liveStatus.value = data.status
      await refreshAnalytics()
    }
  } catch (e) {
    console.error('Control error:', e)
  }
}

function triggerAutotune() {
  sendControl({ re_autotune: true })
}

function onCalibrateRc(rcVal) {
  sendControl({ room_critical_dist_m: rcVal })
}

function onApplyPreset(preset) {
  if (!preset || Object.keys(preset).length === 0) {
    refreshAnalytics()
    return
  }
  sendControl(preset)
}

function onTuneRf(freqMhz) {
  sendControl({ rf_freq_mhz: freqMhz })
}

function playToastAudio(url) {
  if (!url) return
  try {
    const aud = new Audio(url)
    aud.volume = 0.85
    aud.play().catch(() => {})
  } catch (_) {}
}

async function toggleHeaderAutoSpeak() {
  const cur =
    liveStatus.value?.reading_piggyback?.piggyback?.three_state_vad?.config?.auto_play_out_loud ?? true
  try {
    await fetch('/api/reading-piggyback/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ auto_play_out_loud: !cur, hear_reading_out_loud: true }),
    })
    await refreshAnalytics()
  } catch (e) {
    console.error(e)
  }
}

async function cycleHeaderFocusMode() {
  const cur = String(
    liveStatus.value?.reading_piggyback?.piggyback?.closest_focus?.focus_mode || 'BOTH'
  ).toUpperCase()
  const next = cur === 'BOTH' ? 'AUTO' : cur === 'AUTO' ? 'PINNED' : 'BOTH'
  const pinned =
    liveStatus.value?.reading_piggyback?.piggyback?.closest_focus?.pinned_speaker_id || 'PERSON_DELTA'
  try {
    await fetch('/api/spatial/focus-closest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        focus_closest_enabled: true,
        focus_mode: next,
        pinned_speaker_id: pinned,
      }),
    })
    await refreshAnalytics()
  } catch (e) {
    console.error(e)
  }
}

function setHours(h) {
  hours.value = h
}

function setScope(s) {
  scope.value = s
}

watch([hours, bucketMinutes, scope], () => {
  refreshAnalytics()
})

onMounted(async () => {
  await refreshAnalytics()
  const params = new URLSearchParams(window.location.search)
  const shareParam = params.get('share')
  const spkParam = params.get('speaker')
  if (shareParam) {
    try {
      const res = await fetch(`/api/earworm/share/${encodeURIComponent(shareParam)}`)
      if (res.ok) {
        const data = await res.json()
        if (data.packet) openSavedShare(data.packet)
      }
    } catch (_) {
      if (spkParam) openPersonEarworm(spkParam)
    }
  } else if (spkParam) {
    openPersonEarworm(spkParam)
  }

  if (window.location.search.includes('snapshot=1')) {
    sseConnected.value = true
  } else {
    connectSSE()
    pollTimer = setInterval(refreshAnalytics, 8000)
  }
})

onBeforeUnmount(() => {
  if (evtSource) evtSource.close()
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.cockpit-shell {
  max-width: 1680px;
  margin: 0 auto;
  padding: 12px 18px 36px;
}
.top-nav {
  background: rgba(17, 22, 31, 0.92);
  backdrop-filter: blur(10px);
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  padding: 12px 18px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 14px;
}
.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}
.brand h1 {
  font-size: 1.15rem;
  font-weight: 800;
  color: #58a6ff;
}
.brand .thin {
  font-weight: 500;
  color: #e6edf3;
  font-size: 1rem;
}
.pulse-dot {
  width: 11px;
  height: 11px;
  border-radius: 50%;
  background: #656d76;
  flex-shrink: 0;
}
.pulse-dot.online {
  background: #3fb950;
  box-shadow: 0 0 10px #3fb950;
}
.telemetry-strip {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  font-size: 0.74rem;
  color: var(--text-secondary);
  margin-top: 2px;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.live-toast {
  background: rgba(35, 134, 54, 0.16);
  border: 1px solid rgba(63, 185, 80, 0.45);
  border-radius: 9px;
  padding: 8px 14px;
  margin-bottom: 12px;
  font-size: 0.8rem;
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}
.person-quickbar {
  background: linear-gradient(90deg, rgba(17, 24, 39, 0.94), rgba(22, 28, 45, 0.94));
  border: 1px solid rgba(88, 166, 255, 0.32);
  border-radius: 10px;
  padding: 8px 14px;
  margin-bottom: 14px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 0.74rem;
}
.pq-left,
.pq-right {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.pq-lbl {
  color: #9ecbff;
  font-weight: 700;
}
.pq-pill {
  background: #0d131f;
  border: 1px solid;
  border-radius: 99px;
  padding: 3px 10px;
  font-size: 0.72rem;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.pq-pill:hover {
  background: rgba(88, 166, 255, 0.15);
}
.pq-hook {
  color: #e6edf3;
  font-weight: 500;
  opacity: 0.88;
}
.pq-share-last {
  background: rgba(63, 185, 80, 0.14);
  border: 1px solid rgba(63, 185, 80, 0.45);
  color: #7ee787;
  border-radius: 99px;
  padding: 3px 10px;
  font-size: 0.71rem;
  cursor: pointer;
}
.main-grid {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.top-split {
  display: grid;
  grid-template-columns: 1.38fr 1fr;
  gap: 16px;
  align-items: start;
}
@media (max-width: 1180px) {
  .top-split {
    grid-template-columns: 1fr;
  }
}
</style>
