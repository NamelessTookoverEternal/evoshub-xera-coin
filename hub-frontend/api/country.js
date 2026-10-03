// Vercel equivalent of netlify/edge-functions/country.js
export default function handler(req, res) {
  const code = req.headers['x-vercel-ip-country'] || null
  res.setHeader('Cache-Control', 'no-store')
  res.status(200).json({ country: code })
}
