<template>
  <section id="presence-voicematch-studio" class="card pvm-card">
    <!-- HEADER -->
    <div class="pvm-header">
      <div>
        <div class="pvm-title-row">
          <h2 class="pvm-title">
            🚪 PERSON_DELTA Departure / Arrival Biometric Diff · 🪪 "Who Is Who" Voice Match &amp; 🎧 UltraMic384K Ambiance / Unknown Subvoc
          </h2>
          <span
            class="pill mono"
            :class="presenceState === 'AWAY_MONITORING' ? 'away-pill' : 'arrived-pill'"
          >
            {{
              presenceState === 'AWAY_MONITORING'
                ? `🚪 AWAY MONITORING (${data.away_elapsed_min ?? 0}m · Baseline Locked)`
                : `🏠 ARRIVAL COMPARED (${arrivalComp?.verdict || 'VERIFIED'})`
            }}
          </span>
          <span class="pill mono owner-pill">
            🧑 Owner Slot: {{ ownerId }} · VTL {{ depBio.vtl_cm ?? 14.69 }} cm · F0 {{ depBio.f0_hz ?? 301.8 }} Hz
          </span>
        </div>
        <div class="pvm-sub">
          Locks your <span class="mono">271-D ResNet34-ONNX + VTL</span> pre-departure biometric &amp; empty-room FFT spectrum when leaving,
          audits room activity while gone, compares your return arrival biometrics, ranks live <strong>Who Is Who</strong> voiceprints, and monitors
          <span class="mono">UltraMic384K_EVO (48 kHz)</span> ambiance to isolate unknown low-ambient subvocalizations.
        </div>
      </div>

      <div class="pvm-hdr-actions">
        <button
          type="button"
          class="btn btn-ollama mono"
          :disabled="ollamaBusy"
          @click="consultOllama(true)"
        >
          {{ ollamaBusy ? '🧠 Consulting NightSweep…' : '🧠 Ask Ollama Modal to Advise & Improve' }}
        </button>
        <button
          v-if="ollamaAdvice?.recommended_config"
          type="button"
          class="btn btn-apply mono"
          :disabled="configBusy"
          @click="applyOllamaConfig"
        >
          ⚡ Apply Recommended Config (+{{ ollamaAdvice.recommended_config.subvoc_isolator_gain_db }}dB · {{ Math.round((ollamaAdvice.recommended_config.unknown_sim_ceiling || 0.65) * 100) }}% OOD)
        </button>
      </div>
    </div>

    <div v-if="bannerMsg" class="pvm-banner mono">
      ✅ {{ bannerMsg }}
    </div>

    <!-- NIGHTSWEEP OLLAMA MODAL ADVISOR DRAWER -->
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
          <div class="od-col-hdr mono">🚪 Departure vs. Arrival Biometrics</div>
          <ul>
            <li v-for="(it, idx) in (ollamaAdvice.departure_arrival_biometric_advice || []).slice(0, 3)" :key="'da-' + idx">
              {{ it }}
            </li>
          </ul>
        </div>
        <div class="od-col">
          <div class="od-col-hdr mono">🪪 "Who Is Who" Voice Match</div>
          <ul>
            <li v-for="(it, idx) in (ollamaAdvice.who_is_who_voicematch_advice || []).slice(0, 3)" :key="'ww-' + idx">
              {{ it }}
            </li>
          </ul>
        </div>
        <div class="od-col">
          <div class="od-col-hdr mono">🎧 UltraMic Ambiance &amp; Unknown Subvoc</div>
          <ul>
            <li v-for="(it, idx) in (ollamaAdvice.ultramic_unknown_subvoc_advice || []).slice(0, 3)" :key="'um-' + idx">
              {{ it }}
            </li>
          </ul>
        </div>
      </div>
    </div>

    <!-- 3-COLUMN WORKBENCH -->
    <div class="pvm-grid">
      <!-- COLUMN 1: DEPARTURE -> AWAY AUDIT -> ARRIVAL BIOMETRIC DIFF -->
      <div class="pvm-col">
        <div class="col-hdr">
          <span class="col-title">🚪 1. {{ ownerId }} Departure vs. Arrival Biometric Diff</span>
          <span class="mono mini-tag">{{ depCheckpoint.checkpoint_id || 'dep-armed' }}</span>
        </div>

        <div class="action-row">
          <button
            type="button"
            class="btn btn-depart mono"
            :disabled="departBusy"
            @click="markDeparture"
          >
            {{ departBusy ? 'Locking…' : `🚪 Leaving Now: Lock ${ownerId}` }}
          </button>
          <button
            type="button"
            class="btn btn-arrive mono"
            :disabled="arriveBusy"
            @click="markArrival(false)"
          >
            {{ arriveBusy ? 'Comparing…' : '🏠 I’m Back: Compare Live Arrival' }}
          </button>
          <button
            type="button"
            class="btn btn-sim mono"
            :disabled="arriveBusy"
            title="Preview how post-walk arrival comparison looks against your locked pre-departure baseline"
            @click="markArrival(true)"
          >
            🧪 Preview Return Diff
          </button>
        </div>

        <!-- VOICEPRINT RE-ENTRY SCORE BANNER -->
        <div v-if="arrivalComp" class="verdict-box" :class="arrivalComp.verified_same_person ? 'verdict-ok' : 'verdict-warn'">
          <div class="vb-top mono">
            <strong>
              {{ arrivalComp.verified_same_person ? '✅ VERIFIED SAME PERSON' : '⚠️ VOICEPRINT CHECK' }}
              ({{ arrivalComp.verdict }})
            </strong>
            <span class="vb-sim">{{ arrivalComp.voiceprint_similarity_pct }}% Match</span>
          </div>
          <div class="vb-sub mono">
            Trigger: {{ arrivalComp.trigger_source }} · Away {{ arrivalComp.away_duration_min }}m · Arrived {{ (arrivalComp.arrived_at_utc || '').slice(11, 19) }} UTC
          </div>
          <ul class="vb-notes">
            <li v-for="(n, idx) in arrivalComp.forensic_notes || []" :key="'fn-' + idx">{{ n }}</li>
          </ul>
        </div>
        <div v-else class="verdict-box verdict-armed mono">
          <div>
            🔒 <strong>Pre-Departure Snapshot Armed</strong> ({{ (depCheckpoint.departed_at_utc || '').slice(11, 19) }} UTC) —
            Auto-Arrival Re-Entry Verification ({{ cfg.auto_detect_arrival ? 'ON ≥74% match' : 'MANUAL' }}) is listening for your return!
          </div>
        </div>

        <!-- BEFORE vs ARRIVAL BIOMETRIC TABLE -->
        <div class="table-scroll-wrap">
          <table class="bio-diff-table mono">
          <thead>
            <tr>
              <th>Biometric Metric</th>
              <th>Before Leaving</th>
              <th>Upon Arrival</th>
              <th>Δ Shift</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>🧬 VTL (Vocal Tract)</td>
              <td>{{ depBio.vtl_cm ?? 14.69 }} cm</td>
              <td>{{ arrBio ? `${arrBio.vtl_cm} cm` : 'Awaiting…' }}</td>
              <td :class="deltaClass(arrDeltas?.vtl_cm, 0.45)">
                {{ arrDeltas ? formatSigned(arrDeltas.vtl_cm, ' cm') : '--' }}
              </td>
            </tr>
            <tr>
              <td>🎵 Fundamental F0</td>
              <td>{{ depBio.f0_hz ?? 301.8 }} Hz ({{ depBio.musical_note || 'D4' }})</td>
              <td>{{ arrBio ? `${arrBio.f0_hz} Hz (${arrBio.musical_note || ''})` : 'Awaiting…' }}</td>
              <td>{{ arrDeltas ? formatSigned(arrDeltas.f0_hz, ' Hz') : '--' }}</td>
            </tr>
            <tr>
              <td>🫁 Respiration Rate</td>
              <td>{{ depBio.resp_bpm ?? 15.2 }} BPM</td>
              <td>{{ arrBio ? `${arrBio.resp_bpm} BPM` : 'Awaiting…' }}</td>
              <td style="color: #79c0ff">{{ arrDeltas ? formatSigned(arrDeltas.resp_bpm, ' BPM') : '--' }}</td>
            </tr>
            <tr>
              <td>📡 915MHz Throat µm</td>
              <td>{{ depBio.throat_disp_um ?? 60.2 }} µm</td>
              <td>{{ arrBio ? `${arrBio.throat_disp_um} µm` : 'Awaiting…' }}</td>
              <td>{{ arrDeltas ? formatSigned(arrDeltas.throat_disp_um, ' µm') : '--' }}</td>
            </tr>
            <tr>
              <td>📍 3D Range / Azimuth</td>
              <td>{{ depBio.range_m ?? 0.72 }}m / {{ formatAz(depBio.azimuth_deg ?? 36) }}</td>
              <td>{{ arrBio ? `${arrBio.range_m}m / ${formatAz(arrBio.azimuth_deg)}` : 'Awaiting…' }}</td>
              <td>{{ arrDeltas ? `${formatSigned(arrDeltas.range_m, 'm')} / ${formatSigned(arrDeltas.azimuth_deg, '°')}` : '--' }}</td>
            </tr>
          </tbody>
          </table>
        </div>

        <!-- WHILE-YOU-WERE-GONE ROOM AUDIT -->
        <div class="away-audit-box">
          <div class="aab-hdr mono">
            <span>🕵️ While-You-Were-Gone Room Audit</span>
            <span :style="{ color: (whileAway.owner_utterances_while_away || 0) === 0 ? '#7ee787' : '#f0883e' }">
              {{ ownerId }} While Away: {{ whileAway.owner_utterances_while_away ?? 0 }} utts
            </span>
          </div>
          <div class="aab-pills mono">
            <span class="aab-pill">
              🕵️ Unknown Subvocs: <strong>{{ whileAway.unknown_subvoc_while_away ?? 0 }}</strong>
            </span>
            <span
              v-for="(cnt, spk) in whileAway.speaker_counts || {}"
              :key="spk"
              class="aab-pill"
              style="cursor: pointer"
              @click="$emit('select-speaker', spk)"
            >
              {{ spk }}: <strong>{{ cnt }}</strong>
            </span>
          </div>
          <div v-if="(whileAway.recent_events || []).length" class="aab-feed mono">
            <div v-for="(ev, idx) in whileAway.recent_events.slice(0, 4)" :key="'aw-' + idx" class="aab-item">
              <span class="muted">{{ (ev.timestamp_utc || '').slice(11, 19) }}</span>
              <strong style="color: #58a6ff">{{ ev.speaker_id }}</strong>
              <span>({{ ev.range_m }}m): {{ ev.excerpt }}</span>
            </div>
          </div>
          <div v-else class="aab-empty mono">
            Quiet room baseline locked — any speech or unknown subvocalization while you are out logs here automatically.
          </div>
        </div>
      </div>

      <!-- COLUMN 2: VOICE RECOGNITION MATCH SHOWCASE ("WHO IS WHO") -->
      <div class="pvm-col">
        <div class="col-hdr">
          <span class="col-title">🪪 2. Voice Recognition Match ("Who Is Who")</span>
          <span class="mono mini-tag">ResNet34-ONNX 256-D + 15-D VTL</span>
        </div>

        <div class="probe-bar">
          <button
            type="button"
            class="btn btn-primary mono"
            :disabled="probeBusy"
            @click="runVoiceProbe('')"
          >
            {{ probeBusy ? '🎙️ Matching…' : '🎙️ Live 2s Mic Voice Match' }}
          </button>
          <button
            v-for="card in whoCards.slice(0, 4)"
            :key="'prb-' + card.speaker_id"
            type="button"
            class="seg-mini mono"
            :style="{ borderColor: card.color, color: card.color }"
            :disabled="probeBusy"
            @click="runVoiceProbe(card.speaker_id)"
          >
            Test {{ card.speaker_id.replace('PERSON_', '') }}
          </button>
        </div>

        <!-- LATEST UTTERANCE / PROBE CONFIDENCE RANKING BARS -->
        <div v-if="latestMatch" class="match-bars-box">
          <div class="mbb-top mono">
            <span>
              🏆 Best Match:
              <strong style="color: #7ee787; cursor: pointer" @click="$emit('select-speaker', latestMatch.matched_speaker_id)">
                {{ latestMatch.matched_speaker_id }}
              </strong>
              ({{ latestMatch.match_pct }}% · +{{ latestMatch.margin_over_runner_up_pct }}% margin)
            </span>
            <span v-if="latestMatch.is_unknown_ood" class="ood-tag">UNKNOWN OOD</span>
            <span v-else class="ok-tag">{{ latestMatch.band_role }}</span>
          </div>
          <div v-if="latestMatch.excerpt" class="mbb-quote">"{{ latestMatch.excerpt }}"</div>
          <div class="rank-bars">
            <div
              v-for="rk in latestMatch.rankings || []"
              :key="'rk-' + rk.speaker_id"
              class="rank-row mono"
            >
              <span class="rk-lbl" @click="$emit('select-speaker', rk.speaker_id)">
                {{ rk.speaker_id === ownerId ? '🧑 ' : '' }}{{ rk.speaker_id }}
              </span>
              <div class="rk-track">
                <div
                  class="rk-fill"
                  :style="{
                    width: Math.min(100, Math.max(4, rk.match_pct)) + '%',
                    background: rk.speaker_id === latestMatch.matched_speaker_id ? '#3fb950' : '#388bfd',
                  }"
                ></div>
              </div>
              <span class="rk-pct">{{ rk.match_pct }}%</span>
            </div>
          </div>
        </div>

        <!-- ENROLLED "WHO IS WHO" IDENTITY CARDS WITH EDITABLE ALIASES -->
        <div class="who-cards-list">
          <div
            v-for="card in whoCards"
            :key="card.speaker_id"
            class="who-card"
            :class="{ 'owner-card': card.is_owner }"
            :style="{ borderLeftColor: card.color }"
          >
            <div class="wc-top">
              <div class="wc-id mono" :style="{ color: card.color }" @click="$emit('select-speaker', card.speaker_id)">
                {{ card.is_owner ? '🧑 ' : '🗣️ ' }}{{ card.speaker_id }}
                <span v-if="card.is_owner" class="you-badge">YOU · OWNER</span>
              </div>
              <div class="wc-btns mono">
                <button
                  type="button"
                  class="mini-act"
                  title="Play VTL-calibrated voice/earworm WAV signature"
                  @click="playInlineWav(card.audio_url)"
                >
                  ▶ Hear Voice
                </button>
                <button
                  type="button"
                  class="mini-act"
                  title="Open full biometric & earworm dossier"
                  @click="$emit('select-speaker', card.speaker_id)"
                >
                  🔍 Dossier
                </button>
              </div>
            </div>

            <!-- Editable Human Alias Row -->
            <div class="wc-alias-row">
              <input
                v-model="aliasDrafts[card.speaker_id]"
                type="text"
                class="alias-input"
                :placeholder="card.alias"
                @keyup.enter="saveAlias(card.speaker_id)"
              />
              <button type="button" class="mini-save mono" @click="saveAlias(card.speaker_id)">
                Save Tag
              </button>
            </div>

            <div class="wc-metrics mono">
              <span>VTL {{ card.vtl_cm }}cm</span>
              <span>F0 {{ card.f0_hz }}Hz ({{ card.musical_note }})</span>
              <span>Whisper {{ card.whisper_share_pct }}%</span>
              <span>{{ card.range_m }}m / {{ formatAz(card.azimuth_deg) }}</span>
              <span>{{ card.words }}w</span>
            </div>
          </div>
        </div>

        <!-- PAIRWISE SEPARATION MATRIX -->
        <div v-if="sepMatrix.length" class="sep-box mono">
          <div class="sep-title">📐 Pairwise Voiceprint Separation (Orthogonality Proof):</div>
          <div class="sep-chips">
            <span v-for="(sp, idx) in sepMatrix.slice(0, 6)" :key="'sep-' + idx" class="sep-chip">
              {{ sp.speaker_a.replace('PERSON_', '') }}↔{{ sp.speaker_b.replace('PERSON_', '') }}:
              <strong style="color: #7ee787">{{ sp.separation_pct }}% sep</strong>
            </span>
          </div>
        </div>
      </div>

      <!-- COLUMN 3: HEAR ULTRAMIC384K_EVO AMBIANCE & IDENTIFY UNKNOWN SUBVOC -->
      <div class="pvm-col">
        <div class="col-hdr">
          <span class="col-title">🎧 3. Hear UltraMic384K Ambiance &amp; Unknown Subvoc</span>
          <span class="mono mini-tag">48 kHz Live Ring</span>
        </div>

        <!-- LIVE 3-BAND ULTRAMIC METERS -->
        <div class="um-meters mono">
          <div class="um-m">
            <span class="muted">Room Floor</span>
            <strong>{{ ultraMic.live_room_rms_dbfs ?? -58 }} dBFS</strong>
          </div>
          <div class="um-m">
            <span class="muted">Subvoc 1.8–6.5k</span>
            <strong style="color: #7ee787">{{ ultraMic.live_subvoc_band_dbfs ?? -64 }} dBFS</strong>
          </div>
          <div class="um-m">
            <span class="muted">Ultrasonic 13–23.5k</span>
            <strong style="color: #d2a8ff">{{ ultraMic.live_ultrasonic_band_dbfs ?? -68 }} dBFS</strong>
          </div>
        </div>

        <!-- 4 LISTENING MODES -->
        <div class="mode-grid">
          <button
            v-for="m in ambianceModes"
            :key="m.id"
            type="button"
            class="mode-btn mono"
            :class="{ active: selectedMode === m.id }"
            @click="selectAmbianceMode(m.id)"
          >
            <div class="mb-top">{{ m.icon }} {{ m.label }}</div>
            <div class="mb-desc">{{ m.desc }}</div>
          </button>
        </div>

        <!-- LIVE AUDIO PLAYER + CONTINUOUS MONITOR LOOP -->
        <div class="ambiance-player-box">
          <div class="apb-controls">
            <button type="button" class="btn btn-primary mono" @click="refreshAmbianceSlice(true)">
              ▶ Hear 3.5s {{ selectedMode }}
            </button>
            <button
              type="button"
              class="btn mono"
              :class="continuousLoop ? 'btn-loop-on' : ''"
              @click="toggleContinuousLoop"
            >
              {{ continuousLoop ? '🔁 Live Monitor Loop: ON' : '🔁 Continuous Monitor: OFF' }}
            </button>
          </div>
          <audio
            ref="ambianceAudioRef"
            :src="ambianceWavUrl"
            controls
            preload="none"
            class="full-wav"
            @ended="onAmbianceSliceEnded"
          ></audio>
        </div>

        <!-- ULTRAMIC & SUBVOC TUNING SLIDERS -->
        <div class="um-sliders mono">
          <label>
            <span>Subvoc Lift (+{{ subvocGainDb }} dB)</span>
            <input v-model.number="subvocGainDb" type="range" min="14" max="44" step="1" @change="pushUmConfig" />
          </label>
          <label>
            <span>Heterodyne LO ({{ (heterodyneLoHz / 1000).toFixed(1) }} kHz)</span>
            <input v-model.number="heterodyneLoHz" type="range" min="12000" max="21000" step="500" @change="pushUmConfig" />
          </label>
          <label>
            <span>Unknown OOD (&lt;{{ Math.round(unknownCeiling * 100) }}%)</span>
            <input v-model.number="unknownCeiling" type="range" min="0.45" max="0.82" step="0.01" @change="pushUmConfig" />
          </label>
        </div>

        <!-- IDENTIFY UNKNOWN SUBVOCALIZATION LOW-AMBIENT FEED -->
        <div class="unknown-subvoc-box">
          <div class="usb-hdr">
            <span class="mono usb-title">
              🕵️ Unknown Low-Ambient Subvocs ({{ unknownEvents.length }})
            </span>
            <button
              type="button"
              class="btn btn-subvoc mono"
              :disabled="probeBusy"
              @click="triggerUnknownSubvocTest"
            >
              🕵️ Test Unknown Subvoc Capture
            </button>
          </div>

          <div v-if="unknownEvents.length" class="usb-list">
            <div v-for="ev in unknownEvents.slice(0, 5)" :key="ev.id" class="usb-card mono">
              <div class="usb-top">
                <span class="usb-id">🕵️ {{ ev.id }}</span>
                <span v-if="ev.captured_while_away" class="away-mini">WHILE AWAY</span>
                <span class="nov-mini">Novelty {{ ev.ood_novelty_pct }}%</span>
                <button type="button" class="mini-act" @click="playInlineWav(ev.audio_url)">
                  ▶ Hear +32dB Subvoc
                </button>
              </div>
              <div class="usb-meta">
                <span>Est. VTL ~{{ ev.estimated_vtl_cm }}cm</span>
                <span>Peak {{ ev.peak_subvoc_hz }}Hz</span>
                <span>SNR {{ ev.ambient_snr_db }}dB</span>
                <span>{{ ev.range_m }}m / {{ formatAz(ev.azimuth_deg) }}</span>
                <span>Nearest: {{ ev.nearest_enrolled_id }} ({{ ev.nearest_similarity_pct }}%)</span>
              </div>
            </div>
          </div>
          <div v-else class="aab-empty mono">
            Monitoring 1.08×–3.6× room floor for unenrolled (&lt;{{ Math.round(unknownCeiling * 100) }}% match) whispered/palatal subvocalizations…
          </div>
        </div>
      </div>
    </div>

    <audio ref="inlineWavRef" :src="inlineWavUrl" style="display: none"></audio>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

