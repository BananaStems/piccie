const tokenFromLink = new URL(location.href).hash.match(/(?:^#|&)token=([^&]+)/)?.[1] || "";
if (tokenFromLink) {
  sessionStorage.setItem("piccie-studio-token", tokenFromLink);
  history.replaceState(null, "", location.pathname);
}
const token = tokenFromLink || sessionStorage.getItem("piccie-studio-token") || "";

const DRAFT_KEY = "piccie-template-draft-v1";
// Mirrors engine/template_packages.py: print size, editable zones and limits.
const STRIP_W = 600;
const STRIP_H = 1800;
const FOOTER_TOP = 1320;
const OVERLAY_TOP = 1220;
const MAX_LAYERS = 24;
const MAX_IMAGES = 8;
const MAX_IMAGE_BYTES = 2.8 * 1024 * 1024;
const IMAGE_SIDES = [1200, 900, 700];

const SWATCHES = [
  ["#29231e", "Ink"], ["#ffffff", "White"], ["#756c63", "Stone"], ["#c45c4a", "Terracotta"],
  ["#d5a24a", "Gold"], ["#5f7a63", "Sage"], ["#2f4a6b", "Navy"], ["#e7b7b2", "Blush"],
];
const TEXT_FIELDS = [
  { source: "line1", name: "Heading", detail: "The event name" },
  { source: "line2", name: "Subheading", detail: "The event's second line" },
  { source: "date", name: "Date", detail: "The event date" },
];
const ICONS = {
  text: '<path d="M5 7V5h14v2M9 19h6M12 5v14"/>',
  image: '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><circle cx="9" cy="10" r="1.8"/><path d="m20.5 16-4.5-4.5-9 8"/>',
  shape: '<circle cx="8.5" cy="8.5" r="4.5"/><rect x="12" y="12" width="8.5" height="8.5" rx="1.8"/>',
  resize: '<path d="M14 5h5v5M10 19H5v-5M19 5l-6 6M5 19l6-6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  alignLeft: '<path d="M4 6h16M4 10h10M4 14h16M4 18h10"/>',
  alignCenter: '<path d="M4 6h16M7 10h10M4 14h16M7 18h10"/>',
  alignRight: '<path d="M4 6h16M10 10h10M4 14h16M10 18h10"/>',
  centre: '<path d="M12 3v18"/><rect x="5.5" y="8" width="13" height="8" rx="2"/>',
  duplicate: '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V6.5a2 2 0 0 0-2-2h-7a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h2"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
  up: '<path d="M12 19V5M6 11l6-6 6 6"/>',
  down: '<path d="M12 5v14M6 13l6 6 6-6"/>',
};
const icon = (name) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;

const GRAPHIC_PRESETS = [
  {
    id: "bunting", name: "Party banner", width: 360, view: [600, 220],
    body: '<path d="M28 38 Q300 150 572 38" fill="none" stroke="#2d2722" stroke-width="10" stroke-linecap="round"/><g fill="#c45c4a"><path d="M82 64l58 20-46 68z"/><path d="M232 103l63 7-38 78z"/><path d="M390 97l61-14-14 85z"/></g><g fill="#d5a24a"><path d="M154 87l62 14-42 73z"/><path d="M311 108l63-5-29 81z"/><path d="M464 78l56-24 1 84z"/></g>',
  },
  {
    id: "fireworks", name: "Fireworks", width: 320, view: [600, 300],
    body: '<g fill="none" stroke-linecap="round"><g stroke="#c45c4a" stroke-width="14"><path d="M184 130V38M184 130l-68-68M184 130l-92 4M184 130l-66 70M184 130l4 92M184 130l72 66M184 130l92-4M184 130l65-69"/></g><g stroke="#d5a24a" stroke-width="11"><path d="M430 171V86M430 171l-61-60M430 171l-82 3M430 171l-57 61M430 171l4 82M430 171l62 57M430 171l81-5M430 171l56-59"/></g></g><g fill="#2d2722"><circle cx="184" cy="130" r="13"/><circle cx="430" cy="171" r="11"/><circle cx="305" cy="58" r="8"/><circle cx="323" cy="238" r="7"/></g>',
  },
  {
    id: "champagne", name: "Champagne", width: 220, view: [400, 380],
    body: '<g fill="none" stroke="#2d2722" stroke-width="15" stroke-linecap="round" stroke-linejoin="round"><path d="M48 35h130l-20 124c-8 49-81 49-90 0zM112 199v118M63 335h98"/><path d="M222 35h130l-20 124c-8 49-81 49-90 0zM286 199v118M237 335h98"/></g><path d="M67 118h91l-9 48c-8 34-64 34-72 0zM241 118h91l-9 48c-8 34-64 34-72 0z" fill="#d5a24a" opacity=".78"/><g fill="#c45c4a"><circle cx="94" cy="84" r="10"/><circle cx="130" cy="65" r="7"/><circle cx="269" cy="82" r="8"/><circle cx="307" cy="59" r="11"/></g>',
  },
  {
    id: "confetti", name: "Confetti", width: 340, view: [600, 280],
    body: '<g fill="none" stroke-linecap="round" stroke-width="16"><path d="M63 61l34 40" stroke="#c45c4a"/><path d="M198 38l-10 54" stroke="#d5a24a"/><path d="M318 55l31 40" stroke="#2d2722"/><path d="M467 40l-19 53" stroke="#c45c4a"/><path d="M533 126l-46 25" stroke="#d5a24a"/><path d="M116 197l43-27" stroke="#2d2722"/><path d="M272 218l16-47" stroke="#c45c4a"/><path d="M417 221l33-40" stroke="#2d2722"/></g><g fill="#c45c4a"><circle cx="143" cy="80" r="13"/><circle cx="382" cy="126" r="11"/><path d="M510 207l24 35-42 3z"/></g><g fill="#d5a24a"><path d="M49 159l25-33 21 37z"/><circle cx="220" cy="145" r="12"/><circle cx="354" cy="225" r="10"/></g>',
  },
  {
    id: "starburst", name: "Starburst", width: 210, view: [400, 400],
    body: '<path d="M200 18l32 111 91-70-52 102 116 7-111 34 71 91-103-51-7 115-34-110-91 71 51-103-115-7 111-34-71-91 103 51z" fill="#d5a24a"/><path d="M200 93l22 74 61-46-35 68 77 5-74 23 47 60-69-34-5 77-23-74-60 47 34-69-77-5 74-22-47-61 69 35z" fill="#c45c4a"/>',
  },
];

const stage = document.getElementById("strip-stage");
const shell = document.getElementById("strip-shell");
const strip = document.getElementById("studio-strip");
const layerRoot = document.getElementById("studio-layers");
const snapGuide = document.getElementById("snap-guide");
const sheet = document.getElementById("studio-sheet");
const sheetTitle = document.getElementById("sheet-title");
const sheetContent = document.getElementById("sheet-content");
const status = document.getElementById("studio-status");
const nameDisplay = document.getElementById("studio-name-display");
const canvasHint = document.getElementById("canvas-hint");
const undoButton = document.getElementById("undo-edit");
const redoButton = document.getElementById("redo-edit");
const saveButton = document.getElementById("install-template");
const phoneLayout = matchMedia("(max-width: 760px)");
const fontLinks = new Set();
const pointers = new Map();

let scale = 0.25;
let fitScale = scale;
let viewMode = "footer";
let sheetMode = null;
let selectedId = null;
let templateName = "";
let counter = 0;
let gesture = null;
let pan = null;
let stageTap = null;
let sheetSwipe = null;
let statusTimer = null;
let historyStates = [];
let historyIndex = 0;
let savedSnapshot = null;
let savedOnce = false;
let saving = false;
let draftWarned = false;
let nameInvalid = false;
let confirmingReset = false;

const state = { background: "#ffffff", fonts: [], assets: [], layers: defaultLayers() };

// Drafts outlive page loads, so ids carry time as well as a counter to stay unique.
function id(prefix) { counter += 1; return `${prefix}-${Date.now().toString(36)}${counter.toString(36)}`; }
function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}
function textLayer(source, x, y, w, h, fontSize = 48, font = "sans", fill = "#29231e") {
  return { id: id(source), type: "text", source, x, y, w, h, font_size: fontSize, font, fill, align: "center", uppercase: source === "line1" };
}
function defaultLayers() {
  return [
    textLayer("line1", 55, 1372, 490, 84, 62, "playfair-display", "#29231e"),
    textLayer("line2", 55, 1470, 490, 68, 36, "sans", "#756c63"),
    textLayer("date", 160, 1590, 280, 52, 28, "sans", "#29231e"),
  ];
}
function sampleText(layer) {
  // Mixed case, so the Letters setting visibly changes the preview.
  return { line1: "Your Event", line2: "Celebration", date: "01/08/26" }[layer.source] || "Text";
}
function layerName(layer) {
  if (layer.type === "text") return TEXT_FIELDS.find((field) => field.source === layer.source)?.name || "Text";
  return layer.name || (layer.type === "image" ? "Image" : "Shape");
}
function selected() { return state.layers.find((layer) => layer.id === selectedId); }
function fontName(fontId) {
  if (fontId === "sans") return "Outfit";
  if (fontId === "serif") return "Georgia";
  return state.fonts.find((font) => font.id === fontId)?.name || "Outfit";
}
function googleFontsHref(fonts) {
  const families = fonts.filter((font) => font.file)
    .map((font) => `family=${encodeURIComponent(font.name).replace(/%20/g, "+")}`)
    .join("&");
  return families ? `https://fonts.googleapis.com/css2?${families}&display=swap` : "";
}
function loadFonts(fonts) {
  const href = googleFontsHref(fonts);
  if (!href || fontLinks.has(href)) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  document.head.appendChild(link);
  fontLinks.add(href);
}

/* History, drafts and saving state */

function snapshot() {
  // Images are kept once in state.assets, never copied into every undo step.
  return JSON.stringify({ background: state.background, layers: state.layers });
}
function usedAssets() {
  const used = new Set(state.layers.filter((layer) => layer.type === "image").map((layer) => layer.asset));
  return state.assets.filter((asset) => used.has(asset.id));
}
function resetHistory() {
  historyStates = [snapshot()];
  historyIndex = 0;
}
function commit() {
  const next = snapshot();
  if (next === historyStates[historyIndex]) return;
  historyStates = historyStates.slice(0, historyIndex + 1);
  historyStates.push(next);
  if (historyStates.length > 40) historyStates.shift();
  historyIndex = historyStates.length - 1;
  saveDraft();
}
function restoreHistory(index) {
  if (index < 0 || index >= historyStates.length) return;
  historyIndex = index;
  const restored = JSON.parse(historyStates[historyIndex]);
  state.background = restored.background;
  state.layers = restored.layers;
  if (!selected()) {
    selectedId = null;
    if (sheetMode === "edit") sheetMode = null;
  }
  saveDraft();
  render();
}
function saveDraft() {
  try {
    const design = { background: state.background, layers: state.layers, assets: usedAssets() };
    localStorage.setItem(DRAFT_KEY, JSON.stringify({ version: 1, name: templateName, saved: savedOnce, design }));
  } catch {
    if (!draftWarned) {
      draftWarned = true;
      showStatus("This design is too big to keep on this phone. Save it to the booth so it isn't lost.", "error");
    }
  }
}
function restoreDraft() {
  try {
    const draft = JSON.parse(localStorage.getItem(DRAFT_KEY));
    if (draft?.version !== 1 || !Array.isArray(draft.design?.layers)) return false;
    templateName = draft.name === "Untitled template" ? "" : (draft.name || "");
    savedOnce = draft.saved === true;
    state.background = draft.design.background || "#ffffff";
    state.assets = Array.isArray(draft.design.assets) ? draft.design.assets : [];
    state.layers = draft.design.layers;
    return true;
  } catch { return false; }
}

/* Canvas sizing, zoom and keeping the edited item in view */

function stageSpace() {
  const style = getComputedStyle(stage);
  return {
    width: stage.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight),
    height: stage.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom),
  };
}
function fitStrip(reset = false) {
  const available = stageSpace();
  const nextFit = viewMode === "footer"
    ? Math.min(1, Math.max(120, available.width) / STRIP_W)
    : Math.min(1, Math.max(120, available.width) / STRIP_W, Math.max(300, available.height) / STRIP_H);
  const wasFitted = reset || scale <= fitScale + 0.001;
  fitScale = nextFit;
  scale = wasFitted ? fitScale : Math.max(fitScale, Math.min(1, scale));
  sizeStrip();
  requestAnimationFrame(() => {
    if (wasFitted) {
      stage.scrollLeft = 0;
      stage.scrollTop = viewMode === "footer" ? stage.scrollHeight : 0;
    }
    revealSelected();
  });
}
function sizeStrip() {
  shell.style.width = `${STRIP_W * scale}px`;
  shell.style.height = `${STRIP_H * scale}px`;
  strip.style.transform = `scale(${scale})`;
  strip.style.setProperty("--ui", (1 / scale).toFixed(4));
}
function revealSelected() {
  const layer = selected();
  if (!layer) return;
  const stageRect = stage.getBoundingClientRect();
  const shellRect = shell.getBoundingClientRect();
  const margin = 28;
  const top = shellRect.top - stageRect.top + stage.scrollTop + layer.y * scale - margin;
  const bottom = top + layer.h * scale + margin * 2;
  if (top < stage.scrollTop) stage.scrollTop = top;
  else if (bottom > stage.scrollTop + stage.clientHeight) stage.scrollTop = bottom - stage.clientHeight;
  const left = shellRect.left - stageRect.left + stage.scrollLeft + layer.x * scale - margin;
  const right = left + layer.w * scale + margin * 2;
  if (left < stage.scrollLeft) stage.scrollLeft = left;
  else if (right > stage.scrollLeft + stage.clientWidth) stage.scrollLeft = right - stage.clientWidth;
}
function setView(mode) {
  viewMode = mode;
  document.getElementById("view-footer").setAttribute("aria-pressed", String(mode === "footer"));
  document.getElementById("view-full").setAttribute("aria-pressed", String(mode === "full"));
  fitStrip(true);
}
function pointDistance([a, b]) { return Math.hypot(a.x - b.x, a.y - b.y); }
function pointCentre([a, b]) { return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }; }

