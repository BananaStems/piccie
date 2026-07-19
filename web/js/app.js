import { api } from "./api.js";
import {
  attachCaptureRing,
  detachCaptureRing,
  startRingCountdown,
  stopRingCountdown,
} from "./capture-ring.js";
import { initCornerTap, setCornerHandler } from "./corner-tap.js";
import { closeOnScreenKeyboard, initOnScreenKeyboard } from "./osk.js";
import { renderAdminScreen, renderGalleryScreen } from "./screens/admin.js";
import {
  defaultTemplateIndex,
  isoToDisplay,
  renderEditorScreen,
  templateIndexForId,
} from "./screens/editor.js";
import { renderSettingsScreen } from "./screens/settings.js";
import { renderTemplatesScreen } from "./screens/templates.js";
import { renderWifiScreen } from "./screens/wifi.js";
import { renderOnboardingScreen } from "./screens/onboarding.js";

const app = document.getElementById("app");
const WIFI_OFFLINE_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M4.5 12a11 11 0 0 1 15 0"/><path d="M8 15.5a6 6 0 0 1 8 0"/><path d="M12 19h.01"/><path d="m4 4 16 16"/></svg>';

const state = {
  view: "loading",
  status: null,
  events: [],
  templates: [],
  templateView: "active",
  wifiNetworks: [],
  wifiSelected: null,
  wifiReturnView: null,
  onboardingStep: "wifi",
  onboardingR2: null,
  editingEvent: null,
  galleryEvent: null,
  gallerySessions: [],
  selectedGallerySession: null,
  templateIndex: 0,
  activeEvent: null,
  partyState: "idle",
  sessionId: null,
  photoIndex: 0,
  activeTemplate: null,
  captureShellMounted: false,
  resultTimer: 120,
  resultInterval: null,
  pollInterval: null,
  qrUrl: null,
  stripUrl: null,
  resultOffline: false,
  templateColors: {},
  cameraSettings: null,
};

function photoCountdownSeconds(photoIndex) {
  return photoIndex === 1 ? 8 : 5;
}

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function escapeHtml(value) {
  return String(value).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]),
  );
}

function showConfirm({ title, message, confirmLabel = "Confirm", cancelLabel = "Cancel", danger = false }) {
  return new Promise((resolve) => {
    const frame = document.getElementById("booth-frame");
    const overlay = document.createElement("div");
    overlay.className = "confirm-overlay";

    const panel = document.createElement("div");
    panel.className = "confirm-panel";
    panel.setAttribute("role", "alertdialog");
    panel.setAttribute("aria-modal", "true");

    const titleEl = document.createElement("h2");
    titleEl.className = "confirm-title";
    titleEl.textContent = title;

    const messageEl = document.createElement("p");
    messageEl.className = "confirm-message";
    messageEl.textContent = message;

    const actions = document.createElement("div");
    actions.className = "confirm-actions";

    const cancelBtn = document.createElement("button");
    cancelBtn.className = "btn btn-secondary";
    cancelBtn.type = "button";
    cancelBtn.textContent = cancelLabel;

    const confirmBtn = document.createElement("button");
    confirmBtn.className = danger ? "btn btn-danger" : "btn";
    confirmBtn.type = "button";
    confirmBtn.textContent = confirmLabel;

    const cleanup = (result) => {
      overlay.remove();
      resolve(result);
    };

    cancelBtn.onclick = () => cleanup(false);
    confirmBtn.onclick = () => cleanup(true);
    overlay.onclick = (e) => {
      if (e.target === overlay) cleanup(false);
    };

    actions.append(cancelBtn, confirmBtn);
    panel.append(titleEl, messageEl, actions);
    overlay.append(panel);
    frame.appendChild(overlay);
    cancelBtn.focus();
  });
}