const props = defineProps({
  data: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['select-speaker', 'updated'])

const departBusy = ref(false)
const arriveBusy = ref(false)
const probeBusy = ref(false)
const ollamaBusy = ref(false)
const configBusy = ref(false)
const bannerMsg = ref('')
const localOllama = ref(null)

const selectedMode = ref('SUBVOC_ISOLATOR')
const ambianceNonce = ref(Date.now())
const continuousLoop = ref(false)
const ambianceAudioRef = ref(null)
const inlineWavRef = ref(null)
const inlineWavUrl = ref('')

const subvocGainDb = ref(32)
const heterodyneLoHz = ref(15500)
const unknownCeiling = ref(0.66)
const aliasDrafts = reactive({})

const ambianceModes = [
  {
    id: 'FULL_AMBIANCE',
    icon: '🎧',
    label: 'Full Ambiance (+26 dB)',
    desc: '55–20,000 Hz upward soft-knee room monitor',
  },
  {
    id: 'SUBVOC_ISOLATOR',
    icon: '🤫',
    label: 'Subvoc Isolator (+32 dB)',
    desc: '1.65–6.4 kHz whisper formant lift + rumble cut',
  },
  {
    id: 'ULTRASONIC_HETERODYNE',
    icon: '🦇',
    label: 'Ultrasonic Heterodyne',
    desc: '15.5 kHz LO shifts 12.8–23.6 kHz lip clicks audible',
  },
  {
    id: 'DEPARTURE_ANOMALY_DIFF',
    icon: '🧬',
    label: 'Departure Anomaly Diff',
    desc: 'Subtracts empty-room FFT saved on departure',
  },
]

const presenceState = computed(() => props.data?.presence_state || 'AWAY_MONITORING')
const ownerId = computed(() => props.data?.owner_speaker_id || 'PERSON_DELTA')
const depCheckpoint = computed(() => props.data?.departure_checkpoint || {})
const depBio = computed(() => depCheckpoint.value?.biometrics || {})
const arrivalComp = computed(() => props.data?.arrival_comparison || null)
const arrBio = computed(() => arrivalComp.value?.arrival || null)
const arrDeltas = computed(() => arrivalComp.value?.deltas || null)
const whileAway = computed(() => props.data?.while_away || {})
const whoCards = computed(() => props.data?.who_is_who || [])
const sepMatrix = computed(() => props.data?.separation_matrix || [])
const latestMatch = computed(() => (props.data?.recent_voice_matches || [])[0] || null)
const ultraMic = computed(() => props.data?.ultramic_ambiance || {})
const unknownEvents = computed(() => ultraMic.value?.unknown_subvoc_events || [])
const cfg = computed(() => props.data?.config || {})
const ollamaAdvice = computed(() => localOllama.value || props.data?.last_ollama_advisor || null)

const ambianceWavUrl = computed(
  () => `/api/ultramic/ambiance.wav?mode=${encodeURIComponent(selectedMode.value)}&sec=3.5&t=${ambianceNonce.value}`
)

watch(
  () => props.data?.config,
  (c) => {
    if (!c) return
    if (typeof c.subvoc_isolator_gain_db === 'number') subvocGainDb.value = c.subvoc_isolator_gain_db
    if (typeof c.heterodyne_lo_hz === 'number') heterodyneLoHz.value = c.heterodyne_lo_hz
    if (typeof c.unknown_sim_ceiling === 'number') unknownCeiling.value = c.unknown_sim_ceiling
  },
  { immediate: true }
)

watch(
  whoCards,
  (cards) => {
    for (const c of cards || []) {
      if (!(c.speaker_id in aliasDrafts)) {
        aliasDrafts[c.speaker_id] = c.alias || c.speaker_id
      }
    }
  },
  { immediate: true }
)

function flash(msg) {
  bannerMsg.value = msg
  setTimeout(() => {
    if (bannerMsg.value === msg) bannerMsg.value = ''
  }, 5500)
}

function formatAz(az) {
  const n = Math.round(Number(az) || 0)
  return (n >= 0 ? '+' : '') + n + '°'
}

function formatSigned(val, unit = '') {
  const num = Number(val)
  if (Number.isNaN(num)) return '--'
  return `${num >= 0 ? '+' : ''}${num}${unit}`
}

function deltaClass(val, tol) {
  if (val === undefined || val === null) return ''
  return Math.abs(Number(val)) <= tol ? 'delta-invariant' : 'delta-shift'
}

async function markDeparture() {
  departBusy.value = true
  try {
    const res = await fetch('/api/presence-voicematch/depart', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        speaker_id: ownerId.value,
        note: `User Left Room — ${ownerId.value} 271-D Voiceprint & Empty-Room Floor Locked`,
      }),
    })
    if (res.ok) {
      flash(`Locked ${ownerId.value} pre-departure baseline & UltraMic empty-room FFT! Monitoring while you are away.`)
      emit('updated')
    }
  } catch (e) {
    console.error(e)
  } finally {
    departBusy.value = false
  }
}

