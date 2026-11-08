// Phone/laptop setup page. Every API call carries the code shown on the booth.
const CODE_KEY = "piccie-setup-code";
const $ = (id) => document.getElementById(id);
let code = normalizeCode(location.hash.slice(1)) || sessionStorage.getItem(CODE_KEY) || "";
let state = null;

function normalizeCode(value) {
  const letters = String(value || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  return letters.length === 8 ? `${letters.slice(0, 4)}-${letters.slice(4)}` : "";
}

class InactiveCode extends Error {}

async function call(path, body) {
  const response = await fetch(`/api/setup/${path}`, {
    method: body ? "POST" : "GET",
    headers: { "X-Setup-Code": code, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) throw new InactiveCode(data.detail || "This setup code is no longer active.");
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? data.detail.map((item) => item.msg).join(" ") : data.detail;
    throw new Error(detail || `The booth answered ${response.status}.`);
  }
  return data;
}

function show(id) {
  for (const card of ["code-card", "loading-card", "setup-sections", "done-card"]) {
    $(card).hidden = card !== id;
  }
}

function askForCode(message = "") {
  sessionStorage.removeItem(CODE_KEY);
  $("code-message").textContent = message;
  $("code-message").classList.toggle("error", Boolean(message));
  show("code-card");
  $("code-input").focus();
}

function setMessage(id, text, isError = false) {
  $(id).textContent = text;
  $(id).classList.toggle("error", isError);
}

function setPill(id, text, on) {
  $(id).textContent = text;
  $(id).classList.toggle("on", on);
}

function render() {
  const onboarding = state.onboarding;
  $("setup-mode-label").textContent = onboarding ? "First-time setup" : "Booth settings";
  $("setup-title").textContent = onboarding ? "Finish setting up your booth" : "Cloud and remote access";
  $("setup-wifi").textContent = state.wifi_ssid || "Wi-Fi";

  const r2 = state.r2;
  setPill("r2-status", r2 ? `Connected to ${r2.bucket}` : "Not connected", Boolean(r2));
  const r2Form = $("r2-form");
  if (r2) {
    r2Form.account_id.value ||= r2.account_id;
    r2Form.bucket.value = r2.bucket;
    r2Form.jurisdiction.value = r2.jurisdiction;
    $("r2-help").open = false;
  }

  const domain = state.domain;
  setPill("domain-status", domain.public_domain || "Off", Boolean(domain.public_domain));
  const domainForm = $("domain-form");
  domainForm.public_domain.value ||= domain.public_domain;
  if (domain.public_bucket) domainForm.public_bucket.value = domain.public_bucket;
  $("domain-off").hidden = !domain.public_domain;
  for (const element of domainForm.elements) element.disabled = !r2;
  if (!r2) setMessage("domain-message", "Connect cloud storage first.");
  else if ($("domain-message").textContent === "Connect cloud storage first.") setMessage("domain-message", "");

  const accessForm = $("access-form");
  $("access-title").textContent = onboarding ? "Finish setup" : "Remote access";
  $("pin-field").hidden = !onboarding;
  $("pin-confirm-field").hidden = !onboarding;
  $("access-submit").textContent = onboarding ? "Finish setup" : "Save SSH key";
  $("access-submit").disabled = onboarding && !r2;
  if (!accessForm.ssh_authorized_key.value) accessForm.ssh_authorized_key.value = state.ssh_authorized_key || "";
}

async function submitting(form, messageId, busyText, action) {
  const buttons = form.querySelectorAll("button");
  buttons.forEach((button) => { button.disabled = true; });
  setMessage(messageId, busyText);
  try {
    await action();
  } catch (error) {
    if (error instanceof InactiveCode) {
      askForCode(error.message);
      return;
    }
    setMessage(messageId, error.message, true);
  } finally {
    buttons.forEach((button) => { button.disabled = false; });
    if (state) render();
  }
}

$("code-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const entered = normalizeCode($("code-input").value);
  if (!entered) {
    setMessage("code-message", "The code has 8 letters and numbers, like abcd-efgh.", true);
    return;
  }
  code = entered;
  load();
});

document.querySelectorAll("[data-toggle-secret]").forEach((button) => {
  button.addEventListener("click", () => {
    const input = button.previousElementSibling;
    input.type = input.type === "password" ? "text" : "password";
    button.textContent = input.type === "password" ? "Show" : "Hide";
  });
});

$("r2-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  submitting(form, "r2-message", "Uploading and downloading a test photo…", async () => {
    state = await call("r2", Object.fromEntries(new FormData(form)));
    form.secret_access_key.value = "";
    setMessage("r2-message", "Cloud storage connected.");
  });
});

$("domain-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  if (!form.public_domain.value.trim()) {
    setMessage("domain-message", "Enter your domain, or leave this step out.", true);
    return;
  }
  submitting(form, "domain-message", "Checking the domain…", async () => {
    state = await call("domain", Object.fromEntries(new FormData(form)));
    setMessage("domain-message", `Guest links now use ${state.domain.public_domain}.`);
  });
});

$("domain-off").addEventListener("click", () => {
  const form = $("domain-form");
  submitting(form, "domain-message", "Turning the domain off…", async () => {
    state = await call("domain", { public_bucket: form.public_bucket.value, public_domain: "" });
    form.public_domain.value = "";
    setMessage("domain-message", "New guest links use 7-day signed links again.");
  });
});

$("access-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const sshKey = form.ssh_authorized_key.value.trim();
  if (!state.onboarding) {
    submitting(form, "access-message", "Saving…", async () => {
      state = await call("ssh", { ssh_authorized_key: sshKey });
      setMessage("access-message", sshKey ? "SSH key saved." : "SSH access removed.");
    });
    return;
  }
  const pin = form.admin_pin.value;
  if (!/^\d{4}$/.test(pin)) {
    setMessage("access-message", "Choose a PIN of exactly 4 digits.", true);
    return;
  }
  if (pin !== form.admin_pin_confirm.value) {
    setMessage("access-message", "The PINs don't match.", true);
    return;
  }
  submitting(form, "access-message", "Running a final cloud check…", async () => {
    await call("finish", { admin_pin: pin, ssh_authorized_key: sshKey });
    sessionStorage.removeItem(CODE_KEY);
    state = null;
    show("done-card");
  });
});

async function load() {
  if (!code) {
    askForCode();
    return;
  }
  show("loading-card");
  try {
    state = await call("state");
    sessionStorage.setItem(CODE_KEY, code);
    history.replaceState(null, "", location.pathname);
    render();
    show("setup-sections");
  } catch (error) {
    askForCode(error.message);
  }
}

load();
