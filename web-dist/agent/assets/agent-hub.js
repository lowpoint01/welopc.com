const canvas = document.querySelector("#signalSky");
const ctx = canvas.getContext("2d");
const pointer = { x: 0.5, y: 0.3, dx: 0.78, dy: 0.22 };
let stars = [];
let meteors = [];

function resizeSky() {
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.floor(window.innerWidth * ratio);
  canvas.height = Math.floor(window.innerHeight * ratio);
  canvas.style.width = `${window.innerWidth}px`;
  canvas.style.height = `${window.innerHeight}px`;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  const count = Math.max(90, Math.floor((window.innerWidth * window.innerHeight) / 7200));
  stars = Array.from({ length: count }, () => ({
    x: Math.random() * window.innerWidth,
    y: Math.random() * window.innerHeight,
    r: Math.random() * 1.08 + 0.16,
    a: Math.random() * 0.6 + 0.1,
    v: Math.random() * 0.14 + 0.02,
  }));
}

function spawnMeteor() {
  const speed = Math.random() * 2.8 + 3.8;
  meteors.push({
    x: Math.random() * window.innerWidth,
    y: Math.random() * window.innerHeight * 0.72,
    vx: pointer.dx * speed,
    vy: pointer.dy * speed,
    life: 0,
    ttl: Math.random() * 48 + 44,
    len: Math.random() * 110 + 82,
  });
  if (meteors.length > 16) meteors.shift();
}

function drawSky() {
  ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
  ctx.fillStyle = "#020405";
  ctx.fillRect(0, 0, window.innerWidth, window.innerHeight);

  for (const star of stars) {
    star.x += star.v * 0.14;
    if (star.x > window.innerWidth + 4) star.x = -4;
    ctx.globalAlpha = star.a;
    ctx.fillStyle = "#dfefff";
    ctx.beginPath();
    ctx.arc(star.x, star.y, star.r, 0, Math.PI * 2);
    ctx.fill();
  }

  if (Math.random() < 0.045) spawnMeteor();

  for (const meteor of meteors) {
    meteor.life += 1;
    meteor.x += meteor.vx;
    meteor.y += meteor.vy;
    const fade = Math.max(0, 1 - meteor.life / meteor.ttl);
    const mag = Math.hypot(meteor.vx, meteor.vy) || 1;
    const tx = (meteor.vx / mag) * meteor.len;
    const ty = (meteor.vy / mag) * meteor.len;
    const gradient = ctx.createLinearGradient(meteor.x, meteor.y, meteor.x - tx, meteor.y - ty);
    gradient.addColorStop(0, `rgba(255,255,255,${0.68 * fade})`);
    gradient.addColorStop(0.38, `rgba(105,232,255,${0.3 * fade})`);
    gradient.addColorStop(1, "rgba(105,232,255,0)");
    ctx.globalAlpha = 1;
    ctx.strokeStyle = gradient;
    ctx.lineWidth = 1.3;
    ctx.beginPath();
    ctx.moveTo(meteor.x, meteor.y);
    ctx.lineTo(meteor.x - tx, meteor.y - ty);
    ctx.stroke();
  }
  meteors = meteors.filter((meteor) => meteor.life < meteor.ttl);
  ctx.globalAlpha = 1;
  requestAnimationFrame(drawSky);
}

window.addEventListener("resize", resizeSky);
window.addEventListener("mousemove", (event) => {
  pointer.x = event.clientX / Math.max(window.innerWidth, 1);
  pointer.y = event.clientY / Math.max(window.innerHeight, 1);
  pointer.dx = 0.52 + (pointer.x - 0.5) * 1.18;
  pointer.dy = 0.16 + (pointer.y - 0.36) * 0.78;
});

resizeSky();
drawSky();

const topbar = document.querySelector("#topbar");
function syncTopbar() {
  topbar.classList.toggle("is-scrolled", window.scrollY > 12);
}
window.addEventListener("scroll", syncTopbar, { passive: true });
syncTopbar();

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
  toastTimer = setTimeout(() => toast.classList.remove("show"), 1400);
}

document.addEventListener("click", (event) => {
  const trigger = event.target.closest("[data-copy]");
  if (!trigger) return;
  copyText(trigger.dataset.copy || trigger.textContent.trim());
});

