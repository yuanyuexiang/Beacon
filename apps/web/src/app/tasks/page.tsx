"use client";
import Button from "@/components/AccessButton";
import { Alert, Card, Checkbox, Col, DatePicker, Drawer, Empty, Form, Input, Modal, Row, Select, Space, Table, Tabs, Tag, Timeline, Typography } from "antd";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import dayjs from "dayjs";
import { api, json } from "@/lib/api";
import { useOperator } from "@/lib/auth";
import { Assignee, CHANNELS, CommunicationTask, Contact, LeadContext, MODES, PROGRESS, Progress, safeReturnTo } from "@/lib/communication";
import { channelLabel, label } from "@/lib/format";
import { HeroBand } from "@/components/ui";
import OutreachJourney from "@/components/OutreachJourney";
import PrepareOutreach from "@/components/PrepareOutreach";
import GmailOutreach from "@/components/GmailOutreach";
import SocialOutreach from "@/components/SocialOutreach";

type Customer = { id: string; name: string; postcode: string | null; progress: Progress };
type Activity = { timeline: { id: string; channel: string | null; direction: string; at: string; summary: string; source: string; status: string }[]; deliveries: { id: string; task_id: string; channel: string; status: string; source: string; at: string; error?: string | null; message_id?: string | null }[]; conversations: { id: string; channel: string; at: string; summary: string; source: string }[] };
type ManualPreview = { task_id: string; channel: string; url: string; text: string };
const EMPTY_ACTIVITY: Activity = { timeline: [], deliveries: [], conversations: [] };
const SOURCE: Record<string, string> = { manual: "人工记录", gmail: "Gmail 同步（回复仅邮件头）", meta: "平台同步" };
const ACTIVE = ["pending", "opened", "paused"];

