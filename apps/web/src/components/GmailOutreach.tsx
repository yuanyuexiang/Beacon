"use client";
import Button from "@/components/AccessButton";
import { Alert, Checkbox, Input, Modal, Space, Table, Tag, Typography, message } from "antd";
import { useCallback, useEffect, useState } from "react";
import { api, json } from "@/lib/api";

type Task = { id: string; lead_id: string; channel: string; status: string };
type Delivery = { preview_key: string; id: string; task_id: string; status: string; payload: { to: string[]; subject: string; body: string }; gmail_message_id?: string | null; gmail_thread_id?: string | null; last_error?: string | null; sent_at?: string | null; checked_at?: string | null };
const labels: Record<string, string> = { preview: "待确认", ready: "等待单家发送", queued: "已入队", sending: "发送中", sent: "已发送", unknown: "结果待确认", failed: "发送失败", blocked: "复核未通过", expired: "预览已过期", cancelled: "已取消" };
export default function GmailOutreach({ tasks, name, onChanged, focusTaskId }: { tasks: Task[]; name: (id: string) => string; onChanged: () => Promise<void>; focusTaskId?: string }) {
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [selected, setSelected] = useState<React.Key[]>([]);
  useEffect(() => { if (focusTaskId) setSelected([focusTaskId]); }, [focusTaskId]);
  const [subject, setSubject] = useState("");
  const [previews, setPreviews] = useState<Delivery[]>([]);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ connected?: boolean; send_authorized?: boolean; policy?: { sending_enabled: boolean }; message?: string }>();
  const [error, setError] = useState<string>();
  useEffect(() => { api<typeof status>("/api/gmail/status").then(setStatus).catch((e) => setError(e.message)); }, []);
  const refresh = useCallback(async () => { setDeliveries(await api<Delivery[]>("/api/gmail/deliveries")); }, []);
  useEffect(() => {
    refresh().catch((e) => message.error(e.message));
    const timer = setInterval(() => { refresh().catch(() => {}); onChanged().catch(() => {}); }, 5000);
    return () => clearInterval(timer);
  }, [refresh, onChanged]);
  const act = async (work: () => Promise<void>) => {
    setBusy(true); setError(undefined); try { await work(); await refresh(); await onChanged(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const candidates = tasks.filter((t) => t.channel === "email" && ["pending", "opened"].includes(t.status));
  return <>
    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
    {status && <Alert type={status.connected && status.send_authorized && status.policy?.sending_enabled ? "success" : "warning"} showIcon message={`Gmail 账号：${status.connected ? "已连接" : "未连接"} · 发送权限：${status.send_authorized ? "已授权" : "待授权"} · 发送开关：${status.policy?.sending_enabled ? "开启" : "暂停"}`} description={status.message} style={{ marginBottom: 12 }} />}
    <Typography.Paragraph>选择已建立的邮箱任务，填写主题并完整预览。正文使用任务对应的已审批文案；<a href="/settings">发送账号和队列开关在设置中管理</a>。</Typography.Paragraph>
    <Space wrap style={{ marginBottom: 12 }}>
      <Input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="邮件主题" maxLength={256} style={{ width: 340 }} />
      <Button type="primary" loading={busy} disabled={!selected.length || !subject.trim()} onClick={() => act(async () => { const result = await api<Delivery[]>("/api/gmail/preview", json({ task_ids: selected, subject })); setPreviews(result); setConfirmed(false); })}>{selected.length > 1 ? "批量预览" : "预览邮件"}</Button>
      <Button loading={busy} onClick={() => act(async () => { const result = await api<{ checked: number; replies: number }>("/api/gmail/sync-replies", json({})); message.success(`检查 ${result.checked} 个线程，新增 ${result.replies} 条回复记录`); })}>同步回复</Button>
    </Space>
    <Table<Task> size="small" rowKey="id" pagination={{ pageSize: 10 }} dataSource={candidates} rowSelection={{ selectedRowKeys: selected, onChange: setSelected }} columns={[
      { title: "待发送门店", render: (_, task) => name(task.lead_id) }, { title: "任务", dataIndex: "id", ellipsis: true },
    ]} />
    <Typography.Title level={5}>邮件发送记录</Typography.Title>
    <Table<Delivery> size="small" rowKey="id" pagination={{ pageSize: 10 }} dataSource={deliveries.filter((d) => tasks.some((t) => t.id === d.task_id))} columns={[
      { title: "收件人", render: (_, d) => d.payload.to.join(", ") }, { title: "主题", render: (_, d) => d.payload.subject },
      { title: "状态", render: (_, d) => <><Tag color={d.status === "sent" ? "green" : "default"}>{labels[d.status] || d.status}</Tag>{d.last_error}</> },
      { title: "Gmail", render: (_, d) => d.gmail_message_id || "—" },
      { title: "操作", render: (_, d) => <Space wrap>
        {d.status === "preview" && <Button size="small" onClick={() => { setPreviews([d]); setConfirmed(false); }}>查看并确认</Button>}
        {["sending", "unknown"].includes(d.status) && <Button size="small" onClick={() => act(async () => { await api(`/api/gmail/deliveries/${d.id}/reconcile`, json({})); })}>查询发送结果</Button>}
        {["preview", "ready", "queued", "blocked", "expired"].includes(d.status) && <Button size="small" danger onClick={() => act(async () => { await api(`/api/gmail/deliveries/${d.id}/cancel`, json({})); })}>取消邮件</Button>}
      </Space> },
    ]} />
    <Modal title={`确认最终邮件（${previews.length} 封）`} open={!!previews.length} width={850} onCancel={() => setPreviews([])} footer={<Button type="primary" loading={busy} disabled={!confirmed} onClick={() => act(async () => { await api("/api/gmail/approve", json({ delivery_ids: previews.map((d) => d.id), preview_keys: Object.fromEntries(previews.map((d) => [d.id, d.preview_key])), confirmed: true, queued: previews.length > 1 })); setPreviews([]); setSelected([]); message.success("已确认并提交；实际结果以发送记录为准"); })}>{previews.length > 1 ? "确认整批邮件并入队" : "确认发送此邮件"}</Button>}>
      <Alert type="info" message="每封邮件分别发送，不抄送其他客户。确认后执行前仍复核准入、审批、抑制及预览有效期。" />
      {previews.map((d, index) => <div key={d.id} style={{ margin: "16px 0" }}>
        <Typography.Text strong>{index + 1}. 收件人：{d.payload.to.join(", ")}</Typography.Text>
        <Typography.Paragraph>主题：{d.payload.subject}</Typography.Paragraph>
        <Input.TextArea readOnly value={d.payload.body} autoSize={{ minRows: 6 }} />
      </div>)}
      <Checkbox checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)}>我已核对以上每封邮件的最终收件人、主题和正文，并确认发送</Checkbox>
    </Modal>
  </>;
}
