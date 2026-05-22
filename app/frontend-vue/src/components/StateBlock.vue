<script setup lang="ts">
defineProps<{
  title: string
  detail?: string
}>()
</script>

<template>
  <div class="state-block">
    <span class="pulse-dot"></span>
    <strong>{{ title }}</strong>
    <p v-if="detail">{{ detail }}</p>
  </div>
</template>
