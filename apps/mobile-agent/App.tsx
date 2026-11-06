import React, { useEffect, useState } from 'react';
import { Alert, AppState, Keyboard, Image, ImageBackground, Platform, Pressable, SafeAreaView, ScrollView, StatusBar, StyleSheet, Text, TextInput, View } from 'react-native';
import { ACTIONS, CHANNELS, channelLabel } from './lib/channels';
import ReplyNotifications from './ReplyNotifications';
import PairingScanner from './PairingScanner';
import { PairingTicket, pairingServer, parsePairingTicket } from './lib/pairing';
import Executor, { PhoneStatus } from './modules/beacon-executor';

type Job = { id: string; attempt: number; lease: string; snapshot: { target: string; sender: string; body: string; lead_name: string; channel?: string; action?: string; sender_mode?: string } };
const RED = '#cf010e';
async function request(url: string, options: RequestInit) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : Array.isArray(data.detail) ? data.detail.map((d: { msg: string }) => d.msg).join('；') : `请求失败 ${response.status}`);
    return data;
  } catch (e) {
    if (e instanceof Error && (e.name === 'AbortError' || e instanceof TypeError)) {
      throw new Error('连接不到 Beacon。USB 测试请检查连接线和本机转发；云端请检查服务器网络。配对仍保留，恢复后点击“连接并检查任务”。');
    }
    throw e;
  } finally { clearTimeout(timer); }
}
const outcomeLabels: Record<string, string> = { sent: '已发送', failed: '未发送', unknown: '结果待核对', claimed: '待确认执行', preparing: '正在核对聊天', preflight: '正在检查发送条件', click_attempted: '正在核对发送结果', needs_action: '需要手机处理', request_submitted: '请求已提交', unavailable: '暂不可联系' };
export default function App() {
  const [tab, setTab] = useState('工作台');
  const [ticket, setTicket] = useState<PairingTicket>();
  const [manual, setManual] = useState(false);
  const [server, setServer] = useState('https://beacon.ai-onestep.com');
  const [code, setCode] = useState('');
  const [label, setLabel] = useState('我的手机');
  const [account, setAccount] = useState('');
  const [accounts, setAccounts] = useState<Record<string, string>>({});
  const [replyJob, setReplyJob] = useState<string>();
  const [reply, setReply] = useState('');
  const [selectedChannel, setSelectedChannel] = useState('whatsapp');
  const [paired, setPaired] = useState(false);
  const [ready, setReady] = useState(false);
  const [status, setStatus] = useState<PhoneStatus>();
  const [job, setJob] = useState<Job>();
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');
  const [showChecks, setShowChecks] = useState(true);
  const [connectedAt, setConnectedAt] = useState<string>();
  const [pending, setPending] = useState(0);
  function inspect() {
    try { const s = Executor.status(); setStatus(s); if (s.journal) { const j = JSON.parse(s.journal); if (j.phase === 'claimed' && !j.reported) setJob(j); else if (j.reported) setJob(undefined); } } catch (e) { setNotice(String(e)); }
  }
  useEffect(() => {
    try { const c = Executor.credentials(); if (c.token) {
      setPaired(true); setServer(c.server);
      void request(c.server + '/api/mobile/device/state', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + c.token }, body: '{}' }).then(profile => {
        if (profile.accounts) setAccounts(profile.accounts);
        if (profile.account) { setAccount(current => current || profile.account); setShowChecks(false); }
        setPending(profile.pending_count || 0);
      }).catch(e => setNotice(e instanceof Error ? e.message : String(e)));
    } } catch (e) { setNotice('设备凭据读取失败，请重新配对：' + String(e)); }
    try { const s = Executor.status(); if (s.savedAccounts && Object.keys(JSON.parse(s.savedAccounts)).length) setAccounts(JSON.parse(s.savedAccounts)); if (s.savedAccount) { setAccount(s.savedAccount); setShowChecks(false); } } catch { /* Runtime checks show the native error separately. */ }
    inspect(); const timer = setInterval(inspect, 2000); const sub = AppState.addEventListener('change', s => { if (s === 'active') inspect(); });
    return () => { clearInterval(timer); sub.remove(); };
  }, []);
  async function call(path: string, body: object) {
    const c = Executor.credentials();
    return request(c.server + '/api/mobile/device' + path, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + c.token }, body: JSON.stringify(body) });
  }
  async function action(key: string, fn: () => Promise<void>) { if (busy) return; Keyboard.dismiss(); setBusy(key); setNotice(''); try { await fn(); inspect(); } catch (e) { const message = e instanceof Error ? e.message : String(e); setNotice(message); if (key === 'pair') Alert.alert('未能配对', message); } finally { setBusy(''); } }
  async function heartbeat(active: boolean) {
    const response = await call('/heartbeat', { account, accounts: { ...accounts, ...(account ? { whatsapp: account } : {}) }, installed: Executor.status().installed, ready: active, accessibility: Executor.status().accessibility, app_version: '0.3.0', protocol: 2 });
    setConnectedAt(new Date().toLocaleTimeString());
    setPending(response.pending_count || 0);
    if (active && response.status !== 'ready') throw new Error('Beacon 已连接，但无障碍服务尚未连接。请检查服务是否开启，退出其他手机调试工具后再试。');
    return response;
  }
  useEffect(() => {
    if (!ready) return;
    const timer = setInterval(() => { if (AppState.currentState === 'active') void heartbeat(true).catch(e => { setReady(false); setNotice(String(e)); }); }, 30000);
    return () => clearInterval(timer);
  }, [ready, account, accounts]);
  async function pairDevice(address: string, pairingCode: string) {
    if (Executor.status().running || job || (status?.journal && !JSON.parse(status.journal).reported)) throw new Error('请先处理当前任务或回填记录，再更换设备配对');
    const base = pairingServer(address);
    if (!/^\d{6}$/.test(pairingCode.trim())) throw new Error('请输入 6 位数字配对码');
    if (!label.trim()) throw new Error('请填写手机名称');
    const data = await request(base + '/api/mobile/device/pair', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: pairingCode.trim(), label: label.trim() }) });
    Executor.configure(base, data.token); setServer(base); setCode(''); setPaired(true); setReady(false); setPending(0); setConnectedAt(undefined); setTab('工作台'); setNotice(`已绑定到 ${data.owner || '当前网页账号'}，请核对本方账号并连接检查。`);
  }
  async function start() {
    const configured: Record<string, string> = { ...accounts, ...(account ? { whatsapp: account } : {}) };
    const installed = Executor.status().installed || [];
    if (!Object.values(configured).some(Boolean) && !installed.some(p => p !== 'whatsapp')) throw new Error('请安装社媒应用，或填写 WhatsApp 号码');
    if (account && !/^\+[1-9]\d{6,14}$/.test(account)) throw new Error('请核对 WhatsApp 的完整国际号码');
    const s = Executor.status(); if (!s.installed?.some(p => p !== 'whatsapp' || configured[p]) || !s.accessibility || !s.unlocked) throw new Error('请完成运行检查并安装对应社媒应用');
    await heartbeat(true); if (account) Executor.rememberAccount(account); Executor.rememberAccounts(JSON.stringify({ ...accounts, ...(account ? { whatsapp: account } : {}) })); setReady(true); setShowChecks(false); setNotice('已连接。网页确认任务后，点击“领取已确认任务”；领取不会发送消息。');
  }
  const button = (title: string, key: string, fn: () => Promise<void> | void, secondary = false) => <Pressable disabled={!!busy} style={[styles.button, secondary && styles.secondary, !!busy && { opacity: .6 }]} onPress={() => void action(key, async () => { await fn(); })}><Text style={[styles.buttonText, secondary && { color: RED }]}>{busy === key ? '处理中…' : title}</Text></Pressable>;
  const field = (placeholder: string, value: string, onChange: (v: string) => void, secure = false) => <TextInput style={styles.input} placeholder={placeholder} value={value} onChangeText={onChange} secureTextEntry={secure} autoCapitalize="none" autoCorrect={false} />;
  return <SafeAreaView style={styles.root}><StatusBar barStyle="dark-content" /><ImageBackground source={require('./assets/brand/banner.jpg')} style={styles.hero} imageStyle={{ opacity: .18 }} resizeMode="cover" accessible={false}>
      <View style={styles.brandRow}><Image source={require('./assets/brand/logo.png')} style={styles.logo} resizeMode="contain" accessibilityLabel="小当家" /><View style={{ flex: 1 }}><Text style={styles.title}>小当家 · 手机助手</Text><Text style={styles.heroNote}>Beacon · 社媒执行终端</Text></View></View>
    </ImageBackground>
    <View style={styles.tabs}>{['工作台', '记录', '设备与账号'].map(t => <Pressable key={t} onPress={() => { setTab(t); setNotice(''); }}><Text style={[styles.tab, tab === t && { color: RED, fontWeight: '700' }]}>{t}</Text></Pressable>)}</View>
    <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
      {!!notice && <Text accessibilityRole="alert" style={styles.notice}>{notice}</Text>}
      {tab === '设备与账号' && <View style={styles.card}><Text style={styles.heading}>{paired ? '设备已配对' : '绑定 Beacon'}</Text>
        <Text>在电脑网页“设置 → 手机执行”点击“绑定新手机”。</Text>
        <PairingScanner disabled={!!busy || !!status?.running} onScanned={p => { setTicket(p); setManual(false); setNotice('已识别配对码，请核对服务器与绑定账号后确认。'); }} />
        {ticket && <View style={styles.message}><Text style={styles.heading}>确认绑定</Text><Text>服务器：{ticket.server}</Text><Text>绑定账号：{ticket.owner}</Text>
          <Text style={styles.small}>仅绑定到此账号，不开启执行或发送消息。{paired ? '确认后将替换手机当前保存的连接。' : ''}</Text>
          {button('确认绑定', 'scan-pair', async () => { const p = parsePairingTicket(JSON.stringify(ticket)); await pairDevice(p.server, p.code); setTicket(undefined); })}
          {button('取消', 'scan-cancel', () => setTicket(undefined), true)}
        </View>}
        <Pressable onPress={() => { setManual(v => !v); setTicket(undefined); }}><Text style={{ color: RED }}>{manual ? '收起手动配对' : '无法扫码？手动配对'}</Text></Pressable>
        {manual && <>
          <Text style={styles.small}>USB 本地测试填写 http://127.0.0.1:8000；云端填写 HTTPS 地址。</Text>
          {field('服务器地址', server, setServer)}
          {button('使用 USB 本地地址', 'usb-address', () => setServer('http://127.0.0.1:8000'), true)}
          <TextInput style={styles.input} placeholder="6 位数字配对码" value={code} onChangeText={setCode} keyboardType="number-pad" autoCapitalize="none" autoCorrect={false} />
          {button('配对', 'pair', () => pairDevice(server, code))}
        </>}
        {field('手机名称', label, setLabel)}
        <Text style={styles.heading}>本方社媒账号</Text>
        <Text style={styles.small}>在官方 App 登录后填写对应账号。此处不需要 API Key 或密码。更改后需重新连接检查。</Text>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>{CHANNELS.map(c => <Pressable key={c.id} onPress={() => setSelectedChannel(c.id)} style={{ padding: 9, borderRadius: 8, backgroundColor: selectedChannel === c.id ? '#fff0f0' : '#f5f5f5' }}><Text style={{ color: selectedChannel === c.id ? RED : '#333' }}>{c.label}</Text></Pressable>)}</View>
        <Text>{status?.installed?.includes(selectedChannel) ? '✓ 已安装' : '○ 未检测到应用'} · {channelLabel(selectedChannel)}</Text>
        {selectedChannel === 'whatsapp' ? <>{field('+国家区号与电话号码', account, v => { setReady(false); setAccount(v); })}{button('保存 WhatsApp 号码', 'save-accounts', () => { Executor.rememberAccount(account); setNotice('号码已保存，请回工作台连接检查。'); }, true)}</> : <Text style={styles.small}>直接使用 {channelLabel(selectedChannel)} 官方 App 当前登录的账号，无需填写账号或 API Key。请在官方 App 中登录你要使用的账号。</Text>}
        <Text style={styles.small}>设备凭据由 Android 安全存储加密保存。社媒账号在官方 App 登录。</Text></View>}
      {tab === '工作台' && <>
        <View style={styles.card}><Text style={styles.heading}>{status?.running ? '正在执行任务' : ready && status?.accessibility && status?.unlocked ? '已就绪' : paired ? '已配对 · 待连接检查' : '请先绑定手机'}</Text>
          {!!account && <Text>WhatsApp 本方账号：{account}</Text>}
          <Text style={styles.small}>其他社媒使用手机 App 当前登录的账号。</Text>
          {!!connectedAt && <Text style={styles.small}>最近连接：{connectedAt}</Text>}
          {paired ? button(ready ? '检查连接' : '连接并检查任务', 'start', start) : button('扫码绑定手机', 'go-pair', () => setTab('设备与账号'))}
          <Pressable onPress={() => setShowChecks(v => !v)}><Text style={{ color: RED }}>{showChecks ? '收起运行检查' : '账号与运行检查'}</Text></Pressable>
          {(showChecks || !paired) && <><Text>{paired ? '✓ 已配对' : '○ 尚未配对'}</Text><Text>{status?.whatsapp ? '✓ WhatsApp 已安装' : '○ 未发现 WhatsApp'}</Text><Text>{status?.accessibility ? '✓ 无障碍已连接' : '○ 无障碍服务未连接'}</Text><Text>{status?.unlocked ? '✓ 手机已解锁' : '○ 请解锁手机'}</Text>
          {button('打开无障碍设置', 'permissions', () => Executor.permissions(), true)}
          {button('管理全部渠道账号', 'account-settings', () => setTab('设备与账号'), true)}
          <Text>核对当前 WhatsApp 登录账号（可选）：</Text>{field('+国家区号与电话号码', account, v => { if (ready) void heartbeat(false).catch(() => {}); setAccount(v); setReady(false); })}
          <Text style={styles.small}>本方账号由你在官方 App 核对。WhatsApp 已通过单条实机验证，其他平台本轮仅开发，待你决定后测试。</Text>
          <Text style={styles.small}>号码只需核对一次，本机记住号码；每次打开仍由你主动连接，不会自动发送。</Text></>}
          {button('暂停执行', 'pause', async () => { Executor.pause(); setReady(false); if (account && paired) await heartbeat(false); }, true)}
        </View>
        <View style={styles.card}><Text style={styles.heading}>当前任务</Text>
          {job ? <><Text>{channelLabel(job.snapshot.channel)} · {ACTIONS[job.snapshot.action || "direct_message"]}</Text><Text>{job.snapshot.lead_name}</Text><Text>本方：{job.snapshot.sender}</Text><Text>发送至：{job.snapshot.target}</Text><Text style={styles.message}>{job.snapshot.body}</Text>
            {button('核对并执行这条消息', 'execute', () => {
              if (!ready || job.snapshot.sender_mode !== 'current_app' && job.snapshot.sender !== (job.snapshot.channel === 'whatsapp' || !job.snapshot.channel ? account : accounts[job.snapshot.channel])) throw new Error('请先核对本方账号并开启执行');
              Alert.alert('确认手机执行', `本方账号 ${job.snapshot.sender}\n发送至 ${job.snapshot.target}\n\n${job.snapshot.body}`, [{ text: '返回', style: 'cancel' }, { text: '执行', onPress: () => { try { Executor.execute(JSON.stringify(job)); setJob(undefined); setNotice('正在目标社媒执行，请保持手机解锁。返回此页查看结果；需要处理时会保留消息。'); } catch (e) { setNotice(String(e)); } } }]);
            })}</> : <><Text>{status?.running ? '正在执行，请保持解锁' : '尚未领取任务'}</Text>{button('领取已确认任务', 'claim', async () => { if (!ready) throw new Error('请先开启执行'); await heartbeat(true); const data = await call('/claim', {}); if (!data.job) { setNotice(data.blocked || '暂时没有已确认任务'); return; } Executor.stage(JSON.stringify(data.job)); setJob(data.job); })}</>}
          {!job && !status?.running && <Text style={styles.small}>{pending ? `网页已确认 ${pending} 条任务，等待领取` : '网页确认任务后，在这里领取；领取和查看不会发送消息。'}</Text>}
          {status?.journal && !JSON.parse(status.journal).reported && <>{button('恢复并回填中断记录', 'recover', () => { Executor.recover(); setNotice('正在恢复记录；不会重新执行发送动作。'); }, true)}</>}
        </View></>}
      {tab === '设备与账号' && paired && <ReplyNotifications />}
      {tab === '记录' && <><Text style={styles.heading}>最近执行记录</Text>{status?.history?.length ? status.history.map(raw => { const j = JSON.parse(raw); return <View key={j.id} style={styles.card}>
        <Text>{channelLabel(j.snapshot?.channel)} · {ACTIONS[j.snapshot?.action || 'direct_message']}</Text><Text>{j.snapshot?.lead_name}</Text><Text>收件人：{j.snapshot?.target}</Text>
        <Text>状态：{outcomeLabels[j.outcome || j.phase] || '处理中／待核对'}</Text><Text>{j.detail || ''}</Text><Text>{j.reported ? '已回填 Beacon' : '尚未回填，请在工作台恢复记录'}</Text>
        {j.reported && <>
          {button('打开目标应用处理', 'open-' + j.id, () => Executor.openTarget(raw), true)}
          {button('复制本次消息', 'copy-' + j.id, () => { Executor.copyMessage(j.snapshot.body); setNotice('已复制消息。请核对目标后人工处理，并在网页记录实际结果。'); }, true)}
          {button('记录客户回复', 'reply-' + j.id, () => { setReplyJob(j.id); setReply(''); }, true)}
          {replyJob === j.id && <>
            <Text style={styles.small}>只记录该目标发来的真实回复。读取当前聊天需先在官方 App 打开正确会话；无法识别时可手动粘贴。</Text>
            {button('打开当前聊天并读取回复', 'read-' + j.id, async () => { const rows: string[] = JSON.parse(await Executor.captureReplies(raw)); if (!rows.length) throw new Error('当前页面未找到可明确识别的客户回复，请手动粘贴'); setReply(rows.join('\n')); }, true)}
            <TextInput multiline style={[styles.input, { minHeight: 100 }]} value={reply} onChangeText={setReply} placeholder="客户回复，确认后回填" />
            {button('确认这是客户回复并回填', 'save-reply-' + j.id, async () => { if (!reply.trim()) throw new Error('请填写客户回复'); await call('/jobs/' + j.id + '/inbound', { body: reply.trim(), confirmed_incoming: true }); setReplyJob(undefined); setReply(''); setNotice('客户回复已回填，网页会更新沟通状态，可继续使用 AI 分析与起草。'); })}
            {button('取消', 'cancel-reply-' + j.id, () => setReplyJob(undefined), true)}
          </>}
        </>}
      </View>; }) : <View style={styles.card}><Text>暂无记录</Text></View>}</>}
      <Text style={styles.copyright}>© {new Date().getFullYear()} 南京小当家文化咨询有限公司</Text>
    </ScrollView></SafeAreaView>;
}
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#f7f4f1', paddingTop: Platform.OS === 'android' ? StatusBar.currentHeight : 0 }, hero: { padding: 20, backgroundColor: '#211b19' }, brandRow: { flexDirection: 'row', alignItems: 'center', gap: 14 }, logo: { width: 78, height: 48, borderRadius: 4, backgroundColor: '#fff' }, title: { color: '#fab736', fontSize: 20, fontWeight: '700' }, heroNote: { color: '#fff', marginTop: 6, fontSize: 12 },
  tabs: { flexDirection: 'row', justifyContent: 'space-around', backgroundColor: '#fff', padding: 16 }, tab: { fontSize: 16, color: '#666' }, content: { padding: 16, gap: 16, paddingBottom: 50 },
  copyright: { color: '#777', fontSize: 12, textAlign: 'center', lineHeight: 20, paddingTop: 8, paddingBottom: 4 },
  card: { backgroundColor: '#fff', padding: 20, borderRadius: 16, gap: 12 }, heading: { fontSize: 19, fontWeight: '700' }, input: { padding: 13, borderWidth: 1, borderColor: '#ddd', borderRadius: 9, fontSize: 16 },
  button: { padding: 14, borderRadius: 9, backgroundColor: RED, alignItems: 'center' }, secondary: { backgroundColor: '#fff3f3', borderWidth: 1, borderColor: '#f1c7c9' }, buttonText: { color: '#fff', fontWeight: '600', fontSize: 16 }, small: { color: '#777', lineHeight: 21 }, notice: { backgroundColor: '#fff3d4', padding: 15, borderRadius: 10, lineHeight: 23 }, message: { backgroundColor: '#f8f6f3', padding: 12, lineHeight: 24 },
});
