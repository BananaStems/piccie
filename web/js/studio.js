const tokenFromLink = new URL(location.href).hash.match(/(?:^#|&)token=([^&]+)/)?.[1] || "";
if (tokenFromLink) {
  sessionStorage.setItem("piccie-studio-token", tokenFromLink);
  history.replaceState(null, "", location.pathname);
}
const token = tokenFromLink || sessionStorage.getItem("piccie-studio-token") || "";

const DRAFT_KEY = "piccie-template-draft-v1";
const stage = document.getElementById("strip-stage");
const shell = document.getElementById("strip-shell");
const strip = document.getElementById("studio-strip");
const layerRoot = document.getElementById("studio-layers");
const sheet = document.getElementById("studio-sheet");
const sheetTitle = document.getElementById("sheet-title");
const sheetKicker = document.getElementById("sheet-kicker");
const sheetContent = document.getElementById("sheet-content");
const status = document.getElementById("studio-status");
const nameDisplay = document.getElementById("studio-name-display");
const undoButton = document.getElementById("undo-edit");
const redoButton = document.getElementById("redo-edit");
const fontLinks = new Set();
const pointers = new Map();
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

let scale = 0.25;
let fitScale = scale;
let viewMode = "footer";
let sheetMode = null;
let selectedId = null;
let templateName = "";
let counter = 0;
let gesture = null;
let pan = null;
let lastTapId = null;
let lastTapAt = 0;
let sheetSwipe = null;
let statusTimer = null;
let historyStates = [];
let historyIndex = 0;

const state = {
  background: "#ffffff",
  fonts: [],
  assets: [],
  layers: [
    textLayer("line1", 55, 1372, 490, 84, 62, "playfair-display", "#29231e"),
    textLayer("line2", 55, 1470, 490, 68, 36, "sans", "#756c63"),
    textLayer("date", 160, 1590, 280, 52, 28, "sans", "#29231e"),
  ],
};

function id(prefix) { counter += 1; return `${prefix}-${counter}`; }
function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}
function textLayer(source, x, y, w, h, fontSize = 48, font = "sans", fill = "#29231e") {
  return { id: id(source), type: "text", source, x, y, w, h, font_size: fontSize, font, fill, align: "center", uppercase: source === "line1" };
}
function sampleText(layer) {
  return { line1: "YOUR EVENT", line2: "CELEBRATION", date: "01/08/26" }[layer.source] || "TEXT";
}
function layerName(layer) {
  if (layer.type === "text") return { line1: "Heading", line2: "Subheading", date: "Date" }[layer.source] || "Text";
  return layer.name || (layer.type === "image" ? "Image" : "Shape");
}
function selected() { return state.layers.find((layer) => layer.id === selectedId); }
function fontName(fontId) {
  if (fontId === "sans") return "Outfit";
  if (fontId === "serif") return "Georgia";
  return state.fonts.find((font) => font.id === fontId)?.name || "Outfit";
}
function loadFont(fontId) {
  const font = state.fonts.find((item) => item.id === fontId);
  if (!font || !font.file || fontLinks.has(fontId)) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = `https://fonts.googleapis.com/css2?family=${encodeURIComponent(font.name).replace(/%20/g, "+")}&display=swap`;
  document.head.appendChild(link);
  fontLinks.add(fontId);
}
function loadFontPreviews() {
  if (fontLinks.has("all")) return;
  const families = state.fonts.filter((font) => font.file)
    .map((font) => `family=${encodeURIComponent(font.name).replace(/%20/g, "+")}`)
    .join("&");
  if (!families) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = `https://fonts.googleapis.com/css2?${families}&display=swap`;
  document.head.appendChild(link);
  fontLinks.add("all");
}

function snapshot() {
  return JSON.stringify({ background: state.background, assets: state.assets, layers: state.layers });
}
function resetHistory() {
  historyStates = [snapshot()];
  historyIndex = 0;
  updateHistoryButtons();
}
function commit() {
  const next = snapshot();
  if (next === historyStates[historyIndex]) return;
  historyStates = historyStates.slice(0, historyIndex + 1);
  historyStates.push(next);
  if (historyStates.length > 30) historyStates.shift();
  historyIndex = historyStates.length - 1;
  updateHistoryButtons();
  saveDraft();
}
function restoreHistory(index) {
  if (index < 0 || index >= historyStates.length) return;
  historyIndex = index;
  const restored = JSON.parse(historyStates[historyIndex]);
  state.background = restored.background;
  state.assets = restored.assets;
  state.layers = restored.layers;
  if (!selected()) selectedId = null;
  renderLayers();
  updateHistoryButtons();
  saveDraft();
}
function updateHistoryButtons() {
  undoButton.disabled = historyIndex <= 0;
  redoButton.disabled = historyIndex >= historyStates.length - 1;
}
function saveDraft() {
  try {
    localStorage.setItem(DRAFT_KEY, JSON.stringify({ version: 1, name: templateName, design: JSON.parse(snapshot()) }));
  } catch { /* Storage can be unavailable in private browsing. */ }
}
function restoreDraft() {
  try {
    const draft = JSON.parse(localStorage.getItem(DRAFT_KEY));
    if (draft?.version !== 1 || !Array.isArray(draft.design?.layers)) return false;
    templateName = draft.name === "Untitled template" ? "" : (draft.name || "");
    state.background = draft.design.background || "#ffffff";
    state.assets = Array.isArray(draft.design.assets) ? draft.design.assets : [];
    state.layers = draft.design.layers;
    nameDisplay.textContent = templateName || "Untitled template";
    return true;
  } catch { return false; }
}

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
    ? Math.min(1, Math.max(120, available.width) / 600)
    : Math.min(1, Math.max(120, available.width) / 600, Math.max(300, available.height) / 1800);
  const wasFitted = reset || scale <= fitScale + 0.001;
  fitScale = nextFit;
  scale = wasFitted ? fitScale : Math.max(fitScale, Math.min(1, scale));
  sizeStrip();
  if (wasFitted) alignFittedView();
}
function sizeStrip() {
  shell.style.width = `${600 * scale}px`;
  shell.style.height = `${1800 * scale}px`;
  strip.style.transform = `scale(${scale})`;
}
function alignFittedView() {
  requestAnimationFrame(() => {
    stage.scrollLeft = 0;
    stage.scrollTop = viewMode === "footer" ? stage.scrollHeight : 0;
  });
}
function setView(mode) {
  viewMode = mode;
  document.getElementById("view-footer").classList.toggle("is-active", mode === "footer");
  document.getElementById("view-full").classList.toggle("is-active", mode === "full");
  fitStrip(true);
}
function pointDistance([a, b]) { return Math.hypot(a.x - b.x, a.y - b.y); }
function pointCentre([a, b]) { return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }; }

