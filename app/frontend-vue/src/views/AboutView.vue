<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import StateBlock from '../components/StateBlock.vue'
import { api, type RulesResponse } from '../services/api'
import { useModulesStore } from '../stores/modules'

const modules = useModulesStore()
const rules = ref<RulesResponse['items']>([])
const error = ref('')

onMounted(async () => {
  try {
    await modules.load()
    const data = await api.rules()
    rules.value = data.items || []
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  }
})
</script>

<template>
  <AppShell>
    <StateBlock v-if="error" title="暂时无法读取规则" detail="请稍后刷新。" />
    <section class="page-kernel">
      <span>RULES</span>
      <h2>信号筛选规则</h2>
      <p>AI HOT 把多源动态转成五个阅读场景，前台只呈现清洗后的标题、摘要、来源、标签和评分。</p>
    </section>

    <section class="rules-grid">
      <article v-for="rule in rules" :key="rule.code" class="rule-card">
        <span>{{ rule.code }}</span>
        <h3>{{ rule.name }}</h3>
        <p>{{ rule.description }}</p>
        <div class="tag-row">
          <span v-for="item in (rule.scoreSignals || rule.include || []).slice(0, 4)" :key="item" class="tag">{{ item }}</span>
        </div>
      </article>
    </section>
  </AppShell>
</template>
