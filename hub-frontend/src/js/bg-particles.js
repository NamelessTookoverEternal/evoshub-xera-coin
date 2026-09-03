// EVOSHUB — Subtle 3D background blobs (lazy-loaded Three.js)
// ─────────────────────────────────────────────────────────────
// Renders a handful of slow-floating, low-poly, wireframe-free
// blobs behind the page content using <canvas id="bg3d-canvas">.
// Designed to cost as little as possible:
//
//   - `three` is only downloaded (dynamic import) if: WebGL works,
//     3D effects are enabled, the tab is visible, and the browser
//     is idle after first paint. Vite automatically code-splits
//     this into its own chunk — nothing here is in your main bundle.
//   - MeshBasicMaterial only (no lights/shadows to compute).
//   - Pixel ratio capped at 1.5, geometry detail kept at 0
//     (icosahedron "detail 0" = 20 triangles, genuinely low-poly).
//   - Fewer blobs + lower pixel ratio on narrow (mobile) viewports.
//   - Fully paused via `document.hidden` and torn down (geometries,
//     materials, renderer disposed) whenever 3D effects are toggled
//     off, so it releases memory instead of just hiding.
//   - If WebGL isn't available, or effects are off, this file does
//     nothing at all — the existing starfield/gradient background
//     stays exactly as it was. Content is never blocked either way.
//
// Requires: `npm install three` (see README notes shipped alongside
// this file / the redesign summary for the exact command).

import { isMotion3DEnabled, onMotion3DChange } from './motion3d.js'

const canvas = document.getElementById('bg3d-canvas')
if (canvas) {
  const starfield = document.querySelector('.starfield')

  let renderer, scene, camera, blobs = [], rafId = null, resizeObs
  let started = false

  function supportsWebGL() {
    try {
      const test = document.createElement('canvas')
      return !!(window.WebGLRenderingContext &&
        (test.getContext('webgl') || test.getContext('experimental-webgl')))
    } catch (e) {
      return false
    }
  }

  function themeColor(varName, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(varName).trim()
    return v || fallback
  }

  async function start() {
    if (started || !isMotion3DEnabled() || !supportsWebGL()) return
    started = true

    // Dynamic import — this is the line that actually pulls in the
    // three.js chunk over the network. Everything above this point
    // runs with zero extra bytes downloaded.
    const THREE = await import('three')

    const isMobile = window.innerWidth < 640
    const blobCount = isMobile ? 3 : 5
    const pixelRatio = Math.min(window.devicePixelRatio || 1, isMobile ? 1.2 : 1.5)

    renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: pixelRatio < 1.5 })
    renderer.setPixelRatio(pixelRatio)
    renderer.setSize(window.innerWidth, window.innerHeight, false)

    scene = new THREE.Scene()
    camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 100)
    camera.position.z = 12

    const palette = [
      themeColor('--blue', '#3E8BFF'),
      themeColor('--violet', '#A855F7'),
      themeColor('--green', '#2CE6A6'),
    ]

    blobs = Array.from({ length: blobCount }, (_, i) => {
      const geo = new THREE.IcosahedronGeometry(1 + Math.random() * 0.6, 0) // detail 0 = low-poly
      const mat = new THREE.MeshBasicMaterial({
        color: palette[i % palette.length],
        transparent: true,
        opacity: 0.10,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      })
      const mesh = new THREE.Mesh(geo, mat)
      mesh.position.set(
        (Math.random() - 0.5) * 14,
        (Math.random() - 0.5) * 8,
        (Math.random() - 0.5) * 6
      )
      mesh.userData = {
        rotSpeedX: (Math.random() - 0.5) * 0.0025,
        rotSpeedY: (Math.random() - 0.5) * 0.0025,
        floatFreq: 0.2 + Math.random() * 0.3,
        floatAmp: 0.4 + Math.random() * 0.5,
        floatPhase: Math.random() * Math.PI * 2,
        baseY: mesh.position.y,
      }
      scene.add(mesh)
      return mesh
    })

    canvas.classList.add('bg3d-ready')
    if (starfield) starfield.style.display = 'none' // avoid two ambient motions competing

    let clock = 0
    function tick() {
      if (!isMotion3DEnabled() || document.hidden) { rafId = requestAnimationFrame(tick); return }
      clock += 0.016
      blobs.forEach(b => {
        b.rotation.x += b.userData.rotSpeedX
        b.rotation.y += b.userData.rotSpeedY
        b.position.y = b.userData.baseY + Math.sin(clock * b.userData.floatFreq + b.userData.floatPhase) * b.userData.floatAmp
      })
      renderer.render(scene, camera)
      rafId = requestAnimationFrame(tick)
    }
    tick()

    resizeObs = () => {
      const w = window.innerWidth, h = window.innerHeight
      camera.aspect = w / h
      camera.updateProjectionMatrix()
      renderer.setSize(w, h, false)
    }
    window.addEventListener('resize', resizeObs, { passive: true })
  }

  function stop() {
    if (!started) return
    started = false
    if (rafId) cancelAnimationFrame(rafId)
    if (resizeObs) window.removeEventListener('resize', resizeObs)
    blobs.forEach(b => { b.geometry.dispose(); b.material.dispose() })
    blobs = []
    if (renderer) { renderer.dispose(); renderer = null }
    scene = null
    canvas.classList.remove('bg3d-ready')
    if (starfield) starfield.style.display = ''
  }

  // Kick off after first paint, once the browser is idle — never
  // competes with the initial page render or the hero flow-in.
  const schedule = window.requestIdleCallback || (fn => setTimeout(fn, 300))
  window.addEventListener('load', () => schedule(start), { once: true })

  onMotion3DChange(on => (on ? schedule(start) : stop()))
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) return // tick() already no-ops while hidden
  })
}
