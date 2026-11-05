import React, { useEffect, useState } from 'react';
import { Alert, AppState, Keyboard, Platform, Pressable, SafeAreaView, ScrollView, StatusBar, StyleSheet, Text, TextInput, View } from 'react-native';
import Executor, { PhoneStatus } from './modules/beacon-executor';

type Job = { id: string; attempt: number; lease: string; snapshot: { target: string; sender: string; body: string; lead_name: string } };
const RED = '#cf010e';
async function request(url: string, options: RequestInit) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `请求失败 ${response.status}`);
    return data;
  } finally { clearTimeout(timer); }
}
export default function App() {
  const [tab, setTab] = useState('工作台');
  const [server, setServer] = useState('https://beacon.ai-onestep.com');
  const [code, setCode] = useState('');
  const [label, setLabel] = useState('我的手机');
  const [account, setAccount] = useState('');
  const [paired, setPaired] = useState(false);
  const [ready, setReady] = useState(false);
  const [status, setStatus] = useState<PhoneStatus>();
  const [job, setJob] = useState<Job>();
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');
  function inspect() {
    try { const s = Executor.status(); setStatus(s); if (s.journal) { const j = JSON.parse(s.journal); if (j.phase === 'claimed' && !j.reported) setJob(j); else if (j.reported) setJob(undefined); } } catch (e) { setNotice(String(e)); }
  }
  useEffect(() => {
    try { const c = Executor.credentials(); if (c.token) { setPaired(true); setServer(c.server); } } catch (e) { setNotice('设备凭据读取失败，请重新配对：' + String(e)); }
    inspect(); const timer = setInterval(inspect, 2000); const sub = AppState.addEventListener('change', s => { if (s === 'active') inspect(); });
    return () => { clearInterval(timer); sub.remove(); };
  }, []);
  async function call(path: string, body: object) {
    const c = Executor.credentials();
    return request(c.server + '/api/mobile/device' + path, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + c.token }, body: JSON.stringify(body) });
  }
  async function action(key: string, fn: () => Promise<void>) { if (busy) return; Keyboard.dismiss(); setBusy(key); setNotice(''); try { await fn(); inspect(); } catch (e) { const message = e instanceof Error ? e.message : String(e); setNotice(message); if (key === 'pair') Alert.alert('未能配对', message); } finally { setBusy(''); } }
  async function heartbeat(active: boolean) { return call('/heartbeat', { account, ready: active, accessibility: Executor.status().accessibility, app_version: '0.1.0', protocol: 1 }); }
  useEffect(() => {
    if (!ready) return;
    const timer = setInterval(() => { if (AppState.currentState === 'active') void heartbeat(true).catch(e => { setReady(false); setNotice(String(e)); }); }, 30000);
    return () => clearInterval(timer);
  }, [ready, account]);
  async function start() {
    if (!/^\+[1-9]\d{6,14}$/.test(account)) throw new Error('请输入当前 WhatsApp 的完整国际电话号码');
    const s = Executor.status(); if (!s.whatsapp || !s.accessibility || !s.unlocked) throw new Error('请完成下面的运行检查');
    await heartbeat(true); setReady(true); setNotice('已就绪。请在 Beacon 网页确认消息，再点击领取任务。');
  }
  const button = (title: string, key: string, fn: () => Promise<void> | void, secondary = false) => <Pressable disabled={!!busy} style={[styles.button, secondary && styles.secondary, !!busy && { opacity: .6 }]} onPress={() => void action(key, async () => { await fn(); })}><Text style={[styles.buttonText, secondary && { color: RED }]}>{busy === key ? '处理中…' : title}</Text></Pressable>;
  const field = (placeholder: string, value: string, onChange: (v: string) => void, secure = false) => <TextInput style={styles.input} placeholder={placeholder} value={value} onChangeText={onChange} secureTextEntry={secure} autoCapitalize="none" autoCorrect={false} />;
  return <SafeAreaView style={styles.root}><StatusBar barStyle="dark-content" /><View style={styles.hero}><Text style={styles.title}>Beacon 手机助手</Text><Text style={styles.heroNote}>WhatsApp · 单设备验证版</Text></View>
    <View style={styles.tabs}>{['工作台', '记录', '设备与账号'].map(t => <Pressable key={t} onPress={() => { setTab(t); setNotice(''); }}><Text style={[styles.tab, tab === t && { color: RED, fontWeight: '700' }]}>{t}</Text></Pressable>)}</View>
    <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
      {!!notice && <Text accessibilityRole="alert" style={styles.notice}>{notice}</Text>}
      {tab === '设备与账号' && <View style={styles.card}><Text style={styles.heading}>{paired ? '设备已配对' : '绑定 Beacon'}</Text><Text>在网页“设置 → 手机执行”生成配对码。</Text>
        <Text style={styles.small}>USB 本地测试填写 http://127.0.0.1:8000；云端填写 HTTPS 地址。电脑 IP 的 HTTP 地址暂不支持。</Text>
        {field('服务器地址', server, setServer)}
        {button('使用 USB 本地地址', 'usb-address', () => setServer('http://127.0.0.1:8000'), true)}
        {field('手机名称', label, setLabel)}
        <TextInput style={styles.input} placeholder="6 位数字配对码" value={code} onChangeText={setCode} keyboardType="number-pad" autoCapitalize="none" autoCorrect={false} />
        {button('配对', 'pair', async () => {
          const base = server.replace(/\/+$/, ''); const u = new URL(base);
          if (u.protocol !== 'https:' && !(u.protocol === 'http:' && u.hostname === '127.0.0.1')) throw new Error('电脑 IP 的 HTTP 地址不支持。手机已通过 USB 连接，请点击“使用 USB 本地地址”，填写 http://127.0.0.1:8000 后重新配对。');
          if (u.username || u.password || u.pathname !== '/' || u.search || u.hash) throw new Error('只填写服务器根地址');
          const data = await request(base + '/api/mobile/device/pair', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: code.trim(), label }) });
          Executor.configure(base, data.token); setCode(''); setPaired(true); setReady(false); setNotice('配对成功，请回工作台核对本方账号。');
        })}
        <Text style={styles.small}>设备凭据由 Android 安全存储加密保存。社媒账号在官方 App 登录。</Text></View>}
      {tab === '工作台' && <>
        <View style={styles.card}><Text style={styles.heading}>运行检查</Text><Text>{paired ? '✓ 已配对' : '○ 尚未配对'}</Text><Text>{status?.whatsapp ? '✓ WhatsApp 已安装' : '○ 未发现 WhatsApp'}</Text><Text>{status?.accessibility ? '✓ 无障碍已开启' : '○ 请开启 Beacon 无障碍服务'}</Text><Text>{status?.unlocked ? '✓ 手机已解锁' : '○ 请解锁手机'}</Text>
          {button('打开无障碍设置', 'permissions', () => Executor.permissions(), true)}
          <Text>核对当前 WhatsApp 登录账号：</Text>{field('+国家区号与电话号码', account, v => { setAccount(v); setReady(false); })}
          <Text style={styles.small}>首版由你核对本方账号；执行器核对目标电话号码。更换账号后需重新开启。</Text>
          {button(ready ? '刷新运行状态' : '核对账号并开启', 'start', start)}
          {button('暂停执行', 'pause', async () => { Executor.pause(); setReady(false); if (account && paired) await heartbeat(false); }, true)}
        </View>
        <View style={styles.card}><Text style={styles.heading}>当前任务</Text>
          {job ? <><Text>{job.snapshot.lead_name}</Text><Text>本方：{job.snapshot.sender}</Text><Text>发送至：{job.snapshot.target}</Text><Text style={styles.message}>{job.snapshot.body}</Text>
            {button('核对并执行这条消息', 'execute', () => {
              if (!ready || job.snapshot.sender !== account) throw new Error('请先核对本方账号并开启执行');
              Alert.alert('确认手机执行', `本方账号 ${job.snapshot.sender}\n发送至 ${job.snapshot.target}\n\n${job.snapshot.body}`, [{ text: '返回', style: 'cancel' }, { text: '执行', onPress: () => { try { Executor.execute(JSON.stringify(job)); setJob(undefined); setNotice('正在 WhatsApp 执行，请保持手机解锁。返回此页可查看结果。'); } catch (e) { setNotice(String(e)); } } }]);
            })}</> : <><Text>{status?.running ? '正在执行，请保持解锁' : '尚未领取任务'}</Text>{button('领取已确认任务', 'claim', async () => { if (!ready) throw new Error('请先开启执行'); await heartbeat(true); const data = await call('/claim', {}); if (!data.job) { setNotice(data.blocked || '暂时没有已确认任务'); return; } Executor.stage(JSON.stringify(data.job)); setJob(data.job); })}</>}
          {button('恢复并回填中断记录', 'recover', () => { Executor.recover(); setNotice('正在恢复记录；不会重新执行发送动作。'); }, true)}
        </View></>}
      {tab === '记录' && <View style={styles.card}><Text style={styles.heading}>最近执行记录</Text>{status?.journal ? (() => { const j = JSON.parse(status.journal); return <><Text>收件人：{j.snapshot?.target}</Text><Text>状态：{j.outcome || (j.phase === 'claimed' ? '待执行' : '处理中／待核对')}</Text><Text>{j.detail || ''}</Text><Text>{j.reported ? '已回填 Beacon' : '尚未回填，必要时点击恢复'}</Text></>; })() : <Text>暂无记录</Text>}</View>}
    </ScrollView></SafeAreaView>;
}
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#f7f4f1', paddingTop: Platform.OS === 'android' ? StatusBar.currentHeight : 0 }, hero: { padding: 24, backgroundColor: '#211b19' }, title: { color: '#fab736', fontSize: 23, fontWeight: '700' }, heroNote: { color: '#fff', marginTop: 8 },
  tabs: { flexDirection: 'row', justifyContent: 'space-around', backgroundColor: '#fff', padding: 16 }, tab: { fontSize: 16, color: '#666' }, content: { padding: 16, gap: 16, paddingBottom: 50 },
  card: { backgroundColor: '#fff', padding: 20, borderRadius: 16, gap: 12 }, heading: { fontSize: 19, fontWeight: '700' }, input: { padding: 13, borderWidth: 1, borderColor: '#ddd', borderRadius: 9, fontSize: 16 },
  button: { padding: 14, borderRadius: 9, backgroundColor: RED, alignItems: 'center' }, secondary: { backgroundColor: '#fff3f3', borderWidth: 1, borderColor: '#f1c7c9' }, buttonText: { color: '#fff', fontWeight: '600', fontSize: 16 }, small: { color: '#777', lineHeight: 21 }, notice: { backgroundColor: '#fff3d4', padding: 15, borderRadius: 10, lineHeight: 23 }, message: { backgroundColor: '#f8f6f3', padding: 12, lineHeight: 24 },
});