stage.onpointerdown = (event) => {
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  if (!event.target.closest(".studio-layer")) {
    stage.setPointerCapture(event.pointerId);
    pan = { id: event.pointerId, x: event.clientX, y: event.clientY, left: stage.scrollLeft, top: stage.scrollTop };
    stageTap = { id: event.pointerId, x: event.clientX, y: event.clientY };
  }
  if (pointers.size === 2) {
    const pair = [...pointers.values()];
    const centre = pointCentre(pair);
    const rect = shell.getBoundingClientRect();
    gesture = { distance: pointDistance(pair), scale, x: (centre.x - rect.left) / scale, y: (centre.y - rect.top) / scale };
    pan = null;
    stageTap = null;
  }
};
stage.onpointermove = (event) => {
  if (!pointers.has(event.pointerId)) return;
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  if (stageTap?.id === event.pointerId && Math.hypot(event.clientX - stageTap.x, event.clientY - stageTap.y) > 8) stageTap = null;
  if (gesture && pointers.size >= 2) {
    const pair = [...pointers.values()].slice(0, 2);
    const centre = pointCentre(pair);
    scale = Math.max(fitScale, Math.min(1, gesture.scale * pointDistance(pair) / gesture.distance));
    sizeStrip();
    const rect = shell.getBoundingClientRect();
    stage.scrollLeft += rect.left + gesture.x * scale - centre.x;
    stage.scrollTop += rect.top + gesture.y * scale - centre.y;
  } else if (pan?.id === event.pointerId && scale > fitScale) {
    stage.scrollLeft = pan.left - (event.clientX - pan.x);
    stage.scrollTop = pan.top - (event.clientY - pan.y);
  }
};
function releasePointer(event) {
  pointers.delete(event.pointerId);
  if (pointers.size < 2) gesture = null;
  if (pan?.id === event.pointerId) pan = null;
  // A plain tap on the bench or an empty part of the strip clears the selection.
  if (stageTap?.id === event.pointerId && event.type === "pointerup" && selectedId) {
    selectedId = null;
    if (sheetMode === "edit") sheetMode = null;
    render();
  }
  if (stageTap?.id === event.pointerId) stageTap = null;
}
stage.onpointerup = releasePointer;
stage.onpointercancel = releasePointer;

