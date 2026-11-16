<template>
  <section id="whisper-talkback-studio" class="panel talkback-panel" :class="{ armed: state.talkback_enabled }">
    <!-- HEADER WITH MASTER OPT-IN TOGGLE ("MAKE IT AN OPTION TO START TALKING BACK") -->
    <div class="panel-hdr">
      <div>
        <div class="title-row">
          <h2>🔊 Mid-Air Low-Ambient Whisper Talkback &amp; Auto-Conversation</h2>
          <span class="badge mono" :class="state.talkback_enabled ? 'badge-live' : 'badge-passive'">
            {{ state.talkback_enabled ? '🔊 TALKBACK ACTIVE (HALF-DUPLEX)' : '🔇 PASSIVE LISTEN ONLY (DEFAULT)' }}
          </span>
          <span class="badge badge-guard mono" title="MasterExperienceOutputBlock suppresses bio_hook during TX + 420ms room decay">
            🛡️ Echo Guard: -30 dB + 420ms Blank
          </span>
        </div>
        <p class="sub">
          Transmits STFT-whisperized 48 kHz acoustic payloads back into the room &amp; UDP <code>:5005</code>
          <strong>only once the repeated low-ambient Earworm Δ is confirmed</strong>.
        </p>
      </div>

      <div class="master-optin">
        <button
          type="button"
          class="optin-btn mono"
          :class="{ enabled: state.talkback_enabled }"
          :disabled="busy"
          @click="toggleTalkback(!state.talkback_enabled)"
        >
          <span class="dot" :class="{ live: state.talkback_enabled }"></span>
          {{ state.talkback_enabled ? '🔊 Talking Back: ON (Click to Mute)' : '🔇 Start Talking Back (Enable Option)' }}
        </button>
      </div>
    </div>

    <!-- EARWORM DELTA HARVEST CONFIRMATION GATE BANNER -->
    <div class="delta-banner" :class="{ confirmed: harvester.delta_confirmed }">
      <div class="delta-left">
        <div class="delta-status mono">
          <span v-if="harvester.delta_confirmed" class="pill-ok">✅ EARWORM Δ CONFIRMED</span>
          <span v-else class="pill-wait">⏳ AWAITING EARWORM Δ LOCK</span>
          <span class="reason-txt">{{ harvester.status_reason || 'Listening for repeated low-ambient whispers...' }}</span>
        </div>
        <div class="delta-hook-row">
          <span class="lbl mono">Harvested Earworm Δ Hook:</span>
          <strong class="hook-phrase">
            {{ harvester.active_delta_hook ? `"${harvester.active_delta_hook}"` : '— waiting for repeated whisper —' }}
          </strong>
          <span
            v-if="harvester.active_delta_hook"
            class="chip mono"
            :class="harvester.active_delta_is_promoted ? 'violet' : 'cyan'"
          >
            {{ harvester.active_delta_is_promoted ? `🚀 PROMOTED ORDER-${harvester.active_delta_order || 3} CHAIN` : `ORDER-${harvester.active_delta_order || 2}` }}
          </span>
          <span v-if="harvester.active_delta_contour" class="chip mono cyan">{{ harvester.active_delta_contour }}</span>
          <span class="chip mono">
            Repeats: {{ harvester.active_delta_repeats ?? 0 }} / {{ harvester.min_repeats ?? 2 }}×
          </span>
          <span class="chip mono">{{ harvester.active_delta_bpm ?? 118 }} BPM</span>
          <span
            v-if="(harvester.active_delta_next_predictions || []).length"
            class="chip mono violet"
            title="Hierarchical Order 4→3→2→1 Kneser-Ney continuation tokens fed to NightSweep Talkback"
          >
            Next P(wₜ₊₁|Δ): {{ harvester.active_delta_next_predictions.slice(0, 3).map(t => `"${t}"`).join(', ') }}
          </span>
          <button
            v-for="spk in harvester.active_delta_speakers || []"
            :key="spk"
            type="button"
            class="spk-chip mono"
            @click="$emit('select-speaker', spk)"
            title="Click to inspect speaker's shared earworm dossier"
          >
            🎧 {{ spk }}
          </button>
        </div>
      </div>

      <div class="delta-right mono">
        <div>Harvested Whispers: <strong>{{ harvester.total_whispers_harvested ?? 0 }}</strong></div>
        <div v-if="harvester.previous_locked_hook" class="prev-delta">
          Prev Hook → Δ: "{{ harvester.previous_locked_hook }}" → "{{ harvester.active_delta_hook }}"
        </div>
      </div>
    </div>

    <!-- CONFIGURATION CONTROLS STRIP -->
    <div class="controls-grid mono">
      <div class="ctrl-item">
        <label>Conversation Mode</label>
        <div class="seg-pair">
          <button
            type="button"
            class="seg"
            :class="{ active: state.conversation_mode === 'auto_conversation' }"
            @click="updateConfig({ conversation_mode: 'auto_conversation' })"
          >
            🤖 Auto-Conversation
          </button>
          <button
            type="button"
            class="seg"
            :class="{ active: state.conversation_mode === 'live_chat' }"
            @click="updateConfig({ conversation_mode: 'live_chat' })"
          >
            💬 Live Whisper Chat
          </button>
        </div>
      </div>

      <div class="ctrl-item">
        <label>Earworm Δ Confirmation Gate</label>
        <select
          :value="harvester.gate_mode || 'CONFIRMED_EARWORM_DELTA'"
          @change="updateConfig({ gate_mode: $event.target.value })"
        >
          <option value="CONFIRMED_EARWORM_DELTA">Confirmed Earworm Δ (≥N Whispers)</option>
          <option value="PERSON_DELTA_ONLY">PERSON_DELTA Earworm Only (≥N)</option>
          <option value="IMMEDIATE_WHISPER">Immediate Low-Ambient Whisper (1×)</option>
        </select>
      </div>

      <div class="ctrl-item">
        <label>Target Speaker Filter</label>
        <select
          :value="harvester.target_speaker || 'ANY'"
          @change="updateConfig({ target_speaker: $event.target.value })"
        >
          <option value="ANY">ANY Whispering Person</option>
          <option value="PERSON_DELTA">PERSON_DELTA</option>
          <option value="PERSON_ALPHA">PERSON_ALPHA</option>
          <option value="PERSON_BETA">PERSON_BETA</option>
          <option value="PERSON_GAMMA">PERSON_GAMMA</option>
        </select>
      </div>

      <div class="ctrl-item small">
        <label>Min Repeats</label>
        <select
          :value="harvester.min_repeats || 2"
          @change="updateConfig({ min_repeats: Number($event.target.value) })"
        >
          <option :value="2">2× Repeats</option>
          <option :value="3">3× Repeats</option>
          <option :value="4">4× Repeats</option>
        </select>
      </div>

      <div class="ctrl-item">
        <label>Mid-Air Acoustic Payload Style</label>
        <select
          :value="state.acoustic_style || 'low_ambient_whisper'"
          @change="updateConfig({ acoustic_style: $event.target.value })"
        >
          <option value="low_ambient_whisper">🤫 Low-Ambient Whisper (Cepstral)</option>
          <option value="ultrasonic_framed_whisper">📡 18.8 kHz Ultrasonic-Framed Whisper</option>
          <option value="soft_spoken_voice">🗣️ Soft Spoken Voice</option>
        </select>
      </div>

      <div class="ctrl-item small">
        <label>Whisper Level ({{ state.whisper_level_dbfs ?? -14 }} dBFS)</label>
        <input
          type="range"
          min="-28"
          max="-6"
          step="1"
          :value="state.whisper_level_dbfs ?? -14"
          @change="updateConfig({ whisper_level_dbfs: Number($event.target.value) })"
        />
      </div>

      <div class="ctrl-item">
        <label style="color: #d2a8ff">Markov Chain Priority</label>
        <label class="chk-inline" style="margin-top: 4px">
          <input
            type="checkbox"
            :checked="harvester.prefer_promoted_higher_order !== false"
            @change="updateConfig({ prefer_promoted_higher_order: $event.target.checked })"
          />
          🚀 Prefer Order 3/4 Chains
        </label>
      </div>
    </div>

    <div v-if="feedbackBanner" class="feedback-bar mono">
      {{ feedbackBanner }}
    </div>

    <!-- 2-COLUMN BODY: HARVESTER QUEUE + LIVE WHISPER CHAT -->
    <div class="studio-cols">
      <!-- LEFT: HARVESTED LOW-AMBIENT WHISPERS & ARMED PAYLOAD QUEUE -->
      <div class="col-box">
        <div class="box-hdr mono">
          <span>🌾 Harvested Low-Ambient Whispers</span>
          <span class="muted">Window: {{ Math.round((harvester.window_sec || 360) / 60) }}m</span>
        </div>

        <div v-if="(harvester.promoted_whisper_candidates || []).length" class="prom-cand-bar mono">
          <span class="prom-lbl">🚀 Ranked Order 3/4 Hooks:</span>
          <button
            v-for="cand in harvester.promoted_whisper_candidates.slice(0, 4)"
            :key="cand.hook"
            type="button"
            class="prom-chip mono"
            :class="{ active: cand.hook === harvester.active_delta_hook }"
            @click="prefillWithHook(harvester.target_speaker === 'ANY' ? '' : harvester.target_speaker, cand.hook)"
            title="Click to prefill whisper reply with this higher-order Markov hook"
          >
            [O{{ cand.order }}{{ cand.is_promoted ? '★' : '' }}] "{{ cand.hook }}" (×{{ cand.repeats }})
          </button>
        </div>

        <div v-if="(state.armed_payloads || []).length" class="armed-queue">
          <div class="armed-hdr mono">
            <span>🔒 Armed Payloads Waiting for Earworm Δ Confirmation ({{ state.armed_payloads.length }})</span>
            <button type="button" class="mini-clear mono" @click="clearArmed">Clear</button>
          </div>
          <div v-for="item in state.armed_payloads" :key="item.id" class="armed-row mono">
            <span class="arm-tag">⏳ QUEUED → {{ item.target_speaker }}</span>
            <span class="arm-txt">"{{ item.text }}"</span>
          </div>
        </div>

        <div class="harvest-list">
          <div
            v-for="(ev, idx) in harvester.recent_harvests || []"
            :key="idx"
            class="harvest-card"
          >
            <div class="hc-top mono">
              <button
                type="button"
                class="spk-link mono"
                @click="$emit('select-speaker', ev.speaker_id)"
              >
                🎧 {{ ev.speaker_id }}
              </button>
              <span class="hc-contour">{{ ev.contour }}</span>
              <span>{{ ev.disp_um }} µm</span>
              <span>{{ (ev.utc || '').slice(11, 19) }} UTC</span>
            </div>
            <div class="hc-txt">"{{ ev.text }}"</div>
            <div v-if="ev.hooks?.length" class="hc-hooks mono">
              <span
                v-for="hk in ev.hooks.slice(0, 3)"
                :key="hk"
                class="hk-pill"
                :class="{ match: hk === harvester.active_delta_hook }"
                @click="prefillWithHook(ev.speaker_id, hk)"
                title="Click to draft a whisper reply for this hook"
              >
                Δ "{{ hk }}"
              </span>
            </div>
          </div>
          <div v-if="!(harvester.recent_harvests || []).length" class="empty-note mono">
            Listening on 48 kHz UltraMic + Subvoc Gesture Gate for repeated low-ambient whispers...
          </div>
        </div>
      </div>

      <!-- RIGHT: BIDIRECTIONAL MID-AIR WHISPER CONVERSATION STREAM & COMPOSER -->
      <div class="col-box chat-box">
        <div class="box-hdr mono">
          <span>💬 Bidirectional Mid-Air Whisper Conversation</span>
          <label class="chk-inline">
            <input
              type="checkbox"
              :checked="state.auto_play_browser !== false"
              @change="updateConfig({ auto_play_browser: $event.target.checked })"
            />
            Browser Audio Monitor
          </label>
        </div>

        <div class="chat-feed">
          <div
            v-for="msg in reversedMessages"
            :key="msg.id"
            class="chat-bubble"
            :class="msg.direction === 'OUTBOUND_TALKBACK' ? 'outbound' : 'inbound'"
          >
            <div class="cb-meta mono">
              <span v-if="msg.direction === 'OUTBOUND_TALKBACK'" class="dir-out">
                🔊 LAREX MID-AIR WHISPER →
                <strong class="click-spk" @click="$emit('select-speaker', msg.speaker_id)">{{ msg.speaker_id }}</strong>
              </span>
              <span v-else class="dir-in">
                🤫 INBOUND WHISPER ·
                <strong class="click-spk" @click="$emit('select-speaker', msg.speaker_id)">{{ msg.speaker_id }}</strong>
              </span>

              <span class="cb-tags">
                <span v-if="msg.earworm_delta_hook" class="tag-delta">Δ "{{ msg.earworm_delta_hook }}"</span>
                <span v-if="msg.origin === 'auto_conversation'" class="tag-ai">NightSweep Auto</span>
                <span v-if="msg.midair_emitted" class="tag-air">PortAudio TX</span>
                <span v-if="msg.udp_blocks > 0" class="tag-udp">UDP :5005</span>
                <span>{{ (msg.timestamp_utc || '').slice(11, 19) }}</span>
              </span>
            </div>

            <div class="cb-text">"{{ msg.text }}"</div>

            <div v-if="msg.audio_url" class="cb-audio">
              <audio :src="msg.audio_url" controls preload="none" class="mini-wav"></audio>
              <span class="dur mono">{{ msg.duration_sec }}s · {{ msg.acoustic_style }}</span>
            </div>
          </div>

          <div v-if="!reversedMessages.length" class="empty-note mono">
            No talkback turns yet. Arm a whisper payload below or enable
            <strong>Start Talking Back</strong> in Auto-Conversation mode!
          </div>
        </div>

        <!-- QUICK TEMPLATES + COMPOSER -->
        <div class="composer">
          <div class="quick-prompts mono">
            <span>Quick Drafts:</span>
            <button type="button" class="qp-btn" @click="useTemplate('echo')">
              Echo Earworm Δ
            </button>
            <button type="button" class="qp-btn" @click="useTemplate('continue')">
              Ask Next Line
            </button>
            <button type="button" class="qp-btn" @click="useTemplate('checkin')">
              Quiet Check-In
            </button>
          </div>

          <div class="composer-row">
            <input
              v-model="draftText"
              type="text"
              class="chat-input"
              placeholder="Type a mid-air low-ambient whisper payload to send back..."
              @keyup.enter="sendChat(false)"
            />
          </div>

          <div class="composer-actions mono">
            <button
              type="button"
              class="btn btn-gated"
              :disabled="busy || !draftText.trim()"
              @click="sendChat(false)"
              title="Only transmits once the Earworm Delta is confirmed (queues & arms automatically if still harvesting)"
            >
              🔒 {{ harvester.delta_confirmed && state.talkback_enabled ? 'Send Confirmed Δ Whisper' : 'Arm Until Earworm Δ Confirmed' }}
            </button>
            <button
              type="button"
              class="btn btn-now"
              :disabled="busy || !draftText.trim()"
              @click="sendChat(true)"
              title="Transmit this mid-air acoustic whisper immediately for live chat or speaker verification"
            >
              🔊 Whisper Now (Immediate TX)
            </button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  talkback: { type: Object, default: () => ({}) },
  prefillDraft: { type: Object, default: null },
})

