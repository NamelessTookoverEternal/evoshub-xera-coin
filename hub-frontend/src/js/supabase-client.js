// EVOSHUB — Shared Supabase client (browser-side, anon key only)
//
// SECURITY NOTE: the anon key is meant to be public — it ships in every
// Supabase browser bundle by design. It cannot read or write anything the
// Row Level Security policies don't explicitly allow. NEVER put the
// service_role key in frontend code; it bypasses RLS entirely and belongs
// only in the FastAPI backend's environment.
import { createClient } from '@supabase/supabase-js'

const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL
const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY

if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
  console.error(
    '[supabase-client] Missing VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY. ' +
    'Copy .env.example to .env and fill in your project values.'
  )
}

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
  auth: {
    // Each browser gets its own persisted anonymous session so a visitor's
    // request/chat thread survives a page refresh but is still only ever
    // theirs (enforced by RLS on auth.uid(), not by anything client-side).
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: false,
  },
})

/**
 * Ensures the browser has a Supabase session — either the visitor's existing
 * anonymous session, or a freshly created one. Anonymous auth (not a
 * client-generated UUID) is what lets RLS policies trust auth.uid(); a
 * self-picked ID could be forged, a signed session token can't be.
 */
export async function ensureVisitorSession() {
  const { data: { session } } = await supabase.auth.getSession()
  if (session) return session

  const { data, error } = await supabase.auth.signInAnonymously()
  if (error) throw error
  return data.session
}

/** True if the signed-in user is a recognised admin/agent for this product. */
export async function isCurrentUserAdmin() {
  const { data, error } = await supabase.rpc('is_website_admin')
  if (error) {
    console.error('[supabase-client] is_website_admin check failed', error)
    return false
  }
  return data === true
}

/** Escapes text before it's ever inserted into innerHTML, to stop stored XSS
 *  via chat messages / form fields being rendered back to another viewer. */
export function escapeHtml(str) {
  const div = document.createElement('div')
  div.textContent = String(str ?? '')
  return div.innerHTML
}