stage.onpointerdown = (event) => {
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  if (!event.target.closest(".studio-layer")) {
    stage.setPointerCapture(event.pointerId);
    pan = { id: event.pointerId, x: event.clientX, y: event.clientY, left: stage.scrollLeft, top: stage.scrollTop };
  }
  if (pointers.size === 2) {
    const pair = [...pointers.values()];
    const centre = pointCentre(pair);
    const rect = shell.getBoundingClientRect();
    gesture = {
      distance: pointDistance(pair),
      scale,
      x: (centre.x - rect.left) / scale,
      y: (centre.y - rect.top) / scale,
    };
    pan = null;
  }
};
stage.onpointermove = (event) => {
  if (!pointers.has(event.pointerId)) return;
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  if (gesture && pointers.size >= 2) {
    const pair = [...pointers.values()].slice(0, 2);
    const centre = pointCentre(pair);
    scale = Math.max(fitScale, Math.min(1, gesture.scale * pointDistance(pair) / gesture.distance));
    sizeStrip();
    if (scale === fitScale) alignFittedView();
    else {
      const rect = shell.getBoundingClientRect();
      stage.scrollLeft += rect.left + gesture.x * scale - centre.x;
      stage.scrollTop += rect.top + gesture.y * scale - centre.y;
    }
  } else if (pan?.id === event.pointerId && scale > fitScale) {
    stage.scrollLeft = pan.left - (event.clientX - pan.x);
    stage.scrollTop = pan.top - (event.clientY - pan.y);
  }
};
function releasePointer(event) {
  pointers.delete(event.pointerId);
  if (pointers.size < 2) gesture = null;
  if (pan?.id === event.pointerId) pan = null;
}
stage.onpointerup = releasePointer;
stage.onpointercancel = releasePointer;

