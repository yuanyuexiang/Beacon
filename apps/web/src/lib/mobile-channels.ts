export const MOBILE_ACTIONS: Record<string, { value: string; label: string }[]> = {
  whatsapp: [{ value: 'direct_message', label: '发送消息' }],
  facebook: [{ value: 'direct_message', label: '发送私信' }, { value: 'message_request', label: '提交消息请求' }],
  instagram: [{ value: 'direct_message', label: '发送私信' }, { value: 'message_request', label: '提交消息请求' }],
  linkedin: [{ value: 'direct_message', label: '发送私信' }, { value: 'connection_request', label: '申请连接（手机处理）' }, { value: 'inmail', label: 'InMail（手机核对费用）' }],
  tiktok: [{ value: 'direct_message', label: '发送私信' }, { value: 'message_request', label: '提交消息请求' }],
  youtube: [{ value: 'contact_discovery', label: '查看频道联系入口' }, { value: 'direct_message', label: '已有消息会话' }],
  x: [{ value: 'direct_message', label: '发送私信' }, { value: 'message_request', label: '提交消息请求' }],
};
export const MOBILE_LABELS: Record<string, string> = { whatsapp: 'WhatsApp', facebook: 'Facebook', instagram: 'Instagram', linkedin: 'LinkedIn', tiktok: 'TikTok', youtube: 'YouTube', x: 'X' };
export function mobilePlatform(channel: string, contact?: string | null): string | undefined {
  if (channel !== 'other_social') return MOBILE_ACTIONS[channel] ? channel : undefined;
  try { const host = new URL(contact || '').hostname.toLowerCase().replace(/^(www|m)\./, ''); return host === 'youtube.com' ? 'youtube' : ['x.com', 'twitter.com'].includes(host) ? 'x' : undefined; } catch { return undefined; }
}
