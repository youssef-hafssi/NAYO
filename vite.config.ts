import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// /bot-api/* is forwarded to the bot (same origin for the admin login cookie):
// - in dev by this proxy (BOT_PROXY_TARGET, default: the bot running locally on :8000)
// - in production by the rewrite in vercel.json
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react(), tailwindcss()],
    server: {
      proxy: {
        '/bot-api': {
          target: env.BOT_PROXY_TARGET || 'http://127.0.0.1:8000',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/bot-api/, ''),
        },
      },
    },
  }
})
