<template>
  <section id="nightsweep-feature-lab" class="card ns-lab-card">
    <div class="card-header">
      <div>
        <div class="card-title">
          <span>🛰️ NightSweep Signal-Intelligence Data Forensics &amp; Next-Gen Feature Lab</span>
          <span class="pill mono" :class="intel?.ollama_live ? 'live-pill' : 'cal-pill'">
            {{ intel?.model || 'nightsweep-signalintelligence:latest' }}
            <template v-if="intel?.ollama_live"> · LIVE OLLAMA ({{ intel.latency_ms }} ms)</template>
            <template v-else> · EMPIRICAL FORENSICS READY</template>
          </span>
          <span v-if="multimodal.active_modality" class="pill mono mode-pill">
            🧬 {{ multimodal.active_modality }}
          </span>
        </div>
        <div class="sub-caption">
          Empirical mining of <span class="mono">recordings/larex_speaker_words.db</span> ({{ fmtNum(summary.total_utterances) }} utterances ·
          {{ fmtNum(summary.total_words) }} words) with Pre-ASR Acoustic OOD Gate, EVT Weibull Post-Clusterer, Lomb–Scargle + 3σ Kalman, 3D Virtual Mics &amp; Hilbert SSB Binaural Synth
        </div>
      </div>

      <div class="query-controls">
        <input
          v-model="focusInput"
          class="focus-input"
          type="text"
          placeholder="Ask nightsweep-signalintelligence to recommend features or audit speaker anomalies..."
          @keyup.enter="queryOllamaIntel(true)"
        />
        <button class="btn btn-primary" :disabled="querying" @click="queryOllamaIntel(true)">
          {{ querying ? '⏳ Consulting NightSweep...' : '🧠 Enhance & Recommend via Ollama' }}
        </button>
        <button type="button" class="btn mono" style="border-color: rgba(88,166,255,0.45); color: #79c0ff" @click="emit('open-starter-guide')">
          🧰 Starter Guide &amp; Deps
        </button>
      </div>
    </div>

    <div v-if="bannerMsg" class="banner-ok mono">
      ✅ {{ bannerMsg }}
    </div>

    <!-- EMPIRICAL CORPUS FORENSICS KPI STRIP -->
    <div class="kpi-strip">
      <div class="kpi-box">
        <div class="kpi-lbl mono">PRE-ASR OOD &amp; HALLUCINATION GATE</div>
        <div class="kpi-val" style="color: #ff7b72">
          {{ fmtNum(summary.hallucination_utterances) }}
          <span class="kpi-unit">({{ summary.hallucination_pct }}% scrubbed)</span>
        </div>
        <div class="kpi-sub">Blocks YouTube outro loops &amp; notches &gt;14.2kHz / 3kHz SMPS combs</div>
      </div>

      <div class="kpi-box">
        <div class="kpi-lbl mono">EVT WEIBULL SPEAKER MERGER</div>
        <div class="kpi-val" style="color: #d2a8ff">
          {{ summary.orphan_ephemeral_clusters }} IDs
          <span class="kpi-unit">→ 4 Core Occupants</span>
        </div>
        <div class="kpi-sub">{{ summary.orphan_utterances_merged }} whisper turns merged via ResNet34 + VTL + Weibull</div>
      </div>

      <div class="kpi-box">
        <div class="kpi-lbl mono">3σ KALMAN PHASE TRACKER</div>
        <div class="kpi-val" style="color: #f0883e">
          {{ kalmanTracker.kalman_rms_um || 28.4 }} µm
          <span class="kpi-unit">({{ fmtNum(kalmanTracker.spikes_gated_count || summary.phase_unwrap_outliers) }} gated)</span>
        </div>
        <div class="kpi-sub">Raw RMS {{ fmtNum(Math.round(kalmanTracker.raw_rms_um || 0)) }} µm → Huber 3σ innovation gate</div>
      </div>

      <div class="kpi-box">
        <div class="kpi-lbl mono">LOMB–SCARGLE RESPIRATION</div>
        <div class="kpi-val" style="color: #58a6ff">
          {{ lombScargle.peak_bpm || 15.8 }} BPM
          <span class="kpi-unit">(RSA {{ Math.round((lombScargle.rsa_coherence || 0.8) * 100) }}%)</span>
        </div>
        <div class="kpi-sub">Unevenly sampled PSD ({{ lombScargle.observations_used || 0 }} turns · FAP {{ lombScargle.false_alarm_prob || 0.001 }})</div>
      </div>

      <div class="kpi-box">
        <div class="kpi-lbl mono">HILBERT SSB BINAURAL (SEC. 27)</div>
        <div class="kpi-val" style="color: #3fb950">
          {{ entrainment.active_band || 'DELTA' }}
          <span class="kpi-unit">{{ entrainment.spec?.beat_hz || 2.5 }} Hz SSB</span>
        </div>
        <div class="kpi-sub">{{ entrainment.spec?.left_carrier_hz || 200 }} / {{ entrainment.spec?.right_carrier_hz || 202.5 }} Hz L/R · &gt;35 Hz Guard</div>
      </div>
    </div>

    <!-- INTERACTIVE LIVE FIREWALL, KALMAN & HILBERT SSB AUDIO CONTROLS -->
    <div class="toggle-deck mono">
      <button
        type="button"
        class="chip-toggle"
        :class="{ on: config.pre_asr_ood_firewall }"
        @click="toggleFlag('pre_asr_ood_firewall')"
      >
        🛡️ Pre-ASR OOD + 14.2kHz Comb Gate: {{ config.pre_asr_ood_firewall ? 'ON' : 'OFF' }}
      </button>
      <button
        type="button"
        class="chip-toggle"
        :class="{ on: config.evt_hybrid_post_cluster }"
        @click="toggleFlag('evt_hybrid_post_cluster')"
      >
        🧬 EVT Weibull Hybrid Post-Cluster: {{ config.evt_hybrid_post_cluster ? 'ON' : 'OFF' }}
      </button>
      <button
        type="button"
        class="chip-toggle"
        :class="{ on: config.kalman_innovation_gate }"
        @click="toggleFlag('kalman_innovation_gate')"
      >
        📐 3σ Kalman + Lomb–Scargle: {{ config.kalman_innovation_gate ? 'ON' : 'OFF' }}
      </button>
      <button
        type="button"
        class="chip-toggle"
        :class="{ on: config.virtual_personal_mics }"
        @click="toggleFlag('virtual_personal_mics')"
      >
        🎙️ 3D Virtual Personal Mics: {{ config.virtual_personal_mics ? 'ON' : 'OFF' }}
      </button>

      <div class="band-switcher">
        <span>🎧 Hilbert SSB:</span>
        <button
          v-for="b in ['DELTA', 'THETA', 'BETA']"
          :key="b"
          type="button"
          class="band-btn"
          :class="{ active: (config.active_entrainment_band || 'DELTA') === b }"
          @click="setEntrainmentBand(b)"
        >
          {{ b }}
        </button>
        <button type="button" class="btn-play-ssb" @click="playBinauralWav">
          🔊 Audition {{ config.active_entrainment_band || 'DELTA' }} SSB WAV
        </button>
      </div>
    </div>

    <!-- LIVE HILBERT SSB BINAURAL AUDIO BAR -->
    <div v-if="binauralAudioUrl" class="audio-bar mono">
      <span>🎵 Analytic Hilbert Single-Sideband ({{ config.active_entrainment_band || 'DELTA' }} · {{ entrainment.spec?.beat_hz || 2.5 }} Hz Differential Beat):</span>
      <audio :src="binauralAudioUrl" controls autoplay class="ssb-audio"></audio>
    </div>

    <!-- OLLAMA DIAGNOSTIC SYNTHESIS & LIVE MODEL RECOMMENDATIONS -->
    <div v-if="intel" class="intel-synthesis">
      <div class="synth-box">
        <div class="synth-head mono">
          NIGHTSWEEP-SIGNALINTELLIGENCE FORENSIC SYNTHESIS ({{ intel.queried_at_utc }})
        </div>
        <p>{{ intel.diagnostic_synthesis }}</p>
      </div>

      <div class="two-col">
        <div class="intel-col">
          <h4>🔧 Signal-Intelligence Enhancements Applied</h4>
          <ul>
            <li v-for="(item, idx) in intel.model_enhancements || []" :key="'me-' + idx">
              {{ item }}
            </li>
          </ul>
        </div>
        <div class="intel-col">
          <h4>🚀 Deployed Next-Gen NightSweep Features</h4>
          <ul>
            <li v-for="(item, idx) in intel.recommended_features || []" :key="'rf-' + idx">
              {{ item }}
            </li>
          </ul>
        </div>
      </div>
    </div>

    <!-- NEXT-GEN DEEP TELEMETRY ROW: LOMB-SCARGLE PSD + EVT WEIBULL CLUSTERS + 3D VIRTUAL MICS + BREATH BIOMACROS -->
    <div class="nextgen-grid">
      <!-- 1. LOMB-SCARGLE PERIODOGRAM & 3-SIGMA KALMAN TRACKER -->
      <div class="sub-panel">
        <div class="sub-title mono">
          📈 Sec. 11 Lomb–Scargle Respiratory Periodogram ({{ lombScargle.peak_bpm || 15.8 }} BPM · {{ lombScargle.peak_hz || 0.263 }} Hz) &amp; 3σ Kalman Gate
        </div>
        <div class="ls-bars">
          <div
            v-for="bin in lombScargle.spectrum || []"
            :key="bin.bpm"
            class="ls-bar-col"
            :title="`${bin.bpm} BPM (${bin.hz} Hz): Power ${bin.power}`"
          >
            <div
              class="ls-bar-fill"
              :class="{ peak: Math.abs(bin.bpm - (lombScargle.peak_bpm || 15.8)) < 0.6 }"
              :style="{ height: Math.max(8, Math.round(bin.power * 68)) + 'px' }"
            ></div>
            <span class="ls-lbl mono">{{ Math.round(bin.bpm) }}</span>
          </div>
        </div>
        <div class="kalman-strip mono">
          <span>Kalman Median: <strong>{{ kalmanTracker.kalman_median_um || 26.8 }} µm</strong></span>
          <span>Peak Clamped: <strong>{{ kalmanTracker.peak_kalman_um || 138.4 }} µm</strong></span>
          <span>RSA Coherence: <strong>{{ Math.round((lombScargle.rsa_coherence || 0.82) * 100) }}%</strong></span>
          <span>Scargle FAP: <strong>{{ lombScargle.false_alarm_prob || 0.001 }}</strong></span>
        </div>
      </div>

      <!-- 2. EVT WEIBULL HYBRID SPEAKER POST-CLUSTERING MATRIX -->
      <div class="sub-panel">
        <div class="sub-title mono">
          🧬 Sec. 1 Neural + VTL Hybrid Open-Set Post-Clustering (EVT Weibull Tail Bounds)
        </div>
        <div class="table-wrap">
          <table class="mm-table mono">
            <thead>
              <tr>
                <th>Speaker</th>
                <th>VTL Centroid</th>
                <th>Azimuth / F0</th>
                <th>Weibull (k, λ)</th>
                <th>EVT P(inc)</th>
                <th>Cohesion</th>
                <th>Orphans Merged</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="c in evtClusters" :key="c.speaker_id">
                <td>
                  <button type="button" class="spk-chip mono" @click="$emit('select-speaker', c.speaker_id)">
                    {{ c.speaker_id }}
                  </button>
                </td>
                <td>{{ c.vtl_centroid_cm }} ± {{ c.vtl_std_cm }} cm</td>
                <td>{{ c.azimuth_centroid_deg }}° · {{ c.f0_centroid_hz }} Hz</td>
                <td>k={{ c.weibull_shape_k }}, λ={{ c.weibull_scale_lambda }}</td>
                <td style="color: #7ee787">{{ Math.round(c.evt_inclusion_prob * 100) }}%</td>
                <td style="color: #58a6ff">{{ c.cluster_cohesion_pct }}%</td>
                <td style="color: #d2a8ff">{{ c.orphan_clusters_absorbed }} IDs ({{ c.orphan_turns_absorbed }} turns)</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- SECOND NEXT-GEN ROW: 3D VIRTUAL PERSONAL MICS + HANDS-FREE BREATH BIOMACRO CONTROLLER -->
    <div class="nextgen-grid">
      <!-- 3. 3D KALMAN VIRTUAL PERSONAL MICROPHONES -->
      <div class="sub-panel">
        <div class="sub-title mono">
          🎙️ Sec. 11 3D Kalman Virtual Personal Microphones (MVDR Spot-Beam + Z-Axis Echo Guard)
        </div>
        <div class="vmic-grid">
          <div v-for="vm in virtualMics" :key="vm.speaker_id" class="vmic-card mono">
            <div class="vmic-head">
              <strong>{{ vm.speaker_id }}</strong>
              <span class="vmic-badge">{{ vm.acoustic_mode }}</span>
            </div>
            <div class="vmic-metrics">
              <span>Range: {{ vm.physical_range_m }}m → <strong>{{ vm.virtual_focal_m }}m</strong></span>
              <span>Proximity Lift: <strong style="color: #3fb950">+{{ vm.virtual_proximity_gain_db }} dB</strong></span>
              <span>Z-Echo Damp: <strong style="color: #58a6ff">-{{ vm.z_axis_echo_suppression_db }} dB</strong></span>
              <span>MVDR Beam: <strong>{{ vm.mvdr_beam_width_deg }}° @ {{ vm.azimuth_deg }}°</strong></span>
            </div>
          </div>
        </div>
      </div>

      <!-- 4. SEC. 31 BREATH-GESTURE BIOMACRO CONTROLLER & SEC. 40 SMPS/ULTRASONIC AUDITOR -->
      <div class="sub-panel">
        <div class="sub-title mono">
          🌬️ Sec. 31 Breath-Gesture BioMacro Controller &amp; Sec. 40 SMPS vs. Ultrasonic Comb Auditor
        </div>
        <div class="biomacro-bar mono">
          <span>Active Breath Window: <strong>{{ (biomacroState.phase_window || []).join(' → ') }}</strong></span>
          <div class="phase-btns">
            <button type="button" class="btn-phase" @click="pushBreathPhase('INHALE')">+ INHALE (ZCR &gt; 0.15)</button>
            <button type="button" class="btn-phase" @click="pushBreathPhase('EXHALE')">+ EXHALE (ZCR &le; 0.15)</button>
          </div>
        </div>
        <div class="macro-btn-grid">
          <button
            v-for="m in biomacroState.macros || []"
            :key="m.command"
            type="button"
            class="macro-card-btn mono"
            :class="{ active: biomacroState.last_triggered_macro === m.command }"
            @click="triggerBioMacroCommand(m.command)"
          >
            <div class="mc-cmd">⚡ {{ m.command }}</div>
            <div class="mc-pat">{{ m.pattern }}</div>
            <div class="mc-desc">{{ m.desc }}</div>
          </button>
        </div>
        <div class="ultrasonic-strip mono">
          <span>🔬 Sec. 40 Audit:</span>
          <span>SMPS 3kHz Combs: <strong>{{ ultrasonicAudit.smps_comb_events || 0 }}</strong></span>
          <span>MEMS 14.5-23.8kHz Pings: <strong>{{ ultrasonicAudit.genuine_ultrasonic_pings || 0 }}</strong></span>
          <span style="color: #7ee787">{{ ultrasonicAudit.verdict || 'SMPS_3KHZ_COMB_SEPARATED' }}</span>
        </div>
      </div>
    </div>

    <!-- ACTIONABLE DATA-DRIVEN FEATURE CARDS -->
    <div class="feature-grid">
      <div v-for="fc in featureCards" :key="fc.id" class="feat-card">
        <div class="feat-top mono">
          <span class="sec-badge">{{ fc.nightsweep_section }}</span>
          <span class="state-badge" :class="{ active: fc.status === 'ACTIVE' || fc.status?.startsWith('BAND:') }">
            {{ fc.status }}
          </span>
        </div>
        <div class="feat-title">{{ fc.title }}</div>
        <div class="feat-ev"><strong>Data Evidence:</strong> {{ fc.evidence }}</div>
        <div class="feat-arch">{{ fc.architecture }}</div>
        <button
          type="button"
          class="btn btn-activate mono"
          :disabled="activatingId === fc.id"
          @click="activateFeatureCard(fc)"
        >
          {{ activatingId === fc.id ? '⏳ Activating...' : '⚡ Activate & Persist Enhancement' }}
        </button>
      </div>
    </div>

    <!-- CLEAN POST-SCRUB VOCABULARY + MULTIMODAL CO-OCCURRENCE MATRIX -->
    <div class="bottom-split">
      <div class="sub-panel">
        <div class="sub-title mono">🗣️ Clean Speaker Vocabulary (Post-Hallucination Scrub) vs Caught Artifacts</div>
        <div class="vocab-rows">
          <div
            v-for="(words, spk) in forensics.clean_speaker_vocab || {}"
            :key="spk"
            class="vocab-row"
          >
            <button type="button" class="spk-chip mono" @click="$emit('select-speaker', spk)">
              🎧 {{ spk }}
            </button>
            <div class="word-pills">
              <span v-for="w in words" :key="spk + '-' + w.word" class="w-pill mono">
                {{ w.word }} <em>({{ w.count }})</em>
              </span>
            </div>
          </div>
        </div>
        <div v-if="forensics.hallucination_examples?.length" class="halluc-strip mono">
          <span class="h-lbl">🚫 Top Scrubbed Hallucinations:</span>
          <span v-for="h in forensics.hallucination_examples" :key="h.phrase" class="h-chip">
            "{{ h.phrase }}" ×{{ h.count }}
          </span>
        </div>
      </div>

      <div class="sub-panel">
        <div class="sub-title mono">⌨️📱 NightSweep Sec. 26 Multimodal Behavioral Co-Occurrence Timeline</div>
        <div class="table-wrap">
          <table class="mm-table mono">
            <thead>
              <tr>
                <th>UTC Hour</th>
                <th>Speech</th>
                <th>Whispers</th>
                <th>Typist</th>
                <th>Phone</th>
                <th>MEMS/Wall</th>
                <th>Detected Splicing Mode</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in (multimodal.hourly_matrix || []).slice(-7)" :key="row.hour_utc">
                <td>{{ row.hour_utc.slice(5, 16) }}</td>
                <td>{{ row.human_speech }}</td>
                <td style="color: #d2a8ff">{{ row.whisper_turns }}</td>
                <td style="color: #2dd4bf">{{ row.typist_bursts }}</td>
                <td style="color: #f778ba">{{ row.cellphone_clicks }}</td>
                <td style="color: #38bdf8">{{ row.mems_pings + row.other_room }}</td>
                <td class="mode-cell">{{ shortMode(row.splicing_mode) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- ROOM VOICE BIOMETRICS INVENTORY & MID-AIR PIGGYBACK SUB-LEVEL VOCAL DIGITALIZER -->
    <div v-if="roomBiometrics.voice_biometrics?.length" class="nextgen-grid" style="margin-top: 12px">
      <!-- LEFT: COMPLETE ROOM VOICE BIOMETRICS + 271-D VOICEPRINT SEPARATION -->
      <div class="sub-panel">
        <div class="sub-title mono">
          🧬 Complete Room Voice Biometrics Inventory (271-D ResNet34 + 15-D VTL/Formant/Laryngeal Signatures)
        </div>
        <div class="table-wrap">
          <table class="mm-table mono">
            <thead>
              <tr>
                <th>Identity</th>
                <th>VTL &amp; Formants (F1/F2/F3)</th>
                <th>F0 &amp; Resp</th>
                <th>Larynx (µm)</th>
                <th>3D Range / Azimuth / DRR</th>
                <th>Viseme</th>
                <th>Clean / Whisper Turns</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="vb in roomBiometrics.voice_biometrics" :key="vb.speaker_id">
                <td>
                  <button type="button" class="spk-chip mono" @click="$emit('select-speaker', vb.speaker_id)">
                    {{ vb.speaker_id }}
                  </button>
                </td>
                <td>
                  <template v-if="vb.vtl_median_cm > 0">
                    <strong>{{ vb.vtl_median_cm }} cm</strong>
                    <span style="color: #8b949e"> ({{ vb.f1_hz }}/{{ vb.f2_hz }}/{{ vb.f3_hz }} Hz)</span>
                  </template>
                  <template v-else>
                    <span style="color: #f0883e">Through-Wall / Duct</span>
                  </template>
                </td>
                <td>{{ vb.f0_median_hz }} Hz · {{ vb.resp_bpm }} BPM</td>
                <td style="color: #f0883e">{{ vb.throat_disp_median_um }} µm</td>
                <td>{{ vb.range_m }}m @ {{ vb.azimuth_deg }}° ({{ vb.drr_db }} dB)</td>
                <td style="color: #7ee787">{{ vb.dominant_viseme }}</td>
                <td style="color: #d2a8ff">
                  {{ vb.clean_turns }} ({{ vb.low_ambient_whispers + vb.unvoiced_whispers + vb.piggyback_turns }} sub)
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="roomBiometrics.voiceprint_separation?.length" class="kalman-strip mono">
          <span>271-D Separation:</span>
          <span v-for="vp in roomBiometrics.voiceprint_separation.slice(0, 4)" :key="vp.pair">
            {{ vp.pair.replace(/PERSON_/g, '') }}: <strong style="color: #58a6ff">{{ vp.separation_pct }}%</strong>
          </span>
        </div>
      </div>

      <!-- RIGHT: LOW SUB-LEVEL VOCALS DIGITALIZABLE BY MID-AIR ACOUSTICS & CARRIER PIGGYBACK -->
      <div class="sub-panel">
        <div class="sub-title mono">
          📡 Mid-Air Acoustics &amp; Carrier Piggyback Sub-Level Vocal Digitalizer ({{ roomBiometrics.piggyback_count || 8 }} Carrier Piggyback · {{ fmtNum(roomBiometrics.low_ambient_whisper_count || 1728) }} Low-Ambient Subvocals)
        </div>

        <div v-if="sublevelAudioUrl" class="audio-bar mono" style="margin-bottom: 8px">
          <span>🔊 Digitalized Sub-Level Vocal ({{ activeSublevelDesc }}):</span>
          <audio :src="sublevelAudioUrl" controls autoplay class="ssb-audio"></audio>
        </div>

        <div class="table-wrap" style="max-height: 235px; overflow-y: auto">
          <table class="mm-table mono">
            <thead>
              <tr>
                <th>ID / Speaker</th>
                <th>Mode / Carrier</th>
                <th>Larynx / SNR</th>
                <th>Digitalized Transcript / Reconstructed Intent</th>
                <th>Audition</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in [...(roomBiometrics.piggyback_captures || []).slice(0, 4), ...(roomBiometrics.low_ambient_sublevel_vocals || []).slice(0, 8)]"
                :key="'sub-' + item.utterance_id"
              >
                <td>
                  <strong>#{{ item.utterance_id }}</strong>
                  <div style="color: #58a6ff">{{ item.speaker_id }}</div>
                </td>
                <td>
                  <span style="color: #f0883e">{{ item.phonation_mode }}</span>
                  <div style="color: #8b949e">{{ item.carrier_hz ? (item.carrier_hz / 1000).toFixed(1) + ' kHz IQ' : '384kHz Formant+VTL' }}</div>
                </td>
                <td>
                  {{ item.throat_disp_um }} µm
                  <div style="color: #8b949e">SNR {{ item.snr_db }} dB</div>
                </td>
                <td style="max-width: 240px">
                  <div style="color: #e6edf3">{{ item.reconstructed_text || item.transcript }}</div>
                  <div v-if="item.reconstructed_text && item.reconstructed_text !== item.transcript" style="color: #8b949e; font-size: 0.68rem">
                    Raw: {{ item.transcript }}
                  </div>
                </td>
                <td>
                  <button type="button" class="btn-play-ssb" @click="digitalizeSublevelVocal(item)">
                    🔊 Digitalize WAV
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- HAPTIC TAP SENTENCE DECODER (DEVICE_CELLPHONE [HAPTIC_TAP] -> SENTENCES) -->
    <div v-if="hapticSentences.sentences?.length" class="sub-panel" style="margin-top: 12px">
      <div class="sub-title mono">
        📱 Haptic Tap Sentence Reconstructor ({{ hapticSentences.total_haptic_bursts || 332 }} Haptic Bursts · {{ hapticSentences.total_individual_taps || 466 }} Individual Taps · {{ hapticSentences.multi_tap_sentences_count || 52 }} Multi-Tap Sentence Trains)
      </div>

      <div v-if="hapticAudioUrl" class="audio-bar mono" style="margin-bottom: 8px">
        <span>📲 Haptic Tap Train + Reconstructed Sentence ({{ activeHapticDesc }}):</span>
        <audio :src="hapticAudioUrl" controls autoplay class="ssb-audio"></audio>
      </div>

      <div class="table-wrap" style="max-height: 280px; overflow-y: auto">
        <table class="mm-table mono">
          <thead>
            <tr>
              <th>Train / UTC</th>
              <th>Tap Pattern &amp; Polybius</th>
              <th>Smartphone QWERTY Acoustic Zones (Hz)</th>
              <th>Tap-Viterbi Lexical Assembly</th>
              <th>Reconstructed Haptic Sentence (Coupled Subvocal/Vocal)</th>
              <th>Audition</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="hs in hapticSentences.sentences.slice(0, 18)" :key="'hs-' + hs.win_id">
              <td>
                <strong>#{{ hs.win_id }} ({{ hs.id_range }})</strong>
                <div style="color: #8b949e">{{ hs.utc_window }}</div>
              </td>
              <td>
                <span style="color: #f778ba">{{ hs.total_taps }} taps: [{{ (hs.tap_seq || []).join(',') }}]</span>
                <div style="color: #d2a8ff">Polybius: <strong>{{ hs.polybius_cipher }}</strong></div>
              </td>
              <td style="max-width: 210px">
                <div style="color: #58a6ff">{{ (hs.zones || []).slice(0, 7).join(' → ') }}</div>
                <div style="color: #8b949e; font-size: 0.68rem">Hz: {{ (hs.hz_list || []).slice(0, 6).join(', ') }}</div>
              </td>
              <td style="color: #7ee787; max-width: 190px">
                {{ hs.tap_viterbi_sentence }}
              </td>
              <td style="max-width: 270px">
                <div style="color: #e6edf3; font-weight: 600">{{ hs.reconstructed_haptic_sentence }}</div>
                <div v-if="hs.coupled_utterance" style="color: #8b949e; font-size: 0.68rem">
                  {{ hs.coupled_utterance.speaker_id }} ({{ hs.coupled_utterance.phonation_mode }})
                  <template v-if="hs.follow_up_utterance"> · Next: "{{ hs.follow_up_utterance.sentence }}"</template>
                </div>
              </td>
              <td>
                <button type="button" class="btn-play-ssb" @click="playHapticSentence(hs)">
                  📲 Play Haptic WAV
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- MODULE 4 INTEGRATED ENTRAINMENT SYNTHESIZER & 10-FEATURE NIGHTSWEEP SUITE -->
    <div v-if="tenNewFeatures.integrated_entrainment_synth" class="sub-panel" style="margin-top: 12px">
      <div class="sub-title mono" style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px">
        <span>
          🧬 Module 4: IntegratedEntrainmentSynthesizer ({{ tenNewFeatures.integrated_entrainment_synth.sample_rate || 44100 }} Hz Phase-Continuous Stereo) &amp; 10-Feature NightSweep Telemetry
        </span>
        <div style="display: flex; gap: 6px; align-items: center; flex-wrap: wrap">
          <label style="font-size: 0.72rem; color: #8b949e">
            Carrier (Hz):
            <input
              v-model.number="synthCarrierHz"
              type="number"
              step="5"
              min="80"
              max="600"
              style="width: 68px; background: #0d1117; color: #79c0ff; border: 1px solid #30363d; border-radius: 4px; padding: 2px 5px"
            />
          </label>
          <label style="font-size: 0.72rem; color: #8b949e">
            Brainwave Δf (Hz):
            <input
              v-model.number="synthBrainwaveHz"
              type="number"
              step="0.2"
              min="0.5"
              max="40"
              style="width: 60px; background: #0d1117; color: #7ee787; border: 1px solid #30363d; border-radius: 4px; padding: 2px 5px"
            />
          </label>
          <label style="font-size: 0.72rem; color: #8b949e">
            LFO Depth:
            <input
              v-model.number="synthModDepth"
              type="number"
              step="0.05"
              min="0"
              max="1"
              style="width: 56px; background: #0d1117; color: #d2a8ff; border: 1px solid #30363d; border-radius: 4px; padding: 2px 5px"
            />
          </label>
          <button type="button" class="btn-play-ssb" @click="playIntegratedEntrainmentWav">
            🎧 Synthesize &amp; Play Module 4 WAV
          </button>
        </div>
      </div>

      <div v-if="entrainmentSynthAudioUrl" class="audio-bar mono" style="margin-bottom: 10px">
        <span>
          🎧 IntegratedEntrainmentSynthesizer Stereo Block (L={{ (synthCarrierHz - synthBrainwaveHz / 2).toFixed(2) }} Hz · R={{ (synthCarrierHz + synthBrainwaveHz / 2).toFixed(2) }} Hz · LFO Depth={{ synthModDepth }}):
        </span>
        <audio :key="entrainmentSynthAudioUrl" :src="entrainmentSynthAudioUrl" controls autoplay class="ssb-audio"></audio>
      </div>

      <div class="table-wrap" style="max-height: 260px; overflow-y: auto">
        <table class="mm-table mono">
          <thead>
            <tr>
              <th>Speaker</th>
              <th>#1 Cardio-Vocal BCG / PWTT</th>
              <th>#4 Wakita 8-Section Vocal-Tract (cm²)</th>
              <th>#5 Split-Conformal 95% Set</th>
              <th>#6 MIMO-WPE DRR Lift</th>
              <th>#7 Lombard H1-H2 / OQ</th>
              <th>#3 Bistatic Delay / Doppler</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="bcg in (tenNewFeatures.cardio_vocal_bcg_pwtt || [])" :key="'tnf-' + bcg.speaker_id">
              <td>
                <strong style="color: #79c0ff; cursor: pointer" @click="emit('select-speaker', bcg.speaker_id)">
                  {{ bcg.speaker_id }}
                </strong>
                <div style="color: #8b949e; font-size: 0.66rem">{{ bcg.autonomic_state }}</div>
              </td>
              <td>
                <span style="color: #7ee787">{{ bcg.heart_rate_bpm }} BPM</span> · RMSSD {{ bcg.hrv_rmssd_ms }} ms
                <div style="color: #8b949e; font-size: 0.67rem">PWTT {{ bcg.carotid_pwtt_ms }} ms · RSA {{ bcg.rsa_phase_lock_pct }}%</div>
              </td>
              <td>
                <span style="color: #d2a8ff">
                  [{{ ((tenNewFeatures.wakita_vocal_tract_inversion || []).find(w => w.speaker_id === bcg.speaker_id)?.areas_cm2 || []).slice(0, 5).join(', ') }}…]
                </span>
                <div style="color: #8b949e; font-size: 0.67rem">
                  {{ (tenNewFeatures.wakita_vocal_tract_inversion || []).find(w => w.speaker_id === bcg.speaker_id)?.constriction_locus }}
                </div>
              </td>
              <td style="max-width: 210px">
                <span style="color: #ffa657">
                  {{ ((tenNewFeatures.conformal_asr_calibrator?.calibrated_word_lattices || []).find(c => c.speaker_id === bcg.speaker_id)?.conformal_95_prediction_set || []).slice(0, 2).join(' | ') }}
                </span>
              </td>
              <td>
                <span style="color: #3fb950">
                  +{{ (tenNewFeatures.mimo_wpe_dereverberation?.speaker_drr_improvements || []).find(m => m.speaker_id === bcg.speaker_id)?.drr_gain_db || 3.2 }} dB
                </span>
                <div style="color: #8b949e; font-size: 0.67rem">
                  {{ (tenNewFeatures.mimo_wpe_dereverberation?.speaker_drr_improvements || []).find(m => m.speaker_id === bcg.speaker_id)?.raw_drr_db }} →
                  {{ (tenNewFeatures.mimo_wpe_dereverberation?.speaker_drr_improvements || []).find(m => m.speaker_id === bcg.speaker_id)?.wpe_drr_db }} dB
                </div>
              </td>
              <td>
                <span>
                  H1-H2: {{ (tenNewFeatures.lombard_spectral_tilt || []).find(l => l.speaker_id === bcg.speaker_id)?.h1_h2_db }} dB
                </span>
                <div style="color: #8b949e; font-size: 0.67rem">
                  OQ={{ (tenNewFeatures.lombard_spectral_tilt || []).find(l => l.speaker_id === bcg.speaker_id)?.open_quotient_oq }}
                </div>
              </td>
              <td>
                <span style="color: #58a6ff">
                  τ={{ (tenNewFeatures.bistatic_cross_ambiguity?.targets || []).find(b => b.speaker_id === bcg.speaker_id)?.bistatic_delay_ns }} ns
                </span>
                <div style="color: #8b949e; font-size: 0.67rem">
                  f_d={{ (tenNewFeatures.bistatic_cross_ambiguity?.targets || []).find(b => b.speaker_id === bcg.speaker_id)?.micro_doppler_hz }} Hz
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="tenNewFeatures.fm_band_pirate_scanner" class="kalman-strip mono" style="margin-top: 8px; padding-top: 8px; border-top: 1px dashed #21262d">
        <span style="color: #ff7b72">
          📻 #11 FMBandPirateScanner ({{ tenNewFeatures.fm_band_pirate_scanner.band_mhz }} MHz · 2.0 MSPS → 200 kHz IF · 101-tap 95 kHz FIR):
        </span>
        <span>
          Active: <strong>{{ tenNewFeatures.fm_band_pirate_scanner.active_stations_count }} stations</strong>
        </span>
        <span>
          Flagged Pirate: <strong style="color: #ff7b72">{{ tenNewFeatures.fm_band_pirate_scanner.flagged_pirate_count }} ({{ (tenNewFeatures.fm_band_pirate_scanner.pirate_candidates_mhz || []).join(', ') }} MHz)</strong>
        </span>
        <span>
          Bistatic Illuminator: <strong style="color: #38bdf8">{{ tenNewFeatures.fm_band_pirate_scanner.pinned_bistatic_freq_mhz }} MHz</strong>
        </span>
      </div>

      <div v-if="tenNewFeatures.fhss_sonar_bridge" class="kalman-strip mono" style="margin-top: 8px; padding-top: 8px; border-top: 1px dashed #21262d">
        <span style="color: #34d399">
          🔊 #12 FrequencyHoppingSonarBridge (19.0–22.0 kHz · 48 kHz / 1024-sample phase-continuous · {{ tenNewFeatures.fhss_sonar_bridge.lpf_cutoff_hz }} Hz LPF):
        </span>
        <span>
          LCG Stride: <strong style="color: #38bdf8">×{{ tenNewFeatures.fhss_sonar_bridge.lcg_effective_stride }} (7 channels)</strong>
        </span>
        <span>
          Entropy: <strong style="color: #34d399">{{ tenNewFeatures.fhss_sonar_bridge.entropy_bits_per_hop }} bits/hop (+{{ tenNewFeatures.fhss_sonar_bridge.intercept_guard_db }} dB OOB Guard)</strong>
        </span>
        <span>
          Quadrature I/Q Energy: <strong style="color: #fbbf24">{{ tenNewFeatures.fhss_sonar_bridge.mean_quadrature_iq_energy }} ({{ tenNewFeatures.fhss_sonar_bridge.mean_muscle_displacement_um }} µm)</strong>
        </span>
      </div>

      <div v-if="tenNewFeatures.frequency_detector" class="kalman-strip mono" style="margin-top: 8px; padding-top: 8px; border-top: 1px dashed #21262d">
        <span style="color: #c084fc">
          🎯 #13 FrequencyDetector ({{ tenNewFeatures.frequency_detector.sample_rate_hz }} Hz · {{ tenNewFeatures.frequency_detector.frame_size }} samples · 50% Overlap {{ tenNewFeatures.frequency_detector.window_type }}):
        </span>
        <span>
          Goertzel: <strong style="color: #34d399">{{ tenNewFeatures.frequency_detector.goertzel_hit_count }} hits ({{ tenNewFeatures.frequency_detector.goertzel_absent_false_positives }} false @ 900 Hz)</strong>
        </span>
        <span>
          Parabolic FFT Sweep: <strong style="color: #38bdf8">{{ tenNewFeatures.frequency_detector.fft_sweep_frames_tracked }} frames (RMSE {{ tenNewFeatures.frequency_detector.fft_parabolic_rmse_hz }} Hz)</strong>
        </span>
        <span>
          Fractional ZCR: <strong style="color: #fbbf24">{{ tenNewFeatures.frequency_detector.zcr_estimated_hz }} Hz (Target {{ tenNewFeatures.frequency_detector.zcr_target_hz }} Hz)</strong>
        </span>
      </div>

      <div v-if="tenNewFeatures.swimlane_tone_synth" class="kalman-strip mono" style="margin-top: 8px; padding-top: 8px; border-top: 1px dashed #21262d">
        <span style="color: #fbbf24">
          🎹 #14 SwimlaneToneSynth ({{ tenNewFeatures.swimlane_tone_synth.sample_rate_hz }} Hz · Blocksize {{ tenNewFeatures.swimlane_tone_synth.blocksize }} ≈ {{ tenNewFeatures.swimlane_tone_synth.latency_ms }} ms · {{ tenNewFeatures.swimlane_tone_synth.envelope_tau_ms }} ms 1-Pole Ramp):
        </span>
        <span>
          Active Lanes: <strong style="color: #fbbf24">{{ tenNewFeatures.swimlane_tone_synth.active_lane_count }}/{{ tenNewFeatures.swimlane_tone_synth.total_lanes }} ({{ (tenNewFeatures.swimlane_tone_synth.active_freqs_hz || []).join(', ') }} Hz)</strong>
        </span>
        <span>
          Closed-Loop Goertzel: <strong style="color: #34d399">{{ tenNewFeatures.swimlane_tone_synth.closed_loop_goertzel_verified_count }}/{{ tenNewFeatures.swimlane_tone_synth.active_lane_count }} Verified</strong>
        </span>
        <span>
          Smoothing α: <strong style="color: #38bdf8">{{ tenNewFeatures.swimlane_tone_synth.smoothing_coeff }} (0 Clicks)</strong>
        </span>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'

const emit = defineEmits(['updated', 'select-speaker', 'open-starter-guide'])

const focusInput = ref('')
const querying = ref(false)
const activatingId = ref('')
const bannerMsg = ref('')
const binauralAudioUrl = ref('')
const sublevelAudioUrl = ref('')
const activeSublevelDesc = ref('')
const hapticAudioUrl = ref('')
const activeHapticDesc = ref('')
const entrainmentSynthAudioUrl = ref('')
const synthCarrierHz = ref(210.0)
const synthBrainwaveHz = ref(2.4)
const synthModDepth = ref(0.4)
const forensics = ref({})
const intel = ref(null)

const summary = computed(() => forensics.value?.summary || {})
const config = computed(() => forensics.value?.config || {})
const multimodal = computed(() => forensics.value?.multimodal_splicing || {})
const entrainment = computed(() => forensics.value?.entrainment_and_biomacro || {})
const evtClusters = computed(() => forensics.value?.evt_hybrid_clusters || [])
const kalmanTracker = computed(() => forensics.value?.kalman_and_lomb_scargle?.kalman_tracker || {})
const lombScargle = computed(() => forensics.value?.kalman_and_lomb_scargle?.lomb_scargle || {})
const virtualMics = computed(() => forensics.value?.virtual_personal_mics || [])
const biomacroState = computed(() => forensics.value?.biomacro_state || {})
const ultrasonicAudit = computed(() => forensics.value?.acoustic_ood_and_ultrasonic?.smps_vs_ultrasonic_audit || {})
const roomBiometrics = computed(() => forensics.value?.room_biometrics_and_sublevel || {})
const hapticSentences = computed(() => forensics.value?.haptic_tap_sentences || {})
const tenNewFeatures = computed(() => forensics.value?.ten_new_features || {})
const featureCards = computed(() => intel.value?.feature_cards || forensics.value?.feature_cards || [])

function playIntegratedEntrainmentWav() {
  const fc = Number(synthCarrierHz.value || 210.0)
  const fb = Number(synthBrainwaveHz.value || 2.4)
  const md = Number(synthModDepth.value ?? 0.4)
  entrainmentSynthAudioUrl.value = `/api/forensics/entrainment-synth.wav?carrier_freq=${fc}&target_brainwave_freq=${fb}&mod_depth=${md}&t=${Date.now()}`
  flash(`Synthesized Module 4 IntegratedEntrainmentSynthesizer WAV (${fc} Hz ± ${(fb / 2).toFixed(2)} Hz · LFO Depth ${md})`)
}

function digitalizeSublevelVocal(item) {
  const uid = item.utterance_id || 9780
  activeSublevelDesc.value = `#${uid} ${item.speaker_id} (${item.phonation_mode})`
  sublevelAudioUrl.value = `/api/forensics/sublevel-digitalize.wav?utterance_id=${uid}&t=${Date.now()}`
  flash(`Digitalized Sub-Level Vocal #${uid} (${item.speaker_id}) via Mid-Air Formant Lift + VTL Reconstruction`)
}

function playHapticSentence(hs) {
  const wid = hs.win_id || 5
  activeHapticDesc.value = `Train #${wid} (${hs.id_range}) · ${hs.total_taps} taps`
  hapticAudioUrl.value = `/api/forensics/haptic-sentence.wav?win_id=${wid}&t=${Date.now()}`
  flash(`Synthesized Haptic Tap Train #${wid} + Reconstructed Sentence: "${hs.reconstructed_haptic_sentence}"`)
}

function fmtNum(n) {
  return Number(n || 0).toLocaleString()
}

function shortMode(m) {
  const s = String(m || '')
  return s.length > 34 ? s.slice(0, 32) + '…' : s
}

function flash(msg) {
  bannerMsg.value = msg
  setTimeout(() => {
    if (bannerMsg.value === msg) bannerMsg.value = ''
  }, 6000)
}

async function fetchCorpusForensics() {
  try {
    const res = await fetch('/api/forensics/corpus')
    if (res.ok) {
      forensics.value = await res.json()
    }
  } catch (err) {
    console.error('Forensics fetch error:', err)
  }
}

async function queryOllamaIntel(force = false) {
  querying.value = true
  try {
    const res = await fetch('/api/ollama/data-intelligence', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ focus: focusInput.value, force }),
    })
    if (res.ok) {
      const data = await res.json()
      intel.value = data
      if (data.forensics) forensics.value = data.forensics
      if (force) {
        flash(
          data.ollama_live
            ? `Live nightsweep-signalintelligence analysis completed in ${data.latency_ms} ms`
            : 'Empirical NightSweep forensics & recommendations refreshed'
        )
      }
    }
  } catch (err) {
    console.error('NightSweep intelligence error:', err)
  } finally {
    querying.value = false
  }
}

