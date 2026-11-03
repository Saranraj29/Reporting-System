import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const api = process.env.VITE_API_TARGET ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': api, '/health': api } },
  build: { chunkSizeWarningLimit: 1200 },
  test: { environment: 'jsdom', globals: true, setupFiles: ['./src/test/setup.ts'] },
})
