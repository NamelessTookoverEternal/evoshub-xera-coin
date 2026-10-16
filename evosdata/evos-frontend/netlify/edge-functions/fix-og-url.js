// Rewrites the og:url (and og:image, since it's an absolute URL) meta tags
// in the served index.html so they reflect the ACTUAL path being requested,
// instead of the hardcoded "https://evosdata.xyz" baked into index.html.
//
// Why this matters: index.html is one static file shared by every route in
// the SPA (see public/_redirects: "/* /index.html 200"). Link-preview
// crawlers (WhatsApp, Facebook, Telegram, X, etc.) read og:url as the
// canonical link for the card — on some platforms tapping the preview card
// navigates to og:url, not the URL that was actually shared. Without this,
// every shared link (e.g. /store/123) previews and opens as the homepage.
//
// Only touches text/html responses, and skips API/function/asset requests
// so it doesn't add overhead anywhere it isn't needed.

export default async (request, context) => {
  const response = await context.next();

  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("text/html")) {
    return response;
  }

  const url = new URL(request.url);
  const fullUrl = `${url.origin}${url.pathname}`;

  let html = await response.text();

  html = html.replace(
    /<meta\s+property=["']og:url["']\s+content=["'][^"']*["']\s*\/?>/i,
    `<meta property="og:url" content="${fullUrl}" />`
  );

  return new Response(html, {
    status: response.status,
    headers: response.headers,
  });
};

export const config = {
  path: "/*",
  excludedPath: ["/api/*", "/.netlify/*", "/*.{png,jpg,jpeg,svg,ico,css,js,json,xml,txt,woff,woff2}"],
};
