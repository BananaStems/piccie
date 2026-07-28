import assert from "node:assert/strict";
import test from "node:test";

import worker, { escapeHtml, shareKey } from "../src/worker.js";

class FakeBucket {
  constructor() {
    this.objects = new Map();
    this.multipart = new Map();
  }

  async put(key, value, options = {}) {
    let bytes;
    if (value instanceof ReadableStream) {
      bytes = Buffer.from(await new Response(value).arrayBuffer());
    } else {
      bytes = Buffer.from(value);
    }
    if (
      options.onlyIf?.get("If-None-Match") === "*"
      && this.objects.has(key)
    ) {
      return null;
    }
    this.objects.set(key, { bytes, httpMetadata: options.httpMetadata || {} });
    return { key };
  }

  async get(key) {
    const value = this.objects.get(key);
    return value === undefined ? null : {
      body: value.bytes,
      httpMetadata: value.httpMetadata,
      json: async () => JSON.parse(value.bytes.toString()),
    };
  }

  async head(key) {
    return this.objects.has(key) ? {} : null;
  }

  async delete(key) {
    for (const item of Array.isArray(key) ? key : [key]) this.objects.delete(item);
  }

  async list({ prefix }) {
    return {
      objects: [...this.objects.keys()]
        .filter((key) => key.startsWith(prefix))
        .map((key) => ({ key })),
    };
  }

  async createMultipartUpload(key) {
    const uploadId = crypto.randomUUID();
    this.multipart.set(`${key}:${uploadId}`, new Map());
    return { uploadId };
  }

  resumeMultipartUpload(key, uploadId) {
    const id = `${key}:${uploadId}`;
    const parts = this.multipart.get(id);
    if (!parts) throw new Error("Multipart upload not found");
    return {
      uploadPart: async (partNumber, value) => {
        const bytes = Buffer.from(await new Response(value).arrayBuffer());
        const etag = `etag-${partNumber}`;
        parts.set(partNumber, { bytes, etag });
        return { partNumber, etag };
      },
      complete: async (uploaded) => {
        this.objects.set(key, {
          bytes: Buffer.concat(uploaded.map(({ partNumber }) => parts.get(partNumber).bytes)),
          httpMetadata: {},
        });
        this.multipart.delete(id);
      },
      abort: async () => {
        this.multipart.delete(id);
      },
    };
  }
}

function base64Url(bytes) {
  return Buffer.from(bytes).toString("base64url");
}

function workerEnv(bucket, setupKey = "setup-key-that-is-at-least-24-characters") {
  return {
    PHOTOS: bucket,
    PICCIE_SETUP_KEY: setupKey,
  };
}

function claimRequest(setupKey, claimId, origin = "http://192.168.1.145:8080") {
  return new Request("https://gallery.example/claim", {
    method: "POST",
    headers: { "Content-Type": "application/json", Origin: origin },
    body: JSON.stringify({ setup_key: setupKey, claim_id: claimId }),
  });
}

async function claim(bucket, setupKey, claimId) {
  return worker.fetch(
    claimRequest(setupKey, claimId),
    workerEnv(bucket, setupKey),
  );
}

test("share records are event-scoped and token-hashed", async () => {
  const event = "11111111-1111-4111-8111-111111111111";
  const key = await shareKey(event, `${event}.secret-token`);
  assert.match(key, new RegExp(`^events/${event}/shares/[0-9a-f]{64}\\.json$`));
  assert.equal(key.includes("secret-token"), false);
});

test("gallery metadata is escaped", () => {
  assert.equal(escapeHtml('<img src=x onerror="bad">'), "&lt;img src=x onerror=&quot;bad&quot;&gt;");
});

test("malformed paths are rejected without touching storage", async () => {
  const response = await worker.fetch(new Request("https://gallery.example/g/%E0%A4%A"), {});
  assert.equal(response.status, 404);
});