// cancelled. The input focuses on open, which raises the on-screen keyboard.
function promptText({ title, value = "", placeholder = "", confirmLabel = "Save", cancelLabel = "Cancel", required = true, maxLength = 80, type = "text", inputMode = "text" }) {
  return new Promise((resolve) => {
    const frame = document.getElementById("booth-frame");
    const overlay = document.createElement("div");
    overlay.className = "confirm-overlay prompt-overlay";

    const panel = document.createElement("div");
    panel.className = "confirm-panel prompt-panel";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "true");

    const titleEl = document.createElement("h2");
    titleEl.className = "confirm-title";
    titleEl.textContent = title;

    const input = document.createElement("input");
    input.className = "prompt-input";
    input.type = type;
    input.inputMode = inputMode;
    input.value = value;
    input.placeholder = placeholder;
    input.maxLength = maxLength;
    input.setAttribute("autocomplete", "off");

    const actions = document.createElement("div");
    actions.className = "confirm-actions";

    const cancelBtn = document.createElement("button");
    cancelBtn.className = "btn btn-secondary";
    cancelBtn.type = "button";
    cancelBtn.textContent = cancelLabel;

    const confirmBtn = document.createElement("button");
    confirmBtn.className = "btn";
    confirmBtn.type = "button";
    confirmBtn.textContent = confirmLabel;

    const cleanup = (result) => {
      closeOnScreenKeyboard();
      overlay.remove();
      resolve(result);
    };
    const submit = () => {
      const v = input.value.trim();
      if (required && !v) {
        input.focus();
        return;
      }
      cleanup(v);
    };

    cancelBtn.onclick = () => cleanup(null);
    confirmBtn.onclick = submit;
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        submit();
      }
    });
    overlay.onclick = (e) => {
      // Only let a backdrop tap dismiss when nothing's been typed — otherwise a
      // stray tap on a touch panel would silently discard the entered name.
      if (e.target === overlay && !input.value.trim()) cleanup(null);
    };

    actions.append(cancelBtn, confirmBtn);
    panel.append(titleEl, input, actions);
    overlay.append(panel);
    frame.appendChild(overlay);
    input.focus();
  });
}

let previewStreamUrl = null;

function buildCameraPreviewUrl(template = getActiveTemplate()) {
  const pw = template.photo_width || 600;
  const ph = template.photo_height || 400;
  return `${api.cameraPreviewUrl(pw, ph)}&t=${Date.now()}`;
}

// Pause/resume only HIDE the live <img>; the MJPEG connection stays open so resume
// is instant (no multipart re-handshake / black flash). The stream is torn down
// once at teardownCaptureShell. The flash overlay covers the hidden frame.
function pauseLivePreview() {
  document.getElementById("live-preview")?.classList.add("is-paused");
}

function resumeLivePreview() {
  document.getElementById("live-preview")?.classList.remove("is-paused");
}

function captureWithFlash(sessionId, photoIndex) {
  pauseLivePreview();
  const flash = document.getElementById("flash-overlay");
  const capturePromise = api.capture(sessionId, photoIndex);
  flash?.classList.add("is-active");
  return capturePromise.finally(() => {
    flash?.classList.remove("is-active");
    resumeLivePreview();
  });
}

