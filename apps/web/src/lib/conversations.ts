export type ConversationMessage = {
  id: string; task_id?: string; event_id?: string; direction: string; channel: string | null;
  at: string; arrived_at: string; body: string; subject?: string; status: string; source: string;
  error?: string; headers_only?: boolean;
  deliveries: { id: string; status: string; source: string; error?: string; at: string }[];
};
export type ContactConversation = {
  id: string; channel: string | null; contact_ref: string | null; unread: number;
  read_through: string | null; messages: ConversationMessage[];
};
export const MESSAGE_STATES: Record<string,string> = {
  pending: "待确认", opened: "已打开联系入口", paused: "已暂停", cancelled: "已结束",
  preview: "待确认", expired: "预览已过期", ready: "排队中", queued: "排队中", queued_paused: "队列暂停",
  sending: "发送中", claimed: "手机已领取", executing: "手机执行中", sent: "已发送",
  sent_manual: "已发送", sent_email: "已发送", sent_social: "已发送", request_submitted: "请求已提交",
  failed: "发送失败", blocked: "未能发送", unknown: "结果待核对", needs_user: "需要手机处理",
  reply: "客户回复", note: "沟通备注", unsubscribe: "退订", reject: "拒绝联系", bounce: "退信",
};
