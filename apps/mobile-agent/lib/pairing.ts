export type PairingTicket = { type: 'beacon-pair'; version: 1; server: string; code: string; expires_at: string; owner: string };
export function pairingServer(value: string): string {
  const u = new URL(value.trim());
  if (u.protocol !== 'https:' && !(u.protocol === 'http:' && u.hostname === '127.0.0.1' && u.port === '8000')) throw new Error('请使用 HTTPS 服务器；USB 本地测试只支持 http://127.0.0.1:8000');
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
