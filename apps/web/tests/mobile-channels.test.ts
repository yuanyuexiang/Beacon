import { expect, it } from 'vitest';
import { mobilePlatform, MOBILE_ACTIONS } from '../src/lib/mobile-channels';
it('shows actual platform names and never treats arbitrary links as phone channels', () => {
  expect(mobilePlatform('other_social', 'https://www.youtube.com/@shop')).toBe('youtube');
  expect(mobilePlatform('other_social', 'https://x.com/shop')).toBe('x');
  expect(mobilePlatform('other_social', 'https://youtube.com.evil.test/shop')).toBeUndefined();
  expect(mobilePlatform('email', 'mail@example.com')).toBeUndefined();
});
it('exposes explicit requests without a hidden public-comment fallback', () => {
  expect(MOBILE_ACTIONS.linkedin.map(a => a.value)).toContain('inmail');
  expect(MOBILE_ACTIONS.youtube[0].value).toBe('contact_discovery');
  expect(Object.values(MOBILE_ACTIONS).flat().some(a => a.value === 'comment')).toBe(false);
});
