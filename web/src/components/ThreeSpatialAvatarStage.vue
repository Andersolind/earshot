<template>
  <div class="three-stage-wrap">
    <!-- TOP CAMERA & LEGEND OVERLAY -->
    <div class="stage-toolbar mono">
      <div class="st-left">
        <span class="engine-chip">
          🧊 {{ webglActive ? 'Three.js WebGL 3D Room' : 'Three.js 3D Perspective Stage' }}
        </span>
        <span
          class="vad-chip"
          :class="'vad-' + (threeStateVad.state || 'STANDBY').toLowerCase()"
        >
          3-State VAD: {{ threeStateVad.state || 'STANDBY' }}
          <template v-if="threeStateVad.state === 'READING'">
            (~{{ threeStateVad.last_wpm || 200 }} WPM · A2-E3-A3)
          </template>
        </span>
        <span v-if="closestFocus?.enabled && (focusMode === 'AUTO' || focusMode === 'BOTH')" class="focus-chip">
          🎯 Closest: {{ closestFocus.closest_speaker_id || closestFocus.locked_speaker_id }} ({{ closestFocus.closest_range_m ?? closestFocus.locked_range_m }}m · +{{ closestFocus.faint_makeup_gain_db }}dB)
        </span>
        <span v-if="closestFocus?.enabled && (focusMode === 'PINNED' || focusMode === 'BOTH') && closestFocus.pinned_speaker_id" class="pin-chip">
          📌 Pinned: {{ closestFocus.pinned_speaker_id }} ({{ closestFocus.pinned_range_m ?? 0.72 }}m)
        </span>
      </div>
      <div class="st-right">
        <button type="button" class="cam-btn mono" :class="{ active: camPreset === 'iso' }" @click="setCameraPreset('iso')">
          Iso 3D
        </button>
        <button type="button" class="cam-btn mono" :class="{ active: camPreset === 'top' }" @click="setCameraPreset('top')">
          Top-Down
        </button>
        <button type="button" class="cam-btn mono" :class="{ active: camPreset === 'closest' }" @click="setCameraPreset('closest')">
          🎯 Closest POV
        </button>
        <button
          v-if="closestFocus?.pinned_speaker_id"
          type="button"
          class="cam-btn mono"
          :class="{ active: camPreset === 'pinned' }"
          @click="setCameraPreset('pinned')"
        >
          📌 Pinned POV
        </button>
      </div>
    </div>

    <!-- 3D VIEWPORT CONTAINER + PROJECTED CLICKABLE AVATAR LABELS -->
    <div
      ref="viewportRef"
      class="three-viewport"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointerleave="onPointerUp"
      @wheel.prevent="onWheel"
    >
      <canvas ref="canvasRef" class="three-canvas"></canvas>

      <!-- Floating Projected 3D->2D Clickable Avatar Nameplates -->
      <button
        v-for="lbl in projectedLabels"
        :key="lbl.speaker_id"
        type="button"
        class="avatar-label mono"
        :class="{ 'is-closest': lbl.isClosest, 'is-pinned': lbl.isPinned, 'is-nonvocal': lbl.nonVocal }"
        :style="{
          left: lbl.x + 'px',
          top: lbl.y + 'px',
          borderColor: lbl.isPinned ? '#a371f7' : lbl.isClosest ? '#3fb950' : lbl.color,
          color: lbl.color,
        }"
        :title="`Click to inspect ${lbl.speaker_id}'s Earworm & Biometric Dossier`"
        @click.stop="$emit('select-speaker', lbl.speaker_id)"
      >
        <span class="al-top">
          <span>{{ lbl.icon }} {{ lbl.speaker_id }}</span>
          <span v-if="lbl.isClosest" class="closest-tag">CLOSEST</span>
          <span v-if="lbl.isPinned" class="pinned-tag">PINNED</span>
        </span>
        <span class="al-sub">
          {{ lbl.range_m }}m · {{ formatAz(lbl.azimuth_deg) }}
          <template v-if="!lbl.nonVocal"> · {{ Math.round(lbl.wph || 0) }} WPH</template>
        </span>
      </button>

      <!-- Sensor Origin Badge -->
      <div
        v-if="originScreen.visible"
        class="origin-tag mono"
        :style="{ left: originScreen.x + 'px', top: originScreen.y + 'px' }"
      >
        🎙️ UltraMic384K + 📡 RTL-SDR (0,0,0)
      </div>

      <div class="orbit-hint mono">
        Drag to Orbit · Scroll to Zoom · Click any 3D Avatar to Inspect &amp; Share Earworm
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import * as THREE from 'three'

const props = defineProps({
  targets: { type: Array, default: () => [] },
  roomCriticalDist: { type: Number, default: 1.45 },
  gateOpen: { type: Boolean, default: false },
  typistSector: { type: Object, default: () => ({}) },
  closestFocus: { type: Object, default: () => ({}) },
  threeStateVad: { type: Object, default: () => ({}) },
})

const focusMode = computed(() => String(props.closestFocus?.focus_mode || 'BOTH').toUpperCase())

