<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import ArticleCard from '../components/ArticleCard.vue'
import StateBlock from '../components/StateBlock.vue'
import { api, type ArticleItem, type DailyIssue } from '../services/api'
import { compactText, formatFullDate } from '../services/normalizers'

const issue = ref<DailyIssue | null>(null)
const issues = ref<DailyIssue[]>([])
const loading = ref(true)
const error = ref('')

const groupNames: Record<string, string> = {
  model_release: '模型发布',
  product_tool: '产品工具',
  developer: '开发与开源',
  research_paper: '研究论文',
  community: '社区讨论',
  industry: '商业行业',
  risk_policy: '风险政策',
}

function groupedItems(current: DailyIssue | null): Record<string, ArticleItem[]> {
  if (!current) return {}
  if (current.content?.groups) return current.content.groups
  if (current.content?.items) return { 今日要点: current.content.items }
  return {}
}

async function load(date = '') {
  loading.value = true
  error.value = ''
  try {
    const [latest, list] = await Promise.all([api.dailyLatest(date), api.dailyList(14)])
    issue.value = latest
    issues.value = list.items || []
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

onMounted(() => load())
</script>

<template>
  <AppShell>
    <StateBlock v-if="loading" title="正在打开日报阅读器" />
    <StateBlock v-else-if="error" title="暂时无法读取日报" detail="请稍后刷新。" />

    <section v-else-if="issue" class="daily-layout">
      <article class="daily-issue">
        <span>{{ formatFullDate(issue.issueDate) }}</span>
        <h2>{{ issue.title }}</h2>
        <p>{{ compactText(issue.summary, 220) }}</p>
      </article>

      <div class="daily-groups">
        <section v-for="(groupItems, key) in groupedItems(issue)" :key="key" class="daily-group">
          <div class="section-head">
            <span>{{ groupItems.length }} SIGNALS</span>
            <h2>{{ groupNames[key] || key }}</h2>
          </div>
          <ArticleCard v-for="item in groupItems.slice(0, 8)" :key="item.id" :item="item" compact />
        </section>
      </div>

      <aside class="history-list">
        <h2>历史日报</h2>
        <button v-for="item in issues" :key="item.id || item.issueDate" type="button" @click="load(item.issueDate || '')">
          <strong>{{ item.title }}</strong>
          <span>{{ compactText(item.summary, 70) }}</span>
        </button>
      </aside>
    </section>
  </AppShell>
</template>
