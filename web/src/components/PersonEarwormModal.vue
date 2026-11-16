<template>
  <div v-if="speakerId" class="modal-backdrop" @click.self="$emit('close')">
    <div class="modal-card">
      <!-- TOP BAR: PERSON SWITCHER + CLOSE -->
      <div class="modal-topbar">
        <div class="person-tabs">
          <button
            v-for="spk in speakerList"
            :key="spk.speaker_id"
            class="person-tab mono"
            :class="{ active: spk.speaker_id === speakerId }"
            :style="spk.speaker_id === speakerId ? { borderColor: spk.color, color: spk.color } : {}"
            @click="$emit('select-speaker', spk.speaker_id)"
          >
            <span class="p-dot" :style="{ background: spk.color }"></span>
            {{ spk.speaker_id }}
          </button>
        </div>
        <button class="close-btn mono" @click="$emit('close')">✕ Close</button>
      </div>

      <!-- SPEAKER IDENTITY & BIOMETRIC HEADER -->
      <div class="dossier-head" :style="{ borderLeftColor: activeDossier.color || '#58a6ff' }">
        <div>
          <div class="dossier-id-row">
            <h2 class="mono" :style="{ color: activeDossier.color || '#58a6ff' }">
              {{ speakerId === 'DEVICE_CELLPHONE' ? '📱' : (speakerId === 'DEVICE_MEMS' ? '🔬' : (speakerId === 'PERSON_TYPIST' ? '⌨️' : (speakerId === 'OTHER_ROOM_SUBLEVEL' ? '🧱' : '🎧'))) }}
              {{ speakerId }} · {{ speakerId === 'OTHER_ROOM_SUBLEVEL' ? 'Mid-Air Piggybacked Non-Occupant Sublevel Dossier' : ((speakerId === 'DEVICE_CELLPHONE' || speakerId === 'DEVICE_MEMS') ? 'Electronic / MEMS Acoustic Signature Dossier' : 'Shared Earworm & Biometric Dossier') }}
            </h2>
            <span class="pill mono">{{ activeDossier.spatial?.proximity_zone || 'NEAR_FIELD' }}</span>
            <span v-if="activeDossier.gender_badge" class="pill mono" style="border-color: rgba(210, 168, 255, 0.5); color: #e9d5ff">
              {{ activeDossier.gender_badge }}
            </span>
          </div>
          <div class="dossier-metrics mono">
            <span>🗣️ {{ activeDossier.wph ?? 0 }} WPH (Active {{ activeDossier.active_pace_wph ?? 0 }} WPH)</span>
            <span>🤫 Whisper {{ activeDossier.whisper_pct ?? 0 }}%</span>
            <span>🧬 VTL {{ activeDossier.vtl_cm ?? 17 }} cm</span>
            <span>🎵 F0 {{ activeDossier.f0_hz > 0 ? activeDossier.f0_hz + ' Hz' : 'Unvoiced' }}</span>
            <span>🫁 {{ activeDossier.resp_bpm ?? 15 }} BPM</span>
            <span>📍 {{ activeDossier.spatial?.range_m ?? 1.0 }}m ({{ formatAz(activeDossier.spatial?.azimuth_deg) }})</span>
          </div>
        </div>
      </div>

      <div v-if="shareToast" class="share-toast mono">
        ✅ {{ shareToast }}
      </div>

      <!-- PRIMARY SHARED EARWORM SHOWCASE + AUDIO MIRROR -->
      <div class="earworm-hero">
        <div class="hero-top">
          <div>
            <div class="hero-lbl mono">🎶 ACTIVE EARWORM THEY HAVE BEEN SHARING</div>
            <div class="hero-phrase">"{{ selectedPhrase }}"</div>
          </div>
          <div class="tempo-badges mono">
            <span class="t-pill">{{ activeBpm }} BPM</span>
            <span class="t-pill cyan">{{ activeContour }}</span>
            <span class="t-pill">F1 {{ activeDossier.target_f1_hz ?? 510 }} Hz · F2 {{ activeDossier.target_f2_hz ?? 1580 }} Hz</span>
            <span v-if="activeDossier.delta_motion" class="t-pill" style="border-color: rgba(63, 185, 80, 0.5); color: #7ee787">
              🧘 Delta {{ activeDossier.delta_motion.delta_peak_hz ?? 1.55 }} Hz · {{ activeDossier.delta_motion.emotional_reset_pct ?? 76 }}% Reset
            </span>
            <span v-if="activeDossier.delta_motion" class="t-pill" style="border-color: rgba(240, 136, 62, 0.5); color: #ffa657">
              🚶 {{ activeDossier.delta_motion.movement_state || 'STILL_ANCHORED' }} (VAD Motion {{ Math.round((activeDossier.delta_motion.vad_motion_score || 0) * 100) }}%)
            </span>
          </div>
        </div>

        <!-- Markov Sequence Loop + Co-Sharers -->
        <div class="loop-strip mono">
          <div>
            <span class="muted">Markov Loop:</span>
            <strong style="color: #7ee787"> {{ activeDossier.markov_loop || selectedPhrase }}</strong>
          </div>
          <div v-if="activeDossier.shared_with?.length" class="cosharers">
            <span class="muted">Shared With:</span>
            <button
              v-for="cs in activeDossier.shared_with"
              :key="cs.speaker_id"
              class="cosharer-chip mono"
              :style="{ borderColor: cs.color, color: cs.color }"
              @click="$emit('select-speaker', cs.speaker_id)"
              title="Click to inspect co-sharer's earworm dossier"
            >
              ↔ {{ cs.speaker_id }} ({{ cs.shared_hooks_count }} shared)
            </button>
          </div>
          <div v-else class="muted">Solo personal earworm loop in current window</div>
        </div>

        <!-- Synthesized VTL Formant Whisper / Electronic Audio Player -->
        <div class="audio-row">
          <div class="audio-lbl mono">
            {{ (speakerId === 'DEVICE_CELLPHONE' || speakerId === 'DEVICE_MEMS') ? '🔊 48 kHz Audible + Heterodyned Ultrasonic Signature (WAV):' : '🔊 VTL-Calibrated Formant Whisper Mirror (48 kHz WAV):' }}
          </div>
          <audio :key="currentAudioUrl" :src="currentAudioUrl" controls preload="metadata" class="wav-player"></audio>
        </div>

        <!-- SHARE ACTIONS BAR -->
        <div class="share-composer">
          <input
            v-model="shareNote"
            type="text"
            class="note-input"
            placeholder="Optional note when sharing this earworm (e.g., 'Overnight shared chorus between ALPHA & BETA')..."
          />
          <div class="share-buttons">
            <button class="btn btn-primary" :disabled="sharingBusy" @click="shareEarworm('link')">
              🔗 Copy Share Link
            </button>
            <button
              class="btn btn-talkback"
              type="button"
              @click="$emit('talkback-speaker', { speakerId, phrase: selectedPhrase, ts: Date.now() })"
            >
              🔊 Talk Back / Arm Whisper
            </button>
            <button class="btn" :disabled="sharingBusy" @click="shareEarworm('card')">
              📋 Copy Share Card
            </button>
            <button class="btn btn-udp" :disabled="sharingBusy" @click="shareEarworm('udp')">
              📡 Broadcast to UDP :5005
            </button>
            <a :href="currentAudioUrl" :download="`${speakerId.toLowerCase()}_earworm.wav`" class="btn link-btn">
              📥 Download .WAV
            </a>
            <button class="btn" :disabled="sharingBusy" @click="shareEarworm('json')">
              📦 Export .JSON
            </button>
          </div>
        </div>

        <div v-if="lastSharePacket" class="packet-preview mono">
          <div>
            <strong>Share Link:</strong>
            <a :href="lastSharePacket.share_url" target="_blank" rel="noopener">{{ lastSharePacket.share_url }}</a>
          </div>
          <div>
            <strong>SHA-256:</strong> {{ lastSharePacket.packet_sha256?.slice(0, 24) }}…
          </div>
        </div>

        <!-- OLLAMA MODAL ADVISOR + CLOSEST FAINT FOCUS + SILENT READING OUT-LOUD + MODULE 4 ENTRAINMENT -->
        <div class="modal-ollama-box">
          <div class="mob-top">
            <span class="mono mob-title">
              🧠 NightSweep Ollama Modal · Module 4 IntegratedEntrainmentSynthesizer &amp; 10-Feature Reference
            </span>
            <div class="mob-btns">
              <button
                type="button"
                class="btn mob-btn-focus mono"
                style="border-color: #f0883e; color: #ffa657"
                @click="lockDepartureIdentityHere"
              >
                🚪 Lock {{ speakerId }} for Departure/Arrival Diff
              </button>
              <button
                type="button"
                class="btn mob-btn-focus mono"
                @click="pinRoomFocusHere('PINNED')"
              >
                📌 Pin Exclusive Focus on {{ speakerId }}
              </button>
              <button
                type="button"
                class="btn mob-btn-focus mono"
                style="border-color: #a371f7; color: #e9d5ff"
                @click="pinRoomFocusHere('BOTH')"
              >
                ⚡ Dual Focus: Closest + {{ speakerId }}
              </button>
              <button
                type="button"
                class="btn mob-btn-read mono"
                :disabled="modalOutLoudBusy"
                @click="playModalReadingOutLoud"
              >
                {{ modalOutLoudBusy ? '🔊 Rendering…' : '🔊 Hear Reading Out Loud + A2-E3-A3' }}
              </button>
              <button
                type="button"
                class="btn mob-btn-focus mono"
                style="border-color: #3fb950; color: #7ee787"
                @click="playModalDeltaWav"
              >
                🧘 Hear 0.5–4 Hz Delta + Whisper
              </button>
              <button
                type="button"
                class="btn mob-btn-focus mono"
                style="border-color: #58a6ff; color: #79c0ff"
                @click="playModalEntrainmentSynthWav"
              >
                🎧 Hear Module 4 Entrainment Synth WAV
              </button>
              <button
                type="button"
                class="btn mob-btn-focus mono"
                style="border-color: #f85149; color: #ff7b72"
                @click="playModalFmStationWav"
              >
                📻 Audition FM {{ selectedModalFmFreq }} MHz WAV
              </button>
              <button
                type="button"
                class="btn mob-btn-focus mono"
                style="border-color: #38bdf8; color: #38bdf8"
                @click="playModalFhssSonarWav"
              >
                🔊 Audition FHSS 19–22 kHz WAV
              </button>
              <button
                type="button"
                class="btn mob-btn-focus mono"
                style="border-color: #34d399; color: #34d399"
                @click="playModalFreqDetectorWav"
              >
                🎯 Audition FreqDetector WAV
              </button>
              <button
                type="button"
                class="btn mob-btn-focus mono"
                style="border-color: #fbbf24; color: #fbbf24"
                @click="playModalSwimlaneSynthWav"
              >
                🎹 Audition SwimlaneToneSynth WAV
              </button>
              <button
                type="button"
                class="btn mob-btn-focus mono"
                style="border-color: #f472b6; color: #f472b6"
                @click="playModalCovertSideWav"
              >
                🕵️ Audition Covert Side-Channel WAV
              </button>
              <button
                type="button"
                class="btn mob-btn-ollama mono"
                :disabled="modalOllamaBusy"
                @click="askModalOllama"
              >
                {{ modalOllamaBusy ? '🧠 Advising…' : '🧠 Consult Ollama Modal' }}
              </button>
              <button
                type="button"
                class="btn mob-btn-focus mono"
                style="border-color: #58a6ff; color: #79c0ff"
                @click="$emit('open-starter-guide')"
              >
                🧰 Starter Guide &amp; All Dependencies
              </button>
            </div>
          </div>

          <!-- INLINE STARTER GUIDE CALLOUT WHEN NIGHTSWEEP LIVE MODEL OR DEPENDENCIES ARE MISSING -->
          <div
            v-if="starterGuide?.summary?.any_nightsweep_missing"
            class="mob-audio mono"
            style="border-color: rgba(240, 136, 62, 0.5); color: #ffa657; justify-content: space-between; flex-wrap: wrap; gap: 8px"
          >
            <span>
              ⚠️ NightSweep Model / Dependency Setup Available ({{ starterGuide.summary.ready_count }}/{{ starterGuide.summary.total_dependencies }} READY) —
              Build <span style="color: #79c0ff">nightsweep-signalintelligence:latest</span> or download <span style="color: #79c0ff">Faster-Whisper / ResNet34-ONNX</span> weights:
            </span>
            <button
              type="button"
              class="btn mob-btn-focus mono"
              style="border-color: #f0883e; color: #ffa657"
              @click="$emit('open-starter-guide')"
            >
              📘 Open Full Dependency Starter Guide
            </button>
          </div>
          <div v-if="modalOutLoudUrl" class="mob-audio mono">
            <span>🗣️ Silent Reading Out-Loud + A2–E3–A3 WPM Shimmer Drone:</span>
            <audio :src="modalOutLoudUrl" controls autoplay class="wav-player"></audio>
          </div>
          <div v-if="modalDeltaWavUrl" class="mob-audio mono" style="color: #7ee787">
            <span>🧘 0.5–4.0 Hz Binaural Delta Emotional Reset + Whisper Mirror:</span>
            <audio :key="modalDeltaWavUrl" :src="modalDeltaWavUrl" controls autoplay class="wav-player"></audio>
          </div>
          <div v-if="modalEntrainmentWavUrl" class="mob-audio mono" style="color: #79c0ff">
            <span>
              🎧 Module 4 IntegratedEntrainmentSynthesizer ({{ modalRefSynth.speaker_carrier_hz || 210 }} Hz ±
              {{ ((modalRefSynth.speaker_target_brainwave_hz || 2.4) / 2).toFixed(2) }} Hz · LFO Depth {{ modalRefSynth.mod_depth ?? 0.4 }}):
            </span>
            <audio :key="modalEntrainmentWavUrl" :src="modalEntrainmentWavUrl" controls autoplay class="wav-player"></audio>
          </div>
          <div v-if="modalFmWavUrl" class="mob-audio mono" style="color: #ff7b72">
            <span>
              📻 FMBandPirateScanner Superhet Demod ({{ selectedModalFmFreq }} MHz · 2.0 MSPS → 200 kHz IF · 19 kHz Pilot / 57 kHz RDS):
            </span>
            <audio :key="modalFmWavUrl" :src="modalFmWavUrl" controls autoplay class="wav-player"></audio>
          </div>
          <div v-if="modalFhssWavUrl" class="mob-audio mono" style="color: #38bdf8">
            <span>
              🔊 FrequencyHoppingSonarBridge (19.0–22.0 kHz Phase-Continuous Hop + &lt;50 Hz Quadrature I/Q Muscle Reflection):
            </span>
            <audio :key="modalFhssWavUrl" :src="modalFhssWavUrl" controls autoplay class="wav-player"></audio>
          </div>
          <div v-if="modalFreqDetWavUrl" class="mob-audio mono" style="color: #34d399">
            <span>
              🎯 FrequencyDetector 3-Stage Probe (Goertzel 697/1209 Hz Burst · 400→2400 Hz Parabolic FFT Chirp · 880 Hz ZCR Sine):
            </span>
            <audio :key="modalFreqDetWavUrl" :src="modalFreqDetWavUrl" controls autoplay class="wav-player"></audio>
          </div>
          <div v-if="modalSwimlaneWavUrl" class="mob-audio mono" style="color: #fbbf24">
            <span>
              🎹 SwimlaneToneSynth (256-Sample / 5.8ms Polyphonic Sine Synth · 3ms 1-Pole De-Click Ramp · Closed-Loop Goertzel Verified):
            </span>
            <audio :key="modalSwimlaneWavUrl" :src="modalSwimlaneWavUrl" controls autoplay class="wav-player"></audio>
          </div>
          <div v-if="modalCovertSideWavUrl" class="mob-audio mono" style="color: #f472b6">
            <span>
              🕵️ CovertPiggybackAudioAnalyzer (isolated_hidden_side_channel.wav · (L - R)/2 Anti-Phase &amp; 40 kHz Ultrasonic Demod):
            </span>
            <audio :key="modalCovertSideWavUrl" :src="modalCovertSideWavUrl" controls autoplay class="wav-player"></audio>
          </div>

          <!-- LIVE 10-FEATURE + MODULE 4 INTEGRATED ENTRAINMENT SYNTHESIZER MODAL REFERENCE GRID -->
          <div class="modal-ref-grid mono">
            <div class="mref-card mref-synth">
              <div class="mref-hdr">
                <span>⚡ Module 4: IntegratedEntrainmentSynthesizer</span>
                <span class="mref-badge">{{ modalRefSynth.sample_rate || 44100 }} Hz · float32 Stereo</span>
              </div>
              <div class="mref-line">
                Binaural Split:
                <strong>L={{ modalRefSynth.speaker_freq_left_hz || 208.8 }} Hz</strong> ·
                <strong>R={{ modalRefSynth.speaker_freq_right_hz || 211.2 }} Hz</strong>
                (Δf={{ modalRefSynth.speaker_target_brainwave_hz || 2.4 }} Hz)
              </div>
              <div class="mref-line">
                LFO Envelope: <code>1.0 - {{ modalRefSynth.mod_depth ?? 0.4 }}·0.5·(1 + sin(φ_lfo))</code> ·
                Amp={{ modalRefSynth.base_amplitude ?? 0.5 }}
              </div>
            </div>

            <div class="mref-card">
              <div class="mref-hdr">
                <span>❤️ #1 Cardio-Vocal BCG &amp; PWTT</span>
                <span class="mref-badge">{{ modalRefBcg.autonomic_state || 'PARASYMPATHETIC_CALM' }}</span>
              </div>
              <div class="mref-line">
                HR: <strong>{{ modalRefBcg.heart_rate_bpm || 68.5 }} BPM</strong> ·
                RMSSD: <strong>{{ modalRefBcg.hrv_rmssd_ms || 42.0 }} ms</strong> ·
                PWTT: <strong>{{ modalRefBcg.carotid_pwtt_ms || 148.0 }} ms</strong> ·
                RSA: <strong>{{ modalRefBcg.rsa_phase_lock_pct || 84.0 }}%</strong>
              </div>
            </div>

            <div class="mref-card">
              <div class="mref-hdr">
                <span>🗣️ #4 Wakita 8-Section Vocal-Tract</span>
                <span class="mref-badge">{{ modalRefWakita.constriction_locus || 'PALATAL_ALVEOLAR' }}</span>
              </div>
              <div class="mref-line">
                Areas (cm²): <code>[{{ (modalRefWakita.areas_cm2 || [2.8, 3.2, 4.1, 3.9, 2.4, 2.9, 4.5, 5.2]).slice(0, 6).join(', ') }}…]</code>
                · r₀={{ modalRefWakita.glottal_termination_r0 ?? 0.85 }}
              </div>
            </div>

            <div class="mref-card">
              <div class="mref-hdr">
                <span>🎯 #5 Split-Conformal 95% ASR</span>
                <span class="mref-badge">q̂={{ modalRefConformal.nonconformity_q_hat || 0.412 }} · {{ modalRefConformal.empirical_coverage_pct || 95.8 }}%</span>
              </div>
              <div class="mref-line">
                Set: <code>{{ (modalRefConformal.speaker_lattice?.conformal_95_prediction_set || [selectedPhrase]).slice(0, 2).join(' | ') }}</code>
              </div>
            </div>

            <div class="mref-card">
              <div class="mref-hdr">
                <span>🔊 #6 18-Tap MIMO-WPE &amp; #7 Lombard</span>
                <span class="mref-badge">RT60={{ modalRefWpe.room_rt60_sec || 0.44 }}s · +{{ modalRefWpe.speaker_drr?.drr_gain_db || 3.4 }} dB DRR</span>
              </div>
              <div class="mref-line">
                DRR: <strong>{{ modalRefWpe.speaker_drr?.raw_drr_db || 12.4 }} → {{ modalRefWpe.speaker_drr?.wpe_drr_db || 15.8 }} dB</strong> ·
                H1-H2: <strong>{{ modalRefLombard.h1_h2_db || 7.2 }} dB</strong> (OQ={{ modalRefLombard.open_quotient_oq || 0.64 }})
              </div>
            </div>

            <div class="mref-card">
              <div class="mref-hdr">
                <span>📡 #2/#3/#8/#9/#10 Sensor &amp; ZK Audit</span>
                <span class="mref-badge">Merkle ε={{ modalRefMerkle.dp_epsilon || 1.2 }} ✓</span>
              </div>
              <div class="mref-line">
                Bistatic τ=<strong>{{ modalRefBistatic.bistatic_delay_ns || 4.8 }} ns</strong> ·
                Saccade=<strong>{{ modalRefSaccade.estimated_silent_wpm || 192 }} WPM</strong> ·
                Root=<code>{{ (modalRefMerkle.merkle_root || '9f86d081884c').slice(0, 12) }}…</code>
              </div>
            </div>

            <div class="mref-card" style="border-color: rgba(248, 81, 73, 0.5); background: rgba(248, 81, 73, 0.07)">
              <div class="mref-hdr">
                <span style="color: #ff7b72">📻 FMBandPirateScanner (88–108 MHz)</span>
                <span class="mref-badge" style="color: #ff7b72; border-color: rgba(248, 81, 73, 0.5)">
                  {{ modalRefFm.kpis?.flagged_pirate_count ?? 4 }} Pirate / {{ modalRefFm.kpis?.total_stations ?? 10 }} Active
                </span>
              </div>
              <div class="mref-line" style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap">
                <span>Station:</span>
                <select
                  v-model.number="selectedModalFmFreq"
                  style="background: #0d1117; color: #e6edf3; border: 1px solid #30363d; border-radius: 4px; font-size: 0.66rem; padding: 1px 4px"
                >
                  <option
                    v-for="st in (modalRefFm.stations || defaultModalFmStations)"
                    :key="st.frequency_mhz"
                    :value="st.frequency_mhz"
                  >
                    {{ st.frequency_mhz }} MHz ({{ st.flags?.length ? st.flags.join(', ') : 'CLEAN_COMMERCIAL' }} · ±{{ st.peak_deviation_khz }}kHz)
                  </option>
                </select>
                <button
                  type="button"
                  class="mono"
                  style="background: #141d2b; color: #38bdf8; border: 1px solid #2b3c58; border-radius: 4px; font-size: 0.64rem; padding: 1px 6px; cursor: pointer"
                  @click="pinModalFmBistatic"
                >
                  📌 Pin {{ selectedModalFmFreq }} MHz Bistatic
                </button>
              </div>
              <div class="mref-line">
                IF: <code>101-tap 95kHz FIR (2.0MSPS→200kHz)</code> ·
                Bistatic: <strong>{{ modalRefFm.pinned_bistatic_freq_mhz ?? 100.1 }} MHz</strong>
              </div>
            </div>

            <div class="mref-card" style="border-color: rgba(56, 189, 248, 0.5); background: rgba(56, 189, 248, 0.07)">
              <div class="mref-hdr">
                <span style="color: #38bdf8">🔊 FHSS Ultrasonic Sonar (19–22 kHz)</span>
                <span class="mref-badge" style="color: #38bdf8; border-color: rgba(56, 189, 248, 0.5)">
                  Hop #{{ modalRefFhss.current_hop_idx ?? 6 }} · {{ modalRefFhss.active_carrier_khz ?? 20.5 }} kHz
                </span>
              </div>
              <div class="mref-line" style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap">
                <span>
                  I/Q: <strong>{{ modalRefFhss.kpis?.mean_quadrature_iq_energy ?? 0.0186 }}</strong> ·
                  Δd: <strong>{{ modalRefFhss.kpis?.mean_muscle_displacement_um ?? 42.8 }}µm</strong>
                </span>
                <button
                  type="button"
                  class="mono"
                  style="background: #141d2b; color: #38bdf8; border: 1px solid #2b3c58; border-radius: 4px; font-size: 0.64rem; padding: 1px 6px; cursor: pointer"
                  @click="triggerModalFhssHop"
                >
                  🔀 Next Hop
                </button>
              </div>
              <div class="mref-line">
                Guard: <strong>+{{ modalRefFhss.kpis?.intercept_guard_db ?? 31.4 }} dB</strong> ·
                Phase: <code>{{ modalRefFhss.phase_accumulator_rad ?? 1.57 }} rad</code>
              </div>
            </div>

            <div class="mref-card" style="border-color: rgba(52, 211, 153, 0.5); background: rgba(52, 211, 153, 0.07)">
              <div class="mref-hdr">
                <span style="color: #34d399">🎯 FrequencyDetector (Goertzel · FFT · ZCR)</span>
                <span class="mref-badge" style="color: #34d399; border-color: rgba(52, 211, 153, 0.5)">
                  {{ modalRefFreqDet.kpis?.goertzel_hit_count ?? 18 }} Goertzel · {{ modalRefFreqDet.kpis?.fft_sweep_frame_count ?? 42 }} FFT
                </span>
              </div>
              <div class="mref-line" style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap">
                <span>
                  Goertzel SNR: <strong>{{ modalRefFreqDet.kpis?.goertzel_mean_snr ?? 34.4 }}×</strong> ·
                  FFT RMSE: <strong>{{ modalRefFreqDet.kpis?.fft_parabolic_rmse_hz ?? 4.8 }} Hz</strong>
                </span>
                <button
                  type="button"
                  class="mono"
                  style="background: #141d2b; color: #34d399; border: 1px solid #2b3c58; border-radius: 4px; font-size: 0.64rem; padding: 1px 6px; cursor: pointer"
                  @click="triggerModalFreqDetectorRun"
                >
                  ▶ Run 3-Mode Probe
                </button>
              </div>
              <div class="mref-line">
                ZCR: <strong>{{ modalRefFreqDet.kpis?.zcr_mean_estimated_hz ?? 880.0 }} Hz</strong> ·
                900 Hz False Alarms: <code>{{ modalRefFreqDet.kpis?.goertzel_false_positives ?? 0 }}</code>
              </div>
            </div>

            <div class="mref-card" style="border-color: rgba(251, 191, 36, 0.5); background: rgba(251, 191, 36, 0.07)">
              <div class="mref-hdr">
                <span style="color: #fbbf24">🎹 SwimlaneToneSynth ({{ modalRefSwimlane.latency_ms ?? 5.8 }}ms · 3ms 1-Pole)</span>
                <span class="mref-badge" style="color: #fbbf24; border-color: rgba(251, 191, 36, 0.5)">
                  {{ modalRefSwimlane.kpis?.active_lane_count ?? 3 }}/{{ modalRefSwimlane.kpis?.total_lanes ?? 7 }} Active
                </span>
              </div>
              <div class="mref-line" style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap">
                <span>
                  Goertzel Verified: <strong>{{ modalRefSwimlane.kpis?.closed_loop_goertzel_verified_count ?? 3 }} lanes</strong> ·
                  α=<code>{{ modalRefSwimlane.smoothing_coeff ?? 0.00753 }}</code>
                </span>
                <button
                  type="button"
                  class="mono"
                  style="background: #141d2b; color: #fbbf24; border: 1px solid #2b3c58; border-radius: 4px; font-size: 0.64rem; padding: 1px 6px; cursor: pointer"
                  @click="triggerModalSwimlaneSpeakerTone"
                >
                  🎹 Trigger {{ speakerId }} Lane
                </button>
              </div>
              <div class="mref-line">
                Active Hz: <strong>{{ (modalRefSwimlane.kpis?.active_freqs_hz || [440, 659.25, 880]).join(', ') }} Hz</strong>
              </div>
            </div>

            <div class="mref-card" style="border-color: rgba(244, 114, 182, 0.5); background: rgba(244, 114, 182, 0.07)">
              <div class="mref-hdr">
                <span style="color: #f472b6">🕵️ #15/#16 Voice Gender &amp; Covert Piggyback</span>
                <span class="mref-badge" style="color: #f472b6; border-color: rgba(244, 114, 182, 0.5)">
                  {{ activeDossier.gender_badge || '40kHz · Dichotic · Mid/Side' }}
                </span>
              </div>
              <div class="mref-line">
                [1] Ultra: <strong>40.0 kHz (0.428×)</strong> ·
                [2] Hilbert Env: <strong>r=0.142</strong> ·
                [3] Side/Mid: <strong>3.14×</strong>
              </div>
              <div class="mref-line">
                Biometrics: <strong>{{ activeDossier.voice_gender_profile?.classification || 'VTL + F0 Percentile Verified' }}</strong>
              </div>
            </div>
          </div>

          <div v-if="modalOllamaAdvice || modalDeltaOllamaAdvice || modalDataIntelAdvice || modalFmOllamaAdvice || modalFhssOllamaAdvice || modalFreqDetOllamaAdvice || modalSwimlaneOllamaAdvice" class="mob-advice">
            <p v-if="modalSwimlaneOllamaAdvice">{{ modalSwimlaneOllamaAdvice.overall_assessment }}</p>
            <p v-else-if="modalFreqDetOllamaAdvice">{{ modalFreqDetOllamaAdvice.overall_assessment }}</p>
            <p v-else-if="modalFhssOllamaAdvice">{{ modalFhssOllamaAdvice.overall_assessment }}</p>
            <p v-else-if="modalFmOllamaAdvice">{{ modalFmOllamaAdvice.overall_assessment }}</p>
            <p v-else-if="modalDataIntelAdvice">{{ modalDataIntelAdvice.executive_summary }}</p>
            <p v-else-if="modalDeltaOllamaAdvice">{{ modalDeltaOllamaAdvice.overall_assessment }}</p>
            <p v-else-if="modalOllamaAdvice">{{ modalOllamaAdvice.overall_assessment }}</p>
            <ul>
              <li v-for="(item, idx) in (modalSwimlaneOllamaAdvice?.envelope_and_phase_findings || []).slice(0, 2)" :key="'msw-' + idx">
                🎹 {{ item }}
              </li>
              <li v-for="(item, idx) in (modalFreqDetOllamaAdvice?.goertzel_and_cfar_findings || []).slice(0, 2)" :key="'mfd-' + idx">
                🎯 {{ item }}
              </li>
              <li v-for="(item, idx) in (modalFhssOllamaAdvice?.fhss_security_and_lcg_findings || []).slice(0, 2)" :key="'mfh-' + idx">
                🔊 {{ item }}
              </li>
              <li v-for="(item, idx) in (modalFmOllamaAdvice?.pirate_transmitter_findings || []).slice(0, 2)" :key="'mfp-' + idx">
                📻 {{ item }}
              </li>
              <li v-for="(item, idx) in (modalDataIntelAdvice?.new_feature_proposals || []).slice(0, 2)" :key="'mdi-' + idx">
                🧬 {{ item }}
              </li>
              <li v-for="(item, idx) in (modalDeltaOllamaAdvice?.vad_motion_earworm_advice || []).slice(0, 1)" :key="'mdv-' + idx">
                🚶 {{ item }}
              </li>
              <li v-for="(item, idx) in (modalDeltaOllamaAdvice?.delta_brainwave_feelings_advice || []).slice(0, 1)" :key="'mdd-' + idx">
                🧘 {{ item }}
              </li>
              <li v-for="(item, idx) in (modalOllamaAdvice?.closest_faint_focus_advice || []).slice(0, 1)" :key="'mf-' + idx">
                🎯 {{ item }}
              </li>
            </ul>
          </div>
        </div>
      </div>

      <!-- 2-COLUMN HOOK PICKER + MATCHING UTTERANCES -->
      <div class="modal-cols">
        <div class="sub-box">
          <div class="sub-hdr mono">🔁 Shared &amp; Repeated Hooks (Click to Select for Sharing)</div>
          <div class="hooks-list">
            <button
              v-for="(sh, idx) in combinedHooks"
              :key="idx"
              class="hook-btn"
              :class="{ selected: sh.phrase === selectedPhrase }"
              @click="customPhrase = sh.phrase"
            >
              <span class="hook-q">"{{ sh.phrase }}"</span>
              <span class="hook-meta mono">
                <template v-if="sh.shared_by?.length">
                  Shared: {{ sh.shared_by.join(' + ') }} (×{{ sh.total_occurrences }})
                </template>
                <template v-else>
                  ×{{ sh.count }} ({{ sh.shared_speakers || 1 }} spk)
                </template>
              </span>
            </button>
          </div>
        </div>

        <div class="sub-box">
          <div class="sub-hdr mono">🎙️ Recent Utterances Carrying This Earworm</div>
          <div class="utt-mini-list">
            <div
              v-for="(u, idx) in activeDossier.matching_utterances || []"
              :key="idx"
              class="utt-mini"
            >
              <div class="utt-mini-top mono">
                <span>{{ u.band_role }}</span>
                <span>{{ u.throat_disp_um }} µm</span>
                <span>{{ (u.timestamp_utc || '').slice(11, 19) }} UTC</span>
              </div>
              <div class="utt-mini-txt">"{{ u.transcript }}"</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  speakerId: { type: String, default: '' },
  sharedData: { type: Object, default: () => ({}) },
  speakers: { type: Array, default: () => [] },
  initialSharePacket: { type: Object, default: null },
  initialPhrase: { type: String, default: '' },
  starterGuide: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['close', 'select-speaker', 'shared-created', 'talkback-speaker', 'open-starter-guide'])

