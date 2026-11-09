import { describe, expect, it } from 'vitest';
import { pairingAddress, pairingServer as webServer } from '../src/lib/mobile-channels';
import { pairingServer, parsePairingTicket } from '../../mobile-agent/lib/pairing';
const now = Date.parse('2026-11-05T00:00:00Z');
const ticket = { type: 'beacon-pair', version: 1, server: 'https://beacon.example.com', code: '012345', owner: 'sales', expires_at: '2026-11-05T00:05:00Z' };
describe('phone pairing QR input', () => {
  it('keeps an edited or saved LAN address when refreshing a code with stale server configuration', () => {
    const old = 'http://192.168.3.103:8000';
    const current = 'http://192.168.86.32:8000';
    expect(pairingAddress(current, old, 'http://localhost:3000', old)).toBe(current);
    expect(pairingAddress('', current, 'http://localhost:3000', old)).toBe(current);
    expect(pairingAddress('', null, 'http://localhost:3000', old)).toBe(old);
    expect(pairingAddress('', old, 'https://beacon.example.com', old)).toBe('https://beacon.example.com');
  });
  it('preserves leading-zero codes and USB/server addresses', () => {
    expect(parsePairingTicket(JSON.stringify(ticket), now).code).toBe('012345');
    expect(pairingServer('http://127.0.0.1:8000/')).toBe('http://127.0.0.1:8000');
    for (const server of ['http://192.168.1.100:8000', 'http://10.180.8.175:8000', 'http://172.16.1.2:3000']) { expect(pairingServer(server)).toBe(server); expect(webServer(server)).toBe(server); }
  });
  it('rejects stale, unrelated or incomplete codes before any network request', () => {
    for (const raw of ['https://example.com', 'null', JSON.stringify({ ...ticket, version: 2 }), JSON.stringify({ ...ticket, owner: '' }), JSON.stringify({ ...ticket, code: '12345' })]) expect(() => parsePairingTicket(raw, now)).toThrow();
    expect(() => parsePairingTicket(JSON.stringify(ticket), now + 300000)).toThrow('过期');
  });
  it('does not send pairing credentials to insecure or embedded-credential URLs', () => {
    for (const server of ['http://example.com', 'http://172.32.1.2:8000', 'http://192.169.1.2:8000', 'http://127.0.0.1:9000', 'https://user:pass@example.com', 'https://example.com/api', 'https://example.com?x=1', 'file:///tmp/a']) expect(() => parsePairingTicket(JSON.stringify({ ...ticket, server }), now)).toThrow();
  });
});
