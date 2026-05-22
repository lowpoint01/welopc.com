import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  base: '/ai-hot/',
  plugins: [vue()],
  server: {
    proxy: {
      '/ai-hot/api': {
        target: 'https://welopc.com',
        changeOrigin: true,
        secure: true,
      },
    },
  },
})
