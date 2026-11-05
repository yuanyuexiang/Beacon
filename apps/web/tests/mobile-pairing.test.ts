import { describe, expect, it } from 'vitest';
import { pairingServer, parsePairingTicket } from '../../mobile-agent/lib/pairing';
const now = Date.parse('2026-11-05T00:00:00Z');
const ticket = { type: 'beacon-pair', version: 1, server: 'https://beacon.example.com', code: '012345', owner: 'sales', expires_at: '2026-11-05T00:05:00Z' };
describe('phone pairing QR input', () => {
  it('preserves leading-zero codes and USB/server addresses', () => {
    expect(parsePairingTicket(JSON.stringify(ticket), now).code).toBe('012345');
    expect(pairingServer('http://127.0.0.1:8000/')).toBe('http://127.0.0.1:8000');
  });
  it('rejects stale, unrelated or incomplete codes before any network request', () => {
    for (const raw of ['https://example.com', 'null', JSON.stringify({ ...ticket, version: 2 }), JSON.stringify({ ...ticket, owner: '' }), JSON.stringify({ ...ticket, code: '12345' })]) expect(() => parsePairingTicket(raw, now)).toThrow();
    expect(() => parsePairingTicket(JSON.stringify(ticket), now + 300000)).toThrow('过期');
  });
  it('does not send pairing credentials to insecure or embedded-credential URLs', () => {
    for (const server of ['http://example.com', 'http://127.0.0.1:9000', 'https://user:pass@example.com', 'https://example.com/api', 'https://example.com?x=1', 'file:///tmp/a']) expect(() => parsePairingTicket(JSON.stringify({ ...ticket, server }), now)).toThrow();
  });
});
