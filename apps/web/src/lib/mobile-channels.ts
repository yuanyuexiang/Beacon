export const MOBILE_ACTIONS: Record<string, { value: string; label: string }[]> = {
  whatsapp: [{ value: 'direct_message', label: '发送消息' }],
  facebook: [{ value: 'direct_message', label: '发送私信' }, { value: 'message_request', label: '提交消息请求' }],
  instagram: [{ value: 'direct_message', label: '发送私信' }, { value: 'message_request', label: '提交消息请求' }],
  linkedin: [{ value: 'direct_message', label: '发送私信' }, { value: 'connection_request', label: '申请连接（手机处理）' }, { value: 'inmail', label: 'InMail（手机核对费用）' }],
  tiktok: [{ value: 'direct_message', label: '发送私信' }, { value: 'message_request', label: '提交消息请求' }],
  youtube: [{ value: 'contact_discovery', label: '查看频道联系入口' }, { value: 'direct_message', label: '已有消息会话' }],
  x: [{ value: 'direct_message', label: '发送私信' }, { value: 'message_request', label: '提交消息请求' }],
};
// Public posting is an explicit task action, never a private-message fallback.
for (const channel of ['facebook', 'instagram', 'linkedin', 'tiktok', 'youtube', 'x']) {
  MOBILE_ACTIONS[channel].push({value:'public_comment',label:'作品公开留言'});
}
export const MOBILE_LABELS: Record<string, string> = { whatsapp: 'WhatsApp', facebook: 'Facebook', instagram: 'Instagram', linkedin: 'LinkedIn', tiktok: 'TikTok', youtube: 'YouTube', x: 'X' };
export function pairingAddress(current: string, saved: string | null, origin: string, configured?: string): string {
  if (current.trim()) return current;
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(new URL(origin).hostname);
  return local ? saved || configured || '' : origin;
}
export type ExecutionPhone = { id: string; label: string; status: string; online?: boolean; capabilities?: { protocol?: number; installed?: string[]; accounts?: Record<string,string>; accessibility?: boolean; unlocked?: boolean | null } };
export function phoneUnavailableReason(phone: ExecutionPhone, platform?: string): string | undefined {
  if (phone.status === 'revoked') return '已解除绑定';
  if (!phone.online) return '离线，请打开手机助手连接平台';
  if ((phone.capabilities?.protocol || 1) < 2 && platform !== 'whatsapp') return '请更新手机助手';
  if ((phone.capabilities?.protocol || 1) >= 2 && (!platform || !phone.capabilities?.installed?.includes(platform))) return `未安装 ${MOBILE_LABELS[platform || ''] || '对应应用'}`;
  if (phone.capabilities?.accessibility === false) return '请开启 Beacon 无障碍服务';
  if (phone.status !== 'ready') return '在线，待开启执行：请在手机任务页点击“连接并检查任务”';
  return undefined;
}
export function mobilePlatform(channel: string, contact?: string | null): string | undefined {
  if (channel !== 'other_social') return MOBILE_ACTIONS[channel] ? channel : undefined;
  try { const host = new URL(contact || '').hostname.toLowerCase().replace(/^(www|m)\./, ''); return host === 'youtube.com' ? 'youtube' : ['x.com', 'twitter.com'].includes(host) ? 'x' : undefined; } catch { return undefined; }
}

export function defaultExecutionMode(channel: string): string {
  return channel === 'email' ? 'gmail' : MOBILE_ACTIONS[channel] || channel === 'other_social' ? 'mobile' : 'manual';
}

export function pairingServer(value: string): string {
  const u = new URL(value.trim());
  const parts = u.hostname.split('.').map(Number);
  const ipv4 = parts.length === 4 && parts.every(v => Number.isInteger(v) && v >= 0 && v <= 255);
  const lan = ipv4 && (parts[0] === 10 || parts[0] === 192 && parts[1] === 168 || parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31);
  const usb = u.hostname === '127.0.0.1' && u.port === '8000';
  if (u.protocol !== 'https:' && !(u.protocol === 'http:' && (lan || usb))) throw new Error('云端使用 HTTPS；局域网填写电脑 IP，例如 http://192.168.1.100:8000');
  if (u.username || u.password || u.pathname !== '/' || u.search || u.hash) throw new Error('只填写服务器根地址');
  return u.origin;
}

export function phoneStatusLabel(phone: ExecutionPhone): string {
  if (phone.status === 'revoked') return '已解除';
  if (!phone.online) return '离线';
  if (phone.status === 'ready') return phone.capabilities?.unlocked === false ? '在线 · 等待解锁' : '在线 · 执行就绪';
  return '在线 · 执行已暂停';
}
