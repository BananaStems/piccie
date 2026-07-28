const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const BOOTH_TOKEN = /^[A-Za-z0-9_-]{40,128}$/;
const OBJECT_KEY = new RegExp(
  `^events/${UUID.source.slice(1, -1)}/(?:manifest\\.json|download-all\\.zip|sessions/${UUID.source.slice(1, -1)}/strip\\.jpg|shares/[0-9a-f]{64}\\.json)$`,
  "i",
);
const PREFIX_KEY = new RegExp(
  `^events/${UUID.source.slice(1, -1)}/(?:sessions/(?:${UUID.source.slice(1, -1)}/)?)?$`,
  "i",
);

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/claim" && request.method === "OPTIONS") {
      return claimPreflight(request);
    }
    if (url.pathname === "/claim" && request.method === "POST") {
      return claimBooth(request, env);
    }
    if (url.pathname.startsWith("/booth/")) {
      return boothRequest(request, env, url);
    }
    if (request.method !== "GET" && request.method !== "HEAD") return response("Not found", 404);
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

function localSetupUrl(value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  if (
    url.protocol !== "http:"
    || url.port !== "8080"
    || url.pathname !== "/setup.html"
    || url.search
    || url.hash
    || url.username
    || url.password
    || !privateHostname(url.hostname)
  ) {
    return null;
  }
  return url;
}

function privateHostname(hostname) {
  const lowered = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  if (lowered === "localhost" || lowered === "::1") return true;
  const match = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(hostname);
  if (match) {
    const octets = match.slice(1).map(Number);
    if (octets.some((part) => part > 255)) return false;
    return (
      octets[0] === 10
      || octets[0] === 127
      || (octets[0] === 169 && octets[1] === 254)
      || (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31)
      || (octets[0] === 192 && octets[1] === 168)
    );
  }
  if (!lowered.includes(":")) return false;
  return /^(fc|fd)/.test(lowered) || /^fe[89ab]/.test(lowered);
}

function claimCors(origin) {
  const headers = new Headers({
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "600",
    "Cache-Control": "private, no-store",
    "Vary": "Origin",
  });
  const parsed = localSetupUrl(`${origin}/setup.html`);
  if (parsed) headers.set("Access-Control-Allow-Origin", origin);
  return headers;
}

function claimPreflight(request) {
  const origin = request.headers.get("Origin") || "";
  const headers = claimCors(origin);
  return new Response(null, { status: headers.has("Access-Control-Allow-Origin") ? 204 : 403, headers });
}