/* Rendering */

function render() {
  renderCanvas();
  renderSheet();
  renderChrome();
}
function layerStyle(layer) {
  return `left:${layer.x}px;top:${layer.y}px;width:${layer.w}px;height:${layer.h}px`;
}
function renderCanvas() {
  strip.style.background = state.background;
  const handle = `<span class="layer-resize-handle" aria-hidden="true">${icon("resize")}</span>`;
  layerRoot.innerHTML = state.layers.map((layer) => {
    const isSelected = layer.id === selectedId;
    const attrs = `type="button" class="studio-layer studio-layer-${layer.type}${isSelected ? " is-selected" : ""}" data-layer="${escapeHtml(layer.id)}" aria-pressed="${isSelected}"`;
    const extra = isSelected ? handle : "";
    if (layer.type === "text") {
      const justify = { left: "flex-start", right: "flex-end" }[layer.align] || "center";
      return `<button ${attrs} aria-label="${escapeHtml(layerName(layer))}" style="${layerStyle(layer)};font-family:'${escapeHtml(fontName(layer.font))}',sans-serif;font-size:${layer.font_size}px;color:${layer.fill};justify-content:${justify};text-transform:${layer.uppercase ? "uppercase" : "none"}">${sampleText(layer)}${extra}</button>`;
    }
    if (layer.type === "image") {
      const asset = state.assets.find((item) => item.id === layer.asset);
      return `<button ${attrs} aria-label="${escapeHtml(layerName(layer))}" style="${layerStyle(layer)}"><img src="${asset?.data || ""}" alt="" />${extra}</button>`;
    }
    return `<button ${attrs} aria-label="${escapeHtml(layerName(layer))}" style="${layerStyle(layer)};background:${layer.fill};border-radius:${layer.radius}px">${extra}</button>`;
  }).join("");
  loadFonts(state.fonts.filter((font) => state.layers.some((layer) => layer.font === font.id)));
  bindDragging();
}
function renderChrome() {
  sheet.classList.toggle("is-open", Boolean(sheetMode));
  document.querySelectorAll("[data-tool]").forEach((button) => {
    const active = button.dataset.tool === sheetMode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  nameDisplay.textContent = templateName || "Untitled template";
  nameDisplay.classList.toggle("is-placeholder", !templateName);
  canvasHint.textContent = selected() ? "Drag to move or resize" : "Tap an item to edit";
  undoButton.disabled = historyIndex <= 0;
  redoButton.disabled = historyIndex >= historyStates.length - 1;
  const unchanged = savedSnapshot !== null && savedSnapshot === snapshot();
  saveButton.disabled = saving || unchanged;
  saveButton.classList.toggle("is-saved", unchanged);
  saveButton.innerHTML = saving ? "Saving…" : unchanged ? `${icon("check")}Saved` : savedOnce ? "Save copy" : "Save";
}

/* Direct manipulation on the strip */

function clamp(layer) {
  layer.w = Math.min(STRIP_W, Math.max(8, layer.w));
  layer.h = Math.min(580, Math.max(8, layer.h));
  layer.x = Math.min(STRIP_W - layer.w, Math.max(0, layer.x));
  const top = layer.type === "image" ? OVERLAY_TOP : FOOTER_TOP;
  layer.y = Math.min(STRIP_H - layer.h, Math.max(top, layer.y));
}
function snap(value, targets, tolerance) {
  const target = targets.find((item) => Math.abs(item - value) <= tolerance);
  return target ?? value;
}
function selectLayer(layerId) {
  selectedId = layerId;
  sheetMode = "edit";
  render();
}
function bindDragging() {
  layerRoot.querySelectorAll(".studio-layer").forEach((element) => {
    // Keyboard activation (detail 0) selects; pointers go through the handlers below.
    element.onclick = (event) => { if (event.detail === 0) selectLayer(element.dataset.layer); };
    element.onpointerdown = (event) => {
      event.preventDefault();
      const layer = state.layers.find((item) => item.id === element.dataset.layer);
      if (!layer) return;
      const resizing = Boolean(event.target.closest(".layer-resize-handle"));
      const start = { x: event.clientX, y: event.clientY, left: layer.x, top: layer.y, w: layer.w, h: layer.h, fontSize: layer.font_size };
      let cancelled = false;
      let moved = false;
      element.setPointerCapture(event.pointerId);
      element.onpointermove = (move) => {
        if (pointers.size > 1) cancelled = true;
        if (cancelled) return;
        if (!moved && Math.hypot(move.clientX - start.x, move.clientY - start.y) < 4) return;
        if (resizing) {
          const widthRatio = (start.w + (move.clientX - start.x) / scale) / start.w;
          const heightRatio = (start.h + (move.clientY - start.y) / scale) / start.h;
          const minimum = Math.max(24 / start.w, 16 / start.h, layer.type === "text" ? 12 / start.fontSize : 0);
          const maximum = Math.min(
            (STRIP_W - start.left) / start.w,
            (STRIP_H - start.top) / start.h,
            580 / start.h,
            layer.type === "text" ? 180 / start.fontSize : Infinity,
          );
          const factor = Math.max(minimum, Math.min(maximum, Math.max(widthRatio, heightRatio)));
          layer.w = start.w * factor;
          layer.h = start.h * factor;
          if (layer.type === "text") layer.font_size = start.fontSize * factor;
          moved = true;
          element.style.width = `${layer.w}px`;
          element.style.height = `${layer.h}px`;
          if (layer.type === "text") element.style.fontSize = `${layer.font_size}px`;
          return;
        }
        const tolerance = 10 / scale;
        const centreX = (STRIP_W - layer.w) / 2;
        layer.x = snap(start.left + (move.clientX - start.x) / scale, [0, centreX, STRIP_W - layer.w], tolerance);
        layer.y = snap(start.top + (move.clientY - start.y) / scale, [layer.type === "image" ? OVERLAY_TOP : FOOTER_TOP, FOOTER_TOP, STRIP_H - layer.h], tolerance);
        clamp(layer);
        moved = true;
        snapGuide.classList.toggle("is-visible", Math.abs(layer.x - centreX) < 0.5);
        element.style.left = `${layer.x}px`;
        element.style.top = `${layer.y}px`;
      };
      element.onpointerup = element.onpointercancel = (end) => {
        element.onpointermove = null;
        element.onpointerup = element.onpointercancel = null;
        snapGuide.classList.remove("is-visible");
        if (cancelled || end.type === "pointercancel") {
          render();
          return;
        }
        selectedId = layer.id;
        if (moved) {
          commit();
          render();
        } else {
          selectLayer(layer.id);
        }
      };
    };
  });
}
layerRoot.onkeydown = (event) => {
  const layer = selected();
  if (!layer || !event.target.closest(".studio-layer")) return;
  const step = event.shiftKey ? 10 : 1;
  const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
  if (moves[event.key]) {
    event.preventDefault();
    layer.x += moves[event.key][0];
    layer.y += moves[event.key][1];
    clamp(layer);
    commit();
    render();
    layerRoot.querySelector(`[data-layer="${CSS.escape(layer.id)}"]`)?.focus();
  } else if (event.key === "Delete" || event.key === "Backspace") {
    event.preventDefault();
    deleteLayer(layer);
  }
};

/* Panel content */

const SHEET_TITLES = { text: "Event text", shapes: "Shapes", design: "Template", layers: "Layers" };
function setSheet(mode) {
  sheetMode = mode;
  confirmingReset = false;
  render();
}
function renderSheet() {
  if (sheetMode === "edit" && !selected()) sheetMode = null;
  sheetTitle.textContent = sheetMode === "edit" ? layerName(selected()) : SHEET_TITLES[sheetMode] || "Template Studio";
  if (!sheetMode) {
    sheetContent.innerHTML = '<p class="sheet-empty">Tap anything on the strip to edit it, or add text, images and shapes from the bar below.</p>';
    return;
  }
  ({ text: renderTextSheet, shapes: renderShapesSheet, design: renderDesignSheet, layers: renderLayersSheet, edit: renderEditSheet })[sheetMode]();
}
function swatchField(label, value, onPick) {
  const known = SWATCHES.some(([hex]) => hex === value.toLowerCase());
  const html = `<div class="field"><span class="field-label">${label}</span><div class="swatches">
    ${SWATCHES.map(([hex, name]) => `<button class="swatch" type="button" style="--swatch:${hex}" data-swatch="${hex}" aria-label="${name}" aria-pressed="${hex === value.toLowerCase()}"></button>`).join("")}
    <label class="swatch swatch-custom${known ? "" : " is-current"}" ${known ? "" : `style="background:${value}"`}>${known ? icon("plus") : ""}<input type="color" value="${value}" aria-label="Custom colour"></label>
  </div></div>`;
  return {
    html,
    bind(root) {
      root.querySelectorAll("[data-swatch]").forEach((button) => { button.onclick = () => onPick(button.dataset.swatch, true); });
      const custom = root.querySelector(".swatch-custom input");
      custom.oninput = () => onPick(custom.value, false);
      custom.onchange = () => onPick(custom.value, true);
    },
  };
}
function sliderField(label, prop, min, max, value, unit = "px") {
  return `<label class="field"><span class="field-head"><span class="field-label">${label}</span><span class="field-value" data-value-for="${prop}">${Math.round(value)} ${unit}</span></span>
    <input type="range" min="${min}" max="${max}" step="1" value="${Math.round(value)}" data-slider="${prop}"></label>`;
}
function segmented(label, prop, options, current) {
  return `<div class="field"><span class="field-label">${label}</span><div class="segmented" role="group" aria-label="${label}">
    ${options.map(([value, content, aria]) => `<button type="button" data-segment="${prop}" data-value="${value}" aria-pressed="${String(value) === String(current)}"${aria ? ` aria-label="${aria}"` : ""}>${content}</button>`).join("")}
  </div></div>`;
}
function renderTextSheet() {
  sheetContent.innerHTML = `<p class="sheet-note">These fill in from each event's details when guests print their strip.</p>
    <div class="option-list">${TEXT_FIELDS.map((field) => {
      const onStrip = state.layers.some((layer) => layer.type === "text" && layer.source === field.source);
      return `<button class="option-row" type="button" data-add="${field.source}"><span><strong>${field.name}</strong><small>${field.detail}</small></span><span class="chip${onStrip ? "" : " is-add"}">${onStrip ? "Edit" : "Add"}</span></button>`;
    }).join("")}</div>`;
  sheetContent.querySelectorAll("[data-add]").forEach((button) => { button.onclick = () => addText(button.dataset.add); });
}
function renderShapesSheet() {
  sheetContent.innerHTML = `<div class="shape-grid">
    <button class="shape-preset" type="button" data-basic-shape="circle"><span><i class="shape-circle"></i></span><strong>Circle</strong></button>
    <button class="shape-preset" type="button" data-basic-shape="rectangle"><span><i class="shape-rectangle"></i></span><strong>Label</strong></button>
    ${GRAPHIC_PRESETS.map((preset) => `<button class="shape-preset" type="button" data-graphic="${preset.id}"><span><svg viewBox="0 0 ${preset.view[0]} ${preset.view[1]}" aria-hidden="true">${preset.body}</svg></span><strong>${preset.name}</strong></button>`).join("")}
  </div>`;
  sheetContent.querySelectorAll("[data-basic-shape]").forEach((button) => { button.onclick = () => addBasicShape(button.dataset.basicShape); });
  sheetContent.querySelectorAll("[data-graphic]").forEach((button) => { button.onclick = () => addGraphicPreset(button.dataset.graphic); });
}
function renderDesignSheet() {
  const footer = swatchField("Footer colour", state.background, (hex, done) => {
    state.background = hex;
    strip.style.background = hex;
    if (done) { commit(); render(); }
  });
  sheetContent.innerHTML = `<label class="field"><span class="field-label">Template name</span>
      <input class="text-input" id="template-name" maxlength="80" value="${escapeHtml(templateName)}" placeholder="For example, Sarah and James" autocomplete="off" enterkeyhint="done" aria-invalid="${nameInvalid}" aria-describedby="name-error"></label>
    <p class="field-error" id="name-error"${nameInvalid ? "" : " hidden"}>Give the template a name so you can find it on the booth.</p>
    ${footer.html}
    <div class="sheet-divider"></div>
    ${confirmingReset
      ? `<div class="reset-confirm"><p>Start again from a blank footer? This clears the design on this phone. Templates already saved to the booth stay there.</p>
          <div class="action-row"><button class="action-button" type="button" id="reset-cancel">Keep this design</button><button class="action-button is-primary" type="button" id="reset-confirm">Start new</button></div></div>`
      : '<div class="action-row"><button class="action-button" type="button" id="reset-template">Start a new template</button></div>'}`;
  footer.bind(sheetContent);
  const nameInput = document.getElementById("template-name");
  nameInput.oninput = () => {
    templateName = nameInput.value;
    if (nameInvalid && templateName.trim()) {
      nameInvalid = false;
      nameInput.setAttribute("aria-invalid", "false");
      document.getElementById("name-error").hidden = true;
    }
    renderChrome();
    saveDraft();
  };
  nameInput.onkeydown = (event) => { if (event.key === "Enter") nameInput.blur(); };
  const resetButton = document.getElementById("reset-template");
  if (resetButton) resetButton.onclick = () => { confirmingReset = true; renderSheet(); };
  const cancel = document.getElementById("reset-cancel");
  if (cancel) cancel.onclick = () => { confirmingReset = false; renderSheet(); };
  const confirm = document.getElementById("reset-confirm");
  if (confirm) confirm.onclick = startNewTemplate;
}
function renderLayersSheet() {
  const kinds = { text: "text", image: "image", shape: "shape" };
  const layer = selected();
  const index = state.layers.indexOf(layer);
  sheetContent.innerHTML = `<p class="sheet-note">The top of the list sits in front.</p>
    <div class="option-list">${[...state.layers].reverse().map((item) => `
      <button class="option-row" type="button" data-select="${escapeHtml(item.id)}" aria-pressed="${item.id === selectedId}">
        <span class="row-main"><span class="layer-icon">${icon(kinds[item.type])}</span><strong>${escapeHtml(layerName(item))}</strong></span>
      </button>`).join("")}</div>
    <div class="action-row">
      <button class="action-button" type="button" id="layer-down"${layer && index > 0 ? "" : " disabled"}>${icon("down")}Send back</button>
      <button class="action-button" type="button" id="layer-up"${layer && index < state.layers.length - 1 ? "" : " disabled"}>${icon("up")}Bring forward</button>
    </div>`;
  sheetContent.querySelectorAll("[data-select]").forEach((button) => {
    button.onclick = () => { selectedId = button.dataset.select; render(); };
  });
  document.getElementById("layer-down").onclick = () => moveLayer(-1);
  document.getElementById("layer-up").onclick = () => moveLayer(1);
}
function renderEditSheet() {
  const layer = selected();
  let fields = "";
  let colour = null;
  if (layer.type === "text") {
    const field = TEXT_FIELDS.find((item) => item.source === layer.source);
    loadFonts(state.fonts);
    fields += `<p class="sheet-note">Shows ${field ? field.detail.toLowerCase() : "event text"} on each strip.</p>`;
    fields += `<div class="field"><span class="field-label">Font</span><div class="font-browser" role="group" aria-label="Fonts">${state.fonts.map((font) => `<button class="font-option" type="button" data-font="${escapeHtml(font.id)}" aria-pressed="${font.id === layer.font}" style="font-family:'${escapeHtml(fontName(font.id))}',sans-serif"><strong>Ag</strong><span>${escapeHtml(font.name)}</span></button>`).join("")}</div></div>`;
    fields += sliderField("Size", "font_size", 12, 180, layer.font_size);
    colour = swatchField("Colour", layer.fill, (hex, done) => updateLayer(layer, { fill: hex }, done));
    fields += colour.html;
    fields += `<div class="field-pair">${segmented("Align", "align", [["left", icon("alignLeft"), "Align left"], ["center", icon("alignCenter"), "Align centre"], ["right", icon("alignRight"), "Align right"]], layer.align)}
      ${segmented("Letters", "uppercase", [["false", "Aa", "As typed"], ["true", "AA", "All capitals"]], layer.uppercase)}</div>`;
  } else if (layer.type === "shape") {
    colour = swatchField("Colour", layer.fill, (hex, done) => updateLayer(layer, { fill: hex }, done));
    fields += colour.html;
    fields += sliderField("Width", "w", 24, STRIP_W, layer.w);
    fields += sliderField("Height", "h", 16, 480, layer.h);
    fields += sliderField("Corners", "radius", 0, 100, layer.radius);
  } else {
    fields += sliderField("Size", "image_w", 24, STRIP_W, layer.w);
  }
  sheetContent.innerHTML = `${fields}<div class="action-row">
      <button class="action-button" type="button" id="centre-layer">${icon("centre")}Centre</button>
      <button class="action-button" type="button" id="duplicate-layer">${icon("duplicate")}Duplicate</button>
      <button class="action-button is-danger" type="button" id="delete-layer">${icon("trash")}Delete</button>
    </div>`;
  colour?.bind(sheetContent);
  sheetContent.querySelectorAll("[data-font]").forEach((button) => {
    button.onclick = () => updateLayer(layer, { font: button.dataset.font }, true);
  });
  sheetContent.querySelectorAll("[data-segment]").forEach((button) => {
    button.onclick = () => {
      const value = button.dataset.segment === "uppercase" ? button.dataset.value === "true" : button.dataset.value;
      updateLayer(layer, { [button.dataset.segment]: value }, true);
    };
  });
  sheetContent.querySelectorAll("[data-slider]").forEach((input) => {
    const label = sheetContent.querySelector(`[data-value-for="${input.dataset.slider}"]`);
    input.oninput = () => {
      const prop = input.dataset.slider;
      resizeFromSlider(layer, prop, Number(input.value));
      label.textContent = `${Math.round({ font_size: layer.font_size, image_w: layer.w }[prop] ?? layer[prop])} px`;
      renderCanvas();
    };
    input.onchange = () => { commit(); renderChrome(); };
  });
  document.getElementById("centre-layer").onclick = () => updateLayer(layer, { x: (STRIP_W - layer.w) / 2 }, true);
  document.getElementById("duplicate-layer").onclick = () => duplicateLayer(layer);
  document.getElementById("delete-layer").onclick = () => deleteLayer(layer);
}

/* Edits */

function updateLayer(layer, patch, done) {
  Object.assign(layer, patch);
  clamp(layer);
  if (done) {
    commit();
    render();
  } else {
    renderCanvas();
  }
}
// Text and image sliders scale around the item's centre so it stays where it was placed.
function scaleAroundCentre(layer, factor) {
  const cx = layer.x + layer.w / 2;
  const cy = layer.y + layer.h / 2;
  layer.w *= factor;
  layer.h *= factor;
  if (layer.type === "text") layer.font_size *= factor;
  layer.x = cx - layer.w / 2;
  layer.y = cy - layer.h / 2;
  clamp(layer);
}
function resizeFromSlider(layer, prop, value) {
  if (prop === "font_size") {
    const maximum = Math.min(STRIP_W / layer.w, 480 / layer.h, 180 / layer.font_size);
    scaleAroundCentre(layer, Math.min(value / layer.font_size, maximum));
  } else if (prop === "image_w") {
    scaleAroundCentre(layer, Math.min(value / layer.w, STRIP_W / layer.w, 480 / layer.h));
  } else {
    layer[prop] = value;
    clamp(layer);
  }
}
function canAddLayer() {
  if (state.layers.length < MAX_LAYERS) return true;
  showStatus(`A template can hold up to ${MAX_LAYERS} items. Delete one to add another.`, "error");
  return false;
}
function canAddImage() {
  if (!canAddLayer()) return false;
  if (usedAssets().length < MAX_IMAGES) return true;
  showStatus(`A template can hold up to ${MAX_IMAGES} images. Delete one to add another.`, "error");
  return false;
}
function addLayer(layer) {
  state.layers.push(layer);
  selectedId = layer.id;
  sheetMode = "edit";
  commit();
  render();
}
function addText(source) {
  const existing = state.layers.find((layer) => layer.type === "text" && layer.source === source);
  if (existing) {
    selectLayer(existing.id);
    return;
  }
  if (canAddLayer()) addLayer(textLayer(source, 60, 1400, 480, 72));
}
function addBasicShape(kind) {
  if (!canAddLayer()) return;
  const circle = kind === "circle";
  addLayer({
    id: id("shape"), type: "shape", name: circle ? "Circle" : "Label",
    x: circle ? 225 : 150, y: 1450, w: circle ? 150 : 300, h: circle ? 150 : 90,
    fill: "#c45c4a", radius: circle ? 100 : 18,
  });
}
function addGraphicPreset(presetId) {
  const preset = GRAPHIC_PRESETS.find((item) => item.id === presetId);
  if (!preset || !canAddImage()) return;
  const source = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${preset.view[0]} ${preset.view[1]}">${preset.body}</svg>`;
  const image = new Image();
  image.onload = () => {
    const canvas = document.createElement("canvas");
    canvas.width = preset.view[0];
    canvas.height = preset.view[1];
    canvas.getContext("2d").drawImage(image, 0, 0);
    const asset = { id: id("asset"), data: canvas.toDataURL("image/png") };
    const w = preset.width;
    const h = w * preset.view[1] / preset.view[0];
    state.assets.push(asset);
    addLayer({ id: id("image"), type: "image", name: preset.name, asset: asset.id, x: (STRIP_W - w) / 2, y: 1260, w, h });
  };
  image.onerror = () => showStatus("That shape could not be added. Try another.", "error");
  image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(source)}`;
}
function duplicateLayer(layer) {
  // A copy reuses the same image file, so only the item count can stop it.
  if (!canAddLayer()) return;
  const copy = { ...layer, id: id(layer.type), x: layer.x + 20, y: layer.y + 20 };
  clamp(copy);
  addLayer(copy);
}
function deleteLayer(layer) {
  state.layers = state.layers.filter((item) => item.id !== layer.id);
  selectedId = null;
  sheetMode = null;
  commit();
  render();
  showStatus(`${layerName(layer)} deleted. Tap undo to bring it back.`);
}
function moveLayer(direction) {
  const index = state.layers.findIndex((layer) => layer.id === selectedId);
  const target = index + direction;
  if (index < 0 || target < 0 || target >= state.layers.length) return;
  [state.layers[index], state.layers[target]] = [state.layers[target], state.layers[index]];
  commit();
  render();
}
function startNewTemplate() {
  state.background = "#ffffff";
  state.assets = [];
  state.layers = defaultLayers();
  templateName = "";
  selectedId = null;
  savedSnapshot = null;
  savedOnce = false;
  nameInvalid = false;
  confirmingReset = false;
  try { localStorage.removeItem(DRAFT_KEY); } catch { /* Storage unavailable. */ }
  resetHistory();
  setSheet(phoneLayout.matches ? null : "design");
  fitStrip(true);
  showStatus("New template started.");
}

/* Images from the phone */

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = reject;
    image.src = src;
  });
}
// Phone photos are often 3-12 MB. The strip prints at 600 px wide, so shrink on
// the phone instead of refusing the file.
async function prepareImage(file) {
  const url = URL.createObjectURL(file);
  try {
    const image = await loadImage(url);
    const type = file.type === "image/png" ? "image/png" : "image/jpeg";
    for (const side of IMAGE_SIDES) {
      const ratio = Math.min(1, side / Math.max(image.naturalWidth, image.naturalHeight));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(image.naturalWidth * ratio));
      canvas.height = Math.max(1, Math.round(image.naturalHeight * ratio));
      canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height);
      const data = canvas.toDataURL(type, 0.9);
      if (data.length * 0.75 <= MAX_IMAGE_BYTES) return { data, width: canvas.width, height: canvas.height };
    }
    throw new Error("too large");
  } finally {
    URL.revokeObjectURL(url);
  }
}
document.getElementById("studio-image").onchange = async (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file || !canAddImage()) return;
  showStatus("Adding image…");
  try {
    const prepared = await prepareImage(file);
    const asset = { id: id("asset"), data: prepared.data };
    const w = 180;
    const h = Math.min(300, Math.max(40, w * prepared.height / prepared.width));
    const layer = { id: id("image"), type: "image", asset: asset.id, x: (STRIP_W - w) / 2, y: 1260, w, h };
    clamp(layer);
    state.assets.push(asset);
    addLayer(layer);
    showStatus("Image added. Drag it into place.");
  } catch {
    showStatus("That file couldn't be used. Choose a photo or a PNG or JPEG image.", "error");
  }
};

/* Saving to the booth */

function showStatus(message, tone = "") {
  clearTimeout(statusTimer);
  status.textContent = message;
  status.className = `studio-status${tone ? ` is-${tone}` : ""}`;
  // Long messages stay up long enough to read.
  statusTimer = setTimeout(() => { status.textContent = ""; }, Math.max(tone === "error" ? 6000 : 3200, message.length * 55));
}
function showBlocker(title, text, retry = false) {
  document.getElementById("blocker-title").textContent = title;
  document.getElementById("blocker-text").textContent = text;
  document.getElementById("blocker-retry").hidden = !retry;
  document.getElementById("studio-blocker").hidden = false;
}
function linkExpired() {
  showBlocker(
    "This Studio link has expired",
    "On the booth, open Templates and tap Create on phone, then scan the new code. Your design stays on this phone.",
  );
}
const OFFLINE = "Can't reach the booth. Check this phone is on the same Wi-Fi as the booth, then try again.";

saveButton.onclick = async () => {
  const name = templateName.trim();
  if (!name) {
    nameInvalid = true;
    setSheet("design");
    document.getElementById("template-name")?.focus();
    return;
  }
  if (!state.layers.length) {
    showStatus("Add at least one item before saving.", "error");
    return;
  }
  saving = true;
  renderChrome();
  try {
    const response = await fetch("/api/studio/templates", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Studio-Token": token },
      body: JSON.stringify({ name, background: state.background, layers: state.layers, assets: usedAssets() }),
    });
    if (response.status === 401) {
      linkExpired();
      return;
    }
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || "The booth couldn't save this template. Try again.");
    savedSnapshot = snapshot();
    savedOnce = true;
    // Keep the design as a draft so a reload can carry on from it; "saved" makes
    // the next save say "Save copy", because each save adds a template to the booth.
    saveDraft();
    showStatus(`“${result.name}” is on the booth. Pick it when you set up an event.`, "success");
  } catch (error) {
    showStatus(error instanceof TypeError ? OFFLINE : error.message, "error");
  } finally {
    saving = false;
    renderChrome();
  }
};

/* Wiring and start-up */

document.getElementById("view-footer").onclick = () => setView("footer");
document.getElementById("view-full").onclick = () => setView("full");
document.getElementById("close-sheet").onclick = () => setSheet(null);
document.getElementById("studio-name").onclick = () => {
  setSheet("design");
  document.getElementById("template-name")?.focus();
};
document.getElementById("blocker-retry").onclick = () => location.reload();
undoButton.onclick = () => restoreHistory(historyIndex - 1);
redoButton.onclick = () => restoreHistory(historyIndex + 1);
document.querySelectorAll("[data-tool]").forEach((button) => {
  button.onclick = () => setSheet(sheetMode === button.dataset.tool && phoneLayout.matches ? null : button.dataset.tool);
});
sheet.onpointerdown = (event) => {
  if (!phoneLayout.matches) return;
  if (!event.target.closest(".sheet-grabber, .sheet-header") || event.target.closest("button, input, select")) return;
  sheetSwipe = { id: event.pointerId, y: event.clientY, distance: 0 };
  sheet.setPointerCapture(event.pointerId);
};
sheet.onpointermove = (event) => {
  if (sheetSwipe?.id !== event.pointerId) return;
  sheetSwipe.distance = Math.max(0, event.clientY - sheetSwipe.y);
  sheet.style.transform = `translateY(${sheetSwipe.distance}px)`;
};
function finishSheetSwipe(event) {
  if (sheetSwipe?.id !== event.pointerId) return;
  const dismiss = sheetSwipe.distance > 70;
  sheetSwipe = null;
  sheet.style.transform = "";
  if (dismiss) setSheet(null);
}
sheet.onpointerup = finishSheetSwipe;
sheet.onpointercancel = finishSheetSwipe;
document.addEventListener("keydown", (event) => {
  if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "z" || event.target.closest("input")) return;
  event.preventDefault();
  restoreHistory(historyIndex + (event.shiftKey ? 1 : -1));
});

async function start() {
  resetHistory();
  sheetMode = phoneLayout.matches ? null : "design";
  render();
  setView("footer");
  if (!token) {
    linkExpired();
    return;
  }
  try {
    const response = await fetch("/api/studio/bootstrap", { headers: { "X-Studio-Token": token } });
    if (response.status === 401) {
      linkExpired();
      return;
    }
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail);
    state.fonts = data.fonts;
    const recovered = restoreDraft();
    resetHistory();
    render();
    fitStrip(true);
    if (recovered && savedOnce) {
      savedSnapshot = snapshot();
      showStatus(`“${templateName}” is already on the booth. Change it to save a copy, or start a new template from Template.`);
    } else if (recovered) {
      showStatus("Your draft is back where you left it.", "success");
    }
    renderChrome();
  } catch {
    showBlocker("Can't reach the booth", OFFLINE, true);
  }
}

new ResizeObserver(() => fitStrip()).observe(stage);
start();