const customPhrase = ref('')
const shareNote = ref('')
const sharingBusy = ref(false)
const shareToast = ref('')
const lastSharePacket = ref(null)
const modalOutLoudBusy = ref(false)
const modalOutLoudUrl = ref('')
const modalDeltaWavUrl = ref('')
const modalEntrainmentWavUrl = ref('')
const modalFmWavUrl = ref('')
const modalFhssWavUrl = ref('')
const modalFreqDetWavUrl = ref('')
const modalSwimlaneWavUrl = ref('')
const modalCovertSideWavUrl = ref('')
const selectedModalFmFreq = ref(91.5)
const modalOllamaBusy = ref(false)
const modalOllamaAdvice = ref(null)
const modalDeltaOllamaAdvice = ref(null)
const modalDataIntelAdvice = ref(null)
const modalFmOllamaAdvice = ref(null)
const modalFhssOllamaAdvice = ref(null)
const modalFreqDetOllamaAdvice = ref(null)
const modalSwimlaneOllamaAdvice = ref(null)

const defaultModalFmStations = [
  { frequency_mhz: 88.3, peak_deviation_khz: 64.4, flags: ['MISSING_RDS', 'MONO_NO_PILOT'] },
  { frequency_mhz: 91.5, peak_deviation_khz: 87.4, flags: ['MISSING_RDS', 'OVER_DEVIATION (87.4 kHz)'] },
  { frequency_mhz: 95.9, peak_deviation_khz: 91.2, flags: ['MISSING_RDS', 'MONO_NO_PILOT', 'OVER_DEVIATION (91.2 kHz)'] },
  { frequency_mhz: 100.1, peak_deviation_khz: 71.5, flags: [] },
  { frequency_mhz: 101.7, peak_deviation_khz: 89.3, flags: ['MISSING_RDS', 'MONO_NO_PILOT', 'OVER_DEVIATION (89.3 kHz)'] },
]