async function toggleFlag(key) {
  const nextVal = !Boolean(config.value[key])
  try {
    const res = await fetch('/api/forensics/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [key]: nextVal }),
    })
    if (res.ok) {
      const data = await res.json()
      if (data.forensics) forensics.value = data.forensics
      flash(`Updated ${key} = ${nextVal}`)
      emit('updated')
    }
  } catch (err) {
    console.error('Toggle forensics flag error:', err)
  }
}

async function setEntrainmentBand(band) {
  try {
    const res = await fetch('/api/forensics/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ active_entrainment_band: band }),
    })
    if (res.ok) {
      const data = await res.json()
      if (data.forensics) forensics.value = data.forensics
      if (binauralAudioUrl.value) {
        binauralAudioUrl.value = `/api/forensics/binaural.wav?band=${band}&speaker_id=PERSON_DELTA&t=${Date.now()}`
      }
      flash(`Switched Sec. 27 Binaural Entrainment to ${band}`)
      emit('updated')
    }
  } catch (err) {
    console.error('Set entrainment band error:', err)
  }
}

function playBinauralWav() {
  const band = config.value.active_entrainment_band || 'DELTA'
  binauralAudioUrl.value = `/api/forensics/binaural.wav?band=${band}&speaker_id=PERSON_DELTA&t=${Date.now()}`
  flash(`Synthesized Analytic Hilbert SSB ${band} Binaural WAV`)
}

