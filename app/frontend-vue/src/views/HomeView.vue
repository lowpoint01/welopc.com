<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { MessageCircle, Newspaper, Radio, Sparkles, Target } from '@lucide/vue'
import AppShell from '../components/AppShell.vue'
import ArticleCard from '../components/ArticleCard.vue'
import StateBlock from '../components/StateBlock.vue'
import { useModulesStore } from '../stores/modules'
import { api, type ArticleItem } from '../services/api'
import { formatDateTime } from '../services/normalizers'

const modules = useModulesStore()
const selected = ref<ArticleItem[]>([])
const loading = ref(true)
const error = ref('')

const latestRun = computed(() => modules.stats?.latestRun)

function count(code: string) {
  return modules.moduleMap.get(code)?.count || 0
}

const channels = computed(() => [
  { to: '/selected', label: '精选', code: 'selected', count: count('selected'), icon: Sparkles },
  { to: '/feed', label: '全部动态', code: 'feed', count: count('feed'), icon: Radio },
  { to: '/daily', label: 'AI 日报', code: 'daily', count: count('daily'), icon: Newspaper },
  { to: '/mp', label: '公众号', code: 'mp', count: count('mp'), icon: MessageCircle },
  { to: '/opc', label: 'OPC', code: 'opcSolo', count: count('opcSolo'), icon: Target },
])

async function load() {
  loading.value = true
  error.value = ''
  try {
    await modules.load()
    const selectedData = await api.feed({ mode: 'selected', channel: 'all', limit: 5 })
    selected.value = selectedData.items || []
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
    <StateBlock v-if="loading" title="正在读取今日信号" detail="整理精选内容。" />
    <StateBlock v-else-if="error" title="暂时无法读取内容" detail="请稍后刷新。" />

    <template v-else>
      <section class="reader-layout">
        <div class="today-list">
          <div class="clean-heading">
            <span>TODAY</span>
            <h2>今日必看</h2>
            <p>保留最值得先读的 5 条信号，其他状态信息已收起到右上角。</p>
          </div>

          <ArticleCard v-for="item in selected" :key="item.id" :item="item" variant="selected" />
        </div>

        <aside class="quiet-rail">
          <section class="rail-card">
            <span>更新</span>
            <strong>{{ latestRun?.finished_at ? formatDateTime(latestRun.finished_at) : '等待采集' }}</strong>
          </section>

          <section class="rail-card channel-rail">
            <RouterLink v-for="channel in channels" :key="channel.code" :to="channel.to">
              <component :is="channel.icon" :size="15" />
              <span>{{ channel.label }}</span>
              <strong>{{ channel.count }}</strong>
            </RouterLink>
          </section>

        </aside>
      </section>
    </template>
  </AppShell>
</template>
