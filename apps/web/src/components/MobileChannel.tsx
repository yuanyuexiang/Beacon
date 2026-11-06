"use client";
import { Alert, Button, Card, Drawer, Empty, Input, QRCode, Select, Space, Table, Tag, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";
import { api, json } from "@/lib/api";
import { MOBILE_ACTIONS, MOBILE_LABELS } from "@/lib/mobile-channels";
import { useOperator } from "@/lib/auth";

type Device = { id: string; label: string; account: string | null; status: string; online?: boolean; last_seen_at: string | null; capabilities?: { protocol?: number; accounts?: Record<string, string>; installed?: string[] } };
type Job = { id: string; status: string; error: string | null; finished_at: string | null; snapshot: { channel?: string; action?: string; target: string; sender: string; body: string; lead_name: string } };
const labels: Record<string, string> = { paired: "待运行检查", ready: "已就绪", revoked: "已解除", queued: "等待手机领取", claimed: "手机正在准备", sending: "发送中", sent: "已发送", unknown: "结果待核对", failed: "执行失败", cancelled: "已取消", needs_action: "需要手机处理", unavailable: "暂不可联系", request_submitted: "请求已提交，等待接受" };

export default function MobileSettings() {
  const { me } = useOperator();
  const writable = !!me && ["admin", "director", "member"].includes(me.role);
  const [devices, setDevices] = useState<Device[]>([]);
  const [pairing, setPairing] = useState<{ code: string; expires_at: string; owner: string }>();
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string>();
  const [now, setNow] = useState(Date.now());
  const refresh = useCallback(async () => { try { setDevices(await api<Device[]>("/api/mobile/devices")); setError(undefined); } catch (e) { setError(String(e)); } }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => { if (!pairing) return; const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, [pairing]);
  async function action(key: string, fn: () => Promise<void>) { setBusy(old => ({ ...old, [key]: true })); try { await fn(); setError(undefined); } catch (e) { setError(String(e)); } finally { setBusy(old => ({ ...old, [key]: false })); } }
  return <Card title="手机执行渠道" extra={<Button loading={busy.refresh} onClick={() => action("refresh", refresh)}>刷新手机</Button>}>
    <Typography.Paragraph>将 Android 手机绑定到自己的账号。确认消息后，手机领取任务并核对目标执行，结果回到沟通工作台。</Typography.Paragraph>
    <Alert type="info" showIcon message="WhatsApp 已通过本人会话实测；Facebook、Instagram、LinkedIn、TikTok、YouTube、X 适配已开发，等待实机验收。手机需保持解锁并主动连接。" style={{ marginBottom: 16 }} />
    {error && <Alert type="error" message={error} />}
    {writable && <Button type="primary" loading={busy.pair} onClick={() => action("pair", async () => setPairing(await api("/api/mobile/pairing", json({}))))}>绑定新手机</Button>}
    {pairing && <Card size="small" style={{ marginTop: 12 }} title="用 Beacon 手机助手扫码配对">
      <Space align="start" wrap size="large">
        <QRCode value={JSON.stringify({ type: "beacon-pair", version: 1, server: window.location.protocol === "http:" ? "http://127.0.0.1:8000" : window.location.origin, code: pairing.code, owner: pairing.owner || me?.username, expires_at: pairing.expires_at })} size={200}
          status={Date.parse(pairing.expires_at) <= now ? "expired" : "active"} onRefresh={() => action("pair", async () => setPairing(await api("/api/mobile/pairing", json({}))))} />
        <div><p>手机打开“设备与账号” → “扫码配对”，扫描后确认绑定。</p>
          <p>绑定账号：{pairing.owner || me?.username}</p>
          <p>服务器：<Typography.Text copyable>{window.location.protocol === "http:" ? "http://127.0.0.1:8000" : window.location.origin}</Typography.Text></p>
          {window.location.protocol === "http:" && <p>USB 本地测试：手机需连接这台电脑，并保持网络转发运行。二维码已使用 USB 地址。</p>}
          <p>手动配对码：<Typography.Text copyable>{pairing.code}</Typography.Text></p>
          <Typography.Text type="secondary">{Date.parse(pairing.expires_at) <= now ? "已过期，请刷新二维码" : `剩余 ${Math.max(0, Math.ceil((Date.parse(pairing.expires_at) - now) / 1000))} 秒，仅可使用一次。`}</Typography.Text>
          <p><Button loading={busy.pair} onClick={() => action("pair", async () => setPairing(await api("/api/mobile/pairing", json({}))))}>刷新配对码</Button></p>
        </div>
      </Space>
    </Card>}
    <Table rowKey="id" dataSource={devices} pagination={false} style={{ marginTop: 16 }} locale={{ emptyText: <Empty description="尚未绑定手机" /> }} columns={[
      { title: "手机", dataIndex: "label" }, { title: "本方渠道账号", render: (_, d) => <Space direction="vertical">{Object.entries(d.capabilities?.accounts || (d.account ? { whatsapp: d.account } : {})).map(([p, v]) => <span key={p} style={{ overflowWrap: "anywhere" }}>{MOBILE_LABELS[p] || p} · {v}</span>)}</Space> },
      { title: "状态", render: (_, d) => <Space direction="vertical"><Tag>{d.status === "ready" && !d.online ? "离线" : labels[d.status] || d.status}</Tag><small>{d.last_seen_at ? `最近连接 ${new Date(d.last_seen_at).toLocaleString("zh-CN")}` : "尚未连接"}</small></Space> },
      { title: "操作", render: (_, d) => writable && d.status !== "revoked" && <Button danger loading={busy[d.id]} onClick={() => action(d.id, async () => { await api(`/api/mobile/devices/${d.id}/revoke`, json({})); await refresh(); })}>解除绑定</Button> },
    ]} />
  </Card>;
}

export function MobileTask({ taskId, onChanged, platform = "whatsapp" }: { taskId: string; onChanged: () => void; platform?: string }) {
  const { me } = useOperator();
  const writable = !!me && ["admin", "director", "member"].includes(me.role);
  const [open, setOpen] = useState(false);
  const [devices, setDevices] = useState<Device[]>([]);
  const [device, setDevice] = useState<string>();
  const [contactAction, setContactAction] = useState(MOBILE_ACTIONS[platform]?.[0]?.value || "direct_message");
  const supports = useCallback((d: Device) => d.status === "ready" && d.online && (d.capabilities?.protocol === 2 ? (platform !== "whatsapp" || !!d.capabilities.accounts?.[platform]) && d.capabilities.installed?.includes(platform) : platform === "whatsapp"), [platform]);
  useEffect(() => { setContactAction(MOBILE_ACTIONS[platform]?.[0]?.value || "direct_message"); setDevice(undefined); setPreview(undefined); }, [platform, taskId]);
  const [reason, setReason] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [preview, setPreview] = useState<{ preview_hash: string; payload: Job["snapshot"] }>();
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string>();
  const refresh = useCallback(async () => { setJob(await api<Job | null>(`/api/mobile/tasks/${taskId}`)); }, [taskId]);
  const loadDevices = useCallback(async () => {
    const rows = await api<Device[]>("/api/mobile/devices"); setDevices(rows);
    const available = rows.filter(supports);
    setDevice(current => current && available.some(d => d.id === current) ? current : available.length === 1 ? available[0].id : undefined);
  }, [supports]);
  useEffect(() => { if (!open) return; const timer = setInterval(() => { void Promise.all([refresh(), loadDevices()]).catch(e => setError(String(e))); }, 5000); return () => clearInterval(timer); }, [open, refresh, loadDevices]);
  async function act(key: string, fn: () => Promise<void>) { setBusy(old => ({ ...old, [key]: true })); setError(undefined); try { await fn(); } catch (e) { setError(String(e)); } finally { setBusy(old => ({ ...old, [key]: false })); } }
  return <><Button onClick={() => { setOpen(true); setPreview(undefined); void act("load", async () => { await Promise.all([loadDevices(), refresh()]); }); }}>手机执行／查看结果</Button>
    <Drawer title={`${MOBILE_LABELS[platform] || platform} 手机执行`} open={open} onClose={() => setOpen(false)} width={620}>
      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}
      {job ? <><Tag color={job.status === "sent" ? "green" : ["failed", "unknown"].includes(job.status) ? "orange" : "blue"}>{labels[job.status] || job.status}</Tag><p>{job.error}</p>{job.finished_at && <p>更新时间：{new Date(job.finished_at).toLocaleString("zh-CN")}</p>}<p>动作：{MOBILE_ACTIONS[job.snapshot.channel || platform]?.find(a => a.value === job.snapshot.action)?.label || "发送消息"}</p><p>收件人：{job.snapshot.target}</p><p style={{ whiteSpace: "pre-wrap" }}>{job.snapshot.body}</p>
        {job.status === "queued" && <Alert type="info" showIcon message="已交给手机。请在手机工作台领取并核对这条消息，尚未发送。" />}
        {writable && ["queued", "claimed", "sending"].includes(job.status) && <Button danger loading={busy.cancel} onClick={() => act("cancel", async () => { setJob(await api(`/api/mobile/tasks/${taskId}/cancel`, json({}))); onChanged(); })}>停止本次执行</Button>}
        {["needs_action", "unavailable", "request_submitted"].includes(job.status) && <Alert type="info" showIcon message={labels[job.status]} description="在手机执行记录中打开目标应用、复制消息或记录客户回复；完成手动操作后在沟通页回填实际结果。请求提交不会计为私信已发送。" />}
        {["failed", "cancelled"].includes(job.status) && <Alert type="info" message="本次没有确认发送成功，记录已保留。请核对手机聊天及上述原因；可返回任务切换为人工执行。" />}
        {writable && job.status === "unknown" && <><Alert type="warning" message="先在手机暂停并核对实际消息，确认后记录结果。系统不会自动重发。" /><Input.TextArea placeholder="填写核对情况" value={reason} onChange={e => setReason(e.target.value)} style={{ marginTop: 12 }} /><Space style={{ marginTop: 12 }}>{[true, false].map(sent => <Button key={String(sent)} disabled={reason.trim().length < 4} loading={busy[String(sent)]} onClick={() => act(String(sent), async () => { setJob(await api(`/api/mobile/tasks/${taskId}/resolve`, json({ sent, reason }))); onChanged(); })}>{sent ? "确认已发出" : "确认未发出"}</Button>)}</Space></>}
      </> : <>
        <p>选择你绑定的手机，预览完整消息后确认。手机上仍会核对目标，防止用错会话。</p>
        <Select aria-label="手机联系动作" style={{ width: "100%", marginBottom: 12 }} value={contactAction} options={MOBILE_ACTIONS[platform] || []} onChange={v => { setContactAction(v); setPreview(undefined); }} />
        <Select placeholder="选择已就绪手机" style={{ width: "100%" }} value={device} onChange={v => { setDevice(v); setPreview(undefined); }} options={devices.filter(d => d.status !== "revoked").map(d => ({ value: d.id, disabled: !supports(d), label: `${d.label} · ${d.capabilities?.accounts?.[platform] || (platform !== "whatsapp" ? "App 当前登录账号" : d.account || "待填写号码")} · ${!d.online ? "离线" : labels[d.status] || d.status}` }))} />
        {!devices.some(supports) && <Alert style={{ marginTop: 12 }} type="info" message="请先在手机点击“连接并检查任务”。保持对应应用已安装并登录；仅 WhatsApp 需要填写本方号码。" />}
        <p><a href="/settings?section=mobile">管理手机与配对</a></p>
        <Button disabled={!device || !writable} loading={busy.preview} onClick={() => act("preview", async () => setPreview(await api(`/api/mobile/tasks/${taskId}/preview`, json({ device_id: device, preview_hash: "0".repeat(64), action: contactAction }))))}>预览消息</Button>
        {preview && <Card title="确认本次发送" style={{ marginTop: 16 }}><p>本方账号：{preview.payload.sender}</p><p>收件人：{preview.payload.target}</p><p style={{ whiteSpace: "pre-wrap" }}>{preview.payload.body}</p><Button type="primary" disabled={!writable} loading={busy.confirm} onClick={() => act("confirm", async () => { setJob(await api(`/api/mobile/tasks/${taskId}/confirm`, json({ device_id: device, preview_hash: preview.preview_hash, action: contactAction }))); setPreview(undefined); onChanged(); })}>确认交给手机执行</Button></Card>}
      </>}
    </Drawer></>;
}