const emit = defineEmits(['select-speaker'])

const viewportRef = ref(null)
const canvasRef = ref(null)
const webglActive = ref(true)
const camPreset = ref('iso')
const projectedLabels = ref([])
const originScreen = reactive({ x: 240, y: 270, visible: true })

const NON_VOCAL_SET = new Set([
  'PERSON_TYPIST',
  'DEVICE_CELLPHONE',
  'DEVICE_MEMS',
  'OTHER_ROOM_SUBLEVEL',
])

const isSnapshot =
  typeof window !== 'undefined' && window.location.search.includes('snapshot=1')

// Spherical orbit camera state around target (tx, ty, tz)
const camOrbit = reactive({
  yaw: 0.24,
  pitch: 0.62,
  radius: 5.15,
  tx: 0.0,
  ty: 0.45,
  tz: -1.15,
})

let dragging = false
let dragMoved = false
let lastPtrX = 0
let lastPtrY = 0
let rafId = null
let resizeObs = null
let animPhase = 0

// Three.js core objects
let renderer = null
let scene = null
let camera = null
let raycaster = null
let dynamicGroup = null
let avatarPickMeshes = []

function avatarIcon(id) {
  if (id === 'PERSON_TYPIST') return '⌨️'
  if (id === 'DEVICE_CELLPHONE') return '📱'
  if (id === 'DEVICE_MEMS') return '🔬'
  if (id === 'OTHER_ROOM_SUBLEVEL') return '🧱'
  return '🎧'
}

function formatAz(az) {
  const n = Math.round(Number(az) || 0)
  return (n >= 0 ? '+' : '') + n + '°'
}

// Convert GNU-Larex polar coordinates (range_m, azimuth_deg) into 3D room coordinates:
// Sensor array sits at (0, 0, 0); forward (+Y in 2D radar) maps to -Z into the room; +azimuth maps to +X right.
function polarToRoom3D(rangeM, azDeg) {
  const r = Math.min(3.85, Math.max(0.22, Number(rangeM) || 1.0))
  const rad = ((Number(azDeg) || 0) * Math.PI) / 180
  return {
    x: r * Math.sin(rad),
    z: -r * Math.cos(rad),
    r,
    rad,
  }
}

function setCameraPreset(preset) {
  camPreset.value = preset
  if (preset === 'iso') {
    camOrbit.yaw = 0.24
    camOrbit.pitch = 0.62
    camOrbit.radius = 5.15
    camOrbit.tx = 0.0
    camOrbit.ty = 0.45
    camOrbit.tz = -1.15
  } else if (preset === 'top') {
    camOrbit.yaw = 0.0
    camOrbit.pitch = 1.38
    camOrbit.radius = 5.6
    camOrbit.tx = 0.0
    camOrbit.ty = 0.1
    camOrbit.tz = -1.45
  } else if (preset === 'closest' || preset === 'pinned') {
    const targetId =
      preset === 'pinned'
        ? props.closestFocus?.pinned_speaker_id
        : props.closestFocus?.closest_speaker_id || props.closestFocus?.locked_speaker_id
    const locked = (props.targets || []).find((t) => t.speaker_id === targetId) || props.targets?.[0]
    if (locked) {
      const p = polarToRoom3D(locked.range_m, locked.azimuth_deg)
      camOrbit.tx = p.x * 0.75
      camOrbit.ty = 0.52
      camOrbit.tz = p.z * 0.75
      camOrbit.yaw = p.rad * 0.55
      camOrbit.pitch = 0.48
      camOrbit.radius = Math.max(2.35, p.r + 1.85)
    }
  }
  syncCameraTransform()
  renderOnce()
}

function syncCameraTransform() {
  if (!camera) return
  const cp = Math.cos(camOrbit.pitch)
  const sp = Math.sin(camOrbit.pitch)
  camera.position.set(
    camOrbit.tx + camOrbit.radius * cp * Math.sin(camOrbit.yaw),
    camOrbit.ty + camOrbit.radius * sp,
    camOrbit.tz + camOrbit.radius * cp * Math.cos(camOrbit.yaw)
  )
  camera.lookAt(camOrbit.tx, camOrbit.ty, camOrbit.tz)
  camera.updateMatrixWorld()
}

function createArcCurvePoints(radius, startDeg, endDeg, y = 0.01, segments = 48) {
  const pts = []
  for (let i = 0; i <= segments; i++) {
    const deg = startDeg + ((endDeg - startDeg) * i) / segments
    const rad = (deg * Math.PI) / 180
    pts.push(new THREE.Vector3(radius * Math.sin(rad), y, -radius * Math.cos(rad)))
  }
  return pts
}