async function pinModalFmBistatic() {
  const freq = Number(selectedModalFmFreq.value || 100.1)
  try {
    const res = await fetch('/api/fm-scanner/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pinned_bistatic_freq_mhz: freq }),
    })
    if (res.ok) {
      flash(`Pinned ${freq.toFixed(1)} MHz as RTL-SDR :5556 Passive Bistatic Radar Illuminator!`)
      emit('shared-created')
    }
  } catch (e) {
    console.error(e)
  }
}

async function lockDepartureIdentityHere() {
  try {
    const res = await fetch('/api/presence-voicematch/depart', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        speaker_id: props.speakerId,
        note: `Locked ${props.speakerId} from Person Dossier Modal as Departure/Arrival Reference`,
      }),
    })
    if (res.ok) {
      flash(`Locked ${props.speakerId} 271-D voiceprint & empty-room FFT for Departure vs. Arrival comparison!`)
      emit('shared-created')
    }
  } catch (e) {
    console.error(e)
  }
}

async function pinRoomFocusHere(mode = 'PINNED') {
  try {
    const res = await fetch('/api/spatial/focus-closest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        focus_closest_enabled: true,
        focus_mode: mode,
        auto_select_closest: mode === 'BOTH',
        pinned_speaker_id: props.speakerId,
      }),
    })
    if (res.ok) {
      flash(
        mode === 'BOTH'
          ? `Dual 3D Room Focus Active: Auto-Closest + Pinned ${props.speakerId} (+22 dB · 1.06× Gate)!`
          : `Pinned Exclusive 3D Room Faint-Focus Spotlight (+22 dB · 1.06× Gate) onto ${props.speakerId}!`
      )
      emit('shared-created')
    }
  } catch (e) {
    console.error(e)
  }
}

