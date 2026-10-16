// Ecosystem links are admin-curated (xera_ecosystem_links), so a row can still
// hold the standalone EVOS Data address. EVOS Data now lives inside the Hub at
// /evosdata, so those rows open in-app instead of leaving for evosdata.xyz.
// Every other link is returned untouched and stays an external, new-tab link.
const STANDALONE_EVOSDATA_HOSTS = new Set(['evosdata.xyz', 'www.evosdata.xyz'])

export function resolveEcosystemLink(rawUrl) {
  try {
    const u = new URL(rawUrl, window.location.origin)
    if (STANDALONE_EVOSDATA_HOSTS.has(u.hostname.toLowerCase())) {
      const path = u.pathname === '/' ? '' : u.pathname
      return { href: `/evosdata${path}${u.search}${u.hash}`, external: false }
    }
  } catch { /* not a parsable URL: fall through, leave as-is */ }
  return { href: rawUrl, external: true }
}