function formatResultCountdown(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function returnToPartyIdle() {
  clearTimers();
  state.partyState = "idle";
  state.sessionId = null;
  state.qrUrl = null;
  state.stripUrl = null;
  state.resultOffline = false;
  renderParty();
}

function applyTemplateTheme(colors = {}) {
  const root = document.documentElement;
  root.style.setProperty("--party-bg", colors.idle_background || "#f2ebe3");
  root.style.setProperty("--party-text", colors.idle_text || "#2d2926");
  root.style.setProperty("--party-sub", colors.idle_subtext || "#7a7268");
  root.style.setProperty("--party-accent", colors.accent || "#c45c4a");
  state.templateColors = colors;
}

function clearPartyTheme() {
  const root = document.documentElement;
  root.style.removeProperty("--party-bg");
  root.style.removeProperty("--party-text");
  root.style.removeProperty("--party-sub");
  root.style.removeProperty("--party-accent");
}

function teardownCaptureShell() {
  detachCaptureRing();
  state.captureShellMounted = false;
  previewStreamUrl = null;
  document.getElementById("booth-frame")?.classList.remove("capture-active");
  document.getElementById("live-preview")?.removeAttribute("src");
  const flying = document.getElementById("flying-thumb");
  if (flying) flying.remove();
  const shell = document.getElementById("capture-shell");
  if (shell) shell.remove();
}

function clearTimers() {
  stopRingCountdown();
  if (state.resultInterval) clearInterval(state.resultInterval);
  if (state.pollInterval) clearInterval(state.pollInterval);
  state.resultInterval = null;
  state.pollInterval = null;
}

function getActiveTemplate() {
  const event = state.activeEvent;
  if (!event) {
    return { photo_width: 600, photo_height: 400, strip_width: 600, strip_height: 1800 };
  }
  return (
    state.activeTemplate ||
    state.templates.find((t) => t.id === event.template_id) || {
      photo_width: 600,
      photo_height: 400,
      strip_width: 600,
      strip_height: 1800,
    }
  );
}

async function bootstrap() {
  initOnScreenKeyboard();
  initCornerTap(handleCornerTap);
  // The kiosk Chromium races the engine service at power-on; a single failed
  // status() would otherwise leave #app blank forever. Show a spinner and retry
  // with backoff until the engine answers (it has Restart=always, so it will).
  app.innerHTML = `<div class="screen centered"><div class="spinner"></div></div>`;
  state.status = await fetchStatusWithRetry();
  if (state.status.onboarding_required) {
    state.view = "onboarding";
    render();
    return;
  }
  await loadAdminData();
  const activeEvent = state.events.find((event) => event.id === state.status.active_event_id);
  if (activeEvent) {
    await enterParty(activeEvent, { persist: false });
    return;
  }
  state.view = state.status.admin_pin_set ? "locked" : "admin";
  render();
}

async function fetchStatusWithRetry() {
  let backoff = 500;
  for (;;) {
    try {
      return await api.status();
    } catch (e) {
      await delay(backoff);
      backoff = Math.min(backoff * 1.5, 3000);
    }
  }
}

async function loadAdminData() {
  try {
    state.events = await api.listEvents();
    state.templates = await api.listTemplates();
  } catch (error) {
    console.error(error);
  }
}

async function requestOperatorUnlock() {
  let title = "Operator PIN";
  for (;;) {
    const pin = await promptText({
      title,
      confirmLabel: "Unlock",
      type: "password",
      inputMode: "numeric",
      maxLength: 8,
    });
    if (!pin) return false;
    try {
      await api.unlockAdmin(pin);
      return true;
    } catch {
      title = "Incorrect PIN";
    }
  }
}

async function handleCornerTap() {
  if (state.view.startsWith("party")) {
    if (state.status.admin_pin_set && !(await requestOperatorUnlock())) return;
    await api.setActiveEvent(null);
    state.status.active_event_id = null;
    await exitParty();
  }
}

function renderAdminLock() {
  app.innerHTML = `
    <div class="screen centered">
      <form class="confirm-panel prompt-panel" id="admin-unlock-form">
        <h2 class="confirm-title">Operator PIN</h2>
        <input class="prompt-input" id="admin-pin" type="password" inputmode="numeric"
          maxlength="8" autocomplete="off" aria-label="Operator PIN" />
        <p class="form-error" id="admin-pin-error" role="alert"></p>
        <button class="btn" type="submit">Unlock</button>
      </form>
    </div>`;
  const form = document.getElementById("admin-unlock-form");
  const input = document.getElementById("admin-pin");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api.unlockAdmin(input.value.trim());
      // An event may have been removed outside the UI while it was persisted.
      if (state.status.active_event_id) await api.setActiveEvent(null);
      state.status.active_event_id = null;
      state.view = "admin";
      render();
    } catch (error) {
      document.getElementById("admin-pin-error").textContent = error.message;
      input.value = "";
      input.focus();
    }
  });
  input.focus();
}

