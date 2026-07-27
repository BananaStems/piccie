const TOKEN_KEY = "piccie-onboarding-token";
const loading = document.getElementById("setup-loading");
const formCard = document.getElementById("setup-form-card");
const result = document.getElementById("setup-result");
const form = document.getElementById("setup-form");
const message = document.getElementById("setup-message");
const submit = document.getElementById("setup-submit");

const fragmentToken = new URLSearchParams(window.location.hash.slice(1)).get("token");
if (fragmentToken) {
  sessionStorage.setItem(TOKEN_KEY, fragmentToken);
  history.replaceState(null, "", window.location.pathname);
}
const token = fragmentToken || sessionStorage.getItem(TOKEN_KEY) || "";

function errorText(detail, fallback = "Request failed.") {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg || String(item)).join(" ");
  }
  return fallback;
}

async function setupRequest(path, options = {}) {
  let response;
  try {
    response = await fetch(`/api/setup${path}`, {
      signal: AbortSignal.timeout(options.timeoutMs || 15000),
      method: options.method || "GET",
      headers: {
        "Content-Type": "application/json",
        "X-Setup-Token": token,
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
  } catch (error) {
    if (error.name === "TimeoutError" || error.name === "AbortError") {
      throw new Error("The booth took too long to respond.");
    }
    throw new Error("The connection to the booth was interrupted.");
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(errorText(payload.detail, response.statusText));
  }
  return response.json();
}

function showLoadingError(text) {
  const element = document.getElementById("setup-loading-message");
  element.textContent = text;
  element.classList.add("error");
  loading.querySelector(".spinner").hidden = true;
}

async function start() {
  if (!token) {
    showLoadingError("This link has no setup token. Scan the code shown on the booth again.");
    return;
  }
  try {
    const status = await setupRequest("/status");
    document.getElementById("setup-wifi").textContent = status.wifi_ssid || "Wi-Fi";
    loading.hidden = true;
    formCard.hidden = false;
  } catch (error) {
    sessionStorage.removeItem(TOKEN_KEY);
    showLoadingError(error.message);
  }
}

document.getElementById("setup-secret-toggle").onclick = () => {
  const secret = form.elements.secret_key;
  const visible = secret.type === "text";
  secret.type = visible ? "password" : "text";
  document.getElementById("setup-secret-toggle").textContent = visible ? "Show" : "Hide";
};

form.onsubmit = async (event) => {
  event.preventDefault();
  const data = new FormData(form);
  if (data.get("admin_pin") !== data.get("confirm_pin")) {
    message.className = "form-message error";
    message.textContent = "The operator PINs do not match.";
    form.elements.confirm_pin.focus();
    return;
  }

  submit.disabled = true;
  message.className = "form-message";
  message.textContent = "Uploading a private test strip and checking its guest link…";
  try {
    await setupRequest("/complete", {
      method: "POST",
      timeoutMs: 420000,
      body: {
        admin_pin: data.get("admin_pin"),
        ssh_authorized_key: data.get("ssh_authorized_key"),
        r2: {
          account_id: data.get("account_id"),
          access_key: data.get("access_key"),
          secret_key: data.get("secret_key"),
          bucket: data.get("bucket"),
          public_base_url: data.get("public_base_url"),
          jurisdiction: data.get("jurisdiction"),
        },
      },
    });
    sessionStorage.removeItem(TOKEN_KEY);
    form.reset();
    formCard.hidden = true;
    result.hidden = false;
  } catch (error) {
    message.className = "form-message error";
    message.textContent = error.message.includes("interrupted")
      ? "The booth disconnected while finishing. If its screen says it is restarting, setup succeeded; otherwise scan a new code and try again."
      : error.message;
    submit.disabled = false;
  }
};

start();