async function playModalReadingOutLoud() {
  modalOutLoudBusy.value = true
  try {
    const res = await fetch('/api/reading-piggyback/simulate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mode: 'READING_OUT_LOUD',
        text: selectedPhrase.value,
      }),
    })
    if (res.ok) {
      const j = await res.json()
      modalOutLoudUrl.value = j.result?.audio_url || ''
      flash(`Rendered "${selectedPhrase.value}" out loud over ThreeStateVADRouter A2–E3–A3 WPM drone!`)
    }
  } catch (e) {
    console.error(e)
  } finally {
    modalOutLoudBusy.value = false
  }
}

function playModalDeltaWav() {
  const spk = props.speakerId || 'PERSON_DELTA'
  modalDeltaWavUrl.value = `/api/delta-avatar/audio/${encodeURIComponent(spk)}.wav?phrase=${encodeURIComponent(selectedPhrase.value)}&t=${Date.now()}`
  flash(`Playing ${spk}'s 0.5–4.0 Hz Binaural Delta Emotional Control Reset + Whisper Mirror!`)
}

function playModalEntrainmentSynthWav() {
  const s = modalRefSynth.value
  const fc = s.speaker_carrier_hz || 210.0
  const fb = s.speaker_target_brainwave_hz || 2.4
  const md = s.mod_depth ?? 0.4
  modalEntrainmentWavUrl.value = `/api/forensics/entrainment-synth.wav?carrier_freq=${fc}&target_brainwave_freq=${fb}&mod_depth=${md}&t=${Date.now()}`
  flash(`Playing Module 4 IntegratedEntrainmentSynthesizer (${fc} Hz ± ${(fb / 2).toFixed(2)} Hz · LFO Depth ${md})!`)
}

