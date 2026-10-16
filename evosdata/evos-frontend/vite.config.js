import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// VITE_BASE_PATH=/evosdata/ builds the Hub-mounted version; default "/" keeps
// the standalone evosdata.xyz build identical to before.
const base = process.env.VITE_BASE_PATH || '/'

export default defineConfig({
  base,
  // Build-time constant so a Hub build contains no standalone-backend URLs at all.
  define: { __HUB_MOUNT__: JSON.stringify(base !== '/') },
  plugins: [react()],
})
