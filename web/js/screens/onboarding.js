export function renderOnboardingScreen({ app, state, render, api, escapeHtml, loadAdminData, closeOnScreenKeyboard }) {
  state.onboardingStep ||= "wifi";

  const shell = (step, title, copy, content, actions = "") => {
    const stepNumber = { wifi: 1, providers: 2, r2: 2, booth: 3 }[step];
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
        <div class="onboarding-wifi-form" id="onboarding-wifi-form" hidden>
          <div class="onboarding-selected-network">
            <span>Connect to</span><strong id="onboarding-ssid"></strong>
          </div>
          <div class="password-field" id="onboarding-password-field">
            <input id="onboarding-wifi-password" type="password" inputmode="none"
              autocomplete="off" placeholder="Wi-Fi password" aria-label="Wi-Fi password" />
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

    const selectNetwork = (network) => {
      if (!network) return;
      state.wifiSelected = network.ssid;
      const form = document.getElementById("onboarding-wifi-form");
      document.getElementById("onboarding-ssid").textContent = network.ssid;
      document.getElementById("onboarding-wifi-message").textContent = "";
      const password = document.getElementById("onboarding-wifi-password");
      password.value = "";
      password.type = "password";
      document.getElementById("onboarding-password-field").hidden = network.connected;
      document.getElementById("onboarding-password-toggle").textContent = "Show";
      document.getElementById("onboarding-wifi-connect").textContent = network.connected ? "Continue" : "Connect";
      form.hidden = false;
      if (!network.connected) password.focus();
    };

    document.getElementById("onboarding-refresh").onclick = loadNetworks;
    document.getElementById("onboarding-wifi-cancel").onclick = () => {
      state.wifiSelected = null;
      document.getElementById("onboarding-wifi-form").hidden = true;
      closeOnScreenKeyboard();
    };
    const password = document.getElementById("onboarding-wifi-password");
    const toggle = document.getElementById("onboarding-password-toggle");
    toggle.onpointerdown = (event) => event.preventDefault();
    toggle.onclick = () => {
      const visible = password.type === "text";
      password.type = visible ? "password" : "text";
      toggle.textContent = visible ? "Show" : "Hide";
    };
    document.getElementById("onboarding-wifi-connect").onclick = async () => {
      if (!state.wifiSelected) return;
      const button = document.getElementById("onboarding-wifi-connect");
      const message = document.getElementById("onboarding-wifi-message");
      const selected = state.wifiNetworks.find((network) => network.ssid === state.wifiSelected);
      if (selected?.connected) {
        closeOnScreenKeyboard();
        state.onboardingStep = "providers";
        render();
        return;
      }
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
      message.className = "wifi-msg onboarding-wifi-message";
      message.setAttribute("role", "status");
      message.textContent = `Connecting to ${state.wifiSelected}…`;
      closeOnScreenKeyboard();
      try {
        await api.connectWifi(state.wifiSelected, password.value || null);
        state.status = await api.status();
        state.onboardingStep = "providers";
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

  const showProviders = () => {
    shell(
      "providers",
      "Choose your storage",
      "Your booth keeps a local copy and uploads finished strips to your provider.",
      `<button class="provider-card provider-card-r2" type="button" id="provider-r2">
          <span class="provider-logo">R2</span>
          <span class="provider-copy"><strong>Cloudflare R2</strong><small>Connect your bucket</small></span>
          <span class="provider-arrow" aria-hidden="true">→</span>
        </button>
        <div class="provider-coming-soon">
          <div><strong>Amazon S3</strong><span>Coming soon</span></div>
          <div><strong>Google Drive</strong><span>Coming soon</span></div>
        </div>`,
      `<button class="btn btn-secondary" type="button" id="onboarding-provider-back">Back</button>`,
    );
    document.getElementById("provider-r2").onclick = () => {
      state.onboardingStep = "r2";
      render();
    };
    document.getElementById("onboarding-provider-back").onclick = () => {
      state.onboardingStep = "wifi";
      render();
    };
  };

  const showR2 = () => {
    const saved = state.onboardingR2 || {};
    shell(
      "r2",
      "Connect Cloudflare R2",
      "Deploy the self-hosted gallery Worker, then enter its URL and an Object Read & Write token restricted to the same bucket.",
      `<form class="onboarding-fields" id="onboarding-r2-form">
          <label>Account ID<input name="account_id" value="${escapeHtml(saved.account_id || "")}" autocomplete="off" required /></label>
          <label>Bucket<input name="bucket" value="${escapeHtml(saved.bucket || "")}" autocomplete="off" pattern="[a-z0-9][a-z0-9-]{1,61}[a-z0-9]" required /></label>
          <label class="field-wide">Access Key ID<input name="access_key" value="${escapeHtml(saved.access_key || "")}" autocomplete="off" required /></label>
          <label class="field-wide">Secret Access Key<input name="secret_key" value="${escapeHtml(saved.secret_key || "")}" type="password" autocomplete="off" required /></label>
          <label class="field-wide">Gallery Worker URL<input name="public_base_url" value="${escapeHtml(saved.public_base_url || "")}" type="url" inputmode="url" placeholder="https://piccie-gallery.example.workers.dev" required /></label>
          <label>Jurisdiction<select name="jurisdiction">
            <option value="default">Default</option><option value="eu">European Union</option><option value="fedramp">FedRAMP</option>
          </select></label>
        </form>`,
      `<button class="btn btn-secondary" type="button" id="onboarding-r2-back">Back</button>
       <button class="btn" type="submit" form="onboarding-r2-form">Continue</button>`,
    );
    document.querySelector('[name="jurisdiction"]').value = saved.jurisdiction || "default";
    document.getElementById("onboarding-r2-back").onclick = () => {
      state.onboardingStep = "providers";
      render();
    };
    document.getElementById("onboarding-r2-form").onsubmit = (event) => {
      event.preventDefault();
      const data = new FormData(event.currentTarget);
      state.onboardingR2 = Object.fromEntries(data.entries());
      state.onboardingStep = "finish";
      closeOnScreenKeyboard();
      render();
    };
  };

  const showFinish = () => {
    shell(
      "finish",
      "Finish setup",
      "Choose the PIN used to open settings.",
      `<form class="onboarding-fields onboarding-finish-fields" id="onboarding-finish-form">
          <label class="field-wide">Operator PIN<input name="admin_pin" type="password" inputmode="numeric" pattern="[0-9]{4,8}" minlength="4" maxlength="8" autocomplete="new-password" required /><small>Use 4–8 digits.</small></label>
          <label class="field-wide">SSH public key <span class="field-optional">Optional</span><textarea name="ssh_authorized_key" rows="2" maxlength="1000" autocomplete="off" placeholder="ssh-ed25519 …"></textarea><small>Allows secure remote updates from your computer.</small></label>
          <p class="onboarding-submit-message field-wide" id="onboarding-submit-message" role="status"></p>
        </form>`,
      `<button class="btn btn-secondary" type="button" id="onboarding-finish-back">Back</button>
       <button class="btn" type="submit" form="onboarding-finish-form" id="onboarding-finish-button">Finish setup</button>`,
    );
    document.getElementById("onboarding-finish-back").onclick = () => {
      state.onboardingStep = "r2";
      render();
    };
    document.getElementById("onboarding-finish-form").onsubmit = async (event) => {
      event.preventDefault();
      const data = new FormData(event.currentTarget);
      const pin = data.get("admin_pin");
      const button = document.getElementById("onboarding-finish-button");
      const message = document.getElementById("onboarding-submit-message");
      button.disabled = true;
      message.className = "onboarding-submit-message field-wide";
      message.textContent = "Checking your R2 connection…";
      try {
        await api.completeOnboarding({
          admin_pin: pin,
          ssh_authorized_key: data.get("ssh_authorized_key"),
          r2: state.onboardingR2,
        });
        await api.unlockAdmin(pin);
        state.status = await api.status();
        await loadAdminData();
        state.view = "admin";
        render();
      } catch (error) {
        message.className = "onboarding-submit-message field-wide error-text";
        message.textContent = error.message;
        button.disabled = false;
      }
    };
  };

  ({ wifi: showWifi, providers: showProviders, r2: showR2, finish: showFinish }[state.onboardingStep] || showWifi)();
}
