import { api } from "./api";
export type ListWorkflow = {
  id: string; batch_id: string; kind: "create" | "enrich" | "append";
  status: "pending" | "running" | "failed" | "completed" | "cancelled";
  step: number; steps: string[]; params: { authority_name?: string; sample_n?: number | null; business_type_ids?: number[] };
  results: Record<string, unknown>[]; error: string | null;
};
export const workflowBlocksActions = (task: ListWorkflow | null) => !!task && ["pending", "running"].includes(task.status);
export const workflowUnfinished = (task: ListWorkflow | null) => !!task && !["completed", "cancelled"].includes(task.status);
export const WORKFLOW_TITLES: Record<string, string> = { fsa: "获取商户", overture: "补充官网与电话", screen: "规则预筛", contacts: "查找联系方式" };
export function workflowSummary(stage: string, result?: Record<string, unknown>): string | undefined {
  if (!result) return undefined;
  if (stage === "fsa") return `名录 ${result.fetched} 家，已有 ${result.already_in_list ?? 0} 家，剩余可选 ${result.pool} 家，本次选入 ${result.selected} 家（新增 ${result.created}，关联已有 ${result.linked}）`;
  if (stage === "overture") return `匹配 ${result.matched}/${result.leads}，补官网 ${result.website_set}，有电话 ${result.phone_found}`;
  if (stage === "screen") return "仅预筛未确认的门店，已有判断保留";
  const t = result.totals as Record<string, number> | undefined;
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