async function claimBooth(request, env) {
  const origin = request.headers.get("Origin") || "";
  const headers = claimCors(origin);
  headers.set("Content-Type", "application/json; charset=utf-8");
  if (!headers.has("Access-Control-Allow-Origin")) {
    return new Response(
      JSON.stringify({ error: "Booth setup must start from a private Piccie setup page." }),
      { status: 403, headers },
    );
  }
  try {
    if (!env.PHOTOS || typeof env.PICCIE_SETUP_KEY !== "string" || env.PICCIE_SETUP_KEY.length < 24) {
      throw new Error("This gallery Worker does not have a valid setup key.");
    }
    const body = await request.json();
    const setupKey = typeof body.setup_key === "string" ? body.setup_key : "";
    const claimId = typeof body.claim_id === "string" ? body.claim_id : "";
    if (!BOOTH_TOKEN.test(claimId) || setupKey.length < 24 || setupKey.length > 256) {
      throw new Error("The Worker URL or setup key is invalid.");
    }
    if (!(await secureEqual(setupKey, env.PICCIE_SETUP_KEY))) {
      return new Response(
        JSON.stringify({ error: "The Worker URL or setup key is invalid." }),
        { status: 401, headers },
      );
    }
    const markerKey = "setup/claimed.json";
    const token = await deriveBoothToken(setupKey, claimId);
    const digest = await sha256Hex(token);
    const existing = await env.PHOTOS.get(markerKey);
    if (existing) {
      const marker = await existing.json().catch(() => ({}));
      if (marker.claim_id !== claimId) {
        return new Response(
          JSON.stringify({
            error: "This setup key has already been used. Rotate the Worker's setup key to connect another booth.",
          }),
          { status: 409, headers },
        );
      }
      await ensureBoothCredential(env, digest);
      return new Response(
        JSON.stringify({ r2: workerConfiguration(new URL(request.url).origin, token) }),
        { headers },
      );
    }

    await ensureBoothCredential(env, digest);
    const claimed = await env.PHOTOS.put(
      markerKey,
      JSON.stringify({
        version: 1,
        claim_id: claimId,
        created_at: new Date().toISOString(),
      }),
      {
        httpMetadata: { contentType: "application/json" },
        onlyIf: new Headers({ "If-None-Match": "*" }),
      },
    );
    if (!claimed) {
      const winner = await env.PHOTOS.get(markerKey);
      const marker = winner ? await winner.json().catch(() => ({})) : {};
      if (marker.claim_id !== claimId) {
        await env.PHOTOS.delete(`booths/${digest}.json`);
        return new Response(
          JSON.stringify({ error: "This setup key was claimed by another booth." }),
          { status: 409, headers },
        );
      }
    }
    return new Response(
      JSON.stringify({ r2: workerConfiguration(new URL(request.url).origin, token) }),
      { headers },
    );
  } catch (error) {
    return new Response(JSON.stringify({ error: safeError(error) }), { status: 400, headers });
  }
}

async function ensureBoothCredential(env, digest) {
  if (await env.PHOTOS.head(`booths/${digest}.json`)) return;
  await env.PHOTOS.put(
    `booths/${digest}.json`,
    JSON.stringify({
      version: 1,
      created_at: new Date().toISOString(),
    }),
    { httpMetadata: { contentType: "application/json" } },
  );
}

function workerConfiguration(requestOrigin, token) {
  return {
    account_id: "",
    access_key: "",
    secret_key: "",
    bucket: "",
    public_base_url: requestOrigin.replace(/\/+$/, ""),
    jurisdiction: "default",
    worker_token: token,
  };
}

async function deriveBoothToken(setupKey, claimId) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(setupKey),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return encodeBase64Url(new Uint8Array(await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(`piccie-booth-v1:${claimId}`),
  )));
}

async function secureEqual(left, right) {
  const [leftDigest, rightDigest] = await Promise.all([
    crypto.subtle.digest("SHA-256", new TextEncoder().encode(left)),
    crypto.subtle.digest("SHA-256", new TextEncoder().encode(right)),
  ]);
  const leftBytes = new Uint8Array(leftDigest);
  const rightBytes = new Uint8Array(rightDigest);
  let difference = 0;
  for (let index = 0; index < leftBytes.length; index += 1) {
    difference |= leftBytes[index] ^ rightBytes[index];
  }
  return difference === 0;
}

