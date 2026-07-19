/**
 * On-screen keyboard for touchscreen kiosk — right-aligned panel, scrollable form area.
 */

let boothFrame = null;
let panelEl = null;
let keysEl = null;
let activeInput = null;
let shifted = false;
let textMode = "letters";
let layout = "text";
let suppressBlur = false;

const ACTION_KEYS = new Set(["shift", "backspace", "space", "done", "#+=", "abc"]);

const TEXT_ROWS = [
  ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
  ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
  ["a", "s", "d", "f", "g", "h", "j", "k", "l"],
  ["shift", "z", "x", "c", "v", "b", "n", "m", "backspace"],
  ["#+=", "-", "'", "space", ".", "done"],
];

const SYMBOL_ROWS = [
  ["!", "@", "#", "$", "%", "^", "&", "*", "(", ")"],
  ["+", "=", "[", "]", "{", "}", "|", "\\", "/", "?"],
  [",", ";", ":", '"', "~", "`", "_", "<", ">", "backspace"],
  ["abc", "space", "done"],
];

const DATE_ROWS = [
  ["1", "2", "3"],
  ["4", "5", "6"],
  ["7", "8", "9"],
  [".", "0", "/", ":", "backspace"],
  ["done"],
];

function isEditableInput(el) {
  if (!el || el.closest("#osk-panel")) return false;
  return el.matches(
    'input:not([type="hidden"]):not([type="button"]):not([type="submit"]):not([type="checkbox"]):not([type="radio"]), textarea',
  );
}

function layoutForInput(input) {
  // .osk-date is a plain text field that wants the numeric/date key layout (we
  // avoid type=date so the browser's own calendar popup never appears).
  if (input.type === "date" || input.inputMode === "numeric" || input.classList.contains("osk-date")) {
    return "date";
  }
  return "text";
}

function encodeKey(key) {
  if (ACTION_KEYS.has(key)) return key;
  return `c:${encodeURIComponent(key)}`;
}

function decodeKey(key) {
  if (key.startsWith("c:")) return decodeURIComponent(key.slice(2));
  return key;
}

function textRows() {
  return textMode === "symbols" ? SYMBOL_ROWS : TEXT_ROWS;
}

function renderKeys() {
  if (!keysEl) return;
  const rows = layout === "date" ? DATE_ROWS : textRows();
  keysEl.innerHTML = rows
    .map(
      (row) => `
    <div class="osk-row">
      ${row.map((key) => `<button type="button" class="osk-key ${keyClass(key)}" data-key="${encodeKey(key)}">${keyLabel(key)}</button>`).join("")}
    </div>`,
    )
    .join("");
}

function keyClass(key) {
  if (key === "space") return "osk-key-wide";
  if (key === "backspace") return "osk-key-wide";
  if (key === "shift") return `osk-key-wide${shifted ? " is-active" : ""}`;
  if (key === "#+=" || key === "abc") return `osk-key-mode${textMode === "symbols" ? " is-active" : ""}`;
  if (key === "done") return "osk-key-done";
  return "";
}

function keyLabel(key) {
  if (key === "backspace") return "⌫";
  if (key === "space") return "Space";
  if (key === "shift") return "⇧";
  if (key === "#+=") return "#+=";
  if (key === "abc") return "ABC";
  if (key === "done") return "Done";
  if (layout === "text" && textMode === "letters" && shifted && key.length === 1 && /[a-z]/.test(key)) {
    return key.toUpperCase();
  }
  return key;
}

function insertText(text) {
  if (!activeInput) return;
  const start = activeInput.selectionStart ?? activeInput.value.length;
  const end = activeInput.selectionEnd ?? start;
  const value = activeInput.value;
  activeInput.value = value.slice(0, start) + text + value.slice(end);
  const pos = start + text.length;
  activeInput.setSelectionRange(pos, pos);
  activeInput.dispatchEvent(new Event("input", { bubbles: true }));
}

function handleBackspace() {
  if (!activeInput) return;
  const start = activeInput.selectionStart ?? activeInput.value.length;
  const end = activeInput.selectionEnd ?? start;
  if (start === end && start > 0) {
    activeInput.value = activeInput.value.slice(0, start - 1) + activeInput.value.slice(end);
    activeInput.setSelectionRange(start - 1, start - 1);
  } else if (start !== end) {
    activeInput.value = activeInput.value.slice(0, start) + activeInput.value.slice(end);
    activeInput.setSelectionRange(start, start);
  }
  activeInput.dispatchEvent(new Event("input", { bubbles: true }));
}