function layerStyle(layer) {
  return `left:${layer.x}px;top:${layer.y}px;width:${layer.w}px;height:${layer.h}px`;
}
function renderLayers(refreshSheet = true) {
  strip.style.background = state.background;
  layerRoot.innerHTML = state.layers.map((layer) => {
    const selectedClass = layer.id === selectedId ? " is-selected" : "";
    const resizeHandle = selectedClass ? '<span class="layer-resize-handle" aria-hidden="true">↘</span>' : "";
    if (layer.type === "text") {
      loadFont(layer.font);
      const justify = { left: "flex-start", right: "flex-end" }[layer.align] || "center";
      return `<button type="button" class="studio-layer studio-layer-text${selectedClass}" data-layer="${escapeHtml(layer.id)}" style="${layerStyle(layer)};font-family:'${escapeHtml(fontName(layer.font))}',sans-serif;font-size:${layer.font_size}px;color:${layer.fill};justify-content:${justify};text-transform:${layer.uppercase ? "uppercase" : "none"}">${sampleText(layer)}${resizeHandle}</button>`;
    }
    if (layer.type === "image") {
      const asset = state.assets.find((item) => item.id === layer.asset);
      return `<button type="button" class="studio-layer studio-layer-image${selectedClass}" data-layer="${escapeHtml(layer.id)}" style="${layerStyle(layer)}"><img src="${asset?.data || ""}" alt="${escapeHtml(layerName(layer))}" />${resizeHandle}</button>`;
    }
    return `<button type="button" class="studio-layer studio-layer-shape${selectedClass}" data-layer="${escapeHtml(layer.id)}" style="${layerStyle(layer)};background:${layer.fill};border-radius:${layer.radius}px" aria-label="${escapeHtml(layerName(layer))}">${resizeHandle}</button>`;
  }).join("");
  bindDragging();
  if (refreshSheet) renderSheet();
}
function clamp(layer) {
  layer.w = Math.min(600, Math.max(8, layer.w));
  layer.h = Math.min(580, Math.max(8, layer.h));
  layer.x = Math.min(600 - layer.w, Math.max(0, layer.x));
  const top = layer.type === "image" ? 1220 : 1320;
  layer.y = Math.min(1800 - layer.h, Math.max(top, layer.y));
}
function snap(value, targets, tolerance) {
  const target = targets.find((item) => Math.abs(item - value) <= tolerance);
  return target ?? value;
}
function bindDragging() {
  layerRoot.querySelectorAll(".studio-layer").forEach((element) => {
    element.onpointerdown = (event) => {
      event.preventDefault();
      selectedId = element.dataset.layer;
      const layer = selected();
      const resizing = Boolean(event.target.closest(".layer-resize-handle"));
      const start = {
        x: event.clientX,
        y: event.clientY,
        left: layer.x,
        top: layer.y,
        w: layer.w,
        h: layer.h,
        fontSize: layer.font_size,
      };
      let cancelled = false;
      let moved = false;
      element.setPointerCapture(event.pointerId);
      element.onpointermove = (move) => {
        if (pointers.size > 1) cancelled = true;
        if (cancelled) return;
        if (resizing) {
          const widthRatio = (start.w + (move.clientX - start.x) / scale) / start.w;
          const heightRatio = (start.h + (move.clientY - start.y) / scale) / start.h;
          const minimum = Math.max(24 / start.w, 16 / start.h, layer.type === "text" ? 12 / start.fontSize : 0);
          const maximum = Math.min(
            (600 - start.left) / start.w,
            (1800 - start.top) / start.h,
            580 / start.h,
            layer.type === "text" ? 180 / start.fontSize : Infinity,
          );
          const factor = Math.max(minimum, Math.min(maximum, Math.max(widthRatio, heightRatio)));
          layer.w = start.w * factor;
          layer.h = start.h * factor;
          if (layer.type === "text") layer.font_size = start.fontSize * factor;
          moved = moved || Math.abs(factor - 1) > 0.01;
          element.style.width = `${layer.w}px`;
          element.style.height = `${layer.h}px`;
          if (layer.type === "text") element.style.fontSize = `${layer.font_size}px`;
          return;
        }
        let x = start.left + (move.clientX - start.x) / scale;
        let y = start.top + (move.clientY - start.y) / scale;
        const tolerance = 10 / scale;
        x = snap(x, [0, (600 - layer.w) / 2, 600 - layer.w], tolerance);
        y = snap(y, [layer.type === "image" ? 1220 : 1320, 1320, 1800 - layer.h], tolerance);
        layer.x = x;
        layer.y = y;
        clamp(layer);
        moved = moved || layer.x !== start.left || layer.y !== start.top;
        element.style.left = `${layer.x}px`;
        element.style.top = `${layer.y}px`;
      };
      element.onpointerup = () => {
        element.onpointermove = null;
        if (resizing) {
          lastTapId = null;
          if (moved && !cancelled) commit();
        } else if (moved && !cancelled) {
          lastTapId = null;
          commit();
        } else if (!cancelled) {
          const now = Date.now();
          const doubleTapped = lastTapId === selectedId && now - lastTapAt < 350;
          lastTapId = doubleTapped ? null : selectedId;
          lastTapAt = now;
          if (doubleTapped) setSheet("edit");
          else if (sheetMode === "edit") setSheet(null);
        } else lastTapId = null;
        renderLayers();
      };
    };
  });
}

