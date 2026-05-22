<script setup lang="ts">
import type { Component } from 'vue'

defineProps<{
  label: string
  value: string | number
  detail?: string
  tone?: 'cyan' | 'green' | 'amber' | 'red' | 'blue'
  icon?: Component
}>()
</script>

<template>
  <article class="metric-card" :class="`tone-${tone || 'cyan'}`">
    <div class="metric-icon" v-if="icon">
      <component :is="icon" :size="20" />
    </div>
    <div>
      <span>{{ label }}</span>
      <strong>{{ value }}</strong>
      <small v-if="detail">{{ detail }}</small>
    </div>
  </article>
</template>