async function markArrival(simulate = false) {
  arriveBusy.value = true
  try {
    const res = await fetch('/api/presence-voicematch/arrive', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ speaker_id: ownerId.value, simulate }),
    })
    if (res.ok) {
      const j = await res.json()
      const comp = j.arrival_comparison || {}
      flash(
        `${simulate ? 'Previewed' : 'Verified'} Arrival Biometrics: ${comp.voiceprint_similarity_pct}% match (${comp.verdict}, ΔVTL ${formatSigned(comp.deltas?.vtl_cm, ' cm')})`
      )
      emit('updated')
    }
  } catch (e) {
    console.error(e)
  } finally {
    arriveBusy.value = false
  }
}

async function runVoiceProbe(targetSpk = '') {
  probeBusy.value = true
  try {
    const res = await fetch('/api/presence-voicematch/probe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ probe_type: 'LIVE_VOICE_MATCH', speaker_id: targetSpk }),
    })
    if (res.ok) {
      const j = await res.json()
      flash(`Voice Match Probe → ${j.matched_speaker_id} (${j.rankings?.[0]?.match_pct ?? 92}% ResNet34-ONNX + VTL confidence)`)
      emit('updated')
    }
  } catch (e) {
    console.error(e)
  } finally {
    probeBusy.value = false
  }
}

