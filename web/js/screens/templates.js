import { isoToDisplay } from "./editor.js";

const SAVED_AT = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

export function renderTemplatesScreen({ app, state, render, api, escapeHtml, showConfirm }) {
  const showingArchived = state.templateView === "archived";
  const archivedCount = state.templates.filter((item) => item.archived).length;
  const visibleTemplates = state.templates.filter((item) => item.archived === showingArchived);
  const eventsFor = (template) => (state.events || []).filter((event) => event.template_id === template.id);
  const previewSrc = (template) => api.previewUrl(template.id, "YOUR EVENT", "2026-08-01", "CELEBRATION", ".");
  const originLabel = (template) => template.custom
    ? (template.created_at ? `Saved ${SAVED_AT.format(new Date(template.created_at))}` : "Custom")
    : "Built in";
  const usageLabel = (events) => events.length
    ? `Used in ${events[0].name}${events.length > 1 ? ` +${events.length - 1}` : ""}`
    : "Not used yet";

  app.innerHTML = `
    <div class="screen admin-page templates-screen has-bottom-bar">
      <div class="admin-topbar">
        <h2 class="admin-section-title">${showingArchived ? "Archived templates" : "Templates"}</h2>
        <span class="topbar-status">${visibleTemplates.length} ${showingArchived ? "archived" : "available"}</span>
      </div>
      <div class="template-manager-grid drag-scroll">
        ${visibleTemplates.length ? visibleTemplates.map((template) => {
          const events = eventsFor(template);
          return `<button class="template-manager-card${template.archived ? " is-archived" : ""}" type="button" data-template="${template.id}" aria-label="View ${escapeHtml(template.name)}">
            <img src="${previewSrc(template)}" alt="" draggable="false" />
            <span class="template-manager-copy">
              <strong>${escapeHtml(template.name)}</strong>
              <span>${escapeHtml(originLabel(template))}</span>
              <span class="template-usage${events.length ? " is-used" : ""}">${escapeHtml(usageLabel(events))}</span>
            </span>
          </button>`;
        }).join("") : `<p class="template-manager-empty">${showingArchived ? "No archived templates." : "No templates."}</p>`}
      </div>
      <p class="error-text template-manager-error" id="template-manager-error" role="alert"></p>
      <nav class="bottom-bar" aria-label="Template actions">
        <button class="btn btn-secondary" type="button" id="templates-back">Back</button>
        <button class="btn btn-secondary" type="button" id="templates-toggle">${showingArchived ? "Active templates" : `Archived (${archivedCount})`}</button>
        ${showingArchived ? "" : `<button class="btn" type="button" id="templates-create">Create on phone</button>`}
      </nav>
    </div>`;

  document.getElementById("templates-back").onclick = () => {
    state.templateView = "active";
    state.view = "admin";
    render();
  };
  document.getElementById("templates-toggle").onclick = () => {
    state.templateView = showingArchived ? "active" : "archived";
    render();
  };
  const createButton = document.getElementById("templates-create");
  if (createButton) createButton.onclick = async () => {
    const button = document.getElementById("templates-create");
    button.disabled = true;
    try {
      const pairing = await api.pairTemplateStudio();
      showPairing(pairing.url);
    } catch (error) {
      document.getElementById("template-manager-error").textContent = error.message;
    } finally {
      button.disabled = false;
    }
  };
  app.querySelectorAll(".template-manager-card").forEach((card) => {
    card.onclick = () => showDetail(state.templates.find((item) => item.id === card.dataset.template));
  });

  async function refresh() {
    state.templates = await api.listTemplates();
    render();
  }

  function showDetail(template) {
    if (!template) return;
    const events = eventsFor(template);
    const used = events.length > 0;
    const eyebrow = !template.custom ? "Built-in template" : template.archived ? "Archived template" : "Custom template";
    const note = !template.custom
      ? "Built-in templates are always available."
      : used
        ? (template.archived
          ? "Its events still print with it. It can't be deleted while an event uses it."
          : "Archiving hides it from new events. Its events still print with it.")
        : "";
    const overlay = document.createElement("div");
    overlay.className = "confirm-overlay";
    overlay.innerHTML = `<section class="template-detail-panel" role="dialog" aria-modal="true" aria-labelledby="template-detail-title">
      <img class="template-detail-strip" src="${previewSrc(template)}" alt="${escapeHtml(template.name)} strip preview" draggable="false" />
      <div class="template-detail-copy">
        <p class="setup-eyebrow">${eyebrow}</p>
        <h2 id="template-detail-title">${escapeHtml(template.name)}</h2>
        ${template.custom ? `<p class="template-detail-meta">${escapeHtml(originLabel(template))}</p>` : ""}
        <h3>Used in</h3>
        ${events.length
          ? `<ul class="template-detail-events">${events.map((event) => `<li><span>${escapeHtml(event.name)}</span><span>${escapeHtml(isoToDisplay(event.date))}</span></li>`).join("")}</ul>`
          : `<p class="template-detail-meta">No events yet.</p>`}
        ${note ? `<p class="template-detail-meta">${note}</p>` : ""}
        <p class="error-text" role="alert"></p>
        <div class="template-detail-actions">
          ${template.custom && !used ? `<button class="btn btn-danger" type="button" data-action="delete">Delete</button>` : ""}
          ${template.custom ? `<button class="btn btn-secondary" type="button" data-action="${template.archived ? "restore" : "archive"}">${template.archived ? "Restore" : "Archive"}</button>` : ""}
          <button class="btn" type="button" data-action="close">Done</button>
        </div>
      </div>
    </section>`;
    const errorEl = overlay.querySelector(".error-text");
    const close = () => overlay.remove();
    const run = async (work) => {
      overlay.querySelectorAll("button").forEach((button) => { button.disabled = true; });
      try {
        await work();
      } catch (error) {
        errorEl.textContent = error.message;
        overlay.querySelectorAll("button").forEach((button) => { button.disabled = false; });
        return;
      }
      close();
      refresh().catch((error) => {
        document.getElementById("template-manager-error").textContent = error.message;
      });
    };
    overlay.onclick = (event) => {
      if (event.target === overlay) close();
    };
    overlay.querySelector('[data-action="close"]').onclick = close;
    const archive = overlay.querySelector('[data-action="archive"]');
    if (archive) archive.onclick = () => run(() => api.archiveTemplate(template.id));
    const restore = overlay.querySelector('[data-action="restore"]');
    if (restore) restore.onclick = () => run(() => api.restoreTemplate(template.id));
    const remove = overlay.querySelector('[data-action="delete"]');
    if (remove) remove.onclick = async () => {
      const confirmed = await showConfirm({
        title: "Delete template permanently?",
        message: `${template.name} and its assets will be permanently removed from this booth.`,
        confirmLabel: "Delete",
        danger: true,
      });
      if (confirmed) run(() => api.deleteTemplate(template.id));
    };
    document.getElementById("booth-frame").appendChild(overlay);
    overlay.querySelector('[data-action="close"]').focus();
  }

  function showPairing(url) {
    const overlay = document.createElement("div");
    overlay.className = "confirm-overlay template-pair-overlay";
    overlay.innerHTML = `<section class="template-pair-panel" role="dialog" aria-modal="true" aria-labelledby="template-pair-title">
      <div><p class="setup-eyebrow">Template Studio</p><h2 id="template-pair-title">Continue on your phone</h2><p>Keep your phone on the same Wi-Fi as the booth. Creating a new code will replace this one.</p><code>${escapeHtml(url)}</code></div>
      <img src="/api/qr?data=${encodeURIComponent(url)}" alt="QR code to open Template Studio" />
      <button class="btn btn-secondary" type="button">Done</button>
    </section>`;
    overlay.querySelector("button").onclick = async () => {
      overlay.remove();
      await refresh();
    };
    document.getElementById("booth-frame").appendChild(overlay);
  }
}
