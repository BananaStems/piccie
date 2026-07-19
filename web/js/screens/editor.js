import { api } from "../api.js";

const EXAMPLE_HEADING = "";
const EXAMPLE_SUBHEADING = "";
const EXAMPLE_DATE = "";
const EDIT_ICON_SVG =
  '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>';
const TEMPLATE_TICK_SVG =
  '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7"/></svg>';

export function isoToDisplay(iso, separator = "/") {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
  if (!match) return iso || "";
  return `${match[3]}${separator}${match[2]}${separator}${match[1].slice(2)}`;
}

function displayToIso(display) {
  const match = /^(\d{1,2})[./](\d{1,2})[./](\d{2,4})$/.exec((display || "").trim());
  if (!match) return (display || "").trim();
  const year = match[3].length === 2 ? `20${match[3]}` : match[3];
  return `${year}-${match[2].padStart(2, "0")}-${match[1].padStart(2, "0")}`;
}

function endFields(endsAt, fallbackDate) {
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(endsAt || "");
  return {
    date: isoToDisplay(match?.[1] || fallbackDate || ""),
    time: match?.[2] || "23:59",
  };
}

export function defaultTemplateIndex(state) {
  const index = state.templates.findIndex((template) => template.default && !template.archived);
  if (index >= 0) return index;
  const active = state.templates.findIndex((template) => !template.archived);
  return active >= 0 ? active : 0;
}

export function templateIndexForId(state, templateId) {
  const index = state.templates.findIndex((template) => template.id === templateId);
  return index >= 0 ? index : defaultTemplateIndex(state);
}

function selectedTemplate(state) {
  return state.templates[state.templateIndex] || null;
}

function previewSource(templateId, line1, date, line2, separator) {
  return `${api.previewUrl(templateId, line1, date, line2, separator)}&t=${Date.now()}`;
}

function templateRailMarkup(state, escapeHtml, { line1, line2, date, date_separator }, selectedId) {
  if (!state.templates.length) return '<p class="subtitle">No templates available</p>';
  const cards = state.templates.map((template, index) => ({ template, index }))
    .filter(({ template }) => !template.archived || template.id === selectedId)
    .map(({ template, index }) => `
    <div class="template-card${index === state.templateIndex ? " selected" : ""}" data-idx="${index}" role="button" tabindex="0" aria-label="Select ${escapeHtml(template.name)} template">
      <span class="template-tick" aria-hidden="true">${TEMPLATE_TICK_SVG}</span>
      <img class="template-card-img" src="${previewSource(template.id, line1, date, line2, date_separator)}" alt="${escapeHtml(template.name)} preview" draggable="false" />
    </div>`).join("");
  return `<div class="template-rail" id="tpl-rail">${cards}</div>`;
}

function bindTemplateRail(state) {
  const rail = document.getElementById("tpl-rail");
  if (!rail) return;
  const cards = rail.querySelectorAll(".template-card");
  cards.forEach((card) => {
    const select = () => {
      state.templateIndex = Number(card.dataset.idx);
      cards.forEach((item) => item.classList.remove("selected"));
      card.classList.add("selected");
      card.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
    };
    card.addEventListener("click", select);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        select();
      }
    });
  });
  rail.querySelector(".template-card.selected")?.scrollIntoView({ inline: "center", block: "nearest" });
}

function previewFields() {
  const displayDate = document.getElementById("edit-ev-date")?.value || "";
  return {
    line1: document.getElementById("edit-ev-line1")?.value.trim() || EXAMPLE_HEADING,
    line2: document.getElementById("edit-ev-line2")?.value.trim() || EXAMPLE_SUBHEADING,
    date: displayToIso(displayDate) || EXAMPLE_DATE,
    date_separator: document.getElementById("edit-date-separator")?.value || "/",
  };
}

