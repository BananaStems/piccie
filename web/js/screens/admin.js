const SETTINGS_ICON = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3.2"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V15z"/></svg>';
const WIFI_ICON = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M4.5 12a11 11 0 0 1 15 0"/><path d="M8 15.5a6 6 0 0 1 8 0"/><path d="M12 19h.01"/></svg>';
const TEMPLATE_ICON = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M7 7h10M7 11h10M8 16h8"/></svg>';

export function renderAdminScreen({
  app,
  state,
  render,
  api,
  escapeHtml,
  formatDate,
  promptText,
  defaultTemplateIndex,
  templateIndexForId,
  enterParty,
}) {
  const dataWarning = state.status?.data_degraded
    ? `<p class="admin-disk-warning admin-data-warning">Storage fault. Photos and events will be lost after power-off. Check /data.</p>`
    : "";
  const diskWarning = state.status?.disk_low
    ? `<p class="admin-disk-warning">Storage low (${state.status.disk_free_mb} MB free). Delete old events to keep shooting.</p>`
    : "";
  const wifiConnected = Boolean(state.status?.wifi_ssid);
  const wifiLabel = state.status?.wifi_ssid || "No Wi-Fi";
  app.innerHTML = `
    <div class="screen admin-page admin-screen has-bottom-bar">
      ${dataWarning}
      ${diskWarning}
      <div class="event-grid drag-scroll" id="event-grid">
        ${state.events.length === 0 ? '<div class="empty-state"><p>No events yet</p></div>' : ""}
        ${state.events.map((event) => `
          <article class="event-card${event.concluded ? " is-concluded" : ""}">
            <div class="event-card-body">
              <div class="event-card-meta">
                <time class="meta">${escapeHtml(formatDate(event.date))}</time>
                <span class="event-count">${event.concluded ? "Concluded" : `${event.photo_count} strip${event.photo_count === 1 ? "" : "s"}`}</span>
              </div>
              <h3>${escapeHtml(event.name)}</h3>
            </div>
            <div class="event-actions">
              <button class="event-action" type="button" data-action="edit" data-id="${event.id}">Edit</button>
              <button class="event-action" type="button" data-action="gallery" data-id="${event.id}">Gallery</button>
              <button class="event-action event-launch" type="button" data-action="launch" data-id="${event.id}" ${event.concluded ? 'disabled title="Edit the event end time to launch again"' : ""}><svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M4 2.8v10.4c0 .8.9 1.3 1.6.8l7.4-5.2a1 1 0 0 0 0-1.6L5.6 2C4.9 1.5 4 2 4 2.8Z"/></svg>${event.concluded ? "Concluded" : "Launch"}</button>
            </div>
          </article>`).join("")}
      </div>
      <nav class="bottom-bar admin-footer" aria-label="Main actions">
        <button class="btn new-event-fab" type="button" id="new-event-btn">Create a new event</button>
        <button class="wifi-chip settings-chip" type="button" id="settings-btn" aria-label="Camera settings">
          <span class="wifi-chip-icon" aria-hidden="true">${SETTINGS_ICON}</span>
          <span class="wifi-chip-label">Settings</span>
        </button>
        <button class="wifi-chip" type="button" id="templates-btn" aria-label="Manage templates">
          <span class="wifi-chip-icon" aria-hidden="true">${TEMPLATE_ICON}</span>
          <span class="wifi-chip-label">Templates</span>
        </button>
        <button class="wifi-chip${wifiConnected ? "" : " is-offline"}" type="button" id="wifi-btn"
          aria-label="${wifiConnected ? `Wi-Fi settings. Connected to ${escapeHtml(wifiLabel)}` : "Wi-Fi settings. No network connected"}">
          <span class="wifi-chip-icon" aria-hidden="true">${WIFI_ICON}</span>
          <span class="wifi-chip-label">${escapeHtml(wifiLabel)}</span>
        </button>
      </nav>
    </div>`;

  document.getElementById("wifi-btn")?.addEventListener("click", () => {
    state.view = "wifi";
    render();
  });
  document.getElementById("settings-btn")?.addEventListener("click", () => {
    state.view = "settings";
    render();
  });
  document.getElementById("templates-btn")?.addEventListener("click", () => {
    state.view = "templates";
    render();
  });
  document.getElementById("new-event-btn")?.addEventListener("click", async () => {
    const name = await promptText({ title: "Name your event", confirmLabel: "Create" });
    if (!name) return;
    state.editingEvent = {
      id: null,
      name,
      line1: "",
      line2: "",
      date: "",
      ends_at: "",
      date_separator: "/",
      template_id: "",
      photo_count: 0,
    };
    state.templateIndex = defaultTemplateIndex();
    state.view = "edit-event";
    render();
  });

  app.querySelectorAll(".event-action").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        const event = await api.getEvent(button.dataset.id);
        if (button.dataset.action === "edit") {
          state.editingEvent = event;
          state.templateIndex = templateIndexForId(event.template_id);
          state.view = "edit-event";
        } else if (button.dataset.action === "gallery") {
          state.galleryEvent = event;
          state.gallerySessions = await api.listEventSessions(event.id);
          state.selectedGallerySession = state.gallerySessions[0] || null;
          state.view = "gallery";
        } else {
          await enterParty(event);
          return;
        }
        render();
      } catch (error) {
        alert(error.message);
      }
    });
  });
}

