import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

// The guest page is one self-contained HTML file; its last <script> holds the print and save logic.
const html = await readFile(new URL("../../engine/guest_page.html", import.meta.url), "utf8");
const script = html.slice(html.lastIndexOf("<script>") + "<script>".length, html.lastIndexOf("</script>"));

function element(extra = {}) {
  const classes = new Set();
  return {
    hidden: false,
    inert: false,
    textContent: "",
    offsetHeight: 142,
    classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
    },
    style: { setProperty() {} },
    addEventListener() {},
    getBoundingClientRect: () => ({ top: 0, height: 10, width: 100 }),
    querySelector: () => element(),
    ...extra,
  };
}

// Runs the page script in a bare browser stand-in with no Web Animations support.
async function openPage(strip) {
  const root = element();
  root.classList.add("printing");
  const byId = {
    strip,
    status: element(),
    "download-strip": element(),
    retry: element({ hidden: true }),
    "save-note": element({ hidden: true }),
    "save-label": element(),
  };
  vm.runInNewContext(script, {
    document: { documentElement: root, getElementById: (id) => byId[id], querySelector: () => element() },
    localStorage: { getItem() {}, setItem() {} },
    location: { pathname: "/strip", reload() {} },
    navigator: { userAgent: "test", platform: "test", maxTouchPoints: 0 },
    setTimeout: () => 0,
  });
  await new Promise((resolve) => setImmediate(resolve));
  return { root, ...byId };
}

test("a browser without Web Animations still shows the strip and the save button", async () => {
  const page = await openPage(element({ complete: true, naturalWidth: 600 }));

  assert.equal(page.root.classList.contains("printing"), false);
  assert.equal(page["download-strip"].inert, false);
  assert.equal(page["download-strip"].hidden, false);
  assert.equal(page.status.hidden, true);
});

test("a strip that failed before the script ran shows the error and Try again", async () => {
  const page = await openPage(element({ complete: true, naturalWidth: 0 }));

  assert.equal(page.status.classList.contains("error"), true);
  assert.match(page.status.textContent, /didn’t load/);
  assert.equal(page.retry.hidden, false);
  assert.equal(page["download-strip"].hidden, true);
});
