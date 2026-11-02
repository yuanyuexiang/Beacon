export type ChannelAccount = {
  id: string; platform: "facebook" | "instagram"; label: string; auth_mode: string;
  sender_id: string; page_id?: string | null; connected: boolean; sending_enabled: boolean;
  connection_diagnostics?: { state: string; updated_at: string; error?: string } | null;
  queue_enabled: boolean; daily_limit: number; capabilities: string[];
};
export type Conversation = {
  id: string; account_id: string; recipient_id: string; lead_id?: string | null;
  eligibility_id?: string | null; last_message?: string | null; last_inbound_at: string;
  window_expires_at: string; window_open: boolean;
};
export type SocialDelivery = {
  id: string; task_id: string; account_id: string; conversation_id: string; status: string;
  preview_key: string; expires_at: string; platform_message_id?: string | null; last_error?: string | null;
  payload: { platform: string; sender_id: string; account_label: string; recipient_id: string; text: string };
};
export const deliveryLabels: Record<string, string> = {
  preview: "待确认", ready: "等待发送", queued: "已入队", sending: "发送中", sent: "平台已接受",
  failed: "发送失败", blocked: "复核未通过", unknown: "结果待确认", expired: "预览已过期", cancelled: "已取消",
};
export function replyCandidates<T extends { channel: string; lead_id: string; eligibility_id: string; status: string }>(
  tasks: T[], conversation: Conversation | undefined, account: ChannelAccount | undefined,
): T[] {
  if (!conversation?.window_open || !account?.connected || !account.sending_enabled || conversation.account_id !== account.id || !account.capabilities.includes("text_reply")) return [];
  return tasks.filter((task) => task.channel === account.platform && task.lead_id === conversation.lead_id &&
    task.eligibility_id === conversation.eligibility_id && ["pending", "opened"].includes(task.status));
}

export function replyIssue(task: { channel: string; lead_id: string; eligibility_id: string; status: string }, conversations: Conversation[], accounts: ChannelAccount[]): string | undefined {
  if (!["pending", "opened"].includes(task.status)) return "任务当前不是待执行状态";
  const connected = accounts.filter(a => a.platform === task.channel && a.connected);
  if (!connected.length) return "请先在设置中连接本方发送账号";
  const linked = conversations.filter(c => c.lead_id === task.lead_id && c.eligibility_id === task.eligibility_id && connected.some(a => a.id === c.account_id));
  if (!linked.length) return "尚未关联对方发来的会话。公共主页链接不能作为 API 收件人；首次联系请返回任务选择人工执行，在平台联系。若对方已发消息，请检查 Webhook 并关联收到的会话。";
  if (!linked.some(c => c.window_open)) return "会话普通回复窗口已过期，等待对方再次发来消息";
  if (!linked.some(c => c.window_open && connected.some(a => a.id === c.account_id && a.capabilities.includes("text_reply")))) return "发送账号尚不支持文字回复，请检查账号权限";
  if (!linked.some(c => c.window_open && connected.some(a => a.id === c.account_id && a.capabilities.includes("text_reply") && a.sending_enabled))) return "发送账号已暂停发送，请在发送设置中开启";
  return undefined;
}
