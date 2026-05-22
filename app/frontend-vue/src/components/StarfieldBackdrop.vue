<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

type Star = {
  x: number
  y: number
  depth: number
  speed: number
  tone: number
  curl: number
}

type Meteor = {
  x: number
  y: number
  vx: number
  vy: number
  speed: number
  length: number
  life: number
  maxLife: number
  alpha: number
}

const canvasRef = ref<HTMLCanvasElement | null>(null)

let ctx: CanvasRenderingContext2D | null = null
let width = 0
let height = 0
let dpr = 1
let stars: Star[] = []
let meteors: Meteor[] = []
let animationFrame = 0
let lastTime = performance.now()
let lastPointer: { x: number; y: number } | null = null
let targetDir = { x: -0.92, y: 0.38 }
let dir = { x: -0.92, y: 0.38 }
let boost = 0
let meteorClock = 0
let reducedMotion = false

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function normalize(x: number, y: number) {
  const length = Math.hypot(x, y) || 1
  return { x: x / length, y: y / length }
}

function createStars() {
  const density = reducedMotion ? 0.18 : 0.72
  const count = Math.floor(clamp((width * height) / 1100, 260, 1180) * density)
  stars = Array.from({ length: count }, () => ({
    x: Math.random() * width,
    y: Math.random() * height,
    depth: 0.35 + Math.random() * 1.7,
    speed: 0.45 + Math.random() * 1.9,
    tone: 0.45 + Math.random() * 0.55,
    curl: (Math.random() - 0.5) * 0.55,
  }))
}

function resize() {
  const canvas = canvasRef.value
  if (!canvas || !ctx) return
  dpr = Math.min(window.devicePixelRatio || 1, 2)
  width = Math.max(1, window.innerWidth)
  height = Math.max(1, window.innerHeight)
  canvas.width = Math.floor(width * dpr)
  canvas.height = Math.floor(height * dpr)
  canvas.style.width = `${width}px`
  canvas.style.height = `${height}px`
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  createStars()
  ctx.fillStyle = '#000'
  ctx.fillRect(0, 0, width, height)
}

function pointerMove(event: MouseEvent | TouchEvent) {
  const point = 'touches' in event && event.touches[0]
    ? { x: event.touches[0].clientX, y: event.touches[0].clientY }
    : { x: (event as MouseEvent).clientX, y: (event as MouseEvent).clientY }

  if (lastPointer) {
    const dx = point.x - lastPointer.x
    const dy = point.y - lastPointer.y
    const distance = Math.hypot(dx, dy)
    if (distance > 1) {
      targetDir = normalize(dx, dy)
      boost = clamp(boost + distance * 0.012, 0, 4.5)
    }
  }
  lastPointer = point
}

function pointerLeave() {
  lastPointer = null
}

function wheel(event: WheelEvent) {
  boost = clamp(boost + Math.abs(event.deltaY) * 0.008, 0, 5.5)
}

function wrapStar(star: Star) {
  const pad = 28
  if (star.x < -pad) star.x = width + pad
  if (star.x > width + pad) star.x = -pad
  if (star.y < -pad) star.y = height + pad
  if (star.y > height + pad) star.y = -pad
}

function spawnMeteor() {
  const direction = { ...dir }
  const edgeHorizontal = Math.abs(direction.x) > Math.abs(direction.y)
  const x = edgeHorizontal ? (direction.x > 0 ? -80 : width + 80) : Math.random() * width
  const y = edgeHorizontal ? Math.random() * height : (direction.y > 0 ? -80 : height + 80)
  meteors.push({
    x,
    y,
    vx: direction.x,
    vy: direction.y,
    speed: 560 + Math.random() * 420,
    length: 90 + Math.random() * 160,
    life: 0,
    maxLife: 0.75 + Math.random() * 0.55,
    alpha: 0.5 + Math.random() * 0.4,
  })
}

