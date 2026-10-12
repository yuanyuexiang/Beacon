"use client";
import { Alert, Button, Checkbox, DatePicker, Form, Input, Modal, Select, Space, Table, Tag, Typography, message } from "antd";
import { useCallback, useEffect, useState } from "react";
import { api, json } from "@/lib/api";
import { ChannelAccount, Conversation, SocialDelivery, deliveryLabels, replyCandidates } from "@/lib/outreach";
import { channelLabel } from "@/lib/format";

type Task = { id: string; lead_id: string; eligibility_id: string; channel: string; status: string };
type Eligibility = { id: string; channel: string; contact_ref?: string | null };
export default function SocialOutreach({ tasks, name, onChanged }: { tasks: Task[]; name: (id: string) => string; onChanged: () => Promise<void> }) {
  const [accounts, setAccounts] = useState<ChannelAccount[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [deliveries, setDeliveries] = useState<SocialDelivery[]>([]);
  const [previews, setPreviews] = useState<SocialDelivery[]>([]);
  const [selected, setSelected] = useState<React.Key[]>([]);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reconciling, setReconciling] = useState<SocialDelivery>();
  const [reconcileForm] = Form.useForm();
  const [binding, setBinding] = useState<Conversation>();
  const [leads, setLeads] = useState<{ id: string; name: string }[]>([]);
  const [eligibilities, setEligibilities] = useState<Eligibility[]>([]);
  const [eligibilityId, setEligibilityId] = useState<string>();
  const refresh = useCallback(async () => {
    const [a, c, d] = await Promise.all([api<ChannelAccount[]>("/api/outreach/accounts"), api<Conversation[]>("/api/outreach/conversations"), api<SocialDelivery[]>("/api/outreach/deliveries")]);
    setAccounts(a); setConversations(c); setDeliveries(d);
  }, []);
  useEffect(() => { refresh().catch((e) => message.error(e.message)); const timer = setInterval(() => { refresh().catch(() => {}); onChanged().catch(() => {}); }, 5000); return () => clearInterval(timer); }, [refresh, onChanged]);
  const act = async (work: () => Promise<void>) => {
    setBusy(true); try { await work(); await refresh(); await onChanged(); } catch (e) { message.error((e as Error).message); } finally { setBusy(false); }
  };
  const candidates = tasks.filter((t) => conversations.some((c) => replyCandidates([t], c, accounts.find((a) => a.id === c.account_id)).length));
  const previewTask = async (task: Task) => {
    const choices = conversations.filter((c) => replyCandidates([task], c, accounts.find((a) => a.id === c.account_id)).length);
    if (choices.length !== 1) throw new Error("该任务关联多个发送账号，请从会话表明确选择账号后预览");
    return api<SocialDelivery>("/api/outreach/preview", json({ task_id: task.id, conversation_id: choices[0].id }));
  };
  return <>
    <Typography.Paragraph>Facebook / Instagram 支持已收到消息的普通文字回复。先核对会话并关联门店准入，再创建或恢复对应任务；公开主页不能直接发送。<a href="/settings">管理发送账号</a>。</Typography.Paragraph>
    {!accounts.length && <Alert type="info" message="尚未添加发送账号，可先在设置中建立账号，授权以后补齐。" style={{ marginBottom: 12 }} />}
    <Typography.Title level={5}>收到的会话</Typography.Title>
    <Table<Conversation> size="small" rowKey="id" dataSource={conversations} pagination={{ pageSize: 10 }} columns={[
      { title: "发送账号", render: (_, c) => accounts.find((a) => a.id === c.account_id)?.label || c.account_id },
      { title: "对方", render: (_, c) => <>{c.lead_id ? name(c.lead_id) : "待关联门店"}<br /><Typography.Text type="secondary">{c.recipient_id}</Typography.Text></> },
      { title: "最近消息", dataIndex: "last_message", ellipsis: true },
      { title: "普通回复窗口", render: (_, c) => <Tag color={c.window_open ? "green" : "default"}>{c.window_open ? `截止 ${new Date(c.window_expires_at).toLocaleString()}` : "已过期"}</Tag> },
      { title: "操作", render: (_, c) => <Space wrap>
        {!c.lead_id && <Button size="small" onClick={() => act(async () => { setLeads(await api("/api/leads?limit=500")); setBinding(c); setEligibilities([]); setEligibilityId(undefined); })}>关联门店与准入</Button>}
        {replyCandidates(tasks, c, accounts.find((a) => a.id === c.account_id)).map((t) => <Button key={t.id} size="small" loading={busy} onClick={() => act(async () => { setPreviews([await api<SocialDelivery>("/api/outreach/preview", json({ task_id: t.id, conversation_id: c.id }))]); setConfirmed(false); })}>预览回复</Button>)}
      </Space> },
    ]} />
    <Typography.Title level={5}>可回复的任务</Typography.Title>
    <Space style={{ marginBottom: 12 }}><Button disabled={!selected.length} loading={busy} onClick={() => act(async () => { const rows: SocialDelivery[] = []; for (const id of selected) { const t = candidates.find((t) => t.id === id); if (!t) throw new Error("任务条件已变化，请刷新后选择"); rows.push(await previewTask(t)); } setPreviews(rows); setConfirmed(false); })}>预览选中任务</Button><Button onClick={() => act(refresh)}>刷新</Button></Space>
    <Table<Task> size="small" rowKey="id" dataSource={candidates} pagination={{ pageSize: 10 }} rowSelection={{ selectedRowKeys: selected, onChange: setSelected }} columns={[
      { title: "门店", render: (_, t) => name(t.lead_id) }, { title: "渠道", render: (_, t) => channelLabel(t.channel) }, { title: "任务", dataIndex: "id", ellipsis: true },
    ]} />
    <Typography.Title level={5}>发送记录</Typography.Title>
    <Table<SocialDelivery> size="small" rowKey="id" dataSource={deliveries.filter((d) => tasks.some((t) => t.id === d.task_id))} pagination={{ pageSize: 10 }} columns={[
      { title: "账号", render: (_, d) => d.payload.account_label }, { title: "收件人", render: (_, d) => d.payload.recipient_id },
      { title: "状态", render: (_, d) => <><Tag color={d.status === "sent" ? "green" : "default"}>{deliveryLabels[d.status] || d.status}</Tag>{d.last_error}</> },
      { title: "平台消息 ID", dataIndex: "platform_message_id", ellipsis: true },
      { title: "操作", render: (_, d) => <Space wrap>
        {d.status === "preview" && <Button size="small" onClick={() => { setPreviews([d]); setConfirmed(false); }}>查看并确认</Button>}
        {["sending", "unknown"].includes(d.status) && <Button size="small" loading={busy} onClick={() => act(async () => { await api(`/api/outreach/deliveries/${d.id}/reconcile`, json({})); })}>查询结果</Button>}
        {d.status === "unknown" && <Button size="small" onClick={() => { setReconciling(d); reconcileForm.resetFields(); }}>人工核对结果</Button>}
        {["preview", "ready", "queued", "blocked", "expired"].includes(d.status) && <Button size="small" danger onClick={() => act(async () => { await api(`/api/outreach/deliveries/${d.id}/cancel`, json({})); })}>取消</Button>}
      </Space> },
    ]} />
    <Modal title="人工核对未知发送结果" open={!!reconciling} onCancel={() => setReconciling(undefined)} onOk={() => reconcileForm.submit()} confirmLoading={busy}>
      <Typography.Paragraph>先在对应平台核对实际消息。只有明确确认已发送或未提交，才能回填；未确认时保留未知。</Typography.Paragraph>
      <Form form={reconcileForm} layout="vertical" onFinish={(v) => act(async () => { await api(`/api/outreach/deliveries/${reconciling!.id}/manual-reconcile`, json({ ...v, sent_at: v.sent_at?.toISOString() })); setReconciling(undefined); })}>
        <Form.Item name="status" label="实际结果" rules={[{ required: true }]}><Select options={[{ value: "sent", label: "已发送，提供真实消息 ID" }, { value: "failed", label: "确认未提交" }]} /></Form.Item>
        <Form.Item name="message_id" label="平台消息 ID（已发送必填）"><Input /></Form.Item>
        <Form.Item name="sent_at" label="实际发送时间（已发送必填）"><DatePicker showTime /></Form.Item>
        <Form.Item name="reason" label="核对证据与实际发送时间（至少 10 字符）" rules={[{ required: true, min: 10 }]}><Input.TextArea /></Form.Item>
        <Form.Item name="confirmed" valuePropName="checked" rules={[{ validator: (_, v) => v === true ? Promise.resolve() : Promise.reject(new Error("请确认已完成平台核对")) }]}><Checkbox>已在平台核对，确认上述实际结果</Checkbox></Form.Item>
      </Form>
    </Modal>
    <Modal title="关联收到的会话" open={!!binding} onCancel={() => setBinding(undefined)} confirmLoading={busy} okButtonProps={{ disabled: !eligibilityId }} onOk={() => act(async () => { await api(`/api/outreach/conversations/${binding!.id}/binding`, json({ eligibility_id: eligibilityId }, "PUT")); setBinding(undefined); })}>
      <Typography.Paragraph>请核对对方身份和线索来源，关联不会自动将渠道准入设为允许。已收到的回复会暂停该门店的待执行任务。</Typography.Paragraph>
      <Select showSearch placeholder="选择门店" optionFilterProp="label" style={{ width: "100%", marginBottom: 12 }} options={leads.map((l) => ({ value: l.id, label: l.name }))} onChange={(id) => act(async () => { setEligibilityId(undefined); setEligibilities(await api(`/api/leads/${id}/eligibility`)); })} />
      <Select value={eligibilityId} onChange={setEligibilityId} placeholder="选择该门店的对应平台准入记录" style={{ width: "100%" }} options={eligibilities.filter((e) => e.channel === accounts.find((a) => a.id === binding?.account_id)?.platform).map((e) => ({ value: e.id, label: `${channelLabel(e.channel)} ${e.contact_ref || "未填联系值"}` }))} />
    </Modal>
    <Modal title={`确认最终社媒回复（${previews.length} 条）`} open={!!previews.length} width={760} onCancel={() => setPreviews([])} footer={<Button type="primary" disabled={!confirmed} loading={busy} onClick={() => act(async () => { await api("/api/outreach/approve", json({ delivery_ids: previews.map((d) => d.id), preview_keys: Object.fromEntries(previews.map((d) => [d.id, d.preview_key])), confirmed: true, queued: previews.length > 1 })); setPreviews([]); setSelected([]); message.success("已确认，实际结果以发送记录为准"); })}>{previews.length > 1 ? "确认整批并入队" : "确认此回复"}</Button>}>
      {previews.map((d) => <div key={d.id} style={{ marginBottom: 16 }}><Typography.Text strong>{d.payload.account_label} · {channelLabel(d.payload.platform)} → {d.payload.recipient_id}</Typography.Text><Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>{d.payload.text}</Typography.Paragraph><Typography.Text type="secondary">预览有效至 {new Date(d.expires_at).toLocaleString()}</Typography.Text></div>)}
      <Checkbox checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)}>已核对每条消息的发送账号、收件人和最终正文，确认发送</Checkbox>
    </Modal>
  </>;
}
