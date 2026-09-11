import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

// Сборка кладётся в src/postify/web/static/ и коммитится: прод обновляется
// через git merge без пересборки Docker.
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  base: './',
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  build: {
    outDir: path.resolve(__dirname, '../src/postify/web/static'),
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': {
        target: loadEnv(mode, process.cwd(), '').VITE_API_TARGET || 'http://127.0.0.1:8000',
        // Preserve the browser Host so the backend can verify Origin on mutations.
        changeOrigin: false,
      },
    },
  },
}))
