const BASE = (() => {
  const marker = "/ai-hot";
  return location.pathname.startsWith(marker) ? marker : "";
})();
const API = `${BASE}/api`;
const $ = (sel) => document.querySelector(sel);
const state = {
  route: routeFromLocation(),
  channel: "all",
  q: "",
  feedItems: [],
  nextCursor: null,
  dailyDate: "",
  mpPeriod: "all",
  adminTab: "overview",
  token: localStorage.getItem("aihot_admin_token") || "",
  mpSources: [],
  mpSourceEditing: null,
  mpSourceTest: null,
  wechatSources: [],
  wechatSourceArticles: [],
  wechatSourceEditing: null,
  wechatSourceImportResult: null,
  wechatAuth: null,
  wechatSearchResults: [],
  wechatSearchMeta: null,
  wechatSyncResult: null,
};

function routeFromLocation() {
  let path = location.pathname;
  if (BASE && path.startsWith(BASE)) path = path.slice(BASE.length) || "/";
  return path.replace(/\/$/, "") || "/";
}
function go(route) {
  history.pushState({}, "", `${BASE}${route === "/" ? "/" : route}`);
  state.route = route;
  render();
}
function esc(v) {
  return String(v ?? "").replace(/[&<>'"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", "\"": "&quot;" })[c]);
}
function decodeEntities(v) {
  const text = String(v ?? "");
  if (!text) return "";
  const box = document.createElement("textarea");
  box.innerHTML = text;
  return box.value;
}
function cleanText(v) {
  let text = decodeEntities(v);
  text = text
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<a\b[^>]*class=["'][^"']*wx_topic_link[^"']*["'][^>]*>\s*#?([^<]+)<\/a>/gi, " ")
    .replace(/<a\b[^>]*>\s*#?([^<]{1,40})<\/a>/gi, " ")
    .replace(/<br\s*\/?>/gi, " ")
    .replace(/<\/(p|div|li|section|article)>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s*#[\p{L}\p{N}_+-]{1,32}/gu, " ")
    .replace(/(?:data-topic|data-recommend|topic-id|style|class)=["'][^"']*["']/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
  return text;
}
function excerpt(v, max = 160) {
  const text = cleanText(v);
  if (text.length <= max) return text;
  let cut = text.slice(0, max);
  const stops = ["。", "；", "，", ".", ";", ","].map((mark) => cut.lastIndexOf(mark));
  const stop = Math.max(...stops);
  if (stop > max * 0.55) cut = cut.slice(0, stop + 1);
  return `${cut.replace(/[，。；,.;、\s]+$/g, "")}…`;
}
function fmtDate(v) {
  const d = new Date(v || "");
  return Number.isNaN(d.getTime()) ? "--" : d.toLocaleString("zh-CN", { hour12: false });
}
function score(v) {
  const n = Number(v || 0);
  return Number.isFinite(n) ? n.toFixed(1) : "0.0";
}
function int(v) {
  const n = Number(v || 0);
  return Number.isFinite(n) ? Math.round(n).toLocaleString("zh-CN") : "0";
}
function statusText(v) {
  return ({
    active: "正常",
    ready: "待运行",
    ready_for_collect: "待采集",
    waiting_for_collect: "待同步",
    waiting_for_sources: "待接源",
    auth_required: "待授权",
    billing_attention: "余额不足",
    not_configured: "未配置",
    ok: "正常",
    error: "异常",
  }[v] || v || "未知");
}
function tone(v) {
  const text = String(v || "");
  if (["active", "ok", "good", "authorized"].includes(text)) return "good";
  if (["ready", "configured", "info"].includes(text)) return "brand";
  if (["billing_attention", "auth_required", "error", "warn"].includes(text) || text.includes("fail")) return "warn";
  return "";
}
function kpi(label, value, hint = "", cls = "") {
  return `<div class="kpi ${cls}"><span>${esc(label)}</span><strong>${esc(value)}</strong>${hint ? `<small>${esc(hint)}</small>` : ""}</div>`;
}
function moduleCards(modules = []) {
  return `<section class="module-grid">${modules.map((m) => `<article class="module-card">
    <div class="module-head"><strong>${esc(m.name || m.code)}</strong><span class="badge ${tone(m.status)}">${esc(statusText(m.status))}</span></div>
    <div class="module-count">${int(m.count)}</div>
    <p>${esc(m.description || moduleHint(m.code))}</p>
  </article>`).join("")}</section>`;
}
function moduleHint(code) {
  return ({
    feed: "统一整合全部非 X 动态，按时间和综合质量进入全量池。",
    selected: "从全量候选中筛出高可信、高影响、近期且有明确 AI 价值的内容。",
    daily: "按模型发布、产品工具、开发者、研究、社区、行业分组生成日报。",
    mp: "只使用授权公众号源和自有兼容源，按热度、AI 相关度和异常传播筛选。",
    opcSolo: "跨所有频道筛选一人公司、独立开发、自动化、获客和交付相关信息。",
    sources: "跟踪采集信源状态、耗时、最近返回条数和异常。",
    strategy: "沉淀栏目规则、权重、模型判断和人工反馈。",
  }[code] || "");
}
function recommendationPanel(items = []) {
  if (!items.length) return "";
  return `<section class="panel"><div class="section-head"><h2>建议动作</h2><span class="badge">自动诊断</span></div><div class="rec-list">${items.map((item) => `<div class="rec ${tone(item.level)}"><strong>${esc(item.title)}</strong><p>${esc(item.detail)}</p></div>`).join("")}</div></section>`;
}
function modelStatusPanel(model = {}) {
  return `<section class="panel"><div class="section-head"><h2>DeepSeek 模型链路</h2><span class="badge ${tone(model.status)}">${esc(model.label || statusText(model.status))}</span></div>
    <div class="grid three">
      ${kpi("模型", model.model || "-", `${model.thinking || "-"} / ${model.reasoningEffort || "-"}`)}
      ${kpi("全量处理成功", int(model.itemEnrichments?.ok), `错误 ${int(model.itemEnrichments?.error)}`)}
      ${kpi("公众号处理成功", int(model.mpEnrichments?.ok), `错误 ${int(model.mpEnrichments?.error)}`)}
    </div>
    ${model.latestError ? `<pre class="compact-log">${esc(model.latestError)}</pre>` : ""}
  </section>`;
}
function channelMetricPanel(metrics = []) {
  return `<section class="panel"><div class="section-head"><h2>栏目运行指标</h2><span class="badge">独立筛选视图</span></div>
    <div class="metric-grid">${metrics.map((m) => `<article class="metric-card">
      <div class="module-head"><strong>${esc(m.name || channelLabel(m.channel))}</strong><span class="score mini">${score(m.avgScore)}</span></div>
      <div class="metric-row"><span>成品</span><b>${int(m.itemCount)}</b><span>候选</span><b>${int(m.candidateCount)}</b><span>入选</span><b>${int(m.selectedCandidateCount)}</b></div>
      <p class="summary">最新 ${fmtDate(m.newestAt)}，最高分 ${score(m.maxScore)}</p>
      <div class="meta">${(m.topSources || []).map((s) => `<span class="badge">${esc(s.name)} ${int(s.count)}</span>`).join("")}</div>
    </article>`).join("")}</div>
  </section>`;
}
function healthPanel(health = {}) {
  const statuses = Object.entries(health.byStatus || {});
  const attention = health.attention || [];
  return `<section class="panel"><div class="section-head"><h2>信源健康</h2><span class="badge">最近 ${int(health.latestTotal)} 个源</span></div>
    <div class="meta">${statuses.map(([name, count]) => `<span class="badge ${tone(name)}">${esc(statusText(name))} ${int(count)}</span>`).join("")}</div>
    ${attention.length ? `<table class="table compact"><thead><tr><th>信源</th><th>频道</th><th>状态</th><th>详情</th></tr></thead><tbody>${attention.map((r) => `<tr><td>${esc(r.sourceName)}</td><td>${esc(channelLabel(r.channel))}</td><td>${esc(statusText(r.status))}</td><td>${esc(r.detail || "")}</td></tr>`).join("")}</tbody></table>` : `<p class="summary">最近健康记录没有需要特别处理的异常。</p>`}
  </section>`;
}
function tableWrap(html) {
  return `<div class="table-wrap">${html}</div>`;
}
function moduleByCode(modules = [], code) {
  return modules.find((item) => item.code === code) || {};
}
function compactSignal(item = {}) {
  const title = excerpt(item.titleZh || item.title || "未命名", 68);
  const source = excerpt(item.sourceName || item.accountName || item.source?.name || "Source", 24);
  const value = item.channelScore ?? item.finalScore ?? item.heatScore;
  return `<a class="signal-row" href="${esc(item.url || item.link || "#")}" target="_blank" rel="noopener noreferrer">
    <span>${esc(title)}</span>
    <small>${esc(source)} · ${score(value)}</small>
  </a>`;
}
function metricBar(metric = {}) {
  const max = Math.max(1, Number(metric.candidateCount || metric.itemCount || 1));
  const width = Math.max(8, Math.min(100, (Number(metric.itemCount || 0) / max) * 100));
  return `<div class="radar-line">
    <div><strong>${esc(metric.name || channelLabel(metric.channel))}</strong><span>${int(metric.itemCount)} / ${int(metric.candidateCount)}</span></div>
    <i><b style="width:${width}%"></b></i>
  </div>`;
}
function homePanel(title, items = [], route = "") {
  return `<section class="panel live-panel"><div class="section-head"><h2>${esc(title)}</h2>${route ? `<a class="text-link" href="${BASE}${route}" data-route="${route}">查看</a>` : ""}</div>
    <div class="signal-list">${items.length ? items.map(compactSignal).join("") : `<p class="summary">暂无实时条目。</p>`}</div>
  </section>`;
}
function itemText(item = {}) {
  return cleanText(`${item.titleZh || item.title || ""} ${item.summaryZh || item.summary || ""} ${(item.aiTags || item.tags || []).map((t) => t?.tag || t).join(" ")}`).toLowerCase();
}
function scoreValue(item = {}) {
  const n = Number(item.channelScore ?? item.opcSoloScore ?? item.finalScore ?? item.heatScore ?? 0);
  return Number.isFinite(n) ? n : 0;
}
function countBy(items = [], pick) {
  return items.reduce((acc, item) => {
    const key = pick(item) || "其他";
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
}
function topEntries(obj = {}, limit = 6) {
  return Object.entries(obj).sort((a, b) => b[1] - a[1]).slice(0, limit);
}
function ratio(part, total) {
  const n = total ? (Number(part || 0) / Number(total || 1)) * 100 : 0;
  return Math.max(4, Math.min(100, n));
}
function scoreBands(items = []) {
  return [
    ["90+", items.filter((item) => scoreValue(item) >= 90).length],
    ["80-89", items.filter((item) => scoreValue(item) >= 80 && scoreValue(item) < 90).length],
    ["70-79", items.filter((item) => scoreValue(item) >= 70 && scoreValue(item) < 80).length],
    ["<70", items.filter((item) => scoreValue(item) < 70).length],
  ];
}
function miniStat(label, value, hint = "") {
  return `<div class="mini-stat"><span>${esc(label)}</span><strong>${esc(value)}</strong>${hint ? `<small>${esc(hint)}</small>` : ""}</div>`;
}
function mixPanel(title, items = [], pick, label = (x) => x) {
  const total = items.length;
  const rows = topEntries(countBy(items, pick), 7);
  return `<section class="panel insight-panel"><div class="section-head"><h2>${esc(title)}</h2><span class="badge">${int(total)} 条</span></div>
    <div class="bar-list">${rows.map(([name, count]) => `<div class="bar-row"><div><strong>${esc(label(name))}</strong><span>${int(count)}</span></div><i><b style="width:${ratio(count, total)}%"></b></i></div>`).join("") || `<p class="summary">等待更多样本。</p>`}</div>
  </section>`;
}
function scorePanel(title, items = []) {
  const total = Math.max(1, items.length);
  return `<section class="panel insight-panel"><div class="section-head"><h2>${esc(title)}</h2><span class="badge">分数带</span></div>
    <div class="score-bands">${scoreBands(items).map(([name, count]) => `<div><span>${esc(name)}</span><strong>${int(count)}</strong><i style="height:${ratio(count, total)}%"></i></div>`).join("")}</div>
  </section>`;
}
function pulsePanel(title, items = [], route = "") {
  return `<section class="panel pulse-panel"><div class="section-head"><h2>${esc(title)}</h2>${route ? `<a class="text-link" href="${BASE}${route}" data-route="${route}">进入</a>` : ""}</div>
    <div class="pulse-list">${items.slice(0, 6).map((item) => `<a class="pulse-row" href="${esc(item.url || item.link || "#")}" target="_blank" rel="noopener noreferrer"><b>${score(scoreValue(item))}</b><span>${esc(excerpt(item.titleZh || item.title || "未命名", 82))}</span><small>${esc(excerpt(item.sourceName || item.accountName || item.source?.name || "Source", 28))}</small></a>`).join("") || `<p class="summary">暂无实时信号。</p>`}</div>
  </section>`;
}
function channelCards(modules = {}) {
  const cards = modules.modules || [];
  const metrics = modules.channelMetrics || [];
  const mapMetric = (code) => metrics.find((item) => item.channel === code) || {};
  const rows = [
    ["selected", "精选", "高分、近期、可信且具备 AI 价值的跨源信号", "/selected"],
    ["feed", "全部 AI 动态", "非 X 全量时间线，保留原始动态密度", "/all"],
    ["daily", "AI 日报", "按独立栏目压缩成每日简报和存档", "/daily"],
    ["mp", "公众号爆文", "授权公众号和自有兼容源的中文内容池", "/mp"],
    ["opcSolo", "OPC一人公司", "面向一人公司构建、获客、自动化和交付", "/opc"],
  ];
  return `<section class="channel-strip">${rows.map(([code, name, desc, route]) => {
    const module = moduleByCode(cards, code);
    const metric = mapMetric(code);
    return `<a class="lane-card" href="${BASE}${route}" data-route="${route}">
      <span>${esc(name)}</span>
      <strong>${int(module.count || metric.itemCount || 0)}</strong>
      <small>${esc(desc)}</small>
    </a>`;
  }).join("")}</section>`;
}
function keywordLens(items = [], lanes = []) {
  return lanes.map(([code, name, words]) => {
    const count = items.filter((item) => words.some((word) => itemText(item).includes(word.toLowerCase()))).length;
    return { code, name, count, words };
  });
}
function lensPanel(title, items = [], lanes = []) {
  const lens = keywordLens(items, lanes);
  const total = Math.max(1, items.length);
  return `<section class="panel lens-panel"><div class="section-head"><h2>${esc(title)}</h2><span class="badge">${int(items.length)} 条动态计算</span></div>
    <div class="lens-grid">${lens.map((row) => `<div class="lens-cell"><div><strong>${esc(row.name)}</strong><span>${int(row.count)}</span></div><i><b style="width:${ratio(row.count, total)}%"></b></i><small>${esc(row.words.slice(0, 5).join(" / "))}</small></div>`).join("")}</div>
  </section>`;
}
const OPC_LANES = [
  ["build", "产品构建", ["产品", "工具", "app", "saas", "mvp", "开发", "网站", "插件", "github", "开源"]],
  ["automation", "自动化", ["自动化", "agent", "workflow", "工作流", "脚本", "api", "集成", "低代码"]],
  ["growth", "获客增长", ["获客", "营销", "增长", "投放", "私域", "流量", "转化", "seo"]],
  ["content", "内容生产", ["内容", "视频", "文案", "公众号", "写作", "生成", "素材", "剪辑"]],
  ["ops", "运营交付", ["运营", "客服", "交付", "订单", "客户", "数据", "报表", "复盘"]],
];
const MP_LANES = [
  ["model", "模型与Agent", ["模型", "agent", "智能体", "大模型", "推理", "deepseek", "openai"]],
  ["product", "产品工具", ["产品", "工具", "插件", "应用", "工作流", "自动化"]],
  ["business", "商业案例", ["创业", "商业", "公司", "增长", "收入", "案例", "获客"]],
  ["dev", "开发工程", ["开发", "工程", "代码", "github", "api", "部署", "框架"]],
];
function channelLabel(v) {
  return ({ all: "全部", firstParty: "官方", news: "资讯", github: "GitHub", product: "产品/工具", community: "社区/论文", mp: "公众号", opcSolo: "OPC一人公司", x: "X", model_release: "模型发布/更新", product_tool: "产品与工具", research_paper: "论文/研究", developer: "开发者与开源", industry: "行业/商业/监管" }[v] || v || "其他");
}
function originLabel(v) {
  return ({ dynamic_collector: "动态采集", manual_import: "人工导入", third_party_api: "第三方 API" }[v] || v || "来源待定");
}
async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const res = await fetch(`${API}${path}`, { ...options, headers, cache: "no-store" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.message || data.error || `HTTP ${res.status}`);
  return data;
}
function setChrome(title, eyebrow = "AI SIGNAL DESK", toolbar = "") {
  $("#pageTitle").textContent = title;
  $("#eyebrow").textContent = eyebrow;
  $("#toolbar").innerHTML = toolbar;
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === state.route));
}
function loading() {
  $("#app").innerHTML = `<div class="empty">正在读取数据...</div>`;
}
function errorView(err) {
  $("#app").innerHTML = `<div class="empty">${esc(err.message || err)}</div>`;
}
function renderTags(item) {
  return (item.aiTags || []).slice(0, 5).map((t) => `<span class="badge">${esc(excerpt(t?.tag || t, 18))}</span>`).join("");
}
function renderAxes(item) {
  const axes = item.qualityAxesJson || {};
  const labels = { act: "行动", nov: "新颖", sig: "重要", cred: "可信", reson: "共振" };
  return Object.entries(labels).map(([key, label]) => `<span class="axis"><b>${label}</b>${esc(axes[key] ?? "-")}</span>`).join("");
}
function itemCard(item, admin = false) {
  const url = item.url || item.link || "#";
  const title = excerpt(item.titleZh || item.title || "未命名", 86);
  const summary = excerpt(item.summaryZh || item.summary || "", 128);
  const selected = item.aiSelected ? `<span class="badge good">精选</span>` : "";
  const sourceName = excerpt(item.sourceName || item.source?.name || item.source || "Source", 28);
  const duplicate = item.duplicateCount ? `<span class="badge warn">关联讨论 ${item.duplicateCount} 条</span>` : "";
  const scoreValue = item.channelScore ?? item.opcSoloScore ?? item.finalScore ?? item.heatScore;
  const reasons = item.channelReasons || [];
  const edit = admin ? `<button data-action="toggle-select" data-id="${item.id}" data-selected="${item.aiSelected ? 1 : 0}">${item.aiSelected ? "取消精选" : "设为精选"}</button> <button data-action="trace-item" data-id="${item.id}">追溯</button>` : "";
  return `<article class="item">
    <div class="item-head">
      <div>
        <div class="item-title"><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(title)}</a></div>
        <p class="summary">${esc(summary)}</p>
      </div>
      <div class="score">${score(scoreValue)}</div>
    </div>
    <div class="meta">
      ${selected}<span class="badge brand">${esc(channelLabel(item.channel))}</span><span class="badge good">${esc(originLabel(item.sourceOrigin))}</span><span class="badge">${esc(sourceName)}</span><span class="badge">${esc(item.timeLabel || fmtDate(item.publishedAt))}</span>${duplicate}${renderTags(item)}
    </div>
    <div class="axes">${renderAxes(item)}</div>
    ${reasons.length ? `<div class="meta">${reasons.slice(0, 4).map((reason) => `<span class="badge">${esc(excerpt(reason, 26))}</span>`).join("")}</div>` : ""}
    ${item.aiSelectedReason ? `<p class="summary reason">${esc(excerpt(item.aiSelectedReason, 90))}</p>` : ""}
    ${edit ? `<div>${edit}</div>` : ""}
  </article>`;
}
async function refreshSourceMini() {
  try {
    const data = await api("/public/sources");
    const total = data.summary?.total || 0;
    const ok = data.summary?.byStatus?.ok || 0;
    $("#sourceMini").innerHTML = `<div class="eyebrow">信源健康</div><strong>${ok}/${total}</strong><div>非 X 信源在线状态</div>`;
  } catch {
    $("#sourceMini").innerHTML = `<div class="eyebrow">信源健康</div><div>等待 API</div>`;
  }
}
async function renderHome() {
  setChrome("AI HOT", "实时情报台", `<button data-route="/selected">进入精选</button><button data-route="/daily">今日日报</button><button data-refresh>刷新</button>`);
  loading();
  try {
    const [modules, selected, all, mp, opc, daily] = await Promise.all([
      api("/public/modules"),
      api("/public/feed?mode=selected&channel=all&limit=8&q="),
      api("/public/feed?mode=all&channel=all&limit=8&q="),
      api("/public/mp?limit=8&period=all"),
      api("/public/feed?mode=all&channel=opcSolo&limit=6&q="),
      api("/public/daily/latest"),
    ]);
    const cards = modules.modules || [];
    const health = modules.sourceHealth || {};
    const model = modules.modelStatus || {};
    const quality = modules.quality || {};
    const selectedItems = selected.items || [];
    const allItems = all.items || [];
    const mpItems = mp.items || [];
    const opcItems = opc.items || [];
    const lead = selectedItems[0] || allItems[0] || {};
    const leadTitle = excerpt(lead.titleZh || lead.title || "等待实时信号", 96);
    const leadSource = excerpt(lead.sourceName || lead.source?.name || "AI HOT", 32);
    const leadReason = excerpt(lead.aiSelectedReason || (lead.channelReasons || [])[0] || "高分候选进入实时情报台。", 180);
    const feedCount = moduleByCode(cards, "feed").count || 0;
    const selectedCount = moduleByCode(cards, "selected").count || 0;
    const mpCount = moduleByCode(cards, "mp").count || 0;
    const opcCount = moduleByCode(cards, "opcSolo").count || 0;
    const sourceSummary = modules.sourceSummary || {};
    const sourceOk = (sourceSummary.byStatus || {}).ok || (health.byStatus || {}).ok || 0;
    const sourceTotal = sourceSummary.total || health.latestTotal || moduleByCode(cards, "sources").count || 0;
    const pulseItems = [...selectedItems.slice(0, 3), ...mpItems.slice(0, 3), ...opcItems.slice(0, 3)];
    $("#app").innerHTML = `
      <section class="home-hero">
        <div class="hero-main">
          <div class="meta"><span class="badge brand">LIVE</span><span class="badge">${fmtDate(modules.generatedAt || quality.newestItemAt)}</span><span class="badge ${tone(model.status)}">${esc(model.label || statusText(model.status))}</span></div>
          <h2>今日 AI 情报运行态</h2>
          <p>${esc(excerpt(daily.summary || "系统正在聚合官方、开源、社区、产品和公众号信号。", 150))}</p>
        </div>
        <div class="hero-tape">
          ${kpi("全量动态", int(feedCount), `最新 ${fmtDate(quality.newestItemAt)}`)}
          ${kpi("精选信号", int(selectedCount), "编辑级候选")}
          ${kpi("公众号爆文", int(mpCount), `${int(mp.sourceSummary?.summary?.configured)} 个源`)}
          ${kpi("OPC机会", int(opcCount), "一人公司筛选")}
        </div>
      </section>
      <section class="home-grid-main">
        <article class="headline-card">
          <div class="section-head"><h2>头条信号</h2><span class="score">${score(lead.channelScore ?? lead.finalScore)}</span></div>
          <a class="headline-title" href="${esc(lead.url || lead.link || "#")}" target="_blank" rel="noopener noreferrer">${esc(leadTitle)}</a>
          <p>${esc(excerpt(lead.summaryZh || lead.summary || leadReason, 150))}</p>
          <div class="meta"><span class="badge brand">${esc(channelLabel(lead.channel))}</span><span class="badge">${esc(leadSource)}</span><span class="badge">${fmtDate(lead.publishedAt)}</span></div>
        </article>
        <aside class="dashboard-rail">
          <div class="rail-card"><span>信源健康</span><strong>${int(sourceOk)}/${int(sourceTotal)}</strong><small>${fmtDate(health.lastCheckedAt)}</small></div>
          <div class="rail-card"><span>日报期号</span><strong>${esc(daily.issueDate || "--")}</strong><small>${esc((daily.content?.strategy || "independent_channel_items"))}</small></div>
          <div class="rail-card"><span>DeepSeek</span><strong>${esc(model.label || statusText(model.status))}</strong><small>${esc(model.model || "-")}</small></div>
        </aside>
      </section>
      ${channelCards(modules)}
      <section class="grid three">
        ${homePanel("精选正在看", selectedItems.slice(1, 6), "/selected")}
        ${homePanel("中文圈热文", mpItems.slice(0, 5), "/mp")}
        ${homePanel("OPC机会", opcItems.slice(0, 5), "/opc")}
      </section>
      <section class="grid three">
        ${mixPanel("全量信号构成", allItems, (item) => item.channel, channelLabel)}
        ${scorePanel("精选强度", selectedItems)}
        ${mixPanel("公众号账号热度", mpItems, (item) => item.accountName || item.sourceName || "未知公众号")}
      </section>
      ${lensPanel("OPC机会雷达", opcItems, OPC_LANES)}
      ${pulsePanel("最新脉冲", pulseItems)}
      <section class="panel"><div class="section-head"><h2>栏目仪表盘</h2><span class="badge">实时视图</span></div><div class="radar-board">${(modules.channelMetrics || []).map(metricBar).join("")}</div></section>
      ${recommendationPanel(modules.recommendations || [])}
    `;
    document.querySelectorAll("button[data-route]").forEach((btn) => btn.onclick = () => go(btn.dataset.route));
  } catch (err) {
    errorView(err);
  }
}
async function renderFeed(mode, append = false) {
  const selected = mode === "selected";
  const channels = ["all", "firstParty", "news", "github", "product", "community"];
  setChrome(selected ? "精选" : "全部 AI 动态", selected ? "精选信号" : "实时信号流", `<div class="segmented">${channels.map((c) => `<button data-channel="${c}" class="${state.channel === c ? "active" : ""}">${channelLabel(c)}</button>`).join("")}</div><input id="feedSearch" placeholder="搜索标题、摘要或信源" value="${esc(state.q)}"><button data-refresh>刷新</button>`);
  if (!append) {
    loading();
    state.feedItems = [];
    state.nextCursor = null;
  }
  document.querySelectorAll("[data-channel]").forEach((btn) => btn.onclick = () => { state.channel = btn.dataset.channel; renderFeed(mode, false); });
  $("#feedSearch").onkeydown = (event) => {
    if (event.key === "Enter") {
      state.q = event.currentTarget.value.trim();
      renderFeed(mode, false);
    }
  };
  try {
    const cursor = append && state.nextCursor ? `&cursorAt=${encodeURIComponent(state.nextCursor.at)}&cursorId=${encodeURIComponent(state.nextCursor.id)}` : "";
    const data = await api(`/public/feed?mode=${mode}&channel=${encodeURIComponent(state.channel)}&limit=30&q=${encodeURIComponent(state.q)}${cursor}`);
    const items = data.items || [];
    state.feedItems = append ? [...state.feedItems, ...items] : items;
    state.nextCursor = data.nextCursor || null;
    const loadMore = state.nextCursor ? `<div class="loadmore"><button id="loadMore">加载更多</button></div>` : "";
    const rule = data.channelRule || {};
    const insightPanel = !append ? `<section class="grid three">${mixPanel("当前页频道构成", items, (item) => item.channel, channelLabel)}${mixPanel("当前页信源构成", items, (item) => item.sourceName || item.source?.name || "Source")}${scorePanel("当前页分数带", items)}</section>` : "";
    const rulePanel = !append ? `<section class="panel"><div class="meta"><span class="badge brand">${esc(rule.name || channelLabel(state.channel))}</span><span class="badge">当前返回 ${items.length} 条</span><span class="badge">命中总数 ${data.filteredCount || items.length}</span>${data.hasNext ? `<span class="badge">还有更多</span>` : ""}</div><p class="summary">${esc(rule.description || "")}</p><div class="meta">${(rule.include || []).slice(0, 6).map((x) => `<span class="badge">${esc(x)}</span>`).join("")}</div></section>` : "";
    $("#app").innerHTML = state.feedItems.length ? `${insightPanel}${rulePanel}<section class="grid">${state.feedItems.map((item) => itemCard(item)).join("")}</section>${loadMore}` : `${rulePanel}<div class="empty">暂无数据</div>`;
    $("#loadMore")?.addEventListener("click", () => renderFeed(mode, true));
  } catch (err) {
    errorView(err);
  }
}
async function renderOpc() {
  setChrome("OPC一人公司", "一人公司雷达", `<input id="feedSearch" placeholder="搜索产品、自动化、获客、Agent" value="${esc(state.q)}"><button data-refresh>刷新</button>`);
  loading();
  $("#feedSearch").onkeydown = (event) => {
    if (event.key === "Enter") {
      state.q = event.currentTarget.value.trim();
      renderOpc();
    }
  };
  try {
    const data = await api(`/public/feed?mode=all&channel=opcSolo&limit=60&q=${encodeURIComponent(state.q)}`);
    const items = data.items || [];
    $("#app").innerHTML = items.length
      ? `<section class="panel"><div class="meta"><span class="badge brand">全信源动态筛选</span><span class="badge">阈值 ${esc(data.logic?.threshold || "-")}</span><span class="badge">当前 ${items.length} 条</span></div><p class="summary">从全部非 X 动态和公众号动态源中筛选可服务一人公司的产品构建、自动化、获客、内容、运营和交付信号。</p></section>${lensPanel("机会类型拆分", items, OPC_LANES)}<section class="grid two">${mixPanel("机会来源", items, (item) => item.sourceName || item.accountName || item.source?.name || "Source")}${scorePanel("机会强度", items)}</section><section class="grid">${items.map((item) => itemCard(item)).join("")}</section>`
      : `<div class="empty">当前没有命中 OPC一人公司 筛选阈值的动态内容。系统会在后续采集和公众号动态源接入后继续自动分析。</div>`;
  } catch (err) {
    errorView(err);
  }
}
async function renderDaily() {
  setChrome("AI 日报", "每日简报", `<button data-refresh>刷新</button>`);
  loading();
  try {
    const [data, archive] = await Promise.all([
      api(`/public/daily/latest${state.dailyDate ? `?date=${encodeURIComponent(state.dailyDate)}` : ""}`),
      api("/public/daily/list?limit=30"),
    ]);
    const groups = data.content?.groups || {};
    const cards = Object.entries(groups).map(([channel, items]) => `<section class="panel"><h2>${channelLabel(channel)}</h2><div class="grid">${items.slice(0, 8).map((item) => itemCard(item)).join("")}</div></section>`).join("");
    const dates = (archive.items || []).map((issue) => `<button data-daily-date="${esc(issue.issueDate)}" class="${issue.issueDate === data.issueDate ? "primary" : ""}">${esc(issue.issueDate.slice(5))}</button>`).join("");
    $("#app").innerHTML = `<section class="daily-shell"><aside class="daily-rail">${dates || `<button class="primary">${esc(data.issueDate.slice(5))}</button>`}</aside><div class="daily-main"><section class="panel"><div class="meta"><span class="badge brand">VOL ${esc(data.issueDate.replaceAll("-", ""))}</span><span class="badge">${esc(data.issueDate)}</span><span class="badge">${fmtDate(data.generatedAt)}</span></div><h2>${esc(data.title)}</h2><p class="summary">${esc(data.summary || "")}</p></section>${cards}<pre class="markdown">${esc(data.markdown || "")}</pre></div></section>`;
    document.querySelectorAll("[data-daily-date]").forEach((btn) => btn.onclick = () => { state.dailyDate = btn.dataset.dailyDate; renderDaily(); });
  } catch (err) {
    errorView(err);
  }
}
async function renderMp() {
  const periods = [["24h", "过去24h"], ["7d", "过去7天"], ["30d", "过去30天"], ["1y", "过去1年"], ["all", "全部"]];
  setChrome("公众号爆文", "公众号频道", `<div class="segmented">${periods.map(([code, label]) => `<button data-mp-period="${code}" class="${state.mpPeriod === code ? "active" : ""}">${label}</button>`).join("")}</div><button data-refresh>刷新</button>`);
  loading();
  document.querySelectorAll("[data-mp-period]").forEach((btn) => btn.onclick = () => { state.mpPeriod = btn.dataset.mpPeriod; renderMp(); });
  try {
    const data = await api(`/public/mp?limit=80&period=${encodeURIComponent(state.mpPeriod)}`);
    const items = data.items || [];
    const sourceSummary = data.sourceSummary?.summary || {};
    const accountCounts = items.reduce((acc, item) => {
      const name = item.accountName || "未知公众号";
      acc[name] = (acc[name] || 0) + 1;
      return acc;
    }, {});
    const accountBadges = Object.entries(accountCounts).sort((a, b) => b[1] - a[1]).slice(0, 12).map(([name, count]) => `<span class="badge">${esc(name)} ${int(count)}</span>`).join("");
    const statusLabel = {
      active: "正常",
      ready_for_collect: "待采集",
      auth_required: "待授权",
      waiting_for_collect: "待同步",
      waiting_for_sources: "待接源",
    }[data.sourceStatus] || "等待动态数据";
    const sourceMeta = `<section class="grid three">
      ${kpi("频道成品", int(data.count), "独立公众号筛选结果", "hot")}
      ${kpi("真实公众号源", int(sourceSummary.configured), `可采集 ${int(sourceSummary.ready)}`)}
      ${kpi("最近同步", fmtDate(sourceSummary.lastCheckedAt || data.lastFetchAt), statusLabel)}
    </section>
    <section class="panel"><div class="section-head"><h2>公众号筛选逻辑</h2><span class="badge ${data.sourceStatus === "active" ? "good" : "warn"}">${statusLabel}</span></div><p class="summary">只从授权公众号源和自有兼容源中取真实文章，按 AI 相关度、账号可信度、时效、热度、异常传播、工具/Agent/模型关键词进行独立筛选。</p><div class="meta">${accountBadges}</div></section>`;
    const mpInsights = `${lensPanel("公众号内容类型", items, MP_LANES)}<section class="grid two">${mixPanel("账号贡献", items, (item) => item.accountName || "未知公众号")}${scorePanel("爆文强度", items)}</section>`;
    if (!items.length) {
      const emptyMessage = data.sourceStatus === "auth_required"
        ? "公众号信息源已经就绪，但后台还需要先完成微信公众平台授权，之后才能搜索公众号并同步最近文章。"
        : data.sourceStatus === "ready_for_collect" || data.sourceStatus === "waiting_for_collect"
          ? "公众号源已经登记完成，但还没有执行同步。请到后台运行公众号源同步或频道采集。"
          : "公众号爆文模块已启用，但当前还没有真实动态来源数据。请在后台登记公众号源或接入兼容 RSS/JSON/API。";
      $("#app").innerHTML = `${sourceMeta}${mpInsights}<div class="empty">${emptyMessage}</div>`;
      return;
    }
    $("#app").innerHTML = `${sourceMeta}${mpInsights}
      <section class="grid">${items.slice(0, 12).map((item) => `<article class="item">
        <div class="item-head"><div><div class="item-title"><a href="${esc(item.url || "#")}" target="_blank" rel="noopener noreferrer">${esc(excerpt(item.title, 86))}</a></div><p class="summary">${esc(excerpt(item.summary || "", 128))}</p></div><div class="score">${score(item.heatScore)}</div></div>
        <div class="meta"><span class="badge brand">${esc(excerpt(item.accountName, 28))}</span><span class="badge good">${esc(originLabel(item.sourceOrigin))}</span><span class="badge">${fmtDate(item.publishedAt)}</span>${item.original ? `<span class="badge good">原创</span>` : ""}${(item.tags || []).slice(0, 5).map((tag) => `<span class="badge">${esc(excerpt(tag, 18))}</span>`).join("")}</div>
      </article>`).join("")}</section>
      <section class="panel">${tableWrap(`<table class="table"><thead><tr><th>发文日期</th><th>标题</th><th>公众号</th><th>热度</th><th>异常值</th><th>互动</th></tr></thead><tbody>${items.map((item) => `<tr><td>${fmtDate(item.publishedAt).slice(0, 10)}</td><td><a href="${esc(item.url || "#")}" target="_blank" rel="noopener noreferrer"><strong>${esc(excerpt(item.title, 88))}</strong></a></td><td>${esc(excerpt(item.accountName || "", 28))}</td><td>${score(item.heatScore)}</td><td>${score(item.anomalyScore)}</td><td>${item.reads ?? ""} / ${item.likes ?? ""} / ${item.shares ?? ""}</td></tr>`).join("")}</tbody></table>`)}</section>`;
  } catch (err) {
    errorView(err);
  }
}
async function renderAbout() {
  setChrome("关于", "系统总览");
  loading();
  try {
    const [sources, modules] = await Promise.all([api("/public/sources"), api("/public/modules")]);
    const byChannel = sources.summary?.byChannel || {};
    $("#app").innerHTML = `
      ${moduleCards(modules.modules || [])}
      ${recommendationPanel(modules.recommendations || [])}
      ${channelMetricPanel(modules.channelMetrics || [])}
      ${modelStatusPanel(modules.modelStatus || {})}
      ${healthPanel(modules.sourceHealth || {})}
      <section class="panel"><div class="section-head"><h2>信源分布</h2><span class="badge">公共信源 ${int(sources.summary?.total)}</span></div><div class="grid three">${Object.entries(byChannel).map(([k, v]) => kpi(channelLabel(k), int(v))).join("")}</div></section>
      <section class="panel"><div class="section-head"><h2>栏目规则</h2><span class="badge">可解释筛选</span></div>${tableWrap(`<table class="table"><thead><tr><th>栏目</th><th>处理逻辑</th><th>纳入信号</th></tr></thead><tbody>${(modules.channelRules || []).map((r) => `<tr><td>${esc(r.name)}</td><td>${esc(r.description)}</td><td>${esc((r.include || []).join(" / "))}</td></tr>`).join("")}</tbody></table>`)}</section>
      <section class="panel"><div class="section-head"><h2>信源明细</h2><span class="badge">非 X 动态源</span></div>${tableWrap(`<table class="table"><thead><tr><th>名称</th><th>频道</th><th>类型</th><th>状态</th><th>数量</th></tr></thead><tbody>${(sources.sources || []).map((s) => `<tr><td>${esc(s.name)}</td><td>${channelLabel(s.channel)}</td><td>${esc(s.source_kind || "")}</td><td>${esc(statusText(s.last_status))}</td><td>${s.last_count || 0}</td></tr>`).join("")}</tbody></table>`)}</section>`;
  } catch (err) {
    errorView(err);
  }
}
function renderFeedback() {
  setChrome("反馈", "反馈中心");
  $("#app").innerHTML = `<form class="panel form" id="feedbackForm"><div class="field"><label>类型</label><select name="vote"><option value="useful">有价值</option><option value="missing">漏收重要信息</option><option value="wrong">分类/精选不准确</option></select></div><div class="field"><label>内容</label><textarea name="reason"></textarea></div><button class="primary" type="submit">提交</button></form>`;
  $("#feedbackForm").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    await api("/public/feedback", { method: "POST", body: JSON.stringify(Object.fromEntries(fd.entries())) });
    e.target.innerHTML = `<div class="notice">已提交</div>`;
  };
}
function loginForm() {
  setChrome("后台管理", "后台");
  $("#app").innerHTML = `<form class="panel form" id="loginForm"><div class="field"><label>用户名</label><input name="username" autocomplete="username" value="admin"></div><div class="field"><label>密码</label><input name="password" type="password" autocomplete="current-password"></div><button class="primary" type="submit">登录</button></form>`;
  $("#loginForm").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      const data = await api("/admin/login", { method: "POST", body: JSON.stringify(Object.fromEntries(fd.entries())) });
      state.token = data.token;
      localStorage.setItem("aihot_admin_token", state.token);
      renderAdmin();
    } catch (err) {
      alert(err.message);
    }
  };
}
function adminTabs() {
  const tabs = [["overview", "总览"], ["sources", "信源"], ["health", "健康"], ["items", "文章"], ["daily", "日报"], ["mp", "公众号"], ["strategy", "策略"], ["enrich", "AI处理"], ["model", "模型评估"], ["pipeline", "流水线"], ["feedback", "反馈"], ["access", "访问"], ["users", "用户"], ["system", "系统"], ["audit", "审计"]];
  return `<div class="admin-tabs">${tabs.map(([id, label]) => `<button data-admin-tab="${id}" class="${state.adminTab === id ? "primary" : ""}">${label}</button>`).join("")}<button data-logout>退出</button></div>`;
}
function wechatAuthPanel(auth = {}) {
  const status = auth.status || "idle";
  const label = { idle: "未授权", waiting: "等待扫码", scanned: "已扫码待确认", authorized: "已授权" }[status] || status;
  const badge = status === "authorized" ? "good" : status === "waiting" || status === "scanned" ? "warn" : "";
  const account = auth.account || {};
  const meta = [];
  if (account.nickname || account.username) meta.push(`<span class="badge good">${esc(account.nickname || account.username)}</span>`);
  if (auth.expiresAt) meta.push(`<span class="badge">到期 ${fmtDate(auth.expiresAt)}</span>`);
  if (auth.updatedAt) meta.push(`<span class="badge">更新 ${fmtDate(auth.updatedAt)}</span>`);
  return `<section class="panel">
    <h2>微信公众平台授权</h2>
    <div class="meta"><span class="badge ${badge}">${esc(label)}</span>${meta.join("")}</div>
    ${auth.lastError ? `<p class="summary">${esc(auth.lastError)}</p>` : `<p class="summary">公众号搜索和文章同步依赖微信公众平台登录态。先扫码一次，后面就能直接按账号名称入池并抓最近文章。</p>`}
    ${auth.qrImageDataUrl ? `<div class="panel" style="max-width:280px"><img src="${auth.qrImageDataUrl}" alt="wechat auth qr" style="width:100%;display:block"></div>` : ""}
    <div class="actions"><button class="primary" data-action="start-wechat-auth">${status === "authorized" ? "重新授权" : "生成二维码"}</button><button data-action="refresh-wechat-auth">刷新状态</button><button data-action="clear-wechat-auth">清空授权</button></div>
  </section>`;
}
function wechatSearchPanel() {
  const meta = state.wechatSearchMeta || {};
  const items = state.wechatSearchResults || [];
  const table = items.length ? `<table class="table"><thead><tr><th>公众号</th><th>Alias</th><th>FakeID</th><th>简介</th><th>操作</th></tr></thead><tbody>${items.map((item, index) => `<tr><td><strong>${esc(item.accountName || "")}</strong><div class="meta">${item.biz ? `<span class="badge">${esc(item.biz)}</span>` : ""}</div></td><td>${esc(item.alias || "")}</td><td>${esc(item.fakeid || "")}</td><td>${esc(item.intro || "")}</td><td><button data-action="add-wechat-search-result" data-index="${index}">加入源池</button></td></tr>`).join("")}</tbody></table>` : `<div class="empty compact">先完成授权，再按公众号名称搜索。</div>`;
  return `<section class="panel form">
    <h2>按公众号名称搜索并加入源池</h2>
    <div class="grid two">
      <div class="field"><label>公众号名称</label><input id="wechatSourceSearchQuery" placeholder="例如：机器之心 / APPSO / 数字生命卡兹克"></div>
      <div class="field"><label>返回数量</label><input id="wechatSourceSearchLimit" type="number" min="1" max="20" value="10"></div>
    </div>
    <div class="actions"><button class="primary" data-action="search-wechat-sources">搜索公众号</button><button data-action="sync-wechat-sources">同步全部已启用源</button></div>
    ${meta.query ? `<div class="meta"><span class="badge">查询 ${esc(meta.query)}</span><span class="badge">结果 ${meta.items || 0}</span></div>` : ""}
    ${table}
  </section>`;
}
function wechatSyncResultPanel() {
  const result = state.wechatSyncResult;
  if (!result) return "";
  const errors = result.errors || [];
  return `<section class="panel"><h2>公众号同步结果</h2><div class="meta"><span class="badge good">检查 ${result.checked || 0}</span><span class="badge good">入库 ${result.imported || 0}</span><span class="badge">原始文章 ${result.rawArticles || 0}</span><span class="badge ${errors.length ? "warn" : "good"}">${esc(result.status || "ok")}</span></div>${errors.length ? `<pre class="markdown">${esc(JSON.stringify(errors, null, 2))}</pre>` : `<p class="summary">这次同步没有报错。</p>`}</section>`;
}
function wechatSourceEditor(source = {}) {
  const enabled = source.enabled === false ? "" : "checked";
  return `<section class="panel form">
    <h2>${source.uid ? "编辑公众号信息源" : "手工登记公众号信息源"}</h2>
    <div class="grid two">
      <div class="field"><label>源 UID</label><input id="wechatSourceUid" value="${esc(source.uid || "")}" placeholder="留空自动生成，更新时保持不变"></div>
      <div class="field"><label>公众号名称</label><input id="wechatSourceName" value="${esc(source.accountName || "")}" placeholder="公众号名称"></div>
      <div class="field"><label>Biz</label><input id="wechatSourceBiz" value="${esc(source.biz || "")}" placeholder="可选，推荐保存"></div>
      <div class="field"><label>Feed / Collector URL</label><input id="wechatSourceFeedUrl" value="${esc(source.feedUrl || "")}" placeholder="可选，后续可绑定 RSS / JSON / API 输出"></div>
      <div class="field"><label>采集提示</label><input id="wechatSourceCollectorHint" value="${esc(source.collectorHint || "")}" placeholder="manual / wechat_public_article / rsshub"></div>
      <div class="field"><label>样本文章链接</label><input id="wechatSourceSampleUrl" value="${esc(source.sampleArticleUrl || "")}" placeholder="可选，用于记录发现入口"></div>
    </div>
    <label class="checkline"><input id="wechatSourceEnabled" type="checkbox" ${enabled}> 启用该信息源</label>
    <div class="field"><label>备注</label><textarea id="wechatSourceNote" placeholder="记录授权方式、定位、归类、风险等">${esc(source.note || "")}</textarea></div>
    <div class="actions"><button class="primary" data-action="save-wechat-source">保存信息源</button><button data-action="reset-wechat-source">清空表单</button></div>
  </section>`;
}
function readWechatSourceForm() {
  const source = {
    uid: $("#wechatSourceUid")?.value.trim(),
    accountName: $("#wechatSourceName")?.value.trim(),
    biz: $("#wechatSourceBiz")?.value.trim(),
    feedUrl: $("#wechatSourceFeedUrl")?.value.trim(),
    collectorHint: $("#wechatSourceCollectorHint")?.value.trim(),
    sampleArticleUrl: $("#wechatSourceSampleUrl")?.value.trim(),
    enabled: Boolean($("#wechatSourceEnabled")?.checked),
    note: $("#wechatSourceNote")?.value.trim(),
  };
  Object.keys(source).forEach((key) => {
    if (source[key] === "" || source[key] === null) delete source[key];
  });
  return source;
}
function wechatSourceImportPanel() {
  const result = state.wechatSourceImportResult;
  if (!result) return "";
  const errors = result.errors || [];
  return `<section class="panel"><h2>发现结果</h2><div class="meta"><span class="badge good">请求 ${result.requested || 0}</span><span class="badge good">登记源 ${result.importedSources || 0}</span><span class="badge">样本文章 ${result.importedArticles || 0}</span><span class="badge ${errors.length ? "warn" : "good"}">${esc(result.status || "ok")}</span></div>${errors.length ? `<pre class="markdown">${esc(JSON.stringify(errors, null, 2))}</pre>` : `<p class="summary">本轮文章链接发现没有报错。</p>`}</section>`;
}
function wechatSourceTable(sources = []) {
  if (!sources.length) return `<div class="empty compact">还没有登记公众号信息源。先通过文章链接发现，或手工登记源资料。</div>`;
  return `<table class="table"><thead><tr><th>公众号</th><th>Biz</th><th>类型</th><th>样本文章</th><th>Feed</th><th>最近发现</th><th>操作</th></tr></thead><tbody>${sources.map((s) => `<tr><td><strong>${esc(s.accountName)}</strong><div class="meta"><span class="badge ${s.enabled ? "good" : "warn"}">${s.enabled ? "启用" : "停用"}</span><span class="badge">${esc(s.uid)}</span></div></td><td>${esc(s.biz || "")}</td><td>${esc(s.sourceType || "")}<div class="muted">${esc(s.collectorHint || "")}</div></td><td>${s.articleCount || 0}<div class="muted">${esc(s.sampleTitle || "")}</div></td><td>${s.feedUrl ? `<a href="${esc(s.feedUrl)}" target="_blank" rel="noopener noreferrer">查看</a>` : ""}</td><td>${fmtDate(s.lastDiscoveredAt)}</td><td><div class="actions"><button data-action="edit-wechat-source" data-id="${esc(s.uid)}">编辑</button><button data-action="delete-wechat-source" data-id="${esc(s.uid)}">删除</button></div></td></tr>`).join("")}</tbody></table>`;
}
function wechatSourceRecentTable(items = []) {
  if (!items.length) return `<div class="empty compact">还没有录入样本文章。</div>`;
  return `<table class="table"><thead><tr><th>公众号</th><th>样本文章</th><th>发布时间</th><th>登记时间</th></tr></thead><tbody>${items.map((item) => `<tr><td>${esc(item.accountName || "")}</td><td><a href="${esc(item.url || "#")}" target="_blank" rel="noopener noreferrer">${esc(item.title || item.url)}</a><div class="muted">${esc(item.summary || "")}</div></td><td>${fmtDate(item.publishedAt)}</td><td>${fmtDate(item.createdAt)}</td></tr>`).join("")}</tbody></table>`;
}
function applyWechatRegistryState(registry = {}) {
  state.wechatSources = registry.sources || [];
  state.wechatSourceArticles = registry.recentArticles || [];
  if (registry.auth) state.wechatAuth = registry.auth;
}
function wechatAuthPanelV2(auth = {}) {
  const status = auth.status || "idle";
  const labels = {
    idle: "未授权",
    waiting: "等待扫码",
    scanned: "已扫码，待手机确认",
    authorized: "已授权",
  };
  const badge = status === "authorized" ? "good" : status === "waiting" || status === "scanned" ? "warn" : "";
  const account = auth.account || {};
  const meta = [];
  if (account.nickname || account.username) meta.push(`<span class="badge good">${esc(account.nickname || account.username)}</span>`);
  if (auth.expiresAt) meta.push(`<span class="badge">到期 ${fmtDate(auth.expiresAt)}</span>`);
  if (auth.updatedAt) meta.push(`<span class="badge">更新 ${fmtDate(auth.updatedAt)}</span>`);
  return `<section class="panel">
    <h2>微信公众平台授权</h2>
    <div class="meta"><span class="badge ${badge}">${esc(labels[status] || status)}</span>${meta.join("")}</div>
    ${auth.lastError ? `<p class="summary">${esc(auth.lastError)}</p>` : `<p class="summary">公众号搜索和最近文章同步都依赖微信公众平台登录态。先在这里扫码授权，后续就可以直接在 ai-hot 内维护公众号信息源。</p>`}
    ${auth.qrImageDataUrl ? `<div class="panel" style="max-width:280px"><img src="${auth.qrImageDataUrl}" alt="wechat auth qr" style="width:100%;display:block"></div>` : ""}
    <div class="actions"><button class="primary" data-action="start-wechat-auth">${status === "authorized" ? "重新授权" : "生成二维码"}</button><button data-action="refresh-wechat-auth">刷新状态</button><button data-action="clear-wechat-auth">清空授权</button></div>
  </section>`;
}
function wechatSearchPanelV2() {
  const authReady = Boolean(state.wechatAuth?.authorized);
  const meta = state.wechatSearchMeta || {};
  const items = state.wechatSearchResults || [];
  const existing = new Set((state.wechatSources || []).flatMap((source) => [source.biz, source.fakeid]).filter(Boolean));
  const table = items.length ? `<table class="table"><thead><tr><th>公众号</th><th>别名</th><th>FakeID</th><th>简介</th><th>操作</th></tr></thead><tbody>${items.map((item, index) => {
    const exists = existing.has(item.biz) || existing.has(item.fakeid);
    return `<tr><td><strong>${esc(item.accountName || "")}</strong><div class="meta">${item.biz ? `<span class="badge">${esc(item.biz)}</span>` : ""}${item.serviceType ? `<span class="badge">${esc(item.serviceType)}</span>` : ""}${item.verifyType ? `<span class="badge">${esc(item.verifyType)}</span>` : ""}</div></td><td>${esc(item.alias || "")}</td><td>${esc(item.fakeid || "")}</td><td>${esc(item.intro || "")}</td><td><button data-action="add-wechat-search-result" data-index="${index}" ${exists ? "disabled" : ""}>${exists ? "已加入" : "加入源池"}</button></td></tr>`;
  }).join("")}</tbody></table>` : `<div class="empty compact">${authReady ? "输入公众号名称后搜索，即可加入信息源池。" : "请先完成授权，再按公众号名称搜索。"}</div>`;
  return `<section class="panel form">
    <h2>搜索公众号并加入源池</h2>
    <div class="grid two">
      <div class="field"><label>公众号名称</label><input id="wechatSourceSearchQuery" value="${esc(meta.query || "")}" placeholder="例如：APPSO / 机器之心 / 数字生命卡兹克"></div>
      <div class="field"><label>返回数量</label><input id="wechatSourceSearchLimit" type="number" min="1" max="20" value="${esc(meta.limit || 10)}"></div>
    </div>
    <div class="actions"><button class="primary" data-action="search-wechat-sources" ${authReady ? "" : "disabled"}>搜索公众号</button><button data-action="sync-wechat-sources" ${authReady ? "" : "disabled"}>同步全部启用源</button></div>
    ${meta.query ? `<div class="meta"><span class="badge">查询 ${esc(meta.query)}</span><span class="badge">当前显示 ${meta.items || 0}</span><span class="badge">总数 ${meta.total || 0}</span>${meta.authorizedAccount?.nickname ? `<span class="badge good">${esc(meta.authorizedAccount.nickname)}</span>` : ""}</div>` : ""}
    ${table}
  </section>`;
}
function wechatSyncResultPanelV2() {
  const result = state.wechatSyncResult;
  if (!result) return "";
  const errors = result.errors || [];
  const touched = result.sources || [];
  return `<section class="panel"><h2>公众号同步结果</h2><div class="meta"><span class="badge good">检查 ${result.checked || 0}</span><span class="badge good">入库 ${result.imported || 0}</span><span class="badge">原始文章 ${result.rawArticles || 0}</span><span class="badge ${errors.length ? "warn" : "good"}">${esc(result.status || "ok")}</span></div>${touched.length ? `<div class="meta">${touched.slice(0, 6).map((source) => `<span class="badge">${esc(source.accountName || source.uid || "")}:${esc(source.lastSyncStatus || "")}</span>`).join("")}</div>` : ""}${errors.length ? `<pre class="markdown">${esc(JSON.stringify(errors, null, 2))}</pre>` : `<p class="summary">本次同步没有报错。</p>`}</section>`;
}
function wechatSourceEditorV2(source = {}) {
  const weight = Number(source.weight || source.extra?.weight || 1);
  const enabled = source.enabled === false ? "" : "checked";
  return `<section class="panel form">
    <h2>${source.uid ? "编辑公众号源" : "登记公众号源"}</h2>
    <div class="grid two">
      <div class="field"><label>源 UID</label><input id="wechatSourceUid" value="${esc(source.uid || "")}" placeholder="留空自动生成"></div>
      <div class="field"><label>公众号名称</label><input id="wechatSourceName" value="${esc(source.accountName || "")}" placeholder="公众号展示名称"></div>
      <div class="field"><label>Biz</label><input id="wechatSourceBiz" value="${esc(source.biz || "")}" placeholder="可选，但建议保留"></div>
      <div class="field"><label>FakeID</label><input id="wechatSourceFakeid" value="${esc(source.fakeid || "")}" placeholder="用于同步最近文章"></div>
      <div class="field"><label>别名</label><input id="wechatSourceAlias" value="${esc(source.alias || "")}" placeholder="可选别名"></div>
      <div class="field"><label>权重</label><input id="wechatSourceWeight" type="number" min="0.1" max="5" step="0.1" value="${Number.isFinite(weight) ? esc(weight) : "1"}"></div>
      <div class="field"><label>Feed / 采集 URL</label><input id="wechatSourceFeedUrl" value="${esc(source.feedUrl || "")}" placeholder="可选兼容输出地址"></div>
      <div class="field"><label>采集提示</label><input id="wechatSourceCollectorHint" value="${esc(source.collectorHint || "")}" placeholder="manual / wechat_mp_api / rsshub"></div>
      <div class="field"><label>样本文章 URL</label><input id="wechatSourceSampleUrl" value="${esc(source.sampleArticleUrl || "")}" placeholder="可选发现样本"></div>
    </div>
    <label class="checkline"><input id="wechatSourceEnabled" type="checkbox" ${enabled}> 启用该信息源</label>
    <div class="field"><label>备注</label><textarea id="wechatSourceNote" placeholder="分类、风险、维护备注或来源说明">${esc(source.note || "")}</textarea></div>
    <div class="actions"><button class="primary" data-action="save-wechat-source">保存源</button><button data-action="reset-wechat-source">重置表单</button></div>
  </section>`;
}
function readWechatSourceFormV2() {
  const weightRaw = $("#wechatSourceWeight")?.value.trim() || "";
  const source = {
    uid: $("#wechatSourceUid")?.value.trim(),
    accountName: $("#wechatSourceName")?.value.trim(),
    biz: $("#wechatSourceBiz")?.value.trim(),
    fakeid: $("#wechatSourceFakeid")?.value.trim(),
    alias: $("#wechatSourceAlias")?.value.trim(),
    feedUrl: $("#wechatSourceFeedUrl")?.value.trim(),
    collectorHint: $("#wechatSourceCollectorHint")?.value.trim(),
    sampleArticleUrl: $("#wechatSourceSampleUrl")?.value.trim(),
    enabled: Boolean($("#wechatSourceEnabled")?.checked),
    note: $("#wechatSourceNote")?.value.trim(),
  };
  if (weightRaw) source.weight = Number(weightRaw);
  Object.keys(source).forEach((key) => {
    if (source[key] === "" || source[key] === null) delete source[key];
  });
  if (!Number.isFinite(source.weight)) delete source.weight;
  return source;
}
function wechatSourceTableV2(sources = []) {
  if (!sources.length) return `<div class="empty compact">还没有公众号源。先搜索公众号，或手工登记一个源。</div>`;
  return `<table class="table"><thead><tr><th>公众号</th><th>标识</th><th>同步</th><th>文章</th><th>样本</th><th>操作</th></tr></thead><tbody>${sources.map((s) => {
    const syncClass = s.lastSyncStatus === "ok" ? "good" : s.lastSyncStatus === "empty" ? "" : "warn";
    return `<tr><td><strong>${esc(s.accountName)}</strong><div class="meta"><span class="badge ${s.enabled ? "good" : "warn"}">${s.enabled ? "启用" : "停用"}</span><span class="badge">${esc(s.uid)}</span>${s.alias ? `<span class="badge">${esc(s.alias)}</span>` : ""}${s.weight ? `<span class="badge">权重 ${score(s.weight)}</span>` : ""}</div></td><td><div class="muted">${esc(s.biz || "") || "-"}</div><div class="meta">${s.fakeid ? `<span class="badge good">${esc(s.fakeid)}</span>` : `<span class="badge warn">缺少 fakeid</span>`}${s.sourceType ? `<span class="badge">${esc(s.sourceType)}</span>` : ""}${s.collectorHint ? `<span class="badge">${esc(s.collectorHint)}</span>` : ""}</div></td><td><div class="meta"><span class="badge ${syncClass}">${esc(s.lastSyncStatus || "未同步")}</span>${s.lastSyncCount ? `<span class="badge">+${s.lastSyncCount}</span>` : ""}</div><div class="muted">${fmtDate(s.lastSyncAt)}</div>${s.lastError ? `<div class="muted">${esc(s.lastError)}</div>` : ""}</td><td>${s.articleCount || 0}<div class="muted">${fmtDate(s.lastArticleAt)}</div></td><td>${s.sampleArticleUrl ? `<a href="${esc(s.sampleArticleUrl)}" target="_blank" rel="noopener noreferrer">${esc(s.sampleTitle || "样本文章")}</a>` : ""}<div class="muted">${fmtDate(s.lastDiscoveredAt)}</div></td><td><div class="actions"><button data-action="edit-wechat-source" data-id="${esc(s.uid)}">编辑</button><button data-action="sync-wechat-source" data-id="${esc(s.uid)}" ${s.enabled ? "" : "disabled"}>同步</button><button data-action="delete-wechat-source" data-id="${esc(s.uid)}">删除</button></div></td></tr>`;
  }).join("")}</tbody></table>`;
}
function mpSourceEditor(source = {}) {
  const type = source.type || "rss";
  const enabled = source.enabled ? "checked" : "";
  return `<section class="panel form mp-source-editor">
    <h2>${source.id ? "编辑公众号动态源" : "新增公众号动态源"}</h2>
    <div class="grid two">
      <div class="field"><label>源 ID</label><input id="mpSourceId" value="${esc(source.id || "")}" placeholder="留空自动生成，更新时保持不变"></div>
      <div class="field"><label>名称</label><input id="mpSourceName" value="${esc(source.name || "")}" placeholder="公众号名、榜单名或采集器名"></div>
      <div class="field"><label>类型</label><select id="mpSourceType">${["rss", "atom", "json", "json_api"].map((v) => `<option value="${v}" ${type === v ? "selected" : ""}>${v}</option>`).join("")}</select></div>
      <div class="field"><label>权重</label><input id="mpSourceWeight" type="number" min="0.1" max="5" step="0.1" value="${esc(source.weight || 1)}"></div>
    </div>
    <div class="field"><label>RSS/JSON/API 地址</label><input id="mpSourceUrl" value="${esc(source.url || "")}" placeholder="RSSHub/Wechat2RSS feed 或自有采集器 JSON API"></div>
    <div class="grid two">
      <div class="field"><label>列表路径</label><input id="mpItemsPath" value="${esc(source.itemsPath || source.itemPath || "")}" placeholder="JSON 可选，例如 data.items"></div>
      <div class="field"><label>标题字段</label><input id="mpTitleField" value="${esc(source.titleField || "")}" placeholder="默认 title/name/headline"></div>
      <div class="field"><label>账号字段</label><input id="mpAccountField" value="${esc(source.accountField || "")}" placeholder="默认 accountName/source/author"></div>
      <div class="field"><label>链接字段</label><input id="mpUrlField" value="${esc(source.urlField || "")}" placeholder="默认 url/link/articleUrl"></div>
      <div class="field"><label>发布时间字段</label><input id="mpPublishedField" value="${esc(source.publishedField || "")}" placeholder="默认 publishedAt/date/time"></div>
      <div class="field"><label>摘要字段</label><input id="mpSummaryField" value="${esc(source.summaryField || "")}" placeholder="默认 summary/digest/excerpt"></div>
    </div>
    <label class="checkline"><input id="mpSourceEnabled" type="checkbox" ${enabled}> 启用采集</label>
    <div class="field"><label>备注</label><textarea id="mpSourceNote" placeholder="来源说明、授权方式、采集频率、字段备注">${esc(source.note || "")}</textarea></div>
    <div class="actions"><button class="primary" data-action="save-mp-source">保存源</button><button data-action="test-mp-source">测试当前源</button><button data-action="reset-mp-source">清空表单</button></div>
  </section>`;
}
function readMpSourceForm() {
  const source = {
    id: $("#mpSourceId")?.value.trim(),
    name: $("#mpSourceName")?.value.trim(),
    type: $("#mpSourceType")?.value,
    url: $("#mpSourceUrl")?.value.trim(),
    weight: Number($("#mpSourceWeight")?.value || 1),
    enabled: Boolean($("#mpSourceEnabled")?.checked),
    note: $("#mpSourceNote")?.value.trim(),
    itemsPath: $("#mpItemsPath")?.value.trim(),
    titleField: $("#mpTitleField")?.value.trim(),
    accountField: $("#mpAccountField")?.value.trim(),
    urlField: $("#mpUrlField")?.value.trim(),
    publishedField: $("#mpPublishedField")?.value.trim(),
    summaryField: $("#mpSummaryField")?.value.trim(),
  };
  Object.keys(source).forEach((key) => {
    if (source[key] === "" || source[key] === null || Number.isNaN(source[key])) delete source[key];
  });
  return source;
}
function mpSourceTable(sources = []) {
  if (!sources.length) return `<div class="empty compact">还没有配置真实公众号动态源。先新增 RSS/JSON/API 源，测试通过后再启用采集。</div>`;
  return `<table class="table"><thead><tr><th>名称</th><th>类型</th><th>启用</th><th>状态</th><th>入库</th><th>最近检测</th><th>操作</th></tr></thead><tbody>${sources.map((s) => `<tr>
    <td><strong>${esc(s.name)}</strong><div class="meta"><span class="badge">${esc(s.id)}</span>${s.hasUrl ? `<span class="badge good">已配置 URL</span>` : `<span class="badge warn">缺 URL</span>`}</div></td>
    <td>${esc(s.type)}</td>
    <td>${s.enabled ? "是" : "否"}</td>
    <td>${esc(s.lastStatus || "未检测")} ${s.lastCount ? `(${s.lastCount})` : ""}<div class="muted">${esc(s.lastDetail || "")}</div></td>
    <td>${s.articleCount || 0}</td>
    <td>${fmtDate(s.lastCheckedAt)}</td>
    <td><div class="actions"><button data-action="edit-mp-source" data-id="${esc(s.id)}">编辑</button><button data-action="test-saved-mp-source" data-id="${esc(s.id)}">测试</button><button data-action="delete-mp-source" data-id="${esc(s.id)}">删除</button></div></td>
  </tr>`).join("")}</tbody></table>`;
}
function mpSourceTestPanel() {
  const result = state.mpSourceTest;
  if (!result) return "";
  if (result.status !== "ok") return `<section class="panel"><h2>源测试</h2><div class="empty compact">${esc(result.error || "测试失败")}</div></section>`;
  return `<section class="panel"><h2>源测试</h2><div class="meta"><span class="badge good">抓取 ${result.fetched || 0} 条</span><span class="badge">可入库候选 ${result.accepted || 0} 条</span><span class="badge">${result.elapsedMs || 0}ms</span></div><table class="table"><thead><tr><th>标题</th><th>账号</th><th>AI相关</th><th>时间</th></tr></thead><tbody>${(result.items || []).map((item) => `<tr><td>${esc(item.title)}</td><td>${esc(item.accountName)}</td><td>${score(item.aiRelevanceScore)}</td><td>${fmtDate(item.publishedAt)}</td></tr>`).join("")}</tbody></table></section>`;
}
async function renderAdmin() {
  setChrome("后台管理", "ADMIN");
  loading();
  if (!state.token) return loginForm();
  try {
    await api("/admin/me");
  } catch {
    state.token = "";
    localStorage.removeItem("aihot_admin_token");
    return loginForm();
  }
  try {
    let content = "";
    if (state.adminTab === "overview") {
      const d = await api("/admin/overview");
      const counts = d.counts || {};
      content = `
        <section class="grid three">
          ${kpi("全量动态", int(counts.items), `频道成品 ${int(counts.channelItems)}`)}
          ${kpi("精选", int(counts.selected), "人工/规则/模型共同维护")}
          ${kpi("公众号源", int(counts.wechatSources), `原始文章 ${int(counts.wechatRawArticles)}`)}
          ${kpi("公众号文章", int(counts.mpArticles), "已写入频道候选池")}
          ${kpi("日报", int(counts.dailyIssues), "按独立栏目策略生成")}
          ${kpi("流水线", int(counts.pipelineRuns), d.latestRun ? `${statusText(d.latestRun.status)} · ${fmtDate(d.latestRun.started_at)}` : "暂无运行")}
        </section>
        ${recommendationPanel(d.recommendations || [])}
        ${moduleCards(d.modules || [])}
        ${channelMetricPanel(d.channelMetrics || [])}
        ${modelStatusPanel(d.modelStatus || {})}
        ${healthPanel(d.sourceHealth || {})}`;
    }
    if (state.adminTab === "sources") {
      const d = await api("/admin/sources");
      content = `<section class="grid three">${Object.entries(d.summary?.byChannel || {}).map(([k, v]) => kpi(channelLabel(k), int(v))).join("")}</section>
        <section class="panel">${tableWrap(`<table class="table"><thead><tr><th>名称</th><th>频道</th><th>类型</th><th>状态</th><th>数量</th><th>权重</th></tr></thead><tbody>${(d.sources || []).map((s) => `<tr><td>${esc(s.name)}</td><td>${channelLabel(s.channel)}</td><td>${esc(s.source_kind || "")}</td><td><span class="badge ${tone(s.last_status)}">${esc(statusText(s.last_status))}</span></td><td>${s.last_count || 0}</td><td>${score(s.weight)}</td></tr>`).join("")}</tbody></table>`)}</section>`;
    }
    if (state.adminTab === "health") {
      const d = await api("/admin/source-health");
      const rows = d.items || [];
      const failed = rows.filter((r) => !["ok", "configured"].includes(String(r.status || ""))).length;
      content = `<section class="grid three"><div class="kpi"><span>最近记录</span><strong>${rows.length}</strong></div><div class="kpi"><span>异常/跳过</span><strong>${failed}</strong></div><div class="kpi"><span>非 X</span><strong>是</strong></div></section>
        <section class="panel">${tableWrap(`<table class="table"><thead><tr><th>时间</th><th>信源</th><th>频道</th><th>类型</th><th>状态</th><th>数量</th><th>耗时</th><th>详情</th></tr></thead><tbody>${rows.map((r) => `<tr><td>${fmtDate(r.checked_at)}</td><td>${esc(r.source_name)}</td><td>${channelLabel(r.channel)}</td><td>${esc(r.source_kind || "")}</td><td><span class="badge ${tone(r.status)}">${esc(statusText(r.status))}</span></td><td>${r.item_count || 0}</td><td>${int(r.elapsed_ms)}ms</td><td>${esc(r.detail || "")}</td></tr>`).join("")}</tbody></table>`)}</section>`;
    }
    if (state.adminTab === "items") {
      const d = await api("/admin/items?mode=all&channel=all&limit=60");
      content = `<section class="grid">${(d.items || []).map((item) => itemCard(item, true)).join("")}</section>`;
    }
    if (state.adminTab === "daily") {
      const d = await api("/admin/daily");
      content = `<section class="panel"><button class="primary" data-action="regen-daily">重新生成日报</button></section><pre class="markdown">${esc(d.markdown || "")}</pre>`;
    }
    if (state.adminTab === "mp_legacy") {
      const [d, sourceData, registry] = await Promise.all([api("/admin/mp?limit=80"), api("/admin/mp/sources"), api("/admin/mp/source-registry")]);
      state.mpSources = sourceData.sources || [];
      state.wechatSources = registry.sources || [];
      state.wechatSourceArticles = registry.recentArticles || [];
      const summary = sourceData.summary || {};
      const registrySummary = registry.summary || {};
      content = `<section class="grid three">
          <div class="kpi"><span>公众号文章</span><strong>${d.count || 0}</strong></div>
          <div class="kpi"><span>已配置源</span><strong>${summary.configured || 0}</strong></div>
          <div class="kpi"><span>启用可采集</span><strong>${summary.ready || 0}</strong></div>
        </section>
        <section class="panel"><h2>公众号爆文</h2><p class="summary">该栏目只接受真实 RSS、JSON/API 或自有采集器输出。源测试只读取样本不入库，运行采集后才写入文章表；公开页面样本和 AIHOT 页面内容会被后端拒绝。</p><button class="primary" data-action="collect-mp">运行公众号动态采集</button></section>
        ${mpSourceEditor(state.mpSourceEditing || {})}
        ${mpSourceTestPanel()}
        <section class="panel"><h2>已配置公众号源</h2>${mpSourceTable(state.mpSources)}</section>
        <section class="panel form"><h2>自有采集器 JSON 导入</h2><div class="field"><label>JSON 数组</label><textarea id="mpImportJson" placeholder='[{"title":"...","accountName":"...","url":"...","sourceOrigin":"third_party_api","heatScore":90}]'></textarea></div><button data-action="import-mp">导入自有 JSON</button></section>
        <section class="panel"><h2>公众号文章</h2><table class="table"><thead><tr><th>标题</th><th>公众号</th><th>来源</th><th>阅读</th><th>点赞</th><th>转发</th><th>异常</th></tr></thead><tbody>${(d.items || []).map((item) => `<tr><td>${esc(item.title)}</td><td>${esc(item.accountName)} ${item.original ? "原创" : ""}</td><td>${esc(originLabel(item.sourceOrigin))}</td><td>${item.reads ?? ""}</td><td>${item.likes ?? ""}</td><td>${item.shares ?? ""}</td><td>${score(item.anomalyScore)}</td></tr>`).join("")}</tbody></table></section>`;
      const mpRegistryPanels = `<section class="grid three">
          <div class="kpi"><span>已登记源</span><strong>${registrySummary.registered || 0}</strong></div>
          <div class="kpi"><span>已识别 Biz</span><strong>${registrySummary.withBiz || 0}</strong></div>
          <div class="kpi"><span>已留 Feed</span><strong>${registrySummary.withFeedUrl || 0}</strong></div>
        </section>
        <section class="panel form"><h2>通过文章链接发现公众号信息源</h2><div class="field"><label>文章链接</label><textarea id="wechatSourceLinks" placeholder="一行一个 mp.weixin.qq.com 文章链接"></textarea></div><button class="primary" data-action="discover-wechat-sources">通过文章链接登记信息源</button></section>
        ${wechatSourceImportPanel()}
        ${wechatSourceEditor(state.wechatSourceEditing || {})}
        <section class="panel"><h2>已登记公众号信息源</h2>${wechatSourceTable(state.wechatSources)}</section>
        <section class="panel"><h2>最近登记的样本文章</h2>${wechatSourceRecentTable(state.wechatSourceArticles)}</section>`;
      content = mpRegistryPanels + content;
    }
    if (state.adminTab === "mp") {
      const [d, sourceData, registry, auth] = await Promise.all([
        api("/admin/mp?limit=80"),
        api("/admin/mp/sources"),
        api("/admin/mp/source-registry"),
        api("/admin/mp/wechat-auth"),
      ]);
      state.mpSources = sourceData.sources || [];
      applyWechatRegistryState(registry);
      state.wechatAuth = auth || registry.auth || null;
      const summary = sourceData.summary || {};
      const registrySummary = registry.summary || {};
      content = `<section class="grid three">
          <div class="kpi"><span>公众号文章</span><strong>${d.count || 0}</strong></div>
          <div class="kpi"><span>公众号源</span><strong>${registrySummary.registered || 0}</strong></div>
          <div class="kpi"><span>可同步</span><strong>${registrySummary.readyToSync || 0}</strong></div>
        </section>
        <section class="grid three">
          <div class="kpi"><span>已带 fakeid</span><strong>${registrySummary.withFakeid || 0}</strong></div>
          <div class="kpi"><span>样本文章</span><strong>${registrySummary.sampleArticles || 0}</strong></div>
          <div class="kpi"><span>外部兼容源</span><strong>${summary.configured || 0}</strong></div>
        </section>
        ${wechatAuthPanelV2(state.wechatAuth || {})}
        ${wechatSearchPanelV2()}
        ${wechatSyncResultPanelV2()}
        <section class="panel form"><h2>通过文章链接发现公众号源</h2><div class="field"><label>文章链接</label><textarea id="wechatSourceLinks" placeholder="每行一条 mp.weixin.qq.com 文章链接"></textarea></div><button class="primary" data-action="discover-wechat-sources">通过文章链接登记源</button></section>
        ${wechatSourceImportPanel()}
        ${wechatSourceEditorV2(state.wechatSourceEditing || {})}
        <section class="panel"><h2>已登记公众号源</h2>${wechatSourceTableV2(state.wechatSources)}</section>
        <section class="panel"><h2>最近原始文章</h2>${wechatSourceRecentTable(state.wechatSourceArticles)}</section>
        <section class="panel"><h2>写入公众号频道</h2><p class="summary">手动同步会先把原始文章写入源池，再把符合条件的内容送入现有公众号频道分析链路。下面这个按钮仍然保留整个公众号频道采集流程。</p><button class="primary" data-action="collect-mp">运行公众号频道采集</button> <button data-action="run-mp-enrich">DeepSeek 分析公众号文章</button></section>
        <section class="panel"><h2>当前公众号频道文章</h2><table class="table"><thead><tr><th>日期</th><th>标题</th><th>公众号</th><th>来源</th><th>热度</th><th>异常</th></tr></thead><tbody>${(d.items || []).map((item) => `<tr><td>${fmtDate(item.publishedAt).slice(0, 10)}</td><td><a href="${esc(item.url || "#")}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a></td><td>${esc(item.accountName || "")}${item.original ? " 原创" : ""}</td><td>${esc(originLabel(item.sourceOrigin))}</td><td>${score(item.heatScore)}</td><td>${score(item.anomalyScore)}</td></tr>`).join("")}</tbody></table></section>
        <section class="panel"><h2>旧版外部源兼容层</h2><p class="summary">这些 RSS / JSON / API 源仍然保留为兜底输入，但已经不是公众号账号驱动流程的主路径。</p></section>
        ${mpSourceEditor(state.mpSourceEditing || {})}
        ${mpSourceTestPanel()}
        <section class="panel"><h2>已配置外部兼容源</h2>${mpSourceTable(state.mpSources)}</section>
        <section class="panel form"><h2>导入采集器 JSON</h2><div class="field"><label>JSON 数组</label><textarea id="mpImportJson" placeholder='[{"title":"...","accountName":"...","url":"...","sourceOrigin":"third_party_api","heatScore":90}]'></textarea></div><button data-action="import-mp">导入采集器 JSON</button></section>`;
    }
    if (state.adminTab === "strategy") {
      const d = await api("/admin/strategy");
      content = `<section class="panel"><h2>精选策略</h2><table class="table"><thead><tr><th>规则</th><th>说明</th><th>权重</th><th>启用</th></tr></thead><tbody>${(d.items || []).map((r) => `<tr><td>${esc(r.name)}</td><td>${esc(r.description || "")}</td><td>${score(r.weight)}</td><td>${r.enabled ? "是" : "否"}</td></tr>`).join("")}</tbody></table></section>
        <section class="panel"><h2>栏目处理逻辑</h2><table class="table"><thead><tr><th>栏目</th><th>逻辑</th><th>纳入/排除</th></tr></thead><tbody>${(d.channelRules || []).map((r) => `<tr><td>${esc(r.name)}</td><td>${esc(r.description)}</td><td>${esc([...(r.include || []), ...(r.exclude || []).map((x) => "排除 " + x)].join(" / "))}</td></tr>`).join("")}</tbody></table></section>`;
    }
    if (state.adminTab === "enrich") {
      const d = await api("/admin/model-enrich");
      content = `${modelStatusPanel(d.status || d)}
        <section class="panel"><div class="section-head"><h2>处理动作</h2><span class="badge">失败会缓存，避免重复请求</span></div><button class="primary" data-action="run-enrich">处理全量 20 条</button> <button data-action="run-enrich-force">强制重跑全量 10 条</button> <button data-action="run-mp-enrich">处理公众号 10 条</button> <button data-action="refresh-duplicates">刷新关联讨论</button></section>
        <section class="grid two">
          <section class="panel"><div class="section-head"><h2>全量动态模型记录</h2><span class="badge">${int((d.items || []).length)}</span></div>${tableWrap(`<table class="table compact"><thead><tr><th>时间</th><th>条目</th><th>状态</th><th>错误</th></tr></thead><tbody>${(d.items || []).map((r) => `<tr><td>${fmtDate(r.created_at)}</td><td>${r.item_id}</td><td><span class="badge ${tone(r.status)}">${esc(statusText(r.status))}</span></td><td>${esc(r.error || "")}</td></tr>`).join("")}</tbody></table>`)}</section>
          <section class="panel"><div class="section-head"><h2>公众号模型记录</h2><span class="badge">${int((d.mpItems || []).length)}</span></div>${tableWrap(`<table class="table compact"><thead><tr><th>时间</th><th>文章</th><th>状态</th><th>错误</th></tr></thead><tbody>${(d.mpItems || []).map((r) => `<tr><td>${fmtDate(r.created_at)}</td><td>${r.mp_article_id}</td><td><span class="badge ${tone(r.status)}">${esc(statusText(r.status))}</span></td><td>${esc(r.error || "")}</td></tr>`).join("")}</tbody></table>`)}</section>
        </section>`;
    }
    if (state.adminTab === "model") {
      const d = await api("/admin/model-eval");
      const current = d.current || {};
      content = `<section class="grid three"><div class="kpi"><span>当前评分</span><strong>${score(current.score)}</strong></div><div class="kpi"><span>样本</span><strong>${current.sampleCount || 0}</strong></div><div class="kpi"><span>覆盖率</span><strong>${score((current.detail?.coverage || 0) * 100)}%</strong></div></section>
        <section class="panel"><button class="primary" data-action="run-model-eval">运行评估</button><p class="summary">${esc((current.detail?.notes || []).join(" "))}</p></section>
        <section class="panel"><table class="table"><thead><tr><th>时间</th><th>模型/策略</th><th>类型</th><th>样本</th><th>分数</th></tr></thead><tbody>${(d.history || []).map((r) => `<tr><td>${fmtDate(r.created_at)}</td><td>${esc(r.model_name)}</td><td>${esc(r.eval_type)}</td><td>${r.sample_count || 0}</td><td>${score(r.score)}</td></tr>`).join("")}</tbody></table></section>`;
    }
    if (state.adminTab === "pipeline") {
      const d = await api("/admin/pipeline/runs");
      content = `<section class="panel"><button class="primary" data-action="import-latest">导入 latest.json</button> <button data-action="run-pipeline">运行采集流水线</button></section><section class="panel"><table class="table"><thead><tr><th>ID</th><th>类型</th><th>状态</th><th>开始</th><th>条目</th><th>信息</th></tr></thead><tbody>${(d.items || []).map((r) => `<tr><td>${r.id}</td><td>${esc(r.run_type)}</td><td>${esc(r.status)}</td><td>${fmtDate(r.started_at)}</td><td>${r.item_count || 0}</td><td>${esc(r.message || "")}</td></tr>`).join("")}</tbody></table></section>`;
    }
    if (state.adminTab === "feedback") {
      const d = await api("/admin/feedback");
      content = `<section class="panel"><table class="table"><thead><tr><th>时间</th><th>条目</th><th>类型</th><th>内容</th></tr></thead><tbody>${(d.items || []).map((r) => `<tr><td>${fmtDate(r.created_at)}</td><td>${r.item_id || ""}</td><td>${esc(r.vote)}</td><td>${esc(r.reason || "")}</td></tr>`).join("")}</tbody></table></section>`;
    }
    if (state.adminTab === "access") {
      const d = await api("/admin/access");
      content = `<section class="panel"><table class="table"><thead><tr><th>路径</th><th>次数</th><th>最近</th></tr></thead><tbody>${(d.items || []).map((r) => `<tr><td>${esc(r.path)}</td><td>${r.count}</td><td>${fmtDate(r.lastSeen)}</td></tr>`).join("")}</tbody></table></section>`;
    }
    if (state.adminTab === "audit") {
      const d = await api("/admin/audit");
      content = `<section class="panel"><table class="table"><thead><tr><th>时间</th><th>用户</th><th>动作</th><th>对象</th></tr></thead><tbody>${(d.items || []).map((r) => `<tr><td>${fmtDate(r.created_at)}</td><td>${esc(r.actor)}</td><td>${esc(r.action)}</td><td>${esc(r.target_type)} ${esc(r.target_id)}</td></tr>`).join("")}</tbody></table></section>`;
    }
    if (state.adminTab === "users") {
      const d = await api("/admin/users");
      content = `<section class="panel"><table class="table"><thead><tr><th>ID</th><th>用户名</th><th>角色</th><th>启用</th><th>最近登录</th></tr></thead><tbody>${(d.items || []).map((u) => `<tr><td>${u.id}</td><td>${esc(u.username)}</td><td>${esc(u.role)}</td><td>${u.active ? "是" : "否"}</td><td>${fmtDate(u.last_login_at)}</td></tr>`).join("")}</tbody></table></section>`;
    }
    if (state.adminTab === "system") {
      const d = await api("/admin/system");
      content = `<section class="panel"><table class="table"><tbody>${Object.entries(d).map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(Array.isArray(v) ? v.join(" / ") : typeof v === "object" ? JSON.stringify(v) : v)}</td></tr>`).join("")}</tbody></table></section>`;
    }
    $("#app").innerHTML = adminTabs() + content;
    document.querySelectorAll("[data-admin-tab]").forEach((b) => b.onclick = () => { state.adminTab = b.dataset.adminTab; renderAdmin(); });
    document.querySelector("[data-logout]")?.addEventListener("click", () => { state.token = ""; localStorage.removeItem("aihot_admin_token"); loginForm(); });
    document.querySelectorAll("[data-action]").forEach((b) => b.onclick = adminAction);
  } catch (err) {
    errorView(err);
  }
}
async function adminAction(e) {
  const a = e.currentTarget.dataset.action;
  e.currentTarget.disabled = true;
  try {
    if (a === "import-latest") await api("/admin/pipeline/import-latest", { method: "POST", body: "{}" });
    if (a === "run-pipeline") await api("/admin/pipeline/run", { method: "POST", body: "{}" });
    if (a === "regen-daily") await api("/admin/daily/regenerate", { method: "POST", body: "{}" });
    if (a === "run-model-eval") await api("/admin/model-eval/run", { method: "POST", body: "{}" });
    if (a === "run-enrich") await api("/admin/model-enrich/run", { method: "POST", body: JSON.stringify({ limit: 20 }) });
    if (a === "run-enrich-force") await api("/admin/model-enrich/run", { method: "POST", body: JSON.stringify({ limit: 10, force: true }) });
    if (a === "run-mp-enrich") await api("/admin/mp/model-enrich/run", { method: "POST", body: JSON.stringify({ limit: 10 }) });
    if (a === "refresh-duplicates") await api("/admin/duplicates/refresh", { method: "POST", body: "{}" });
    if (a === "collect-mp") await api("/admin/mp/collect", { method: "POST", body: "{}" });
    if (a === "start-wechat-auth") {
      state.wechatAuth = await api("/admin/mp/wechat-auth/start", { method: "POST", body: "{}" });
      state.wechatSearchResults = [];
      state.wechatSearchMeta = null;
      renderAdmin();
      return;
    }
    if (a === "refresh-wechat-auth") {
      state.wechatAuth = await api("/admin/mp/wechat-auth/refresh", { method: "POST", body: "{}" });
      renderAdmin();
      return;
    }
    if (a === "clear-wechat-auth") {
      state.wechatAuth = await api("/admin/mp/wechat-auth/clear", { method: "POST", body: "{}" });
      state.wechatSearchResults = [];
      state.wechatSearchMeta = null;
      state.wechatSyncResult = null;
      renderAdmin();
      return;
    }
    if (a === "search-wechat-sources") {
      const query = $("#wechatSourceSearchQuery")?.value.trim() || "";
      const limit = Number($("#wechatSourceSearchLimit")?.value || 10);
      if (!query) throw new Error("请先输入要搜索的公众号名称。");
      const result = await api("/admin/mp/source-registry/search", { method: "POST", body: JSON.stringify({ query, limit }) });
      state.wechatSearchResults = result.items || [];
      state.wechatSearchMeta = {
        query: result.query || query,
        limit,
        total: result.total || 0,
        items: (result.items || []).length,
        authorizedAccount: result.authorizedAccount || {},
      };
      renderAdmin();
      return;
    }
    if (a === "add-wechat-search-result") {
      const index = Number(e.currentTarget.dataset.index || -1);
      const item = (state.wechatSearchResults || [])[index];
      if (!item) throw new Error("选中的搜索结果已失效，请重新搜索。");
      const result = await api("/admin/mp/source-registry/add-search-result", { method: "POST", body: JSON.stringify({ item }) });
      applyWechatRegistryState(result.registry || {});
      state.wechatSourceEditing = result.source || null;
      renderAdmin();
      return;
    }
    if (a === "sync-wechat-sources") {
      const result = await api("/admin/mp/source-registry/sync", { method: "POST", body: JSON.stringify({ limit: 10 }) });
      state.wechatSyncResult = result;
      applyWechatRegistryState(result.registry || {});
      renderAdmin();
      return;
    }
    if (a === "sync-wechat-source") {
      const uid = e.currentTarget.dataset.id || "";
      const result = await api("/admin/mp/source-registry/sync", { method: "POST", body: JSON.stringify({ uid, limit: 10 }) });
      state.wechatSyncResult = result;
      applyWechatRegistryState(result.registry || {});
      renderAdmin();
      return;
    }
    if (a === "discover-wechat-sources") {
      const raw = document.querySelector("#wechatSourceLinks")?.value || "";
      const urls = raw.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
      if (!urls.length) {
        throw new Error("请先输入至少一条公众号文章链接");
      }
      state.wechatSourceImportResult = await api("/admin/mp/source-registry/by-article", { method: "POST", body: JSON.stringify({ urls }) });
    }
    if (a === "edit-wechat-source") {
      state.wechatSourceEditing = state.wechatSources.find((s) => s.uid === e.currentTarget.dataset.id) || null;
      renderAdmin();
      return;
    }
    if (a === "reset-wechat-source") {
      state.wechatSourceEditing = null;
      renderAdmin();
      return;
    }
    if (a === "save-wechat-source") {
      const result = await api("/admin/mp/source-registry/upsert", { method: "POST", body: JSON.stringify({ source: readWechatSourceFormV2() }) });
      applyWechatRegistryState(result.registry || {});
      state.wechatSourceEditing = result.source || null;
      renderAdmin();
      return;
    }
    if (a === "delete-wechat-source") {
      if (!confirm("确定删除这个公众号信息源吗？已登记的样本文章也会一并删除。")) {
        e.currentTarget.disabled = false;
        return;
      }
      await api("/admin/mp/source-registry/delete", { method: "POST", body: JSON.stringify({ uid: e.currentTarget.dataset.id }) });
      if (state.wechatSourceEditing?.uid === e.currentTarget.dataset.id) state.wechatSourceEditing = null;
      state.wechatSourceImportResult = null;
    }
    if (a === "edit-mp-source") {
      state.mpSourceEditing = state.mpSources.find((s) => s.id === e.currentTarget.dataset.id) || null;
      state.mpSourceTest = null;
      renderAdmin();
      return;
    }
    if (a === "reset-mp-source") {
      state.mpSourceEditing = null;
      state.mpSourceTest = null;
      renderAdmin();
      return;
    }
    if (a === "save-mp-source") {
      const result = await api("/admin/mp/sources/upsert", { method: "POST", body: JSON.stringify({ source: readMpSourceForm() }) });
      state.mpSourceEditing = result.source || null;
      state.mpSourceTest = null;
    }
    if (a === "test-mp-source") {
      state.mpSourceTest = await api("/admin/mp/sources/test", { method: "POST", body: JSON.stringify({ source: readMpSourceForm() }) });
    }
    if (a === "test-saved-mp-source") {
      state.mpSourceEditing = state.mpSources.find((s) => s.id === e.currentTarget.dataset.id) || null;
      state.mpSourceTest = await api("/admin/mp/sources/test", { method: "POST", body: JSON.stringify({ id: e.currentTarget.dataset.id }) });
    }
    if (a === "delete-mp-source") {
      if (!confirm("确定删除这个公众号动态源？已入库文章不会被自动删除。")) {
        e.currentTarget.disabled = false;
        return;
      }
      await api("/admin/mp/sources/delete", { method: "POST", body: JSON.stringify({ id: e.currentTarget.dataset.id }) });
      if (state.mpSourceEditing?.id === e.currentTarget.dataset.id) state.mpSourceEditing = null;
      state.mpSourceTest = null;
    }
    if (a === "trace-item") {
      const trace = await api(`/admin/items/${e.currentTarget.dataset.id}/trace`);
      const target = document.createElement("section");
      target.className = "panel";
      target.innerHTML = `<h2>追溯</h2><pre class="markdown">${esc(JSON.stringify(trace, null, 2))}</pre>`;
      document.querySelector("#app").prepend(target);
      return;
    }
    if (a === "import-mp") {
      const raw = document.querySelector("#mpImportJson")?.value || "[]";
      const items = JSON.parse(raw);
      await api("/admin/mp/import", { method: "POST", body: JSON.stringify({ items }) });
    }
    if (a === "toggle-select") await api(`/admin/items/${e.currentTarget.dataset.id}`, { method: "PATCH", body: JSON.stringify({ aiSelected: e.currentTarget.dataset.selected !== "1" }) });
    renderAdmin();
  } catch (err) {
    alert(err.message);
    e.currentTarget.disabled = false;
  }
}
function render() {
  state.route = routeFromLocation();
  if (state.route === "/") return renderHome();
  if (state.route === "/selected") return renderFeed("selected");
  if (state.route === "/all") return renderFeed("all");
  if (state.route === "/daily") return renderDaily();
  if (state.route === "/mp") return renderMp();
  if (state.route === "/opc") return renderOpc();
  if (state.route === "/about") return renderAbout();
  if (state.route === "/feedback") return renderFeedback();
  if (state.route === "/admin") return renderAdmin();
  return renderFeed("selected");
}
document.addEventListener("click", (e) => {
  const refresh = e.target.closest("[data-refresh]");
  if (refresh) {
    e.preventDefault();
    refresh.disabled = true;
    Promise.resolve(refreshSourceMini()).then(() => render()).finally(() => { refresh.disabled = false; });
    return;
  }
  const a = e.target.closest("a[data-route]");
  if (!a) return;
  e.preventDefault();
  go(a.dataset.route);
});
window.addEventListener("popstate", render);
refreshSourceMini();
render();
setInterval(() => {
  if (document.visibilityState !== "visible") return;
  refreshSourceMini();
  if (state.route === "/") renderHome();
}, 300000);