async function triggerUnknownSubvocTest() {
  probeBusy.value = true
  try {
    const res = await fetch('/api/presence-voicematch/probe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ probe_type: 'UNKNOWN_SUBVOC' }),
    })
    if (res.ok) {
      const j = await res.json()
      const ev = j.unknown_subvoc_event || {}
      flash(
        `Isolated Unknown Low-Ambient Subvoc (${ev.id}): Est. VTL ~${ev.estimated_vtl_cm}cm, Novelty ${ev.ood_novelty_pct}%!`
      )
      if (ev.audio_url) playInlineWav(ev.audio_url)
      emit('updated')
    }
  } catch (e) {
    console.error(e)
  } finally {
    probeBusy.value = false
  }
}

async function saveAlias(speakerId) {
  const label = (aliasDrafts[speakerId] || '').trim()
  if (!label) return
  try {
    const res = await fetch('/api/presence-voicematch/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ alias_speaker_id: speakerId, alias_label: label }),
    })
    if (res.ok) {
      flash(`Saved "Who Is Who" identity tag for ${speakerId}: "${label}"`)
      emit('updated')
    }
  } catch (e) {
    console.error(e)
  }
}

async function pushUmConfig() {
  configBusy.value = true
  try {
    const res = await fetch('/api/presence-voicematch/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        subvoc_isolator_gain_db: subvocGainDb.value,
        heterodyne_lo_hz: heterodyneLoHz.value,
        unknown_sim_ceiling: unknownCeiling.value,
      }),
    })
    if (res.ok) {
      ambianceNonce.value = Date.now()
      emit('updated')
    }
  } catch (e) {
    console.error(e)
  } finally {
    configBusy.value = false
  }
}

