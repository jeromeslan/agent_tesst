/** Petit client REST vers le backend FastAPI (même origine, via proxy). */

async function req(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`API ${res.status} ${path}: ${text}`);
  }
  return res.json();
}

export const api = {
  status: () => req("/api/status"),
  signals: () => req("/api/signals"),
  refresh: () => req("/api/signals/refresh", { method: "POST" }),
  setMode: (mode) =>
    req("/api/config/mode", { method: "PUT", body: JSON.stringify({ mode }) }),
  setThreshold: (threshold) =>
    req("/api/config/threshold", {
      method: "PUT",
      body: JSON.stringify({ threshold }),
    }),
  orders: (status) =>
    req(status ? `/api/orders?status=${status}&limit=50` : "/api/orders?limit=50"),
  approve: (id) => req(`/api/orders/${id}/approve`, { method: "POST" }),
  reject: (id) => req(`/api/orders/${id}/reject`, { method: "POST" }),
};