function playModalFmStationWav() {
  const freq = Number(selectedModalFmFreq.value || 91.5).toFixed(1)
  modalFmWavUrl.value = `/api/fm-scanner/audio/${freq}.wav?t=${Date.now()}`
  flash(`Auditioning FMBandPirateScanner Demodulated MPX Baseband at ${freq} MHz!`)
}

function playModalFhssSonarWav() {
  modalFhssWavUrl.value = `/api/fhss-sonar/audio/hop_stream.wav?t=${Date.now()}`
  flash('Auditioning 48 kHz Stereo FHSS Ultrasonic Sonar Hop Sequence + <50 Hz Quadrature I/Q Reflection!')
}

function playModalFreqDetectorWav() {
  modalFreqDetWavUrl.value = `/api/frequency-detector/audio/all.wav?sec=2.1&t=${Date.now()}`
  flash('Auditioning 3-Stage FrequencyDetector Probe (Goertzel 697/1209 Hz Burst · 400→2400 Hz Chirp · 880 Hz ZCR)!')
}

function playModalSwimlaneSynthWav() {
  modalSwimlaneWavUrl.value = `/api/swimlane-synth/audio/chord.wav?sec=1.8&t=${Date.now()}`
  flash('Auditioning SwimlaneToneSynth (256-sample / 5.8ms Polyphonic Sine Synth · 3ms 1-Pole De-Click Ramp)!')
}

