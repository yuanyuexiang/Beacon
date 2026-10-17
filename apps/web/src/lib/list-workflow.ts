import { api } from "./api";
export type ListWorkflow = {
  id: string; batch_id: string; kind: "create" | "enrich" | "append";
  status: "pending" | "running" | "failed" | "completed" | "cancelled";
  step: number; steps: string[]; params: { authority_name?: string; sample_n?: number | null; business_type_ids?: number[] };
  results: Record<string, unknown>[]; error: string | null;
};
export const workflowBlocksActions = (task: ListWorkflow | null) => !!task && ["pending", "running"].includes(task.status);
export const workflowUnfinished = (task: ListWorkflow | null) => !!task && !["completed", "cancelled"].includes(task.status);
export const WORKFLOW_TITLES: Record<string, string> = { pool: "从门店池选入商户", fsa: "获取商户", overture: "补充官网与电话", google: "Google Places 按需补充", screen: "客户筛选策略", contacts: "查找联系方式" };
export function workflowSummary(stage: string, result?: Record<string, unknown>): string | undefined {
  if (!result) return undefined;
  if (stage === "fsa" || stage === "pool") return `名录 ${result.fetched} 家，已有 ${result.already_in_list ?? 0} 家，剩余可选 ${result.pool} 家，本次选入 ${result.selected} 家（新增 ${result.created}，关联已有 ${result.linked}）`;
  if (stage === "overture") return `匹配 ${result.matched}/${result.leads}，补官网 ${result.website_set}，有电话 ${result.phone_found}`;
  if (stage === "google") return `官网核验通过 ${result.verified ?? 0}，待复核 ${result.review ?? 0}，失败 ${result.failed ?? 0}${result.note ? `；${result.note}` : ""}`;
  if (stage === "screen") return "按保存的策略预筛，人工确认保留；待复核继续查找联系方式";
  const t = result.totals as Record<string, number> | undefined;
  if (t && stage === "contacts" && "read_complete" in t) return `读取完成 ${t.read_complete}，部分读取 ${t.read_partial ?? 0}，读取失败 ${t.read_failed ?? 0}${t.no_website ? `，无官网 ${t.no_website}` : ""}${t.read_unknown ? `，读取情况待确认 ${t.read_unknown}` : ""}；找到联系方式 ${t.with_contacts ?? 0} 家；待处理 ${(t.pending ?? 0) + (t.running ?? 0)}`;
  return t ? `成功 ${t.succeeded ?? 0}，失败 ${t.failed ?? 0}，待处理 ${(t.pending ?? 0) + (t.running ?? 0)}` : undefined;
}

// FSA 全量名单可能超过单页 500 条；读完整名单后统一展示与统计。
export async function getAllBatchLeads<T>(key: string): Promise<T[]> {
  const rows: T[] = [];
  for (let offset = 0; ; offset += 500) {
    const page = await api<T[]>(`/api/leads?batch_key=${encodeURIComponent(key)}&limit=500&offset=${offset}`);
    rows.push(...page);
    if (page.length < 500) return rows;
  }
}

export function contactFailureLabel(error: string): string {
  if (/SSL|TLS|CERTIFICATE/i.test(error)) return "HTTPS／SSL 连接中断或证书错误";
  if (/timeout|timed out/i.test(error)) return "网站连接或读取超时";
  if (/HTTP 403/.test(error)) return "网站拒绝访问（403）";
  if (/HTTP 429/.test(error)) return "网站限制访问频率（429）";
  if (/HTTP 5\d\d/.test(error)) return "网站或上游网关异常（5xx）";
  if (/HTTP 404/.test(error)) return "页面不存在（404）";
  if (/Connect|DNS|NameResolution|gaierror/i.test(error)) return "网络连接或域名解析失败";
  if (/HTTP 200/.test(error)) return "链接内容不是可读取的网页";
  return "页面未完全读取，展开查看记录";
}
