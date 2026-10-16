// Builds the EVOS Data React app for the /evosdata mount and drops it into dist/evosdata.
// Runs after the Hub's own vite build (which empties dist/). Skip with SKIP_EVOSDATA_BUILD=1.
import { execSync } from 'node:child_process'
import path from 'node:path'
import fs from 'node:fs'

if (process.env.SKIP_EVOSDATA_BUILD === '1') { console.log('[evosdata] skipped'); process.exit(0) }

const app = path.resolve('..', 'evosdata', 'evos-frontend')
const out = path.resolve('dist', 'evosdata')
if (!fs.existsSync(app)) { console.error('[evosdata] source not found at', app); process.exit(1) }

const env = {
  ...process.env,
  VITE_BASE_PATH: '/evosdata/',
  VITE_HUB_API_URL: process.env.VITE_API_BASE_URL || 'https://api.evoshub.xyz',
}
execSync('npm ci --no-audit --no-fund', { cwd: app, stdio: 'inherit', env })
execSync(`npx vite build --outDir "${out}" --emptyOutDir`, { cwd: app, stdio: 'inherit', env })
// The PWA manifest must be scoped to the mount point, not the whole Hub origin.
const mf = path.join(out, 'manifest.webmanifest')
if (fs.existsSync(mf)) {
  const m = JSON.parse(fs.readFileSync(mf, 'utf8'))
  const pre = (u) => (typeof u === 'string' && u.startsWith('/') && !u.startsWith('/evosdata') ? '/evosdata' + u : u)
  m.start_url = '/evosdata/'; m.scope = '/evosdata/'; if (m.id) m.id = '/evosdata/'
  for (const i of m.icons || []) i.src = pre(i.src)
  for (const sc of m.shortcuts || []) { sc.url = pre(sc.url); for (const i of sc.icons || []) i.src = pre(i.src) }
  fs.writeFileSync(mf, JSON.stringify(m, null, 2))
}
// A _redirects file in a subfolder is ignored by Netlify; the root netlify.toml owns routing.
fs.rmSync(path.join(out, '_redirects'), { force: true })
console.log('[evosdata] built into', out)
