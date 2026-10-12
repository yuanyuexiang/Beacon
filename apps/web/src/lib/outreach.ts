export type ChannelAccount = {
  id: string; platform: "facebook" | "instagram"; label: string; auth_mode: string;
  sender_id: string; page_id?: string | null; connected: boolean; sending_enabled: boolean;
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
  if (!conversation?.window_open || !account?.connected || conversation.account_id !== account.id || !account.capabilities.includes("text_reply")) return [];
  return tasks.filter((task) => task.channel === account.platform && task.lead_id === conversation.lead_id &&
    task.eligibility_id === conversation.eligibility_id && ["pending", "opened"].includes(task.status));
}
