const API = "/api";
const DEFAULT_TIMEOUT_MS = 15000;
let adminToken = "";

async function request(path, options = {}) {
  // Always time out: a wedged camera daemon that holds the socket open without
  // responding would otherwise freeze the booth forever on a spinner. The caller
  // catches the AbortError and shows a retry path instead of hanging.
  const { timeoutMs = DEFAULT_TIMEOUT_MS, ...fetchOptions } = options;
  let res;
  try {
    res = await fetch(`${API}${path}`, {
      signal: AbortSignal.timeout(timeoutMs),
      ...fetchOptions,
      headers: {
        "Content-Type": "application/json",
        ...(adminToken ? { "X-Admin-Token": adminToken } : {}),
        ...(fetchOptions.headers || {}),
      },
    });
  } catch (e) {
    if (e.name === "TimeoutError" || e.name === "AbortError") {
      throw new Error("The booth took too long to respond. Please try again.");
    }
    throw new Error("Could not reach the booth. Please try again.");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Request failed");
  }
  if (res.status === 204) return null;
  const type = res.headers.get("content-type") || "";
  if (type.includes("application/json")) return res.json();
  return res;
}

export const api = {
  status: () => request("/status"),
  unlockAdmin: async (pin) => {
    const result = await request("/admin/unlock", {
      method: "POST",
      body: JSON.stringify({ pin }),
    });
    adminToken = result.token;
    return result;
  },
  setActiveEvent: (eventId) =>
    request("/admin/active-event", {
      method: "PUT",
      body: JSON.stringify({ event_id: eventId }),
    }),
  listEvents: () => request("/events"),
  createEvent: (data) => request("/events", { method: "POST", body: JSON.stringify(data) }),
  getEvent: (id) => request(`/events/${id}`),
  listEventSessions: (id) => request(`/events/${id}/sessions`),
  updateEvent: (id, data) => request(`/events/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  getEventShare: (id) => request(`/events/${id}/share`),
  createEventShare: (id) => request(`/events/${id}/share`, { method: "POST", timeoutMs: 120000 }),
  regenerateEventShare: (id) => request(`/events/${id}/share/regenerate`, { method: "POST", timeoutMs: 120000 }),
  disableEventShare: (id) => request(`/events/${id}/share`, { method: "DELETE" }),
  clearEventPhotos: (id) => request(`/events/${id}/clear-photos`, { method: "POST" }),
  deleteEvent: (id) => request(`/events/${id}`, { method: "DELETE" }),
  listTemplates: () => request("/templates"),
  pairTemplateStudio: () => request("/templates/pair", { method: "POST" }),
  archiveTemplate: (id) => request(`/templates/${id}/archive`, { method: "POST" }),
  restoreTemplate: (id) => request(`/templates/${id}/restore`, { method: "POST" }),
  deleteTemplate: (id) => request(`/templates/${id}`, { method: "DELETE" }),
  listWifiNetworks: () => request("/wifi/networks"),
  connectWifi: (ssid, password, hidden = false) =>
    request("/wifi/connect", {
      method: "POST",
      body: JSON.stringify({ ssid, password, hidden }),
      timeoutMs: 45000,
    }),
  completeOnboarding: (data) =>
    request("/onboarding/complete", {
      method: "POST",
      body: JSON.stringify(data),
      timeoutMs: 60000,
    }),
  getCameraSettings: () => request("/settings/camera"),
  updateCameraSettings: (patch) =>
    request("/settings/camera", { method: "PUT", body: JSON.stringify(patch) }),
  resetCameraSettings: () => request("/settings/camera/reset", { method: "POST" }),
  getPerformanceSettings: () => request("/settings/performance"),
  updatePerformanceSettings: (data) =>
    request("/settings/performance", { method: "PUT", body: JSON.stringify(data) }),
  startSession: (eventId) => request(`/events/${eventId}/sessions`, { method: "POST" }),
  capture: (sessionId, index) => request(`/sessions/${sessionId}/capture/${index}`, { method: "POST" }),
  finalize: (sessionId) => request(`/sessions/${sessionId}/finalize`, { method: "POST" }),
  getSession: (sessionId) => request(`/sessions/${sessionId}`),
  photoUrl: (sessionId, index) => `/api/sessions/${sessionId}/photos/${index}`,
  previewUrl: (templateId, line1, date, line2 = "", dateSeparator = "/") => {
    const params = new URLSearchParams({
      line1,
      date,
      line2,
      date_separator: dateSeparator,
    });
    return `/api/templates/${templateId}/preview?${params.toString()}`;
  },
  cameraPreviewUrl: (photoWidth, photoHeight) => {
    const base = "/api/camera/preview";
    if (photoWidth && photoHeight) {
      return `${base}?w=${photoWidth}&h=${photoHeight}`;
    }
    return base;
  },
};
