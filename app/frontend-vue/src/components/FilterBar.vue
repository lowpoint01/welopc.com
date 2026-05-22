<script setup lang="ts">
import { Search, SlidersHorizontal } from '@lucide/vue'

defineProps<{
  query: string
  channel?: string
  showChannel?: boolean
}>()

const emit = defineEmits<{
  'update:query': [value: string]
  'update:channel': [value: string]
}>()

const channels = [
  ['all', '全部'],
  ['firstParty', '官方'],
  ['github', 'GitHub'],
  ['community', '社区'],
  ['news', '资讯'],
  ['product', '产品'],
]
</script>

<template>
  <div class="filter-bar">
    <label class="search-box">
      <Search :size="17" />
      <input :value="query" placeholder="搜索标题、来源或关键词" @input="emit('update:query', ($event.target as HTMLInputElement).value)" />
    </label>
    <div v-if="showChannel" class="segmented" aria-label="频道过滤">
      <SlidersHorizontal :size="15" />
      <button
        v-for="[value, label] in channels"
        :key="value"
        type="button"
        :class="{ active: channel === value }"
        @click="emit('update:channel', value)"
      >
        {{ label }}
      </button>
    </div>
  </div>
</template>
