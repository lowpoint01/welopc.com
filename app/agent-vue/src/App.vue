<template>
<header class="topbar">
    <a class="brand" href="../" aria-label="返回 AI HOT">
      <img :src="'../assets/welopc-ai-logo-appicon.png'" alt="WelOPC AI HOT logo">
      <span>
        <strong>AIHOT Agent</strong>
        <small>WelOPC content capability</small>
      </span>
    </a>
    <nav aria-label="Agent 接入导航">
      <a href="../">实时雷达</a>
      <a href="#install">安装</a>
      <a href="#scenario-packs">场景包</a>
      <a href="#use-cases">用途</a>
      <a href="#api">API</a>
    </nav>
  </header>

  <main>
    <section class="hero" id="install">
      <div class="hero-copy">
        <p class="eyebrow">WEL-OPC AIHOT AGENT ACCESS</p>
        <h1>把 AIHOT 变成 Agent 可调用的内容能力源</h1>
        <p class="lead">不是只查询新闻。Agent 可以基于 WelOPC AIHOT 的热点、分数、来源和日报，生成趋势判断、选题、简报、coding-agent 情报和自动化工作流输出。</p>
      </div>
      <div class="command-panel" aria-label="安装命令">
        <span>Universal install</span>
        <code>npx skills add welopc/aihot-skills --skill welopc-aihot</code>
        <span>OPC scenario pack</span>
        <code>npx @welopc/cli add opc-aihot</code>
        <small>GitHub 包仓库发布后，这条命令正式生效；当前主站已提供 API、SKILL.md 和接入说明。</small>
      </div>
    </section>

    <section class="band quickstart">
      <div>
        <p class="eyebrow">PUBLIC API BASE</p>
        <h2>统一数据底座</h2>
        <p>脚本和后续 MCP 都只读取公开 API，不需要后台 token、数据库权限或服务器 SSH。</p>
      </div>
      <a class="api-link" href="https://welopc.com/ai-hot/api/public/feed?mode=selected&amp;channel=all&amp;limit=5">https://welopc.com/ai-hot/api/public</a>
    </section>

    <section class="scenario-packs" id="scenario-packs">
      <div class="section-heading">
        <p class="eyebrow">WELOPC SCENARIO PACKS</p>
        <h2>把 AIHOT 热点源接入主站场景包</h2>
      </div>
      <p class="scenario-kicker">WelOPC 场景包矩阵</p>
      <p class="scenario-lead">主站的 OPC 场景包负责岗位工作流，AIHOT 负责给这些工作流提供最新热点、选题、趋势和引用来源。</p>
      <div class="pack-command">
        <span>AIHOT 场景包安装</span>
        <code>npx @welopc/cli add opc-aihot</code>
      </div>
      <div class="pack-grid">
        <article>
          <span class="pack-tag">传播入口</span>
          <h3>opc-selfmedia</h3>
          <p>把 AIHOT 热点源接入自媒体运营，生成选题池、素材库、草稿方向和发布检查清单。</p>
          <code>npx @welopc/cli add opc-selfmedia</code>
        </article>
        <article>
          <span class="pack-tag">优先变现</span>
          <h3>opc-ecommerce</h3>
          <p>用 AIHOT 追踪 AI 工具、产品和平台变化，辅助商品台账、活动日报和售后知识更新。</p>
          <code>npx @welopc/cli add opc-ecommerce</code>
        </article>
        <article>
          <span class="pack-tag">高复用</span>
          <h3>opc-knowledgebiz</h3>
          <p>把 AIHOT 日报和高信号内容沉淀进知识库，服务资料整理、社群答疑和内容分发。</p>
          <code>npx @welopc/cli add opc-knowledgebiz</code>
        </article>
        <article>
          <span class="pack-tag">本地线索</span>
          <h3>opc-localbiz</h3>
          <p>把 AI 趋势转成门店活动、评价监控和本地生活线索的内容素材。</p>
          <code>npx @welopc/cli add opc-localbiz</code>
        </article>
        <article>
          <span class="pack-tag">商务跟进</span>
          <h3>opc-sales</h3>
          <p>用 AIHOT 信号辅助销售助理识别客户关心的 AI 主题，生成跟进提醒、周报和 CRM 备注。</p>
          <code>npx @welopc/cli add opc-sales</code>
        </article>
      </div>
    </section>

    <section class="grid" id="use-cases">
      <article>
        <span>01</span>
        <h2>趋势判断</h2>
        <p>读取最近标题、摘要、频道、分数和来源密度，判断哪些模型、工具、公司或关键词正在升温。</p>
      </article>
      <article>
        <span>02</span>
        <h2>选题和内容生产</h2>
        <p>为公众号、短帖、文章、视频和自媒体 OPC 工作台生成选题角度、标题方向和引用材料。</p>
      </article>
      <article>
        <span>03</span>
        <h2>Coding-agent 情报</h2>
        <p>监控 Codex、Claude Code、Cursor、MCP、Agent framework 和开发工具链的高信号变化。</p>
      </article>
      <article>
        <span>04</span>
        <h2>工作流触发</h2>
        <p>当高分热点、指定关键词或指定频道更新时，继续生成摘要、推送、内部报告或选题库。</p>
      </article>
    </section>

    <section class="commands">
      <div class="section-heading">
        <p class="eyebrow">SCRIPT INTERFACE</p>
        <h2>Agent 拿到 skill 后调用这些命令</h2>
      </div>
      <div class="command-list">
        <pre><code>python scripts/latest.py --channel all --mode selected --limit 10 --format markdown</code></pre>
        <pre><code>python scripts/daily.py --format markdown</code></pre>
        <pre><code>python scripts/search.py "Claude Code" --channel all --mode all --limit 20 --format json</code></pre>
        <pre><code>python scripts/stats.py --format json</code></pre>
      </div>
    </section>

    <section class="matrix" id="api">
      <div class="section-heading">
        <p class="eyebrow">RETURN SHAPES</p>
        <h2>接入口返回内容</h2>
      </div>
      <div class="matrix-row">
        <strong>最新热点</strong>
        <span>标题、摘要、频道、分数、来源、发布时间、URL</span>
      </div>
      <div class="matrix-row">
        <strong>日报</strong>
        <span>Markdown 日报、重点条目、主题分组、引用来源</span>
      </div>
      <div class="matrix-row">
        <strong>关键词研究</strong>
        <span>匹配条目、相关主题、最近出现时间、来源列表</span>
      </div>
      <div class="matrix-row">
        <strong>站点状态</strong>
        <span>条目数、来源数、入选数量、日报数量、pipeline 状态</span>
      </div>
    </section>

    <section class="links">
      <a href="https://welopc.com/ai-hot/api/public/feed?mode=selected&amp;channel=all&amp;limit=5">精选 feed</a>
      <a href="https://welopc.com/ai-hot/api/public/daily/latest">最新日报 API</a>
      <a href="./SKILL.md">查看 SKILL.md</a>
      <a href="../">返回 AIHOT 雷达</a>
    </section>
  </main>
</template>
