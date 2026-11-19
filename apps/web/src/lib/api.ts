// 统一 API 调用：同源 /api（由 next.config 重写到后端），携带会话 cookie；错误抛出后端 detail。
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, { credentials: "include", ...init });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let body: unknown = text;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    /* 非 JSON */
  }
  if (!res.ok) {
    if (typeof window !== "undefined" && path !== "/api/auth/login") {
      if (res.status === 401) window.dispatchEvent(new Event("beacon-auth-invalid"));
      if (res.headers.get("X-Beacon-Action") === "change-password") window.dispatchEvent(new Event("beacon-password-required"));
    }
    const detail = (body as { detail?: unknown })?.detail;
    const value = body && typeof body === "object" && "detail" in body ? detail : body;
    const fallback = `请求失败（HTTP ${res.status}），服务器未返回有效说明，请重试或联系管理员`;
    const message = typeof value === "string"
      ? (value.trim() && value.trim() !== "null" ? value : fallback)
      : value == null ? fallback : JSON.stringify(value);
    throw new ApiError(res.status, message);
  }
  return body as T;
}

export const json = (data: unknown, method = "POST"): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(data),
});