async function exitParty() {
  teardownCaptureShell();
  clearTimers();
  state.activeEvent = null;
  state.activeTemplate = null;
  state.partyState = "idle";
  state.view = "admin";
  clearPartyTheme();
  setCornerHandler(handleCornerTap);
  await loadAdminData();
  render();
}

function render() {
  closeOnScreenKeyboard();
  clearTimers();
  document.getElementById("booth-frame")?.classList.toggle("party-mode", state.view === "party");
  switch (state.view) {
    case "admin":
      renderAdminScreen({
        app,
        state,
        render,
        api,
        escapeHtml,
        formatDate: isoToDisplay,
        promptText,
        defaultTemplateIndex: () => defaultTemplateIndex(state),
        templateIndexForId: (templateId) => templateIndexForId(state, templateId),
        enterParty,
      });
      startAdminStatusPolling();
      break;
    case "locked":
      renderAdminLock();
      break;
    case "onboarding":
      renderOnboardingScreen({
        app,
        state,
        render,
        api,
        escapeHtml,
        loadAdminData,
        closeOnScreenKeyboard,
      });
      break;
    case "wifi":
      renderWifiScreen({ app, state, api, escapeHtml, closeOnScreenKeyboard, returnFromWifi });
      break;
    case "settings":
      renderSettingsScreen({ app, state, render, api, escapeHtml, showConfirm });
      break;
    case "templates":
      renderTemplatesScreen({ app, state, render, api, escapeHtml, showConfirm });
      break;
    case "edit-event":
      renderEditorScreen({ app, state, render, escapeHtml, promptText, showConfirm });
      break;
    case "gallery":
      renderGalleryScreen({ app, state, render, api, escapeHtml });
      break;
    case "party":
      renderParty();
      break;
    default:
      app.innerHTML = `<div class="screen centered"><div class="spinner"></div></div>`;
  }
}

function returnFromWifi() {
  const returnView = state.wifiReturnView || "admin";
  const returningToResult = returnView === "party" && state.partyState === "result";
  state.wifiReturnView = null;
  state.view = returnView;
  if (returningToResult) state.resultOffline = !state.status?.wifi_ssid;
  render();
  if (returningToResult) {
    startResultTimer();
    if (!state.qrUrl) pollUpload();
  }
}

function startAdminStatusPolling() {
  state.pollInterval = setInterval(async () => {
    if (state.view !== "admin") return;
    const latest = await api.status().catch(() => null);
    if (!latest) return;
    const connectionChanged = latest.wifi_ssid !== state.status?.wifi_ssid;
    state.status = latest;
    if (connectionChanged) render();
  }, 5000);
}

async function enterParty(event, { persist = true } = {}) {
  if (persist) {
    state.status = await api.status();
    if (!state.status.wifi_ssid) {
      const connectNow = await showConfirm({
        title: "No Wi-Fi connection",
        message: "Photos will stay on this booth, but uploads and guest downloads will wait until Wi-Fi returns.",
        confirmLabel: "Connect to Wi-Fi",
        cancelLabel: "Launch offline",
      });
      if (connectNow) {
        state.view = "wifi";
        render();
        return;
      }
    }
    await api.setActiveEvent(event.id);
    state.status.active_event_id = event.id;
  }
  const template =
    state.templates.find((t) => t.id === event.template_id) ||
    (await api.listTemplates()).find((t) => t.id === event.template_id);
  applyTemplateTheme(template?.colors || {});
  state.activeEvent = event;
  state.activeTemplate = template || null;
  state.partyState = "idle";
  state.view = "party";
  setCornerHandler(handleCornerTap);
  render();
}

let idleMotionTimer = null;

