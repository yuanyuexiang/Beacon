import { expect, it } from 'vitest';
import { mobilePlatform, MOBILE_ACTIONS, defaultExecutionMode, phoneUnavailableReason } from '../src/lib/mobile-channels';
it('explains connected but paused phones without requiring a recorded Facebook name', () => {
  const phone = {id:'phone',label:'Xiaomi',online:true,status:'paired',capabilities:{protocol:2,installed:['facebook'],accessibility:true}};
  expect(phoneUnavailableReason(phone,'facebook')).toContain('待开启执行');
  expect(phoneUnavailableReason({...phone,status:'ready'},'facebook')).toBeUndefined();
  expect(phoneUnavailableReason({...phone,status:'ready',online:false},'facebook')).toContain('离线');
  expect(phoneUnavailableReason(phone,'tiktok')).toContain('未安装 TikTok');
  expect(phoneUnavailableReason({...phone,capabilities:{...phone.capabilities,installed:['whatsapp']}},'whatsapp')).toContain('本方号码');
});
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

it('defaults social preparation to phones while email retains Gmail', () => {
  for (const channel of ['facebook', 'instagram', 'whatsapp', 'linkedin', 'tiktok', 'other_social']) expect(defaultExecutionMode(channel)).toBe('mobile');
  expect(defaultExecutionMode('email')).toBe('gmail');
  expect(defaultExecutionMode('phone')).toBe('manual');
  expect(defaultExecutionMode('contact_form')).toBe('manual');
});