function TasksInner() {
  const { me } = useOperator();
  const canWrite = me?.role === "admin" || me?.role === "member";
  const router = useRouter();
  const sp = useSearchParams();
  const leadId = sp.get("lead") || undefined;
  const batch = sp.get("batch") || undefined;
  const channel = sp.get("channel") || undefined;
  const assigned = sp.get("owner") || undefined;
  const group = sp.get("preparation") || undefined;
  const query = sp.get("q") || "";
  const page = Math.max(1, Number(sp.get("page")) || 1);
  const tab = ["tasks", "conversation", "records"].includes(sp.get("tab") || "") ? sp.get("tab")! : "tasks";
  const back = safeReturnTo(sp.get("returnTo") || (batch ? `/leads?batch=${encodeURIComponent(batch)}` : "/leads"));
  const [rows, setRows] = useState<Customer[]>([]);
  const [total, setTotal] = useState(0);
  const [batches, setBatches] = useState<{ batch_key: string }[]>([]);
  const [owners, setOwners] = useState<Assignee[]>([]);
  const [context, setContext] = useState<LeadContext | null>(null);
  const [activity, setActivity] = useState<Activity>(EMPTY_ACTIVITY);
  const [error, setError] = useState<string>();
  const [success, setSuccess] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [prepare, setPrepare] = useState(false);
  const [unstarted, setUnstarted] = useState(false);
  const [manual, setManual] = useState<ManualPreview>();
  const [confirmed, setConfirmed] = useState(false);
  const [apiTask, setApiTask] = useState<CommunicationTask>();
  const [contact, setContact] = useState<Contact>();
  const [suppression, setSuppression] = useState<Record<string, string>[] | null>(null);
  const [eventForm] = Form.useForm();
  const [contactForm] = Form.useForm();
  const [sentForm] = Form.useForm();
  const eventKey = useRef<string | null>(null);
  const contextRequest = useRef(0);
  const listRequest = useRef(0);
  const navigate = useCallback((patch: Record<string, string | undefined>) => { const params = new URLSearchParams(sp.toString()); Object.entries(patch).forEach(([key, value]) => value ? params.set(key, value) : params.delete(key)); router.replace(`/tasks?${params}`, { scroll: false }); }, [router, sp]);
  const refreshList = useCallback(async () => { const request = ++listRequest.current; const params = new URLSearchParams({ page: String(page) }); if (batch) params.set("batch_key", batch); if (channel) params.set("channel", channel); if (assigned) params.set("assigned_to", assigned); if (query) params.set("q", query); if (group) params.set("preparation_group", group); const result = await api<{ items: Customer[]; total: number }>(`/api/communication/overview?${params}`); if (request === listRequest.current) { setRows(result.items); setTotal(result.total); } }, [page, batch, channel, assigned, query, group]);
  const refreshContext = useCallback(async () => { const request = ++contextRequest.current; if (!leadId) { setContext(null); setUnstarted(false); setActivity(EMPTY_ACTIVITY); return; } const [data, history] = await Promise.all([api<LeadContext>(`/api/communication/leads/${leadId}`), api<Activity>(`/api/communication/activity/${leadId}`)]); if (request === contextRequest.current) { const started = data.tasks.length > 0 || history.timeline.length > 0 || history.conversations.length > 0; setContext(started ? data : null); setUnstarted(!started); setActivity(started ? history : EMPTY_ACTIVITY); } }, [leadId]);
  const refresh = useCallback(async () => { await Promise.all([refreshList(), refreshContext()]); }, [refreshList, refreshContext]);
  useEffect(() => { api<{ batch_key: string }[]>("/api/batches").then(setBatches).catch((e) => setError(e.message)); api<Assignee[]>("/api/communication/assignees").then(setOwners).catch((e) => setError(e.message)); }, []);
  useEffect(() => { refreshList().catch((e) => setError(e.message)); }, [refreshList]);
  useEffect(() => { setContext(null); setActivity(EMPTY_ACTIVITY); setManual(undefined); setApiTask(undefined); setError(undefined); eventForm.resetFields(); eventKey.current = null; refreshContext().catch((e) => setError(e.message)); }, [refreshContext, eventForm]);
  useEffect(() => { if (!leadId && rows[0]) navigate({ lead: rows[0].id }); }, [leadId, rows, navigate]);
  useEffect(() => { const tick = () => { if (!document.hidden && !busy) refresh().catch(() => {}); }; const timer = setInterval(tick, 15000); window.addEventListener("focus", tick); return () => { clearInterval(timer); window.removeEventListener("focus", tick); }; }, [refresh, busy]);
  useEffect(() => { if (contact) { contactForm.resetFields(); contactForm.setFieldsValue({ ...contact, review_due_at: contact.review_due_at ? dayjs(contact.review_due_at) : null }); } }, [contact, contactForm]);
  const act = async (work: () => Promise<void>) => { setBusy(true); setError(undefined); setSuccess(undefined); try { await work(); await refresh(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  const tasks = (context?.tasks || []).filter((t) => (!channel || t.channel === channel) && (!assigned || t.assigned_to === assigned) && (!group || t.preparation_group_id === group));
  const selectedTask = tasks.find((t) => t.id === sp.get("task")) || tasks.find((t) => ACTIVE.includes(t.status)) || tasks[0];
  const inflight = (task: CommunicationTask) => activity.deliveries.some((d) => d.task_id === task.id && ["ready", "queued", "sending", "unknown", "sent"].includes(d.status));
  const openManual = async (task: CommunicationTask) => { const value = await api<ManualPreview>(`/api/communication/tasks/${task.id}/manual-open`, { method: "POST" }); setManual(value); sentForm.resetFields(); setConfirmed(false); navigate({ task: task.id }); };
  const rename = (id: string) => context?.lead.id === id ? context.lead.name : rows.find((r) => r.id === id)?.name || id;
  return <>
    <HeroBand kicker="COMMUNICATION" title="触达任务与回复" subtitle="从名单创建触达任务后，在这里执行、查看回复与继续跟进。" extra={<Space wrap><Link href={back}><Button readOnlySafe>返回来源页面</Button></Link><Button readOnlySafe onClick={() => refresh().catch((e) => setError(e.message))}>刷新进展</Button><Button readOnlySafe onClick={() => api<Record<string, string>[]>("/api/suppressions").then(setSuppression).catch((e) => setError(e.message))}>抑制名单</Button></Space>} />
    <OutreachJourney current={!context ? 0 : ["waiting_reply", "replied", "recorded", "suppressed"].includes(context?.progress.status || "") ? 3 : 2} />
    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
    {success && <Alert type="success" showIcon message={success} style={{ marginBottom: 12 }} />}
    <Space wrap style={{ marginBottom: 16 }}>
      <Select aria-label="来源名单" allowClear placeholder="全部名单" value={batch} style={{ width: 200 }} options={batches.map((b) => ({ value: b.batch_key, label: b.batch_key }))} onChange={(v) => navigate({ batch: v, lead: undefined, task: undefined, draft: undefined, preparation: undefined, page: "1", returnTo: v ? `/leads?batch=${encodeURIComponent(v)}` : "/leads" })} />
      <Select aria-label="沟通渠道筛选" allowClear placeholder="全部渠道" value={channel} options={CHANNELS} style={{ width: 170 }} onChange={(v) => navigate({ channel: v, page: "1" })} />
      <Select aria-label="沟通负责人筛选" allowClear placeholder="全部负责人" value={assigned} style={{ width: 170 }} options={owners.map((o) => ({ value: o.username, label: o.display_name || o.username }))} onChange={(v) => navigate({ owner: v, page: "1" })} />
      <Input.Search key={query} defaultValue={query} placeholder="搜索客户／邮编" allowClear style={{ width: 230 }} onSearch={(q) => navigate({ q: q || undefined, page: "1" })} />
      {group && <Tag closable onClose={() => navigate({ preparation: undefined, page: "1" })}>本次新建任务</Tag>}
    </Space>
    <Row gutter={[16, 16]}>
      <Col xs={24} xl={6}><Card size="small" title={`客户 · ${total}`}>
        <Table<Customer> rowKey="id" size="small" dataSource={rows} pagination={{ current: page, pageSize: 20, total, showSizeChanger: false, onChange: (value) => navigate({ page: String(value) }) }} rowClassName={(r) => r.id === leadId ? "communication-selected" : ""} onRow={(r) => ({ onClick: () => navigate({ lead: r.id, task: undefined, draft: undefined }) })} columns={[{ title: "客户与进展", render: (_, r) => <a onClick={() => navigate({ lead: r.id, task: r.progress.task_id || undefined, draft: r.progress.draft_id || undefined })}><b>{r.name}</b><br /><Tag color={r.progress.status === "suppressed" ? "red" : r.progress.status === "replied" ? "green" : "default"}>{PROGRESS[r.progress.status] || r.progress.status}</Tag><Typography.Text type="secondary">{r.postcode}</Typography.Text></a> }]} />
      </Card></Col>
      <Col xs={24} xl={12}><Card size="small" title={context?.lead.name || "选择客户"}>
        {!context ? <Empty description={unstarted ? "这家门店尚未发起触达，准备草稿请在名单中继续处理。" : "暂无可执行的触达任务。请先在批次与线索中准备并创建任务，或调整当前筛选。"}><Link href={back}>前往批次与线索</Link></Empty> : <>
          <Tag color={context.progress.status === "suppressed" ? "red" : "blue"}>{PROGRESS[context.progress.status]}</Tag>
          <Tabs activeKey={tab} onChange={(value) => navigate({ tab: value })} items={[
            { key: "tasks", label: "待办任务", children: <>
              {!tasks.length ? <Empty description="当前筛选下没有任务，可查看客户会话和发送记录。" /> : tasks.map((t) => <Card key={t.id} size="small" style={{ marginBottom: 12, borderColor: selectedTask?.id === t.id ? "#cf010e" : undefined }} title={<Space wrap><span>{channelLabel(t.channel)}</span><Tag>{label(t.status)}</Tag><Typography.Text type="secondary">{t.execution_mode === "manual" ? "人工执行" : t.execution_mode === "gmail" ? "Gmail 接口" : "已授权社媒会话"}</Typography.Text></Space>}>
                <Typography.Paragraph type="secondary">负责人：{t.assigned_to || "未分配"}{t.follow_up_at ? ` · 跟进提醒：${new Date(t.follow_up_at).toLocaleString("zh-CN")}` : ""}</Typography.Paragraph>
                {t.status_reason && <Alert type="warning" message={t.status_reason} style={{ marginBottom: 12 }} />}
                {inflight(t) && <Alert type="info" message="已有接口发送记录，请先核对排队、发送或未知结果，避免人工重复发送。" style={{ marginBottom: 12 }} />}
                <Space wrap>
                  <Select aria-label={`任务执行方式-${t.id}`} style={{ width: 185 }} value={t.execution_mode} disabled={!canWrite || busy || !ACTIVE.includes(t.status) || inflight(t)} options={MODES.filter((m) => m.value === "manual" || (m.value === "gmail" && t.channel === "email") || (m.value === "social" && ["facebook", "instagram"].includes(t.channel)))} onChange={(execution_mode) => act(async () => { await api(`/api/communication/tasks/${t.id}`, json({ execution_mode }, "PATCH")); })} />
                  <Select aria-label={`任务负责人-${t.id}`} allowClear placeholder="负责人" value={t.assigned_to || undefined} style={{ width: 145 }} disabled={!canWrite || busy || !ACTIVE.includes(t.status) || inflight(t)} options={owners.map((o) => ({ value: o.username, label: o.display_name || o.username }))} onChange={(assigned_to) => act(async () => { await api(`/api/communication/tasks/${t.id}`, json({ assigned_to: assigned_to || null }, "PATCH")); })} />
                  <DatePicker showTime aria-label={`任务跟进提醒-${t.id}`} placeholder="提醒时间" value={t.follow_up_at ? dayjs(t.follow_up_at) : null} disabled={!canWrite || busy || !ACTIVE.includes(t.status) || inflight(t)} onChange={(v) => act(async () => { await api(`/api/communication/tasks/${t.id}`, json({ follow_up_at: v?.toISOString() || null }, "PATCH")); })} />
                  {["pending", "opened"].includes(t.status) && t.execution_mode === "manual" && <Button disabled={busy || inflight(t)} onClick={() => act(() => openManual(t))}>开始人工执行</Button>}
                  {t.execution_mode !== "manual" && <Button disabled={busy} onClick={() => { setApiTask(t); navigate({ task: t.id }); }}>查看接口预览与记录</Button>}
                  {t.status === "paused" && <Button disabled={busy || inflight(t)} onClick={() => act(async () => { await api(`/api/tasks/${t.id}/resume`, json({ reason: "负责人查看回复后明确继续" })); setSuccess("已重新复核并恢复任务，尚未发送"); })}>核对后恢复</Button>}
                  {ACTIVE.includes(t.status) && <Button danger disabled={busy || inflight(t)} onClick={() => act(async () => { await api(`/api/tasks/${t.id}/cancel`, json({ reason: "负责人结束本次触达" })); })}>结束任务</Button>}
                </Space>
              </Card>)}
            </> },
            { key: "conversation", label: "客户会话", children: <>
              <Alert type="info" showIcon message="人工渠道通过下方回填；Gmail 当前同步回复邮件头，不展示未获取的邮件正文。平台会话仅展示已同步内容。" style={{ marginBottom: 12 }} />
              {activity.conversations.map((c) => <Card key={c.id} size="small" title={`${channelLabel(c.channel)} · 平台最近消息`}><p>{c.summary}</p><Typography.Text type="secondary">{new Date(c.at).toLocaleString("zh-CN")} · 平台同步</Typography.Text></Card>)}
              <Timeline items={activity.timeline.map((e) => ({ key: e.id, color: e.direction === "inbound" ? "green" : "blue", children: <><b>{e.direction === "outbound" ? "发出" : e.direction === "note" ? "备注" : "收到／回填"} · {channelLabel(e.channel || "")} · {label(e.status)}</b><p style={{ whiteSpace: "pre-wrap" }}>{e.summary}</p><Typography.Text type="secondary">{new Date(e.at).toLocaleString("zh-CN")} · {SOURCE[e.source] || e.source}</Typography.Text></> }))} />
              <Card size="small" title="记录回复、拒收或下一步">
                <Form form={eventForm} layout="vertical" disabled={!canWrite || busy} onFinish={(v) => act(async () => { eventKey.current ||= `manual:${crypto.randomUUID()}`; await api(`/api/leads/${leadId}/events`, json({ event_key: eventKey.current, kind: v.kind, channel: v.channel || null, occurred_at: v.occurred_at?.toISOString() || null, payload: { intent: v.intent || "unknown", summary: v.summary || "", contact_ref: v.contact_ref || null } })); eventKey.current = null; eventForm.resetFields(); setSuccess("结果已记录；回复会暂停待发任务，拒收会进入抑制。"); })}>
                  <Space wrap align="start"><Form.Item name="kind" label="结果" rules={[{ required: true }]}><Select style={{ width: 150 }} options={[{ value: "reply", label: "客户已回复" }, { value: "reject", label: "拒绝联系" }, { value: "unsubscribe", label: "退订" }, { value: "bounce", label: "退信／无效" }, { value: "note", label: "沟通备注" }]} /></Form.Item><Form.Item name="channel" label="渠道"><Select allowClear style={{ width: 160 }} options={CHANNELS} /></Form.Item><Form.Item name="intent" label="客户意向"><Select allowClear style={{ width: 150 }} options={[{ value: "positive", label: "有兴趣" }, { value: "quote", label: "希望报价" }, { value: "later", label: "稍后联系" }, { value: "no", label: "无意向" }, { value: "unknown", label: "待明确" }]} /></Form.Item></Space>
                  <Form.Item name="occurred_at" label="实际回复时间（可选）"><DatePicker showTime /></Form.Item><Form.Item name="contact_ref" label="对应联系值（退信或联系值抑制时填写）"><Input /></Form.Item><Form.Item name="summary" label="摘要／约定的下一步"><Input.TextArea rows={2} maxLength={1500} /></Form.Item><Button type="primary" htmlType="submit" loading={busy}>记录沟通结果</Button>
                </Form>
                <Button onClick={() => { setPrepare(true); }}>人工准备下一次跟进</Button><Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>已有未完成任务会复用；跟进时间只作提醒，不会自动发送。</Typography.Paragraph>
              </Card>
            </> },
            { key: "records", label: "发送记录", children: <>
              <Table<Activity["deliveries"][number]> size="small" rowKey="id" pagination={{ pageSize: 10 }} dataSource={[...activity.deliveries, ...activity.timeline.filter((e) => e.direction === "outbound" && e.source === "manual").map((e) => ({ id: e.id, task_id: e.id.replace("task:", ""), channel: e.channel || "", status: e.status, source: "manual", at: e.at, error: undefined, message_id: undefined }))]} columns={[{ title: "渠道", dataIndex: "channel", render: (v) => channelLabel(v) }, { title: "状态", dataIndex: "status", render: (v) => <Tag>{label(v)}</Tag> }, { title: "来源", dataIndex: "source", render: (v) => v === "manual" ? "人工回填" : v }, { title: "发生时间", dataIndex: "at", render: (v) => new Date(v).toLocaleString("zh-CN") }, { title: "详情", render: (_, r) => <>{r.error || r.message_id || "—"}{r.source !== "manual" && <Button readOnlySafe size="small" onClick={() => setApiTask(context.tasks.find((t) => t.id === r.task_id))}>查询／处理</Button>}</> }]} />
            </> },
          ]} />
        </>}
      </Card></Col>
      <Col xs={24} xl={6}><Card size="small" title="客户资料与准备依据">
        {!context ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选中客户后展示" /> : <>
          <Typography.Paragraph>{context.lead.address} {context.lead.postcode}</Typography.Paragraph>{context.lead.website && <p><a href={context.lead.website} target="_blank" rel="noreferrer">查看官网</a></p>}
          <Space wrap><Link href={`/leads/${context.lead.id}?returnTo=${encodeURIComponent(back)}`}>完整线索详情</Link><Link href={`/leads/${context.lead.id}?returnTo=${encodeURIComponent(back)}#menu-files`}>补充／核对菜单</Link></Space>
          <Typography.Title level={5}>已发现的联系方式</Typography.Title>
          {context.contacts.length ? context.contacts.map((e) => <div key={e.id} style={{ padding: "8px 0", borderBottom: "1px solid #eee" }}><b>{channelLabel(e.channel, e.contact_ref)}</b><p style={{ overflowWrap: "anywhere", margin: "4px 0" }}>{e.contact_ref || "未填写"}</p><Tag color={e.suppressed ? "red" : e.eligibility === "allowed" ? "green" : "default"}>{e.suppressed ? "已抑制" : e.eligibility === "allowed" ? "准入允许" : "准入待核对"}</Tag><Button size="small" onClick={() => setContact(e)}>核对准入</Button></div>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无联系方式，请在线索详情补充" />}
          <Typography.Title level={5}>菜单问题依据</Typography.Title>{context.analyses.length ? context.analyses.map((a) => <Typography.Paragraph key={a.id}>已审核 v{a.version}：{a.facts.join("；")}</Typography.Paragraph>) : <Typography.Paragraph type="secondary">还没有已审核、已确认的问题，准备抽屉会提示补齐，不能虚构营销理由。</Typography.Paragraph>}
          <Typography.Title level={5}>文案与审批</Typography.Title>{context.contents.map((c) => <p key={c.id}>文案 v{c.version} · <Tag color={c.approved ? "green" : "default"}>{c.approved ? "审批有效" : "需核对／审批"}</Tag></p>)}
        </>}
      </Card></Col>
    </Row>
    <PrepareOutreach open={prepare} leadIds={leadId ? [leadId] : []} batchKey={batch} returnTo={back} initialChannel={channel || context?.drafts?.[0]?.channel || "email"} purpose="followup" onClose={() => { setPrepare(false); refresh().catch((e) => setError(e.message)); }} onChanged={() => refresh().catch((e) => setError(e.message))} />
    <Modal title="人工执行 · 打开平台不等于已发送" open={!!manual} onCancel={() => setManual(undefined)} footer={null} width={720}>
      {error && <Alert type="error" message={error} style={{ marginBottom: 12 }} />}
      {manual && <><Alert type="info" showIcon message="复制已审批文案，到平台人工发送；实际发送后再回填时间。" /><Typography.Paragraph style={{ whiteSpace: "pre-wrap", marginTop: 16 }}>{manual.text}</Typography.Paragraph><Space><Button disabled={busy} onClick={() => act(async () => { const fresh = await api<ManualPreview>(`/api/communication/tasks/${manual.task_id}/manual-open`, { method: "POST" }); setManual(fresh); await navigator.clipboard.writeText(fresh.text); setSuccess("已复制已审批文案，尚未记录为发送"); })}>复制已审批文案</Button><a href={manual.url} target="_blank" rel="noreferrer">打开 {channelLabel(manual.channel)} 联系入口 ↗</a></Space>
        <Form form={sentForm} layout="vertical" disabled={!canWrite || busy} style={{ marginTop: 20 }} onFinish={(v) => act(async () => { if (!confirmed) throw new Error("请先确认已经在平台实际发送"); await api(`/api/tasks/${manual.task_id}/sent`, json({ sent_at: v.sent_at.toISOString(), notes: v.notes })); setManual(undefined); setSuccess("已记录人工发送，客户进展已更新"); })}><Form.Item name="sent_at" label="实际发送时间" rules={[{ required: true }]}><DatePicker showTime /></Form.Item><Form.Item name="notes" label="发送备注"><Input.TextArea maxLength={1500} /></Form.Item><Checkbox checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)}>我已在平台实际发送，并核对收件人和内容</Checkbox><Button type="primary" htmlType="submit" disabled={!confirmed} loading={busy} style={{ marginLeft: 12 }}>记录已人工发送</Button></Form></>}
    </Modal>
    <Drawer title="接口预览与发送记录" width={1000} open={!!apiTask} onClose={() => setApiTask(undefined)} destroyOnHidden>
      {apiTask?.channel === "email" ? <GmailOutreach tasks={[apiTask]} name={rename} onChanged={refresh} focusTaskId={apiTask.id} /> : apiTask && <SocialOutreach tasks={[apiTask]} name={rename} onChanged={refresh} focusTaskId={apiTask.id} />}
    </Drawer>
    <Modal title="人工核对渠道准入" open={!!contact} onCancel={() => setContact(undefined)} footer={null}>
      {error && <Alert type="error" message={error} />}
      <Form form={contactForm} layout="vertical" disabled={!canWrite || busy} onFinish={(v) => act(async () => { await api(`/api/leads/${leadId}/eligibility`, json({ channel: contact?.channel, contact_ref: contact?.contact_ref, contact_source: contact?.contact_source, contact_usable: v.contact_usable, eligibility: v.eligibility, rule_version: v.rule_version, evidence: v.evidence, review_due_at: v.review_due_at?.toISOString() || null })); setContact(undefined); setSuccess("渠道准入已保存；执行时仍将再次复核"); })}>
        <p>{channelLabel(contact?.channel || "", contact?.contact_ref)} · {contact?.contact_ref}</p><Alert type="info" message="本处保留任务关联的联系值；更换收件人需结束旧任务，再重新准备，避免误发。" style={{ marginBottom: 12 }} />
        <Form.Item name="contact_usable" label="联系方式可用性"><Select options={[{ value: "unknown", label: "未知" }, { value: "valid", label: "有效" }, { value: "invalid", label: "无效" }]} /></Form.Item><Form.Item name="eligibility" label="渠道准入"><Select options={[{ value: "unknown", label: "待核对" }, { value: "allowed", label: "允许" }, { value: "blocked", label: "禁止" }]} /></Form.Item><Form.Item name="rule_version" label="规则版本"><Input /></Form.Item><Form.Item name="evidence" label="真实准入证据"><Input.TextArea /></Form.Item><Form.Item name="review_due_at" label="复核到期时间"><DatePicker showTime /></Form.Item><Button htmlType="submit" type="primary">保存准入</Button>
      </Form>
    </Modal>
    <Modal title="抑制名单" open={!!suppression} onCancel={() => setSuppression(null)} footer={null} width={850}><Table rowKey="id" dataSource={suppression || []} columns={[{ title: "客户", dataIndex: "lead_id" }, { title: "联系值", dataIndex: "contact_ref" }, { title: "原因", dataIndex: "reason" }, { title: "时间", dataIndex: "created_at" }]} /></Modal>
    <style>{`.communication-selected td { background: #fff4f0 !important; }`}</style>
  </>;
}
export default function TasksPage() { return <Suspense fallback={<p>读取沟通工作台…</p>}><TasksInner /></Suspense>; }