function selectAmbianceMode(modeId) {
  selectedMode.value = modeId
  refreshAmbianceSlice(continuousLoop.value)
}

async function refreshAmbianceSlice(autoPlay = false) {
  ambianceNonce.value = Date.now()
  await nextTick()
  if (autoPlay && ambianceAudioRef.value) {
    try {
      ambianceAudioRef.value.load()
      await ambianceAudioRef.value.play()
    } catch (_) {}
  }
}

function toggleContinuousLoop() {
  continuousLoop.value = !continuousLoop.value
  if (continuousLoop.value) {
    refreshAmbianceSlice(true)
    flash(`Continuous Live UltraMic384K Monitor Loop ON (${selectedMode.value})`)
  }
}

function onAmbianceSliceEnded() {
  if (continuousLoop.value) {
    refreshAmbianceSlice(true)
  }
}

async function playInlineWav(url) {
  if (!url) return
  inlineWavUrl.value = `${url}${url.includes('?') ? '&' : '?'}t=${Date.now()}`
  await nextTick()
  if (inlineWavRef.value) {
    try {
      inlineWavRef.value.load()
      await inlineWavRef.value.play()
    } catch (_) {}
  }
}

async function consultOllama(force = true) {
  ollamaBusy.value = true
  try {
    const res = await fetch('/api/ollama/presence-voicematch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force }),
    })
    if (res.ok) {
      localOllama.value = await res.json()
      if (force) {
        flash('NightSweep Ollama Modal synthesized Departure/Arrival Diff, Who-Is-Who & UltraMic Subvoc improvements!')
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
    const res = await fetch('/api/presence-voicematch/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(rc),
    })
    if (res.ok) {
      flash('Applied NightSweep Ollama recommended Presence, Voice-Match & UltraMic Subvoc configuration!')
      emit('updated')
    }
  } catch (e) {
    console.error(e)
  } finally {
    configBusy.value = false
  }
}

