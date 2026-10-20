import type { Progress } from "./communication";

export const MENU_STATES: Record<string, string> = { missing: "暂未获取", analysis_failed: "分析失败", failed: "获取失败", fetching: "获取中", obtained: "已获取", analyzing: "分析中", needs_review: "待核对", reviewed: "已核对" };
export type ListSummary = { menu_status: string; channels: string[] };
export function leadNextAction(lead: { contact_count: number; communication_progress?: Progress; list_summary?: ListSummary | null }) {
  const p = lead.communication_progress;
  const status = p?.status || "not_started";
  if (status === "suppressed") return { text: "停止触达", target: "tasks" };
  if (status === "replied") return { text: "处理客户回复", target: "tasks" };
  if (status === "waiting_reply") return { text: "查看回复／安排跟进", target: "tasks" };
  if (status === "paused") return { text: "查看暂停原因", target: "tasks" };
  if (status === "pending") return { text: "确认并执行触达", target: "tasks" };
  if (status === "recorded") return { text: "查看沟通记录", target: "tasks" };
  if (!lead.contact_count) return { text: "补充联系方式", target: "contacts" };
  if (status === "preparing" && p?.contact_selected === false) return { text: "选择联系方式", target: "prepare" };
  if (status === "preparing" && p?.content_selected === false) return { text: "准备并审批文案", target: "prepare" };
  if (status === "preparing") return { text: "检查文案与渠道准入", target: "prepare" };
  if (lead.list_summary?.menu_status === "needs_review") return { text: "核对菜单／准备文案", target: "detail" };
  if (["missing", "failed"].includes(lead.list_summary?.menu_status || "")) return { text: "准备菜单询问", target: "prepare" };
  return { text: "选择渠道并准备文案", target: "prepare" };
}
