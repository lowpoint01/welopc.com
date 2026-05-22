<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppShell from '../components/AppShell.vue'
import ArticleCard from '../components/ArticleCard.vue'
import FilterBar from '../components/FilterBar.vue'
import StateBlock from '../components/StateBlock.vue'
import { api, type ArticleItem } from '../services/api'

const route = useRoute()
const items = ref<ArticleItem[]>([])
const query = ref('')
const channel = ref('all')
const loading = ref(false)
const error = ref('')

const mode = computed(() => String(route.meta.mode || 'all'))
const showChannel = computed(() => mode.value === 'all')
const heading = computed(() => (mode.value === 'selected' ? '高价值信号墙' : '实时 AI 动态流'))
const intro = computed(() =>
  mode.value === 'selected'
    ? '优先展示高置信、强影响、可直接进入阅读队列的信号。'
    : '按时间和来源持续滚动，保留搜索与来源过滤，方便快速扫描。',
)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await api.feed({ mode: mode.value, channel: channel.value, q: query.value, limit: 72 })
    items.value = data.items || []
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch([mode, channel], load)
let timer = 0
watch(query, () => {
  window.clearTimeout(timer)
  timer = window.setTimeout(load, 260)
})
</script>

<template>
  <AppShell>
    <section class="page-kernel">
      <span>{{ mode === 'selected' ? 'SELECTED' : 'STREAM' }}</span>
      <h2>{{ heading }}</h2>
      <p>{{ intro }}</p>
    </section>

    <FilterBar v-model:query="query" v-model:channel="channel" :show-channel="showChannel" />

    <StateBlock v-if="loading" title="正在加载信号" detail="列表会在读取完成后平滑更新。" />
    <StateBlock v-else-if="error" title="暂时无法读取内容" detail="请稍后刷新。" />
    <StateBlock v-else-if="!items.length" title="暂无内容" detail="当前筛选条件没有匹配结果。" />

    <TransitionGroup v-else name="list" tag="section" class="feed-list">
      <ArticleCard v-for="item in items" :key="item.id" :item="item" :variant="mode === 'selected' ? 'selected' : 'stream'" />
    </TransitionGroup>
  </AppShell>
</template>
