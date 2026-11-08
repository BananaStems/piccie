import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const js = await readFile(new URL("../js/studio.js", import.meta.url), "utf8");
const css = await readFile(new URL("../css/studio.css", import.meta.url), "utf8");
const html = await readFile(new URL("../studio.html", import.meta.url), "utf8");

test("one tap on an item opens its controls (no hidden double-tap)", () => {
  assert.match(js, /\} else \{\s*selectLayer\(layer\.id\);/);
  assert.doesNotMatch(js, /lastTapAt|doubleTapped/);
});

test("phone panel sits in the layout so the edited item stays visible", () => {
  const phone = css.slice(css.indexOf("@media (max-width: 760px)"));
  assert.match(phone, /\.studio-sheet:not\(\.is-open\) \{ display: none; \}/);
  assert.doesNotMatch(phone.slice(0, phone.indexOf("@keyframes")), /\.studio-sheet \{[^}]*position: fixed/);
  assert.match(js, /function revealSelected\(\)/);
});

test("handles and outlines are counter-scaled to stay finger-sized", () => {
  assert.match(js, /setProperty\("--ui", \(1 \/ scale\)/);
  assert.match(css, /\.layer-resize-handle \{[^}]*width: calc\(34px \* var\(--ui\)\)/s);
});

test("phone photos are shrunk before upload and only used images are sent", () => {
  assert.match(html, /accept="image\/\*"/);
  assert.match(js, /async function prepareImage\(file\)/);
  assert.match(js, /assets: usedAssets\(\)/);
  // Undo history must not copy image data into every step.
  assert.match(js, /JSON\.stringify\(\{ background: state\.background, layers: state\.layers \}\)/);
});

test("expired links and lost Wi-Fi get a clear blocking message", () => {
  assert.match(js, /response\.status === 401\) \{\s*linkExpired\(\);/);
  assert.match(js, /Can't reach the booth/);
});

test("icons are drawn SVG, not text glyphs", () => {
  assert.doesNotMatch(html, /[↶↷＋○◐▱×]/);
});
