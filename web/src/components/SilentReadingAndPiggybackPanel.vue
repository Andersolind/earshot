<template>
  <section id="reading-piggyback-studio" class="card rpb-card">
    <div class="card-header">
      <div>
        <div class="card-title">
          <span>📖 ThreeStateVADRouter · Silent Reading Out-Loud Mode &amp; 🧱 Mid-Air Piggyback</span>
          <span
            class="pill mono"
            :class="
              threeVad.state === 'READING'
                ? 'amber-pill'
                : threeVad.state === 'ACTIVE'
                ? 'green-pill'
                : 'muted-pill'
            "
          >
            🎛️ 3-State VAD: {{ threeVad.state || 'STANDBY' }}
            <template v-if="threeVad.state === 'READING'">
              (~{{ threeVad.last_wpm || reading.estimated_wpm || 200 }} WPM · Drone {{ Math.round((threeVad.drone_gain || 0) * 100) }}%)
            </template>
          </span>
          <span
            class="pill mono"
            :class="localCfg.hear_reading_out_loud ? 'green-pill' : 'muted-pill'"
          >
            🔊 Out-Loud Reading: {{ localCfg.hear_reading_out_loud ? 'ENABLED' : 'MUTED' }}
          </span>
          <span
            class="pill mono click-pill"
            :class="localCfg.auto_play_out_loud ? 'green-pill' : 'amber-pill'"
            title="Click to toggle Auto-Speak in Browser whenever ThreeStateVADRouter enters READING"
            @click="localCfg.auto_play_out_loud = !localCfg.auto_play_out_loud; pushConfig({ auto_play_out_loud: localCfg.auto_play_out_loud })"
          >
            🎧 Auto-Speak Browser: {{ localCfg.auto_play_out_loud ? 'ON' : 'MANUAL' }}
          </span>
          <span
            class="pill mono click-pill sky-pill"
            title="Click to inspect OTHER_ROOM_SUBLEVEL dossier & play demodulated sublevel WAV"
            @click="$emit('select-speaker', 'OTHER_ROOM_SUBLEVEL')"
          >
            🧱 OTHER_ROOM_SUBLEVEL: {{ pb.total_piggyback_captures ?? 0 }} captures ↗
          </span>
        </div>
        <div class="sub-caption">
          Routes <span class="mono">STANDBY ↔ READING ↔ ACTIVE</span> via <span class="mono">ThreeStateVADRouter</span> (<span class="mono">110 / 164.81 / 220 Hz</span> warm <span class="mono">A2–E3–A3</span> open-fifth WPM drone + spoken out-loud vocalization) &amp; IQ-demodulates <span class="mono">13.5–23.6 kHz</span> mid-air piggyback sublevels
        </div>
      </div>

      <div class="hdr-actions">
        <button class="btn btn-ollama mono" :disabled="ollamaBusy" @click="askOllama">
          {{ ollamaBusy ? '🧠 Consulting NightSweep…' : '🧠 Ask Ollama Modal to Advise' }}
        </button>
      </div>
    </div>

    <!-- NIGHTSWEEP OLLAMA ADVISOR (3-STATE VAD + READING OUT-LOUD + CLOSEST FAINT FOCUS + PIGGYBACK) -->
    <div v-if="advisor" class="ollama-drawer">
      <div class="od-top">
        <div class="mono od-title">
          🧠 <strong>{{ advisor.model || 'nightsweep-signalintelligence:latest' }}</strong>
          <span class="pill mono" :style="{ color: advisor.ollama_live ? '#3fb950' : '#d2a8ff' }">
            {{ advisor.ollama_live ? 'LIVE OLLAMA RESPONSE' : 'CALIBRATED PROFILE' }}
          </span>
        </div>
        <button class="btn btn-apply mono" :disabled="applyBusy" @click="applyRecommended">
          ⚡ Apply 3-State Reading, Faint-Focus &amp; Piggyback Config
        </button>
      </div>
      <p class="od-summary">{{ advisor.overall_assessment }}</p>
      <div class="od-cols">
        <div v-if="advisor.voice_gender_analysis?.length" class="od-col">
          <div class="sec-lbl mono" style="color: #e9d5ff">♀️/♂️ Male vs. Female Voice Biometrics Study</div>
          <ul>
            <li v-for="(t, i) in advisor.voice_gender_analysis" :key="'vga-' + i">{{ t }}</li>
          </ul>
        </div>
        <div v-if="advisor.covert_piggyback_advice?.length" class="od-col">
          <div class="sec-lbl mono" style="color: #38bdf8">🕵️ 3-Stage Covert Piggyback Audio (analyze_covert_audio)</div>
          <ul>
            <li v-for="(t, i) in advisor.covert_piggyback_advice" :key="'cpa-' + i">{{ t }}</li>
          </ul>
        </div>
        <div v-if="advisor.reading_outloud_and_vad_advice?.length" class="od-col">
          <div class="sec-lbl mono">🔊 ThreeStateVADRouter &amp; Silent Reading Out-Loud</div>
          <ul>
            <li v-for="(t, i) in advisor.reading_outloud_and_vad_advice" :key="'rol-' + i">{{ t }}</li>
          </ul>
        </div>
        <div v-if="advisor.closest_faint_focus_advice?.length" class="od-col">
          <div class="sec-lbl mono">🎯 Closest-Identity Ultra-Faint Room Focus</div>
          <ul>
            <li v-for="(t, i) in advisor.closest_faint_focus_advice" :key="'cff-' + i">{{ t }}</li>
          </ul>
        </div>
        <div class="od-col">
          <div class="sec-lbl mono">🌊 Mid-Air Carrier AM/PM Piggyback Demod</div>
          <ul>
            <li v-for="(t, i) in advisor.piggyback_demod_advice || []" :key="'pd-' + i">{{ t }}</li>
          </ul>
        </div>
        <div class="od-col">
          <div class="sec-lbl mono">📖 SilentReadingDetector Occupant Veto</div>
          <ul>
            <li v-for="(t, i) in advisor.silent_reading_veto_advice || []" :key="'sr-' + i">{{ t }}</li>
          </ul>
        </div>
      </div>
    </div>

    <div v-if="banner" class="status-banner mono">✅ {{ banner }}</div>

    <!-- 2-COLUMN BODY -->
    <div class="rpb-grid">
      <!-- LEFT: THREE-STATE VAD ROUTER & SILENT READING OUT-LOUD STUDIO -->
      <div class="rpb-box">
        <div class="box-hdr">
          <div class="box-title mono">🔊 ThreeStateVADRouter &amp; Silent Reading Out-Loud Mode</div>
          <span
            class="veto-badge mono"
            :class="reading.is_physically_still ? 'veto-ok' : 'veto-busy'"
          >
            {{ reading.is_physically_still ? '✓ CLOSED MOUTH / STILL HANDS' : '✗ LOCAL MOUTH/HAND MOTION' }}
          </span>
        </div>

        <!-- 3-STATE PIPELINE INDICATOR -->
        <div class="state-stepper mono">
          <div class="st-node" :class="{ active: (threeVad.state || 'STANDBY') === 'STANDBY' }">
            <span class="st-name">1 · STANDBY</span>
            <span class="st-meta">Floor {{ Number(threeVad.noise_floor || 0.004).toFixed(4) }}</span>
          </div>
          <span class="st-arrow">⇄</span>
          <div class="st-node reading-node" :class="{ active: threeVad.state === 'READING' }">
            <span class="st-name">2 · READING</span>
            <span class="st-meta">A2·E3·A3 + Out-Loud</span>
          </div>
          <span class="st-arrow">⇄</span>
          <div class="st-node active-node" :class="{ active: threeVad.state === 'ACTIVE' }">
            <span class="st-name">3 · ACTIVE</span>
            <span class="st-meta">Hold {{ threeVad.hangover_blocks ?? 0 }}/{{ threeVad.max_hangover ?? 7 }}</span>
          </div>
        </div>

        <!-- OUT-LOUD READING CONTROLS + DRONE TELEMETRY -->
        <div class="reading-hero">
          <div class="rh-main">
            <div class="rh-lbl mono">
              SILENT READING OUT-LOUD + WARM A2–E3–A3 (110 · 164.81 · 220 HZ) WPM SHIMMER DRONE
            </div>
            <div class="rh-val">
              <strong :style="{ color: reading.state === 'SILENT_READING' || threeVad.state === 'READING' ? '#fbbf24' : '#c9d1d9' }">
                {{ threeVad.state || reading.state || 'STANDBY' }}
              </strong>
              <span class="rh-wpm mono">
                {{ reading.syllable_rate_hz || 4.5 }} Hz · ~{{ threeVad.last_wpm || reading.estimated_wpm || 200 }} WPM · Detune +{{ threeVad.wpm_detune_hz ?? 0.16 }} Hz
              </span>
            </div>
            <div class="rh-sub mono">
              Drone Gain: {{ Math.round((threeVad.drone_gain || 0) * 100) }}% · Micro-Tension: {{ Number(reading.micro_tension || 0).toFixed(5) }} · Out-Loud Renders: {{ threeVad.total_out_loud_renders ?? 0 }}
            </div>
          </div>

          <div class="rh-btns">
            <button class="btn btn-outloud mono" :disabled="simBusy" @click="simulate('READING_OUT_LOUD')">
              🔊 Hear Silent Reading Out Loud
            </button>
            <button class="btn btn-read mono" :disabled="simBusy" @click="simulate('SILENT_READING')">
              📖 Cadence Only
            </button>
          </div>
        </div>

        <!-- TOGGLES + PASSAGE OVERRIDE -->
        <div class="outloud-toggles mono">
          <label class="chk-pill">
            <input
              type="checkbox"
              v-model="localCfg.hear_reading_out_loud"
              @change="pushConfig({ hear_reading_out_loud: localCfg.hear_reading_out_loud })"
            />
            🔊 Hear Silent Reading Out Loud
          </label>
          <label class="chk-pill">
            <input
              type="checkbox"
              v-model="localCfg.auto_play_out_loud"
              @change="pushConfig({ auto_play_out_loud: localCfg.auto_play_out_loud })"
            />
            🎧 Auto-Speak in Browser
          </label>
          <label class="chk-pill">
            <input
              type="checkbox"
              v-model="localCfg.udp_out_loud_mirror"
              @change="pushConfig({ udp_out_loud_mirror: localCfg.udp_out_loud_mirror })"
            />
            📡 Mirror to Master Mixer (:5005)
          </label>
        </div>

        <div class="passage-bar">
          <input
            v-model="customReadingText"
            type="text"
            class="passage-input"
            placeholder="Optional reading passage override (leave blank to vocalize live Markov Order-3/4 / subvocal context)..."
            @keyup.enter="simulate('READING_OUT_LOUD')"
          />
        </div>

        <div class="sliders-grid mono">
          <label>
            <span>Out-Loud Voice Level: <b>{{ Math.round(localCfg.out_loud_voice_gain * 100) }}%</b></span>
            <input
              type="range" min="0.25" max="1.00" step="0.05"
              v-model.number="localCfg.out_loud_voice_gain"
              @change="pushConfig({ out_loud_voice_gain: localCfg.out_loud_voice_gain })"
            />
          </label>
          <label>
            <span>A2–E3–A3 Drone Mix: <b>{{ Math.round(localCfg.out_loud_drone_mix * 100) }}%</b></span>
            <input
              type="range" min="0.05" max="0.90" step="0.05"
              v-model.number="localCfg.out_loud_drone_mix"
              @change="pushConfig({ out_loud_drone_mix: localCfg.out_loud_drone_mix })"
            />
          </label>
          <label>
            <span>Mouth Still Ceiling: <b>{{ localCfg.mouth_still_ceiling.toFixed(3) }}</b></span>
            <input
              type="range" min="0.004" max="0.050" step="0.001"
              v-model.number="localCfg.mouth_still_ceiling"
              @change="pushConfig({ mouth_still_ceiling: localCfg.mouth_still_ceiling })"
            />
          </label>
          <label>
            <span>Typing Still Ceiling: <b>{{ localCfg.typing_still_ceiling.toFixed(3) }}</b></span>
            <input
              type="range" min="0.004" max="0.060" step="0.001"
              v-model.number="localCfg.typing_still_ceiling"
              @change="pushConfig({ typing_still_ceiling: localCfg.typing_still_ceiling })"
            />
          </label>
        </div>

        <!-- PLAYABLE SILENT READING OUT-LOUD WAV FEED -->
        <div class="feed-hdr mono">
          <span>🗣️ Silent Reading Out-Loud Audio Feed (48 kHz Voice + A2–E3–A3 WPM Drone)</span>
          <span>{{ outLoudEvents.length }} renders</span>
        </div>
        <div v-if="outLoudEvents.length" class="ev-list">
          <div v-for="ol in outLoudEvents.slice(0, 4)" :key="ol.id" class="ev-row outloud-row">
            <div class="ev-top mono">
              <strong style="color: #fbbf24">📖 {{ ol.speaker_id }} · ~{{ ol.estimated_wpm }} WPM</strong>
              <span>{{ ol.lexical_source }} · Detune +{{ ol.wpm_detune_hz }} Hz</span>
              <span class="ev-ts">{{ (ol.timestamp_utc || '').slice(11, 19) }}</span>
            </div>
            <div class="ev-bot mono">
              <span class="ev-desc">"{{ ol.spoken_text }}"</span>
              <audio :src="ol.audio_url" controls preload="none" class="mini-audio"></audio>
            </div>
          </div>
        </div>
        <div v-else class="empty-note mono">
          Click "🔊 Hear Silent Reading Out Loud" or read silently (3–6.5 Hz laryngeal twitches) to synthesize spoken reading + warm A2–E3–A3 drone.
        </div>
      </div>

      <!-- RIGHT: MID-AIR PIGGYBACK OTHER-ROOM SUBLEVEL DEMODULATOR -->
      <div class="rpb-box">
        <div class="box-hdr">
          <div class="box-title mono">🧱 Gates 2 &amp; 3 · Mid-Air Carrier IQ Piggyback Demodulator</div>
          <span class="sky-badge mono">M6 Isolated · Outer Boundary (3.35 m)</span>
        </div>

        <div
          class="other-card"
          title="Click to inspect OTHER_ROOM_SUBLEVEL dossier & play demodulated sublevel audio"
          @click="$emit('select-speaker', 'OTHER_ROOM_SUBLEVEL')"
        >
          <div class="oc-top">
            <div class="oc-id mono">
              🧱 OTHER_ROOM_SUBLEVEL
              <span class="open-chip">Click Non-Occupant Dossier ↗</span>
            </div>
            <button
              type="button"
              class="btn btn-piggy mono"
              :disabled="simBusy"
              @click.stop="simulate('PIGGYBACK_SUBLEVEL')"
            >
              🌊 Demodulate Piggyback Sublevel
            </button>
          </div>
          <div class="oc-desc">
            Quadrature AM + unwrapped-PM sideband demodulation of <strong>{{ ((pb.last_carrier_hz || 19200) / 1000).toFixed(1) }} kHz</strong> live mid-air standing mode + negative-DRR boundary wave
          </div>
          <div class="oc-metrics mono">
            <span>Air Carrier: <b>{{ Math.round(pb.last_carrier_hz || 19200) }} Hz</b></span>
            <span>Coherence: <b style="color: #38bdf8">{{ Number(pb.last_coherence || 0).toFixed(2) }}</b></span>
            <span>Boundary DRR: <b>{{ Number(pb.last_drr_db || 0).toFixed(1) }} dB</b></span>
            <span>Wall LPF: <b>{{ Number(pb.last_wall_lpf_ratio || 0).toFixed(1) }}×</b></span>
          </div>
        </div>

        <div class="sliders-grid mono">
          <label>
            <span>Carrier Coherence Thresh: <b>{{ localCfg.coherence_thresh.toFixed(2) }}</b></span>
            <input
              type="range" min="0.14" max="0.75" step="0.02"
              v-model.number="localCfg.coherence_thresh"
              @change="pushConfig({ coherence_thresh: localCfg.coherence_thresh })"
            />
          </label>
          <label>
            <span>Max Boundary DRR: <b>{{ localCfg.max_drr_db.toFixed(1) }} dB</b></span>
            <input
              type="range" min="-5.0" max="3.0" step="0.2"
              v-model.number="localCfg.max_drr_db"
              @change="pushConfig({ max_drr_db: localCfg.max_drr_db })"
            />
          </label>
          <label>
            <span>Sublevel Boost: <b>+{{ localCfg.sublevel_boost_db.toFixed(1) }} dB</b></span>
            <input
              type="range" min="6.0" max="30.0" step="0.5"
              v-model.number="localCfg.sublevel_boost_db"
              @change="pushConfig({ sublevel_boost_db: localCfg.sublevel_boost_db })"
            />
          </label>
          <label>
            <span>Wall Bearing: <b>{{ (localCfg.boundary_azimuth_deg > 0 ? '+' : '') + localCfg.boundary_azimuth_deg }}°</b></span>
            <input
              type="range" min="-75" max="75" step="1"
              v-model.number="localCfg.boundary_azimuth_deg"
              @change="pushConfig({ boundary_azimuth_deg: localCfg.boundary_azimuth_deg })"
            />
          </label>
        </div>

        <div class="explain-note">
          <strong>3-State VAD + Piggyback Synergy:</strong> When <code class="mono">ThreeStateVADRouter</code> is in <code class="mono">READING</code> or <code class="mono">STANDBY</code> (<code class="mono">mouth_open_energy &lt; 0.015</code>, <code class="mono">typing_hf_energy &lt; 0.020</code>), local silent reading is spoken out loud over the warm <code class="mono">A2–E3–A3</code> drone while any non-occupant acoustic sidebands on <code class="mono">13.5–23.6 kHz</code> room modes are cleanly isolated into <code class="mono">OTHER_ROOM_SUBLEVEL</code>.
        </div>

        <div class="feed-hdr mono">
          <span>🔊 Demodulated Other-Room Sublevel Stream (48 kHz Reconstructed WAV)</span>
          <span>{{ (pb.recent_captures || []).length }} events</span>
        </div>
        <div v-if="pb.recent_captures?.length" class="ev-list">
          <div v-for="ev in pb.recent_captures.slice(0, 4)" :key="ev.id" class="ev-row">
            <div class="ev-top mono">
              <strong style="color: #38bdf8">{{ ev.token }}</strong>
              <span>Carrier {{ (ev.carrier_hz / 1000).toFixed(1) }} kHz · r={{ ev.coherence }} · DRR {{ ev.drr_db }} dB · Occupant: {{ ev.occupant_reading_state }}</span>
              <span class="ev-ts">{{ (ev.timestamp_utc || '').slice(11, 19) }}</span>
            </div>
            <div class="ev-bot mono">
              <span class="ev-desc">{{ ev.transcript }}</span>
              <audio :src="ev.audio_url" controls preload="none" class="mini-audio"></audio>
            </div>
          </div>
        </div>
        <div v-else class="empty-note mono">
          Monitoring 13.5–23.6 kHz mid-air standing modes for non-occupant boundary AM/PM sidebands while room occupants are still.
        </div>
      </div>
    </div>

    <!-- 3-STAGE COVERT PIGGYBACK AUDIO SCANNER (analyze_covert_audio) & MALE/FEMALE VOICE BIOMETRICS STUDIO -->
    <div class="rpb-grid" style="margin-top: 12px">
      <!-- LEFT: 3-STAGE COVERT PIGGYBACK AUDIO SCANNER -->
      <div class="rpb-box">
        <div class="box-hdr">
          <div class="box-title mono">🕵️ 3-Stage Covert Piggyback Word Scanner (analyze_covert_audio)</div>
          <span class="sky-badge mono">{{ latestCovertScan.sample_rate_hz || 96000 }} Hz · {{ latestCovertScan.channels || 'Stereo' }}</span>
        </div>

        <div class="rh-btns" style="margin-bottom: 10px; display: flex; flex-wrap: wrap; gap: 6px">
          <button class="btn btn-piggy mono" :disabled="covertBusy" @click="runCovertScan('COMPOSITE_PIGGYBACK')">
            ⚡ Scan All 3 Piggyback Vectors
          </button>
          <button class="btn btn-read mono" :disabled="covertBusy" @click="runCovertScan('ULTRASONIC_PARAMETRIC')">
            🔊 [1] &gt;22 kHz Parametric
          </button>
          <button class="btn btn-read mono" :disabled="covertBusy" @click="runCovertScan('DICHOTIC_CHIMERA')">
            🎧 [2] Dichotic Hilbert L/R
          </button>
          <button class="btn btn-outloud mono" :disabled="covertBusy" @click="runCovertScan('PHASE_INVERTED_SIDE')">
            🔄 [3] Mid/Side Anti-Phase
          </button>
        </div>

        <div class="oc-metrics mono" style="margin-bottom: 8px; display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 6px">
          <div class="ev-row">
            <strong style="color: #38bdf8">[1] Ultrasonic (&gt;22 kHz)</strong>
            <div>Peak: <b>{{ latestCovertScan.ultrasonic_parametric_scan?.peak_ultra_freq_hz || 40000 }} Hz</b> · Ratio: <b>{{ latestCovertScan.ultrasonic_parametric_scan?.ultra_to_audible_ratio ?? 0.428 }}</b></div>
            <div :style="{ color: latestCovertScan.ultrasonic_parametric_scan?.alert ? '#ff7b72' : '#7ee787' }">
              {{ latestCovertScan.ultrasonic_parametric_scan?.verdict || '[ALERT] High ultrasonic energy detected!' }}
            </div>
          </div>
          <div class="ev-row">
            <strong style="color: #d2a8ff">[2] Dichotic &amp; Chimera (L/R)</strong>
            <div>Wave Corr: <b>{{ latestCovertScan.dichotic_binaural_scan?.waveform_correlation ?? -0.824 }}</b> · Hilbert Env: <b>{{ latestCovertScan.dichotic_binaural_scan?.envelope_correlation ?? 0.142 }}</b></div>
            <div :style="{ color: latestCovertScan.dichotic_binaural_scan?.alert ? '#fbbf24' : '#7ee787' }">
              {{ latestCovertScan.dichotic_binaural_scan?.verdict || '[ALERT] Dichotic Listening detected!' }}
            </div>
          </div>
          <div class="ev-row">
            <strong style="color: #7ee787">[3] Mid/Side Phase Inversion</strong>
            <div>Side/Mid Ratio: <b>{{ latestCovertScan.phase_inversion_mid_side_scan?.side_to_mid_ratio ?? 3.14 }}</b> (Mid {{ latestCovertScan.phase_inversion_mid_side_scan?.mid_rms ?? 0.04 }} / Side {{ latestCovertScan.phase_inversion_mid_side_scan?.side_rms ?? 0.13 }})</div>
            <div :style="{ color: latestCovertScan.phase_inversion_mid_side_scan?.alert ? '#ff7b72' : '#7ee787' }">
              {{ latestCovertScan.phase_inversion_mid_side_scan?.verdict || '[ALERT] Anti-phase side-channel energy!' }}
            </div>
          </div>
        </div>

        <div class="ev-row outloud-row mono" style="margin-bottom: 8px">
          <div class="ev-top">
            <strong style="color: #7ee787">🔊 Exported Hidden Side Channel (isolated_hidden_side_channel.wav · (L - R)/2)</strong>
          </div>
          <div class="ev-bot">
            <audio :key="isolatedSideUrl" :src="isolatedSideUrl" controls preload="none" class="mini-audio" style="width: 100%"></audio>
          </div>
        </div>

        <div v-if="latestCovertScan.piggybacked_words_detected?.length" class="ev-list">
          <div v-for="(pw, pIdx) in latestCovertScan.piggybacked_words_detected" :key="'pw-' + pIdx" class="ev-row mono">
            <div class="ev-top">
              <strong style="color: #38bdf8">{{ pw.vector }}</strong>
              <span>{{ pw.speaker_gender }}</span>
            </div>
            <div class="ev-bot">
              <span class="ev-desc">"{{ pw.extracted_words }}"</span>
            </div>
          </div>
        </div>
      </div>

      <!-- RIGHT: MALE VS. FEMALE VOICE BIOMETRICS STUDY -->
      <div class="rpb-box">
        <div class="box-hdr">
          <div class="box-title mono">♀️/♂️ Male vs. Female Acoustic Voice Biometrics Study (VTL cm + F0 Percentiles)</div>
          <span class="sky-badge mono">11,090 Corpus Utterances</span>
        </div>
        <div class="explain-note" style="margin-bottom: 8px">
          {{ voiceGenderStudy.summary || 'Biometric F0 percentile + Whisper-Invariant VTL (cm) study across room speakers.' }}
        </div>
        <div class="ev-list">
          <div v-for="vp in voiceGenderProfiles" :key="vp.speaker_id" class="ev-row mono">
            <div class="ev-top">
              <strong style="color: #58a6ff; cursor: pointer" @click="$emit('select-speaker', vp.speaker_id)">
                🎧 {{ vp.speaker_id }} · {{ vp.gender_badge }}
              </strong>
              <span style="color: #7ee787">Conf {{ vp.confidence_pct }}%</span>
            </div>
            <div style="font-size: 11px; color: #c9d1d9; margin: 3px 0">
              F0 (p10/p50/p90): <b>{{ (vp.f0_voiced_p10_p25_p50_p75_p90_hz || []).join(' / ') }} Hz</b> ·
              VTL (p10/p50/p90): <b>{{ (vp.vtl_p10_p50_p90_cm || []).join(' / ') }} cm</b> ·
              Bands: <b>&lt;165Hz {{ vp.male_chest_band_lt165_pct }}% | 165-255Hz {{ vp.female_modal_band_165_255_pct }}% | &gt;255Hz {{ vp.high_expressive_gt255_pct }}%</b>
            </div>
            <div style="font-size: 11px; color: #8b949e">
              {{ vp.acoustic_mechanism }}
            </div>
          </div>
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
const covertBusy = ref(false)
const banner = ref('')
const localAdvisor = ref(null)
const localCovertScan = ref(null)
const isolatedSideUrl = ref('/api/reading-piggyback/isolated-side.wav')
const customReadingText = ref('')

