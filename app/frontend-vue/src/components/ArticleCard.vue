<script setup lang="ts">
import { computed, ref } from 'vue'
import { ChevronDown, ExternalLink } from '@lucide/vue'
import type { ArticleItem } from '../services/api'
import { compactText, formatDateTime, scoreClass } from '../services/normalizers'

const props = defineProps<{
  item: ArticleItem
  compact?: boolean
  variant?: 'selected' | 'stream' | 'opc'
}>()

const open = ref(false)
const title = computed(() => compactText(props.item.titleZh || props.item.title, props.compact ? 72 : 96))
const summary = computed(() =>
  compactText(props.item.summaryZh || props.item.summary || props.item.editorialJudgment, props.compact ? 96 : 138),
)
const source = computed(() => props.item.sourceName || props.item.source?.name || '未知来源')
const kind = computed(() => props.item.sourceKind || props.item.source_kind || props.item.channel || 'signal')
const score = computed(() => Number(props.item.channelScore ?? props.item.finalScore ?? props.item.heatScore ?? props.item.importance ?? 0))
const tags = computed(() =>
  (props.item.aiTags || [])
    .map((tag) => (typeof tag === 'string' ? tag : tag.tag))
    .filter(Boolean)
    .slice(0, 4),
)
const reason = computed(() => compactText(props.item.aiSelectedReason || props.item.editorialJudgment, 180))
const detailLine = computed(() => {
  const parts = [
    props.item.duplicateCount ? `重复 ${props.item.duplicateCount}` : '',
    props.item.qualityScore ? `质量 ${Number(props.item.qualityScore).toFixed(0)}` : '',
    props.item.importance ? `重要 ${Number(props.item.importance).toFixed(0)}` : '',
  ].filter(Boolean)
  return parts.join(' / ')
})
</script>

<template>
  <article class="signal-card" :class="[`variant-${variant || 'stream'}`, { compact }]">
    <div class="signal-card-body">
      <div class="card-kicker">
        <span class="source-pip"></span>
        <span>{{ source }}</span>
        <span>{{ kind }}</span>
        <span>{{ formatDateTime(item.publishedAt) }}</span>
      </div>

      <div class="article-title-row">
        <h3>{{ title }}</h3>
        <a v-if="item.url || item.link" :href="item.url || item.link" target="_blank" rel="noreferrer" class="ghost-link" title="打开原文">
          <ExternalLink :size="15" />
        </a>
      </div>

      <p v-if="summary" class="article-summary">{{ summary }}</p>

      <div class="tag-row" v-if="tags.length || reason">
        <span v-for="tag in tags" :key="tag" class="tag">{{ tag }}</span>
        <span v-if="variant === 'opc'" class="tag accent">可执行</span>
      </div>

      <button v-if="reason || detailLine" class="detail-toggle" type="button" @click="open = !open">
        <span>{{ open ? '收起信号详情' : '查看信号详情' }}</span>
        <ChevronDown :size="15" :class="{ open }" />
      </button>

      <Transition name="detail">
        <div v-if="open" class="signal-detail">
          <p v-if="reason">{{ reason }}</p>
          <small v-if="detailLine">{{ detailLine }}</small>
        </div>
      </Transition>
    </div>

    <div class="signal-score" :class="scoreClass(score)">
      <strong>{{ score.toFixed(1) }}</strong>
      <small>signal</small>
    </div>
  </article>
</template>