const commands = {
  latest: "python scripts/latest.py --channel all --mode selected --limit 10 --format markdown",
  daily: "python scripts/daily.py --format markdown",
  search: 'python scripts/search.py "Agent" --channel all --mode all --limit 20 --format json',
  stats: "python scripts/stats.py --format json",
};

const commandText = document.querySelector("#commandText");
const copyCommand = document.querySelector("#copyCommand");

document.querySelectorAll("[data-command]").forEach((button) => {
  button.addEventListener("click", () => {
    const command = commands[button.dataset.command];
    if (!command) return;
    document.querySelectorAll("[data-command]").forEach((item) => item.classList.toggle("is-active", item === button));
    commandText.textContent = command;
    copyCommand.dataset.copy = command;
  });
});

const packs = {
  aihot: {
    slug: "aihot",
    tag: "UPSTREAM SIGNAL",
    title: "AI HOT 情报入口",
    body: "把精选热点、日报、公众号和来源评分组合成可引用上下文，让 Agent 不再从空白问题开始工作。",
    output: "output: trend_brief / topic_pool / citations / automation_trigger",
  },
  selfmedia: {
    slug: "selfmedia",
    tag: "CONTENT ENGINE",
    title: "内容选题工作台",
    body: "把热点和公众号内容转成选题角度、标题方向、素材引用和发布前检查清单。",
    output: "output: title_angles / script_seed / post_outline / source_quotes",
  },
  ecommerce: {
    slug: "ops",
    tag: "OPERATION SIGNAL",
    title: "运营辅助信号源",
    body: "追踪 AI 工具、平台政策、自动化方案和产品变化，辅助台账、日报和 SOP 更新。",
    output: "output: tool_list / ops_digest / product_sheet / automation_sop",
  },
  knowledge: {
    slug: "knowledge",
    tag: "KNOWLEDGE ASSET",
    title: "知识沉淀素材库",
    body: "将高信号内容沉淀为课程素材、社群答疑、知识库条目和可复用研究笔记。",
    output: "output: notes / lesson_seed / qa_material / research_digest",
  },
  sales: {
    slug: "sales",
    tag: "CRM CONTEXT",
    title: "销售跟进情报",
    body: "把客户可能关心的 AI 主题转成跟进提醒、行业切入点、周报和 CRM 备注。",
    output: "output: crm_note / followup_hint / industry_angle / weekly_brief",
  },
};

const packSlug = document.querySelector("#packSlug");
const packTag = document.querySelector("#packTag");
const packTitle = document.querySelector("#packTitle");
const packBody = document.querySelector("#packBody");
const packOutput = document.querySelector("#packOutput");

document.querySelectorAll("[data-pack]").forEach((button) => {
  button.addEventListener("click", () => {
    const data = packs[button.dataset.pack];
    if (!data) return;
    document.querySelectorAll("[data-pack]").forEach((item) => item.classList.toggle("is-active", item === button));
    packSlug.textContent = data.slug;
    packTag.textContent = data.tag;
    packTitle.textContent = data.title;
    packBody.textContent = data.body;
    packOutput.textContent = data.output;
  });
});

function shortTime(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return `${String(date.getMonth() + 1).padStart(2, "0")}/${String(date.getDate()).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function animateNumber(el, value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    el.textContent = "--";
    return;
  }
  const from = Number(el.dataset.value || 0);
  const start = performance.now();
  const duration = 520;
  function frame(now) {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    const current = Math.round(from + (number - from) * eased);
    el.textContent = String(current);
    if (t < 1) requestAnimationFrame(frame);
    else el.dataset.value = String(number);
  }
  requestAnimationFrame(frame);
}

async function loadLiveStats() {
  const healthText = document.querySelector("#healthText");
  try {
    const [health, stats] = await Promise.all([
      fetch("../api/health").then((res) => res.json()),
      fetch("../api/public/stats").then((res) => res.json()),
    ]);
    healthText.textContent = health.status === "ok" ? "Online" : "Attention";
    animateNumber(document.querySelector("#itemsCount"), stats.counts?.items);
    animateNumber(document.querySelector("#selectedCount"), stats.counts?.selected);
    animateNumber(document.querySelector("#dailyCount"), stats.counts?.dailyIssues);
    document.querySelector("#latestTime").textContent = shortTime(stats.generatedAt || stats.latestRun?.finished_at);
  } catch {
    healthText.textContent = "Offline";
  }
}

loadLiveStats();
setInterval(loadLiveStats, 60000);