// Pause the idle pulse after 60s of no interaction so an unattended booth isn't
// compositing an animation on the GPU around the clock. Any tap on the idle
// screen starts a session and re-renders, which reschedules this.
function scheduleIdleMotionPause() {
  if (idleMotionTimer) clearTimeout(idleMotionTimer);
  idleMotionTimer = setTimeout(() => {
    document.querySelector(".party-idle")?.classList.add("motion-idle");
  }, 60000);
}

function renderParty() {
  const event = state.activeEvent;
  if (idleMotionTimer) {
    clearTimeout(idleMotionTimer);
    idleMotionTimer = null;
  }

  if (state.partyState === "idle") {
    const tagMeta = [isoToDisplay(event.date), event.line2].filter(Boolean).join(" · ");
    app.innerHTML = `
      <div class="screen party-idle" id="party-tap">
        <div class="party-center">
          <div class="tap-ring"><div class="tap-ring-inner"></div></div>
          <h2>Tap to start</h2>
        </div>
        <div class="party-tag">
          <p class="party-tag-name">${escapeHtml(event.line1 || event.name || "")}</p>
          ${tagMeta ? `<p class="party-tag-meta">${escapeHtml(tagMeta)}</p>` : ""}
        </div>
      </div>`;
    document.getElementById("party-tap").onclick = startSession;
    scheduleIdleMotionPause();
    return;
  }

  if (state.partyState === "capturing") {
    return;
  }

  if (state.partyState === "composing") {
    app.innerHTML = `
      <div class="screen centered composing-panel">
        <div class="spinner"></div>
        <h2>Creating strip</h2>
      </div>`;
    return;
  }

  if (state.partyState === "result") {
    const showQr = state.qrUrl;
    const stripSrc = state.stripUrl || "";
    const tpl = getActiveTemplate();
    const stripAspect = `${tpl.strip_width || 600} / ${tpl.strip_height || 1800}`;
    app.innerHTML = `
      <div class="screen result-screen">
        <div class="result-layout">
          <div class="strip-panel" style="aspect-ratio: ${stripAspect}">
            ${stripSrc ? `<img class="strip-preview" src="${stripSrc}" alt="Your photo strip" />` : `<div class="spinner"></div>`}
          </div>
          <div class="qr-panel">
            <div class="qr-main">
              ${showQr
                ? `<img class="qr-code" src="/api/qr?data=${encodeURIComponent(state.qrUrl)}" alt="QR code to download photos" /><p class="subtitle">Scan to download</p>`
                : state.resultOffline
                  ? `<div class="result-offline" role="status">
                      <span class="result-offline-icon" aria-hidden="true">${WIFI_OFFLINE_ICON}</span>
                      <h2>We've lost the network connection</h2>
                      <p>Don't worry. The event organiser can send you your photos later.</p>
                    </div>`
                  : `<div class="spinner"></div><p class="subtitle">Uploading</p>`}
              ${state.resultOffline ? `<button class="result-reconnect" type="button" id="result-reconnect">Try reconnect</button>` : ""}
              <p id="result-timer" class="result-timer">${formatResultCountdown(state.resultTimer)}</p>
            </div>
            <button class="btn btn-large result-new-session" type="button" id="new-session-btn">Take another</button>
          </div>
        </div>
      </div>`;
    document.getElementById("new-session-btn").onclick = returnToPartyIdle;
    document.getElementById("result-reconnect")?.addEventListener("click", () => {
      state.wifiReturnView = "party";
      state.view = "wifi";
      render();
    });
  }
}

