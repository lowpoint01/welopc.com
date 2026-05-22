<script setup lang="ts">
import { computed, ref } from 'vue'
import { ChevronDown, ExternalLink } from '@lucide/vue'
import type { MpArticle } from '../services/api'
import { compactText, formatDateTime, scoreClass } from '../services/normalizers'

const props = defineProps<{ item: MpArticle }>()
const open = ref(false)
const summary = computed(() => compactText(props.item.summary, 128))
const heat = computed(() => Number(props.item.heatScore || 0))
const relevance = computed(() => Number(props.item.aiRelevanceScore || 0))
const anomaly = computed(() => Number(props.item.anomalyScore || 0))
</script>

<template>
  <article class="signal-card mp-card">
    <div class="signal-card-body">
      <div class="card-kicker">
        <span class="source-pip"></span>
        <span>{{ item.accountName || '公众号' }}</span>
        <span>{{ item.sourceOrigin || '动态采集' }}</span>
        <span>{{ formatDateTime(item.publishedAt) }}</span>
      </div>

      <div class="article-title-row">
        <h3>{{ compactText(item.title, 96) }}</h3>
        <a v-if="item.url" :href="item.url" target="_blank" rel="noreferrer" class="ghost-link" title="打开原文">
          <ExternalLink :size="15" />
        </a>
      </div>

      <p v-if="summary" class="article-summary">{{ summary }}</p>

      <div class="tag-row">
        <span class="tag">AI 相关 {{ relevance.toFixed(0) }}</span>
        <span class="tag">热度 {{ heat.toFixed(1) }}</span>
        <span v-if="anomaly > 0" class="tag muted">异常 {{ anomaly.toFixed(1) }}</span>
        <span v-for="tag in (item.tags || []).slice(0, 2)" :key="tag" class="tag">{{ tag }}</span>
      </div>

      <button class="detail-toggle" type="button" @click="open = !open">
        <span>{{ open ? '收起公众号信号' : '查看公众号信号' }}</span>
        <ChevronDown :size="15" :class="{ open }" />
      </button>

      <Transition name="detail">
        <div v-if="open" class="signal-detail">
          <p>账号 {{ item.accountName || '未知' }}，AI 相关度 {{ relevance.toFixed(0) }}，热度 {{ heat.toFixed(1) }}。</p>
        </div>
      </Transition>
    </div>

    <div class="signal-score" :class="scoreClass(heat)">
      <strong>{{ heat.toFixed(1) }}</strong>
      <small>heat</small>
    </div>
  </article>
</template>
