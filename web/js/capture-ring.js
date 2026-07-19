/**
 * Countdown ring drawn inside the preview frame with a slight inset.
 */

const RING_INSET = 10;
const RING_RADIUS = 10;
const RAF_MIN_MS = 33;

let chromeEl = null;
let mediaEl = null;
let svgEl = null;
let trackEl = null;
let progressEl = null;
let countdownEl = null;
let countdownSlot = null;
let observer = null;
let timeoutId = null;
let cornerInterval = null;
let rafId = null;
let layoutRafId = null;
let countdownReject = null;
let lastRingWidth = 0;
let lastRingHeight = 0;

/** Open path (no Z) for reliable stroke-dashoffset animation. */
function roundedRectPath(w, h, radius, inset) {
  const left = inset;
  const top = inset;
  const right = w - inset;
  const bottom = h - inset;
  const r = Math.min(radius, (right - left) / 2, (bottom - top) / 2);
  const midX = w / 2;

  return [
    `M ${midX} ${top}`,
    `L ${left + r} ${top}`,
    `Q ${left} ${top} ${left} ${top + r}`,
    `L ${left} ${bottom - r}`,
    `Q ${left} ${bottom} ${left + r} ${bottom}`,
    `L ${right - r} ${bottom}`,
    `Q ${right} ${bottom} ${right} ${bottom - r}`,
    `L ${right} ${top + r}`,
    `Q ${right} ${top} ${right - r} ${top}`,
    `L ${midX} ${top}`,
  ].join(" ");
}

function layoutRing() {
  if (!chromeEl || !mediaEl || !svgEl || !trackEl || !progressEl) return false;

  const mw = mediaEl.clientWidth;
  const mh = mediaEl.clientHeight;
  if (mw < 2 || mh < 2) return false;

  if (mw === lastRingWidth && mh === lastRingHeight) return true;
  lastRingWidth = mw;
  lastRingHeight = mh;

  svgEl.style.left = "0";
  svgEl.style.top = "0";
  svgEl.style.width = `${mw}px`;
  svgEl.style.height = `${mh}px`;

  const rx = Math.min(RING_RADIUS, Math.min(mw, mh) * 0.025);
  const d = roundedRectPath(mw, mh, rx, RING_INSET);

  svgEl.setAttribute("viewBox", `0 0 ${mw} ${mh}`);
  trackEl.setAttribute("d", d);
  progressEl.setAttribute("d", d);
  trackEl.style.display = "";
  progressEl.style.display = "";
  return true;
}

function scheduleLayoutRing() {
  if (layoutRafId) return;
  layoutRafId = requestAnimationFrame(() => {
    layoutRafId = null;
    layoutRing();
  });
}

async function ensureLayout(maxRetries = 6) {
  for (let i = 0; i < maxRetries; i += 1) {
    if (layoutRing()) return true;
    await new Promise((resolve) => requestAnimationFrame(resolve));
  }
  return layoutRing();
}

export function attachCaptureRing(chrome) {
  detachCaptureRing();
  chromeEl = chrome;
  mediaEl = chrome.querySelector(".preview-media");
  svgEl = chrome.querySelector("#preview-ring");
  trackEl = chrome.querySelector("#ring-track");
  progressEl = chrome.querySelector("#ring-progress");
  if (!mediaEl || !svgEl || !trackEl || !progressEl) return;

  observer = new ResizeObserver(() => scheduleLayoutRing());
  observer.observe(chromeEl);
  observer.observe(mediaEl);
  requestAnimationFrame(() => layoutRing());
}

export function detachCaptureRing() {
  stopRingCountdown();
  if (observer) {
    observer.disconnect();
    observer = null;
  }
  if (layoutRafId) {
    cancelAnimationFrame(layoutRafId);
    layoutRafId = null;
  }
  chromeEl = null;
  mediaEl = null;
  svgEl = null;
  trackEl = null;
  progressEl = null;
  countdownEl = null;
  countdownSlot = null;
  lastRingWidth = 0;
  lastRingHeight = 0;
}

function slotCountdownEl(slotIndex) {
  const slot = document.querySelector(`.side-slot[data-slot="${slotIndex}"]`);
  return slot?.querySelector(".slot-countdown") ?? null;
}

export function stopRingCountdown() {
  if (countdownReject) {
    countdownReject(new DOMException("Countdown aborted", "AbortError"));
    countdownReject = null;
  }
  if (timeoutId) {
    clearTimeout(timeoutId);
    timeoutId = null;
  }
  if (cornerInterval) {
    clearInterval(cornerInterval);
    cornerInterval = null;
  }
  if (rafId) {
    cancelAnimationFrame(rafId);
    rafId = null;
  }
  if (progressEl) {
    progressEl.style.strokeDashoffset = "";
    progressEl.style.strokeDasharray = "";
  }
  if (countdownEl) {
    countdownEl.textContent = "";
  }
  countdownEl = null;
  countdownSlot = null;
}

export function startRingCountdown(seconds, slotIndex = 1, onShutter = null) {
  return new Promise(async (resolve, reject) => {
    if (!progressEl) {
      resolve();
      return;
    }

    stopRingCountdown();
    countdownReject = reject;
    countdownSlot = slotIndex;
    countdownEl = slotCountdownEl(slotIndex);
    await ensureLayout();

    const length = progressEl.getTotalLength();
    if (!length || length < 1) {
      countdownReject = null;
      resolve();
      return;
    }

    let remaining = seconds;
    if (countdownEl) countdownEl.textContent = String(remaining);
    cornerInterval = setInterval(() => {
      remaining -= 1;
      if (remaining > 0 && countdownEl) {
        countdownEl.textContent = String(remaining);
      } else {
        clearInterval(cornerInterval);
        cornerInterval = null;
      }
    }, 1000);

    progressEl.style.strokeDasharray = `${length}`;
    progressEl.style.strokeDashoffset = `${length}`;

    const start = performance.now();
    const duration = seconds * 1000;
    let settled = false;
    let shutterPromise = null;
    let lastTick = 0;

    const finish = async () => {
      if (settled) return;
      settled = true;
      countdownReject = null;
      if (rafId) {
        cancelAnimationFrame(rafId);
        rafId = null;
      }
      if (timeoutId) {
        clearTimeout(timeoutId);
        timeoutId = null;
      }
      if (cornerInterval) {
        clearInterval(cornerInterval);
        cornerInterval = null;
      }
      if (countdownEl) countdownEl.textContent = "";
      countdownEl = null;
      countdownSlot = null;
      try {
        if (shutterPromise) await shutterPromise;
        resolve();
      } catch (err) {
        reject(err);
      }
    };

    const tick = (now) => {
      if (now - lastTick < RAF_MIN_MS) {
        rafId = requestAnimationFrame(tick);
        return;
      }
      lastTick = now;
      const t = Math.min(1, (now - start) / duration);
      progressEl.style.strokeDashoffset = `${length * (1 - t)}`;
      if (t < 1) {
        rafId = requestAnimationFrame(tick);
        return;
      }
      rafId = null;
      if (onShutter && !shutterPromise) {
        shutterPromise = onShutter();
      }
      finish();
    };

    rafId = requestAnimationFrame(tick);
    timeoutId = setTimeout(() => {
      if (onShutter && !shutterPromise) {
        shutterPromise = onShutter();
      }
      finish();
    }, duration);
  });
}
