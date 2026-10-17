// Builds the EVOSGPT React app for the /evosgpt mount and drops it into dist/evosgpt.
// Runs after the Hub's own vite build (which empties dist/). Skip with SKIP_EVOSGPT_BUILD=1.
import { execSync } from 'node:child_process'
import path from 'node:path'
import fs from 'node:fs'

if (process.env.SKIP_EVOSGPT_BUILD === '1') { console.log('[evosgpt] skipped'); process.exit(0) }

const app = path.resolve('..', 'evosgpt', 'evosgpt-frontend')
const out = path.resolve('dist', 'evosgpt')
if (!fs.existsSync(app)) { console.error('[evosgpt] source not found at', app); process.exit(1) }

const env = {
  ...process.env,
  VITE_BASE_PATH: '/evosgpt/',
  VITE_HUB_API_URL: process.env.VITE_API_BASE_URL || 'https://api.evoshub.xyz',
}
execSync('npm ci --no-audit --no-fund', { cwd: app, stdio: 'inherit', env })
execSync(`npx vite build --outDir "${out}" --emptyOutDir`, { cwd: app, stdio: 'inherit', env })
// A _redirects file in a subfolder is ignored by Netlify; the root netlify.toml owns routing.
fs.rmSync(path.join(out, '_redirects'), { force: true })
console.log('[evosgpt] built into', out)