function galleryQrMarkup(session) {
  return session?.r2_strip_url
    ? `<img class="qr-code" src="/api/qr?data=${encodeURIComponent(session.r2_strip_url)}" alt="QR code to download this photo strip" /><p>Scan to download</p>`
    : `<p class="subtitle">Upload pending</p>`;
}

export function renderGalleryScreen({ app, state, render, api, escapeHtml }) {
  const event = state.galleryEvent;
  if (!event) {
    state.view = "admin";
    render();
    return;
  }
  const sessions = state.gallerySessions;
  const selected = state.selectedGallerySession;
  app.innerHTML = `
    <div class="screen admin-page gallery-screen has-bottom-bar">
      <div class="admin-topbar">
        <h2 class="admin-section-title">${escapeHtml(event.name)}</h2>
        <span class="topbar-status gallery-count">${sessions.length} strip${sessions.length === 1 ? "" : "s"}</span>
      </div>
      ${sessions.length === 0 ? `<div class="empty-state"><p>No photo strips yet</p></div>` : `
        <div class="gallery-body">
          <div class="gallery-grid drag-scroll">
            ${sessions.map((session, index) => `<button class="gallery-thumb${session.id === selected?.id ? " selected" : ""}" type="button" data-session="${session.id}" aria-label="View photo strip ${sessions.length - index}" aria-pressed="${session.id === selected?.id}">
              ${session.photo_local_urls.map((url, photoIndex) => `<img src="${url}" alt="Photo ${photoIndex + 1} from strip ${sessions.length - index}" draggable="false" />`).join("")}
            </button>`).join("")}
          </div>
          <div class="gallery-detail">
            <div class="gallery-strip-panel"><img src="${selected.strip_local_url}" alt="Selected photo strip" /></div>
            <div class="gallery-qr-panel">${galleryQrMarkup(selected)}</div>
          </div>
        </div>`}
      <nav class="bottom-bar" aria-label="Gallery actions">
        <button class="btn btn-secondary" type="button" id="gallery-back">Back</button>
        <button class="btn" type="button" id="gallery-share" ${sessions.length ? "" : "disabled"}>Share event</button>
      </nav>
    </div>`;

  document.getElementById("gallery-back").onclick = () => {
    state.galleryEvent = null;
    state.gallerySessions = [];
    state.selectedGallerySession = null;
    state.view = "admin";
    render();
  };
  document.getElementById("gallery-share")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    if (state.galleryEvent.share_url) {
      showEventShare(state.galleryEvent.share_url);
      return;
    }
    button.disabled = true;
    button.textContent = "Preparing…";
    try {
      const share = await api.createEventShare(state.galleryEvent.id);
      state.galleryEvent.share_url = share.url;
      const stored = state.events.find((item) => item.id === state.galleryEvent.id);
      if (stored) stored.share_url = share.url;
      showEventShare(share.url);
    } catch (error) {
      button.disabled = false;
      button.textContent = "Share event";
      showShareError(error.message);
    }
  });
  app.querySelectorAll(".gallery-thumb").forEach((thumb) => {
    thumb.onclick = () => {
      const next = sessions.find((session) => session.id === thumb.dataset.session);
      if (!next || next.id === state.selectedGallerySession?.id) return;
      state.selectedGallerySession = next;
      app.querySelector(".gallery-thumb.selected")?.classList.remove("selected");
      app.querySelectorAll(".gallery-thumb").forEach((item) => item.setAttribute("aria-pressed", item === thumb));
      thumb.classList.add("selected");
      app.querySelector(".gallery-strip-panel img").src = next.strip_local_url;
      app.querySelector(".gallery-qr-panel").innerHTML = galleryQrMarkup(next);
    };
  });

  function showShareError(message) {
    const overlay = document.createElement("div");
    overlay.className = "confirm-overlay";
    overlay.innerHTML = `<section class="confirm-panel" role="alertdialog" aria-modal="true">
      <h2 class="confirm-title">Could not share event</h2>
      <p class="confirm-message">${escapeHtml(message)}</p>
      <div class="confirm-actions"><button class="btn" type="button">Done</button></div>
    </section>`;
    overlay.querySelector("button").onclick = () => overlay.remove();
    document.getElementById("booth-frame").appendChild(overlay);
  }

  function showEventShare(url) {
    const overlay = document.createElement("div");
    overlay.className = "confirm-overlay event-share-overlay";
    overlay.innerHTML = `<section class="event-share-panel" role="dialog" aria-modal="true" aria-labelledby="event-share-title">
      <div class="event-share-copy">
        <p class="setup-eyebrow">Event gallery</p>
        <h2 id="event-share-title">Ready to share</h2>
        <p>Scan this code or copy the private link.</p>
        <code id="event-share-url">${escapeHtml(url)}</code>
        <p class="event-share-status" id="event-share-status" role="status"></p>
      </div>
      <div class="event-share-qr"><img src="/api/qr?data=${encodeURIComponent(url)}" alt="QR code for this event gallery" /></div>
      <div class="event-share-actions">
        <button class="btn btn-secondary" type="button" id="event-share-disable">Disable</button>
        <button class="btn btn-secondary" type="button" id="event-share-regenerate">New link</button>
        <button class="btn" type="button" id="event-share-copy">Copy link</button>
        <button class="btn btn-secondary" type="button" id="event-share-done">Done</button>
      </div>
    </section>`;
    document.getElementById("booth-frame").appendChild(overlay);
    const status = overlay.querySelector("#event-share-status");
    const setBusy = (busy) => overlay.querySelectorAll("button").forEach((item) => { item.disabled = busy; });
    overlay.querySelector("#event-share-done").onclick = () => overlay.remove();
    overlay.querySelector("#event-share-copy").onclick = async () => {
      try {
        await navigator.clipboard.writeText(state.galleryEvent.share_url);
        status.textContent = "Link copied";
      } catch {
        status.textContent = "Copy unavailable. Scan the QR code instead.";
      }
    };
    overlay.querySelector("#event-share-regenerate").onclick = async () => {
      setBusy(true);
      status.textContent = "Creating a new link…";
      try {
        const share = await api.regenerateEventShare(state.galleryEvent.id);
        state.galleryEvent.share_url = share.url;
        overlay.remove();
        showEventShare(share.url);
      } catch (error) {
        status.textContent = error.message;
        setBusy(false);
      }
    };
    overlay.querySelector("#event-share-disable").onclick = async () => {
      setBusy(true);
      status.textContent = "Disabling link…";
      try {
        await api.disableEventShare(state.galleryEvent.id);
        state.galleryEvent.share_url = null;
        const stored = state.events.find((item) => item.id === state.galleryEvent.id);
        if (stored) stored.share_url = null;
        overlay.remove();
      } catch (error) {
        status.textContent = error.message;
        setBusy(false);
      }
    };
  }
}