function bindPreviewInputs(state) {
  let timer = null;
  const refresh = () => {
    const fields = previewFields();
    const rail = document.getElementById("tpl-rail");
    if (!rail) return;
    rail.querySelectorAll(".template-card").forEach((card) => {
      const template = state.templates[Number(card.dataset.idx)];
      const image = card.querySelector(".template-card-img");
      if (template && image) image.src = previewSource(template.id, fields.line1, fields.date, fields.line2, fields.date_separator);
    });
  };
  const schedule = () => {
    clearTimeout(timer);
    timer = setTimeout(refresh, 350);
  };
  ["edit-ev-line1", "edit-ev-line2", "edit-ev-date"].forEach((id) => {
    document.getElementById(id)?.addEventListener("input", schedule);
  });
  document.getElementById("edit-date-separator")?.addEventListener("change", schedule);
}

export function renderEditorScreen({ app, state, render, escapeHtml, promptText, showConfirm }) {
  const event = state.editingEvent;
  if (!event) {
    state.view = "admin";
    render();
    return;
  }
  const existing = Boolean(event.id);
  const end = endFields(event.ends_at, event.date);
  const initialPreview = {
    line1: event.line1 || EXAMPLE_HEADING,
    line2: event.line2 || EXAMPLE_SUBHEADING,
    date: event.date || EXAMPLE_DATE,
    date_separator: event.date_separator || "/",
  };
  app.innerHTML = `
    <div class="screen admin-page event-editor-screen has-bottom-bar">
      <div class="editor-header">
        <h1 class="editor-title" id="ev-title">${escapeHtml(event.name || "New event")}</h1>
        <button class="editor-title-edit" type="button" id="edit-name-btn" aria-label="Edit event name">${EDIT_ICON_SVG}</button>
      </div>
      <div class="edit-columns">
        <div class="edit-col-main drag-scroll">
          <div class="form-stack">
            <div class="form-group"><label>Heading</label><input id="edit-ev-line1" value="${escapeHtml(event.line1)}" /></div>
            <div class="form-group"><label>Subheading</label><input id="edit-ev-line2" value="${escapeHtml(event.line2)}" /></div>
            <div class="form-group"><label>Event date</label><input id="edit-ev-date" class="osk-date" type="text" maxlength="10" value="${escapeHtml(isoToDisplay(event.date))}" placeholder="DD/MM/YY" /></div>
            <div class="form-group"><label>Event ends</label><div class="event-end-fields">
              <input id="edit-ev-end-date" class="osk-date" type="text" maxlength="10" value="${escapeHtml(end.date)}" placeholder="DD/MM/YY" aria-label="Event end date" />
              <input id="edit-ev-end-time" class="osk-date" type="text" maxlength="5" value="${escapeHtml(end.time)}" placeholder="23:59" aria-label="Event end time" />
            </div></div>
            <div class="form-group"><label for="edit-date-separator">Date on strip</label><select id="edit-date-separator">
              <option value="/"${(event.date_separator || "/") === "/" ? " selected" : ""}>DD/MM/YY</option>
              <option value="."${event.date_separator === "." ? " selected" : ""}>DD.MM.YY</option>
            </select></div>
          </div>
          <p id="edit-ev-err" class="error-text"></p>
        </div>
        <div class="edit-col-template">
          <label class="field-label">Template</label>
          ${templateRailMarkup(state, escapeHtml, initialPreview, event.template_id)}
        </div>
      </div>
      <nav class="bottom-bar editor-bar" aria-label="Event actions">
        <button class="btn btn-secondary" type="button" id="cancel-edit-event">Back</button>
        <div class="editor-bar-actions">
          ${existing ? `<button class="btn btn-secondary" type="button" id="clear-photos" ${event.photo_count === 0 ? "disabled" : ""}>Clear photos (${event.photo_count})</button>` : ""}
          ${existing ? `<button class="btn btn-danger" type="button" id="delete-event">Delete</button>` : ""}
          <button class="btn" type="button" id="save-event">${existing ? "Save" : "Create"}</button>
        </div>
      </nav>
    </div>`;

  bindTemplateRail(state);
  bindPreviewInputs(state);
  document.getElementById("edit-ev-date")?.addEventListener("input", (inputEvent) => {
    const endDate = document.getElementById("edit-ev-end-date");
    if (endDate && !endDate.value && /^\d{1,2}[./]\d{1,2}[./]\d{2,4}$/.test(inputEvent.currentTarget.value)) {
      endDate.value = inputEvent.currentTarget.value;
    }
  });

  document.getElementById("edit-name-btn").onclick = async () => {
    const name = await promptText({
      title: "Event name",
      value: state.editingEvent.name || "",
      confirmLabel: "Done",
    });
    if (name === null) return;
    state.editingEvent.name = name;
    document.getElementById("ev-title").textContent = name;
  };

  document.getElementById("save-event").onclick = async () => {
    const line1 = document.getElementById("edit-ev-line1").value.trim();
    const line2 = document.getElementById("edit-ev-line2").value.trim();
    const date = displayToIso(document.getElementById("edit-ev-date").value);
    const endDate = displayToIso(document.getElementById("edit-ev-end-date").value);
    const endTime = document.getElementById("edit-ev-end-time").value.trim();
    const date_separator = document.getElementById("edit-date-separator").value;
    const template = selectedTemplate(state);
    const error = document.getElementById("edit-ev-err");
    const name = (state.editingEvent.name || "").trim();
    error.textContent = "";
    if (!name) error.textContent = "Tap the title to name the event";
    else if (!line1) error.textContent = "Heading is required";
    else if (!line2) error.textContent = "Subheading is required";
    else if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) error.textContent = "Enter the event date";
    else if (!/^\d{4}-\d{2}-\d{2}$/.test(endDate)) error.textContent = "Enter the event end date";
    else if (!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(endTime)) error.textContent = "Enter the end time as HH:MM";
    else if (endDate < date) error.textContent = "End date cannot be before the event date";
    else if (!template) error.textContent = "Choose a template";
    if (error.textContent) return;

    try {
      const payload = {
        name,
        line1,
        line2,
        date,
        ends_at: `${endDate}T${endTime}:00`,
        date_separator,
        template_id: template.id,
      };
      if (existing) await api.updateEvent(event.id, payload);
      else await api.createEvent(payload);
      state.events = await api.listEvents();
      state.editingEvent = null;
      state.view = "admin";
      render();
    } catch (saveError) {
      error.textContent = saveError.message;
    }
  };

  document.getElementById("clear-photos")?.addEventListener("click", async () => {
    const { name, photo_count: photoCount, id } = state.editingEvent;
    if (!photoCount) return;
    const confirmed = await showConfirm({
      title: "Clear photos?",
      message: `Remove all ${photoCount} photo strips from "${name}"? Local copies and cloud uploads will be deleted. This cannot be undone.`,
      confirmLabel: "Clear photos",
      danger: true,
    });
    if (!confirmed) return;
    try {
      await api.clearEventPhotos(id);
      state.editingEvent = await api.getEvent(id);
      state.events = await api.listEvents();
      render();
    } catch (error) {
      document.getElementById("edit-ev-err").textContent = error.message;
    }
  });

  document.getElementById("delete-event")?.addEventListener("click", async () => {
    const { name, id } = state.editingEvent;
    const confirmed = await showConfirm({
      title: "Delete event?",
      message: `Delete "${name}" and all its photos? This cannot be undone.`,
      confirmLabel: "Delete",
      danger: true,
    });
    if (!confirmed) return;
    try {
      await api.deleteEvent(id);
      state.editingEvent = null;
      state.events = await api.listEvents();
      state.view = "admin";
      render();
    } catch (error) {
      document.getElementById("edit-ev-err").textContent = error.message;
    }
  });

  document.getElementById("cancel-edit-event").onclick = () => {
    state.editingEvent = null;
    state.view = "admin";
    render();
  };
}
