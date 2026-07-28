import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function importBrowserModule(relativePath) {
  const url = new URL(relativePath, import.meta.url);
  const source = await readFile(url, "utf8");
  return import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);
}

const cornerTap = await importBrowserModule("../js/corner-tap.js");
const osk = await importBrowserModule("../js/osk.js");
const onboardingSource = await readFile(new URL("../js/screens/onboarding.js", import.meta.url), "utf8");

test("five-tap party exit never deactivates without operator unlock", async () => {
  const actions = [];
  const exited = await cornerTap.runProtectedCornerExit({
    isParty: true,
    requestUnlock: async () => {
      actions.push("unlock");
      return false;
    },
    deactivateParty: async () => actions.push("deactivate"),
    exitParty: async () => actions.push("exit"),
  });

  assert.equal(exited, false);
  assert.deepEqual(actions, ["unlock"]);
});

test("five-tap party exit unlocks before deactivating and returning", async () => {
  const actions = [];
  const exited = await cornerTap.runProtectedCornerExit({
    isParty: true,
    requestUnlock: async () => {
      actions.push("unlock");
      return true;
    },
    deactivateParty: async () => actions.push("deactivate"),
    exitParty: async () => actions.push("exit"),
  });

  assert.equal(exited, true);
  assert.deepEqual(actions, ["unlock", "deactivate", "exit"]);
});

test("Wi-Fi keyboard fields snap to the visible bottom edge", () => {
  const wifiInput = { classList: { contains: (name) => name === "wifi-password-anchor" } };
  const wifiNameInput = { classList: { contains: () => false } };
  const regularInput = { classList: { contains: () => false } };

  assert.equal(osk.scrollBlockForInput(wifiInput), "end");
  assert.equal(osk.scrollBlockForInput(wifiNameInput), "center");
  assert.equal(osk.scrollBlockForInput(regularInput), "center");
});

test("first-boot setup uses the SD-card R2 file and has no phone pairing flow", () => {
  assert.match(onboardingSource, /piccie-r2\.txt/);
  assert.match(onboardingSource, /r2_configured/);
  assert.doesNotMatch(onboardingSource, /pairOnboarding|onboarding-pair-qr|Continue on your phone/);
});
