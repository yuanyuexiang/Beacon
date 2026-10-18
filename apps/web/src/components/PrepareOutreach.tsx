"use client";
import { Alert, Card, Checkbox, Collapse, DatePicker, Drawer, Form, Input, Select, Space, Table, Tag, Typography } from "antd";
import Button from "@/components/AccessButton";
import OutreachJourney from "@/components/OutreachJourney";
import Link from "next/link";
import dayjs from "dayjs";
import { useEffect, useState } from "react";
import { api, json } from "@/lib/api";
import { Assignee, CHANNELS, Draft, MODES, Prepared, taskLink } from "@/lib/communication";
import { channelLabel } from "@/lib/format";

function DraftEditor({ draft, assignees, returnTo, sender, optOut, onChange }: { draft: Draft; assignees: Assignee[]; returnTo: string; sender: string; optOut: string; onChange: (value: Draft) => void }) {
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [text, setText] = useState("");
  const piece = draft.context.contents.find((c) => c.id === draft.content_id);
  const contact = draft.context.contacts.find((e) => e.id === draft.eligibility_id);
  const [contactForm] = Form.useForm();
  useEffect(() => { setText(piece?.body_text || ""); setConfirmed(false); }, [piece?.id, piece?.body_text]);
  useEffect(() => { contactForm.resetFields(); contactForm.setFieldsValue({ channel: draft.channel, contact_ref: contact?.contact_ref, contact_source: contact?.contact_source, contact_usable: contact?.contact_usable || "unknown", eligibility: contact?.eligibility || "unknown", evidence: contact?.evidence, rule_version: contact?.rule_version, review_due_at: contact?.review_due_at ? dayjs(contact.review_due_at) : null }); }, [contactForm, contact?.id, contact?.evidence, contact?.eligibility, contact?.rule_version, contact?.review_due_at, contact?.contact_ref, contact?.contact_source, contact?.contact_usable, draft.channel]);
  const patch = async (changes: Record<string, unknown>) => { const value = await api<Draft>(`/api/communication/drafts/${draft.id}`, json(changes, "PATCH")); onChange(value); return value; };
  const act = async (work: () => Promise<unknown>) => { setBusy(true); setError(undefined); try { await work(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  const choices = MODES.filter((m) => m.value === "manual" || (m.value === "gmail" && draft.channel === "email") || (m.value === "social" && ["facebook", "instagram"].includes(draft.channel)));
  return <Card size="small" title={`${draft.context.lead.name} · ${channelLabel(draft.channel)}`}>
    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
    {draft.blockers.length > 0 && <Alert type="warning" showIcon message="尚不能创建可执行任务，草稿已保存" description={draft.blockers.join("；")} style={{ marginBottom: 12 }} />}
    <Space wrap style={{ marginBottom: 12 }}>
      <Select aria-label="执行方式" value={draft.execution_mode} style={{ width: 210 }} disabled={busy} options={choices} onChange={(execution_mode) => act(() => patch({ execution_mode }))} />
      <Select aria-label="负责人" allowClear value={draft.assigned_to || undefined} style={{ width: 170 }} placeholder="负责人" disabled={busy} options={assignees.map((a) => ({ value: a.username, label: a.display_name || a.username }))} onChange={(assigned_to) => act(() => patch({ assigned_to: assigned_to || null }))} />
      <DatePicker showTime aria-label="跟进提醒时间" placeholder="跟进提醒时间（不自动发送）" value={draft.follow_up_at ? dayjs(draft.follow_up_at) : null} disabled={busy} onChange={(v) => act(() => patch({ follow_up_at: v?.toISOString() || null }))} />
      <Link href={`/leads/${draft.lead_id}?returnTo=${encodeURIComponent(returnTo)}`}>菜单与客户资料</Link>
    </Space>
    <Form layout="vertical">
      <Form.Item label="联系方式"><Select allowClear placeholder="选择本渠道的联系方式" value={draft.eligibility_id || undefined} options={draft.context.contacts.filter((e) => e.channel === draft.channel).map((e) => ({ value: e.id, label: `${e.contact_ref || "未填写"} · ${e.eligibility === "allowed" ? "准入已允许" : "准入待核对"}${e.suppressed ? " · 已抑制" : ""}` }))} onChange={(eligibility_id) => act(() => patch({ eligibility_id: eligibility_id || null }))} disabled={busy} /></Form.Item>
      <Form.Item label="短文案与审批"><Select allowClear placeholder="选择文案版本" value={draft.content_id || undefined} options={draft.context.contents.map((c) => ({ value: c.id, label: `文案 v${c.version} · ${c.approved ? "审批有效" : c.reason || "待审批"}` }))} onChange={(content_id) => act(() => patch({ content_id: content_id || null }))} disabled={busy} /></Form.Item>
    </Form>
    <Collapse items={[
      { key: "eligibility", label: "补充联系方式／人工核对渠道准入", children: <Form form={contactForm} layout="vertical" disabled={busy} onFinish={(v) => act(async () => { const recorded = await api<{ id: string }>(`/api/leads/${draft.lead_id}/eligibility`, json({ ...v, channel: draft.channel, review_due_at: v.review_due_at?.toISOString() || null })); await patch({ eligibility_id: recorded.id }); })}>
        <Alert type="info" showIcon message="记录联系方式不等于允许联系。准入允许时必须填写真实证据与规则版本；系统不会代替你授权。" style={{ marginBottom: 12 }} />
        <Form.Item name="contact_ref" label="邮箱／平台主页" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="contact_source" label="来源"><Input /></Form.Item>
        <Space align="start"><Form.Item name="contact_usable" label="联系方式可用性"><Select style={{ width: 140 }} options={[{ value: "unknown", label: "未知" }, { value: "valid", label: "有效" }, { value: "invalid", label: "无效" }]} /></Form.Item><Form.Item name="eligibility" label="渠道准入"><Select style={{ width: 150 }} options={[{ value: "unknown", label: "待核对" }, { value: "allowed", label: "允许" }, { value: "blocked", label: "禁止" }]} /></Form.Item></Space>
        <Form.Item name="rule_version" label="准入规则版本"><Input /></Form.Item><Form.Item name="evidence" label="准入证据"><Input.TextArea rows={2} /></Form.Item>
        <Form.Item name="review_due_at" label="复核到期时间"><DatePicker showTime /></Form.Item><Button htmlType="submit" loading={busy}>保存联系方式与准入</Button>
      </Form> },
      { key: "content", label: "准备与核对内容", children: <>
        {draft.context.analyses.length ? <><Typography.Paragraph>已确认的问题：{draft.context.analyses[0].facts.join("；")}</Typography.Paragraph><Button disabled={!sender.trim() || !optOut.trim() || busy} onClick={() => act(async () => { const c = await api<{ id: string }>(`/api/leads/${draft.lead_id}/content`, json({ kind: "message_short", analysis_id: draft.context.analyses[0].id, sender_identity: sender, opt_out_text: optOut })); await patch({ content_id: c.id }); })}>按已确认事实生成待审批文案</Button></> : <Alert type="info" message="尚无完成审核且含已确认问题的菜单分析，请先在线索详情补充菜单和核对事实。" />}
        {piece && <><Input.TextArea aria-label="文案内容" value={text} onChange={(e) => { setText(e.target.value); setConfirmed(false); }} rows={7} style={{ marginTop: 12 }} /><Space wrap style={{ marginTop: 12 }}><Button disabled={busy || text === piece.body_text} onClick={() => act(async () => { const revised = await api<{ id: string }>(`/api/content/${piece.id}/revise`, json({ body_text: text })); await patch({ content_id: revised.id }); })}>保存为新版本（需重新审批）</Button><Checkbox checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)}>我已核对引用事实、身份和退出说明</Checkbox><Button type="primary" disabled={!confirmed || text !== piece.body_text || busy || piece.approved} onClick={() => act(async () => { await api(`/api/content/${piece.id}/approve`, json({ decision: "approved" })); await patch({ content_id: piece.id }); setConfirmed(false); })}>{piece.approved ? "审批有效" : "确认审批此版本"}</Button></Space></>}
      </> },
    ]} />
  </Card>;
}

export default function PrepareOutreach({ open, leadIds, batchKey, returnTo, onClose, onChanged, initialChannel = "email", savedDrafts, purpose = "initial" }: { open: boolean; leadIds: string[]; batchKey?: string; returnTo: string; onClose: () => void; onChanged?: () => void; initialChannel?: string; savedDrafts?: Draft[]; purpose?: "initial" | "followup" }) {
  const [channel, setChannel] = useState(initialChannel);
  const [mode, setMode] = useState("manual");
  const [assigned, setAssigned] = useState<string>();
  const [rows, setRows] = useState<Prepared[]>([]);
  const [assignees, setAssignees] = useState<Assignee[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [note, setNote] = useState<string>();
  const [sender, setSender] = useState("");
  const [optOut, setOptOut] = useState("Please let me know if you would prefer not to hear from us again.");
  const [targetLink, setTargetLink] = useState<string>();
  useEffect(() => { if (open) { setRows((savedDrafts || []).map((draft) => ({ lead_id: draft.lead_id, name: draft.context.lead.name, draft }))); setError(undefined); setNote(undefined); setTargetLink(undefined); setChannel(savedDrafts?.[0]?.channel || initialChannel); setMode("manual"); api<Assignee[]>("/api/communication/assignees").then(setAssignees).catch((e) => setError(e.message)); } }, [open, initialChannel, savedDrafts]);
  const check = async () => { setBusy(true); setError(undefined); const collected: Prepared[] = []; try { for (let offset = 0; offset < leadIds.length; offset += 25) { const next = await api<{ items: Prepared[] }>("/api/communication/prepare", json({ lead_ids: leadIds.slice(offset, offset + 25), channel, execution_mode: mode, batch_key: batchKey, assigned_to: assigned, purpose })); collected.push(...next.items); setRows([...collected]); setNote(`已检查 ${collected.length}/${leadIds.length} 家`); } onChanged?.(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  const activate = async () => { const candidates = rows.filter((r) => r.draft?.status === "draft" && !r.draft.blockers.length).map((r) => r.draft!.id); const group = crypto.randomUUID(); setBusy(true); setError(undefined); let first: { task: string; lead: string } | undefined; let created = false; try { for (let offset = 0; offset < candidates.length; offset += 100) { const result = await api<{ items: { draft_id: string; task_id?: string; error?: string; reused?: boolean }[] }>("/api/communication/activate", json({ draft_ids: candidates.slice(offset, offset + 100), group_id: group })); result.items.forEach((item) => { const row = rows.find((r) => r.draft?.id === item.draft_id); if (item.task_id && row && !first) first = { task: item.task_id, lead: row.lead_id }; if (item.task_id && !item.reused) created = true; }); setRows((old) => old.map((r) => { const resultRow = result.items.find((i) => i.draft_id === r.draft?.id); return resultRow ? { ...r, error: resultRow.error, activated_task_id: resultRow.task_id, draft: r.draft && resultRow.task_id ? { ...r.draft, status: "converted", task_id: resultRow.task_id } : r.draft } : r; })); } if (first) setTargetLink(taskLink({ lead: first.lead, task: first.task, batch: batchKey, channel, preparation: created ? group : undefined, returnTo })); setNote("任务已准备；尚未发送任何消息。缺项草稿已保留。"); onChanged?.(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  const ready = rows.filter((r) => r.draft?.status === "draft" && !r.draft.blockers.length).length;
  return <Drawer title={`准备触达 · ${leadIds.length} 家${purpose === "followup" ? " · 人工准备跟进" : ""}`} open={open} width={980} onClose={() => { if (!busy) onClose(); }} maskClosable={!busy}>
    <OutreachJourney current={1} />
    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
    <Alert type="info" showIcon message="准备草稿可保存缺项；创建任务不会发送消息。已有任务会复用，批量操作逐家显示结果。" style={{ marginBottom: 12 }} />
    <Space wrap style={{ marginBottom: 12 }}><Select aria-label="触达渠道" value={channel} options={CHANNELS} style={{ width: 180 }} disabled={busy || !!rows.length} onChange={(v) => { setChannel(v); setMode("manual"); }} /><Select aria-label="默认执行方式" value={mode} style={{ width: 220 }} disabled={busy} options={MODES.filter((m) => m.value === "manual" || (m.value === "gmail" && channel === "email") || (m.value === "social" && ["facebook", "instagram"].includes(channel)))} onChange={setMode} /><Select allowClear aria-label="默认负责人" placeholder="负责人（默认当前操作者）" value={assigned} onChange={setAssigned} disabled={busy} style={{ width: 200 }} options={assignees.map((a) => ({ value: a.username, label: a.display_name || a.username }))} /><Button loading={busy} onClick={check} disabled={!leadIds.length}>检查并保存草稿</Button></Space>
    <Space wrap style={{ marginBottom: 16 }}><Input aria-label="发件身份" value={sender} onChange={(e) => setSender(e.target.value)} placeholder="真实发件身份（生成文案时使用）" style={{ width: 300 }} /><Input aria-label="退出说明" value={optOut} onChange={(e) => setOptOut(e.target.value)} placeholder="退出说明" style={{ width: 550 }} /></Space>
    {note && <Alert type="success" showIcon message={note} style={{ marginBottom: 12 }} />}
    <Space wrap style={{ marginBottom: 16 }}><Button type="primary" disabled={!ready || busy} loading={busy} onClick={activate}>创建就绪任务（{ready}）</Button>{targetLink && <Link href={targetLink}>进入本次触达工作台 →</Link>}</Space>
    <Table<Prepared> rowKey="lead_id" size="small" pagination={{ pageSize: 10 }} dataSource={rows} columns={[
      { title: "客户", render: (_, r) => r.name || r.draft?.context.lead.name || r.lead_id },
      { title: "准备结果", render: (_, r) => r.error ? <Typography.Text type="danger">{r.error}</Typography.Text> : r.activated_task_id ? <Tag color="green">任务已就绪，尚未发送</Tag> : r.existing_task ? <Tag color="blue">已有任务 · {r.existing_task.status}</Tag> : <Tag color={r.draft?.blockers.length ? "orange" : "green"}>{r.draft?.blockers.length ? `待补 ${r.draft.blockers.length} 项` : "可创建任务"}</Tag> },
      { title: "缺项／操作", render: (_, r) => r.existing_task || r.activated_task_id ? <Link href={taskLink({ lead: r.lead_id, task: r.existing_task?.id || r.activated_task_id, batch: batchKey, returnTo })}>查看任务与会话</Link> : r.draft?.blockers.join("；") },
    ]} expandable={{ rowExpandable: (r) => !!r.draft && r.draft.status === "draft", expandedRowRender: (r) => r.draft && <DraftEditor draft={r.draft} assignees={assignees} returnTo={returnTo} sender={sender} optOut={optOut} onChange={(draft) => setRows((old) => old.map((item) => item.lead_id === draft.lead_id ? { ...item, draft, error: undefined } : item))} /> }} />
  </Drawer>;
}
