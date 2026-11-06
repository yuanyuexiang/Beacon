export const CHANNELS = [
  { id: 'whatsapp', label: 'WhatsApp', hint: '+国家区号与电话号码' },
  { id: 'facebook', label: 'Facebook / Messenger', hint: '本方主页链接或账号名称' },
  { id: 'instagram', label: 'Instagram', hint: '本方 @用户名或主页链接' },
  { id: 'linkedin', label: 'LinkedIn', hint: '本方个人主页链接' },
  { id: 'tiktok', label: 'TikTok', hint: '本方 @用户名或主页链接' },
  { id: 'youtube', label: 'YouTube', hint: '本方频道链接或 @名称' },
  { id: 'x', label: 'X', hint: '本方 @用户名或主页链接' },
];
export const channelLabel = (channel = 'whatsapp') => CHANNELS.find(c => c.id === channel)?.label || channel;
export const ACTIONS: Record<string, string> = { direct_message: '发送私信', message_request: '提交消息请求', connection_request: '申请连接', inmail: '发送 InMail', contact_discovery: '查看频道联系入口' };
