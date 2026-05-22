<script setup lang="ts">
import { reactive, ref } from 'vue'
import AppShell from '../components/AppShell.vue'
import StateBlock from '../components/StateBlock.vue'
import { api } from '../services/api'

const form = reactive({ name: '', contact: '', message: '' })
const status = ref('')
const error = ref('')
const sending = ref(false)

async function submit() {
  status.value = ''
  error.value = ''
  sending.value = true
  try {
    await api.feedback(form)
    status.value = '反馈已提交'
    form.message = ''
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    sending.value = false
  }
}
</script>

<template>
  <AppShell>
    <section class="feedback-layout">
      <form class="feedback-form" @submit.prevent="submit">
        <label>
          <span>称呼</span>
          <input v-model="form.name" placeholder="可选" />
        </label>
        <label>
          <span>联系方式</span>
          <input v-model="form.contact" placeholder="可选" />
        </label>
        <label>
          <span>反馈内容</span>
          <textarea v-model="form.message" required rows="8" placeholder="栏目、信源、文章质量或产品建议" />
        </label>
        <button class="primary-button" type="submit" :disabled="sending || !form.message.trim()">
          {{ sending ? '提交中' : '提交反馈' }}
        </button>
      </form>
      <StateBlock v-if="status" :title="status" />
      <StateBlock v-if="error" title="提交失败" detail="请稍后重试。" />
    </section>
  </AppShell>
</template>