function rebuildThreeScene() {
  if (!scene || !dynamicGroup) return
  while (dynamicGroup.children.length > 0) {
    const ch = dynamicGroup.children.pop()
    dynamicGroup.remove(ch)
  }
  avatarPickMeshes = []

  // 1. Concentric range arcs (1m, 2m, 3m, 4m) + azimuth rays
  for (const r of [1, 2, 3, 4]) {
    const geom = new THREE.BufferGeometry().setFromPoints(createArcCurvePoints(r, -82, 82, 0.012, 56))
    const mat = new THREE.LineBasicMaterial({ color: 0x24364f, transparent: true, opacity: 0.85 })
    dynamicGroup.add(new THREE.Line(geom, mat))
  }
  for (const ang of [-60, -30, 0, 30, 60]) {
    const pEnd = polarToRoom3D(3.85, ang)
    const gRay = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(0, 0.01, 0),
      new THREE.Vector3(pEnd.x, 0.01, pEnd.z),
    ])
    dynamicGroup.add(
      new THREE.Line(gRay, new THREE.LineBasicMaterial({ color: 0x1a283b, transparent: true, opacity: 0.8 }))
    )
  }

  // 2. Calibrated Room Critical Distance r_c Ring (Sabine Direct = Reverb boundary)
  const rc = Math.min(3.5, Math.max(0.5, Number(props.roomCriticalDist) || 1.45))
  const rcGeom = new THREE.BufferGeometry().setFromPoints(createArcCurvePoints(rc, -82, 82, 0.022, 64))
  dynamicGroup.add(
    new THREE.Line(rcGeom, new THREE.LineBasicMaterial({ color: 0xf0883e, transparent: true, opacity: 0.9 }))
  )

  // 3. Outer Room Wall Boundary Arc (3.18m) separating interior avatars from OTHER_ROOM_SUBLEVEL
  const wallPts = createArcCurvePoints(3.18, -78, 78, 0.0, 48)
  const wallShapeGeom = new THREE.CylinderGeometry(3.18, 3.18, 0.95, 48, 1, true, Math.PI - 1.35, 2.7)
  const wallMat = new THREE.MeshPhongMaterial({
    color: 0x1e3a5f,
    transparent: true,
    opacity: 0.13,
    side: THREE.DoubleSide,
    depthWrite: false,
  })
  const wallMesh = new THREE.Mesh(wallShapeGeom, wallMat)
  wallMesh.position.y = 0.475
  dynamicGroup.add(wallMesh)
  dynamicGroup.add(
    new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(wallPts.map((p) => new THREE.Vector3(p.x, 0.95, p.z))),
      new THREE.LineBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.35 })
    )
  )

  // 4. PERSON_TYPIST 3D Desk Sector Wedge
  const ts = props.typistSector || {}
  if (ts.spatial_sector_lock !== false) {
    const dAz = Number(ts.desk_azimuth_deg ?? -8)
    const dRng = Math.min(2.1, Math.max(0.45, Number(ts.desk_range_m ?? 0.62) + 0.25))
    const dHyst = Number(ts.directional_hysteresis_deg ?? 22)
    const arcPts = createArcCurvePoints(dRng, dAz - dHyst, dAz + dHyst, 0.018, 24)
    const shapePts = [new THREE.Vector3(0, 0.018, 0), ...arcPts, new THREE.Vector3(0, 0.018, 0)]
    dynamicGroup.add(
      new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(shapePts),
        new THREE.LineBasicMaterial({ color: 0x2dd4bf, transparent: true, opacity: 0.78 })
      )
    )
  }

  // 5. Sensor Origin Tower at (0, 0, 0)
  const towerGrp = new THREE.Group()
  const baseCyl = new THREE.Mesh(
    new THREE.CylinderGeometry(0.14, 0.19, 0.12, 24),
    new THREE.MeshStandardMaterial({ color: 0x1f2d42, metalness: 0.6, roughness: 0.3 })
  )
  baseCyl.position.y = 0.06
  towerGrp.add(baseCyl)
  const mast = new THREE.Mesh(
    new THREE.CylinderGeometry(0.03, 0.04, 0.42, 16),
    new THREE.MeshStandardMaterial({ color: 0x58a6ff, emissive: 0x1d4ed8, emissiveIntensity: 0.45 })
  )
  mast.position.y = 0.27
  towerGrp.add(mast)
  const capsule = new THREE.Mesh(
    new THREE.SphereGeometry(0.075, 20, 20),
    new THREE.MeshStandardMaterial({ color: 0x79c0ff, emissive: 0x38bdf8, emissiveIntensity: 0.75 })
  )
  capsule.position.y = 0.50
  towerGrp.add(capsule)
  dynamicGroup.add(towerGrp)

  // 6. Closest-Identity & Pinned-Identity Faint-Focus 3D Volumetric Spotlight Cones
  const cf = props.closestFocus || {}
  const mode = focusMode.value
  const closestId =
    cf.enabled !== false && (mode === 'AUTO' || mode === 'BOTH')
      ? cf.closest_speaker_id || cf.locked_speaker_id
      : ''
  const pinnedId =
    cf.enabled !== false && (mode === 'PINNED' || mode === 'BOTH')
      ? cf.pinned_speaker_id || ''
      : ''

  function addSpotlightCone(targetObj, coneHex, lineHex) {
    if (!targetObj) return
    const pLock = polarToRoom3D(targetObj.range_m, targetObj.azimuth_deg)
    const startV = new THREE.Vector3(0, 0.48, 0)
    const endV = new THREE.Vector3(pLock.x, 0.48, pLock.z)
    const dir = new THREE.Vector3().subVectors(endV, startV)
    const dist = Math.max(0.25, dir.length())
    const coneRadius = Math.max(
      0.18,
      Math.tan(((Number(cf.focus_beamwidth_deg) || 26) * Math.PI) / 180) * dist * 0.45
    )
    const spotGeom = new THREE.ConeGeometry(coneRadius, dist, 28, 1, true)
    const spotMat = new THREE.MeshBasicMaterial({
      color: coneHex,
      transparent: true,
      opacity: 0.17,
      side: THREE.DoubleSide,
      depthWrite: false,
    })
    const spotMesh = new THREE.Mesh(spotGeom, spotMat)
    const mid = new THREE.Vector3().addVectors(startV, endV).multiplyScalar(0.5)
    spotMesh.position.copy(mid)
    spotMesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, -1, 0), dir.clone().normalize())
    dynamicGroup.add(spotMesh)

    const lockLine = new THREE.BufferGeometry().setFromPoints([
      startV,
      new THREE.Vector3(pLock.x, 0.56, pLock.z),
    ])
    dynamicGroup.add(
      new THREE.Line(
        lockLine,
        new THREE.LineBasicMaterial({ color: lineHex, transparent: true, opacity: 0.92 })
      )
    )
  }

  if (cf.enabled !== false) {
    const cutR = Math.min(2.8, Math.max(0.4, Number(cf.focus_cutoff_m) || 1.15))
    const cutRing = new THREE.BufferGeometry().setFromPoints(createArcCurvePoints(cutR, -82, 82, 0.028, 56))
    dynamicGroup.add(
      new THREE.Line(cutRing, new THREE.LineBasicMaterial({ color: 0x3fb950, transparent: true, opacity: 0.6 }))
    )

    if (closestId) {
      addSpotlightCone((props.targets || []).find((t) => t.speaker_id === closestId), 0x3fb950, 0x7ee787)
    }
    if (pinnedId && pinnedId !== closestId) {
      addSpotlightCone((props.targets || []).find((t) => t.speaker_id === pinnedId), 0xa371f7, 0xd2a8ff)
    } else if (pinnedId && mode === 'PINNED') {
      addSpotlightCone((props.targets || []).find((t) => t.speaker_id === pinnedId), 0xa371f7, 0xd2a8ff)
    }
  }

  // 7. Build 3D Avatars for Every Enrolled Identity & Non-Vocal Character
  const vadState = props.threeStateVad?.state || 'STANDBY'
  for (const t of props.targets || []) {
    const sid = t.speaker_id
    const pos = polarToRoom3D(t.range_m, t.azimuth_deg)
    const col = new THREE.Color(t.color || '#58a6ff')
    const isClosest = Boolean(closestId && sid === closestId) || Boolean(pinnedId && sid === pinnedId)
    const grp = new THREE.Group()
    grp.position.set(pos.x, 0, pos.z)
    grp.lookAt(0, 0, 0)

    if (sid === 'PERSON_TYPIST') {
      // 3D Desk + Mechanical Keyboard Avatar
      const desk = new THREE.Mesh(
        new THREE.BoxGeometry(0.46, 0.04, 0.26),
        new THREE.MeshStandardMaterial({ color: 0x134e4a, roughness: 0.4 })
      )
      desk.position.y = 0.34
      grp.add(desk)
      const kb = new THREE.Mesh(
        new THREE.BoxGeometry(0.32, 0.03, 0.13),
        new THREE.MeshStandardMaterial({ color: 0x2dd4bf, emissive: 0x14b8a6, emissiveIntensity: 0.65 })
      )
      kb.position.y = 0.375
      grp.add(kb)
      const stand = new THREE.Mesh(
        new THREE.CylinderGeometry(0.03, 0.05, 0.34, 12),
        new THREE.MeshStandardMaterial({ color: 0x1e293b })
      )
      stand.position.y = 0.17
      grp.add(stand)
    } else if (sid === 'DEVICE_CELLPHONE') {
      // 3D Smartphone Slab + Pink LRA Haptic Halo
      const phone = new THREE.Mesh(
        new THREE.BoxGeometry(0.16, 0.28, 0.025),
        new THREE.MeshStandardMaterial({ color: 0xf778ba, emissive: 0xdb2777, emissiveIntensity: 0.55 })
      )
      phone.position.y = 0.34
      phone.rotation.x = -0.35
      grp.add(phone)
    } else if (sid === 'DEVICE_MEMS') {
      // 3D Ultrasonic Octahedral MEMS Crystal
      const crystal = new THREE.Mesh(
        new THREE.OctahedronGeometry(0.16, 0),
        new THREE.MeshStandardMaterial({ color: 0xeab308, emissive: 0xca8a04, emissiveIntensity: 0.6, metalness: 0.5 })
      )
      crystal.position.y = 0.42
      grp.add(crystal)
    } else if (sid === 'OTHER_ROOM_SUBLEVEL') {
      // 3D Outer-Room Boundary Portal Slab + Wave Ring
      const portal = new THREE.Mesh(
        new THREE.BoxGeometry(0.44, 0.72, 0.07),
        new THREE.MeshStandardMaterial({
          color: 0x38bdf8,
          emissive: 0x0284c7,
          emissiveIntensity: 0.55,
          transparent: true,
          opacity: 0.78,
        })
      )
      portal.position.y = 0.38
      grp.add(portal)
    } else {
      // Enrolled Human Vocal Identity 3D Avatar (Pedestal + Torso + Head + Visor + State Halo)
      const vtlScale = Math.min(1.16, Math.max(0.86, (Number(t.vtl_cm) || 17.0) / 17.0))
      const torso = new THREE.Mesh(
        new THREE.CylinderGeometry(0.13 * vtlScale, 0.17 * vtlScale, 0.46 * vtlScale, 20),
        new THREE.MeshStandardMaterial({
          color: col,
          emissive: col,
          emissiveIntensity: isClosest ? 0.42 : 0.2,
          roughness: 0.35,
          metalness: 0.25,
        })
      )
      torso.position.y = 0.28 * vtlScale
      grp.add(torso)

      const shoulders = new THREE.Mesh(
        new THREE.SphereGeometry(0.155 * vtlScale, 18, 14),
        new THREE.MeshStandardMaterial({ color: col, roughness: 0.4 })
      )
      shoulders.scale.set(1.25, 0.55, 0.85)
      shoulders.position.y = 0.50 * vtlScale
      grp.add(shoulders)

      const head = new THREE.Mesh(
        new THREE.SphereGeometry(0.125 * vtlScale, 22, 22),
        new THREE.MeshStandardMaterial({
          color: 0xe6edf3,
          emissive: col,
          emissiveIntensity: 0.22,
          roughness: 0.25,
        })
      )
      head.position.y = 0.69 * vtlScale
      grp.add(head)

      const visor = new THREE.Mesh(
        new THREE.BoxGeometry(0.17 * vtlScale, 0.045, 0.08),
        new THREE.MeshStandardMaterial({
          color: isClosest ? 0x3fb950 : 0x58a6ff,
          emissive: isClosest ? 0x3fb950 : 0x38bdf8,
          emissiveIntensity: 0.9,
        })
      )
      visor.position.set(0, 0.70 * vtlScale, 0.09 * vtlScale)
      grp.add(visor)

      // 3-State VAD Crown Halo (Amber A2-E3-A3 ring in READING, Emerald in ACTIVE)
      if (vadState === 'READING' || isClosest) {
        const haloColor = vadState === 'READING' ? 0xf59e0b : 0x3fb950
        const halo = new THREE.Mesh(
          new THREE.TorusGeometry(0.24, 0.016, 12, 36),
          new THREE.MeshBasicMaterial({ color: haloColor, transparent: true, opacity: 0.88 })
        )
        halo.rotation.x = Math.PI / 2
        halo.position.y = 0.90 * vtlScale
        grp.add(halo)
      }
    }

    // Ground Base Ring (Double bright emerald reticle for Closest Focused Identity)
    const baseRing = new THREE.Mesh(
      new THREE.RingGeometry(isClosest ? 0.23 : 0.17, isClosest ? 0.30 : 0.22, 32),
      new THREE.MeshBasicMaterial({
        color: isClosest ? 0x3fb950 : col,
        side: THREE.DoubleSide,
        transparent: true,
        opacity: isClosest ? 0.95 : 0.65,
      })
    )
    baseRing.rotation.x = -Math.PI / 2
    baseRing.position.y = 0.016
    grp.add(baseRing)

    // Invisible click-pick bounding cylinder for easy raycasting
    const pickHit = new THREE.Mesh(
      new THREE.CylinderGeometry(0.28, 0.28, 0.95, 12),
      new THREE.MeshBasicMaterial({ visible: false })
    )
    pickHit.position.y = 0.48
    pickHit.userData = { speaker_id: sid }
    grp.add(pickHit)
    avatarPickMeshes.push(pickHit)

    // Breadcrumb trail in 3D floor plane
    if (Array.isArray(t.trail) && t.trail.length > 1) {
      const tPts = t.trail.slice(-14).map((pt) => {
        const tp = polarToRoom3D(pt.range_m, pt.azimuth_deg)
        return new THREE.Vector3(tp.x, 0.02, tp.z)
      })
      dynamicGroup.add(
        new THREE.Line(
          new THREE.BufferGeometry().setFromPoints(tPts),
          new THREE.LineBasicMaterial({ color: col, transparent: true, opacity: 0.42 })
        )
      )
    }

    dynamicGroup.add(grp)
  }
}

