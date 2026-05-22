# AI Signal Radar DESIGN.md

> 一个面向 AI 从业者的实时热点情报控制台：先给出“今天该看什么”，再展示“为什么可信”。

## 1. Visual Theme & Atmosphere

**Style**: WelOPC Dark Product Console
**Keywords**: WelOPC 主站一致性、深色产品站、绿色/cyan/紫渐变、玻璃导航、情报室、交易终端、源证据、实时脉冲
**Tone**: 保持 WelOPC 产品站的深色背景、绿色主按钮、cyan/紫渐变和圆角胶囊气质，同时维持高密度监控台，不做营销页，不做博客页。
**Feel**: 像嵌入 WelOPC 主站里的 AI 情报模块，打开后能立即判断今天哪个 AI 热点值得追。

**Interaction Tier**: L1.5 / L2 轻量交互
**Dependencies**: CSS + 原生 JavaScript，无框架、无构建，保持 Cloudflare Pages 可直接部署。

## 2. Color Palette & Roles

```css
:root {
  --bg: #0a0a0f;
  --bg-rgb: 10, 10, 15;
  --surface: #12121a;
  --surface-rgb: 18, 18, 26;
  --surface-strong: #1a1a26;
  --surface-soft: #0f0f16;
  --border: rgba(255, 255, 255, 0.06);
  --border-soft: rgba(255, 255, 255, 0.06);
  --border-hover: #00e5a0;
  --text: #f0f0f5;
  --text-secondary: #8b8ba3;
  --text-tertiary: #5a5a72;
  --accent: #00e5a0;
  --accent-rgb: 0, 229, 160;
  --accent-alt: #00b4d8;
  --accent-alt-rgb: 0, 180, 216;
  --violet: #7b61ff;
  --violet-rgb: 123, 97, 255;
  --danger: #ff6b6b;
  --success: #76f7a1;
  --warning: #f5c542;
}
```

**Color Rules:**
- 所有组件颜色必须通过 CSS 变量引用，除变量定义外不散落硬编码颜色。
- 主强调色只用于实时状态、当前头条、可点击证据；不要全页泛滥。
- Reddit / YouTube / X / GitHub / Product Hunt 用低饱和标签区分，不使用大面积品牌色。

## 3. Typography Rules

**Font Stack:**
```css
@import url("https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Outfit:wght@400;500;600;700;800&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap");
```

| Role | Font | Size | Weight | Line Height | Letter Spacing |
|------|------|------|--------|-------------|----------------|
| Product mark | Outfit | 27px | 700 | 1 | 0.08em |
| Page H1 | Outfit / Noto Sans SC | 30-48px | 800/900 | 1.18 | 0.01em |
| Section H2 | Outfit / Noto Sans SC | 19px | 800 | 1.3 | 0.04em |
| Card title | Plus Jakarta Sans / Noto Sans SC | 16-36px | 700 | 1.45 | 0.01em |
| Body | Plus Jakarta Sans / Noto Sans SC | 14.5-16px | 400/500 | 1.75 | 0.02em |
| Label / data | JetBrains Mono | 11-13px | 600 | 1.4 | 0.06em |

**Typography Rules:**
- 中文字体必须优先于英文字体，正文行高不低于 1.65。
- 数据、时间戳、分数、source count 使用等宽字体。
- 禁止只用系统默认字体；禁止大面积全大写英文造成阅读噪音。

**Text Decoration:**
- 不使用大面积渐变文字；仅在产品 mark 和核心数字上使用轻微高亮。
- 正文、摘要、原因不做投影和渐变，保证可读性。

## 4. Component Stylings

### Panels
```css
.panel {
  background: linear-gradient(180deg, rgba(var(--surface-rgb), 0.96), rgba(var(--surface-rgb), 0.72));
  border: 1px solid var(--border-soft);
  border-radius: 18px;
}
.panel:hover { border-color: var(--border); }
```

### Cards
```css
.signal-card {
  background: rgba(var(--surface-rgb), 0.68);
  border: 1px solid var(--border-soft);
  border-radius: 16px;
  transition: border-color 160ms ease, background 160ms ease, transform 160ms ease;
}
.signal-card:hover,
.signal-card:focus-within {
  border-color: rgba(var(--accent-rgb), 0.5);
  background: rgba(var(--surface-rgb), 0.94);
}
```

### Links
```css
a { color: inherit; text-decoration: none; }
a:hover { color: var(--accent); }
a:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
```

### Tags / Badges
```css
.badge {
  border: 1px solid var(--border-soft);
  background: rgba(var(--surface-rgb), 0.72);
  color: var(--text-secondary);
  border-radius: 999px;
  font-family: var(--font-mono);
}
```

## 5. Layout Principles

**Container:**
- Desktop: 左侧 rail 240px，主列最小 520px，右侧 inspector 360px。
- Dashboard 不设营销 Hero，首屏必须显示真实热点、时间线和证据。
- 主要信息顺序：头条聚类 -> 实时信息流 -> GitHub / Product Hunt / X / 社区视频 -> 信源健康。

**Grid:**
```css
.shell { display: grid; grid-template-columns: 244px minmax(0, 1fr); }
.content-grid { display: grid; grid-template-columns: minmax(520px, 1fr) 380px; }
```

## 6. Depth & Elevation

| Level | Treatment | Use |
|-------|-----------|-----|
| Base | 暗色背景 + 细网格 | 全局背景 |
| Panel | 1px 边框 + 低透明 surface | 大区块 |
| Active | accent 边框 + 左侧信号线 | 当前头条、活跃信号 |
| Alert | warning 左边框 | 需要关注的原因 |

不使用厚重阴影、玻璃拟态泛滥、卡片套卡片。

## 7. Animation & Interaction

**Motion Philosophy**: 实时监控感来自状态灯、扫描线、轻微 hover，而不是重型叙事动画。
**Tier**: L1.5 / L2

### Entrance Animation
```css
@keyframes riseIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
```

### Status Pulse
```css
@keyframes pulse {
  0%, 100% { opacity: 0.45; transform: scale(0.92); }
  50% { opacity: 1; transform: scale(1.08); }
}
```

### Reduced Motion
```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

## 8. Do's and Don'ts

### Do
- 第一屏至少展示 3 条真实热点或信号。
- 每个热点聚类都必须包含：这是什么、为什么今天热、对谁重要、一句话判断。
- GitHub 卡片必须显眼展示当日 star 增长、总 star、语言和一句话摘要。
- 空状态必须解释“未命中/等待下一轮抓取”，不能只显示空白。
- 信源证据要比装饰更显眼。

### Don't
- 不要做大 Hero、营销 slogan 或欢迎页。
- 不要使用大面积蓝紫渐变和软 blob 装饰。
- 不要把 Reddit / YouTube / X 藏在普通列表里，必须独立成证据层。
- 不要卡片套卡片。
- 不要使用弹窗打断扫视。
- 不要引入 React/Vue/Vite。
- 不要让移动端横向溢出。
- 不要把“Source: Video”这种模糊标签单独展示，必须展示实际标题。

## 9. Responsive Behavior

| Name | Width | Key Changes |
|------|-------|-------------|
| Desktop | > 1180px | 左 rail + 主列 + 右 inspector |
| Tablet | 820-1180px | rail 压缩为顶部，主列和 inspector 单列 |
| Mobile | < 820px | 全部单列，导航横向滚动，卡片缩短摘要 |

**Touch Targets:** 最小 44px。
**Collapsing Strategy:** 移动端隐藏次级解释，但保留 title、score、source、summary 和链接。
