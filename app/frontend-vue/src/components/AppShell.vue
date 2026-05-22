<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { Home, MessageCircle, Newspaper, Radio, RefreshCw, Sparkles, Target } from '@lucide/vue'
import StarfieldBackdrop from './StarfieldBackdrop.vue'
import { useModulesStore } from '../stores/modules'
import { formatDateTime } from '../services/normalizers'

const route = useRoute()
const modules = useModulesStore()
const refreshing = ref(false)
const scanning = ref(false)

const navItems = [
  { path: '/', label: '首页', code: 'home', icon: Home },
  { path: '/selected', label: '精选', code: 'selected', icon: Sparkles },
  { path: '/feed', label: '动态', code: 'feed', icon: Radio },
  { path: '/daily', label: '日报', code: 'daily', icon: Newspaper },
  { path: '/mp', label: '公众号', code: 'mp', icon: MessageCircle },
  { path: '/opc', label: 'OPC', code: 'opcSolo', icon: Target },
]

const currentLabel = computed(() => String(route.meta.label || 'AI HOT'))
const currentSubtitle = computed(() => String(route.meta.subtitle || '实时 AI 信号雷达'))
const latestRun = computed(() => modules.stats?.latestRun)

function moduleCount(code: string) {
  if (code === 'home') return ''
  return modules.moduleMap.get(code)?.count ?? ''
}

async function refresh() {
  refreshing.value = true
  scanning.value = true
  try {
    await modules.load()
  } finally {
    window.setTimeout(() => {
      refreshing.value = false
      scanning.value = false
    }, 520)
  }
}

onMounted(() => {
  if (!modules.summary && !modules.loading) void modules.load()
})

watch(
  () => route.fullPath,
  () => {
    scanning.value = true
    window.setTimeout(() => {
      scanning.value = false
    }, 420)
  },
)
</script>

<template>
  <div class="signal-app">
    <StarfieldBackdrop />
    <div class="scan-sweep" :class="{ active: scanning }" aria-hidden="true"></div>

    <header class="shell-header">
      <RouterLink class="shell-brand" to="/">
        <span class="brand-mark">W</span>
        <span>
          <strong>WelOPC</strong>
          <small>AI HOT</small>
        </span>
      </RouterLink>

      <nav class="shell-nav" aria-label="AI HOT 栏目">
        <RouterLink v-for="item in navItems" :key="item.path" :to="item.path" class="nav-lock">
          <component :is="item.icon" :size="15" />
          <span>{{ item.label }}</span>
          <small v-if="moduleCount(item.code) !== ''">{{ moduleCount(item.code) }}</small>
        </RouterLink>
      </nav>

      <div class="header-actions">
        <button class="refresh-button" type="button" :class="{ loading: refreshing }" @click="refresh">
          <RefreshCw :size="15" />
          <span>刷新</span>
        </button>
      </div>
    </header>

    <main class="shell-main">
      <section v-if="route.name !== 'home'" class="route-hero compact">
        <div>
          <p class="overline">AI SIGNAL</p>
          <h1>{{ currentLabel }}</h1>
          <p>{{ currentSubtitle }}</p>
        </div>
        <div class="quiet-status">
          <span>{{ latestRun?.finished_at ? formatDateTime(latestRun.finished_at) : '等待采集' }}</span>
        </div>
      </section>

      <slot />
    </main>
  </div>
</template>