const pb = computed(() => props.data?.piggyback || {})
const reading = computed(() => pb.value?.silent_reading || {})
const threeVad = computed(() => pb.value?.three_state_vad || {})
const outLoudEvents = computed(() => threeVad.value?.recent_out_loud_events || [])
const advisor = computed(() => localAdvisor.value || props.data?.last_ollama_advisor || null)
const latestCovertScan = computed(() => localCovertScan.value || pb.value?.covert_piggyback_scan?.latest_scan || {})
const voiceGenderStudy = computed(() => pb.value?.voice_gender_study || {})
const voiceGenderProfiles = computed(() => voiceGenderStudy.value?.profiles || [])

const localCfg = reactive({
  hear_reading_out_loud: true,
  auto_play_out_loud: true,
  udp_out_loud_mirror: false,
  out_loud_voice_gain: 0.8,
  out_loud_drone_mix: 0.36,
  mouth_still_ceiling: 0.015,
  typing_still_ceiling: 0.020,
  coherence_thresh: 0.28,
  max_drr_db: 0.8,
  sublevel_boost_db: 18.0,
  boundary_azimuth_deg: 54,
})

watch(
  () => [pb.value?.config, reading.value?.config, threeVad.value?.config],
  ([pCfg, rCfg, tCfg]) => {
    if (pCfg) {
      if (pCfg.coherence_thresh !== undefined) localCfg.coherence_thresh = Number(pCfg.coherence_thresh)
      if (pCfg.max_drr_db !== undefined) localCfg.max_drr_db = Number(pCfg.max_drr_db)
      if (pCfg.sublevel_boost_db !== undefined) localCfg.sublevel_boost_db = Number(pCfg.sublevel_boost_db)
      if (pCfg.boundary_azimuth_deg !== undefined) localCfg.boundary_azimuth_deg = Number(pCfg.boundary_azimuth_deg)
    }
    if (rCfg) {
      if (rCfg.mouth_still_ceiling !== undefined) localCfg.mouth_still_ceiling = Number(rCfg.mouth_still_ceiling)
      if (rCfg.typing_still_ceiling !== undefined) localCfg.typing_still_ceiling = Number(rCfg.typing_still_ceiling)
    }
    if (tCfg) {
      if (tCfg.hear_reading_out_loud !== undefined) localCfg.hear_reading_out_loud = Boolean(tCfg.hear_reading_out_loud)
      if (tCfg.auto_play_out_loud !== undefined) localCfg.auto_play_out_loud = Boolean(tCfg.auto_play_out_loud)
      if (tCfg.udp_out_loud_mirror !== undefined) localCfg.udp_out_loud_mirror = Boolean(tCfg.udp_out_loud_mirror)
      if (tCfg.out_loud_voice_gain !== undefined) localCfg.out_loud_voice_gain = Number(tCfg.out_loud_voice_gain)
      if (tCfg.out_loud_drone_mix !== undefined) localCfg.out_loud_drone_mix = Number(tCfg.out_loud_drone_mix)
    }
  },
  { immediate: true, deep: true }
)

