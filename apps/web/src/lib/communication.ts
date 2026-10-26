import { AutoAdmission, ContactAssessment } from "@/lib/contact-ranking";
export type Progress = { status: string; contact_selected?: boolean; content_selected?: boolean; task_id?: string | null; draft_id?: string | null };
export const PROGRESS: Record<string, string> = { recorded: "已有沟通记录", not_started: "未准备", preparing: "准备中", pending: "待执行", awaiting_send: "待确认发送", queued: "排队中", sending: "发送中", send_failed: "发送失败", send_unknown: "结果待查询", waiting_reply: "等待回复", replied: "已回复", paused: "已暂停", suppressed: "已抑制" };
export const CHANNELS = [{ value: "phone", label: "电话" }, { value: "whatsapp", label: "WhatsApp" }, { value: "contact_form", label: "联系表单" }, { value: "post", label: "邮寄" }, { value: "email", label: "Gmail／邮箱" }, { value: "tiktok", label: "TikTok" }, { value: "linkedin", label: "LinkedIn" }, { value: "facebook", label: "Facebook" }, { value: "instagram", label: "Instagram" }];
export const MODES = [{ value: "manual", label: "人工执行" }, { value: "gmail", label: "Gmail 接口" }, { value: "social", label: "已授权 FB／INS 会话" }];
export type Contact = { contact_conditions?: {status: string; missing: string[]}; auto_admission?: AutoAdmission | null; recommendation?: ContactAssessment | null; id: string; channel: string; contact_ref: string | null; contact_source: string | null; contact_usable: string; eligibility: string; rule_version?: string | null; evidence?: string | null; review_due_at?: string | null; suppressed: boolean };
export type Message = { subject?: string; rationale?: string; missing?: string[]; sources?: {id: string; text: string}[]; engine?: string; analysis_id?: string | null; mode?: "menu_inquiry" | "menu_analysis"; id: string; version: number; body_text: string | null; approved: boolean; reason: string | null };
export type CommunicationTask = { id: string; lead_id: string; eligibility_id: string; content_id: string; channel: string; status: string; status_reason: string | null; execution_mode: string; assigned_to: string | null; follow_up_at: string | null; sent_at: string | null; preparation_group_id?: string | null };
export type LeadContext = { lead: { id: string; name: string; website: string | null; address: string | null; postcode: string | null }; contacts: Contact[]; contents: Message[]; analyses: { id: string; version: number; facts: string[]; label?: string }[]; tasks: CommunicationTask[]; progress: Progress; drafts?: Draft[] };
export type Draft = { queued?: boolean; id: string; lead_id: string; channel: string; execution_mode: string; eligibility_id: string | null; content_id: string | null; assigned_to: string | null; follow_up_at: string | null; purpose: string; notes: string | null; status: string; task_id: string | null; blockers: string[]; context: LeadContext };
export type Prepared = { lead_id: string; name?: string; draft: Draft | null; existing_task?: CommunicationTask | null; error?: string; activated_task_id?: string };
export type Assignee = { username: string; display_name: string | null };
export function safeReturnTo(value?: string | null): string {
  if (!value || !value.startsWith("/") || value.includes("\\")) return "/leads";
  try { const url = new URL(value, "https://beacon.local"); return url.origin === "https://beacon.local" && (url.pathname === "/leads" || /^\/leads\/[a-f0-9-]{36}$/.test(url.pathname)) ? url.pathname + url.search + url.hash : "/leads"; } catch { return "/leads"; }
}
export function taskLink(options: { lead?: string; task?: string | null; draft?: string | null; batch?: string; channel?: string; preparation?: string; returnTo?: string; tab?: string }): string {
  const query = new URLSearchParams();
  Object.entries(options).forEach(([key, value]) => { if (value) query.set(key, key === "returnTo" ? safeReturnTo(value) : value); });
  return "/tasks?" + query.toString();
}
