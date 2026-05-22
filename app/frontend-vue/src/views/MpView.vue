<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import MpArticleCard from '../components/MpArticleCard.vue'
import StateBlock from '../components/StateBlock.vue'
import { api, type MpArticle } from '../services/api'

const items = ref<MpArticle[]>([])
const period = ref('all')
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await api.mp({ limit: 80, period: period.value })
    items.value = data.items || []
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <AppShell>
    <section class="page-kernel">
      <span>WECHAT MONITOR</span>
      <h2>公众号观察台</h2>
      <p>按账号、热度、AI 相关度和异常分数整理，进入列表前会清洗 HTML、话题链接和长文本。</p>
    </section>

    <div class="segmented standalone">
      <button :class="{ active: period === 'all' }" type="button" @click="period = 'all'; load()">全部</button>
      <button :class="{ active: period === '7d' }" type="button" @click="period = '7d'; load()">近 7 天</button>
      <button :class="{ active: period === '30d' }" type="button" @click="period = '30d'; load()">近 30 天</button>
    </div>

    <StateBlock v-if="loading" title="正在加载公众号文章" />
    <StateBlock v-else-if="error" title="暂时无法读取内容" detail="请稍后刷新。" />
    <StateBlock v-else-if="!items.length" title="暂无公众号文章" detail="当前时间范围暂无入选文章。" />

    <section v-else class="feed-list">
      <MpArticleCard v-for="item in items" :key="item.id" :item="item" />
    </section>
  </AppShell>
</template>
