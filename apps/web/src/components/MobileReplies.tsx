"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Card, Checkbox, Drawer, Empty, Select, Space, Tabs, Tag, Typography } from "antd";
import { useRouter } from "next/navigation";
import { api, json } from "@/lib/api";
import { MOBILE_LABELS } from "@/lib/mobile-channels";

type Notice = { source?: string; time_basis?: string; id: string; channel: string; title: string; body: string; occurred_at: string; status: string; stable_thread: boolean; structured: boolean; read: boolean; lead_id: string | null; lead_name: string | null };
type Target = { id: string; channel: string; lead_name: string; target: string };
export default function MobileReplies({ onChanged }: { onChanged: () => Promise<void> }) {
  const router = useRouter();
  const [pending, setPending] = useState<Notice[]>([]);
  const [linked, setLinked] = useState<Notice[]>([]);
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState("pending");
  const [selection, setSelection] = useState<Record<string, string>>({});
  const [remember, setRemember] = useState<Record<string, boolean>>({});
  const [targets, setTargets] = useState<Target[]>([]);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string>();
  const searchVersion = useRef(0);
  const linkedVersion = useRef<string | undefined>(undefined);
  useEffect(() => {
    const version = linked.map(n => n.id).sort().join(",");
    if (linkedVersion.current !== undefined && linkedVersion.current !== version) {
      void onChanged().catch(e => setError(String(e)));
    }
    linkedVersion.current = version;
  }, [linked, onChanged]);
  const refresh = useCallback(async () => {
    const [p, l] = await Promise.all([api<Notice[]>("/api/mobile/notifications"), api<Notice[]>("/api/mobile/notifications?status=linked")]);
    setPending(p); setLinked(l);
  }, []);
  useEffect(() => { void refresh().catch(e => setError(String(e))); const timer = setInterval(() => { if (!document.hidden) void refresh().catch(e => setError(String(e))); }, 15000); return () => clearInterval(timer); }, [refresh]);
  const loadTargets = async (q = "") => { const version = ++searchVersion.current; try { const rows = await api<Target[]>(`/api/mobile/reply-targets?q=${encodeURIComponent(q)}`); if (version === searchVersion.current) setTargets(rows); } catch (e) { setError(String(e)); } };
  async function act(key: string, fn: () => Promise<void>) { setBusy(old => ({ ...old, [key]: true })); try { await fn(); setError(undefined); await refresh(); await onChanged(); } catch (e) { setError(String(e)); } finally { setBusy(old => ({ ...old, [key]: false })); } }
  const unread = linked.filter(n => !n.read).length;
  return <>
    <Card size="small" style={{ marginBottom: 16 }}><Space wrap><strong>手机回复</strong><Tag color={pending.length ? "orange" : undefined}>待关联 {pending.length}</Tag><Tag color={unread ? "green" : undefined}>新回复 {unread}</Tag><Button onClick={() => { setOpen(true); void loadTargets(); void refresh().catch(e => setError(String(e))); }}>查看手机回复</Button><Typography.Text type="secondary">首次关联门店后，同一稳定会话的新回复自动回填。</Typography.Text></Space>{error && <Alert type="error" message={error} />}</Card>
    <Drawer title="手机回复" width={680} open={open} onClose={() => setOpen(false)}>
      <Alert type="info" showIcon message="来自手机通知或任务聊天页面补收，不代表完整聊天记录。未关联通知需确认门店；自动回填不会发送消息。" style={{ marginBottom: 16 }} />
      <Tabs activeKey={tab} onChange={setTab} items={[{ key: "pending", label: `待关联（${pending.length}）` }, { key: "linked", label: `已回填（${unread} 条未读）` }]} />
      {(tab === "pending" ? pending : linked).map(n => <Card key={n.id} size="small" title={<Space><Tag>{MOBILE_LABELS[n.channel] || n.channel}</Tag>{n.title}</Space>} style={{ marginBottom: 12 }}>
        <Typography.Paragraph style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{n.body}</Typography.Paragraph>
        <p>{n.source === "mobile_foreground" && <Tag>聊天补收</Tag>}{n.time_basis === "observed" ? "读取时间：" : "消息时间："}{new Date(n.occurred_at).toLocaleString("zh-CN")}</p>
        {tab === "pending" ? <Space direction="vertical" style={{ width: "100%" }}>
          {!n.structured && <Typography.Text type="secondary">普通通知，需要确认这确实是客户回复。</Typography.Text>}
          <Select aria-label="关联回复门店" showSearch filterOption={false} onSearch={q => void loadTargets(q)} placeholder="搜索并选择同渠道门店会话" style={{ width: "100%" }} value={selection[n.id]} onChange={v => setSelection(old => ({ ...old, [n.id]: v }))} options={targets.filter(t => t.channel === n.channel).map(t => ({ value: t.id, label: `${t.lead_name} · ${t.target}` }))} />
          {n.stable_thread ? <Checkbox checked={remember[n.id] !== false} onChange={e => setRemember(old => ({ ...old, [n.id]: e.target.checked }))}>记住此会话，后续明确消息自动回填</Checkbox> : <Typography.Text type="secondary">平台未提供稳定会话标识，本次关联后，后续通知仍需确认。</Typography.Text>}
          <Space><Button type="primary" disabled={!selection[n.id]} loading={busy[`link-${n.id}`]} onClick={() => act(`link-${n.id}`, async () => { await api(`/api/mobile/notifications/${n.id}/link`, json({ execution_id: selection[n.id], remember: remember[n.id] !== false })); })}>确认客户回复并回填</Button><Button loading={busy[`ignore-${n.id}`]} onClick={() => act(`ignore-${n.id}`, async () => { await api(`/api/mobile/notifications/${n.id}/ignore`, json({})); })}>忽略</Button></Space>
        </Space> : <Space><span>{n.lead_name || "原门店记录"}</span>{!n.read && <Tag color="green">新回复</Tag>}<Button loading={busy[`read-${n.id}`]} onClick={() => act(`read-${n.id}`, async () => { await api(`/api/mobile/notifications/${n.id}/read`, json({})); if (n.lead_id) { setOpen(false); router.push(`/tasks?lead=${n.lead_id}`); } })}>查看沟通</Button></Space>}
      </Card>)}
      {!(tab === "pending" ? pending : linked).length && <Empty description={tab === "pending" ? "暂无待关联手机通知" : "暂无已回填手机回复"} />}
      <Typography.Paragraph type="secondary" style={{ marginTop: 24 }}>更换社媒登录账号前，可解除自己的全部通知会话关联。已有回复会保留，后续通知重新确认。</Typography.Paragraph>
      <Button danger loading={busy.reset} onClick={() => act("reset", async () => { await api("/api/mobile/notification-threads/reset", json({})); })}>解除我的通知会话关联</Button>
    </Drawer>
  </>;
}