function mountCaptureShell(template) {
  const pw = template.photo_width || 600;
  const ph = template.photo_height || 400;
  const aspect = `${pw} / ${ph}`;

  app.innerHTML = `
    <div class="screen capture-shell" id="capture-shell">
      <div class="capture-layout">
        <div class="capture-preview-col">
          <div class="preview-chrome" id="preview-frame">
            <div class="preview-media" style="aspect-ratio: ${aspect}">
              <img id="live-preview" class="preview-image" alt="" />
              <svg class="preview-ring" id="preview-ring" aria-hidden="true">
                <path class="ring-track" id="ring-track" fill="none" />
                <path class="ring-progress" id="ring-progress" fill="none" />
              </svg>
            </div>
            <div class="capture-error" id="capture-error" hidden></div>
          </div>
        </div>
        <div class="capture-strip-col">
          <div class="side-strip" id="side-strip">
            <div class="side-slot" data-slot="1" style="aspect-ratio: ${aspect}">
              <span class="slot-countdown" aria-hidden="true"></span>
            </div>
            <div class="side-slot" data-slot="2" style="aspect-ratio: ${aspect}">
              <span class="slot-countdown" aria-hidden="true"></span>
            </div>
            <div class="side-slot" data-slot="3" style="aspect-ratio: ${aspect}">
              <span class="slot-countdown" aria-hidden="true"></span>
            </div>
          </div>
        </div>
      </div>
    </div>
    <img class="flying-thumb" id="flying-thumb" hidden alt="" />`;

  state.captureShellMounted = true;
  state.partyState = "capturing";
  document.getElementById("booth-frame")?.classList.add("capture-active");
  previewStreamUrl = buildCameraPreviewUrl(template);
  previewReloadAttempts = 0;
  const preview = document.getElementById("live-preview");
  if (preview) {
    preview.src = previewStreamUrl;
    preview.addEventListener("error", onPreviewError, { once: true });
  }
  const frame = document.getElementById("preview-frame");
  if (frame) attachCaptureRing(frame);
}

let previewReloadAttempts = 0;

// A dropped MJPEG stream (backend restart, camera stall — both seen on this Pi)
// must NOT be routed through showCaptureError: that stops the ring countdown,
// which rejects the sequence's pending promise with AbortError, and the sequence
// treats AbortError as an intentional exit — leaving the "Try again" button
// wired to nothing and the capture screen frozen until a reboot. Instead: retry
// the stream silently a couple of times (captures use a separate still path, so
// a brief preview gap is harmless), then fall back to a guaranteed exit to idle.
function onPreviewError() {
  if (!state.captureShellMounted) return;
  if (previewReloadAttempts < 2) {
    previewReloadAttempts += 1;
    setTimeout(() => {
      const p = document.getElementById("live-preview");
      if (!p || !state.captureShellMounted || !previewStreamUrl) return;
      const sep = previewStreamUrl.includes("?") ? "&" : "?";
      p.addEventListener("error", onPreviewError, { once: true });
      p.src = `${previewStreamUrl}${sep}r=${Date.now()}`;
    }, 1500);
    return;
  }
  const el = document.getElementById("capture-error");
  if (!el) {
    returnToPartyIdle();
    return;
  }
  el.hidden = false;
  el.innerHTML =
    `<p>Camera preview lost. Check the camera and restart the booth.</p>` +
    `<button class="btn" type="button" id="preview-back">Back to start</button>`;
  const back = document.getElementById("preview-back");
  if (back) back.onclick = () => returnToPartyIdle();
}

function waitRingCountdown(seconds, slotIndex, onShutter) {
  return startRingCountdown(seconds, slotIndex, onShutter);
}

function setActiveSlot(index) {
  document.querySelectorAll(".side-slot").forEach((slot) => {
    const n = Number(slot.dataset.slot);
    slot.classList.toggle("is-active", n === index);
    if (n !== index) {
      const countdown = slot.querySelector(".slot-countdown");
      if (countdown) countdown.textContent = "";
    }
  });
}

function updateSideStrip(index, url) {
  const slot = document.querySelector(`.side-slot[data-slot="${index}"]`);
  if (!slot) return;
  slot.innerHTML = `<img src="${url}" alt="Photo ${index}" />`;
  slot.classList.add("is-filled");
  slot.classList.remove("is-active");
}

