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
    const detail = (body as { detail?: unknown })?.detail;
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail ?? body));
  }
  return body as T;
}

export const json = (data: unknown, method = "POST"): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(data),
});
