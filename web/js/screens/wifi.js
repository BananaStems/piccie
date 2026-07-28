export function renderWifiScreen({ app, state, api, escapeHtml, closeOnScreenKeyboard, returnFromWifi }) {
  const loadNetworks = async () => {
    const listEl = document.getElementById("wifi-list");
    if (!listEl) return;
    listEl.innerHTML = `<div class="spinner"></div>`;
    try {
      state.wifiNetworks = await api.listWifiNetworks();
      if (state.wifiNetworks.length === 0) {
        listEl.innerHTML = `<p class="subtitle">No visible networks found</p>`;
      } else {
        listEl.innerHTML = state.wifiNetworks
          .map(
            (network, index) => `
            <button class="wifi-item" type="button" data-idx="${index}">
              <span>
                <strong>${escapeHtml(network.ssid)}</strong>
                ${network.connected ? '<span class="wifi-badge">Connected</span>' : ""}
              </span>
              ${network.signal != null ? `<span class="wifi-signal">${network.signal}%</span>` : ""}
            </button>`,
          )
          .join("");
      }
      listEl.insertAdjacentHTML(
        "beforeend",
        `<button class="wifi-item" type="button" id="wifi-hidden-network"><span><strong>Join a hidden network</strong></span></button>`,
      );
      listEl.querySelectorAll(".wifi-item").forEach((item) => {
        if (item.id !== "wifi-hidden-network") {
          item.onclick = () => showConnect(state.wifiNetworks[Number(item.dataset.idx)]?.ssid);
        }
      });
      document.getElementById("wifi-hidden-network").onclick = () => showConnect("", true);
    } catch (error) {
      listEl.innerHTML = `<p class="error-text">${escapeHtml(error.message)}</p>`;
    }
  };

  const hideConnect = () => {
    state.wifiSelected = null;
    const panel = document.getElementById("wifi-connect");
    if (panel) panel.hidden = true;
    closeOnScreenKeyboard();
  };

  const showConnect = (ssid, hidden = false) => {
    if (!ssid && !hidden) return;
    state.wifiSelected = ssid;
    state.wifiHidden = hidden;
    const panel = document.getElementById("wifi-connect");
    if (!panel) return;
    const label = document.getElementById("wifi-ssid-label");
    const hiddenInput = document.getElementById("wifi-hidden-ssid");
    label.textContent = ssid;
    label.hidden = hidden;
    hiddenInput.hidden = !hidden;
    hiddenInput.value = "";
    const message = document.getElementById("wifi-msg");
    message.textContent = "";
    message.className = "wifi-msg";
    const password = document.getElementById("wifi-pw");
    password.value = "";
    password.type = "password";
    document.getElementById("wifi-pw-toggle").textContent = "Show";
    document.getElementById("wifi-connect-btn").disabled = false;
    panel.hidden = false;
    (hidden ? hiddenInput : password).focus();
  };

  const connect = async () => {
    const ssid = state.wifiHidden
      ? document.getElementById("wifi-hidden-ssid").value.trim()
      : state.wifiSelected;
    if (!ssid) return;
    const password = document.getElementById("wifi-pw").value;
    const message = document.getElementById("wifi-msg");
    const button = document.getElementById("wifi-connect-btn");
    message.className = "wifi-msg";
    message.textContent = `Connecting to ${ssid}...`;
    button.disabled = true;
    closeOnScreenKeyboard();
    try {
      const result = await api.connectWifi(ssid, password || null, state.wifiHidden);
      state.status = await api.status();
      message.className = result.warning ? "wifi-msg error" : "wifi-msg success";
      message.textContent = result.warning
        ? `Connected to ${ssid}, but guest delivery is unavailable: ${result.warning}`
        : `Connected to ${ssid}. Guest delivery verified.`;
      if (result.warning) {
        button.disabled = false;
      } else {
        setTimeout(() => {
          returnFromWifi();
        }, 900);
      }
    } catch (error) {
      message.className = "wifi-msg error";
      message.textContent = error.message;
      button.disabled = false;
      document.getElementById("wifi-pw").focus();
      document.getElementById("wifi-pw").select();
    }
  };

  app.innerHTML = `
    <div class="screen admin-page wifi-screen has-bottom-bar">
      <div class="admin-topbar">
        <h2 class="admin-section-title">Wi-Fi</h2>
      </div>
      <div class="wifi-list drag-scroll" id="wifi-list"><div class="spinner"></div></div>
      <div class="wifi-connect" id="wifi-connect" hidden>
        <div class="form-group">
          <label>Network <span id="wifi-ssid-label"></span>
            <input class="wifi-keyboard-anchor" id="wifi-hidden-ssid" type="text"
              inputmode="none" autocomplete="off" placeholder="Hidden network name" hidden />
          </label>
          <div class="password-field">
            <input class="wifi-keyboard-anchor wifi-password-anchor" id="wifi-pw" type="password"
              inputmode="none" autocomplete="off" />
            <button class="btn btn-secondary password-toggle" type="button" id="wifi-pw-toggle">Show</button>
          </div>
        </div>
        <p id="wifi-msg" class="wifi-msg"></p>
        <div class="form-actions">
          <button class="btn" type="button" id="wifi-connect-btn">Connect</button>
          <button class="btn btn-secondary" type="button" id="wifi-cancel-btn">Cancel</button>
        </div>
      </div>
      <div class="wifi-keyboard-spacer" aria-hidden="true"></div>
      <nav class="bottom-bar" aria-label="Wi-Fi actions">
        <button class="btn btn-secondary" type="button" id="wifi-back">Back</button>
        <button class="btn btn-secondary" type="button" id="wifi-refresh">Refresh</button>
      </nav>
    </div>`;

  document.getElementById("wifi-back").onclick = () => {
    returnFromWifi();
  };
  document.getElementById("wifi-refresh").onclick = loadNetworks;
  document.getElementById("wifi-cancel-btn").onclick = hideConnect;
  document.getElementById("wifi-connect-btn").onclick = connect;
  const password = document.getElementById("wifi-pw");
  const toggle = document.getElementById("wifi-pw-toggle");
  toggle.onpointerdown = (event) => event.preventDefault();
  toggle.onclick = () => {
    const visible = password.type === "text";
    password.type = visible ? "password" : "text";
    toggle.textContent = visible ? "Show" : "Hide";
  };
  loadNetworks();
}
