import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { TanStackRouterVite } from '@tanstack/router-plugin/vite'
import tailwindcss from '@tailwindcss/vite'

// Allow serving static assets from a CDN in production. The container still
// serves index.html so client-side routing works; JS/CSS assets are loaded
// from the configured CDN URL.
const base = process.env.VITE_CDN_URL || '/'

export default defineConfig({
  base,
  plugins: [
    // Route generation must stay enabled: the code splitter only processes
    // files the generator registers in globalThis.TSR_ROUTES_BY_ID_MAP, and
    // with generation disabled that map is never populated — producing a
    // single monolithic bundle despite autoCodeSplitting.
    TanStackRouterVite({ target: 'react', autoCodeSplitting: true }),
    tailwindcss(),
    react(),
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/ws': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
