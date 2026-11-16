<template>
  <section class="card">
    <div class="card-header">
      <div>
        <div class="card-title">
          <span>🧬 Per-Speaker Biometric &amp; Word Showcase</span>
          <span class="pill mono">{{ speakers.length }} Enrolled Identity{{ speakers.length === 1 ? '' : 's' }}</span>
        </div>
        <div class="sub-caption">
          WeSpeaker ResNet34-ONNX (256-D) + Whisper-Invariant Vocal Tract Length (<span class="mono">VTL cm</span>) + Liveness BPM + Spatial Range
        </div>
      </div>

      <div class="filter-bar">
        <input
          v-model="wordFilter"
          type="text"
          placeholder="Filter extracted words across speakers..."
          class="search-input"
        />
      </div>
    </div>

    <div v-if="speakers.length" class="speakers-grid">
      <article
        v-for="spk in speakers"
        :key="spk.speaker_id"
        class="spk-card"
        :style="{ borderTopColor: spk.color }"
      >
        <!-- Header Identity + WPH Velocity (Clickable Person) -->
        <div
          class="spk-head clickable-head"
          :title="`Click to open ${spk.speaker_id}'s Shared Earworm & Biometric Dossier`"
          @click="$emit('select-speaker', spk.speaker_id)"
        >
          <div class="spk-head-info">
            <div class="spk-id mono" :style="{ color: spk.color }">
              {{ spk.speaker_id === 'PERSON_TYPIST' ? '⌨️' : (spk.speaker_id === 'DEVICE_CELLPHONE' ? '📱' : (spk.speaker_id === 'DEVICE_MEMS' ? '🔬' : (spk.speaker_id === 'OTHER_ROOM_SUBLEVEL' ? '🧱' : '🎧'))) }} {{ spk.speaker_id }}
              <span v-if="spk.typing_only || spk.speaker_id === 'PERSON_TYPIST'" class="inspect-pill" style="border-color: #2dd4bf; color: #2dd4bf">
                TYPING EVENTS ONLY
              </span>
              <span v-else-if="spk.speaker_id === 'DEVICE_CELLPHONE'" class="inspect-pill" style="border-color: #f778ba; color: #f778ba">
                CELLPHONE CLICK ONLY
              </span>
              <span v-else-if="spk.speaker_id === 'DEVICE_MEMS'" class="inspect-pill" style="border-color: #eab308; color: #eab308">
                MEMS ULTRASONIC ONLY
              </span>
              <span v-else-if="spk.speaker_id === 'OTHER_ROOM_SUBLEVEL'" class="inspect-pill" style="border-color: #38bdf8; color: #38bdf8">
                NON-OCCUPANT MID-AIR PIGGYBACK
              </span>
              <span v-else-if="spk.gender_badge" class="inspect-pill" style="border-color: rgba(210, 168, 255, 0.45); color: #e9d5ff">
                {{ spk.gender_badge }}
              </span>
              <span class="inspect-pill">Click to Inspect &amp; Share ↗</span>
            </div>
            <div class="spk-sub mono">
              Match {{ spk.match_score_pct }}% · Conf {{ spk.avg_conf_pct }}% · {{ spk.utterances }} utterances
            </div>
          </div>

          <div class="wph-badge">
            <div class="wph-num mono" :style="{ color: spk.color }">{{ spk.wph }}</div>
            <div class="wph-unit">WORDS / HR</div>
          </div>
        </div>

        <!-- SHARED EARWORM STRIP + 1-CLICK SHARE BUTTON -->
        <div class="earworm-strip">
          <div class="ew-strip-left">
            <div class="ew-lbl mono">
              🎶 EARWORM SHARING
              <span v-if="speakerEarworm(spk.speaker_id).earworm_bpm" class="ew-bpm">
                · {{ speakerEarworm(spk.speaker_id).earworm_bpm }} BPM · {{ speakerEarworm(spk.speaker_id).phoneme_contour || 'EE-AH' }}
              </span>
            </div>
            <div
              class="ew-hook"
              @click="$emit('select-speaker', { speakerId: spk.speaker_id, phrase: speakerEarworm(spk.speaker_id).primary_earworm_phrase })"
            >
              "{{ speakerEarworm(spk.speaker_id).primary_earworm_phrase || topFallbackHook(spk) }}"
            </div>
            <div v-if="speakerEarworm(spk.speaker_id).shared_with?.length" class="ew-cosharers mono">
              <span class="muted">Sharing with:</span>
              <button
                v-for="cs in speakerEarworm(spk.speaker_id).shared_with.slice(0, 3)"
                :key="cs.speaker_id"
                type="button"
                class="ew-cs-chip"
                :style="{ borderColor: cs.color, color: cs.color }"
                @click.stop="$emit('select-speaker', cs.speaker_id)"
              >
                ↔ {{ cs.speaker_id }}
              </button>
            </div>
          </div>
          <button
            type="button"
            class="btn-share-ew mono"
            @click.stop="$emit('select-speaker', { speakerId: spk.speaker_id, phrase: speakerEarworm(spk.speaker_id).primary_earworm_phrase })"
          >
            🔗 Share Earworm
          </button>
        </div>

        <!-- Biometric & Spatial Matrix -->
        <div class="bio-matrix mono">
          <div class="bm-cell">
            <span class="bm-lbl">Vocal Tract</span>
            <strong>{{ spk.vtl_cm }} cm</strong>
          </div>
          <div class="bm-cell">
            <span class="bm-lbl">Pitch F0</span>
            <strong>{{ spk.f0_hz > 0 ? spk.f0_hz + ' Hz' : 'Whisper' }}</strong>
          </div>
          <div class="bm-cell">
            <span class="bm-lbl">Respiration</span>
            <strong>{{ spk.resp_bpm }} BPM</strong>
          </div>
          <div class="bm-cell">
            <span class="bm-lbl">Spatial Pos</span>
            <strong>{{ spk.spatial.range_m }}m ({{ formatAz(spk.spatial.azimuth_deg) }})</strong>
          </div>
          <div class="bm-cell">
            <span class="bm-lbl">Mouth Viseme</span>
            <strong style="color: #79c0ff">{{ spk.mouth_openness_pct ?? 30 }}% · {{ spk.dominant_viseme || 'MID_EH' }}</strong>
          </div>
        </div>

        <!-- Voiced vs Sublevel Whisper Split Bar -->
        <div class="phonation-strip">
          <div class="phon-labels mono">
            <span>🗣️ Voiced: {{ spk.voiced_utterances }} ({{ (100 - spk.whisper_pct).toFixed(0) }}%)</span>
            <span>🤫 Sublevel Whisper: {{ spk.whisper_utterances }} ({{ spk.whisper_pct }}%)</span>
          </div>
          <div class="phon-track">
            <div
              class="phon-voiced"
              :style="{ width: Math.max(4, 100 - spk.whisper_pct) + '%' }"
            ></div>
            <div
              class="phon-whisper"
              :style="{ width: spk.whisper_pct + '%' }"
            ></div>
          </div>
        </div>

        <!-- Top Extracted Lexical Vocabulary -->
        <div class="vocab-block" v-if="spk.top_words && spk.top_words.length">
          <div class="sec-lbl">Top Extracted Words ({{ spk.words }} total tokens)</div>
          <div class="vocab-chips">
            <span
              v-for="tw in spk.top_words"
              :key="tw.word"
              class="vocab-chip mono"
              @click="wordFilter = tw.word"
            >
              {{ tw.word }} <b>×{{ tw.count }}</b>
            </span>
          </div>
        </div>

        <!-- Live Utterance & Word-Confidence Stream -->
        <div class="utt-stream">
          <div class="sec-lbl">Recent Forensic Word Stream (NightSweep Reconstructed)</div>
          <div
            v-for="(u, uIdx) in filteredUtterances(spk.recent_utterances)"
            :key="uIdx"
            class="utt-item"
          >
            <div class="utt-meta mono">
              <span>{{ u.time_local }}</span>
              <span :class="['role-pill', u.band_role === 'WHISPER' ? 'whisper' : 'voiced']">
                {{ u.band_role }}
              </span>
              <span>📍 {{ u.spatial.range_m }}m · {{ formatAz(u.spatial.azimuth_deg) }}</span>
              <span v-if="u.mouth_articulation" style="color: #79c0ff">
                👄 {{ Math.round((u.mouth_articulation.mouth_openness || 0) * 100) }}% ({{ u.mouth_articulation.viseme }})
              </span>
              <span>ASR {{ u.avg_conf_pct }}%</span>
            </div>
            <div class="utt-recon">{{ u.reconstructed }}</div>
            <div class="word-tokens mono">
              <span
                v-for="(w, wIdx) in u.words"
                :key="wIdx"
                class="w-tok"
                :class="probClass(w.prob_pct)"
                :title="`ASR Probability: ${w.prob_pct}%`"
              >
                {{ w.word }}<sub>{{ w.prob_pct }}%</sub>
              </span>
            </div>
          </div>
        </div>
      </article>
    </div>

    <div v-else class="empty-spk">
      No speaker utterances in the selected time window yet.
    </div>
  </section>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  speakers: { type: Array, default: () => [] },
  sharedEarworms: { type: Object, default: () => ({}) },
})