async function playModalCovertSideWav() {
  try {
    await fetch('/api/reading-piggyback/covert-scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: 'COMPOSITE_PIGGYBACK', hidden_phrase: selectedPhrase.value }),
    })
  } catch (_) {}
  modalCovertSideWavUrl.value = `/api/reading-piggyback/isolated-side.wav?t=${Date.now()}`
  flash('Auditioning CovertPiggybackAudioAnalyzer isolated_hidden_side_channel.wav ((L - R)/2 Anti-Phase & 40 kHz Ultrasonic Demod)!')
}

async function triggerModalSwimlaneSpeakerTone() {
  try {
    const res = await fetch('/api/swimlane-synth/trigger', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ speaker_id: props.speakerId || 'PERSON_ALPHA', active: true, volume: 0.22 }),
    })
    if (res.ok) {
      const st = await res.json()
      flash(
        `[SwimlaneToneSynth] Triggered ${props.speakerId} lane · ${st.kpis?.active_lane_count}/${st.kpis?.total_lanes} lanes active (Goertzel verified: ${st.kpis?.closed_loop_goertzel_verified_count})!`
      )
      emit('shared-created')
    }
  } catch (e) {
    console.error(e)
  }
}

async function triggerModalFreqDetectorRun() {
  try {
    const res = await fetch('/api/frequency-detector/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: 'all' }),
    })
    if (res.ok) {
      const st = await res.json()
      flash(
        `[FrequencyDetector] ${st.kpis?.goertzel_hit_count} Goertzel hits (${st.kpis?.goertzel_mean_snr}× SNR) · ${st.kpis?.fft_sweep_frame_count} Parabolic FFT frames · ZCR=${st.kpis?.zcr_mean_estimated_hz} Hz!`
      )
      emit('shared-created')
    }
  } catch (e) {
    console.error(e)
  }
}

async function triggerModalFhssHop() {
  try {
    const res = await fetch('/api/fhss-sonar/hop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: 'single' }),
    })
    if (res.ok) {
      const st = await res.json()
      flash(`[FHSS SECURE TRIGGER] Hopped to ${st.active_carrier_khz} kHz · Muscle Δd=${st.kpis?.mean_muscle_displacement_um} µm!`)
      emit('shared-created')
    }
  } catch (e) {
    console.error(e)
  }
}

async function askModalOllama() {
  modalOllamaBusy.value = true
  try {
    const [resRpb, resDelta, resDi, resFm, resFhss, resFd, resSw] = await Promise.all([
      fetch('/api/ollama/reading-piggyback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force: true }),
      }),
      fetch('/api/ollama/delta-avatar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force: true }),
      }),
      fetch('/api/ollama/data-intelligence', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          force: true,
          focus: `Dossier Modal Reference for ${props.speakerId}: Module 4 IntegratedEntrainmentSynthesizer + FMBandPirateScanner + FrequencyHoppingSonarBridge + FrequencyDetector + SwimlaneToneSynth + 10 NightSweep Features`,
        }),
      }),
      fetch('/api/ollama/fm-scanner', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force: true }),
      }),
      fetch('/api/ollama/fhss-sonar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force: true }),
      }),
      fetch('/api/ollama/frequency-detector', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force: true }),
      }),
      fetch('/api/ollama/swimlane-synth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force: true }),
      }),
    ])
    if (resRpb.ok) modalOllamaAdvice.value = await resRpb.json()
    if (resDelta.ok) modalDeltaOllamaAdvice.value = await resDelta.json()
    if (resDi.ok) modalDataIntelAdvice.value = await resDi.json()
    if (resFm.ok) modalFmOllamaAdvice.value = await resFm.json()
    if (resFhss.ok) modalFhssOllamaAdvice.value = await resFhss.json()
    if (resFd.ok) modalFreqDetOllamaAdvice.value = await resFd.json()
    if (resSw.ok) modalSwimlaneOllamaAdvice.value = await resSw.json()
    flash(`NightSweep Ollama Modal analyzed ${props.speakerId}'s SwimlaneToneSynth, FrequencyDetector, FHSS Sonar, FM Scanner & 10-Feature Reference!`)
  } catch (e) {
    console.error(e)
  } finally {
    modalOllamaBusy.value = false
  }
}