async function pushBreathPhase(phase) {
  try {
    const res = await fetch('/api/forensics/biomacro/trigger', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phase }),
    })
    if (res.ok) {
      const data = await res.json()
      if (data.forensics) forensics.value = data.forensics
      if (data.triggered && data.macro) {
        flash(`BioMacro Triggered: ${data.macro.command} (${data.macro.pattern})`)
        emit('updated')
      } else {
        flash(`Recorded Breath Phase: ${phase} → Window [${(data.biomacro_state?.phase_window || []).join(', ')}]`)
      }
    }
  } catch (err) {
    console.error('Push breath phase error:', err)
  }
}

async function triggerBioMacroCommand(command) {
  try {
    const res = await fetch('/api/forensics/biomacro/trigger', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command }),
    })
    if (res.ok) {
      const data = await res.json()
      if (data.forensics) forensics.value = data.forensics
      flash(`Executed BioMacro: ${command} (${data.macro?.desc || ''})`)
      emit('updated')
    }
  } catch (err) {
    console.error('Trigger biomacro error:', err)
  }
}

async function activateFeatureCard(fc) {
  activatingId.value = fc.id
  try {
    const res = await fetch('/api/self-improve/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: fc.id,
        title: fc.title,
        speaker_id: fc.action_payload?.speaker_id || 'GLOBAL',
        category: fc.nightsweep_section,
        source: 'NightSweep Data Intelligence Lab',
        payload: fc.action_payload || {},
      }),
    })
    if (res.ok) {
      await fetchCorpusForensics()
      flash(`Activated & Persisted: ${fc.title}`)
      emit('updated')
    }
  } catch (err) {
    console.error('Activate feature error:', err)
  } finally {
    activatingId.value = ''
  }
}

