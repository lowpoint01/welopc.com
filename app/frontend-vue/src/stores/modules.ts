import { defineStore } from 'pinia'
import { api, type ModuleSummary, type StatsResponse } from '../services/api'

export const useModulesStore = defineStore('modules', {
  state: () => ({
    summary: null as ModuleSummary | null,
    stats: null as StatsResponse | null,
    loading: false,
    error: '',
    loadedAt: '',
  }),
  getters: {
    moduleMap(state) {
      return new Map((state.summary?.modules || []).map((item) => [item.code, item]))
    },
  },
  actions: {
    async load() {
      this.loading = true
      this.error = ''
      try {
        const [summary, stats] = await Promise.all([api.modules(), api.stats()])
        this.summary = summary
        this.stats = stats
        this.loadedAt = new Date().toISOString()
      } catch (error) {
        this.error = error instanceof Error ? error.message : String(error)
      } finally {
        this.loading = false
      }
    },
  },
})
