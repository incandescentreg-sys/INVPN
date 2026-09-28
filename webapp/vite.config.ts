import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// VITE_API_URL is injected at build time (Vercel / docker). Falls back to the
// same origin, which is what you want when the API is proxied behind the same
// domain as the Web App.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    target: 'es2020',
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom', 'react-router-dom'],
        },
      },
    },
  },
})