function handleKey(key) {
  if (!activeInput) return;
  activeInput.focus();

  if (key === "done") {
    closeOnScreenKeyboard();
    return;
  }
  if (key === "backspace") {
    handleBackspace();
    return;
  }
  if (key === "shift") {
    shifted = !shifted;
    renderKeys();
    return;
  }
  if (key === "#+=") {
    textMode = "symbols";
    shifted = false;
    renderKeys();
    return;
  }
  if (key === "abc") {
    textMode = "letters";
    renderKeys();
    return;
  }
  if (key === "space") {
    insertText(" ");
    return;
  }
  if (ACTION_KEYS.has(key)) return;

  let char = key;
  if (layout === "text" && textMode === "letters" && shifted && /[a-z]/.test(char)) {
    char = char.toUpperCase();
    shifted = false;
    renderKeys();
  }
  insertText(char);
}

function isKeyboardOpen() {
  return boothFrame?.classList.contains("osk-open") ?? false;
}

function tapKeepsKeyboard(target) {
  if (!target || !activeInput) return false;
  if (panelEl.contains(target)) return true;
  if (target === activeInput) return true;
  if (target.closest(".password-toggle")) return true;
  if (isEditableInput(target)) return true;
  return false;
}

function clearInputOskState(input) {
  if (!input) return;
  input.removeAttribute("inputmode");
  input.classList.remove("osk-target");
}

function openFor(input) {
  if (activeInput && activeInput !== input) clearInputOskState(activeInput);
  activeInput = input;
  layout = layoutForInput(input);
  shifted = false;
  textMode = "letters";
  // Suppress the native soft keyboard on touch devices; physical keyboards still work.
  input.setAttribute("inputmode", "none");
  input.classList.add("osk-target");
  boothFrame.classList.add("osk-open");
  panelEl.hidden = false;
  renderKeys();
  // Centre the field in the scroll area (which reserves keyboard space via
  // scroll-padding) so a field low on the screen lifts clear of the keyboard.
  // "nearest" wouldn't scroll — the scrollport extends under the keyboard.
  // Reading offsetHeight forces the just-added osk-open layout (the padding that
  // makes the column scrollable) to apply, then we scroll synchronously.
  void input.offsetHeight;
  input.scrollIntoView({ block: "center" });
}

export function closeOnScreenKeyboard() {
  if (!isKeyboardOpen() && !activeInput) return;

  if (activeInput) {
    clearInputOskState(activeInput);
    activeInput.blur();
  }
  activeInput = null;
  shifted = false;
  textMode = "letters";
  boothFrame?.classList.remove("osk-open");
  if (panelEl) panelEl.hidden = true;
}

export function initOnScreenKeyboard() {
  boothFrame = document.getElementById("booth-frame");
  panelEl = document.getElementById("osk-panel");
  keysEl = document.getElementById("osk-keys");
  if (!boothFrame || !panelEl || !keysEl) return;

  panelEl.hidden = true;
  boothFrame.classList.remove("osk-open");

  panelEl.addEventListener("pointerdown", (e) => {
    suppressBlur = true;
    e.preventDefault();
  });
  panelEl.addEventListener("pointerup", () => {
    suppressBlur = false;
  });

  keysEl.addEventListener("click", (e) => {
    const btn = e.target.closest(".osk-key");
    if (!btn) return;
    handleKey(decodeKey(btn.getAttribute("data-key") || ""));
  });

  const dismissIfOutside = (e) => {
    if (!isKeyboardOpen()) return;
    if (tapKeepsKeyboard(e.target)) return;
    closeOnScreenKeyboard();
  };

  document.getElementById("app")?.addEventListener("pointerdown", dismissIfOutside, true);
  boothFrame.addEventListener("pointerdown", dismissIfOutside, true);

  boothFrame.addEventListener(
    "focusin",
    (e) => {
      if (isEditableInput(e.target)) {
        if (e.target !== activeInput) openFor(e.target);
        return;
      }
      if (activeInput) closeOnScreenKeyboard();
    },
    true,
  );

  boothFrame.addEventListener(
    "focusout",
    (e) => {
      if (!activeInput || e.target !== activeInput) return;
      setTimeout(() => {
        if (suppressBlur) {
          activeInput?.focus();
          return;
        }
        if (document.activeElement === activeInput) return;
        if (panelEl.contains(document.activeElement)) return;
        if (isEditableInput(document.activeElement)) return;
        closeOnScreenKeyboard();
      }, 0);
    },
    true,
  );

  boothFrame.addEventListener(
    "keydown",
    (e) => {
      if (!isKeyboardOpen() || !activeInput || e.target !== activeInput) return;
      if (e.key === "Escape") {
        e.preventDefault();
        closeOnScreenKeyboard();
      }
    },
    true,
  );
}