async function animateThumbnailToSlot(index, imageUrl) {
  const frame = document.querySelector(".preview-media") || document.getElementById("preview-frame");
  const slot = document.querySelector(`.side-slot[data-slot="${index}"]`);
  const flying = document.getElementById("flying-thumb");
  if (!frame || !slot || !flying) {
    updateSideStrip(index, imageUrl);
    return;
  }

  // The flying thumb renders over the still-running live preview — no pause needed.
  const frameRect = frame.getBoundingClientRect();
  const slotRect = slot.getBoundingClientRect();

  flying.src = imageUrl;
  flying.hidden = false;
  flying.style.transition = "none";
  flying.style.width = `${frameRect.width}px`;
  flying.style.height = `${frameRect.height}px`;
  flying.style.left = `${frameRect.left}px`;
  flying.style.top = `${frameRect.top}px`;
  flying.style.transform = "translate(0, 0) scale(1)";
  flying.style.opacity = "1";

  void flying.offsetWidth;

  const scaleX = slotRect.width / frameRect.width;
  const scaleY = slotRect.height / frameRect.height;
  const dx = slotRect.left + slotRect.width / 2 - (frameRect.left + frameRect.width / 2);
  const dy = slotRect.top + slotRect.height / 2 - (frameRect.top + frameRect.height / 2);

  flying.style.transition = "transform 400ms cubic-bezier(0.4, 0, 0.2, 1), opacity 400ms ease";
  flying.style.transform = `translate(${dx}px, ${dy}px) scale(${scaleX}, ${scaleY})`;
  flying.style.opacity = "0.88";

  await delay(420);

  flying.hidden = true;
  flying.style.transition = "";
  flying.style.transform = "";
  flying.removeAttribute("src");

  updateSideStrip(index, imageUrl);
  slot.classList.add("just-landed");
  setTimeout(() => slot.classList.remove("just-landed"), 320);
}

async function showCaptureError(message) {
  const el = document.getElementById("capture-error");
  if (!el) throw new Error(message);
  stopRingCountdown();
  el.hidden = false;
  el.innerHTML = `<p>${escapeHtml(message)}</p><button class="btn" type="button" id="capture-retry">Try again</button>`;
  return new Promise((resolve) => {
    document.getElementById("capture-retry").onclick = () => {
      el.hidden = true;
      el.innerHTML = "";
      resolve();
    };
  });
}

async function finalizeSession() {
  teardownCaptureShell();
  state.partyState = "composing";
  renderParty();
  try {
    const session = await api.finalize(state.sessionId);
    state.stripUrl = session.strip_local_url
      ? `${window.location.origin}${session.strip_local_url}?t=${Date.now()}`
      : null;
    state.qrUrl = session.r2_strip_url || null;
    state.resultOffline = !state.status?.wifi_ssid;
    state.partyState = "result";
    state.resultTimer = 120;
    renderParty();
    startResultTimer();
    if (!session.r2_strip_url) pollUpload();
  } catch (e) {
    state.partyState = "idle";
    state.sessionId = null;
    renderParty();
    app.innerHTML = `<div class="screen centered"><p class="error-text">${escapeHtml(e.message)}</p><button class="btn" id="back-idle">Back to idle</button></div>`;
    document.getElementById("back-idle").onclick = () => {
      state.partyState = "idle";
      render();
    };
  }
}

