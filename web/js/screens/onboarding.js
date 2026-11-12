let setupPoll = null;

export function renderOnboardingScreen({ app, state, render, api, escapeHtml, closeOnScreenKeyboard }) {
  state.onboardingStep ||= "wifi";
  clearInterval(setupPoll);

  const shell = (step, title, copy, content, actions = "") => {
    const stepNumber = { wifi: 1, phone: 2 }[step];
    app.innerHTML = `
      <div class="screen onboarding-screen">
        <header class="onboarding-header">
          <img class="onboarding-brand" src="/assets/piccie-wordmark.svg" alt="piccie" />
          <span class="onboarding-step">Step ${stepNumber} of 2</span>
        </header>
        <main class="onboarding-main">
          <section class="onboarding-intro">
            <p class="setup-eyebrow">${step === "wifi" ? "Set up this booth" : "First-time setup"}</p>
            <h1>${title}</h1>
            <p>${copy}</p>
          </section>
          <section class="onboarding-panel">${content}</section>
        </main>
        <nav class="onboarding-actions" aria-label="Setup actions">${actions}</nav>
      </div>`;
  };

  const showWifi = () => {
    shell(
      "wifi",
      "Choose a Wi-Fi network",
      "Use any network to finish setup. Before each event, connect the booth to the venue's Wi-Fi from the admin screen.",
      `<div class="onboarding-panel-head">
          <h2>Available networks</h2>
          <button class="text-button" type="button" id="onboarding-refresh">Refresh</button>
        </div>
        <div class="onboarding-network-list" id="onboarding-network-list">
          <div class="spinner"></div>
        </div>
        <button class="text-button" type="button" id="onboarding-hidden-network">Join a hidden network</button>
        <div class="onboarding-wifi-form" id="onboarding-wifi-form" hidden>
          <div class="onboarding-selected-network">
            <span>Connect to</span><strong id="onboarding-ssid"></strong>
            <input class="wifi-keyboard-anchor" id="onboarding-hidden-ssid" type="text" inputmode="none"
              autocomplete="off" placeholder="Hidden network name" hidden />
          </div>
          <div class="password-field" id="onboarding-password-field">
            <input class="wifi-keyboard-anchor wifi-password-anchor masked-secret" id="onboarding-wifi-password"
              type="text" inputmode="none" autocomplete="off" autocapitalize="none" spellcheck="false"
              data-1p-ignore="true" data-lpignore="true" placeholder="Wi-Fi password" aria-label="Wi-Fi password" />
            <button class="btn btn-secondary password-toggle" type="button" id="onboarding-password-toggle">Show</button>
          </div>
          <p class="wifi-msg onboarding-wifi-message" id="onboarding-wifi-message"
            role="status" aria-live="polite"></p>
          <div class="form-actions">
            <button class="btn btn-secondary" type="button" id="onboarding-wifi-cancel">Cancel</button>
            <button class="btn" type="button" id="onboarding-wifi-connect">Connect</button>
          </div>
        </div>`,
    );

    const loadNetworks = async () => {
      const list = document.getElementById("onboarding-network-list");
      if (!list) return;
      list.innerHTML = `<div class="spinner"></div>`;
      try {
        state.wifiNetworks = await api.listWifiNetworks();
        if (!state.wifiNetworks.length) {
          list.innerHTML = `<p class="empty-copy">No Wi-Fi networks found. Check the antenna, then refresh.</p>`;
          return;
        }
        list.innerHTML = state.wifiNetworks.map((network, index) => `
          <button class="onboarding-network" type="button" data-network="${index}">
            <span class="network-mark" aria-hidden="true"><i></i><i></i><i></i></span>
            <span class="network-name">${escapeHtml(network.ssid)}</span>
            ${network.connected ? '<span class="wifi-badge">Connected</span>' : ""}
            ${network.signal != null ? `<span class="wifi-signal">${network.signal}%</span>` : ""}
          </button>`).join("");
        list.querySelectorAll("[data-network]").forEach((button) => {
          button.onclick = () => selectNetwork(state.wifiNetworks[Number(button.dataset.network)]);
        });
      } catch (error) {
        list.innerHTML = `<p class="error-text">${escapeHtml(error.message)}</p>`;
      }
    };

    const selectNetwork = (network, hidden = false) => {
      if (!network) return;
      state.wifiSelected = network.ssid;
      state.wifiHidden = hidden;
      const form = document.getElementById("onboarding-wifi-form");
      const ssidLabel = document.getElementById("onboarding-ssid");
      const hiddenSsid = document.getElementById("onboarding-hidden-ssid");
      ssidLabel.textContent = network.ssid;
      ssidLabel.hidden = hidden;
      hiddenSsid.hidden = !hidden;
      hiddenSsid.value = "";
      document.getElementById("onboarding-wifi-message").textContent = "";
      const password = document.getElementById("onboarding-wifi-password");
      password.value = "";
      password.classList.remove("is-visible");
      document.getElementById("onboarding-password-field").hidden = network.connected;
      document.getElementById("onboarding-password-toggle").textContent = "Show";
      document.getElementById("onboarding-wifi-connect").textContent = network.connected ? "Continue" : "Connect";
      form.hidden = false;
      if (!network.connected) (hidden ? hiddenSsid : password).focus();
    };

    document.getElementById("onboarding-refresh").onclick = loadNetworks;
    document.getElementById("onboarding-hidden-network").onclick = () =>
      selectNetwork({ ssid: "", connected: false }, true);
    document.getElementById("onboarding-wifi-cancel").onclick = () => {
      state.wifiSelected = null;
      document.getElementById("onboarding-wifi-form").hidden = true;
      closeOnScreenKeyboard();
    };
    const password = document.getElementById("onboarding-wifi-password");
    const toggle = document.getElementById("onboarding-password-toggle");
    toggle.onpointerdown = (event) => event.preventDefault();
    toggle.onclick = () => {
      const visible = password.classList.toggle("is-visible");
      toggle.textContent = visible ? "Hide" : "Show";
    };
    document.getElementById("onboarding-wifi-connect").onclick = async () => {
      if (!state.wifiSelected && !state.wifiHidden) return;
      const button = document.getElementById("onboarding-wifi-connect");
      const message = document.getElementById("onboarding-wifi-message");
      const selected = state.wifiNetworks.find((network) => network.ssid === state.wifiSelected);
      if (selected?.connected) {
        closeOnScreenKeyboard();
        state.status = await api.status();
        state.onboardingStep = "phone";
        render();
        return;
      }
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
      message.className = "wifi-msg onboarding-wifi-message";
      message.setAttribute("role", "status");
      message.textContent = "Connecting to Wi-Fi…";
      closeOnScreenKeyboard();
      try {
        const ssid = state.wifiHidden
          ? document.getElementById("onboarding-hidden-ssid").value.trim()
          : state.wifiSelected;
        if (!ssid) throw new Error("Enter the hidden network name.");
        const result = await api.connectWifi(ssid, password.value || null, state.wifiHidden);
        state.status = await api.status();
        if (result.warning) {
          message.className = "wifi-msg onboarding-wifi-message error";
          message.textContent = `Wi-Fi connected, but cloud access failed: ${result.warning}`;
          button.disabled = false;
          button.removeAttribute("aria-busy");
          return;
        }
        state.onboardingStep = "phone";
        render();
      } catch (error) {
        message.className = "wifi-msg onboarding-wifi-message error";
        message.setAttribute("role", "alert");
        message.textContent = error.message;
        button.disabled = false;
        button.removeAttribute("aria-busy");
        password.focus();
        password.select();
      }
    };
    loadNetworks();
  };

  const showPhone = async () => {
    shell(
      "phone",
      "Finish on your phone or computer",
      "Connect cloud storage, an optional custom domain and the operator PIN from any phone or computer on the same Wi-Fi. Use a Wi-Fi you trust. Nothing else needs typing here.",
      `<div class="onboarding-setup-link">
          <div>
            <p>Scan the code, or open this address in a browser:</p>
            <code id="onboarding-setup-url">Creating a setup link…</code>
            <p>Setup code <strong id="onboarding-setup-code"></strong></p>
            <ul class="onboarding-checklist" aria-label="Setup progress">
              <li id="onboarding-check-r2">Cloud storage</li>
              <li id="onboarding-check-pin">Operator PIN</li>
            </ul>
          </div>
          <img id="onboarding-setup-qr" alt="QR code to open booth setup" hidden />
        </div>`,
      `<button class="btn btn-secondary" type="button" id="onboarding-phone-back">Back</button>`,
    );
    document.getElementById("onboarding-phone-back").onclick = () => {
      state.onboardingStep = "wifi";
      render();
    };
    const showProgress = (status) => {
      document.getElementById("onboarding-check-r2")?.classList.toggle("done", Boolean(status?.r2_configured));
      document.getElementById("onboarding-check-pin")?.classList.toggle("done", Boolean(status?.admin_pin_set));
    };
    showProgress(state.status);
    try {
      const link = await api.createSetupLink();
      const qr = document.getElementById("onboarding-setup-qr");
      if (!qr) return;
      document.getElementById("onboarding-setup-url").textContent = link.url;
      document.getElementById("onboarding-setup-code").textContent = link.code;
      qr.src = `/api/qr?data=${encodeURIComponent(link.link)}`;
      qr.hidden = false;
    } catch (error) {
      const url = document.getElementById("onboarding-setup-url");
      if (url) url.textContent = error.message;
      return;
    }
    // The phone page finishes setup; follow along until the booth is provisioned.
    setupPoll = setInterval(async () => {
      try {
        state.status = await api.status();
      } catch {
        return;
      }
      showProgress(state.status);
      if (!state.status.onboarding_required) {
        clearInterval(setupPoll);
        window.location.reload();
      }
    }, 2000);
  };

  ({
    wifi: showWifi,
    phone: showPhone,
  }[state.onboardingStep] || showWifi)();
}