function updateProjectedOverlays(width, height) {
  if (!camera || width <= 0 || height <= 0) return
  const cf = props.closestFocus || {}
  const mode = focusMode.value
  const closestId =
    cf.enabled !== false && (mode === 'AUTO' || mode === 'BOTH')
      ? cf.closest_speaker_id || cf.locked_speaker_id
      : ''
  const pinnedId =
    cf.enabled !== false && (mode === 'PINNED' || mode === 'BOTH')
      ? cf.pinned_speaker_id || ''
      : ''
  const out = []

  for (const t of props.targets || []) {
    const sid = t.speaker_id
    const pos = polarToRoom3D(t.range_m, t.azimuth_deg)
    const headY = NON_VOCAL_SET.has(sid) ? 0.66 : 0.96
    const v = new THREE.Vector3(pos.x, headY, pos.z).project(camera)
    if (v.z > 1.0) continue
    const sx = (v.x * 0.5 + 0.5) * width
    const sy = (-v.y * 0.5 + 0.5) * height
    if (sx < 16 || sx > width - 16 || sy < 14 || sy > height - 18) continue
    out.push({
      speaker_id: sid,
      icon: avatarIcon(sid),
      color: t.color || '#58a6ff',
      range_m: t.range_m,
      azimuth_deg: t.azimuth_deg,
      wph: t.wph,
      isClosest: Boolean(closestId && sid === closestId),
      isPinned: Boolean(pinnedId && sid === pinnedId),
      nonVocal: NON_VOCAL_SET.has(sid),
      x: Math.round(sx),
      y: Math.round(sy),
    })
  }
  // De-overlap stacked 3D avatar badges so every identity nameplate is cleanly legible
  out.sort((a, b) => a.y - b.y)
  for (let pass = 0; pass < 2; pass++) {
    for (let i = 0; i < out.length; i++) {
      for (let j = i + 1; j < out.length; j++) {
        if (Math.abs(out[i].x - out[j].x) < 105 && Math.abs(out[j].y - out[i].y) < 31) {
          out[j].y = Math.min(height - 20, out[i].y + 31)
        }
      }
    }
  }
  projectedLabels.value = out

  const origV = new THREE.Vector3(0, -0.05, 0.14).project(camera)
  originScreen.visible = origV.z <= 1.0
  originScreen.x = Math.round((origV.x * 0.5 + 0.5) * width)
  originScreen.y = Math.round((-origV.y * 0.5 + 0.5) * height)
}