async function runPhotoSequence() {
  setActiveSlot(1);
  let pendingShot = waitRingCountdown(
    photoCountdownSeconds(1),
    1,
    () => captureWithFlash(state.sessionId, 1),
  );

  for (let i = 1; i <= 3; i += 1) {
    state.photoIndex = i;
    if (!state.captureShellMounted) return;

    while (true) {
      if (!state.captureShellMounted) return;
      try {
        await pendingShot;
        const photoUrl = `${api.photoUrl(state.sessionId, i)}?t=${Date.now()}`;
        await animateThumbnailToSlot(i, photoUrl);
        if (i < 3) {
          setActiveSlot(i + 1);
          pendingShot = waitRingCountdown(
            photoCountdownSeconds(i + 1),
            i + 1,
            () => captureWithFlash(state.sessionId, i + 1),
          );
        }
        break;
      } catch (e) {
        if (e?.name === "AbortError") return;
        await showCaptureError(e.message);
        if (!state.captureShellMounted) return;
        setActiveSlot(i);
        pendingShot = waitRingCountdown(
          photoCountdownSeconds(i),
          i,
          () => captureWithFlash(state.sessionId, i),
        );
      }
    }
  }
  await finalizeSession();
}

async function startSession() {
  // Re-entrancy guard: a double-tap on the touchscreen would otherwise create
  // two sessions and run two capture loops fighting over the singleton ring.
  // Flip state synchronously (before the first await) so the second tap bails.
  if (state.partyState !== "idle") return;
  state.partyState = "starting";
  try {
    const template = getActiveTemplate();
    const session = await api.startSession(state.activeEvent.id);
    state.sessionId = session.id;
    state.photoIndex = 1;
    mountCaptureShell(template);
    await runPhotoSequence();
  } catch (e) {
    teardownCaptureShell();
    state.partyState = "idle";
    app.innerHTML = `<div class="screen centered"><p class="error-text">${escapeHtml(e.message)}</p><button class="btn" id="retry">Retry</button></div>`;
    document.getElementById("retry").onclick = () => {
      state.partyState = "idle";
      render();
    };
  }
}

function pollUpload() {
  let failures = 0;
  let checking = false;
  const stop = () => {
    if (state.pollInterval) clearInterval(state.pollInterval);
    state.pollInterval = null;
  };
  const check = async () => {
    // The session can be cleared out from under an in-flight poll (return to
    // idle / corner exit); bail rather than GET /sessions/null.
    if (!state.sessionId) {
      stop();
      return;
    }
    if (checking) return;
    checking = true;
    try {
      const [session, status] = await Promise.all([
        api.getSession(state.sessionId),
        api.status(),
      ]);
      state.status = status;
      failures = 0;
      if (session.r2_strip_url) {
        state.qrUrl = session.r2_strip_url;
        if (!state.stripUrl && session.strip_local_url) {
          state.stripUrl = `${window.location.origin}${session.strip_local_url}?t=${Date.now()}`;
        }
        stop();
        renderParty();
        return;
      }
      const offline = !status.wifi_ssid;
      if (offline !== state.resultOffline) {
        state.resultOffline = offline;
        renderParty();
      }
    } catch (e) {
      // Offline venue: don't flood the console for the whole result window.
      // Give up after a few tries — the backend upload rescan will finish it,
      // and the guest already has the on-screen strip.
      failures += 1;
      if (failures >= 5) stop();
    } finally {
      checking = false;
    }
  };
  check();
  state.pollInterval = setInterval(check, 5000);
}

function startResultTimer() {
  if (state.resultInterval) clearInterval(state.resultInterval);
  state.resultInterval = setInterval(() => {
    state.resultTimer -= 1;
    const el = document.getElementById("result-timer");
    if (el) el.textContent = formatResultCountdown(state.resultTimer);
    if (state.resultTimer <= 0) {
      clearInterval(state.resultInterval);
      state.resultInterval = null;
      returnToPartyIdle();
    }
  }, 1000);
}

// Liveness heartbeat: the engine's kiosk watchdog (appliance only) restarts
// Chromium when these stop — a crashed renderer is a permanent blank screen in
// --app kiosk mode and this ping is the only way anything can notice. Plain
// fetch, no JSON, errors ignored (engine restarts are covered by its own retry).
setInterval(() => {
  fetch("/api/kiosk/heartbeat", { method: "POST" }).catch(() => {});
}, 5000);

bootstrap().catch(console.error);
