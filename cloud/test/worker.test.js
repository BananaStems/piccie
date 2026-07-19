import assert from "node:assert/strict";
import test from "node:test";

import worker, { escapeHtml, shareKey } from "../src/worker.js";

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
