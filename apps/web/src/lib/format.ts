// 纯函数：状态文案与比率格式化。单独测试。
export type Ratio = { numerator: number; denominator: number; value: number | null; note: string | null };

export function formatRatio(r: Ratio): string {
  if (r.denominator === 0 || r.value === null) return `${r.numerator}/${r.denominator}（不适用）`;
  return `${r.numerator}/${r.denominator} = ${(r.value * 100).toFixed(1)}%`;
}

export const STATUS_LABEL: Record<string, string> = {
  pending: "待处理",
  running: "运行中",
  succeeded: "成功",
  needs_review: "需人工",
  failed: "失败",
  fetched: "已获取",
  draft: "草稿",
  approved: "已审批",
  rejected: "已驳回",
  opened: "已打开",
  sent_manual: "已人工发送",
  paused: "已暂停",
  cancelled: "已取消",
  unknown: "未知",
  company: "公司",
  sole_trader: "个体经营",
  other: "其他",
  allowed: "允许",
  blocked: "禁止",
  valid: "有效",
  invalid: "无效",
};

export const CHANNEL_LABEL: Record<string, string> = {
  email: "邮件",
  phone: "电话",
  whatsapp: "WhatsApp",
  instagram: "Instagram",
  facebook: "Facebook",
  tiktok: "TikTok",
  other_social: "其他社媒",
  contact_form: "联系表单",
  post: "邮寄",
};

export function label(s: string | null | undefined): string {
  if (!s) return "-";
  return STATUS_LABEL[s] ?? s;
}

export function approvalText(valid: boolean, reason: string | null): string {
  return valid ? "审批有效" : `审批无效：${reason ?? "未审批"}`;
}
