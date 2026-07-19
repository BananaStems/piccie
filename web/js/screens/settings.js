const PHOTO_LOOKS = [
  ["clean", "Clean"],
  ["soft", "Soft"],
  ["warm", "Warm"],
  ["mono", "Mono"],
  ["bold", "Bold"],
];

const PREVIEW_FREEZE_MS = 700;
let pendingPatch = {};
let settingsTimer = null;
let lastInteraction = 0;

function titleCaseOption(value) {
  return String(value).replace(/_/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatValue(key, value) {
  const number = Number(value);
  if (key === "filter_strength") return `${Math.round(number * 100)}%`;
  if (key === "exposure_value") return `${number >= 0 ? "+" : ""}${number.toFixed(1)}`;
  return number.toFixed(1);
}

function slider({ id, label, key, value, min, max, step = 0.1, rowId = "", hidden = false }) {
  return `<div class="set-row set-slider${hidden ? " hidden" : ""}"${rowId ? ` id="${rowId}"` : ""}>
    <span class="set-label">${label}</span>
    <span class="set-control">
      <button type="button" class="set-step" data-target="${id}" data-delta="-${step}" aria-label="Decrease ${label}">−</button>
      <input type="range" id="${id}" data-key="${key}" min="${min}" max="${max}" step="${step}" value="${value}" />
      <button type="button" class="set-step" data-target="${id}" data-delta="${step}" aria-label="Increase ${label}">+</button>
      <output id="${id}-out" class="set-val">${formatValue(key, value)}</output>
    </span>
  </div>`;
}

function toggle({ id, label, key, checked }) {
  return `<label class="set-row set-toggle">
    <span class="set-label">${label}</span>
    <input type="checkbox" id="${id}" data-key="${key}" ${checked ? "checked" : ""} />
    <span class="set-switch" aria-hidden="true"></span>
  </label>`;
}

function select({ id, label, key, value, options }) {
  return `<label class="set-row set-select">
    <span class="set-label">${label}</span>
    <select id="${id}" data-key="${key}">
      ${options.map((option) => `<option value="${option}"${option === value ? " selected" : ""}>${titleCaseOption(option)}</option>`).join("")}
    </select>
  </label>`;
}

function group(title, rows) {
  return `<section class="set-group"><h3 class="set-group-title">${title}</h3>${rows.join("")}</section>`;
}

function lookCards(selected) {
  return `<div class="look-grid">${PHOTO_LOOKS.map(([name, label]) => `
    <button class="look-card${name === selected ? " active" : ""}" type="button" data-look="${name}" aria-pressed="${name === selected}">${label}</button>`).join("")}</div>`;
}

function startPreview() {
  const canvas = document.getElementById("settings-preview");
  if (!canvas?.getContext) return;
  const context = canvas.getContext("2d");
  const interacting = () => Date.now() - lastInteraction < PREVIEW_FREEZE_MS;

  const drawCover = (bitmap) => {
    const width = canvas.clientWidth || 320;
    const height = canvas.clientHeight || 240;
    if (canvas.width !== width) canvas.width = width;
    if (canvas.height !== height) canvas.height = height;
    const scale = Math.max(width / bitmap.width, height / bitmap.height);
    const drawnWidth = bitmap.width * scale;
    const drawnHeight = bitmap.height * scale;
    context.drawImage(bitmap, (width - drawnWidth) / 2, (height - drawnHeight) / 2, drawnWidth, drawnHeight);
  };

  const poll = () => {
    if (document.getElementById("settings-preview") !== canvas) return;
    if (interacting()) {
      setTimeout(poll, 200);
      return;
    }
    const next = new Image();
    next.onload = () => {
      if (document.getElementById("settings-preview") !== canvas) return;
      if (!interacting()) {
        try {
          drawCover(next);
        } catch (_) {
          // A transient sizing race is harmless; the next poll redraws.
        }
      }
      setTimeout(poll, 160);
    };
    next.onerror = () => {
      if (document.getElementById("settings-preview") === canvas) setTimeout(poll, 500);
    };
    next.src = `/api/camera/frame?t=${Date.now()}`;
  };
  poll();
}

export async function renderSettingsScreen({ app, state, render, api, escapeHtml, showConfirm }) {
  const queueUpdate = (key, value) => {
    lastInteraction = Date.now();
    pendingPatch[key] = value;
    if (state.cameraSettings) state.cameraSettings[key] = value;
    clearTimeout(settingsTimer);
    settingsTimer = setTimeout(async () => {
      const patch = pendingPatch;
      pendingPatch = {};
      if (!Object.keys(patch).length) return;
      try {
        await api.updateCameraSettings(patch);
      } catch (error) {
        console.warn("Camera settings update failed:", error.message);
      }
    }, 140);
  };

  app.innerHTML = `<div class="screen centered"><div class="spinner"></div></div>`;
  let data;
  try {
    data = await api.getCameraSettings();
  } catch (error) {
    app.innerHTML = `
      <div class="screen admin-page settings-screen has-bottom-bar">
        <div class="admin-topbar"><h2 class="admin-section-title">Settings</h2></div>
        <p class="error-text">${escapeHtml(error.message)}</p>
        <nav class="bottom-bar" aria-label="Settings actions">
          <button class="btn btn-secondary" type="button" id="settings-back">Back</button>
        </nav>
      </div>`;
    document.getElementById("settings-back").onclick = () => {
      state.view = "admin";
      render();
    };
    return;
  }
  const performance = await api.getPerformanceSettings().catch((error) => ({ error: error.message }));

  const settings = data.settings;
  const options = data.options || {};
  state.cameraSettings = settings;
  const cameraAvailable = data.camera_available !== false;
  const performanceDevices = performance.devices || [];
  const selectedDevice = performance.selected_device || "pi4";
  const selectedMode = performance.mode === "performance" ? "performance" : "standard";
  const detectedOption = performanceDevices.find((device) => device.id === performance.detected_device);
  const detectedLabel = detectedOption
    ? `${detectedOption.label}${performance.detected_memory_gb ? ` · ${performance.detected_memory_gb} GB` : ""}`
    : "No supported Raspberry Pi detected";
  const performancePanel = performance.error
    ? `<p class="error-text">${escapeHtml(performance.error)}</p>`
    : `<div class="performance-panel" data-detected-device="${escapeHtml(performance.detected_device || "")}" data-current-device="${escapeHtml(selectedDevice)}" data-current-mode="${selectedMode}" data-can-apply="${performance.can_apply ? "true" : "false"}">
        <label class="set-row set-select">
          <span class="set-label">Device</span>
          <select id="performance-device">
            ${performanceDevices.map((device) => `<option value="${escapeHtml(device.id)}" data-performance-available="${device.performance_available ? "true" : "false"}" data-detail="${escapeHtml(device.performance_detail)}"${device.id === selectedDevice ? " selected" : ""}>${escapeHtml(device.label)}</option>`).join("")}
          </select>
        </label>
        <p class="performance-detected">Detected: ${escapeHtml(detectedLabel)}</p>
        <div class="performance-options" role="group" aria-label="Performance mode">
          <button type="button" class="performance-option${selectedMode === "standard" ? " active" : ""}" data-performance-mode="standard" aria-pressed="${selectedMode === "standard"}">Standard</button>
          <button type="button" class="performance-option${selectedMode === "performance" ? " active" : ""}" data-performance-mode="performance" aria-pressed="${selectedMode === "performance"}">Performance</button>
        </div>
        <p class="performance-detail" id="performance-detail"></p>
        <div class="performance-warning" id="performance-warning">
          <strong>Overclocking can reduce stability.</strong>
          <span>Use active cooling and a reliable power supply. Run Piccie for at least one hour and complete several test sessions before using it at an event.</span>
          <label><input type="checkbox" id="performance-ack" /> I understand that performance mode can cause overheating, crashes or data loss.</label>
        </div>
        <p class="performance-status" id="performance-status"></p>
        <button type="button" class="btn performance-apply" id="performance-apply">Apply & restart</button>
      </div>`;
  const groups = [
    group("Photo", [
      lookCards(settings.filter_name),
      slider({ id: "set-filter-strength", label: "Strength", key: "filter_strength", value: settings.filter_strength, min: 0, max: 1, step: 0.05 }),
    ]),
    group("Camera", [
      slider({ id: "set-ev", label: "Light", key: "exposure_value", value: settings.exposure_value, min: -2, max: 2, step: 0.1 }),
      select({ id: "set-awb", label: "White balance", key: "awb_mode", value: settings.awb_mode, options: options.awb_mode || ["auto", "indoor", "daylight"] }),
    ]),
    group("Focus", [
      toggle({ id: "set-af", label: "Continuous autofocus", key: "af_continuous", checked: settings.af_continuous }),
      slider({ id: "set-lens", label: "Manual focus", key: "lens_position", value: settings.lens_position, min: 0, max: 10, step: 0.1, rowId: "row-lens", hidden: settings.af_continuous }),
    ]),
    group("System performance", [performancePanel]),
  ];

  app.innerHTML = `
    <div class="screen admin-page settings-screen has-bottom-bar">
      <div class="admin-topbar"><h2 class="admin-section-title">Settings</h2></div>
      <div class="settings-body">
        <div class="settings-preview-col">
          <div class="settings-preview-frame">
            ${cameraAvailable
              ? `<canvas id="settings-preview" class="settings-preview-img" aria-label="Live camera preview"></canvas>`
              : `<div class="settings-preview-msg">Camera unavailable</div>`}
          </div>
        </div>
        <div class="settings-controls drag-scroll">${groups.join("")}</div>
      </div>
      <nav class="bottom-bar" aria-label="Settings actions">
        <button class="btn btn-secondary" type="button" id="settings-back">Back</button>
        <button class="btn btn-secondary" type="button" id="settings-reset">Reset</button>
      </nav>
    </div>`;

  if (cameraAvailable) startPreview();
  document.getElementById("settings-back").onclick = () => {
    state.view = "admin";
    render();
  };
  document.getElementById("settings-reset").onclick = async () => {
    try {
      const result = await api.resetCameraSettings();
      state.cameraSettings = result.settings;
      renderSettingsScreen({ app, state, render, api, escapeHtml, showConfirm });
    } catch (error) {
      alert(error.message);
    }
  };

  const controls = app.querySelector(".settings-controls");
  controls.querySelectorAll('input[type="range"]').forEach((input) => {
    input.addEventListener("input", () => {
      const value = parseFloat(input.value);
      const output = document.getElementById(`${input.id}-out`);
      if (output) output.textContent = formatValue(input.dataset.key, value);
      queueUpdate(input.dataset.key, value);
    });
  });
  controls.querySelectorAll('input[type="checkbox"][data-key]').forEach((input) => {
    input.addEventListener("change", () => {
      queueUpdate(input.dataset.key, input.checked);
      if (input.dataset.key === "af_continuous") {
        document.getElementById("row-lens")?.classList.toggle("hidden", input.checked);
      }
    });
  });
  controls.querySelectorAll("select[data-key]").forEach((input) => {
    input.addEventListener("change", () => queueUpdate(input.dataset.key, input.value));
  });
  controls.querySelectorAll(".set-step").forEach((button) => {
    button.addEventListener("click", () => {
      const input = document.getElementById(button.dataset.target);
      if (!input) return;
      const min = parseFloat(input.min);
      const max = parseFloat(input.max);
      const step = parseFloat(input.step);
      let value = parseFloat(input.value) + parseFloat(button.dataset.delta);
      value = Math.round(value / step) * step;
      value = Math.min(max, Math.max(min, value));
      input.value = value;
      const output = document.getElementById(`${input.id}-out`);
      if (output) output.textContent = formatValue(input.dataset.key, value);
      queueUpdate(input.dataset.key, value);
    });
  });
  controls.querySelectorAll(".look-card").forEach((card) => {
    card.addEventListener("click", () => {
      controls.querySelectorAll(".look-card").forEach((item) => {
        const active = item === card;
        item.classList.toggle("active", active);
        item.setAttribute("aria-pressed", active);
      });
      queueUpdate("filter_name", card.dataset.look);
    });
  });

  const performanceElement = document.querySelector(".performance-panel");
  if (performanceElement) {
    const deviceSelect = document.getElementById("performance-device");
    const modeButtons = [...performanceElement.querySelectorAll(".performance-option")];
    const warning = document.getElementById("performance-warning");
    const acknowledge = document.getElementById("performance-ack");
    const detail = document.getElementById("performance-detail");
    const status = document.getElementById("performance-status");
    const apply = document.getElementById("performance-apply");
    let mode = selectedMode;

    const refreshPerformance = () => {
      const option = deviceSelect.selectedOptions[0];
      const available = option?.dataset.performanceAvailable === "true";
      if (mode === "performance" && !available) mode = "standard";
      modeButtons.forEach((button) => {
        const active = button.dataset.performanceMode === mode;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", String(active));
        button.disabled = button.dataset.performanceMode === "performance" && !available;
      });
      warning.hidden = mode !== "performance";
      detail.textContent = option?.dataset.detail || "";

      const selected = deviceSelect.value;
      const detected = performanceElement.dataset.detectedDevice;
      const unchanged = selected === performanceElement.dataset.currentDevice
        && mode === performanceElement.dataset.currentMode;
      let message = "A restart is required to change this setting.";
      let blocked = performanceElement.dataset.canApply !== "true";
      if (!detected) message = "Open this page on Piccie to apply hardware settings.";
      else if (selected !== detected) {
        message = "Select the Raspberry Pi detected above.";
        blocked = true;
      } else if (unchanged) message = "This mode is already selected.";
      status.textContent = message;
      apply.disabled = blocked || unchanged || (mode === "performance" && !acknowledge.checked);
    };

    deviceSelect.addEventListener("change", refreshPerformance);
    acknowledge.addEventListener("change", refreshPerformance);
    modeButtons.forEach((button) => {
      button.addEventListener("click", () => {
        if (button.disabled) return;
        mode = button.dataset.performanceMode;
        refreshPerformance();
      });
    });
    apply.addEventListener("click", async () => {
      const enabling = mode === "performance";
      const confirmed = await showConfirm({
        title: enabling ? "Enable performance mode?" : "Return to standard mode?",
        message: enabling
          ? "Piccie will restart. Active cooling is strongly recommended. Test the booth for at least one hour before relying on it at an event."
          : "Piccie will remove its performance profile and restart.",
        confirmLabel: "Apply & restart",
      });
      if (!confirmed) return;
      apply.disabled = true;
      apply.textContent = "Applying…";
      try {
        await api.updatePerformanceSettings({
          device: deviceSelect.value,
          mode,
          warning_acknowledged: enabling && acknowledge.checked,
        });
        app.innerHTML = `<div class="screen centered restart-screen"><div class="spinner"></div><h2>Restarting Piccie</h2><p>This can take a minute.</p></div>`;
        setTimeout(async function waitForPiccie() {
          try {
            await api.status();
            location.reload();
          } catch (_) {
            setTimeout(waitForPiccie, 2000);
          }
        }, 8000);
      } catch (error) {
        status.textContent = error.message;
        status.classList.add("error-text");
        apply.textContent = "Apply & restart";
        refreshPerformance();
      }
    });
    refreshPerformance();
  }
}
