const namedEntities: Record<string, string> = {
  nbsp: ' ',
  amp: '&',
  lt: '<',
  gt: '>',
  quot: '"',
  apos: "'",
}

function decodeHtml(value: string): string {
  return value
    .replace(/&([a-z]+);/gi, (match, name: string) => namedEntities[name.toLowerCase()] || match)
    .replace(/&#(\d+);/g, (_match, code: string) => String.fromCharCode(Number(code)))
    .replace(/&#x([0-9a-f]+);/gi, (_match, code: string) => String.fromCharCode(Number.parseInt(code, 16)))
}

export function compactText(value: unknown, limit = 180): string {
  const raw = typeof value === 'string' ? value : value == null ? '' : String(value)
  const decoded = decodeHtml(raw)
  const withoutWxTopics = decoded.replace(/<a\b[^>]*class=["'][^"']*wx_topic_link[^"']*["'][^>]*>(.*?)<\/a>/gis, '$1')
  const noTags = withoutWxTopics
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
  const clean = noTags
    .replace(/\b(?:topic-id|data-topic|data-recommend|style|class)=["'][^"']*["']/gi, ' ')
    .replace(/https?:\/\/\S+/gi, ' ')
    .replace(/\s+([，。！？；：、,.!?;:])/g, '$1')
    .replace(/([#＃][\w\u4e00-\u9fa5-]{1,32})\s*/g, '$1 ')
    .replace(/\s+/g, ' ')
    .trim()
  if (clean.length <= limit) return clean
  return `${clean.slice(0, Math.max(0, limit - 1)).trim()}...`
}

export function formatDateTime(value?: string | null): string {
  if (!value) return '未知时间'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

export function formatFullDate(value?: string | null): string {
  if (!value) return '未知日期'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date)
}

export function scoreClass(score?: number | null): string {
  const n = Number(score || 0)
  if (n >= 85) return 'score-hot'
  if (n >= 70) return 'score-strong'
  if (n >= 50) return 'score-normal'
  return 'score-muted'
}
