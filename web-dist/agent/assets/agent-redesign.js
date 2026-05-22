const canvas = document.querySelector("#agent-sky");
const ctx = canvas.getContext("2d");
const pointer = { x: 0, y: 0, dx: 0.75, dy: 0.25 };
let stars = [];
let meteors = [];

function resize() {
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.floor(window.innerWidth * ratio);
  canvas.height = Math.floor(window.innerHeight * ratio);
  canvas.style.width = `${window.innerWidth}px`;
  canvas.style.height = `${window.innerHeight}px`;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  const count = Math.floor((window.innerWidth * window.innerHeight) / 8500);
  stars = Array.from({ length: count }, () => ({
    x: Math.random() * window.innerWidth,
    y: Math.random() * window.innerHeight,
    r: Math.random() * 1.2 + 0.2,
    a: Math.random() * 0.6 + 0.15,
    drift: Math.random() * 0.16 + 0.04,
  }));
}

function spawnMeteor() {
  const speed = Math.random() * 3 + 4;
  const dx = pointer.dx || 0.8;
  const dy = pointer.dy || 0.25;
  meteors.push({
    x: Math.random() * window.innerWidth,
    y: Math.random() * window.innerHeight * 0.55,
    vx: dx * speed,
    vy: dy * speed,
    life: 0,
    ttl: Math.random() * 42 + 42,
    len: Math.random() * 80 + 90,
  });
  if (meteors.length > 18) meteors.shift();
}

function draw() {
  ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
  ctx.fillStyle = "#020406";
  ctx.fillRect(0, 0, window.innerWidth, window.innerHeight);

  stars.forEach((star) => {
    star.x += star.drift * 0.12;
    if (star.x > window.innerWidth + 4) star.x = -4;
    ctx.globalAlpha = star.a;
    ctx.fillStyle = "#dcefff";
    ctx.beginPath();
    ctx.arc(star.x, star.y, star.r, 0, Math.PI * 2);
    ctx.fill();
  });

  if (Math.random() < 0.055) spawnMeteor();

  meteors.forEach((meteor) => {
    meteor.life += 1;
    meteor.x += meteor.vx;
    meteor.y += meteor.vy;
    const fade = 1 - meteor.life / meteor.ttl;
    const mag = Math.hypot(meteor.vx, meteor.vy) || 1;
    const tx = (meteor.vx / mag) * meteor.len;
    const ty = (meteor.vy / mag) * meteor.len;
    const gradient = ctx.createLinearGradient(meteor.x, meteor.y, meteor.x - tx, meteor.y - ty);
    gradient.addColorStop(0, `rgba(245, 252, 255, ${0.7 * fade})`);
    gradient.addColorStop(0.35, `rgba(105, 232, 255, ${0.32 * fade})`);
    gradient.addColorStop(1, "rgba(105, 232, 255, 0)");
    ctx.strokeStyle = gradient;
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    ctx.moveTo(meteor.x, meteor.y);
    ctx.lineTo(meteor.x - tx, meteor.y - ty);
    ctx.stroke();
  });
  meteors = meteors.filter((meteor) => meteor.life < meteor.ttl);
  ctx.globalAlpha = 1;
  requestAnimationFrame(draw);
}

window.addEventListener("resize", resize);
window.addEventListener("mousemove", (event) => {
  const nx = event.clientX / Math.max(window.innerWidth, 1) - 0.5;
  const ny = event.clientY / Math.max(window.innerHeight, 1) - 0.5;
  pointer.dx = 0.65 + nx * 1.1;
  pointer.dy = 0.18 + ny * 0.7;
});

resize();
draw();

const toast = document.querySelector("#toast");
let toastTimer = 0;
async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const input = document.createElement("textarea");
    input.value = text;
    input.style.position = "fixed";
    input.style.opacity = "0";
    document.body.appendChild(input);
    input.select();
    document.execCommand("copy");
    input.remove();
  }
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 1500);
}

document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-copy]");
  if (!target) return;
  copyText(target.dataset.copy || target.textContent.trim());
});

function shortTime(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return `${String(date.getMonth() + 1).padStart(2, "0")}/${String(date.getDate()).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

async function loadStats() {
  const healthEl = document.querySelector("#healthStatus");
  try {
    const [health, stats] = await Promise.all([
      fetch("../api/health").then((r) => r.json()),
      fetch("../api/public/stats").then((r) => r.json()),
    ]);
    healthEl.textContent = health.status === "ok" ? "在线" : "异常";
    document.querySelector("#statItems").textContent = stats.counts?.items ?? "--";
    document.querySelector("#statSelected").textContent = stats.counts?.selected ?? "--";
    document.querySelector("#statDaily").textContent = stats.counts?.dailyIssues ?? "--";
    document.querySelector("#statTime").textContent = shortTime(stats.generatedAt || stats.latestRun?.finished_at);
  } catch {
    healthEl.textContent = "离线";
  }
}

loadStats();
setInterval(loadStats, 60000);