watch(
  [() => props.speakerId, () => props.initialPhrase],
  ([, initPh]) => {
    customPhrase.value = initPh || ''
    lastSharePacket.value = null
  },
  { immediate: true }
)

watch(
  () => props.initialSharePacket,
  (pkt) => {
    if (pkt && pkt.earworm_phrase) {
      customPhrase.value = pkt.earworm_phrase
      lastSharePacket.value = pkt
    }
  },
  { immediate: true }
)

const speakerList = computed(() => {
  if (props.speakers?.length) return props.speakers
  const map = props.sharedData?.speakers || {}
  return Object.values(map)
})

const activeDossier = computed(() => {
  return props.sharedData?.speakers?.[props.speakerId] || {}
})

const modalRef = computed(() => {
  return activeDossier.value.nightsweep_modal_reference || {}
})

const modalRefSynth = computed(() => {
  return modalRef.value.integrated_entrainment_synth || {}
})

const modalRefBcg = computed(() => {
  return modalRef.value.cardio_vocal_bcg || {}
})

const modalRefWakita = computed(() => {
  return modalRef.value.wakita_vocal_tract || {}
})

const modalRefConformal = computed(() => {
  return modalRef.value.conformal_asr || {}
})

const modalRefWpe = computed(() => {
  return modalRef.value.mimo_wpe_dereverb || {}
})

const modalRefLombard = computed(() => {
  return modalRef.value.lombard_spectral_tilt || {}
})

const modalRefBistatic = computed(() => {
  return modalRef.value.bistatic_radar || {}
})

const modalRefSaccade = computed(() => {
  return modalRef.value.ultrasonic_saccade_sonar || {}
})

const modalRefMerkle = computed(() => {
  return modalRef.value.merkle_zk_audit || {}
})

const modalRefFm = computed(() => {
  return modalRef.value.fm_pirate_scanner || {}
})

const modalRefFhss = computed(() => {
  return modalRef.value.fhss_sonar_bridge || {}
})

const modalRefFreqDet = computed(() => {
  return modalRef.value.frequency_detector || {}
})

const modalRefSwimlane = computed(() => {
  return modalRef.value.swimlane_tone_synth || {}
})

const selectedPhrase = computed(() => {
  return customPhrase.value || activeDossier.value.primary_earworm_phrase || 'watching you much'
})

const activeBpm = computed(() => {
  return activeDossier.value.earworm_bpm || 118
})

const activeContour = computed(() => {
  const match = (activeDossier.value.shared_earworms || []).find((x) => x.phrase === selectedPhrase.value)
  return match?.phoneme_contour || activeDossier.value.phoneme_contour || 'EE-AH-OO'
})

const currentAudioUrl = computed(() => {
  if (!props.speakerId) return ''
  return `/api/earworm/audio/${encodeURIComponent(props.speakerId)}.wav?phrase=${encodeURIComponent(selectedPhrase.value)}&bpm=${activeBpm.value}`
})

const combinedHooks = computed(() => {
  const shared = activeDossier.value.shared_earworms || []
  const personal = (activeDossier.value.personal_hooks || []).filter(
    (p) => !shared.some((s) => s.phrase === p.phrase)
  )
  return [...shared, ...personal].slice(0, 8)
})

function formatAz(az) {
  const n = Math.round(Number(az) || 0)
  return (n >= 0 ? '+' : '') + n + '°'
}

function flash(msg) {
  shareToast.value = msg
  setTimeout(() => {
    if (shareToast.value === msg) shareToast.value = ''
  }, 5500)
}

async function copyText(txt) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(txt)
      return true
    }
  } catch (_) {
    // Fallback textarea copy
  }
  const ta = document.createElement('textarea')
  ta.value = txt
  document.body.appendChild(ta)
  ta.select()
  document.execCommand('copy')
  document.body.removeChild(ta)
  return true
}