defineEmits(['select-speaker', 'updated'])

const localState = ref(null)
const draftText = ref('')
const busy = ref(false)
const feedbackBanner = ref('')

const state = computed(() => localState.value || props.talkback || {})
const harvester = computed(() => state.value.harvester || {})
const reversedMessages = computed(() => {
  const list = state.value.messages || []
  return [...list].reverse().slice(0, 14)
})

watch(
  () => props.talkback,
  (val) => {
    if (val && Object.keys(val).length) {
      localState.value = val
    }
  },
  { immediate: true, deep: true }
)

watch(
  () => props.prefillDraft,
  (draft) => {
    if (!draft) return
    const hook = draft.phrase || harvester.value.active_delta_hook || 'that whisper'
    draftText.value = `I hear your "${hook}" whisper, ${draft.speakerId || 'friend'} — what comes next?`
    if (draft.speakerId) {
      updateConfig({ target_speaker: draft.speakerId })
    }
  }
)

function flashFeedback(msg) {
  feedbackBanner.value = msg
  setTimeout(() => {
    if (feedbackBanner.value === msg) feedbackBanner.value = ''
  }, 5500)
}

async function toggleTalkback(enable) {
  await updateConfig({ talkback_enabled: enable })
  flashFeedback(
    enable
      ? '🔊 Mid-Air Whisper Talkback ENABLED — GNU-Larex will respond once Earworm Δ is confirmed.'
      : '🔇 Mid-Air Whisper Talkback MUTED — Passive listening only.'
  )
}

