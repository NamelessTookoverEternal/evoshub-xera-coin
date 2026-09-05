import { defineConfig } from 'vite'

export default defineConfig({
  root: 'src/pages',
  publicDir: '../../public',
  build: {
    outDir: '../../dist',
    rollupOptions: {
      input: {
        main:              'src/pages/index.html',
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
