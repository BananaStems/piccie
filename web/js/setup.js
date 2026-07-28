const TOKEN_KEY = "piccie-onboarding-token";
const CLAIM_ID_KEY = "piccie-worker-claim-id";
const loading = document.getElementById("setup-loading");
const formCard = document.getElementById("setup-form-card");
const result = document.getElementById("setup-result");
const form = document.getElementById("setup-form");
const message = document.getElementById("setup-message");
const submit = document.getElementById("setup-submit");
const claimPanel = document.getElementById("setup-claim-panel");
const claimButton = document.getElementById("setup-claim");
const claimMessage = document.getElementById("setup-claim-message");
const workerUrlInput = document.getElementById("setup-worker-url");
const claimKeyInput = document.getElementById("setup-claim-key");
const manual = document.getElementById("setup-manual");

const fragment = new URLSearchParams(window.location.hash.slice(1));
const fragmentToken = fragment.get("token");
if (fragmentToken) {
  sessionStorage.setItem(TOKEN_KEY, fragmentToken);
}
if (window.location.hash) {
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

function encodeBase64Url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

function claimId() {
  let value = sessionStorage.getItem(CLAIM_ID_KEY);
  if (!/^[A-Za-z0-9_-]{40,128}$/.test(value || "")) {
    value = encodeBase64Url(crypto.getRandomValues(new Uint8Array(32)));
    sessionStorage.setItem(CLAIM_ID_KEY, value);
  }
  return value;
}

function normalizeWorkerUrl(value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new Error("Enter the HTTPS Worker URL shown by Cloudflare.");
  }
  if (
    url.protocol !== "https:"
    || !url.hostname
    || url.username
    || url.password
    || (url.pathname !== "/" && url.pathname !== "")
    || url.search
    || url.hash
  ) {
    throw new Error("Enter the HTTPS Worker URL without a path, query, or password.");
  }
  return url.origin;
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

function setR2Config(config) {
  for (const field of [
    "account_id",
    "access_key",
    "secret_key",
    "bucket",
    "public_base_url",
    "jurisdiction",
    "worker_token",
  ]) {
    if (typeof config[field] === "string" && form.elements[field]) {
      form.elements[field].value = config[field];
    }
  }
  manual.open = false;
  claimPanel.classList.add("connected");
  claimButton.hidden = true;
  workerUrlInput.disabled = true;
  claimKeyInput.value = "";
  claimKeyInput.disabled = true;
  claimMessage.className = "";
  claimMessage.textContent =
    "Gallery connected. Piccie will upload a private test strip before saving anything.";
}

async function claimWorker() {
  claimButton.disabled = true;
  claimMessage.className = "";
  claimMessage.textContent = "Connecting this booth to your gallery…";
  try {
    const workerUrl = normalizeWorkerUrl(workerUrlInput.value.trim());
    const setupKey = claimKeyInput.value;
    if (setupKey.length < 24 || setupKey.length > 256) {
      throw new Error("Enter the setup key created during Cloudflare deployment.");
    }
    const response = await fetch(`${workerUrl}/claim`, {
      method: "POST",
      signal: AbortSignal.timeout(15000),
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        setup_key: setupKey,
        claim_id: claimId(),
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.r2) {
      throw new Error(errorText(payload.error, "The gallery could not connect this booth."));
    }
    setR2Config(payload.r2);
  } catch (error) {
    claimMessage.className = "error";
    claimMessage.textContent =
      error.name === "TimeoutError" || error.name === "AbortError"
        ? "The gallery took too long to respond. Check the Worker URL and try again."
        : error.message;
    claimButton.disabled = false;
  }
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
    claimButton.onclick = claimWorker;
  } catch (error) {
    sessionStorage.removeItem(TOKEN_KEY);
    showLoadingError(error.message);
  }
}

function toggleSecret(input, button) {
  const visible = input.type === "text";
  input.type = visible ? "password" : "text";
  button.textContent = visible ? "Show" : "Hide";
}

document.getElementById("setup-secret-toggle").onclick = () => {
  toggleSecret(form.elements.secret_key, document.getElementById("setup-secret-toggle"));
};

document.getElementById("setup-claim-key-toggle").onclick = () => {
  toggleSecret(claimKeyInput, document.getElementById("setup-claim-key-toggle"));
};

form.onsubmit = async (event) => {
  event.preventDefault();
  const data = new FormData(form);
  const workerToken = String(data.get("worker_token") || "").trim();
  const requiredR2Fields = workerToken
    ? ["public_base_url"]
    : ["account_id", "bucket", "access_key", "secret_key", "public_base_url"];
  const missingR2Field = requiredR2Fields.find(
    (field) => !String(data.get(field) || "").trim(),
  );
  if (missingR2Field) {
    if (workerToken) {
      message.className = "form-message error";
      message.textContent = "Reconnect the gallery and try again.";
    } else {
      manual.open = true;
      message.className = "form-message error";
      message.textContent = "Connect your gallery or complete all manual Cloudflare fields.";
      form.elements[missingR2Field].focus();
    }
    return;
  }
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
          worker_token: workerToken,
        },
      },
    });
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(CLAIM_ID_KEY);
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