test("claim only accepts private Piccie setup origins", async () => {
  const bucket = new FakeBucket();
  const setupKey = "setup-key-that-is-at-least-24-characters";
  const claimId = base64Url(crypto.getRandomValues(new Uint8Array(32)));
  for (const origin of ["https://attacker.example", "http://fcloud.example:8080"]) {
    const response = await worker.fetch(
      claimRequest(setupKey, claimId, origin),
      workerEnv(bucket, setupKey),
    );
    assert.equal(response.status, 403);
    assert.equal(response.headers.get("access-control-allow-origin"), null);
  }
  assert.equal(bucket.objects.size, 0);

  const preflight = await worker.fetch(
    new Request("https://gallery.example/claim", {
      method: "OPTIONS",
      headers: { Origin: "http://192.168.1.145:8080" },
    }),
    workerEnv(bucket, setupKey),
  );
  assert.equal(preflight.status, 204);
  assert.equal(
    preflight.headers.get("access-control-allow-origin"),
    "http://192.168.1.145:8080",
  );
});

test("claim rejects invalid configuration, requests, and setup keys", async () => {
  const bucket = new FakeBucket();
  const setupKey = "setup-key-that-is-at-least-24-characters";
  const claimId = base64Url(crypto.getRandomValues(new Uint8Array(32)));

  const missingBinding = await worker.fetch(claimRequest(setupKey, claimId), {
    PICCIE_SETUP_KEY: setupKey,
  });
  assert.equal(missingBinding.status, 400);

  const shortConfiguredKey = await worker.fetch(claimRequest(setupKey, claimId), {
    PHOTOS: bucket,
    PICCIE_SETUP_KEY: "too-short",
  });
  assert.equal(shortConfiguredKey.status, 400);

  const wrongKey = await worker.fetch(
    claimRequest("a-different-key-that-is-long-enough", claimId),
    workerEnv(bucket, setupKey),
  );
  assert.equal(wrongKey.status, 401);

  const malformedClaim = await worker.fetch(
    claimRequest(setupKey, "not-valid"),
    workerEnv(bucket, setupKey),
  );
  assert.equal(malformedClaim.status, 400);
  assert.equal(bucket.objects.size, 0);
});

test("claim provisions one hashed booth credential and is idempotent", async () => {
  const bucket = new FakeBucket();
  const setupKey = "setup-key-that-is-at-least-24-characters";
  const claimId = base64Url(crypto.getRandomValues(new Uint8Array(32)));

  const first = await claim(bucket, setupKey, claimId);
  assert.equal(first.status, 200);
  assert.equal(first.headers.get("access-control-allow-origin"), "http://192.168.1.145:8080");
  const firstPayload = await first.json();
  assert.equal(firstPayload.r2.public_base_url, "https://gallery.example");
  assert.equal(firstPayload.r2.account_id, "");
  assert.equal(firstPayload.r2.access_key, "");
  assert.equal(firstPayload.r2.secret_key, "");
  assert.equal(firstPayload.r2.bucket, "");
  assert.match(firstPayload.r2.worker_token, /^[A-Za-z0-9_-]{40,}$/);

  const digest = Buffer.from(
    await crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(firstPayload.r2.worker_token),
    ),
  ).toString("hex");
  assert.equal(bucket.objects.has(`booths/${digest}.json`), true);
  assert.equal(
    bucket.objects.get(`booths/${digest}.json`).bytes.includes(firstPayload.r2.worker_token),
    false,
  );
  assert.equal(
    [...bucket.objects.values()].some(({ bytes }) => bytes.includes(setupKey)),
    false,
  );
  assert.equal(
    JSON.parse(bucket.objects.get("setup/claimed.json").bytes).claim_id,
    claimId,
  );

  const objectCount = bucket.objects.size;
  const retry = await claim(bucket, setupKey, claimId);
  assert.equal(retry.status, 200);
  assert.equal((await retry.json()).r2.worker_token, firstPayload.r2.worker_token);
  assert.equal(bucket.objects.size, objectCount);
});

test("a claimed setup key rejects a different booth", async () => {
  const bucket = new FakeBucket();
  const setupKey = "setup-key-that-is-at-least-24-characters";
  const firstId = base64Url(crypto.getRandomValues(new Uint8Array(32)));
  const secondId = base64Url(crypto.getRandomValues(new Uint8Array(32)));
  assert.equal((await claim(bucket, setupKey, firstId)).status, 200);

  const rejected = await claim(bucket, setupKey, secondId);
  assert.equal(rejected.status, 409);
  assert.match((await rejected.json()).error, /already been used/i);
  assert.equal(
    [...bucket.objects.keys()].filter((key) => key.startsWith("booths/")).length,
    1,
  );
});