async function boothRequest(request, env, url) {
  if (!env.PHOTOS || !(await authorizedBooth(request, env))) {
    return jsonResponse({ error: "This booth upload credential is not valid." }, 401);
  }
  try {
    if (url.pathname === "/booth/health" && request.method === "GET") {
      return jsonResponse({ ok: true });
    }
    if (url.pathname === "/booth/object") {
      const key = validObjectKey(url.searchParams.get("key"));
      if (!key) return jsonResponse({ error: "The object key is not allowed." }, 400);
      if (request.method === "PUT") {
        if (!request.body) return jsonResponse({ error: "The upload body is empty." }, 400);
        await env.PHOTOS.put(key, request.body, {
          httpMetadata: {
            contentType: request.headers.get("Content-Type") || "application/octet-stream",
          },
        });
        return jsonResponse({ ok: true });
      }
      if (request.method === "DELETE") {
        await env.PHOTOS.delete(key);
        return jsonResponse({ ok: true });
      }
    }
    if (url.pathname === "/booth/prefix" && request.method === "DELETE") {
      const prefix = validPrefix(url.searchParams.get("prefix"));
      if (!prefix) return jsonResponse({ error: "The deletion prefix is not allowed." }, 400);
      let deleted = 0;
      while (true) {
        const listed = await env.PHOTOS.list({ prefix, limit: 1000 });
        const keys = listed.objects.map((object) => object.key);
        if (!keys.length) break;
        await env.PHOTOS.delete(keys);
        deleted += keys.length;
      }
      return jsonResponse({ ok: true, deleted });
    }
    if (url.pathname === "/booth/multipart/start" && request.method === "POST") {
      const key = validObjectKey(url.searchParams.get("key"));
      if (!key) return jsonResponse({ error: "The object key is not allowed." }, 400);
      const upload = await env.PHOTOS.createMultipartUpload(key, {
        httpMetadata: {
          contentType: request.headers.get("Content-Type") || "application/octet-stream",
        },
      });
      return jsonResponse({ upload_id: upload.uploadId });
    }
    if (url.pathname === "/booth/multipart/part" && request.method === "PUT") {
      const key = validObjectKey(url.searchParams.get("key"));
      const uploadId = url.searchParams.get("upload_id") || "";
      const part = Number(url.searchParams.get("part"));
      if (!key || !uploadId || !Number.isInteger(part) || part < 1 || part > 10000 || !request.body) {
        return jsonResponse({ error: "The multipart upload request is invalid." }, 400);
      }
      const upload = env.PHOTOS.resumeMultipartUpload(key, uploadId);
      const uploaded = await upload.uploadPart(part, request.body);
      return jsonResponse({ part_number: uploaded.partNumber, etag: uploaded.etag });
    }
    if (url.pathname === "/booth/multipart/complete" && request.method === "POST") {
      const body = await request.json();
      const key = validObjectKey(body.key);
      const uploadId = typeof body.upload_id === "string" ? body.upload_id : "";
      const parts = Array.isArray(body.parts) ? body.parts : [];
      if (
        !key || !uploadId || !parts.length || parts.length > 10000
        || parts.some((part) => (
          !Number.isInteger(part.partNumber) || part.partNumber < 1
          || typeof part.etag !== "string" || !part.etag
        ))
      ) {
        return jsonResponse({ error: "The multipart completion is invalid." }, 400);
      }
      await env.PHOTOS.resumeMultipartUpload(key, uploadId).complete(parts);
      return jsonResponse({ ok: true });
    }
    if (url.pathname === "/booth/multipart" && request.method === "DELETE") {
      const key = validObjectKey(url.searchParams.get("key"));
      const uploadId = url.searchParams.get("upload_id") || "";
      if (!key || !uploadId) {
        return jsonResponse({ error: "The multipart upload request is invalid." }, 400);
      }
      await env.PHOTOS.resumeMultipartUpload(key, uploadId).abort();
      return jsonResponse({ ok: true });
    }
    return jsonResponse({ error: "Not found" }, 404);
  } catch (error) {
    return jsonResponse({ error: safeError(error) }, 500);
  }
}

async function authorizedBooth(request, env) {
  const match = /^Bearer ([A-Za-z0-9_-]+)$/.exec(request.headers.get("Authorization") || "");
  if (!match || !BOOTH_TOKEN.test(match[1])) return false;
  const digest = await sha256Hex(match[1]);
  return Boolean(await env.PHOTOS.head(`booths/${digest}.json`));
}

function validObjectKey(value) {
  return typeof value === "string" && OBJECT_KEY.test(value) ? value : null;
}

function validPrefix(value) {
  return typeof value === "string" && PREFIX_KEY.test(value) ? value : null;
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: securityHeaders("application/json; charset=utf-8"),
  });
}

function safeError(error) {
  const text = error instanceof Error ? error.message : String(error || "");
  return text.slice(0, 300) || "Gallery request failed.";
}

function encodeBase64Url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

async function sha256Hex(value) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

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