async function updateConfig(patch) {
  busy.value = true
  try {
    const res = await fetch('/api/talkback/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
    if (res.ok) {
      localState.value = await res.json()
    }
  } catch (e) {
    console.error('Talkback config error:', e)
  } finally {
    busy.value = false
  }
}

function prefillWithHook(speakerId, hook) {
  draftText.value = `I caught your whisper on "${hook}" — keep going, I'm listening.`
  if (speakerId) {
    updateConfig({ target_speaker: speakerId })
  }
}

function useTemplate(kind) {
  const hk = harvester.value.active_delta_hook || 'see you'
  if (kind === 'echo') {
    draftText.value = `Echoing "${hk}" softly back across the room — earworm delta confirmed.`
  } else if (kind === 'continue') {
    draftText.value = `I caught "${hk}" in the quiet air — whisper the next line to me.`
  } else {
    draftText.value = `Live low-ambient whisper link is open on "${hk}" — can you hear me?`
  }
}

async function sendChat(forceNow) {
  const txt = draftText.value.trim()
  if (!txt) return
  busy.value = true
  try {
    if (!forceNow && !state.value.talkback_enabled) {
      // Enable talkback option automatically when user explicitly arms a gated talkback reply, or keep clear status
      await fetch('/api/talkback/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ talkback_enabled: true }),
      })
    }
    const res = await fetch('/api/talkback/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: txt,
        target_speaker: harvester.value.target_speaker || 'ANY',
        require_delta_confirmation: !forceNow,
        force_now: Boolean(forceNow),
      }),
    })
    if (res.ok) {
      const data = await res.json()
      if (data.status) localState.value = data.status
      draftText.value = ''
      if (data.action === 'TRANSMITTED') {
        flashFeedback(`🔊 Whisper transmitted (${data.message?.duration_sec}s): "${data.message?.text}"`)
        if (state.value.auto_play_browser !== false && data.message?.audio_url) {
          try {
            const aud = new Audio(data.message.audio_url)
            aud.volume = 0.65
            aud.play().catch(() => {})
          } catch (_) {}
        }
      } else {
        flashFeedback('🔒 Whisper payload ARMED — waiting for repeated low-ambient Earworm Δ confirmation!')
      }
    }
  } catch (e) {
    console.error('Talkback send error:', e)
  } finally {
    busy.value = false
  }
}