onMounted(() => {
  if (!props.data?.last_ollama_advisor) {
    consultOllama(false)
  }
})

onBeforeUnmount(() => {
  continuousLoop.value = false
})
</script>

<style scoped>
.pvm-card {
  background: linear-gradient(180deg, rgba(16, 22, 32, 0.96), rgba(11, 15, 22, 0.98));
  border: 1px solid rgba(240, 136, 62, 0.35);
  border-radius: 12px;
  padding: 16px 18px;
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.38);
}

.pvm-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.pvm-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.pvm-title {
  margin: 0;
  font-size: 1.03rem;
  font-weight: 700;
  color: #f0f6fc;
}

.pvm-sub {
  margin-top: 4px;
  font-size: 0.79rem;
  color: #8b949e;
  line-height: 1.4;
}

.away-pill {
  background: rgba(240, 136, 62, 0.16);
  border: 1px solid rgba(240, 136, 62, 0.55);
  color: #ffa657;
}

.arrived-pill {
  background: rgba(63, 185, 80, 0.16);
  border: 1px solid rgba(63, 185, 80, 0.55);
  color: #7ee787;
}

.owner-pill {
  background: rgba(88, 166, 255, 0.12);
  border: 1px solid rgba(88, 166, 255, 0.4);
  color: #79c0ff;
}

.pvm-hdr-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.btn-ollama {
  background: rgba(163, 113, 247, 0.16);
  border: 1px solid rgba(163, 113, 247, 0.55);
  color: #d2a8ff;
}

.btn-apply {
  background: rgba(63, 185, 80, 0.16);
  border: 1px solid rgba(63, 185, 80, 0.55);
  color: #7ee787;
}

.pvm-banner {
  background: rgba(46, 160, 67, 0.16);
  border: 1px solid rgba(63, 185, 80, 0.45);
  color: #7ee787;
  padding: 7px 12px;
  border-radius: 7px;
  font-size: 0.78rem;
  margin-bottom: 10px;
}

.ollama-drawer {
  background: rgba(22, 27, 38, 0.85);
  border: 1px solid rgba(163, 113, 247, 0.32);
  border-radius: 9px;
  padding: 10px 12px;
  margin-bottom: 12px;
}