function control(label, html, wide = false) {
  return `<label class="control-row${wide ? " wide" : ""}"><span>${label}</span>${html}</label>`;
}
function setSheet(mode) {
  sheetMode = mode;
  sheet.classList.toggle("is-open", Boolean(mode));
  const activeTool = mode === "shapes" ? "shape" : mode;
  document.querySelectorAll("[data-tool]").forEach((button) => button.classList.toggle("is-active", button.dataset.tool === activeTool));
  renderSheet();
}
function renderSheet() {
  if (sheetMode === "edit" && !selected()) sheetMode = "layers";
  const headings = {
    edit: ["Selected", selected() ? layerName(selected()) : "Element"],
    text: ["Add", "Text"],
    shapes: ["Add", "Shapes"],
    design: ["Template", "Design"],
    layers: ["Arrange", "Layers"],
  };
  const [kicker, title] = headings[sheetMode] || ["Template", "Tools"];
  sheetKicker.textContent = kicker;
  sheetTitle.textContent = title;
  if (!sheetMode) {
    sheetContent.innerHTML = '<p class="empty-controls">Select an element or choose a tool.</p>';
    return;
  }
  if (sheetMode === "text") renderTextSheet();
  if (sheetMode === "shapes") renderShapesSheet();
  if (sheetMode === "design") renderDesignSheet();
  if (sheetMode === "layers") renderLayersSheet();
  if (sheetMode === "edit") renderEditSheet();
}
function renderTextSheet() {
  sheetContent.innerHTML = `<div class="text-choices">
    <button class="text-choice" type="button" data-add="line1">Heading <span>Event name</span></button>
    <button class="text-choice" type="button" data-add="line2">Subheading <span>Event detail</span></button>
    <button class="text-choice" type="button" data-add="date">Date <span>Event date</span></button>
  </div>`;
  sheetContent.querySelectorAll("[data-add]").forEach((button) => { button.onclick = () => add(button.dataset.add); });
}
function renderShapesSheet() {
  sheetContent.innerHTML = `<div class="shape-grid">
    <button class="shape-preset" type="button" data-basic-shape="circle"><span><i class="shape-circle"></i></span><strong>Circle</strong></button>
    <button class="shape-preset" type="button" data-basic-shape="rectangle"><span><i class="shape-rectangle"></i></span><strong>Label</strong></button>
    ${GRAPHIC_PRESETS.map((preset) => `<button class="shape-preset" type="button" data-graphic="${preset.id}"><span><svg viewBox="0 0 ${preset.view[0]} ${preset.view[1]}" aria-hidden="true">${preset.body}</svg></span><strong>${preset.name}</strong></button>`).join("")}
  </div>`;
  sheetContent.querySelectorAll("[data-basic-shape]").forEach((button) => {
    button.onclick = () => addBasicShape(button.dataset.basicShape);
  });
  sheetContent.querySelectorAll("[data-graphic]").forEach((button) => {
    button.onclick = () => addGraphicPreset(button.dataset.graphic);
  });
}
function renderDesignSheet() {
  sheetContent.innerHTML = `<div class="design-grid">
    ${control("Template name", `<input id="template-name" maxlength="80" value="${escapeHtml(templateName)}" placeholder="Untitled template">`, true)}
    ${control("Footer", `<input id="footer-color" type="color" value="${state.background}">`)}
  </div>`;
  const nameInput = document.getElementById("template-name");
  const colourInput = document.getElementById("footer-color");
  nameInput.oninput = () => {
    templateName = nameInput.value;
    nameDisplay.textContent = templateName || "Untitled template";
    saveDraft();
  };
  colourInput.oninput = () => { state.background = colourInput.value; strip.style.background = state.background; };
  colourInput.onchange = () => { commit(); renderLayers(); };
}
function renderLayersSheet() {
  sheetContent.innerHTML = `<div class="layer-list">${[...state.layers].reverse().map((layer) => `
    <button class="layer-item${layer.id === selectedId ? " is-selected" : ""}" type="button" data-select="${escapeHtml(layer.id)}"><span>${layerName(layer)}</span><small>${layer.type}</small></button>`).join("")}</div>
    <div class="control-actions layer-order"><button id="layer-down" type="button"${selected() ? "" : " disabled"}>Move down</button><button id="layer-up" type="button"${selected() ? "" : " disabled"}>Move up</button></div>`;
  sheetContent.querySelectorAll("[data-select]").forEach((button) => {
    button.onclick = () => { selectedId = button.dataset.select; setSheet("edit"); renderLayers(); };
  });
  document.getElementById("layer-down").onclick = () => moveLayer(-1);
  document.getElementById("layer-up").onclick = () => moveLayer(1);
}
function renderEditSheet() {
  const layer = selected();
  if (!layer) return;
  let fields = "";
  let fontChoices = "";
  if (layer.type === "text") {
    loadFontPreviews();
    fontChoices = `<div class="font-browser" aria-label="Fonts">${state.fonts.map((font) => `<button class="font-option${font.id === layer.font ? " is-selected" : ""}" type="button" data-font="${escapeHtml(font.id)}" style="font-family:'${escapeHtml(fontName(font.id))}',sans-serif"><strong>Ag</strong><span>${escapeHtml(font.name)}</span></button>`).join("")}</div>`;
    fields += control("Colour", `<input type="color" value="${layer.fill}" data-prop="fill">`);
    fields += control("Align", `<select data-prop="align"><option${layer.align === "left" ? " selected" : ""}>left</option><option${layer.align === "center" ? " selected" : ""}>center</option><option${layer.align === "right" ? " selected" : ""}>right</option></select>`);
    fields += control("Uppercase", `<select data-prop="uppercase"><option value="false"${!layer.uppercase ? " selected" : ""}>No</option><option value="true"${layer.uppercase ? " selected" : ""}>Yes</option></select>`);
  } else if (layer.type === "shape") {
    fields += control("Colour", `<input type="color" value="${layer.fill}" data-prop="fill">`);
    fields += control("Corners", `<input type="range" min="0" max="100" value="${layer.radius}" data-prop="radius"><span class="control-value">${Math.round(layer.radius)} px</span>`);
  }
  if (layer.type === "shape") {
    fields += control("Width", `<input type="range" min="24" max="600" value="${layer.w}" data-prop="w"><span class="control-value">${Math.round(layer.w)} px</span>`);
    fields += control("Height", `<input type="range" min="16" max="480" value="${layer.h}" data-prop="h"><span class="control-value">${Math.round(layer.h)} px</span>`);
  }
  sheetContent.innerHTML = `${fontChoices}<p class="direct-edit-hint">Drag the corner handle to resize.</p><div class="control-grid">${fields}</div><div class="control-actions"><button id="duplicate-layer" type="button">Duplicate</button><button class="delete-layer" id="delete-layer" type="button">Delete</button></div>`;
  sheetContent.querySelectorAll("[data-font]").forEach((button) => {
    button.onclick = () => {
      layer.font = button.dataset.font;
      commit();
      renderLayers();
    };
  });
  sheetContent.querySelectorAll("[data-prop]").forEach((input) => {
    input.onchange = () => {
      const prop = input.dataset.prop;
      let value = input.value;
      if (["font_size", "radius", "w", "h"].includes(prop)) value = Number(value);
      if (prop === "uppercase") value = value === "true";
      layer[prop] = value;
      clamp(layer);
      commit();
      renderLayers();
    };
  });
  document.getElementById("duplicate-layer").onclick = () => {
    const copy = { ...layer, id: id(layer.type), x: layer.x + 20, y: layer.y + 20 };
    clamp(copy);
    state.layers.push(copy);
    selectedId = copy.id;
    commit();
    renderLayers();
  };
  document.getElementById("delete-layer").onclick = () => {
    state.layers = state.layers.filter((item) => item.id !== layer.id);
    selectedId = null;
    sheetMode = "layers";
    commit();
    renderLayers();
  };
}