function flash(msg) {
  banner.value = msg
  setTimeout(() => {
    if (banner.value === msg) banner.value = ''
  }, 5500)
}

async function pushConfig(patch) {
  try {
    const res = await fetch('/api/reading-piggyback/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
    if (res.ok) {
      const j = await res.json()
      flash('Applied live: ' + (j.applied || []).join(', '))
      emit('updated')
    }
  } catch (e) {
    console.error(e)
  }
}

async function simulate(mode) {
  simBusy.value = true
  try {
    const res = await fetch('/api/reading-piggyback/simulate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode, text: customReadingText.value }),
    })
    if (res.ok) {
      const j = await res.json()
      if (mode === 'READING_OUT_LOUD') {
        const audioUrl = j.result?.audio_url
        flash(`ThreeStateVADRouter -> READING (~${j.result?.estimated_wpm || 202} WPM): Rendered Out-Loud Voice + A2-E3-A3 Drone!`)
        if (localCfg.auto_play_out_loud && audioUrl) {
          try {
            const aud = new Audio(audioUrl)
            aud.volume = 0.8
            aud.play().catch(() => {})
          } catch (_) {}
        }
        if (localCfg.auto_play_out_loud && audioUrl) {
          try {
            const aud = new Audio(audioUrl)
            aud.volume = 0.8
            aud.play().catch(() => {})
          } catch (_) {}
        }
      } else if (mode === 'SILENT_READING') {
        flash('SilentReadingDetector locked: 4.5 Hz isometric laryngeal cadence (~202 WPM), closed mouth!')
      } else {
        flash('Captured non-occupant OTHER_ROOM_SUBLEVEL piggybacked on 19.2 kHz mid-air carrier!')
      }
      emit('updated')
    }
  } catch (e) {
    console.error(e)
  } finally {
    simBusy.value = false
  }
}