defineEmits(['select-speaker'])

const wordFilter = ref('')

function speakerEarworm(speakerId) {
  return props.sharedEarworms?.speakers?.[speakerId] || {}
}

function topFallbackHook(spk) {
  if (spk.recent_utterances?.length) {
    return String(spk.recent_utterances[0].reconstructed || '').split(' ').slice(0, 4).join(' ')
  }
  return 'listening in room'
}

function filteredUtterances(list) {
  if (!list) return []
  const q = wordFilter.value.trim().toLowerCase()
  if (!q) return list.slice(0, 8)
  return list.filter(
    (u) =>
      (u.reconstructed || '').toLowerCase().includes(q) ||
      (u.raw_transcript || '').toLowerCase().includes(q)
  )
}

function probClass(pct) {
  if (pct >= 75) return 'high'
  if (pct >= 45) return 'mid'
  return 'low'
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
.filter-bar {
  width: min(100%, 320px);
  min-width: 0;
}
.search-input {
  background: #0b0f17;
  border: 1px solid var(--border-subtle);
  color: var(--text-primary);
  border-radius: 7px;
  padding: 6px 12px;
  font-size: 0.8rem;
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}
.search-input:focus {
  outline: none;
  border-color: var(--blue);
}
.speakers-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 350px), 1fr));
  gap: 14px;
}
.spk-card {
  background: #0c1119;
  border: 1px solid var(--border-subtle);
  border-top-width: 3px;
  border-radius: 10px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 11px;
  min-width: 0;
  container-type: inline-size;
}
.spk-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
  flex-wrap: wrap;
}
.spk-head-info {
  min-width: 0;
  flex: 1 1 200px;
}
.clickable-head {
  cursor: pointer;
  padding: 4px 6px;
  margin: -4px -6px;
  border-radius: 8px;
  transition: background 0.15s ease;
}
.clickable-head:hover {
  background: rgba(88, 166, 255, 0.08);
}
.inspect-pill {
  font-size: 0.64rem;
  font-weight: 600;
  color: #9ecbff;
  background: rgba(88, 166, 255, 0.14);
  border: 1px solid rgba(88, 166, 255, 0.35);
  padding: 1px 7px;
  border-radius: 99px;
  white-space: nowrap;
}
.earworm-strip {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  background: linear-gradient(135deg, rgba(88, 166, 255, 0.08), rgba(210, 168, 255, 0.09));
  border: 1px solid rgba(210, 168, 255, 0.32);
  border-radius: 8px;
  padding: 8px 10px;
}
.ew-strip-left {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  flex: 1 1 190px;
}
.ew-lbl {
  font-size: 0.65rem;
  color: #d2a8ff;
  font-weight: 700;
}
.ew-bpm {
  color: #79c0ff;
}
.ew-hook {
  font-size: 0.86rem;
  font-weight: 800;
  color: #ffffff;
  cursor: pointer;
  overflow-wrap: anywhere;
}
.ew-hook:hover {
  color: #79c0ff;
}
.ew-cosharers {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
  font-size: 0.68rem;
}
.ew-cs-chip {
  background: #0e1522;
  border: 1px solid;
  border-radius: 99px;
  padding: 1px 7px;
  font-size: 0.66rem;
  cursor: pointer;
}
.btn-share-ew {
  flex-shrink: 0;
  background: rgba(63, 185, 80, 0.16);
  border: 1px solid rgba(63, 185, 80, 0.5);
  color: #7ee787;
  border-radius: 8px;
  padding: 6px 11px;
  font-size: 0.73rem;
  font-weight: 700;
  cursor: pointer;
}
.btn-share-ew:hover {
  background: rgba(63, 185, 80, 0.28);
}
.muted {
  color: var(--text-secondary);
}
.spk-id {
  font-size: 1.02rem;
  font-weight: 800;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px 7px;
  word-break: break-word;
}
.spk-sub {
  font-size: 0.73rem;
  color: var(--text-secondary);
  margin-top: 3px;
}
.wph-badge {
  flex-shrink: 0;
  text-align: right;
  background: #131b28;
  border: 1px solid #223047;
  border-radius: 8px;
  padding: 5px 11px;
}
.wph-num {
  font-size: 1.25rem;
  font-weight: 800;
  line-height: 1.1;
}
.wph-unit {
  font-size: 0.63rem;
  color: var(--text-secondary);
  letter-spacing: 0.06em;
}
.bio-matrix {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(112px, 1fr));
  gap: 7px;
}
.bm-cell {
  background: #111824;
  border: 1px solid #1d293d;
  border-radius: 7px;
  padding: 6px 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 0.75rem;
  min-width: 0;
  overflow-wrap: anywhere;
}
.bm-cell strong {
  line-height: 1.25;
  word-break: break-word;
}
.bm-lbl {
  font-size: 0.65rem;
  color: var(--text-muted);
}
.phonation-strip {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.phon-labels {
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 4px 10px;
  font-size: 0.71rem;
  color: var(--text-secondary);
}
.phon-track {
  height: 7px;
  border-radius: 99px;
  overflow: hidden;
  display: flex;
  background: #182030;
}
.phon-voiced {
  background: linear-gradient(90deg, #1f6feb, #58a6ff);
}
.phon-whisper {
  background: linear-gradient(90deg, #8957e5, #d2a8ff);
}
.sec-lbl {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-secondary);
  margin-bottom: 5px;
  font-weight: 700;
}
.vocab-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.vocab-chip {
  font-size: 0.72rem;
  background: #141d2b;
  border: 1px solid #24334a;
  padding: 2px 8px;
  border-radius: 99px;
  cursor: pointer;
}
.vocab-chip:hover {
  border-color: var(--blue);
}
.vocab-chip b {
  color: var(--blue);
}
.utt-stream {
  max-height: 295px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding-right: 3px;
}
.utt-item {
  background: #101622;
  border: 1px solid #1c2638;
  border-radius: 8px;
  padding: 8px 10px;
}
.utt-meta {
  display: flex;
  gap: 10px;
  align-items: center;
  font-size: 0.69rem;
  color: var(--text-secondary);
  margin-bottom: 4px;
  flex-wrap: wrap;
}
.role-pill {
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 700;
  font-size: 0.64rem;
}
.role-pill.voiced {
  background: rgba(88, 166, 255, 0.16);
  color: #58a6ff;
}
.role-pill.whisper {
  background: rgba(210, 168, 255, 0.16);
  color: #d2a8ff;
}
.utt-recon {
  font-size: 0.85rem;
  color: #7ee787;
  font-weight: 600;
  margin-bottom: 5px;
}
.word-tokens {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.w-tok {
  font-size: 0.7rem;
  padding: 1px 5px;
  border-radius: 4px;
  background: #0b0f17;
  border: 1px solid #1e293b;
}
.w-tok sub {
  font-size: 0.58rem;
  margin-left: 2px;
  opacity: 0.8;
}
.w-tok.high { color: #c9d1d9; border-color: rgba(63, 185, 80, 0.35); }
.w-tok.mid  { color: #e3b341; border-color: rgba(227, 179, 65, 0.35); }
.w-tok.low  { color: #ffa198; border-color: rgba(248, 81, 73, 0.35); }
.empty-spk {
  padding: 28px;
  text-align: center;
  color: var(--text-secondary);
}

@container (max-width: 460px) {
  .bio-matrix {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .btn-share-ew {
    width: 100%;
    text-align: center;
  }
}

@media (max-width: 768px) {
  .filter-bar {
    width: 100%;
  }
  .speakers-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 480px) {
  .spk-card {
    padding: 11px;
  }
  .bio-matrix {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .wph-badge {
    width: 100%;
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    text-align: left;
  }
  .btn-share-ew {
    width: 100%;
    text-align: center;
  }
}
</style>