function drawCanvas2DFallback(width, height) {
  const cvs = canvasRef.value
  if (!cvs || !camera) return
  cvs.width = width
  cvs.height = height
  const ctx = cvs.getContext('2d')
  if (!ctx) return

  const grad = ctx.createLinearGradient(0, 0, 0, height)
  grad.addColorStop(0, '#070d17')
  grad.addColorStop(1, '#0b1526')
  ctx.fillStyle = grad
  ctx.fillRect(0, 0, width, height)

  const proj = (x, y, z) => {
    const v = new THREE.Vector3(x, y, z).project(camera)
    return {
      x: (v.x * 0.5 + 0.5) * width,
      y: (-v.y * 0.5 + 0.5) * height,
      ok: v.z <= 1.0,
    }
  }

  // Draw 3D perspective range arcs
  for (const r of [1, 2, 3, 4]) {
    ctx.beginPath()
    ctx.strokeStyle = 'rgba(46, 74, 112, 0.75)'
    ctx.lineWidth = 1.2
    const pts = createArcCurvePoints(r, -80, 80, 0.0, 40)
    pts.forEach((pt, idx) => {
      const s = proj(pt.x, pt.y, pt.z)
      if (idx === 0) ctx.moveTo(s.x, s.y)
      else ctx.lineTo(s.x, s.y)
    })
    ctx.stroke()
  }

  // Draw r_c ring
  const rc = Number(props.roomCriticalDist) || 1.45
  ctx.beginPath()
  ctx.setLineDash([6, 4])
  ctx.strokeStyle = '#f0883e'
  createArcCurvePoints(rc, -80, 80, 0.01, 40).forEach((pt, idx) => {
    const s = proj(pt.x, pt.y, pt.z)
    if (idx === 0) ctx.moveTo(s.x, s.y)
    else ctx.lineTo(s.x, s.y)
  })
  ctx.stroke()
  ctx.setLineDash([])

  const orig = proj(0, 0.25, 0)
  // Closest spotlight beam
  const lockedId = props.closestFocus?.enabled !== false ? props.closestFocus?.locked_speaker_id : ''
  const lockedT = (props.targets || []).find((t) => t.speaker_id === lockedId)
  if (lockedT && orig.ok) {
    const lp = polarToRoom3D(lockedT.range_m, lockedT.azimuth_deg)
    const ls = proj(lp.x, 0.35, lp.z)
    ctx.beginPath()
    ctx.strokeStyle = 'rgba(63, 185, 80, 0.88)'
    ctx.lineWidth = 3.5
    ctx.moveTo(orig.x, orig.y)
    ctx.lineTo(ls.x, ls.y)
    ctx.stroke()
  }

  // Draw 3D avatar pillars
  for (const t of props.targets || []) {
    const p = polarToRoom3D(t.range_m, t.azimuth_deg)
    const base = proj(p.x, 0, p.z)
    const top = proj(p.x, 0.68, p.z)
    if (!base.ok || !top.ok) continue
    const isC = lockedId && t.speaker_id === lockedId
    ctx.fillStyle = t.color || '#58a6ff'
    ctx.strokeStyle = isC ? '#3fb950' : t.color || '#58a6ff'
    ctx.lineWidth = isC ? 2.6 : 1.5
    ctx.beginPath()
    ctx.ellipse(base.x, base.y, isC ? 18 : 13, isC ? 8 : 6, 0, 0, Math.PI * 2)
    ctx.stroke()

    ctx.lineWidth = 9
    ctx.beginPath()
    ctx.moveTo(base.x, base.y)
    ctx.lineTo(top.x, top.y + 8)
    ctx.stroke()

    ctx.beginPath()
    ctx.arc(top.x, top.y, 8, 0, Math.PI * 2)
    ctx.fill()
  }

  if (orig.ok) {
    ctx.fillStyle = '#58a6ff'
    ctx.beginPath()
    ctx.arc(orig.x, orig.y, 7, 0, Math.PI * 2)
    ctx.fill()
  }
}