.od-top {
  display: flex;
  justify-content: space-between;
  font-size: 0.75rem;
  color: #d2a8ff;
  margin-bottom: 4px;
}

.od-summary {
  margin: 0 0 8px;
  font-size: 0.8rem;
  color: #c9d1d9;
  line-height: 1.42;
}

.od-cols {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.od-col {
  background: rgba(13, 17, 23, 0.65);
  border: 1px solid rgba(48, 54, 61, 0.7);
  border-radius: 7px;
  padding: 8px 10px;
}

.od-col-hdr {
  font-size: 0.74rem;
  font-weight: 700;
  color: #79c0ff;
  margin-bottom: 5px;
}

.od-col ul {
  margin: 0;
  padding-left: 15px;
  font-size: 0.75rem;
  color: #b1bac4;
  line-height: 1.38;
}

.pvm-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

@media (max-width: 1420px) {
  .pvm-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .pvm-grid > .pvm-col:nth-child(3) {
    grid-column: 1 / -1;
  }
  .od-cols {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 920px) {
  .pvm-grid,
  .od-cols {
    grid-template-columns: 1fr;
  }
  .pvm-grid > .pvm-col:nth-child(3) {
    grid-column: auto;
  }
}

.pvm-col {
  background: rgba(13, 17, 23, 0.78);
  border: 1px solid rgba(48, 54, 61, 0.85);
  border-radius: 9px;
  padding: 11px 12px;
  display: flex;
  flex-direction: column;
  gap: 9px;
  min-width: 0;
}

.col-hdr {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.col-title {
  font-size: 0.86rem;
  font-weight: 700;
  color: #e6edf3;
}

.mini-tag {
  font-size: 0.69rem;
  padding: 2px 6px;
  border-radius: 5px;
  background: rgba(56, 139, 253, 0.13);
  color: #79c0ff;
}

.action-row,
.probe-bar {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.btn-depart {
  background: rgba(240, 136, 62, 0.18);
  border: 1px solid rgba(240, 136, 62, 0.6);
  color: #ffa657;
  font-size: 0.74rem;
  padding: 5px 9px;
}

.btn-arrive {
  background: rgba(46, 160, 67, 0.2);
  border: 1px solid rgba(63, 185, 80, 0.6);
  color: #7ee787;
  font-size: 0.74rem;
  padding: 5px 9px;
}

.btn-sim {
  background: rgba(88, 166, 255, 0.14);
  border: 1px solid rgba(88, 166, 255, 0.45);
  color: #79c0ff;
  font-size: 0.73rem;
  padding: 5px 8px;
}

.verdict-box {
  border-radius: 7px;
  padding: 8px 10px;
  font-size: 0.75rem;
}

.verdict-armed {
  background: rgba(240, 136, 62, 0.1);
  border: 1px solid rgba(240, 136, 62, 0.35);
  color: #f0c674;
}

.verdict-ok {
  background: rgba(46, 160, 67, 0.14);
  border: 1px solid rgba(63, 185, 80, 0.5);
  color: #c9d1d9;
}

.verdict-warn {
  background: rgba(210, 153, 34, 0.16);
  border: 1px solid rgba(210, 153, 34, 0.5);
  color: #e3b341;
}

.vb-top {
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 6px;
  color: #7ee787;
}

.table-scroll-wrap {
  width: 100%;
  max-width: 100%;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.vb-sim {
  font-size: 0.85rem;
  font-weight: 700;
}

.vb-sub {
  font-size: 0.69rem;
  color: #8b949e;
  margin-top: 2px;
}

.vb-notes {
  margin: 5px 0 0;
  padding-left: 15px;
  font-size: 0.72rem;
  color: #c9d1d9;
}

.bio-diff-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.72rem;
}

.bio-diff-table th,
.bio-diff-table td {
  padding: 5px 6px;
  border-bottom: 1px solid rgba(48, 54, 61, 0.65);
  text-align: left;
}

.bio-diff-table th {
  color: #8b949e;
  font-weight: 600;
}

.delta-invariant {
  color: #7ee787;
  font-weight: 700;
}

.delta-shift {
  color: #ffa657;
}

.away-audit-box,
.unknown-subvoc-box {
  background: rgba(22, 27, 34, 0.75);
  border: 1px solid rgba(48, 54, 61, 0.8);
  border-radius: 7px;
  padding: 8px 9px;
}

.aab-hdr,
.usb-hdr {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.74rem;
  margin-bottom: 6px;
}

.aab-pills {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
  margin-bottom: 5px;
}

.aab-pill {
  font-size: 0.69rem;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(48, 54, 61, 0.55);
  color: #c9d1d9;
}

.aab-feed {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 0.7rem;
}

.aab-item {
  display: flex;
  gap: 5px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.aab-empty {
  font-size: 0.71rem;
  color: #8b949e;
}

.seg-mini {
  background: rgba(22, 27, 34, 0.85);
  border: 1px solid #30363d;
  border-radius: 5px;
  padding: 4px 7px;
  font-size: 0.7rem;
  cursor: pointer;
}

.match-bars-box {
  background: rgba(22, 27, 34, 0.8);
  border: 1px solid rgba(56, 139, 253, 0.35);
  border-radius: 7px;
  padding: 8px 9px;
}

.mbb-top {
  display: flex;
  justify-content: space-between;
  font-size: 0.73rem;
  margin-bottom: 3px;
}

.mbb-quote {
  font-size: 0.72rem;
  color: #8b949e;
  font-style: italic;
  margin-bottom: 6px;
}

.ood-tag {
  background: rgba(248, 81, 73, 0.2);
  color: #ff7b72;
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 0.67rem;
}

.ok-tag {
  background: rgba(63, 185, 80, 0.16);
  color: #7ee787;
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 0.67rem;
}

.rank-bars {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.rank-row {
  display: grid;
  grid-template-columns: 108px 1fr 42px;
  align-items: center;
  gap: 6px;
  font-size: 0.7rem;
}

.rk-lbl {
  cursor: pointer;
  color: #c9d1d9;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rk-track {
  height: 7px;
  background: rgba(48, 54, 61, 0.7);
  border-radius: 4px;
  overflow: hidden;
}

.rk-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.25s ease;
}

.rk-pct {
  text-align: right;
  color: #e6edf3;
}

.who-cards-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 255px;
  overflow-y: auto;
}

.who-card {
  background: rgba(22, 27, 34, 0.75);
  border: 1px solid rgba(48, 54, 61, 0.75);
  border-left: 3px solid #58a6ff;
  border-radius: 6px;
  padding: 6px 8px;
}

.owner-card {
  background: rgba(240, 136, 62, 0.09);
  border-color: rgba(240, 136, 62, 0.45);
}

.wc-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.wc-id {
  font-size: 0.76rem;
  font-weight: 700;
  cursor: pointer;
}

.you-badge {
  background: rgba(240, 136, 62, 0.24);
  color: #ffa657;
  font-size: 0.64rem;
  padding: 1px 5px;
  border-radius: 4px;
  margin-left: 4px;
}

.wc-btns {
  display: flex;
  gap: 4px;
}

.mini-act,
.mini-save {
  background: rgba(48, 54, 61, 0.65);
  border: 1px solid rgba(110, 118, 129, 0.4);
  color: #c9d1d9;
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 0.67rem;
  cursor: pointer;
}

.mini-act:hover,
.mini-save:hover {
  border-color: #58a6ff;
  color: #79c0ff;
}

.wc-alias-row {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin: 4px 0;
}

.alias-input {
  flex: 1 1 140px;
  min-width: 0;
  background: rgba(13, 17, 23, 0.85);
  border: 1px solid rgba(48, 54, 61, 0.85);
  border-radius: 4px;
  color: #e6edf3;
  font-size: 0.72rem;
  padding: 3px 6px;
}

.wc-metrics {
  display: flex;
  gap: 7px;
  flex-wrap: wrap;
  font-size: 0.68rem;
  color: #8b949e;
}

.sep-box {
  background: rgba(13, 17, 23, 0.6);
  border: 1px dashed rgba(63, 185, 80, 0.35);
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 0.69rem;
}

.sep-title {
  color: #8b949e;
  margin-bottom: 4px;
}

.sep-chips {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
}

.sep-chip {
  background: rgba(48, 54, 61, 0.5);
  padding: 2px 6px;
  border-radius: 4px;
}

.um-meters {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
}

.um-m {
  background: rgba(22, 27, 34, 0.8);
  border: 1px solid rgba(48, 54, 61, 0.75);
  border-radius: 6px;
  padding: 5px 7px;
  display: flex;
  flex-direction: column;
  font-size: 0.7rem;
}

.mode-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}

.mode-btn {
  text-align: left;
  background: rgba(22, 27, 34, 0.8);
  border: 1px solid rgba(48, 54, 61, 0.85);
  border-radius: 6px;
  padding: 6px 8px;
  cursor: pointer;
  color: #c9d1d9;
}

.mode-btn.active {
  border-color: #3fb950;
  background: rgba(46, 160, 67, 0.14);
}

.mb-top {
  font-size: 0.73rem;
  font-weight: 700;
  color: #f0f6fc;
}

.mb-desc {
  font-size: 0.65rem;
  color: #8b949e;
  margin-top: 2px;
}

.ambiance-player-box {
  background: rgba(22, 27, 34, 0.75);
  border: 1px solid rgba(48, 54, 61, 0.8);
  border-radius: 7px;
  padding: 7px 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.apb-controls {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.btn-loop-on {
  background: rgba(46, 160, 67, 0.22);
  border-color: #3fb950;
  color: #7ee787;
}

.full-wav {
  width: 100%;
  height: 32px;
}

.um-sliders {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
  font-size: 0.67rem;
  color: #8b949e;
}

.um-sliders label {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.btn-subvoc {
  background: rgba(210, 168, 255, 0.16);
  border: 1px solid rgba(210, 168, 255, 0.5);
  color: #d2a8ff;
  font-size: 0.69rem;
  padding: 3px 7px;
}

.usb-title {
  font-size: 0.74rem;
  font-weight: 700;
  color: #d2a8ff;
}

.usb-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
  max-height: 150px;
  overflow-y: auto;
}

.usb-card {
  background: rgba(13, 17, 23, 0.8);
  border: 1px solid rgba(210, 168, 255, 0.28);
  border-radius: 5px;
  padding: 5px 7px;
  font-size: 0.68rem;
}

.usb-top {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 3px;
}

.usb-id {
  color: #d2a8ff;
  font-weight: 700;
}

.away-mini {
  background: rgba(240, 136, 62, 0.2);
  color: #ffa657;
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 0.63rem;
}

.nov-mini {
  background: rgba(56, 139, 253, 0.18);
  color: #79c0ff;
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 0.63rem;
}

.usb-meta {
  display: flex;
  gap: 7px;
  flex-wrap: wrap;
  color: #8b949e;
}

@media (max-width: 640px) {
  .um-meters,
  .mode-grid,
  .um-sliders {
    grid-template-columns: 1fr;
  }
  .rank-row {
    grid-template-columns: minmax(78px, 94px) 1fr 38px;
  }
  .aab-hdr,
  .usb-hdr,
  .mbb-top,
  .od-top {
    flex-wrap: wrap;
    gap: 4px;
  }
}
</style>