test("simultaneous claims produce exactly one booth credential", async () => {
  const bucket = new FakeBucket();
  const setupKey = "setup-key-that-is-at-least-24-characters";
  const claimIds = [
    base64Url(crypto.getRandomValues(new Uint8Array(32))),
    base64Url(crypto.getRandomValues(new Uint8Array(32))),
  ];
  const responses = await Promise.all(claimIds.map((claimId) => claim(bucket, setupKey, claimId)));
  assert.deepEqual(responses.map(({ status }) => status).sort(), [200, 409]);
  assert.equal(
    [...bucket.objects.keys()].filter((key) => key.startsWith("booths/")).length,
    1,
  );
});

test("booth credential only allows Piccie event objects", async () => {
  const bucket = new FakeBucket();
  const token = base64Url(crypto.getRandomValues(new Uint8Array(32)));
  const digest = Buffer.from(
    await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token)),
  ).toString("hex");
  await bucket.put(`booths/${digest}.json`, "{}");
  const event = "11111111-1111-4111-8111-111111111111";
  const session = "22222222-2222-4222-8222-222222222222";
  const key = `events/${event}/sessions/${session}/strip.jpg`;
  const authorized = { Authorization: `Bearer ${token}`, "Content-Type": "image/jpeg" };

  const uploaded = await worker.fetch(
    new Request(`https://gallery.example/booth/object?key=${encodeURIComponent(key)}`, {
      method: "PUT",
      headers: authorized,
      body: "jpeg",
    }),
    workerEnv(bucket),
  );
  assert.equal(uploaded.status, 200);
  assert.equal(bucket.objects.get(key).bytes.toString(), "jpeg");

  const forbidden = await worker.fetch(
    new Request("https://gallery.example/booth/object?key=booths%2Fstolen.json", {
      method: "PUT",
      headers: authorized,
      body: "bad",
    }),
    workerEnv(bucket),
  );
  assert.equal(forbidden.status, 400);

  const unauthenticated = await worker.fetch(
    new Request(`https://gallery.example/booth/object?key=${encodeURIComponent(key)}`, {
      method: "DELETE",
    }),
    workerEnv(bucket),
  );
  assert.equal(unauthenticated.status, 401);
});

test("booth multipart upload completes and event prefix deletion is bounded", async () => {
  const bucket = new FakeBucket();
  const token = base64Url(crypto.getRandomValues(new Uint8Array(32)));
  const digest = Buffer.from(
    await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token)),
  ).toString("hex");
  await bucket.put(`booths/${digest}.json`, "{}");
  const event = "11111111-1111-4111-8111-111111111111";
  const key = `events/${event}/download-all.zip`;
  const headers = { Authorization: `Bearer ${token}` };

  const started = await worker.fetch(
    new Request(`https://gallery.example/booth/multipart/start?key=${encodeURIComponent(key)}`, {
      method: "POST",
      headers,
    }),
    workerEnv(bucket),
  );
  const uploadId = (await started.json()).upload_id;
  const uploadedParts = [];
  for (const [part, body] of [[1, "first"], [2, "second"]]) {
    const response = await worker.fetch(
      new Request(
        `https://gallery.example/booth/multipart/part?key=${encodeURIComponent(key)}&upload_id=${uploadId}&part=${part}`,
        { method: "PUT", headers, body },
      ),
      workerEnv(bucket),
    );
    const result = await response.json();
    uploadedParts.push({ partNumber: part, etag: result.etag });
  }
  const completed = await worker.fetch(
    new Request("https://gallery.example/booth/multipart/complete", {
      method: "POST",
      headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify({ key, upload_id: uploadId, parts: uploadedParts }),
    }),
    workerEnv(bucket),
  );
  assert.equal(completed.status, 200);
  assert.equal(bucket.objects.get(key).bytes.toString(), "firstsecond");

  const deleted = await worker.fetch(
    new Request(
      `https://gallery.example/booth/prefix?prefix=${encodeURIComponent(`events/${event}/`)}`,
      { method: "DELETE", headers },
    ),
    workerEnv(bucket),
  );
  assert.equal(deleted.status, 200);
  assert.equal(bucket.objects.has(key), false);
  assert.equal(bucket.objects.has(`booths/${digest}.json`), true);
});