function drawMeteor(meteor: Meteor) {
  if (!ctx) return
  const tailX = meteor.x - meteor.vx * meteor.length
  const tailY = meteor.y - meteor.vy * meteor.length
  const gradient = ctx.createLinearGradient(tailX, tailY, meteor.x, meteor.y)
  gradient.addColorStop(0, 'rgba(255,255,255,0)')
  gradient.addColorStop(0.58, `rgba(190,235,255,${meteor.alpha * 0.45})`)
  gradient.addColorStop(1, `rgba(255,255,255,${meteor.alpha})`)
  ctx.strokeStyle = gradient
  ctx.lineWidth = 1.1
  ctx.beginPath()
  ctx.moveTo(tailX, tailY)
  ctx.lineTo(meteor.x, meteor.y)
  ctx.stroke()
}

function draw(time: number) {
  if (!ctx) return
  const dt = Math.min((time - lastTime) / 1000, 0.033)
  lastTime = time

  dir.x += (targetDir.x - dir.x) * 0.055
  dir.y += (targetDir.y - dir.y) * 0.055
  dir = normalize(dir.x, dir.y)
  boost *= 0.965

  ctx.globalCompositeOperation = 'source-over'
  ctx.fillStyle = reducedMotion ? 'rgba(0,0,0,0.42)' : 'rgba(0,0,0,0.18)'
  ctx.fillRect(0, 0, width, height)

  if (!reducedMotion) {
    ctx.globalCompositeOperation = 'lighter'
    const centerX = width * 0.5
    const centerY = height * 0.52
    const baseSpeed = 120 + boost * 78

    for (const star of stars) {
      const dx = star.x - centerX
      const dy = star.y - centerY
      const swirl = 0.0009 * (1 + boost * 0.18) * star.curl
      const vx = dir.x * baseSpeed * star.speed * star.depth - dy * swirl * baseSpeed
      const vy = dir.y * baseSpeed * star.speed * star.depth + dx * swirl * baseSpeed
      star.x += vx * dt
      star.y += vy * dt
      wrapStar(star)

      const size = clamp(star.depth * 1.15, 0.35, 2.2)
      const alpha = clamp(0.2 + star.depth * 0.22 + boost * 0.04, 0.2, 0.9) * star.tone
      ctx.fillStyle = `rgba(235,248,255,${alpha})`
      ctx.fillRect(star.x, star.y, size, size)
    }

    meteorClock += dt * (1 + boost * 0.2)
    if (meteorClock > 0.18 + Math.random() * 0.32) {
      meteorClock = 0
      spawnMeteor()
    }
    meteors = meteors.filter((meteor) => {
      meteor.vx += (dir.x - meteor.vx) * 0.03
      meteor.vy += (dir.y - meteor.vy) * 0.03
      const nd = normalize(meteor.vx, meteor.vy)
      meteor.vx = nd.x
      meteor.vy = nd.y
      meteor.x += meteor.vx * meteor.speed * dt
      meteor.y += meteor.vy * meteor.speed * dt
      meteor.life += dt
      meteor.alpha *= 0.994
      drawMeteor(meteor)
      return meteor.life < meteor.maxLife && meteor.x > -260 && meteor.x < width + 260 && meteor.y > -260 && meteor.y < height + 260
    })
  } else {
    ctx.fillStyle = 'rgba(245,250,255,0.62)'
    for (const star of stars) ctx.fillRect(star.x, star.y, 1, 1)
  }

  animationFrame = requestAnimationFrame(draw)
}

onMounted(() => {
  const canvas = canvasRef.value
  if (!canvas) return
  ctx = canvas.getContext('2d', { alpha: false })
  reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  resize()
  window.addEventListener('resize', resize, { passive: true })
  window.addEventListener('mousemove', pointerMove, { passive: true })
  window.addEventListener('touchmove', pointerMove, { passive: true })
  window.addEventListener('mouseleave', pointerLeave, { passive: true })
  window.addEventListener('wheel', wheel, { passive: true })
  animationFrame = requestAnimationFrame(draw)
})

onBeforeUnmount(() => {
  cancelAnimationFrame(animationFrame)
  window.removeEventListener('resize', resize)
  window.removeEventListener('mousemove', pointerMove)
  window.removeEventListener('touchmove', pointerMove)
  window.removeEventListener('mouseleave', pointerLeave)
  window.removeEventListener('wheel', wheel)
})
</script>

<template>
  <canvas ref="canvasRef" class="signal-backdrop" aria-hidden="true"></canvas>
  <div class="signal-vignette" aria-hidden="true"></div>
</template>