function add(kind) {
  if (["line1", "line2", "date"].includes(kind)) {
    const existing = state.layers.find((layer) => layer.type === "text" && layer.source === kind);
    if (existing) {
      selectedId = existing.id;
      setSheet("edit");
      renderLayers();
      return;
    }
    const layer = textLayer(kind, 60, 1400, 480, 72);
    state.layers.push(layer);
    selectedId = layer.id;
  }
  commit();
  setSheet("edit");
  renderLayers();
}
function addBasicShape(kind) {
  const circle = kind === "circle";
  const layer = {
    id: id("shape"),
    type: "shape",
    name: circle ? "Circle" : "Label",
    x: circle ? 225 : 150,
    y: 1450,
    w: circle ? 150 : 300,
    h: circle ? 150 : 90,
    fill: "#c45c4a",
    radius: circle ? 100 : 18,
  };
  state.layers.push(layer);
  selectedId = layer.id;
  commit();
  setSheet(null);
  renderLayers();
}
function addGraphicPreset(presetId) {
  const preset = GRAPHIC_PRESETS.find((item) => item.id === presetId);
  if (!preset) return;
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
    const layer = { id: id("image"), type: "image", name: preset.name, asset: asset.id, x: (600 - w) / 2, y: 1260, w, h };
    state.assets.push(asset);
    state.layers.push(layer);
    selectedId = layer.id;
    commit();
    setSheet(null);
    renderLayers();
  };
  image.onerror = () => showStatus("Could not add that shape.", true);
  image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(source)}`;
}
function moveLayer(direction) {
  const index = state.layers.findIndex((layer) => layer.id === selectedId);
  const target = index + direction;
  if (index < 0 || target < 0 || target >= state.layers.length) return;
  [state.layers[index], state.layers[target]] = [state.layers[target], state.layers[index]];
  commit();
  renderLayers();
}
function showStatus(message, error = false, success = false) {
  clearTimeout(statusTimer);
  status.textContent = message;
  status.className = `studio-status${error ? " is-error" : ""}${success ? " is-success" : ""}`;
  if (!error) statusTimer = setTimeout(() => { status.textContent = ""; }, 3200);
}

document.getElementById("view-footer").onclick = () => setView("footer");
document.getElementById("view-full").onclick = () => setView("full");
document.getElementById("close-sheet").onclick = () => setSheet(null);
sheet.onpointerdown = (event) => {
  if (!matchMedia("(max-width: 760px)").matches) return;
  if (!event.target.closest(".sheet-grabber, .sheet-header") || event.target.closest("button, input, select")) return;
  sheetSwipe = { id: event.pointerId, y: event.clientY, distance: 0 };
  sheet.setPointerCapture(event.pointerId);
  sheet.style.transition = "none";
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
  sheet.style.transition = "";
  sheet.style.transform = "";
  if (dismiss) setSheet(null);
}
sheet.onpointerup = finishSheetSwipe;
sheet.onpointercancel = finishSheetSwipe;
undoButton.onclick = () => restoreHistory(historyIndex - 1);
redoButton.onclick = () => restoreHistory(historyIndex + 1);
document.querySelectorAll("[data-tool]").forEach((button) => {
  button.onclick = () => setSheet(button.dataset.tool === "shape" ? "shapes" : button.dataset.tool);
});
document.getElementById("studio-image").onchange = (event) => {
  const file = event.target.files[0];
  if (!file || !["image/png", "image/jpeg"].includes(file.type) || file.size > 3 * 1024 * 1024) {
    showStatus("Choose a PNG or JPEG smaller than 3 MB.", true);
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    const asset = { id: id("asset"), data: reader.result };
    state.assets.push(asset);
    const image = new Image();
    image.onload = () => {
      const w = 180;
      const h = Math.min(300, Math.max(40, w * image.height / image.width));
      const layer = { id: id("image"), type: "image", asset: asset.id, x: (600 - w) / 2, y: 1260, w, h };
      clamp(layer);
      state.layers.push(layer);
      selectedId = layer.id;
      commit();
      setSheet("edit");
      renderLayers();
    };
    image.src = reader.result;
  };
  reader.readAsDataURL(file);
  event.target.value = "";
};

document.getElementById("install-template").onclick = async (event) => {
  const name = templateName.trim();
  if (!name) {
    setSheet("design");
    showStatus("Name the template before saving.", true);
    return;
  }
  if (!state.layers.length) {
    showStatus("Add at least one element before saving.", true);
    return;
  }
  const button = event.currentTarget;
  button.disabled = true;
  showStatus("Saving to booth…");
  try {
    const response = await fetch("/api/studio/templates", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Studio-Token": token },
      body: JSON.stringify({ name, background: state.background, layers: state.layers, assets: state.assets }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not save template");
    localStorage.removeItem(DRAFT_KEY);
    showStatus(`${result.name} is ready to use.`, false, true);
  } catch (error) {
    showStatus(error.message, true);
  } finally {
    button.disabled = false;
  }
};

async function start() {
  renderLayers(false);
  resetHistory();
  setView("footer");
  setSheet(matchMedia("(min-width: 761px)").matches ? "design" : null);
  if (!token) {
    showStatus("This Studio link is invalid. Create a new one on the booth.", true);
    return;
  }
  try {
    const response = await fetch("/api/studio/bootstrap", { headers: { "X-Studio-Token": token } });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail);
    state.fonts = data.fonts;
    const recovered = restoreDraft();
    resetHistory();
    renderLayers();
    fitStrip(true);
    if (recovered) showStatus("Draft restored.", false, true);
  } catch (error) {
    showStatus(error.message || "Could not connect to the booth.", true);
  }
}

new ResizeObserver(() => fitStrip()).observe(stage);
start();
