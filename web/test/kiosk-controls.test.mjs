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
const appSource = await readFile(new URL("../js/app.js", import.meta.url), "utf8");
const apiSource = await readFile(new URL("../js/api.js", import.meta.url), "utf8");
const adminSource = await readFile(new URL("../js/screens/admin.js", import.meta.url), "utf8");
const onboardingSource = await readFile(new URL("../js/screens/onboarding.js", import.meta.url), "utf8");
const settings = await importBrowserModule("../js/screens/settings.js");
const settingsSource = await readFile(new URL("../js/screens/settings.js", import.meta.url), "utf8");
const wifiSource = await readFile(new URL("../js/screens/wifi.js", import.meta.url), "utf8");
const cssSource = await readFile(new URL("../css/app.css", import.meta.url), "utf8");

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

test("operator PIN uses a digits-only keypad and strips physical non-digits", () => {
  const pinInput = {
    dataset: { oskLayout: "pin" },
    type: "text",
    inputMode: "numeric",
    classList: { contains: () => false },
  };
  const keys = osk.rowsForLayout(osk.layoutForInput(pinInput)).flat();

  assert.deepEqual(keys, [
    "1", "2", "3",
    "4", "5", "6",
    "7", "8", "9",
    "backspace", "0", "done",
  ]);
  assert.equal(osk.normalizePinValue("12a-34 56"), "1234");
});

test("operator unlock is a compact masked four-digit numpad", () => {
  assert.match(appSource, /class="operator-pin-panel"[^>]+data-operator-pin-form/);
  assert.match(appSource, /data-operator-pin-display/);
  assert.match(appSource, /slot\.textContent = index < code\.length \? "\*" : ""/);
  assert.match(appSource, /data-operator-unlock[^>]+disabled/);
  assert.match(appSource, /unlock\.disabled = busy \|\| code\.length !== 4/);
  assert.match(appSource, /data-operator-backspace/);
  assert.match(cssSource, /\.operator-pin-panel\s*\{[^}]*width:\s*min\(320px,/s);
  assert.match(cssSource, /\.operator-pin-grid\s*\{[^}]*grid-template-columns:\s*repeat\(3,/s);
});

test("kiosk secrets are masked without native password fields", () => {
  const kioskSource = `${appSource}\n${onboardingSource}\n${wifiSource}`;

  assert.doesNotMatch(kioskSource, /type=["']password["']/);
  assert.match(onboardingSource, /name="operator_code"[^>]+data-osk-layout="pin"/);
  assert.match(appSource, /data-operator-pin-form/);
  assert.match(cssSource, /\.pin-input\s*\{[^}]*letter-spacing:/s);
  assert.match(cssSource, /\.masked-secret,\s*\.pin-input\s*\{[^}]*-webkit-text-security:\s*disc/s);
});

test("first-boot setup uses the SD-card R2 file and has no phone pairing flow", () => {
  assert.match(onboardingSource, /piccie-r2\.txt/);
  assert.match(onboardingSource, /r2_configured/);
  assert.doesNotMatch(onboardingSource, /pairOnboarding|onboarding-pair-qr|Continue on your phone/);
});

test("finishing setup opens the menu without a lockdown reboot", () => {
  assert.match(onboardingSource, /await api\.completeOnboarding[\s\S]+window\.location\.reload\(\)/);
  assert.doesNotMatch(onboardingSource, /Securing your booth|Restarting…|onboardingRestartPolling/);
});

test("performance restart must go offline before it is considered complete", async () => {
  const statuses = ["online", "online", "offline", "offline", "online"];
  let checks = 0;

  await settings.waitForRestartCycle({
    checkStatus: async () => {
      const status = statuses[checks];
      checks += 1;
      if (status === "offline") throw new Error("offline");
    },
    wait: async () => {},
  });

  assert.equal(checks, 5);
});

test("performance restart reports when no restart begins", async () => {
  await assert.rejects(
    settings.waitForRestartCycle({
      checkStatus: async () => {},
      wait: async () => {},
      startChecks: 2,
    }),
    /did not begin restarting/,
  );
});

test("settings preview is paced by fresh backend frames at the appliance rate", () => {
  assert.match(settingsSource, /setTimeout\(poll, 20\)/);
  assert.doesNotMatch(settingsSource, /setTimeout\(poll, 160\)/);
});

test("settings expose editable PIN and SSH access without password fields", () => {
  assert.match(settingsSource, /Operator access/);
  assert.match(settingsSource, /id="new-operator-pin"[^>]+data-osk-layout="pin"/);
  assert.match(settingsSource, /id="confirm-operator-pin"[^>]+data-osk-layout="pin"/);
  assert.match(settingsSource, /id="ssh-authorized-key"/);
  assert.match(settingsSource, /api\.updateOperatorPin/);
  assert.match(settingsSource, /api\.updateSshAuthorizedKey/);
  assert.match(settingsSource, /id="new-operator-pin"[^>]+maxlength="4"/);
  assert.match(settingsSource, /Use exactly 4 digits/);
  assert.doesNotMatch(settingsSource, /type=["']password["']/);
});

test("capture thumbnails use the selected filter and result QR stays compact", () => {
  assert.match(appSource, /photoUrl\(state\.sessionId, i\)\}\?filtered=true&t=/);
  assert.match(cssSource, /\.qr-panel \.qr-code\s*\{[^}]*width:\s*200px;[^}]*height:\s*200px;/s);
  assert.match(appSource, /session\.guest_qr_url \|\| session\.r2_strip_url/);
  assert.match(appSource, /setInterval\(check, 1000\)/);
});

test("event gallery exposes confirmed per-strip deletion", () => {
  assert.match(adminSource, /class="gallery-thumb-row"/);
  assert.match(adminSource, /data-delete-session=/);
  assert.match(adminSource, /showConfirm\(\{/);
  assert.match(adminSource, /api\.deleteSession\(sessionId\)/);
  assert.match(apiSource, /deleteSession:[\s\S]+method: "DELETE"/);
  assert.match(cssSource, /\.gallery-thumb-row\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\) auto;/s);
});

test("event share allows large strip and original-photo archives", () => {
  assert.match(apiSource, /createEventShare:[\s\S]+timeoutMs: 900000/);
  assert.match(adminSource, /download every strip and original photo/);
});