async function clearArmed() {
  busy.value = true
  try {
    const res = await fetch('/api/talkback/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ clear_armed: true }),
    })
    if (res.ok) {
      const data = await res.json()
      if (data.status) localState.value = data.status
      flashFeedback('Cleared armed whisper payload queue.')
    }
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.talkback-panel {
  background: #161b22;
  border: 1px solid #30363d;
  border-radius: 12px;
  padding: 16px 18px;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.talkback-panel.armed {
  border-color: rgba(63, 185, 80, 0.65);
  box-shadow: 0 0 0 1px rgba(63, 185, 80, 0.18), 0 8px 26px rgba(0, 0, 0, 0.35);
}
.panel-hdr {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
h2 {
  margin: 0;
  font-size: 1.04rem;
  color: #f0f6fc;
}
.sub {
  margin: 4px 0 0;
  font-size: 0.8rem;
  color: #8b949e;
}
.badge {
  font-size: 0.7rem;
  padding: 3px 9px;
  border-radius: 999px;
  font-weight: 600;
}
.badge-live {
  background: rgba(63, 185, 80, 0.18);
  color: #3fb950;
  border: 1px solid rgba(63, 185, 80, 0.5);
}
.badge-passive {
  background: rgba(139, 148, 158, 0.14);
  color: #c9d1d9;
  border: 1px solid #30363d;
}
.badge-guard {
  background: rgba(88, 166, 255, 0.12);
  color: #79c0ff;
  border: 1px solid rgba(88, 166, 255, 0.35);
}

.optin-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: #21262d;
  color: #f0f6fc;
  border: 1px solid #f0883e;
  border-radius: 8px;
  padding: 9px 14px;
  font-size: 0.8rem;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.16s;
}
.optin-btn:hover {
  background: rgba(240, 136, 62, 0.16);
}
.optin-btn.enabled {
  background: rgba(35, 134, 54, 0.28);
  border-color: #3fb950;
  color: #7ee787;
}
.dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #8b949e;
}
.dot.live {
  background: #3fb950;
  box-shadow: 0 0 8px #3fb950;
}

.delta-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  background: rgba(240, 136, 62, 0.08);
  border: 1px solid rgba(240, 136, 62, 0.35);
  border-radius: 9px;
  padding: 10px 13px;
  margin-bottom: 12px;
}
.delta-banner.confirmed {
  background: rgba(46, 160, 67, 0.11);
  border-color: rgba(63, 185, 80, 0.5);
}
.delta-status {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 5px;
}
.pill-ok {
  background: #238636;
  color: #fff;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: 700;
}
.pill-wait {
  background: #9e6a03;
  color: #fff;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: 700;
}
.reason-txt {
  font-size: 0.76rem;
  color: #c9d1d9;
}
.delta-hook-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.lbl {
  font-size: 0.73rem;
  color: #8b949e;
}
.hook-phrase {
  font-size: 0.96rem;
  color: #f0f6fc;
}
.chip {
  background: #0d1117;
  border: 1px solid #30363d;
  color: #c9d1d9;
  padding: 2px 7px;
  border-radius: 999px;
  font-size: 0.7rem;
}
.chip.cyan {
  color: #79c0ff;
  border-color: rgba(88, 166, 255, 0.4);
}
.chip.violet {
  color: #d2a8ff;
  background: rgba(163, 113, 247, 0.14);
  border-color: rgba(163, 113, 247, 0.52);
  font-weight: 600;
}
.prom-cand-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  padding: 7px 10px;
  margin-bottom: 8px;
  border-radius: 7px;
  background: rgba(163, 113, 247, 0.08);
  border: 1px solid rgba(163, 113, 247, 0.3);
  font-size: 0.71rem;
}
.prom-lbl {
  color: #d2a8ff;
  font-weight: 600;
}
.prom-chip {
  background: #0d1117;
  border: 1px solid rgba(163, 113, 247, 0.35);
  color: #e2c5ff;
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 0.69rem;
  cursor: pointer;
}
.prom-chip.active {
  background: rgba(163, 113, 247, 0.25);
  border-color: #d2a8ff;
  color: #fff;
}
.spk-chip {
  background: rgba(88, 166, 255, 0.12);
  border: 1px solid rgba(88, 166, 255, 0.45);
  color: #58a6ff;
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 0.7rem;
  cursor: pointer;
}
.delta-right {
  font-size: 0.74rem;
  color: #8b949e;
  text-align: right;
}
.prev-delta {
  color: #d2a8ff;
  margin-top: 3px;
}

