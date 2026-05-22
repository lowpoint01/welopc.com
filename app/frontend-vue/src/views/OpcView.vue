<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import AppShell from '../components/AppShell.vue'
import ArticleCard from '../components/ArticleCard.vue'
import FilterBar from '../components/FilterBar.vue'
import StateBlock from '../components/StateBlock.vue'
import { api, type ArticleItem } from '../services/api'

const items = ref<ArticleItem[]>([])
const query = ref('')
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await api.feed({ mode: 'all', channel: 'opcSolo', q: query.value, limit: 80 })
    items.value = data.items || []
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

onMounted(load)
let timer = 0
watch(query, () => {
  window.clearTimeout(timer)
  timer = window.setTimeout(load, 260)
})
</script>

<template>
  <AppShell>
    <section class="page-kernel">
      <span>OPC SOLO</span>
      <h2>一人公司机会筛选器</h2>
      <p>从全部信源中挑出更适合自动化、获客、交付、产品化和低成本验证的内容。</p>
    </section>

    <FilterBar v-model:query="query" />

    <StateBlock v-if="loading" title="正在加载 OPC 信号" />
    <StateBlock v-else-if="error" title="暂时无法读取内容" detail="请稍后刷新。" />
    <StateBlock v-else-if="!items.length" title="暂无内容" detail="当前筛选条件没有匹配结果。" />

    <TransitionGroup v-else name="list" tag="section" class="feed-list">
      <ArticleCard v-for="item in items" :key="item.id" :item="item" variant="opc" />
    </TransitionGroup>
  </AppShell>
</template>
