export type PairingTicket = { type: 'beacon-pair'; version: 1; server: string; code: string; expires_at: string; owner: string };
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
export function parsePairingTicket(raw: string, now = Date.now()): PairingTicket {
  if (raw.length > 4096) throw new Error('这不是 Beacon 配对二维码');
  let p: PairingTicket;
  try { p = JSON.parse(raw); } catch { throw new Error('请扫描 Beacon 网页“绑定手机”中的二维码'); }
  if (!p || p.type !== 'beacon-pair' || p.version !== 1 || typeof p.server !== 'string' || typeof p.code !== 'string' || !/^\d{6}$/.test(p.code) || typeof p.owner !== 'string' || !p.owner.trim() || p.owner.length > 128) throw new Error('配对二维码不完整，请在网页重新生成');
  const expiry = Date.parse(p.expires_at);
  if (!Number.isFinite(expiry) || expiry <= now) throw new Error('二维码已过期，请在网页刷新配对码');
  return { ...p, server: pairingServer(p.server) };
}
