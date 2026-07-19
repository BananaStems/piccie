export function renderTemplatesScreen({ app, state, render, api, escapeHtml, showConfirm }) {
  const showingArchived = state.templateView === "archived";
  const archivedCount = state.templates.filter((item) => item.archived).length;
  const visibleTemplates = state.templates.filter((item) => item.archived === showingArchived);
  app.innerHTML = `
    <div class="screen admin-page templates-screen has-bottom-bar">
      <div class="admin-topbar">
        <h2 class="admin-section-title">${showingArchived ? "Archived templates" : "Templates"}</h2>
        <span class="topbar-status">${visibleTemplates.length} ${showingArchived ? "archived" : "available"}</span>
      </div>
      <div class="template-manager-grid drag-scroll">
        ${visibleTemplates.length ? visibleTemplates.map((template) => `
          <article class="template-manager-card${template.archived ? " is-archived" : ""}">
            <img src="${api.previewUrl(template.id, "YOUR EVENT", "2026-08-01", "CELEBRATION", ".")}" alt="${escapeHtml(template.name)} template preview" draggable="false" />
            <div class="template-manager-copy">
              <div><h3>${escapeHtml(template.name)}</h3><p>${template.custom ? (template.archived ? "Archived" : "Custom") : "Built in"} · ${template.event_count} event${template.event_count === 1 ? "" : "s"}</p></div>
              ${template.custom ? `<div class="template-manager-actions">${template.archived
                ? `<button class="template-action template-restore" type="button" data-template="${template.id}" aria-label="Restore ${escapeHtml(template.name)}" title="Restore template"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7v5h5"/><path d="M5.5 11a7 7 0 1 1 1.8 7.2"/></svg></button><button class="template-action template-delete" type="button" data-template="${template.id}" aria-label="Delete ${escapeHtml(template.name)} permanently" title="${template.event_count ? "Used templates cannot be deleted" : "Delete permanently"}"${template.event_count ? " disabled" : ""}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3m3 0-1 13H7L6 7m4 4v5m4-5v5"/></svg></button>`
                : `<button class="template-action template-archive" type="button" data-template="${template.id}" aria-label="Archive ${escapeHtml(template.name)}" title="Archive template"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16v13H4zM3 4h18v3H3zm6 7h6"/></svg></button>`}</div>` : ""}
            </div>
          </article>`).join("") : `<p class="template-manager-empty">No archived templates.</p>`}
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
  app.querySelectorAll(".template-archive").forEach((button) => {
    button.onclick = async () => {
      const template = state.templates.find((item) => item.id === button.dataset.template);
      const confirmed = await showConfirm({
        title: "Archive template?",
        message: template.event_count
          ? `It stays available to ${template.event_count} existing event${template.event_count === 1 ? "" : "s"}, but cannot be selected for new events.`
          : "It will no longer appear when creating events.",
        confirmLabel: "Archive",
      });
      if (!confirmed) return;
      try {
        await api.archiveTemplate(template.id);
        state.templates = await api.listTemplates();
        render();
      } catch (error) {
        document.getElementById("template-manager-error").textContent = error.message;
      }
    };
  });
  app.querySelectorAll(".template-restore").forEach((button) => {
    button.onclick = async () => {
      try {
        await api.restoreTemplate(button.dataset.template);
        state.templates = await api.listTemplates();
        render();
      } catch (error) {
        document.getElementById("template-manager-error").textContent = error.message;
      }
    };
  });
  app.querySelectorAll(".template-delete").forEach((button) => {
    button.onclick = async () => {
      const template = state.templates.find((item) => item.id === button.dataset.template);
      const confirmed = await showConfirm({
        title: "Delete template permanently?",
        message: `${template.name} and its assets will be permanently removed from this booth.`,
        confirmLabel: "Delete",
        danger: true,
      });
      if (!confirmed) return;
      try {
        await api.deleteTemplate(template.id);
        state.templates = await api.listTemplates();
        render();
      } catch (error) {
        document.getElementById("template-manager-error").textContent = error.message;
      }
    };
  });

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
      state.templates = await api.listTemplates();
      render();
    };
    document.getElementById("booth-frame").appendChild(overlay);
  }
}
