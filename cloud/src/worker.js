const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default {
  async fetch(request, env) {
    if (request.method !== "GET" && request.method !== "HEAD") return response("Not found", 404);
    const url = new URL(request.url);
    let parts;
    try {
      parts = url.pathname.split("/").filter(Boolean).map(decodeURIComponent);
    } catch {
      return response("Not found", 404);
    }

    if (parts[0] === "health") return response("OK");
    if (parts[0] === "setup-check" && parts.length === 2) {
      const object = await env.PHOTOS.get(`setup-check/${parts[1]}`);
      return object ? objectResponse(object, request.method === "HEAD") : response("Not found", 404);
    }
    if (parts[0] === "s" && parts.length === 2) return serveStrip(env, parts[1], request);
    if (parts[0] === "g" && parts.length >= 2) return serveGallery(env, parts.slice(1), request);
    return response("Not found", 404);
  },
};

async function serveStrip(env, token, request) {
  const share = await resolveShare(env, token, "strip");
  if (!share) return response("Gallery not found", 404);
  const object = await env.PHOTOS.get(
    `events/${share.event_id}/sessions/${share.session_id}/strip.jpg`,
  );
  if (!object) return response("Gallery not found", 404);
  return objectResponse(object, request.method === "HEAD", `photo-strip-${share.session_id}.jpg`);
}

async function serveGallery(env, parts, request) {
  const [token, action, item] = parts;
  const share = await resolveShare(env, token, "event");
  if (!share) return response("Gallery not found", 404);
  const prefix = `events/${share.event_id}/`;

  if (action === "strip" && UUID.test(item || "")) {
    const object = await env.PHOTOS.get(`${prefix}sessions/${item}/strip.jpg`);
    if (!object) return response("Gallery not found", 404);
    return objectResponse(
      object,
      request.method === "HEAD",
      new URL(request.url).searchParams.has("download") ? `photo-strip-${item}.jpg` : null,
    );
  }
  if (action === "download-all.zip") {
    const object = await env.PHOTOS.get(`${prefix}download-all.zip`);
    if (!object) return response("Download not ready", 404);
    return objectResponse(object, request.method === "HEAD", "photo-strips.zip");
  }
  if (action) return response("Gallery not found", 404);

  const [manifestObject, listed] = await Promise.all([
    env.PHOTOS.get(`${prefix}manifest.json`),
    env.PHOTOS.list({ prefix: `${prefix}sessions/` }),
  ]);
  if (!manifestObject) return response("Gallery not found", 404);
  const manifest = await manifestObject.json();
  const sessions = listed.objects
    .sort((left, right) => new Date(left.uploaded || 0) - new Date(right.uploaded || 0))
    .map((object) => /\/sessions\/([^/]+)\/strip\.jpg$/.exec(object.key)?.[1])
    .filter((id) => id && UUID.test(id));
  return new Response(galleryHtml(manifest, token, sessions), {
    headers: securityHeaders("text/html; charset=utf-8"),
  });
}

async function resolveShare(env, token, expectedKind) {
  const eventId = token.split(".", 1)[0];
  if (!UUID.test(eventId)) return null;
  const object = await env.PHOTOS.get(await shareKey(eventId, token));
  if (!object) return null;
  try {
    const share = await object.json();
    if (share.kind !== expectedKind || share.event_id !== eventId) return null;
    return share;
  } catch {
    return null;
  }
}

export async function shareKey(eventId, token) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token));
  const hex = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  return `events/${eventId}/shares/${hex}.json`;
}

function objectResponse(object, head, filename = null) {
  const headers = securityHeaders(object.httpMetadata?.contentType || "application/octet-stream");
  if (object.httpEtag) headers.set("ETag", object.httpEtag);
  if (filename) headers.set("Content-Disposition", `attachment; filename="${filename}"`);
  return new Response(head ? null : object.body, { headers });
}

function response(body, status = 200) {
  return new Response(body, { status, headers: securityHeaders("text/plain; charset=utf-8") });
}

function securityHeaders(contentType) {
  return new Headers({
    "Content-Type": contentType,
    "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
    "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'",
  });
}

export function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character],
  );
}

function galleryHtml(manifest, token, sessions) {
  const encodedToken = encodeURIComponent(token);
  const cards = sessions.length
    ? sessions.map((session, index) => `
      <article class="strip">
        <img src="/g/${encodedToken}/strip/${session}" alt="Photo strip ${index + 1}" loading="lazy">
        <a href="/g/${encodedToken}/strip/${session}?download">Download strip</a>
      </article>`).join("")
    : '<p class="empty">No strips have finished uploading yet. Refresh this page shortly.</p>';
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${escapeHtml(manifest.name)} photos</title>
<style>
:root{color-scheme:light;--ink:#29231e;--muted:#756c63;--paper:#f5f0e9;--card:#fff;--accent:#df6c3f;--line:#ded5cb}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.45 system-ui,-apple-system,sans-serif}header,main{width:min(100% - 32px,1080px);margin:auto}header{display:flex;align-items:end;justify-content:space-between;gap:24px;padding:52px 0 28px;border-bottom:1px solid var(--line)}h1{margin:0;font-size:clamp(34px,7vw,64px);line-height:.95;letter-spacing:-.05em}header p{margin:8px 0 0;color:var(--muted)}.download-all{flex:none;display:inline-flex;align-items:center;min-height:48px;padding:0 18px;border-radius:12px;background:var(--accent);color:#fff;text-decoration:none;font-weight:700}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:24px;padding:32px 0 56px}.strip{display:grid;gap:12px}.strip img{width:100%;aspect-ratio:1/3;object-fit:contain;background:var(--card);border-radius:14px;padding:10px;box-shadow:0 8px 28px rgba(65,48,36,.08)}.strip a{color:var(--ink);font-weight:650;text-underline-offset:3px}.empty{color:var(--muted)}@media(max-width:560px){header{align-items:start;flex-direction:column;padding-top:32px}.download-all{width:100%;justify-content:center}.grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}}
</style></head><body><header><div><h1>${escapeHtml(manifest.name)}</h1><p>${escapeHtml(manifest.date)} · ${sessions.length} strip${sessions.length === 1 ? "" : "s"}</p></div><a class="download-all" href="/g/${encodedToken}/download-all.zip">Download all</a></header><main class="grid">${cards}</main></body></html>`;
}
