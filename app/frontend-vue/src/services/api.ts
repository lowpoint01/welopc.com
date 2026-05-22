export interface ModuleItem {
  code: string
  name: string
  status: string
  count: number
}

export interface ModelStatus {
  available: boolean
  status: string
  label: string
  model?: string
  thinking?: string
  reasoningEffort?: string
  promptVersion?: string
  itemEnrichments?: Record<string, number>
  mpEnrichments?: Record<string, number>
  latestError?: string
  latestOkAt?: string
  latestErrorAt?: string
  errorDigest?: {
    recentErrorCount?: number
    byKind?: Record<string, number>
    samples?: Array<{ scope?: string; kind?: string; updatedAt?: string; error?: string }>
  }
}

export interface ChannelMetric {
  channel: string
  name: string
  itemCount: number
  candidateCount: number
  selectedCandidateCount: number
  avgScore: number
  maxScore: number
  newestAt?: string
  oldestAt?: string
  topSources?: Array<{ name: string; count: number; avgScore: number }>
}

export interface SourceAttention {
  sourceName: string
  channel: string
  status: string
  detail?: string
  checkedAt?: string
}

export interface ModuleSummary {
  modules: ModuleItem[]
  sourceSummary?: {
    total: number
    byStatus: Record<string, number>
    byChannel: Record<string, number>
  }
  wechatSourceSummary?: {
    configured: number
    enabled: number
    ready: number
    declaredReady?: number
    lastCheckedAt?: string
    wechatAuthStatus?: string
    wechatAuthStatusRaw?: string
    wechatSessionStatus?: string
    wechatSessionIssue?: {
      status?: string
      affectedSources?: number
      checkedAt?: string
      samples?: string[]
      detail?: string
    }
  }
  channelMetrics?: ChannelMetric[]
  sourceHealth?: {
    latestTotal?: number
    byStatus?: Record<string, number>
    byChannel?: Record<string, number>
    byErrorKind?: Record<string, number>
    itemCount?: number
    lastCheckedAt?: string
    wechatSessionIssue?: {
      status?: string
      affectedSources?: number
      checkedAt?: string
      samples?: string[]
      detail?: string
    }
    attention?: SourceAttention[]
  }
  modelStatus?: ModelStatus
}

export interface ArticleItem {
  id: number | string
  title?: string
  titleZh?: string
  summary?: string
  summaryZh?: string
  url?: string
  link?: string
  sourceName?: string
  source?: { name?: string; kind?: string }
  sourceKind?: string
  source_kind?: string
  channel?: string
  publishedAt?: string
  dateLabel?: string
  timeLabel?: string
  finalScore?: number
  heatScore?: number
  channelScore?: number
  importance?: number
  qualityScore?: number
  aiSelected?: boolean
  aiSelectedReason?: string
  aiTags?: Array<{ tag?: string } | string>
  duplicateCount?: number
  editorialJudgment?: string
}

export interface FeedResponse {
  items: ArticleItem[]
  nextCursor?: string
  count?: number
}

export interface MpArticle {
  id: string | number
  title: string
  accountName: string
  url?: string
  publishedAt?: string
  summary?: string
  heatScore?: number
  anomalyScore?: number
  aiRelevanceScore?: number
  tags?: string[]
  sourceOrigin?: string
}

export interface MpResponse {
  items: MpArticle[]
  count?: number
}

export interface DailyIssue {
  id?: number
  issueDate?: string
  title: string
  summary?: string
  content?: {
    groups?: Record<string, ArticleItem[]>
    items?: ArticleItem[]
  }
  markdown?: string
  status?: string
  generatedAt?: string
}

export interface DailyListResponse {
  items: DailyIssue[]
  count?: number
}

export interface RulesResponse {
  items: Array<{
    code: string
    name: string
    description: string
    include?: string[]
    exclude?: string[]
    scoreSignals?: string[]
  }>
}

export interface StatsResponse {
  counts: Record<string, number>
  latestRun?: {
    id: number
    run_type: string
    status: string
    started_at: string
    finished_at?: string
    message?: string
  }
  newestItemAt?: string
}

const API_BASE = `${import.meta.env.BASE_URL.replace(/\/$/, '')}/api`

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`)
  }
  return response.json() as Promise<T>
}

export const api = {
  modules: () => request<ModuleSummary>('/public/modules'),
  stats: () => request<StatsResponse>('/public/stats'),
  rules: () => request<RulesResponse>('/public/rules'),
  feed: (params: { mode?: string; channel?: string; q?: string; limit?: number; cursor?: string }) => {
    const search = new URLSearchParams()
    search.set('mode', params.mode || 'all')
    search.set('channel', params.channel || 'all')
    search.set('limit', String(params.limit || 30))
    search.set('q', params.q || '')
    if (params.cursor) search.set('cursor', params.cursor)
    return request<FeedResponse>(`/public/feed?${search}`)
  },
  mp: (params: { limit?: number; period?: string } = {}) => {
    const search = new URLSearchParams()
    search.set('limit', String(params.limit || 40))
    search.set('period', params.period || 'all')
    return request<MpResponse>(`/public/mp?${search}`)
  },
  dailyLatest: (date = '') => request<DailyIssue>(`/public/daily/latest${date ? `?date=${encodeURIComponent(date)}` : ''}`),
  dailyList: (limit = 12) => request<DailyListResponse>(`/public/daily/list?limit=${limit}`),
  feedback: (payload: Record<string, string>) =>
    request<{ status: string }>('/public/feedback', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
}
