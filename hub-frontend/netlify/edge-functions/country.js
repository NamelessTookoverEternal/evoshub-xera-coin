// Returns the visitor's country as derived by Netlify's edge from the request IP.
// Used only for UX gating on /appevoxera (no browser geolocation prompt).
export default async (_request, context) => {
  const code = context?.geo?.country?.code ?? null
  return new Response(JSON.stringify({ country: code }), {
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  })
}

export const config = { path: '/api/country' }
