import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The build lands inside the Python package so `hushmask serve` can serve it at /dashboard/.
// In dev (`npm run dev`), API calls go to a running `hushmask serve` on port 8700.
export default defineConfig({
  base: '/dashboard/',
  plugins: [react(), tailwindcss()],
  build: { outDir: '../src/hushmask/web_dist', emptyOutDir: true },
  server: {
    proxy: {
      '/hushmask': 'http://127.0.0.1:8700',
      '/v1': 'http://127.0.0.1:8700',
    },
  },
})