.controls-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(175px, 1fr));
  gap: 10px;
  background: #0d1117;
  border: 1px solid #21262d;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
}
.ctrl-item {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.ctrl-item label {
  font-size: 0.69rem;
  color: #8b949e;
  text-transform: uppercase;
}
.ctrl-item select,
.ctrl-item input[type='range'] {
  background: #161b22;
  color: #e6edf3;
  border: 1px solid #30363d;
  border-radius: 6px;
  padding: 5px 7px;
  font-size: 0.75rem;
}
.seg-pair {
  display: flex;
  gap: 4px;
}
.seg {
  flex: 1;
  background: #161b22;
  color: #8b949e;
  border: 1px solid #30363d;
  border-radius: 6px;
  padding: 5px 6px;
  font-size: 0.71rem;
  cursor: pointer;
}
.seg.active {
  background: rgba(88, 166, 255, 0.18);
  color: #58a6ff;
  border-color: #58a6ff;
  font-weight: 600;
}

.feedback-bar {
  background: rgba(56, 139, 253, 0.14);
  border: 1px solid rgba(88, 166, 255, 0.45);
  color: #79c0ff;
  padding: 7px 11px;
  border-radius: 7px;
  font-size: 0.76rem;
  margin-bottom: 12px;
}

.studio-cols {
  display: grid;
  grid-template-columns: 1fr 1.25fr;
  gap: 14px;
}
@media (max-width: 980px) {
  .studio-cols {
    grid-template-columns: 1fr;
  }
}
.col-box {
  background: #0d1117;
  border: 1px solid #21262d;
  border-radius: 9px;
  padding: 11px 12px;
  display: flex;
  flex-direction: column;
  gap: 9px;
}
.box-hdr {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.76rem;
  color: #c9d1d9;
  font-weight: 600;
}
.muted {
  color: #8b949e;
  font-weight: 400;
}
.chk-inline {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 0.71rem;
  color: #8b949e;
  cursor: pointer;
}

.armed-queue {
  background: rgba(210, 168, 255, 0.09);
  border: 1px solid rgba(210, 168, 255, 0.38);
  border-radius: 7px;
  padding: 8px 10px;
}
.armed-hdr {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.71rem;
  color: #d2a8ff;
  margin-bottom: 5px;
}
.mini-clear {
  background: transparent;
  border: 1px solid #30363d;
  color: #c9d1d9;
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 0.68rem;
  cursor: pointer;
}
.armed-row {
  display: flex;
  gap: 8px;
  font-size: 0.73rem;
  padding: 3px 0;
}
.arm-tag {
  color: #f0883e;
}
.arm-txt {
  color: #f0f6fc;
}

.harvest-list,
.chat-feed {
  max-height: 255px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.harvest-card {
  background: #161b22;
  border: 1px solid #21262d;
  border-radius: 7px;
  padding: 7px 9px;
}
.hc-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 6px;
  font-size: 0.69rem;
  color: #8b949e;
}
.spk-link {
  background: transparent;
  border: none;
  color: #58a6ff;
  padding: 0;
  cursor: pointer;
  font-weight: 600;
}
.hc-contour {
  color: #79c0ff;
}
.hc-txt {
  font-size: 0.81rem;
  color: #e6edf3;
  margin: 4px 0;
}
.hc-hooks {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.hk-pill {
  background: #0d1117;
  border: 1px solid #30363d;
  color: #8b949e;
  border-radius: 999px;
  padding: 1px 7px;
  font-size: 0.68rem;
  cursor: pointer;
}
.hk-pill.match {
  border-color: #3fb950;
  color: #7ee787;
}

.chat-bubble {
  border-radius: 8px;
  padding: 8px 10px;
  border: 1px solid #21262d;
}
.chat-bubble.inbound {
  background: #161b22;
  border-left: 3px solid #58a6ff;
}
.chat-bubble.outbound {
  background: rgba(35, 134, 54, 0.12);
  border-color: rgba(63, 185, 80, 0.35);
  border-left: 3px solid #3fb950;
}
.cb-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 0.69rem;
  margin-bottom: 4px;
}
.dir-out {
  color: #7ee787;
}
.dir-in {
  color: #79c0ff;
}
.click-spk {
  cursor: pointer;
  text-decoration: underline;
}
.cb-tags {
  display: flex;
  gap: 5px;
  align-items: center;
  color: #8b949e;
}
.tag-delta {
  color: #d2a8ff;
}
.tag-ai {
  background: rgba(210, 168, 255, 0.16);
  color: #d2a8ff;
  padding: 1px 5px;
  border-radius: 4px;
}
.tag-air {
  background: rgba(63, 185, 80, 0.18);
  color: #3fb950;
  padding: 1px 5px;
  border-radius: 4px;
}
.tag-udp {
  background: rgba(88, 166, 255, 0.16);
  color: #79c0ff;
  padding: 1px 5px;
  border-radius: 4px;
}
.cb-text {
  font-size: 0.84rem;
  color: #f0f6fc;
}
.cb-audio {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}
.mini-wav {
  height: 28px;
  flex: 1;
}
.dur {
  font-size: 0.68rem;
  color: #8b949e;
}

.composer {
  border-top: 1px solid #21262d;
  padding-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.quick-prompts {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 0.7rem;
  color: #8b949e;
}
.qp-btn {
  background: #161b22;
  color: #c9d1d9;
  border: 1px solid #30363d;
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 0.69rem;
  cursor: pointer;
}
.qp-btn:hover {
  border-color: #58a6ff;
  color: #58a6ff;
}
.chat-input {
  width: 100%;
  box-sizing: border-box;
  background: #161b22;
  color: #f0f6fc;
  border: 1px solid #30363d;
  border-radius: 7px;
  padding: 8px 10px;
  font-size: 0.82rem;
}
.composer-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.btn {
  border-radius: 7px;
  padding: 7px 12px;
  font-size: 0.75rem;
  font-weight: 600;
  cursor: pointer;
  border: 1px solid #30363d;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.btn-gated {
  flex: 1;
  background: #238636;
  border-color: #2ea043;
  color: #ffffff;
}
.btn-now {
  background: rgba(88, 166, 255, 0.16);
  border-color: rgba(88, 166, 255, 0.5);
  color: #79c0ff;
}
.empty-note {
  color: #8b949e;
  font-size: 0.75rem;
  padding: 12px 4px;
}
</style>
