import { apiBase } from "./format";

const TOKEN_KEY = "bb_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setSession(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
}

export async function api<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(`${apiBase()}${path}`, { ...init, headers });
  if (res.status === 401 && typeof window !== "undefined") {
    clearSession();
    if (!path.startsWith("/v1/auth")) window.location.href = "/login";
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (data as any)?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: any) => d?.msg || JSON.stringify(d)).join("; ")
          : (data as any)?.message || `Request failed (${res.status})`,
    );
  }
  return data as T;
}

const post = (path: string, body?: unknown) =>
  api(path, { method: "POST", body: JSON.stringify(body ?? {}) });

export const brain = {
  // auth
  login: (email: string, password: string) => post("/v1/auth/login", { email, password }),
  register: (body: Record<string, unknown>) => post("/v1/auth/register", body),
  me: () => api("/v1/auth/me"),

  // merchant intelligence
  health: () => api("/v1/merchant/health"),
  state: () => api("/v1/merchant/state"),
  cashflow: () => api("/v1/merchant/cashflow"),
  risks: () => api("/v1/merchant/risks"),
  money: () => api("/v1/merchant/unresolved-money"),
  attention: () => api("/v1/merchant/attention"),
  why: () => api("/v1/merchant/why"),
  features: () => api("/v1/merchant/features"),
  profile: () => api("/v1/merchant/profile"),
  recommendations: () => api("/v1/merchant/recommendations"),
  cycle: () => post("/v1/merchant/cycle"),

  // policy & memory
  policy: () => api("/v1/merchant/policy"),
  savePolicy: (body: Record<string, unknown>) =>
    api("/v1/merchant/policy", { method: "PUT", body: JSON.stringify(body) }),
  memories: () => api("/v1/merchant/memories"),
  addMemory: (kind: string, text: string, structured: Record<string, unknown> = {}) =>
    post("/v1/merchant/memories", { kind, text, structured }),

  // agents
  orchestrate: () => post("/v1/orchestrate"),
  performance: () => api("/v1/agent-performance"),
  agentRuns: () => api("/v1/agent-runs"),
  agentRegistry: () => api("/internal/agents"),
  agentPropose: (agentId: string) => post(`/internal/agents/${agentId}/propose`),
  agentHealth: (agentId: string) => api(`/internal/agents/${agentId}/health`),

  // simulation
  simulate: (actions: unknown[], horizon_hours = 48) =>
    post("/v1/simulations", { actions, horizon_hours }),
  compare: (options: unknown[], horizon_hours = 48) =>
    post("/v1/simulations/compare", { options, horizon_hours }),

  // copilot
  ask: (message: string, actions?: unknown[]) =>
    post("/v1/copilot/ask", { message, actions: actions || [] }),

  // actions & approvals
  actions: () => api("/v1/actions"),
  action: (id: string) => api(`/v1/actions/${id}`),
  createAction: (body: Record<string, unknown>) => post("/v1/actions", body),
  approve: (actionId: string, token?: string) => post(`/v1/actions/${actionId}/approve`, { token }),
  reject: (actionId: string, token?: string) => post(`/v1/actions/${actionId}/reject`, { token }),
  actOnRecommendation: (id: string) => post(`/v1/merchant/recommendations/${id}/act`),

  // events
  events: (params: { event_type?: string; limit?: number } = {}) => {
    const q = new URLSearchParams();
    if (params.event_type) q.set("event_type", params.event_type);
    q.set("limit", String(params.limit ?? 100));
    return api(`/v1/events?${q.toString()}`);
  },
  ingest: (body: Record<string, unknown>) => post("/v1/events", body),

  // admin console
  system: () => api("/v1/admin/system"),
  analytics: (days = 30) => api(`/v1/admin/analytics?days=${days}`),
  stateHistory: (limit = 60) => api(`/v1/admin/state-history?limit=${limit}`),
  collections: () => api("/v1/admin/collections"),
  browse: (name: string, opts: { q?: string; limit?: number; skip?: number } = {}) => {
    const q = new URLSearchParams();
    if (opts.q) q.set("q", opts.q);
    q.set("limit", String(opts.limit ?? 50));
    q.set("skip", String(opts.skip ?? 0));
    return api(`/v1/admin/collections/${name}?${q.toString()}`);
  },
  audit: (limit = 120) => api(`/v1/admin/audit?limit=${limit}`),
  approvals: () => api("/v1/admin/approvals"),
  causal: () => api("/v1/admin/causal"),
  adminAgents: () => api("/v1/admin/agents"),
  pipeline: () => api("/v1/admin/pipeline"),
  lastSelfTest: () => api("/v1/admin/self-test"),
  selfTest: (includeMutating: boolean) => post("/v1/admin/self-test", { include_mutating: includeMutating }),
};

export const EVENT_TYPES = [
  "payment.captured",
  "payment.failed",
  "payment.authorized",
  "payment.refunded",
  "order.created",
  "order.paid",
  "order.cancelled",
  "subscription.payment_failed",
  "subscription.recovered",
  "dispute.created",
  "dispute.resolved",
  "settlement.created",
  "settlement.delayed",
  "settlement.processed",
  "payout.created",
  "payout.completed",
  "payout.delayed",
  "invoice.created",
  "invoice.paid",
  "invoice.overdue",
  "payroll.scheduled",
  "customer.created",
  "customer.returned",
  "refund.created",
  "refund.processed",
  "cash.adjusted",
] as const;

export const ACTION_TYPES = [
  "observe",
  "invoice.dunning.draft",
  "receivable.recover",
  "payment.retry",
  "payout.delay",
  "retry.config.update",
  "refund.create",
  "payout.create",
] as const;