async function askOllama() {
  ollamaBusy.value = true
  try {
    const res = await fetch('/api/ollama/reading-piggyback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force: true }),
    })
    if (res.ok) {
      localAdvisor.value = await res.json()
      flash('NightSweep Ollama updated 3-State Reading Out-Loud, Closest Faint Focus & Mid-Air Piggyback advice.')
    }
  } catch (e) {
    console.error(e)
  } finally {
    ollamaBusy.value = false
  }
}

async function runCovertScan(mode = 'COMPOSITE_PIGGYBACK') {
  covertBusy.value = true
  try {
    const res = await fetch('/api/reading-piggyback/covert-scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    })
    if (res.ok) {
      const j = await res.json()
      localCovertScan.value = j.result || null
      isolatedSideUrl.value = `/api/reading-piggyback/isolated-side.wav?t=${Date.now()}`
      flash(`Executed 3-Stage Covert Piggyback Scan (${mode}) & exported isolated_hidden_side_channel.wav!`)
      emit('updated')
    }
  } catch (e) {
    console.error(e)
  } finally {
    covertBusy.value = false
  }
}

async function applyRecommended() {
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
.rpb-card {
  border: 1px solid #1f334a;
  background: linear-gradient(180deg, #0b1420 0%, #090e17 100%);
}
.green-pill {
  color: #3fb950;
  border-color: rgba(63, 185, 80, 0.45);
  background: rgba(63, 185, 80, 0.1);
}
.amber-pill {
  color: #fbbf24;
  border-color: rgba(251, 191, 36, 0.45);
  background: rgba(251, 191, 36, 0.12);
}
.muted-pill {
  color: #8b949e;
}
.click-pill {
  cursor: pointer;
}
.sky-pill {
  color: #38bdf8;
  border-color: rgba(56, 189, 248, 0.45);
  background: rgba(56, 189, 248, 0.1);
}
.btn-ollama {
  background: linear-gradient(135deg, #0284c7, #6e40c9);
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
  border: 1px solid rgba(56, 189, 248, 0.35);
  background: rgba(56, 189, 248, 0.06);
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
}
.od-cols {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 14px;
}
.od-col ul {
  margin: 4px 0 0;
  padding-left: 18px;
  font-size: 11.8px;
  color: #b1bac4;
  line-height: 1.45;
}
.status-banner {
  margin-top: 10px;
  padding: 6px 11px;
  border-radius: 6px;
  background: rgba(56, 189, 248, 0.12);
  border: 1px solid rgba(56, 189, 248, 0.4);
  color: #7dd3fc;
  font-size: 12px;
}
.rpb-grid {
  margin-top: 14px;
  display: grid;
  grid-template-columns: 1.04fr 0.96fr;
  gap: 14px;
}
.rpb-box {
  border: 1px solid #1d2c40;
  border-radius: 9px;
  padding: 12px;
  background: #0a1019;
  display: flex;
  flex-direction: column;
  gap: 9px;
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
.veto-badge {
  font-size: 10px;
  padding: 2px 7px;
  border-radius: 99px;
}
.veto-ok {
  background: rgba(63, 185, 80, 0.15);
  color: #7ee787;
}
.veto-busy {
  background: rgba(240, 136, 62, 0.15);
  color: #f0883e;
}
.sky-badge {
  font-size: 10px;
  padding: 2px 7px;
  border-radius: 99px;
  background: rgba(56, 189, 248, 0.14);
  color: #7dd3fc;
}
.state-stepper {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  padding: 6px 8px;
  background: #0d1523;
  border: 1px solid #1b2a40;
  border-radius: 7px;
}
.st-node {
  flex: 1;
  padding: 5px 8px;
  border-radius: 6px;
  border: 1px solid #223047;
  background: #090f18;
  display: flex;
  flex-direction: column;
  gap: 1px;
  opacity: 0.65;
}
.st-node.active {
  opacity: 1;
  border-color: #58a6ff;
  background: rgba(56, 139, 253, 0.12);
}
.st-node.reading-node.active {
  border-color: #fbbf24;
  background: rgba(251, 191, 36, 0.14);
}
.st-node.active-node.active {
  border-color: #3fb950;
  background: rgba(63, 185, 80, 0.14);
}
.st-name {
  font-size: 10.5px;
  font-weight: 700;
  color: #e6edf3;
}
.st-meta {
  font-size: 9.5px;
  color: #8b949e;
}
.st-arrow {
  color: #484f58;
  font-size: 12px;
}
.reading-hero {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(251, 191, 36, 0.06);
  border: 1px solid rgba(251, 191, 36, 0.32);
  flex-wrap: wrap;
}
.rh-lbl {
  font-size: 9.8px;
  color: #fbbf24;
}
.rh-val {
  margin-top: 3px;
  font-size: 14.5px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.rh-wpm {
  font-size: 11.8px;
  color: #79c0ff;
}
.rh-sub {
  margin-top: 3px;
  font-size: 10.8px;
  color: #8b949e;
}
.rh-btns {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.btn-outloud {
  background: linear-gradient(135deg, #d97706, #b45309);
  color: #fff;
  border: none;
  padding: 6px 11px;
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 700;
  cursor: pointer;
}
.btn-read {
  background: #238636;
  color: #fff;
  border: none;
  padding: 6px 9px;
  border-radius: 6px;
  font-size: 11px;
  cursor: pointer;
}
.outloud-toggles {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.chk-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 10.8px;
  color: #c9d1d9;
  background: #0e1624;
  border: 1px solid #1e2e46;
  padding: 4px 8px;
  border-radius: 6px;
  cursor: pointer;
}
.passage-bar {
  display: flex;
}
.passage-input {
  width: 100%;
  background: #0d1421;
  border: 1px solid #1f3048;
  border-radius: 6px;
  padding: 6px 9px;
  color: #e6edf3;
  font-size: 11.5px;
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
.explain-note {
  padding: 9px 11px;
  border-radius: 6px;
  background: rgba(56, 189, 248, 0.06);
  border: 1px dashed rgba(56, 189, 248, 0.3);
  font-size: 11.3px;
  color: #b1bac4;
  line-height: 1.45;
}
.other-card {
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(56, 189, 248, 0.07);
  border: 1px solid rgba(56, 189, 248, 0.38);
  cursor: pointer;
}
.oc-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.oc-id {
  font-size: 13px;
  font-weight: 700;
  color: #38bdf8;
  display: flex;
  align-items: center;
  gap: 8px;
}
.open-chip {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 99px;
  border: 1px solid rgba(56, 189, 248, 0.45);
}
.btn-piggy {
  background: rgba(56, 189, 248, 0.2);
  color: #7dd3fc;
  border: 1px solid rgba(56, 189, 248, 0.5);
  padding: 5px 10px;
  border-radius: 6px;
  font-size: 11px;
  cursor: pointer;
}
.oc-desc {
  margin-top: 4px;
  font-size: 11.5px;
  color: #9ca3af;
}
.oc-metrics {
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 11px;
  color: #c9d1d9;
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
  max-height: 185px;
  overflow-y: auto;
}
.ev-row {
  padding: 7px 9px;
  border-radius: 6px;
  background: #0f1826;
  border: 1px solid #1d2c42;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.outloud-row {
  border-color: rgba(251, 191, 36, 0.35);
  background: rgba(251, 191, 36, 0.05);
}
.ev-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-size: 10.5px;
  color: #9ca3af;
}
.ev-ts {
  color: #6e7681;
}
.ev-bot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: #d0d7de;
}
.ev-desc {
  flex: 1;
}
.mini-audio {
  height: 26px;
  width: 195px;
}
.empty-note {
  padding: 10px;
  border-radius: 6px;
  background: #0d1420;
  color: #8b949e;
  font-size: 11.2px;
  text-align: center;
}
@media (max-width: 1150px) {
  .rpb-grid,
  .od-cols {
    grid-template-columns: 1fr;
  }
}
</style>