function renderOnce() {
  const vp = viewportRef.value
  if (!vp || !camera) return
  const w = Math.max(320, vp.clientWidth || 560)
  const h = Math.max(260, vp.clientHeight || 340)
  camera.aspect = w / h
  camera.updateProjectionMatrix()
  syncCameraTransform()

  if (webglActive.value && renderer) {
    renderer.setSize(w, h, false)
    renderer.render(scene, camera)
  } else {
    drawCanvas2DFallback(w, h)
  }
  updateProjectedOverlays(w, h)
}

function initThree() {
  const cvs = canvasRef.value
  const vp = viewportRef.value
  if (!cvs || !vp) return

  scene = new THREE.Scene()
  scene.background = new THREE.Color(0x070c15)
  scene.fog = new THREE.FogExp2(0x070c15, 0.065)

  const w = Math.max(320, vp.clientWidth || 560)
  const h = Math.max(260, vp.clientHeight || 340)
  camera = new THREE.PerspectiveCamera(44, w / h, 0.1, 40)
  raycaster = new THREE.Raycaster()

  // Studio 3-point lighting
  scene.add(new THREE.AmbientLight(0x9fb8d8, 0.85))
  const keyLight = new THREE.DirectionalLight(0xffffff, 1.15)
  keyLight.position.set(2.5, 5.2, 3.2)
  scene.add(keyLight)
  const rimLight = new THREE.PointLight(0x38bdf8, 0.9, 10)
  rimLight.position.set(-2.2, 2.4, -2.8)
  scene.add(rimLight)

  // Subtle acoustic chamber floor grid
  const grid = new THREE.GridHelper(8.4, 24, 0x1e334d, 0x111c2d)
  grid.position.set(0, 0, -1.6)
  scene.add(grid)

  dynamicGroup = new THREE.Group()
  scene.add(dynamicGroup)

  try {
    renderer = new THREE.WebGLRenderer({
      canvas: cvs,
      antialias: true,
      powerPreference: 'high-performance',
      preserveDrawingBuffer: true,
    })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    webglActive.value = true
  } catch (_) {
    renderer = null
    webglActive.value = false
  }

  rebuildThreeScene()
  renderOnce()

  if (!isSnapshot) {
    const tick = () => {
      animPhase += 0.025
      if (dynamicGroup) {
        // Subtle breathing shimmer on halo rings
        renderOnce()
      }
      rafId = requestAnimationFrame(tick)
    }
    rafId = requestAnimationFrame(tick)
  }
}

