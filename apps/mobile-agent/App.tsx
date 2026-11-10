import React, { useCallback, useEffect, useState } from 'react';
import { Alert, AppState, BackHandler, Keyboard, Image, Pressable, ScrollView, StatusBar, StyleSheet, Text, TextInput, View } from 'react-native';
import Ionicons from '@expo/vector-icons/Ionicons';
import { SafeAreaView } from 'react-native-safe-area-context';
import { router, useLocalSearchParams } from 'expo-router';
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
      throw new Error('连接不到 Beacon。局域网请检查手机和电脑是否在同一网络、电脑 IP 和端口是否正确；云端请检查网络。配对仍保留，可重新连接。');
    }
    throw e;
  } finally { clearTimeout(timer); }
}
const outcomeLabels: Record<string, string> = { sent: '已发送', failed: '未发送', unknown: '结果待核对', claimed: '待确认执行', preparing: '正在核对聊天', preflight: '正在检查发送条件', click_attempted: '正在核对发送结果', needs_action: '需要手机处理', request_submitted: '请求已提交', unavailable: '已完成 · 不可联系' };
export default function App() {
  const params = useLocalSearchParams<{ tab?: string; panel?: string }>();
  const tab = ['任务', '记录', '设备'].includes(params.tab || '') ? params.tab! : '任务';
  const panel = params.panel || '';
  const setTab = (value: string) => { Keyboard.dismiss(); router.setParams({ tab: value, panel: '' }); setNotice(''); };
  const setPanel = (value: string) => { Keyboard.dismiss(); router.setParams({ panel: value }); setNotice(''); };
  useEffect(() => {
    const sub = BackHandler.addEventListener('hardwareBackPress', () => {
      if (panel) { router.setParams({ panel: '' }); return true; }
      if (tab !== '任务') { router.setParams({ tab: '任务', panel: '' }); return true; }
      return false;
    });
    return () => sub.remove();
  }, [panel, tab]);
  const [recordFilter, setRecordFilter] = useState('全部');
  const [expandedRecord, setExpandedRecord] = useState<string>();
  const [ticket, setTicket] = useState<PairingTicket>();
  const [manual, setManual] = useState(false);
  const [server, setServer] = useState('https://beacon.ai-onestep.com');
  const [code, setCode] = useState('');
  const [label, setLabel] = useState(() => Executor.status().deviceName || 'Android 手机');
  const [savedLabel, setSavedLabel] = useState(() => Executor.status().deviceName || 'Android 手机');
  const [account, setAccount] = useState('');
  const [accounts, setAccounts] = useState<Record<string, string>>({});
  const [replyJob, setReplyJob] = useState<string>();
  const [reply, setReply] = useState('');
  const [accountCandidate, setAccountCandidate] = useState<{channel: string; identity: string; observed_at: number; source?: string; model?: string}>();
  const [selectedChannel, setSelectedChannel] = useState('whatsapp');
  const [paired, setPaired] = useState(false);
  const [connectionPaused, setConnectionPaused] = useState(() => Executor.connectionPaused());
  const [switching, setSwitching] = useState(false);
  const [ready, setReady] = useState(false);
  const [initialized, setInitialized] = useState(false), [connected, setConnected] = useState(false);
  const [status, setStatus] = useState<PhoneStatus>();
  const [job, setJob] = useState<Job>();
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');
  const [connectionError, setConnectionError] = useState('');
  const [connectedAt, setConnectedAt] = useState<string>();
  const [pending, setPending] = useState(0);
  const [replyPermission, setReplyPermission] = useState(false);
  const [checksExpanded, setChecksExpanded] = useState(false);
  const [hasWorked, setHasWorked] = useState(false);
  function inspect() {
    try {
      const s = Executor.status(); setStatus(s); setReady(s.autoEnabled);
      setReplyPermission(Executor.notificationStatus().granted);
      if (s.autoEnabled) setHasWorked(true);
      const paused = Executor.connectionPaused(); setConnectionPaused(paused);
      setConnected(!paused && s.platformConnected); setConnectionError(s.connectionError);
      if (s.connectionLastContact) setConnectedAt(new Date(s.connectionLastContact).toLocaleTimeString());
      if (s.journal) { const j = JSON.parse(s.journal); if (j.phase === 'claimed' && !j.reported) setJob(j); else if (j.reported) setJob(undefined); }
    } catch (e) { setNotice(String(e)); }
  }
  useEffect(() => {
    let disposed = false;
    void Promise.resolve().then(() => {
    if (disposed) return;
    try { const c = Executor.credentials(); if (c.token) {
      setPaired(true); setServer(c.server);
      if (Executor.connectionPaused()) setInitialized(true);
      else void request(c.server + '/api/mobile/device/state', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + c.token }, body: '{}' }).then(profile => {
        if (profile.label && profile.label !== '我的手机') { setLabel(profile.label); setSavedLabel(profile.label); }
        if (profile.accounts) setAccounts(profile.accounts);
        if (profile.account) { setAccount(current => current || profile.account); }
        setPending(profile.pending_count || 0);
      }).catch(e => setConnectionError(e instanceof Error ? e.message : String(e))).finally(() => setInitialized(true));
    } else setInitialized(true); } catch (e) { setInitialized(true); setNotice('设备凭据读取失败，请重新配对：' + String(e)); }
    try { const s = Executor.status(); if (s.savedAccounts && Object.keys(JSON.parse(s.savedAccounts)).length) setAccounts(JSON.parse(s.savedAccounts)); if (s.savedAccount) { setAccount(s.savedAccount); } } catch { /* Runtime checks show the native error separately. */ }
    inspect();
    });
    const timer = setInterval(inspect, 2000); const sub = AppState.addEventListener('change', s => { if (s === 'active') inspect(); });
    return () => { disposed = true; clearInterval(timer); sub.remove(); };
  }, []);
  const call = useCallback(async (path: string, body: object) => {
    if (Executor.connectionPaused() && !['/disconnect', '/unbind'].includes(path)) throw new Error('当前已断开，请先重新连接平台');
    const c = Executor.credentials();
    return request(c.server + '/api/mobile/device' + path, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + c.token }, body: JSON.stringify(body) });
  }, []);
  async function action(key: string, fn: () => Promise<void>) { if (busy) return; Keyboard.dismiss(); setBusy(key); setNotice(''); try { await fn(); inspect(); } catch (e) { const message = e instanceof Error ? e.message : String(e); setNotice(message.replace(/^[\s\S]*Caused by:\s*(?:java\.lang\.[A-Za-z]+Exception:\s*)?/, '')); if (key === 'pair') Alert.alert('未能配对', message); } finally { setBusy(''); } }
  const heartbeat = useCallback(async (active: boolean, phoneLabel = savedLabel) => {
    const response = await call('/heartbeat', { label: phoneLabel.trim() || Executor.status().deviceName, account, accounts: Object.fromEntries(Object.entries({ ...accounts, ...(account ? { whatsapp: account } : {}) }).filter(([, value]) => value.trim())), installed: Executor.status().installed, ready: active, accessibility: Executor.status().accessibility, unlocked: Executor.status().unlocked, app_version: '0.3.0', protocol: 2 });
    if (Executor.connectionPaused()) return response;
    setConnected(true); setConnectionError(''); setConnectedAt(new Date().toLocaleTimeString());
    setPending(response.pending_count || 0);
    if (active && response.status !== 'ready') setReady(false);
    return response;
  }, [savedLabel, account, accounts, call]);
  useEffect(() => {
    if (!paired || !initialized || connectionPaused) return;
    let disposed = false;
    void Promise.resolve().then(() => {
      if (disposed) return;
      try { Executor.startConnection(); } catch (e) { setConnectionError(String(e)); }
    });
    return () => { disposed = true; };
  }, [paired, initialized, connectionPaused]);
  async function pairDevice(address: string, pairingCode: string) {
    if (Executor.status().running || job || (status?.journal && !JSON.parse(status.journal).reported)) throw new Error('请先处理当前任务或回填记录，再更换设备配对');
    const base = pairingServer(address);
    if (!/^\d{6}$/.test(pairingCode.trim())) throw new Error('请输入 6 位数字配对码');
    if (!label.trim()) throw new Error('请填写手机名称');
    const data = await request(base + '/api/mobile/device/pair', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: pairingCode.trim(), label: label.trim() }) });
    if (paired) { try { await call('/unbind', {}); } catch { /* Old server may be unreachable; the phone stops using its credentials. */ } }
    Executor.configure(base, data.token); Executor.startConnection(); setConnectionPaused(false); setSwitching(false); setSavedLabel(label.trim()); setServer(base); setCode(''); setPaired(true); setInitialized(true); setConnected(false); setReady(false); setPending(0); setConnectedAt(undefined); setTab('任务'); setNotice(`已绑定到 ${data.owner || '当前网页账号'}，请核对本方账号并连接检查。`);
  }
  async function updateAddress() {
    if (Executor.status().running || job) throw new Error('请先处理当前任务');
    const base = pairingServer(server); const current = Executor.credentials();
    const profile = await request(base + '/api/mobile/device/state', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + current.token }, body: '{}' });
    if (!['paired', 'ready'].includes(profile.status)) throw new Error('新地址未确认此设备，请重新配对');
    Executor.updateAddress(base, current.server); setServer(base); setConnectionPaused(false); setReady(false); setConnectionError('');
    setPending(profile.pending_count || 0); setNotice('平台地址已更新，配对及社媒账号已保留；执行已暂停。');
  }
  async function reconnect() {
    Executor.setConnectionPaused(false); Executor.startConnection(); setConnectionPaused(false);
    try { const active = Executor.status().autoEnabled; await heartbeat(active); setNotice(active ? '平台已连接，自动执行保持开启。' : '平台已连接；点击运行检查后再开启执行。'); }
    catch (e) { setConnected(false); setConnectionError(e instanceof Error ? e.message : String(e)); throw e; }
  }
  async function disconnect() {
    if (Executor.status().running) throw new Error('正在执行任务，请完成后再断开');
    Executor.pause(); Executor.setConnectionPaused(true); setConnectionPaused(true); setReady(false); setConnected(false);
    try { await call('/disconnect', {}); } catch { /* Keep the local disconnect even when offline. */ }
    setNotice('已断开，配对和社媒账号已保留。');
  }
  async function unbind() {
    if (Executor.status().running || job || (status?.journal && !JSON.parse(status.journal).reported)) throw new Error('请先处理当前任务及未回填记录');
    await call('/unbind', {});
    Executor.clearConnection(); setPaired(false); setReady(false); setConnected(false); setConnectionPaused(true); setPending(0); setConnectedAt(undefined); setConnectionError('');
    setNotice('已解除绑定，可以扫描另一平台的配对码。');
  }
  async function start() {
    if (connectionPaused || !connected) await reconnect();
    const installed = Executor.status().installed || [];
    if (!installed.length) throw new Error('请先安装对应社媒应用');
    if (account && !/^\+[1-9]\d{6,14}$/.test(account)) throw new Error('请核对 WhatsApp 的完整国际号码');
    const s = Executor.status();
    if (!s.accessibility) { if (!s.accessibilityEnabled) Executor.permissions(); setNotice(s.accessibilityEnabled ? '无障碍已开启，但系统尚未连接服务。请先退出手机自动化检查工具；若仍未恢复，在系统设置关闭再开启“Beacon 手机执行”。恢复后重新开启执行。' : '请在系统设置开启“Beacon 手机执行”无障碍服务，返回后点击“开始工作”。'); return; }
    if (!s.unlocked) throw new Error('请先解锁手机屏幕');
    if (!s.installed?.length) throw new Error('请先安装对应社媒应用');
    const profile = await heartbeat(true);
    if (profile.status !== 'ready') throw new Error('平台已连接，但运行检查未通过，请检查无障碍服务。');
    if (account) Executor.rememberAccount(account); Executor.rememberAccounts(JSON.stringify({ ...accounts, ...(account ? { whatsapp: account } : {}) })); Executor.startAutomatic(); setReady(true); setNotice('自动执行已开启，网页确认后会自动打开对应社媒执行；请保持解锁。');
  }
  const button = (title: string, key: string, fn: () => Promise<void> | void, secondary = false) => <Pressable disabled={!!busy} style={[styles.button, secondary && styles.secondary, !!busy && { opacity: .6 }]} onPress={() => void action(key, async () => { await fn(); })}><Text style={[styles.buttonText, secondary && { color: RED }]}>{busy === key ? '处理中…' : title}</Text></Pressable>;
  const field = (placeholder: string, value: string, onChange: (v: string) => void, secure = false) => <TextInput style={styles.input} placeholder={placeholder} value={value} onChangeText={onChange} secureTextEntry={secure} autoCapitalize="none" autoCorrect={false} />;
  const executionReady = ready && connected && !!status?.accessibility && !!status?.unlocked;
  const stateLabel = status?.running ? '正在执行' : status?.autoEnabled && !status.unlocked ? '等待解锁' : executionReady ? status?.autoEnabled ? '自动执行中' : '已就绪' : '待运行检查';
  const platformLabel = !paired ? '未绑定' : connectionPaused ? '已断开' : connected ? '已连接' : connectionError ? '连接中断' : '连接中';
  const row = (title: string, detail: string, onPress: () => void) => <Pressable accessibilityRole="button" onPress={onPress} style={styles.settingRow}><Text style={styles.rowTitle}>{title}</Text><Text style={styles.rowDetail}>{detail}</Text></Pressable>;
  const entries: { raw: string; j: { id: string; phase: string; navigation_history?: string[]; outcome?: string; detail?: string; reported?: boolean; updated_at?: number; snapshot: Job['snapshot'] } }[] = (status?.history || []).flatMap(raw => { try { return [{ raw, j: JSON.parse(raw) }]; } catch { return []; } });
  const completed = entries.filter(({j}) => ['sent', 'request_submitted', 'unavailable'].includes(j.outcome || '')).length;
  const needsAction = entries.filter(({j}) => ['unknown', 'failed', 'needs_action'].includes(j.outcome || '') || !j.reported && j.phase !== 'claimed').length;
  const records = entries.filter(({j}) => recordFilter === '全部' || (recordFilter === '已完成' ? ['sent', 'request_submitted', 'unavailable'].includes(j.outcome || '') : ['unknown', 'failed', 'needs_action'].includes(j.outcome || '') || !j.reported));
  const platformBadge = (platform: string) => <View style={[styles.platformIcon, { backgroundColor: platform === 'whatsapp' ? '#edf6ef' : platform === 'instagram' ? '#fbf0f3' : '#eef3fa' }]}><Text style={[styles.platformLetter, { color: platform === 'whatsapp' ? '#3d8651' : platform === 'instagram' ? '#b35b7a' : '#3568a8' }]}>{({whatsapp:'W',facebook:'f',instagram:'◎',linkedin:'in',tiktok:'♪',youtube:'▶',x:'X'} as Record<string,string>)[platform] || '•'}</Text></View>;
  const panelTitles: Record<string,string> = { connection: '连接与配对', accounts: '本方社媒账号', permissions: '运行权限', notifications: '客户回复通知', about: '关于手机助手' };
  return <SafeAreaView style={styles.root} edges={['top', 'bottom']}><StatusBar barStyle="dark-content" />
    <View style={styles.topBar}>
      <View style={styles.brandRow}>{tab === '任务' && <Image source={require('./assets/brand/logo.png')} style={styles.logo} resizeMode="contain" accessibilityLabel="小当家" />}<Text style={styles.title}>{tab === '任务' ? '手机助手' : tab === '记录' ? '执行记录' : '设备与连接'}</Text></View>
      <Pressable accessibilityRole="button" accessibilityLabel={`平台${platformLabel}，查看连接详情`} hitSlop={8} onPress={() => { setTab('设备'); router.setParams({ tab: '设备', panel: 'connection' }); }} style={styles.statusChip}><View style={[styles.statusDot, { backgroundColor: connected ? '#429460' : '#b48a43' }]} /><Text style={[styles.statusText, { color: connected ? '#38724d' : '#8c6c32' }]}>{platformLabel}</Text></Pressable>
    </View>
    <ScrollView key={`${tab}:${panel}`} style={{ flex: 1, backgroundColor: '#f6f5f2' }} contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
      {!!status?.autoError && <Text accessibilityRole="alert" style={styles.notice}>{status.autoError}</Text>}
      {!!notice && notice !== status?.autoError && <Text accessibilityRole="alert" style={styles.notice}>{notice}</Text>}
      {tab === '任务' && <>
        <View style={styles.workCard}>
          <Text style={styles.sectionLabel}>{savedLabel}</Text>
          <Pressable accessibilityRole="button" accessibilityLabel={status?.running ? '正在执行，暂停领取新任务' : executionReady ? '工作中，点击暂停' : !paired ? '绑定手机' : !connected ? '重新连接' : '开始工作'} accessibilityState={{disabled: !!busy, busy: busy === 'work'}} disabled={!!busy} style={[styles.workCircle, executionReady && styles.workGreen, hasWorked && !status?.autoEnabled && connected && styles.workPaused, !!busy && {opacity:.65}]} onPress={() => void action('work', async () => {
            if (!paired) { setTab('设备'); router.setParams({tab:'设备',panel:'connection'}); return; }
            if (!connected) { await reconnect(); return; }
            if (Executor.status().autoEnabled) {
              Executor.pauseReceiving(); setReady(false);
              setNotice(status?.running ? '已暂停领取新任务，当前任务继续处理并回填结果。' : '已暂停，点击圆形按钮继续工作。');
              if (connected && !status?.running) await heartbeat(false);
              return;
            }
            await start();
          })}>
            <Ionicons name={busy === 'work' ? 'hourglass-outline' : status?.autoEnabled ? 'pause' : !paired ? 'qr-code-outline' : !connected ? 'refresh' : 'play'} size={38} color="#fff" />
            <Text style={styles.workTitle}>{busy === 'work' ? '检查中' : status?.running ? '正在执行' : executionReady ? '工作中' : !paired ? '绑定手机' : !connected ? '重新连接' : hasWorked ? '继续工作' : '开始工作'}</Text>
            <Text style={styles.workSubtitle}>{status?.autoEnabled ? '点击暂停领取' : !connected ? '恢复连接后开始工作' : '连接 · 检查 · 接收任务'}</Text>
          </Pressable>
          <Text style={styles.workHint}>{status?.running ? '正在处理当前任务，请保持屏幕解锁' : executionReady ? '等待网页已确认的任务，收到后自动执行' : status?.autoEnabled ? '工作暂不可用，请处理下方运行检查' : '开始后持续接收网页已确认的任务'}</Text>
        </View>
        <View style={styles.card}>
          <Pressable accessibilityRole="button" accessibilityState={{expanded: checksExpanded || !executionReady}} onPress={() => setChecksExpanded(v => !v)} style={styles.sectionRow}>
            <Text style={styles.heading}>就绪检查</Text><Text style={styles.link}>{executionReady ? (checksExpanded ? '收起检查' : '运行检查通过 · 展开') : '请完成下方检查'}</Text>
          </Pressable>
          {(checksExpanded || !executionReady) && <>
            {row('平台连接', platformLabel + (connected ? ' · 查看' : ' · 去连接'), () => { if (paired) void action('check-connect', reconnect); else { setTab('设备'); router.setParams({tab:'设备',panel:'connection'}); } })}
            {row('无障碍服务 · 必需', status?.accessibility ? '已连接' : status?.accessibilityEnabled ? '等待系统连接 · 检查' : '未开启 · 去开启', () => Executor.permissions())}
            {status?.accessibilityEnabled && !status.accessibility && <Text style={styles.caption}>权限已开启，正在等待系统连接；无需重复授权。仍未恢复时可在系统设置关闭再开启。</Text>}
            {row('客户回复通知 · 可选', replyPermission ? '已授权 · 渠道设置' : '未开启 · 去开启', () => { setTab('设备'); router.setParams({tab:'设备',panel:'notifications'}); })}
            {row('后台运行 · 建议', status?.batteryUnrestricted ? '省电无限制 · 查看' : '去设置', () => Executor.backgroundSettings())}
            <Text style={styles.caption}>{status?.unlocked ? '屏幕已解锁' : '请解锁屏幕后执行'} · 已安装：{status?.installed?.map(channelLabel).join('、') || '尚未检测到社媒应用'}。回复通知未开启不影响发送。</Text>
          </>}
        </View>
        <View style={styles.summary}>{[[String(pending + (job ? 1 : 0)), '待处理'], [String(completed), '本机完成'], [String(needsAction), '需处理']].map(([count, title]) => <View key={title} style={styles.stat}><Text style={styles.statNumber}>{count}</Text><Text style={styles.caption}>{title}</Text></View>)}</View>
        <View style={styles.sectionRow}><Text style={styles.sectionLabel}>当前任务</Text><Text style={styles.caption}>{stateLabel}</Text></View>
        <View style={styles.card}>
          {job ? <><View style={styles.sectionRow}><Text style={styles.sectionLabel}>{channelLabel(job.snapshot.channel)} · {ACTIONS[job.snapshot.action || "direct_message"]}</Text><Text style={styles.badge}>待确认</Text></View><Text style={styles.deviceName}>{job.snapshot.lead_name}</Text><Text>本方：{job.snapshot.sender}</Text><Text>发送至：{job.snapshot.target}</Text><Text style={styles.message}>{job.snapshot.body}</Text>
            {button('确认执行这条消息', 'execute', () => {
              if (!ready || job.snapshot.sender_mode !== 'current_app' && job.snapshot.sender !== (job.snapshot.channel === 'whatsapp' || !job.snapshot.channel ? account : accounts[job.snapshot.channel])) throw new Error('请先核对本方账号并开启执行');
              Alert.alert('确认手机执行', `本方账号 ${job.snapshot.sender}\n发送至 ${job.snapshot.target}\n\n${job.snapshot.body}`, [{ text: '返回', style: 'cancel' }, { text: '执行', onPress: () => { try { Executor.execute(JSON.stringify(job)); setJob(undefined); setNotice('正在目标社媒执行，请保持手机解锁。返回此页查看结果；需要处理时会保留消息。'); } catch (e) { setNotice(String(e)); } } }]);
            })}</> : <><Text>{status?.running ? '正在执行，请保持解锁' : '暂无正在处理的任务'}</Text>{!status?.running && executionReady && !status?.autoEnabled && button('领取已确认任务', 'claim', async () => { if (!ready) throw new Error('请先完成运行检查'); await heartbeat(true); const data = await call('/claim', {}); if (!data.job) { setNotice(data.blocked || '暂时没有已确认任务'); return; } Executor.stage(JSON.stringify(data.job)); setJob(data.job); })}</>}
          {!job && !status?.running && <Text style={styles.small}>{pending ? `网页已确认 ${pending} 条任务，等待领取` : '网页确认消息后，手机自动领取并执行，无需逐条操作。'}</Text>}
          {status?.journal && !JSON.parse(status.journal).reported && <>{button('恢复并回填中断记录', 'recover', () => { Executor.recover(); setNotice('正在恢复记录；不会重新执行发送动作。'); }, true)}</>}

        </View>
        {!!entries.length && <View style={styles.card}><View style={styles.sectionRow}><Text style={styles.heading}>最近结果</Text><Pressable accessibilityRole="button" onPress={() => setTab('记录')}><Text style={styles.link}>全部记录</Text></Pressable></View>{entries.slice(0, 3).map(({j}, index) => <View key={j.id + index} style={styles.resultRow}><View style={{flex:1}}><Text style={styles.accountLabel}>{j.snapshot.lead_name}</Text><Text style={styles.caption}>{channelLabel(j.snapshot.channel)} · {j.detail || outcomeLabels[j.outcome || j.phase] || '处理中'}</Text></View><Text style={[styles.badge, j.outcome === 'sent' && styles.successBadge]}>{outcomeLabels[j.outcome || j.phase] || '处理中'}</Text></View>)}</View>}
      </>}
      {tab === '设备' && !panel && <>
        <View style={styles.card}><View style={styles.sectionRow}><View style={{flex:1}}><Text style={styles.deviceName}>{savedLabel}</Text><Text style={styles.small}>{paired ? '已绑定 Beacon' : '尚未配对'}</Text></View><Pressable accessibilityRole="button" onPress={() => setPanel('connection')}><Text style={styles.link}>编辑</Text></Pressable></View>{row('平台连接', platformLabel, () => setPanel('connection'))}{row('执行状态', stateLabel, () => setPanel('permissions'))}{row('连接详情', connectedAt || '尚未通信', () => setPanel('connection'))}</View>
        <View style={styles.sectionRow}><Text style={styles.sectionLabel}>本方社媒账号</Text><Pressable accessibilityRole="button" onPress={() => setPanel('accounts')}><Text style={styles.link}>管理全部</Text></Pressable></View>
        <View style={styles.card}>{CHANNELS.filter(c => status?.installed?.includes(c.id) || (c.id === 'whatsapp' ? account : accounts[c.id])).slice(0,3).map(c => <Pressable accessibilityRole="button" key={c.id} style={styles.accountRow} onPress={() => { setSelectedChannel(c.id); setPanel('accounts'); }}>{platformBadge(c.id)}<View style={{flex:1}}><Text style={styles.accountLabel}>{c.label}</Text><Text style={styles.caption} numberOfLines={1}>{(c.id === 'whatsapp' ? account : accounts[c.id]) || '使用 App 当前账号 · 未记录名称'}</Text></View><Text style={styles.caption}>{status?.installed?.includes(c.id) ? '已安装' : '未安装'}</Text></Pressable>)}<Text style={styles.caption}>所有平台平行使用，点击“管理全部”查看或维护。</Text></View>
        <View style={styles.card}>{row('运行权限', status?.accessibility && status?.unlocked ? '检查正常' : '待检查', () => setPanel('permissions'))}{row('客户回复通知', '权限与监听设置', () => setPanel('notifications'))}{row('关于手机助手', '版本与版权', () => setPanel('about'))}</View>
      </>}
      {tab === '设备' && !!panel && <>
        <Pressable accessibilityRole="button" onPress={() => setPanel('')} style={styles.back}><Text style={styles.link}>返回设备</Text></Pressable>
        <Text style={styles.pageHeading}>{panelTitles[panel] || '设备设置'}</Text>
        {panel === 'connection' && <View style={styles.card}><Text style={styles.heading}>Beacon 平台 · {platformLabel}</Text><Text style={styles.small}>{status?.connectionService ? '后台连接服务已开启，退出页面后继续待命。' : '后台连接服务未运行，请重新连接。'}</Text>{!status?.notificationPermission && button('允许显示连接通知', 'notify-permission', () => Executor.notificationPermission(), true)}<Text style={styles.small}>后台稳定性：在系统应用设置中允许后台运行／自启动，并将省电策略设为无限制。锁屏时保持连接，等待解锁再执行；强行停止后需重新打开。</Text>{button('后台运行设置', 'background-settings', () => Executor.backgroundSettings(), true)}<Text style={styles.small}>平台地址（切换 Wi-Fi／热点后，填写电脑当前 IP）</Text><TextInput accessibilityLabel="平台地址" style={styles.input} value={server} onChangeText={setServer} keyboardType="url" autoCapitalize="none" autoCorrect={false} />{paired && server.trim() !== Executor.credentials().server && button('验证并更新地址', 'update-address', updateAddress, true)}{!!connectedAt && <Text style={styles.small}>最近通信：{connectedAt}</Text>}{!!connectionError && <Text accessibilityRole="alert" style={styles.notice}>{connectionError}</Text>}{paired && <><Text style={styles.small}>执行：{stateLabel}。平台连接成功不等于已开启执行。</Text>{button(connected ? '检查连接' : '重新连接', 'ping', reconnect, true)}{!connectionPaused && button('断开连接', 'disconnect', disconnect, true)}{button('切换 Beacon 平台', 'switch', () => setSwitching(v => !v), true)}{button('解除绑定', 'unbind', () => Alert.alert('解除平台绑定？', '清除当前平台凭据，社媒账号资料保留。', [{text:'取消',style:'cancel'},{text:'解除绑定',style:'destructive',onPress:() => void action('unbind-confirm', unbind)}]), true)}</>}
        {(!paired || switching) && <>
        <Text>在电脑网页“设置 → 手机执行”点击“绑定新手机”。</Text>
        <PairingScanner disabled={!!busy || !!status?.running} onScanned={p => { setTicket(p); setManual(false); setNotice('已识别配对码，请核对服务器与绑定账号后确认。'); }} />
        {ticket && <View style={styles.message}><Text style={styles.heading}>确认绑定</Text><Text>服务器：{ticket.server}</Text><Text>绑定账号：{ticket.owner}</Text>
          <Text style={styles.small}>仅绑定到此账号，不开启执行或发送消息。{paired ? '确认后将替换手机当前保存的连接。' : ''}</Text>
          {button('确认绑定', 'scan-pair', async () => { const p = parsePairingTicket(JSON.stringify(ticket)); await pairDevice(p.server, p.code); setTicket(undefined); })}
          {button('取消', 'scan-cancel', () => setTicket(undefined), true)}
        </View>}
        <Pressable onPress={() => { setManual(v => !v); setTicket(undefined); }}><Text style={{ color: RED }}>{manual ? '收起手动配对' : '无法扫码？手动配对'}</Text></Pressable>
        {manual && <>
          <Text style={styles.small}>本地优先使用同一 Wi-Fi 下电脑的 IP，例如 http://192.168.1.100:8000；云端填写 HTTPS 地址，无需 USB。</Text>
          <TextInput style={styles.input} placeholder="服务器地址" value={server} onChangeText={setServer} keyboardType="url" autoCapitalize="none" autoCorrect={false} />
          {button('USB 调试备用地址', 'usb-address', () => setServer('http://127.0.0.1:8000'), true)}
          <TextInput style={styles.input} placeholder="6 位数字配对码" value={code} onChangeText={setCode} keyboardType="number-pad" autoCapitalize="none" autoCorrect={false} />
          {button('配对', 'pair', () => pairDevice(server, code))}
        </>}
        </>}
        {field('手机名称', label, setLabel)}
        <Text style={styles.small}>系统设备名称：{status?.deviceName || '读取中'}</Text>
        {paired && button('保存手机名称', 'save-label', async () => { if (!label.trim()) throw new Error('请填写手机名称'); await heartbeat(ready, label.trim()); setSavedLabel(label.trim()); setNotice('手机名称已同步到 Beacon。'); }, true)}

        </View>}
        {panel === 'accounts' && <View style={styles.card}>
        <Text style={styles.heading}>本方社媒账号</Text>
        <Text style={styles.small}>各平台账号独立记录，可选填名称或主页链接。记录不代表已核验登录身份；实际使用官方 App 当前登录账号。无需 API Key 或密码。</Text>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>{CHANNELS.map(c => <Pressable key={c.id} onPress={() => setSelectedChannel(c.id)} style={{ padding: 9, borderRadius: 8, backgroundColor: selectedChannel === c.id ? '#fff0f0' : '#f5f5f5' }}><Text style={{ color: selectedChannel === c.id ? RED : '#333' }}>{c.label}</Text></Pressable>)}</View>
        <Text>{status?.installed?.includes(selectedChannel) ? '✓ 已安装' : '○ 未检测到应用'} · {channelLabel(selectedChannel)}</Text>
        {button('识别当前账号', 'identify-account', async () => {
          if (job || status?.running) throw new Error('请先处理当前任务，再识别账号');
          setAccountCandidate(undefined);
          const result = JSON.parse(await Executor.inspectAccount(selectedChannel));
          if (result.channel !== selectedChannel || !result.identity) throw new Error('没有获得明确账号，本次未保存');
          setAccountCandidate(result);
        }, true)}
        <Text style={styles.caption}>打开本方资料页读取账号。规则识别失败时，将资料页顶部文字交给 Beacon AI 辅助识别；不上传截图，不读取聊天，不发送消息。</Text>
        {accountCandidate?.channel === selectedChannel && <View style={styles.message}><Text style={styles.heading}>请确认识别结果</Text><Text>{channelLabel(accountCandidate.channel)} · {accountCandidate.identity}</Text><Text style={styles.caption}>{accountCandidate.source === 'ai' ? `AI 辅助 · ${accountCandidate.model || '当前模型'} · ` : '规则识别 · '}读取时间：{new Date(accountCandidate.observed_at).toLocaleString()}</Text>
          {button('确认并保存账号', 'accept-account', async () => {
            const value = accountCandidate.identity.trim();
            const next = {...accounts, [accountCandidate.channel]: value};
            if (accountCandidate.channel === 'whatsapp') { Executor.rememberAccount(value); setAccount(value); }
            Executor.rememberAccounts(JSON.stringify(next)); setAccounts(next); setReady(false); setAccountCandidate(undefined);
            setNotice('识别结果已确认并保存。请回任务页重新检查，再执行任务。');
          })}
          {button('放弃本次结果', 'discard-account', () => setAccountCandidate(undefined), true)}
        </View>}
        {selectedChannel === 'whatsapp' ? <>{field('本方电话号码（可选，含国家区号）', account, v => { setReady(false); setAccount(v); })}{button('保存 WhatsApp 号码', 'save-accounts', () => { Executor.rememberAccount(account); setNotice('号码已保存，请回工作台连接检查。'); }, true)}<Text style={styles.small}>留空使用 WhatsApp 当前登录账号，号码仅用于记录及本人会话识别。</Text></> : <>{field(CHANNELS.find(c => c.id === selectedChannel)?.hint || '账号名称或主页链接（可选）', accounts[selectedChannel] || '', v => { setReady(false); setAccounts(old => ({ ...old, [selectedChannel]: v })); })}{button('保存账号记录', 'save-accounts', () => { Executor.rememberAccounts(JSON.stringify(accounts)); setNotice('账号记录已保存。请在官方 App 核对当前登录身份，再连接检查。'); }, true)}<Text style={styles.small}>可识别资料页后确认保存，也可手动记录。留空仍使用当前 App 账号；切换账号后请重新识别。</Text></>}
        <Text style={styles.small}>设备凭据由 Android 安全存储加密保存。社媒账号在官方 App 登录。</Text>
        </View>}
        {panel === 'permissions' && <View style={styles.card}><Text style={styles.heading}>运行检查</Text><Text style={styles.small}>{paired ? '✓ 已配对' : '○ 尚未配对'}</Text><Text style={styles.small}>{status?.accessibility ? '✓ 无障碍已开启并连接' : status?.accessibilityEnabled ? '○ 无障碍已开启，等待系统连接' : '○ 无障碍尚未开启'}</Text>{status?.accessibilityEnabled && !status?.accessibility && <Text style={styles.caption}>权限已开启，无需重复授权。请退出手机自动化检查工具并稍候；仍未恢复时，可在系统设置关闭再开启“Beacon 手机执行”。连接状态会自动刷新。</Text>}<Text style={styles.small}>{status?.unlocked ? '✓ 手机已解锁' : '○ 请解锁手机'}</Text><Text style={styles.small}>已安装渠道：{status?.installed?.map(channelLabel).join('、') || '尚未检测到'}</Text>{button('打开无障碍设置', 'permissions', () => Executor.permissions(), true)}{paired && button('开启自动执行', 'start', start)}<Text style={styles.caption}>完成检查不会领取或发送任务。</Text></View>}
        {panel === 'notifications' && (paired ? <ReplyNotifications /> : <View style={styles.card}><Text style={styles.small}>请先绑定手机，再设置回复通知。</Text>{button('绑定手机', 'go-pair', () => setPanel('connection'), true)}</View>)}
        {panel === 'about' && <View style={styles.card}><Image source={require('./assets/brand/logo.png')} style={{width:80,height:52,alignSelf:'center'}} resizeMode="contain" accessibilityLabel="小当家" /><Text style={styles.heading}>Beacon 手机助手</Text><Text style={styles.small}>版本 1.0.0 · 社媒执行终端</Text><Text style={styles.small}>消息在网页准备并确认，手机按任务核对目标后执行。执行记录与客户回复回到 Beacon。</Text><Text style={styles.small}>账号名称由资料页识别后确认，或手动记录，不代表持续监控登录身份。平台安装与真实收发能力分别验收。</Text><Text style={styles.copyright}>© {new Date().getFullYear()} 南京小当家文化咨询有限公司</Text></View>}
      </>}
      {tab === '记录' && <>
        <View style={styles.filters}>{['全部', '已完成', '需处理'].map(f => <Pressable accessibilityRole="button" accessibilityState={{selected:recordFilter === f}} key={f} onPress={() => setRecordFilter(f)} style={[styles.filter,recordFilter === f && styles.selectedFilter]}><Text style={[styles.filterText,recordFilter === f && {color:RED}]}>{f}</Text></Pressable>)}</View>
        <View style={styles.sectionRow}><Text style={styles.sectionLabel}>本机最近记录</Text><Text style={styles.caption}>{records.length} 条</Text></View>
        {records.length ? records.map(({raw,j}) => <View key={j.id} style={styles.card}>
          <Pressable accessibilityRole="button" accessibilityState={{expanded:expandedRecord === j.id}} onPress={() => setExpandedRecord(expandedRecord === j.id ? undefined : j.id)} style={styles.recordHeader}>{platformBadge(j.snapshot?.channel || 'whatsapp')}<View style={{flex:1}}><Text style={styles.accountLabel}>{j.snapshot?.lead_name || '未命名客户'}</Text><Text style={styles.caption}>{channelLabel(j.snapshot?.channel)} · {ACTIONS[j.snapshot?.action || 'direct_message']}</Text></View><Text style={[styles.badge, ['sent','request_submitted'].includes(j.outcome || '') && styles.successBadge]}>{outcomeLabels[j.outcome || j.phase] || '处理中'}</Text></Pressable>
          <View style={styles.sectionRow}><Text style={styles.caption}>{j.reported ? '已回填 Beacon' : '尚未回填'}</Text><Text style={styles.caption}>{j.updated_at ? '更新于 ' + new Date(j.updated_at).toLocaleString() : '历史时间未记录'}</Text></View>
          {expandedRecord === j.id && <><Text selectable style={styles.small}>收件人：{j.snapshot?.target}</Text><Text style={styles.message}>{j.snapshot?.body}</Text>{!!j.detail && <Text style={styles.small}>{j.detail}</Text>}{j.navigation_history?.map((step, index) => <Text key={index} style={styles.caption}>{index + 1}. {step}</Text>)}
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
          </>}
        </View>) : <View style={styles.empty}><Text style={styles.emptySymbol}>◷</Text><Text style={styles.heading}>暂无{recordFilter === '全部' ? '执行' : recordFilter}记录</Text><Text style={styles.small}>手机执行结果会显示在这里。</Text></View>}
      </>}
    </ScrollView>
    <View style={styles.bottomNav}>{[{name:'任务',icon:'clipboard-outline' as const},{name:'记录',icon:'time-outline' as const},{name:'设备',icon:'phone-portrait-outline' as const}].map(item => <Pressable accessibilityRole="tab" accessibilityState={{selected:tab === item.name}} accessibilityLabel={item.name} key={item.name} style={styles.navItem} onPress={() => setTab(item.name)}><Ionicons name={item.icon} size={23} color={tab === item.name ? RED : '#8a857e'} /><Text style={[styles.navLabel,tab === item.name && {color:RED,fontWeight:'600'}]}>{item.name}</Text></Pressable>)}</View>
  </SafeAreaView>;
}
const styles = StyleSheet.create({
  workCard:{alignItems:'center',paddingVertical:22,gap:16,backgroundColor:'#fff',borderRadius:22,borderWidth:1,borderColor:'#edeae5'},workCircle:{width:176,height:176,borderRadius:88,backgroundColor:RED,alignItems:'center',justifyContent:'center',gap:8,elevation:3},workGreen:{backgroundColor:'#278451'},workPaused:{backgroundColor:'#777e79'},workTitle:{fontSize:25,fontWeight:'700',color:'#fff'},workSubtitle:{fontSize:11,color:'#fff'},workHint:{fontSize:13,lineHeight:21,color:'#77736b',textAlign:'center',paddingHorizontal:18},resultRow:{flexDirection:'row',alignItems:'center',gap:12,paddingVertical:9,borderBottomWidth:1,borderBottomColor:'#f1eeea'},
  root: {flex:1,backgroundColor:'#fff'}, topBar: {height:60,paddingHorizontal:20,flexDirection:'row',justifyContent:'space-between',alignItems:'center',backgroundColor:'#fff'}, brandRow:{flexDirection:'row',alignItems:'center',gap:9},logo:{width:38,height:29},title:{fontSize:20,fontWeight:'700',color:'#232321'},statusChip:{flexDirection:'row',alignItems:'center',gap:6,minHeight:44},statusDot:{width:6,height:6,borderRadius:3},statusText:{fontSize:12},content:{padding:18,gap:14,paddingBottom:30},bottomNav:{flexDirection:'row',borderTopWidth:1,borderTopColor:'#eae7e1',backgroundColor:'#fff',paddingTop:7,paddingBottom:5},navItem:{flex:1,minHeight:54,alignItems:'center',justifyContent:'center',gap:4},navIcon:{fontSize:25,lineHeight:27,color:'#8a857e'},navLabel:{fontSize:11,color:'#8a857e'},card:{backgroundColor:'#fff',padding:17,borderRadius:17,gap:13,borderWidth:1,borderColor:'#edeae5'},heading:{fontSize:17,fontWeight:'600',color:'#272724'},pageHeading:{fontSize:23,fontWeight:'700',color:'#272724'},deviceName:{fontSize:21,fontWeight:'700',color:'#272724'},small:{fontSize:13,color:'#7e7971',lineHeight:21},caption:{fontSize:11,color:'#918a81',lineHeight:17},summary:{flexDirection:'row',paddingVertical:17,borderRadius:15,backgroundColor:'#fff',borderWidth:1,borderColor:'#edeae5'},stat:{flex:1,alignItems:'center',gap:6},statNumber:{fontSize:25,fontWeight:'600',color:'#272724'},sectionRow:{flexDirection:'row',alignItems:'center',justifyContent:'space-between',gap:12},sectionLabel:{fontSize:12,color:'#8a857d',fontWeight:'600'},settingRow:{minHeight:47,flexDirection:'row',alignItems:'center',justifyContent:'space-between',gap:12,borderBottomWidth:1,borderBottomColor:'#f1eeea'},rowTitle:{fontSize:13,color:'#35332f'},rowDetail:{fontSize:12,color:'#8a857d',flexShrink:1,textAlign:'right'},back:{minHeight:34,justifyContent:'center'},link:{fontSize:13,color:'#b62b35',paddingVertical:6},accountRow:{flexDirection:'row',alignItems:'center',gap:10,paddingVertical:10,borderBottomWidth:1,borderBottomColor:'#f0ece7'},accountLabel:{fontSize:14,fontWeight:'600',color:'#2b2926',marginBottom:4},platformIcon:{width:34,height:34,borderRadius:10,alignItems:'center',justifyContent:'center'},platformLetter:{fontSize:18,fontWeight:'700'},recordHeader:{flexDirection:'row',alignItems:'center',gap:11,minHeight:44},badge:{fontSize:11,color:'#8f692d',backgroundColor:'#fff3e1',borderRadius:6,padding:6,overflow:'hidden'},successBadge:{color:'#38724d',backgroundColor:'#edf5ef'},filters:{flexDirection:'row',gap:8},filter:{paddingVertical:9,paddingHorizontal:14,borderRadius:9,borderWidth:1,borderColor:'#e9e5df',backgroundColor:'#fff'},selectedFilter:{backgroundColor:'#fff0f0',borderColor:'#f3d5d5'},filterText:{fontSize:12,color:'#848078'},empty:{alignItems:'center',paddingVertical:35,gap:10},emptySymbol:{fontSize:38,color:'#bbb4aa'},input:{padding:12,borderWidth:1,borderColor:'#e2ded7',borderRadius:10,fontSize:15,color:'#2b2926'},button:{minHeight:46,padding:13,borderRadius:11,backgroundColor:RED,alignItems:'center',justifyContent:'center'},secondary:{backgroundColor:'#f5f4f1',borderWidth:1,borderColor:'#e9e5df'},buttonText:{color:'#fff',fontWeight:'600',fontSize:14},notice:{backgroundColor:'#fff4df',color:'#856127',padding:14,borderRadius:11,fontSize:13,lineHeight:21},message:{backgroundColor:'#f7f6f3',color:'#5d5b57',padding:14,borderRadius:10,fontSize:14,lineHeight:23},copyright:{color:'#9a948a',fontSize:11,textAlign:'center',lineHeight:19}
});
