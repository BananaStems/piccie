const TAP_COUNT = 5;
const TAP_WINDOW_MS = 2000;
const ZONE_SIZE = 100;

let taps = [];
let handler = null;

export function initCornerTap(onTrigger) {
  handler = onTrigger;
  const zone = document.getElementById("corner-tap-zone");
  zone.addEventListener("pointerdown", (e) => {
    const now = Date.now();
    taps = taps.filter((t) => now - t < TAP_WINDOW_MS);
    taps.push(now);
    if (taps.length >= TAP_COUNT) {
      taps = [];
      handler?.();
    }
  });
}

export function setCornerHandler(fn) {
  handler = fn;
}