function onPointerDown(e) {
  dragging = true
  dragMoved = false
  lastPtrX = e.clientX
  lastPtrY = e.clientY
}

function onPointerMove(e) {
  if (!dragging) return
  const dx = e.clientX - lastPtrX
  const dy = e.clientY - lastPtrY
  if (Math.abs(dx) + Math.abs(dy) > 3) dragMoved = true
  lastPtrX = e.clientX
  lastPtrY = e.clientY
  camOrbit.yaw = Math.max(-1.45, Math.min(1.45, camOrbit.yaw - dx * 0.0065))
  camOrbit.pitch = Math.max(0.18, Math.min(1.44, camOrbit.pitch + dy * 0.0065))
  camPreset.value = 'custom'
  if (isSnapshot) renderOnce()
}

function onPointerUp(e) {
  if (dragging && !dragMoved && e.type === 'pointerup' && raycaster && camera && viewportRef.value) {
    const rect = viewportRef.value.getBoundingClientRect()
    const ndc = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1
    )
    raycaster.setFromCamera(ndc, camera)
    const hits = raycaster.intersectObjects(avatarPickMeshes, false)
    if (hits.length > 0 && hits[0].object?.userData?.speaker_id) {
      emit('select-speaker', hits[0].object.userData.speaker_id)
    }
  }
  dragging = false
}

function onWheel(e) {
  camOrbit.radius = Math.max(1.85, Math.min(8.5, camOrbit.radius + e.deltaY * 0.0035))
  if (isSnapshot) renderOnce()
}

