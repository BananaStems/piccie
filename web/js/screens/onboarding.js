export function renderOnboardingScreen({ app, state, render, api, escapeHtml, loadAdminData, closeOnScreenKeyboard }) {
  state.onboardingStep ||= "wifi";

  const shell = (step, title, copy, content, actions = "") => {
    const stepNumber = { wifi: 1, storage: 2, finish: 3, booth: 3 }[step];
    app.innerHTML = `
      <div class="screen onboarding-screen">
        <header class="onboarding-header">
          <img class="onboarding-brand" src="/assets/piccie-wordmark.svg" alt="piccie" />
          <span class="onboarding-step">Step ${stepNumber} of 3</span>
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
        state.onboardingStep = "storage";
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
        state.onboardingStep = "storage";
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

  const showStorage = () => {
    const configured = Boolean(state.status?.r2_configured);
    shell(
      "storage",
      configured ? "Cloud storage is ready" : "Cloud storage file not found",
      configured
        ? "Piccie securely imported the R2 settings you added to the microSD card."
        : "Piccie needs the completed piccie-r2.txt file from the microSD boot partition.",
      configured
        ? `<div class="provider-card provider-card-r2 onboarding-storage-ready">
            <span class="provider-logo">R2</span>
            <span class="provider-copy"><strong>Cloudflare R2 connected</strong><small>The readable credential file has been removed</small></span>
            <span class="wifi-badge">Ready</span>
          </div>`
        : `<div class="onboarding-storage-missing">
            <p><strong>To finish setup:</strong></p>
            <ol>
              <li>Shut down Piccie.</li>
              <li>Put the microSD card in your computer.</li>
              <li>Open the boot drive and complete <code>piccie-r2.txt</code>.</li>
              <li>If present, check <code>piccie-r2-status.txt</code> for the exact field to fix.</li>
              <li>Safely eject the card, return it to Piccie and power on.</li>
            </ol>
            <p>The file itself contains the complete Cloudflare instructions.</p>
          </div>`,
      `<button class="btn btn-secondary" type="button" id="onboarding-storage-back">Back</button>
       ${configured
         ? '<button class="btn" type="button" id="onboarding-storage-continue">Continue</button>'
         : '<button class="btn btn-secondary" type="button" id="onboarding-storage-retry">Check again</button><button class="btn" type="button" id="onboarding-storage-shutdown">Shut down</button>'}`,
    );
    document.getElementById("onboarding-storage-back").onclick = () => {
      state.onboardingStep = "wifi";
      render();
    };
    document.getElementById("onboarding-storage-continue")?.addEventListener("click", () => {
      state.onboardingStep = "finish";
      render();
    });
    document.getElementById("onboarding-storage-retry")?.addEventListener("click", async () => {
      state.status = await api.status();
      render();
    });
    document.getElementById("onboarding-storage-shutdown")?.addEventListener("click", async (event) => {
      event.currentTarget.disabled = true;
      event.currentTarget.textContent = "Shutting down…";
      await api.shutdown();
    });
  };

  const showFinish = () => {
    shell(
      "finish",
      "Finish setup",
      "Choose the PIN used to open settings.",
      `<form class="onboarding-fields onboarding-finish-fields" id="onboarding-finish-form" autocomplete="off">
          <label class="field-wide">Operator PIN<input class="pin-input" name="operator_code" type="text" inputmode="numeric" data-osk-layout="pin" pattern="[0-9]{4,8}" minlength="4" maxlength="8" autocomplete="off" autocapitalize="none" spellcheck="false" data-1p-ignore="true" data-lpignore="true" required /><small>Use 4–8 digits.</small></label>
          <label class="field-wide">SSH public key <span class="field-optional">Optional</span><textarea name="ssh_authorized_key" rows="2" maxlength="1000" autocomplete="off" placeholder="ssh-ed25519 …"></textarea><small>Allows secure remote updates from your computer.</small></label>
          <p class="onboarding-submit-message field-wide" id="onboarding-submit-message" role="status"></p>
        </form>`,
      `<button class="btn btn-secondary" type="button" id="onboarding-finish-back">Back</button>
       <button class="btn" type="submit" form="onboarding-finish-form" id="onboarding-finish-button">Finish setup</button>`,
    );
    document.getElementById("onboarding-finish-back").onclick = () => {
      state.onboardingStep = "storage";
      render();
    };
    document.getElementById("onboarding-finish-form").onsubmit = async (event) => {
      event.preventDefault();
      const data = new FormData(event.currentTarget);
      const pin = data.get("operator_code");
      const button = document.getElementById("onboarding-finish-button");
      const message = document.getElementById("onboarding-submit-message");
      button.disabled = true;
      message.className = "onboarding-submit-message field-wide";
      message.textContent = "Checking your R2 connection…";
      try {
        await api.completeOnboarding({
          admin_pin: pin,
          ssh_authorized_key: data.get("ssh_authorized_key"),
        });
        window.location.reload();
      } catch (error) {
        message.className = "onboarding-submit-message field-wide error-text";
        message.textContent = error.message;
        button.disabled = false;
      }
    };
  };

  ({
    wifi: showWifi,
    storage: showStorage,
    finish: showFinish,
  }[state.onboardingStep] || showWifi)();
}