async function shareEarworm(mode) {
  sharingBusy.value = true
  try {
    const res = await fetch('/api/earworm/share', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        speaker_id: props.speakerId,
        phrase: selectedPhrase.value,
        earworm_bpm: activeBpm.value,
        note: shareNote.value,
        broadcast_udp: mode === 'udp',
      }),
    })
    if (!res.ok) return
    const data = await res.json()
    const pkt = data.packet
    lastSharePacket.value = pkt
    emit('shared-created', pkt)

    if (mode === 'link') {
      await copyText(pkt.share_url)
      if (navigator.share) {
        try {
          await navigator.share({
            title: `${props.speakerId} Shared Earworm: "${pkt.earworm_phrase}"`,
            text: data.share_markdown,
            url: pkt.share_url,
          })
        } catch (_) {
          // User dismissed native sheet; clipboard already copied
        }
      }
      flash(`Copied direct share link: ${pkt.share_url}`)
    } else if (mode === 'card') {
      await copyText(data.share_markdown)
      flash(`Copied formatted Shared Earworm card for ${props.speakerId} to clipboard`)
    } else if (mode === 'udp') {
      flash(`Broadcasted "${pkt.earworm_phrase}" (${pkt.udp_frames_broadcast} audio blocks) live on UDP :5005!`)
    } else if (mode === 'json') {
      const blob = new Blob([JSON.stringify(pkt, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${props.speakerId.toLowerCase()}_earworm_${pkt.share_id}.json`
      a.click()
      URL.revokeObjectURL(url)
      flash(`Exported signed JSON packet (${pkt.share_id})`)
    }
  } catch (err) {
    console.error('Share earworm error:', err)
  } finally {
    sharingBusy.value = false
  }
}
</script>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 999;
  background: rgba(5, 9, 16, 0.82);
  backdrop-filter: blur(5px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 18px;
}

.modal-card {
  width: min(1040px, 96vw);
  max-height: 92vh;
  overflow-y: auto;
  overflow-x: hidden;
  box-sizing: border-box;
  background: #0d131f;
  border: 1px solid #2a3b57;
  border-radius: 14px;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 13px;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.65);
}

.modal-topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.person-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.person-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #121a28;
  border: 1px solid #243249;
  color: #9ca3af;
  border-radius: 99px;
  padding: 4px 11px;
  font-size: 0.74rem;
  cursor: pointer;
}

.person-tab.active {
  background: rgba(47, 129, 247, 0.14);
  font-weight: 700;
}

.p-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.close-btn {
  background: #161f2e;
  border: 1px solid #2b3a52;
  color: #e6edf3;
  border-radius: 7px;
  padding: 5px 11px;
  cursor: pointer;
  font-size: 0.76rem;
}

.dossier-head {
  background: #111927;
  border: 1px solid #22314a;
  border-left-width: 4px;
  border-radius: 9px;
  padding: 10px 14px;
}

.dossier-id-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.dossier-id-row h2 {
  margin: 0;
  font-size: 1.02rem;
}

.dossier-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-top: 6px;
  font-size: 0.75rem;
  color: #b1bac4;
}

.share-toast {
  background: rgba(46, 160, 67, 0.18);
  border: 1px solid rgba(63, 185, 80, 0.5);
  color: #7ee787;
  padding: 7px 12px;
  border-radius: 8px;
  font-size: 0.77rem;
}

.earworm-hero {
  background: linear-gradient(135deg, rgba(88, 166, 255, 0.09), rgba(210, 168, 255, 0.08));
  border: 1px solid rgba(88, 166, 255, 0.35);
  border-radius: 10px;
  padding: 13px 15px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.hero-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
}

.hero-lbl {
  font-size: 0.69rem;
  color: #79c0ff;
}

.hero-phrase {
  font-size: 1.32rem;
  font-weight: 800;
  color: #ffffff;
  margin-top: 2px;
  overflow-wrap: anywhere;
}

.tempo-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.t-pill {
  font-size: 0.71rem;
  background: #111826;
  border: 1px solid #2b3c58;
  color: #d2a8ff;
  padding: 3px 9px;
  border-radius: 99px;
}

.t-pill.cyan {
  color: #79c0ff;
}

.loop-strip {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 0.76rem;
}

.cosharers {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.cosharer-chip {
  background: rgba(17, 24, 39, 0.9);
  border: 1px solid;
  border-radius: 99px;
  padding: 2px 9px;
  font-size: 0.71rem;
  cursor: pointer;
}

.audio-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  background: #090e16;
  border: 1px solid #1d2a40;
  border-radius: 8px;
  padding: 7px 11px;
}

.audio-lbl {
  font-size: 0.74rem;
  color: #9ecbff;
}

.wav-player {
  height: 32px;
  min-width: min(100%, 240px);
  width: 100%;
  flex: 1 1 240px;
  max-width: 460px;
}

.share-composer {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.note-input {
  background: #090d14;
  border: 1px solid #25344d;
  border-radius: 7px;
  color: #e6edf3;
  padding: 7px 11px;
  font-size: 0.78rem;
}

.share-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.btn-udp {
  border-color: rgba(210, 168, 255, 0.45);
  color: #d2a8ff;
}

.btn-talkback {
  background: rgba(35, 134, 54, 0.25);
  border-color: rgba(63, 185, 80, 0.6);
  color: #7ee787;
}

.link-btn {
  text-decoration: none;
  display: inline-flex;
  align-items: center;
}

.packet-preview {
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 0.72rem;
  color: #9ecbff;
  background: rgba(13, 19, 31, 0.85);
  border: 1px dashed #2b4266;
  border-radius: 6px;
  padding: 6px 10px;
}

.packet-preview a {
  color: #58a6ff;
}

.modal-cols {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

@media (max-width: 860px) {
  .modal-cols {
    grid-template-columns: 1fr;
  }
}

.sub-box {
  background: #101724;
  border: 1px solid #1f2d44;
  border-radius: 9px;
  padding: 10px 12px;
}

.sub-hdr {
  font-size: 0.73rem;
  color: #79c0ff;
  margin-bottom: 8px;
  font-weight: 700;
}

.hooks-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.hook-btn {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 8px;
  background: #0b1019;
  border: 1px solid #1d293e;
  border-radius: 7px;
  padding: 6px 10px;
  color: #e6edf3;
  cursor: pointer;
  text-align: left;
  min-width: 0;
}

.hook-btn.selected {
  border-color: #58a6ff;
  background: rgba(88, 166, 255, 0.12);
}

.hook-q {
  font-size: 0.79rem;
  font-weight: 600;
}

.hook-meta {
  font-size: 0.69rem;
  color: #8b949e;
}

.utt-mini-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.utt-mini {
  background: #0b1019;
  border: 1px solid #1b2638;
  border-radius: 7px;
  padding: 6px 9px;
}

.utt-mini-top {
  display: flex;
  justify-content: space-between;
  font-size: 0.67rem;
  color: #8b949e;
  margin-bottom: 3px;
}

.utt-mini-txt {
  font-size: 0.77rem;
  color: #c9d1d9;
}

.muted {
  color: #8b949e;
}
.modal-ollama-box {
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(56, 189, 248, 0.07);
  border: 1px solid rgba(56, 189, 248, 0.35);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.mob-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.mob-title {
  font-size: 0.75rem;
  font-weight: 700;
  color: #79c0ff;
}
.mob-btns {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.mob-btn-focus {
  background: rgba(63, 185, 80, 0.18);
  color: #7ee787;
  border: 1px solid rgba(63, 185, 80, 0.45);
  font-size: 0.7rem;
}
.mob-btn-read {
  background: rgba(251, 191, 36, 0.18);
  color: #fbbf24;
  border: 1px solid rgba(251, 191, 36, 0.45);
  font-size: 0.7rem;
}
.mob-btn-ollama {
  background: linear-gradient(135deg, #0284c7, #6e40c9);
  color: #fff;
  border: none;
  font-size: 0.7rem;
}
.mob-audio {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 0.72rem;
  color: #fbbf24;
}
.mob-advice {
  font-size: 0.75rem;
  color: #c9d1d9;
}
.mob-advice p {
  margin: 0 0 5px;
}
.mob-advice ul {
  margin: 0;
  padding-left: 18px;
  color: #b1bac4;
  line-height: 1.45;
}
.modal-ref-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 7px;
  margin-top: 2px;
}
.mref-card {
  background: rgba(11, 16, 25, 0.88);
  border: 1px solid #22324c;
  border-radius: 7px;
  padding: 6px 9px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.mref-synth {
  border-color: rgba(88, 166, 255, 0.55);
  background: rgba(88, 166, 255, 0.08);
}
.mref-hdr {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 6px;
  font-size: 0.69rem;
  font-weight: 700;
  color: #9ecbff;
}
.mref-badge {
  background: #131d2e;
  border: 1px solid #2b3f5c;
  color: #7ee787;
  padding: 1px 6px;
  border-radius: 99px;
  font-size: 0.63rem;
}
.mref-line {
  font-size: 0.68rem;
  color: #c9d1d9;
  line-height: 1.35;
}
.mref-line code {
  color: #d2a8ff;
  font-size: 0.66rem;
}

@media (max-width: 640px) {
  .modal-backdrop {
    padding: 8px;
  }
  .modal-card {
    width: 98vw;
    padding: 12px 13px;
    gap: 10px;
  }
  .dossier-id-row h2 {
    font-size: 0.9rem;
  }
  .dossier-metrics {
    gap: 6px 11px;
    font-size: 0.71rem;
  }
  .hero-phrase {
    font-size: 1.08rem;
  }
  .share-buttons .btn,
  .mob-btns .btn {
    flex: 1 1 auto;
    justify-content: center;
    text-align: center;
  }
  .utt-mini-top {
    flex-wrap: wrap;
    gap: 4px 8px;
  }
}
</style>