watch(
  () => [props.targets, props.roomCriticalDist, props.closestFocus, props.threeStateVad, props.typistSector],
  () => {
    rebuildThreeScene()
    renderOnce()
  },
  { deep: true }
)

onMounted(() => {
  initThree()
  if (typeof ResizeObserver !== 'undefined' && viewportRef.value) {
    resizeObs = new ResizeObserver(() => renderOnce())
    resizeObs.observe(viewportRef.value)
  }
})

onBeforeUnmount(() => {
  if (rafId) cancelAnimationFrame(rafId)
  if (resizeObs) resizeObs.disconnect()
  if (renderer) {
    renderer.dispose()
    renderer = null
  }
})
</script>

<style scoped>
.three-stage-wrap {
  background: #070c15;
  border: 1px solid #1e2f47;
  border-radius: 10px;
  overflow: hidden;
}
.stage-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 7px 10px;
  background: rgba(13, 21, 34, 0.95);
  border-bottom: 1px solid #1b2a40;
  font-size: 10.5px;
}
.st-left,
.st-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.engine-chip {
  color: #79c0ff;
  background: rgba(56, 139, 253, 0.14);
  border: 1px solid rgba(56, 139, 253, 0.38);
  padding: 2px 7px;
  border-radius: 99px;
}
.vad-chip {
  padding: 2px 7px;
  border-radius: 99px;
  border: 1px solid #30363d;
}
.vad-standby {
  color: #8b949e;
  background: rgba(110, 118, 129, 0.12);
}
.vad-reading {
  color: #fbbf24;
  border-color: rgba(251, 191, 36, 0.5);
  background: rgba(251, 191, 36, 0.14);
}
.vad-active {
  color: #3fb950;
  border-color: rgba(63, 185, 80, 0.5);
  background: rgba(63, 185, 80, 0.14);
}
.focus-chip {
  color: #7ee787;
  background: rgba(63, 185, 80, 0.14);
  border: 1px solid rgba(63, 185, 80, 0.42);
  padding: 2px 8px;
  border-radius: 99px;
}
.pin-chip {
  color: #d2a8ff;
  background: rgba(163, 113, 247, 0.16);
  border: 1px solid rgba(163, 113, 247, 0.45);
  padding: 2px 8px;
  border-radius: 99px;
}
.cam-btn {
  background: #111b2b;
  color: #9ca3af;
  border: 1px solid #24354d;
  border-radius: 5px;
  padding: 2px 8px;
  font-size: 10.5px;
  cursor: pointer;
}
.cam-btn.active,
.cam-btn:hover {
  color: #e6edf3;
  border-color: #58a6ff;
  background: rgba(56, 139, 253, 0.2);
}
.three-viewport {
  position: relative;
  width: 100%;
  height: 345px;
  cursor: grab;
  user-select: none;
}
.three-viewport:active {
  cursor: grabbing;
}
.three-canvas {
  width: 100%;
  height: 100%;
  display: block;
}
.avatar-label {
  position: absolute;
  transform: translate(-50%, -100%);
  background: rgba(10, 16, 26, 0.88);
  backdrop-filter: blur(4px);
  border: 1px solid #58a6ff;
  border-radius: 6px;
  padding: 3px 7px;
  display: flex;
  flex-direction: column;
  gap: 1px;
  cursor: pointer;
  pointer-events: auto;
  white-space: nowrap;
  z-index: 4;
  transition: transform 0.12s ease, box-shadow 0.12s ease;
}
.avatar-label:hover {
  transform: translate(-50%, -106%) scale(1.04);
  z-index: 8;
}
.avatar-label.is-closest {
  box-shadow: 0 0 14px rgba(63, 185, 80, 0.45);
  background: rgba(9, 26, 18, 0.92);
}
.avatar-label.is-pinned {
  box-shadow: 0 0 14px rgba(163, 113, 247, 0.48);
  background: rgba(24, 13, 38, 0.92);
}
.al-top {
  font-size: 10.5px;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 5px;
}
.al-sub {
  font-size: 9.2px;
  color: #9ca3af;
}
.closest-tag {
  background: #238636;
  color: #fff;
  font-size: 8.5px;
  padding: 0 5px;
  border-radius: 99px;
}
.pinned-tag {
  background: #8957e5;
  color: #fff;
  font-size: 8.5px;
  padding: 0 5px;
  border-radius: 99px;
}
.origin-tag {
  position: absolute;
  transform: translate(-50%, 4px);
  font-size: 9.5px;
  color: #79c0ff;
  background: rgba(9, 15, 25, 0.82);
  border: 1px solid rgba(88, 166, 255, 0.35);
  padding: 2px 7px;
  border-radius: 99px;
  pointer-events: none;
  white-space: nowrap;
}
.orbit-hint {
  position: absolute;
  right: 10px;
  bottom: 7px;
  font-size: 9.5px;
  color: #6e7681;
  background: rgba(7, 12, 21, 0.72);
  padding: 2px 7px;
  border-radius: 4px;
  pointer-events: none;
}
</style>
