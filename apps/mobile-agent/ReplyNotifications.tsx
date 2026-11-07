import React, { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import Executor from './modules/beacon-executor';
import { CHANNELS } from './lib/channels';

export default function ReplyNotifications() {
  const [status, setStatus] = useState<ReturnType<typeof Executor.notificationStatus>>(() => Executor.notificationStatus());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  function refresh() { try { setStatus(Executor.notificationStatus()); } catch (e) { setError(String(e)); } }
  useEffect(() => { const timer = setInterval(refresh, 3000); return () => clearInterval(timer); }, []);
  const channels: string[] = status ? JSON.parse(status.channels) : [];
  function toggle(channel: string) {
    try { Executor.notificationChannels(JSON.stringify(channels.includes(channel) ? channels.filter(c => c !== channel) : [...channels, channel])); refresh(); }
    catch (e) { setError(String(e)); }
  }
  return <View style={styles.card}>
    <Text style={styles.heading}>客户回复通知</Text>
    <Text>先在下方选择 Facebook 等渠道，再给“Beacon 手机助手”开启系统通知使用权。系统列表中不需要找 Facebook。只处理开启之后的新消息，不读取通知历史或自动回复。</Text>
    <Text>首次回复在网页“触达任务与回复 → 手机回复”关联门店；稳定会话后续回复可自动回填。群聊和汇总通知不回填。</Text>
    <Text>系统权限：{status?.granted ? '已开启' : '未开启'} · 监听服务：{status?.connected ? '已连接' : '等待系统连接'} · 待上传：{status?.pending || 0}</Text>
    <View style={styles.channels}>{CHANNELS.map(c => <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: channels.includes(c.id) }} key={c.id} style={[styles.choice, channels.includes(c.id) && styles.selected]} onPress={() => toggle(c.id)}><Text>{channels.includes(c.id) ? '✓ ' : '○ '}{c.label}</Text></Pressable>)}</View>
    {!channels.length && <Text>监听已关闭。先选择本次要测试的 Facebook 即可。</Text>}
    <Pressable style={styles.button} onPress={() => Executor.notificationSettings()}><Text style={styles.white}>给 Beacon 开启通知使用权</Text></Pressable>
    <Pressable disabled={busy || !status?.granted || !channels.length} style={styles.choice} onPress={async () => { setBusy(true); try { await Executor.syncNotifications(); refresh(); } finally { setBusy(false); } }}><Text>{busy ? '同步中…' : '同步待上传通知'}</Text></Pressable>
    {!!channels.length && <Pressable style={styles.choice} onPress={() => { Executor.notificationChannels('[]'); refresh(); }}><Text>关闭监听并清除本机待上传通知</Text></Pressable>}
    {!!(error || status?.error) && <Text>{error || status?.error}</Text>}
    <Text style={styles.small}>通知隐藏正文、平台不发通知或系统限制后台时可能漏收，仍可从“记录”手动回填。更换社媒登录账号前，请在网页解除旧会话关联。不会触发发送。</Text>
  </View>;
}
const styles = StyleSheet.create({ card: { padding: 20, borderRadius: 16, backgroundColor: '#fff', gap: 12 }, heading: { fontSize: 19, fontWeight: '700' }, small: { color: '#777', lineHeight: 21 }, channels: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 }, choice: { borderWidth: 1, borderColor: '#ddd', borderRadius: 8, padding: 12 }, selected: { backgroundColor: '#fff3f3', borderColor: '#cf010e' }, button: { backgroundColor: '#cf010e', borderRadius: 8, padding: 14, alignItems: 'center' }, white: { color: '#fff', fontWeight: '600' } });