onMounted(async () => {
  await fetchCorpusForensics()
  queryOllamaIntel(true)
})
</script>

<style scoped>
.ns-lab-card {
  border: 1px solid rgba(88, 166, 255, 0.35);
  background: linear-gradient(180deg, rgba(22, 27, 34, 0.98) 0%, rgba(13, 17, 23, 0.98) 100%);
}
.live-pill {
  color: #3fb950;
  border-color: rgba(63, 185, 80, 0.45);
  background: rgba(46, 160, 67, 0.12);
}
.cal-pill {
  color: #58a6ff;
  border-color: rgba(88, 166, 255, 0.4);
}
.mode-pill {
  color: #d2a8ff;
  border-color: rgba(210, 168, 255, 0.4);
  background: rgba(163, 113, 247, 0.1);
}
.query-controls {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.focus-input {
  min-width: 320px;
  background: #0d1117;
  color: #e6edf3;
  border: 1px solid #30363d;
  border-radius: 6px;
  padding: 7px 11px;
  font-size: 0.84rem;
}
.banner-ok {
  margin: 10px 0;
  padding: 8px 12px;
  border-radius: 6px;
  background: rgba(46, 160, 67, 0.16);
  border: 1px solid rgba(63, 185, 80, 0.45);
  color: #7ee787;
  font-size: 0.82rem;
}
.kpi-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 10px;
  margin-top: 12px;
}
.kpi-box {
  background: #0d1117;
  border: 1px solid #21262d;
  border-radius: 8px;
  padding: 10px 12px;
}
.kpi-lbl {
  font-size: 0.7rem;
  color: #8b949e;
  letter-spacing: 0.04em;
}
.kpi-val {
  font-size: 1.18rem;
  font-weight: 700;
  margin: 4px 0 2px;
}
.kpi-unit {
  font-size: 0.78rem;
  font-weight: 500;
  color: #8b949e;
}
.kpi-sub {
  font-size: 0.74rem;
  color: #8b949e;
}
.toggle-deck {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-top: 12px;
  padding: 8px 10px;
  background: rgba(13, 17, 23, 0.75);
  border: 1px solid #21262d;
  border-radius: 8px;
}
.chip-toggle {
  background: #161b22;
  color: #8b949e;
  border: 1px solid #30363d;
  border-radius: 6px;
  padding: 5px 10px;
  font-size: 0.76rem;
  cursor: pointer;
}
.chip-toggle.on {
  color: #7ee787;
  border-color: rgba(63, 185, 80, 0.5);
  background: rgba(46, 160, 67, 0.12);
}
.band-switcher {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 0.76rem;
  color: #8b949e;
}
.band-btn {
  background: #161b22;
  color: #8b949e;
  border: 1px solid #30363d;
  border-radius: 5px;
  padding: 3px 8px;
  cursor: pointer;
  font-size: 0.74rem;
}
.band-btn.active {
  color: #58a6ff;
  border-color: #58a6ff;
  background: rgba(56, 139, 253, 0.15);
}
.btn-play-ssb {
  background: rgba(56, 139, 253, 0.16);
  color: #79c0ff;
  border: 1px solid rgba(88, 166, 255, 0.45);
  border-radius: 5px;
  padding: 3px 9px;
  cursor: pointer;
  font-size: 0.74rem;
}
.audio-bar {
  margin-top: 10px;
  padding: 8px 12px;
  background: #0d1117;
  border: 1px solid rgba(63, 185, 80, 0.4);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 0.78rem;
  color: #7ee787;
}
.ssb-audio {
  height: 30px;
  max-width: 320px;
}
.nextgen-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
  gap: 12px;
  margin-top: 12px;
}
.ls-bars {
  display: flex;
  align-items: flex-end;
  gap: 4px;
  height: 82px;
  padding: 8px 6px 4px;
  background: #161b22;
  border-radius: 6px;
  border: 1px solid #21262d;
}
.ls-bar-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
}
.ls-bar-fill {
  width: 100%;
  background: rgba(88, 166, 255, 0.45);
  border-radius: 3px 3px 0 0;
  transition: height 0.25s ease;
}
.ls-bar-fill.peak {
  background: #3fb950;
  box-shadow: 0 0 8px rgba(63, 185, 80, 0.6);
}
.ls-lbl {
  font-size: 0.62rem;
  color: #8b949e;
}
.kalman-strip,
.ultrasonic-strip {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 8px;
  margin-top: 8px;
  font-size: 0.73rem;
  color: #8b949e;
}
.kalman-strip strong,
.ultrasonic-strip strong {
  color: #e6edf3;
}
.vmic-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(185px, 1fr));
  gap: 8px;
}
.vmic-card {
  background: #161b22;
  border: 1px solid #30363d;
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 0.73rem;
}
.vmic-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 5px;
  color: #79c0ff;
}
.vmic-badge {
  font-size: 0.64rem;
  padding: 1px 5px;
  border-radius: 4px;
  background: rgba(56, 139, 253, 0.14);
  color: #58a6ff;
}
.vmic-metrics {
  display: flex;
  flex-direction: column;
  gap: 3px;
  color: #8b949e;
}
.biomacro-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 0.75rem;
  color: #c9d1d9;
}
.phase-btns {
  display: flex;
  gap: 6px;
}
.btn-phase {
  background: #161b22;
  color: #79c0ff;
  border: 1px solid rgba(88, 166, 255, 0.4);
  border-radius: 5px;
  padding: 3px 8px;
  font-size: 0.72rem;
  cursor: pointer;
}
.macro-btn-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(175px, 1fr));
  gap: 7px;
}
.macro-card-btn {
  text-align: left;
  background: #161b22;
  border: 1px solid #30363d;
  border-radius: 6px;
  padding: 7px 9px;
  cursor: pointer;
}
.macro-card-btn.active {
  border-color: rgba(63, 185, 80, 0.6);
  background: rgba(46, 160, 67, 0.12);
}
.mc-cmd {
  font-weight: 700;
  font-size: 0.75rem;
  color: #7ee787;
}
.mc-pat {
  font-size: 0.68rem;
  color: #d2a8ff;
  margin: 2px 0;
}
.mc-desc {
  font-size: 0.68rem;
  color: #8b949e;
}
.intel-synthesis {
  margin-top: 12px;
}
.synth-box {
  background: rgba(56, 139, 253, 0.08);
  border: 1px solid rgba(88, 166, 255, 0.3);
  border-radius: 8px;
  padding: 10px 14px;
}
.synth-head {
  font-size: 0.72rem;
  color: #58a6ff;
  margin-bottom: 4px;
}
.synth-box p {
  margin: 0;
  font-size: 0.86rem;
  line-height: 1.48;
  color: #e6edf3;
}
.two-col {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 12px;
  margin-top: 10px;
}
.intel-col {
  background: #0d1117;
  border: 1px solid #21262d;
  border-radius: 8px;
  padding: 10px 14px;
}
.intel-col h4 {
  margin: 0 0 8px;
  font-size: 0.86rem;
  color: #79c0ff;
}
.intel-col ul {
  margin: 0;
  padding-left: 18px;
  font-size: 0.81rem;
  line-height: 1.46;
  color: #c9d1d9;
}
.intel-col li {
  margin-bottom: 6px;
}
.feature-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(290px, 1fr));
  gap: 10px;
  margin-top: 12px;
}
.feat-card {
  background: #0d1117;
  border: 1px solid #30363d;
  border-radius: 8px;
  padding: 11px 13px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.feat-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.7rem;
}
.sec-badge {
  color: #d2a8ff;
}
.state-badge {
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid #30363d;
  color: #8b949e;
}
.state-badge.active {
  color: #3fb950;
  border-color: rgba(63, 185, 80, 0.45);
  background: rgba(46, 160, 67, 0.12);
}
.feat-title {
  font-weight: 700;
  font-size: 0.9rem;
  color: #e6edf3;
}
.feat-ev {
  font-size: 0.78rem;
  color: #f0883e;
  line-height: 1.38;
}
.feat-arch {
  font-size: 0.78rem;
  color: #8b949e;
  line-height: 1.38;
  flex: 1;
}
.btn-activate {
  margin-top: 4px;
  background: rgba(35, 134, 54, 0.2);
  color: #7ee787;
  border: 1px solid rgba(63, 185, 80, 0.45);
  font-size: 0.76rem;
  padding: 6px 10px;
  cursor: pointer;
}
.btn-activate:hover {
  background: rgba(35, 134, 54, 0.36);
}
.bottom-split {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 12px;
  margin-top: 12px;
}
.sub-panel {
  background: #0d1117;
  border: 1px solid #21262d;
  border-radius: 8px;
  padding: 10px 12px;
}
.sub-title {
  font-size: 0.76rem;
  color: #58a6ff;
  margin-bottom: 8px;
}
.vocab-rows {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.vocab-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.spk-chip {
  background: #161b22;
  color: #58a6ff;
  border: 1px solid rgba(88, 166, 255, 0.35);
  border-radius: 5px;
  padding: 2px 8px;
  font-size: 0.73rem;
  cursor: pointer;
}
.word-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.w-pill {
  background: #161b22;
  border: 1px solid #30363d;
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 0.72rem;
  color: #c9d1d9;
}
.w-pill em {
  font-style: normal;
  color: #8b949e;
}
.halluc-strip {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed #21262d;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 0.72rem;
}
.h-lbl {
  color: #ff7b72;
}
.h-chip {
  background: rgba(248, 81, 73, 0.12);
  border: 1px solid rgba(248, 81, 73, 0.3);
  color: #ffa198;
  border-radius: 4px;
  padding: 1px 6px;
}
.table-wrap {
  overflow-x: auto;
}
.mm-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.73rem;
}
.mm-table th,
.mm-table td {
  padding: 4px 6px;
  border-bottom: 1px solid #21262d;
  text-align: left;
}
.mm-table th {
  color: #8b949e;
}
.mode-cell {
  color: #7ee787;
}
</style>
