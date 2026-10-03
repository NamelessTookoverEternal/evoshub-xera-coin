import { defineConfig } from 'vite'
import fs from 'node:fs'
import path from 'node:path'

// Dev/preview convenience: mirror the host's pretty-URL rewrites
// (/appevoxera -> /appevoxera.html, /xera -> /xera/index.html) so
// local navigation matches production. Production uses netlify.toml / vercel.json.
function prettyUrls(rootDirs) {
  const handler = (req, _res, next) => {
    const raw = (req.url || '').split('?')[0]
    if (raw !== '/' && !path.extname(raw)) {
      const clean = raw.replace(/\/$/, '')
      const candidates = [`${clean}.html`, `${clean}/index.html`]
      const hit = candidates.find((c) => rootDirs.some((d) => fs.existsSync(path.join(d, c))))
      if (hit) req.url = hit + (req.url.includes('?') ? '?' + req.url.split('?')[1] : '')
    }
    next()
  }
  return {
    name: 'evos-pretty-urls',
    configureServer(server) { server.middlewares.use(handler) },
    configurePreviewServer(server) { server.middlewares.use(handler) },
  }
}

export default defineConfig({
  root: 'src/pages',
  plugins: [prettyUrls([path.resolve('src/pages'), path.resolve('dist')])],
  publicDir: '../../public',
  build: {
    outDir: '../../dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main:              'src/pages/index.html',
        home:              'src/pages/home.html',
        appEvoxera:        'src/pages/appevoxera.html',
        about:             'src/pages/about.html',
        services:          'src/pages/services.html',
        contact:           'src/pages/contact.html',
        websiteCreation:   'src/pages/website-creation.html',
        businessTools:     'src/pages/business-tools.html',
        adminLogin:        'src/pages/admin-login.html',
        adminWebsiteChat:  'src/pages/admin-website-chat.html',
        comingSoon:        'src/pages/coming-soon.html',
        notFound:          'src/pages/404.html',
        xera:               'src/pages/xera/index.html',
        xeraApp:            'src/pages/xera/app.html',
        xeraInvite:         'src/pages/xera/invite.html',
        xeraWhitepaper:     'src/pages/xera/whitepaper.html',
        xeraStats:          'src/pages/xera/stats.html',
        xeraTokenomics:     'src/pages/xera/tokenomics.html',
        xeraRoadmap:        'src/pages/xera/roadmap.html',
        xeraFaq:            'src/pages/xera/faq.html',
        xeraDisclosure:     'src/pages/xera/disclosure.html',
        ecosystem:          'src/pages/ecosystem.html',
      }
    }
  }
})
