"use client";
import { useOutreachIdentity } from "@/lib/useOutreachIdentity";
import { Alert, Card, Checkbox, Collapse, DatePicker, Drawer, Form, Input, Select, Space, Table, Tag, Typography } from "antd";
import Button from "@/components/AccessButton";
import ContactReviewActions from "./ContactReviewActions";
import OutreachJourney from "@/components/OutreachJourney";
import Link from "next/link";
import dayjs from "dayjs";
import { useEffect, useRef, useState } from "react";
import { api, json } from "@/lib/api";
import { Assignee, CHANNELS, Draft, LeadContext, MODES, Prepared, taskLink } from "@/lib/communication";
import { CONTACT_RANK_LABELS, contactRank } from "@/lib/contact-ranking";
import { useOperator } from "@/lib/auth";
import { channelLabel } from "@/lib/format";

function sourceText(source: { id: string; text: string }): string {
  try {
    const d = JSON.parse(source.text);
    if (source.id === "store") return [d.name, d.address, d.postcode].filter(Boolean).join(" · ");
    if (source.id === "services") return [d.company, d.services, d.proof, d.constraints].filter(Boolean).join("\n");
    if (source.id === "menu") return [d.items?.map((i: {name: string; price: string}) => `${i.name} ${i.price || ""}`).join("；"), d.confirmed_problems?.length ? `已确认问题：${d.confirmed_problems.join("；")}` : "未确认明显问题"].filter(Boolean).join("\n");
    return [d.owner, ...(d.citations || []).map((c: {quote?: string}) => c.quote)].filter(Boolean).join("\n");
  } catch { return source.text; }
}

function blockerText(value: string) {
  return value === "文案审批无效：内容状态为 draft" ? "消息尚未确认：请核对下方正文，再点击“确认消息内容”" : value;
}

function DraftEditor({ draft, assignees, returnTo, sender, optOut, preferredAnalysisId, onViewMenus, onChange }: { onViewMenus?: () => void; preferredAnalysisId?: string; draft: Draft; assignees: Assignee[]; returnTo: string; sender: string; optOut: string; onChange: (value: Draft) => void }) {
  const { me } = useOperator();
  const readOnly = !["admin", "director", "member"].includes(me?.role || "");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [sections, setSections] = useState<string[]>(["content"]);
  const [admissionNotice, setAdmissionNotice] = useState<string>();
  const [text, setText] = useState("");
  const [subject, setSubject] = useState("");
  const [analysisId, setAnalysisId] = useState<string>();
  const piece = draft.context.contents.find((c) => c.id === draft.content_id);
  const contact = draft.context.contacts.find((e) => e.id === draft.eligibility_id);
  const [contactForm] = Form.useForm();
  const firstAnalysisId = draft.context.analyses[0]?.id;
  useEffect(() => { setAnalysisId(piece?.id ? piece.analysis_id || undefined : preferredAnalysisId || firstAnalysisId); }, [piece?.id, piece?.analysis_id, preferredAnalysisId, firstAnalysisId]);
  const selectedAnalysis = draft.context.analyses.find((a) => a.id === analysisId);
  useEffect(() => { setText(piece?.body_text || ""); setSubject(piece?.subject || ""); setConfirmed(false); }, [piece?.id, piece?.body_text, piece?.subject]);
  useEffect(() => { contactForm.resetFields(); contactForm.setFieldsValue({ channel: draft.channel, contact_ref: contact?.contact_ref, contact_source: contact?.contact_source, contact_usable: contact?.contact_usable || "unknown", eligibility: contact?.eligibility || "unknown", evidence: contact?.evidence, rule_version: contact?.rule_version?.startsWith("ai-admission:") ? "manual-review:v1" : contact?.rule_version, review_due_at: contact?.review_due_at ? dayjs(contact.review_due_at) : null }); }, [contactForm, contact?.id, contact?.evidence, contact?.eligibility, contact?.rule_version, contact?.review_due_at, contact?.contact_ref, contact?.contact_source, contact?.contact_usable, draft.channel]);
  const patch = async (changes: Record<string, unknown>) => { const value = await api<Draft>(`/api/communication/drafts/${draft.id}`, json(changes, "PATCH")); onChange(value); return value; };
  const act = async (work: () => Promise<unknown>) => { setBusy(true); setError(undefined); try { await work(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  const refreshDraft = async () => {
    const next = await api<Draft>(`/api/communication/drafts/${draft.id}`);
    onChange(next);
    return next;
  };
  const admissionBlocked = draft.blockers.some(value => /准入|联系方式|邮箱|抑制/.test(value));
  const verifyAdmission = () => act(async () => {
    setAdmissionNotice(undefined);
    await api(`/api/leads/${draft.lead_id}/auto-admission?refresh=false`, { method: "POST" });
    const next = await refreshDraft();
    setAdmissionNotice(next.blockers.some(value => /准入|联系方式|邮箱|抑制/.test(value))
      ? "核验已完成，但仍需处理下面的具体缺项；可补充真实依据后再核验，或打开准入设置。"
      : "准入检查已通过，创建条件已更新。");
  });
  const choices = MODES.filter((m) => m.value === "manual" || (m.value === "gmail" && draft.channel === "email") || (m.value === "social" && ["facebook", "instagram"].includes(draft.channel)));
  return <Card size="small" title="触达消息">
    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
    {draft.blockers.length > 0 && <Alert type="warning" showIcon message="尚不能创建可执行任务，草稿已保存" description={<><ul>{draft.blockers.map(value => <li key={value}>{blockerText(value)}</li>)}</ul><Space wrap>
      {contact && admissionBlocked && <Button disabled={busy || readOnly} onClick={verifyAdmission}>重新核验准入</Button>}
      {contact && admissionBlocked && <ContactReviewActions leadId={draft.lead_id} row={contact} website={draft.context.lead.website} busy={busy || readOnly} onAI={() => {}} onAdmission={verifyAdmission} onChanged={async () => { await refreshDraft(); }} />}
      {!contact && <Button readOnlySafe onClick={() => setSections(["eligibility", "content"])}>补充联系方式</Button>}
      {draft.blockers.some(value => /文案|消息/.test(value)) && <Button readOnlySafe onClick={() => setSections(["content"])}>核对消息内容</Button>}
      <Button readOnlySafe disabled={busy} onClick={() => act(refreshDraft)}>重新检查创建条件</Button>
    </Space></>} style={{ marginBottom: 12 }} />}
    {admissionNotice && <Alert type="info" showIcon message={admissionNotice} style={{ marginBottom: 12 }} />}
    <Collapse size="small" style={{ marginBottom: 12 }} items={[{ key: "execution", label: `执行安排 · ${choices.find((c) => c.value === draft.execution_mode)?.label || "人工执行"}${draft.assigned_to ? ` · ${draft.assigned_to}` : ""}`, children: <Space wrap>
      <Select aria-label="执行方式" value={draft.execution_mode} style={{ width: 210 }} disabled={busy || readOnly} options={choices} onChange={(execution_mode) => act(() => patch({ execution_mode }))} />
      <Select aria-label="负责人" allowClear value={draft.assigned_to || undefined} style={{ width: 170 }} placeholder="负责人" disabled={busy || readOnly} options={assignees.map((a) => ({ value: a.username, label: a.display_name || a.username }))} onChange={(assigned_to) => act(() => patch({ assigned_to: assigned_to || null }))} />
      <DatePicker showTime aria-label="跟进提醒时间" placeholder="跟进提醒时间（不自动发送）" value={draft.follow_up_at ? dayjs(draft.follow_up_at) : null} disabled={busy || readOnly} onChange={(v) => act(() => patch({ follow_up_at: v?.toISOString() || null }))} />
      {onViewMenus ? <Button readOnlySafe type="link" onClick={onViewMenus}>查看菜单资料</Button> : <Link href={`/leads/${draft.lead_id}?returnTo=${encodeURIComponent(returnTo)}`}>菜单与客户资料</Link>}
    </Space> }]} />
    <Form layout="vertical">
      <Form.Item label="发给谁"><Select allowClear placeholder="选择本渠道的联系方式" value={draft.eligibility_id || undefined} options={draft.context.contacts.filter((e) => e.channel === draft.channel).sort((a, b) => contactRank(a.recommendation) - contactRank(b.recommendation)).map((e) => ({ value: e.id, label: `${e.recommendation ? CONTACT_RANK_LABELS[e.recommendation.recommendation] + " · " : ""}${e.contact_ref || "未填写"} · ${(e.auto_admission?.status || e.eligibility) === "allowed" ? "准入已允许" : e.auto_admission?.reason || "准入待核对"}${e.suppressed ? " · 已抑制" : ""}` }))} onChange={(eligibility_id) => act(() => patch({ eligibility_id: eligibility_id || null }))} disabled={busy || readOnly} /></Form.Item>
      <Form.Item hidden={!draft.context.contents.length}><Collapse size="small" items={[{ key: "history", label: `历史消息（${draft.context.contents.length}）`, children: <Select allowClear placeholder="选择已有消息" value={draft.content_id || undefined} options={draft.context.contents.map((c) => ({ value: c.id, label: `${c.mode === "menu_inquiry" ? "询问菜单／负责人" : "菜单合作消息"} v${c.version} · ${c.approved ? "审批有效" : c.reason || "待审批"}` }))} onChange={(content_id) => act(() => patch({ content_id: content_id || null }))} disabled={busy || readOnly} style={{ width: "100%" }} /> }]} /></Form.Item>
    </Form>
    <Collapse activeKey={sections} onChange={keys => setSections(typeof keys === "string" ? [keys] : keys)} items={[
      { key: "eligibility", label: "补充联系方式／人工核对渠道准入", children: <Form form={contactForm} layout="vertical" disabled={busy || readOnly} onFinish={(v) => act(async () => { const recorded = await api<{ id: string }>(`/api/leads/${draft.lead_id}/eligibility`, json({ ...v, channel: draft.channel, review_due_at: v.review_due_at?.toISOString() || null })); await patch({ eligibility_id: recorded.id }); })}>
        <Alert type="info" showIcon message="记录联系方式不等于允许联系。准入允许时必须填写真实证据与规则版本；系统不会代替你授权。" style={{ marginBottom: 12 }} />
        <Form.Item name="contact_ref" label="邮箱／平台主页" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="contact_source" label="来源"><Input /></Form.Item>
        <Space align="start"><Form.Item name="contact_usable" label="联系方式可用性"><Select style={{ width: 140 }} options={[{ value: "unknown", label: "未知" }, { value: "valid", label: "有效" }, { value: "invalid", label: "无效" }]} /></Form.Item><Form.Item name="eligibility" label="渠道准入"><Select style={{ width: 150 }} options={[{ value: "unknown", label: "待核对" }, { value: "allowed", label: "允许" }, { value: "blocked", label: "禁止" }]} /></Form.Item></Space>
        <Form.Item name="rule_version" label="准入规则版本"><Input /></Form.Item><Form.Item name="evidence" label="准入证据"><Input.TextArea rows={2} /></Form.Item>
        <Form.Item name="review_due_at" label="复核到期时间"><DatePicker showTime /></Form.Item><Button htmlType="submit" loading={busy}>保存联系方式与准入</Button>
      </Form> },
      { key: "content", label: "发送什么", children: <>
        <Typography.Paragraph type="secondary">结合门店、已核对菜单与我们的服务起草；没有菜单也可以询问菜单或负责人。</Typography.Paragraph>
        <Select aria-label="文案引用的菜单分析" allowClear placeholder="未选择菜单：询问菜单或负责人" value={analysisId} onChange={setAnalysisId} style={{ width: "100%", marginBottom: 12 }} options={draft.context.analyses.map((a) => ({ value: a.id, label: `${a.label || "菜单"} · 分析 v${a.version}${a.facts.length ? " · 有已确认问题" : " · 未确认明显问题"}` }))} />
        {selectedAnalysis?.facts.length ? <Typography.Paragraph>可引用的问题：{selectedAnalysis.facts.join("；")}</Typography.Paragraph> : null}
        <Space wrap><Button type="primary" loading={busy} disabled={!sender.trim() || !optOut.trim() || busy} onClick={() => act(async () => { const c = await api<{ id: string }>(`/api/leads/${draft.lead_id}/outreach-message`, json({ analysis_id: analysisId || null, eligibility_id: draft.eligibility_id, channel: draft.channel, sender_identity: sender, opt_out_text: optOut })); await patch({ content_id: c.id }); })}>{piece ? "AI 重新起草消息" : "AI 起草触达消息"}</Button>{me?.role === "admin" ? <Link href="/settings">维护我们的服务资料</Link> : <Typography.Text type="secondary">服务资料由管理员维护</Typography.Text>}</Space>
        {(!sender.trim() || !optOut.trim()) && <Typography.Paragraph type="secondary">请展开“发件身份与退出说明”并填写后起草。</Typography.Paragraph>}
        {piece?.rationale && <Collapse size="small" style={{ marginTop: 12 }} items={[{ key: "basis", label: "为什么这样写 · 生成依据", children: <><p>{piece.rationale}</p>{piece.missing?.length ? <p>待补信息：{piece.missing.join("；")}</p> : null}{piece.sources?.map((s) => <div key={s.id}><strong>{({store: "门店资料", services: "我们的服务", menu: "已核对菜单", operation: "经营特点", recipient: "联系人职责"} as Record<string, string>)[s.id] || s.id}</strong><pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>{sourceText(s)}</pre></div>)}</> }]} />}
        {piece && <>{draft.channel === "email" && <Form.Item label="邮件主题" style={{ marginTop: 12, marginBottom: 0 }}><Input aria-label="邮件主题" maxLength={200} disabled={readOnly} value={subject} onChange={(e) => { setSubject(e.target.value); setConfirmed(false); }} /></Form.Item>}<Input.TextArea aria-label="文案内容" disabled={readOnly} value={text} onChange={(e) => { setText(e.target.value); setConfirmed(false); }} rows={7} style={{ marginTop: 12 }} /><Space wrap style={{ marginTop: 12 }}><Button disabled={busy || text === piece.body_text && subject === (piece.subject || "")} onClick={() => act(async () => { const revised = await api<{ id: string }>(`/api/content/${piece.id}/revise`, json({ body_text: text, subject })); await patch({ content_id: revised.id }); })}>保存修改</Button><Checkbox checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)}>我已核对引用事实、身份和退出说明</Checkbox><Button type="primary" disabled={!confirmed || (text !== piece.body_text || subject !== (piece.subject || "")) || busy || piece.approved} onClick={() => act(async () => { await api(`/api/content/${piece.id}/approve`, json({ decision: "approved" })); await patch({ content_id: piece.id }); setConfirmed(false); })}>{piece.approved ? "内容已确认" : "确认消息内容"}</Button></Space></>}
      </> },
    ]} />
  </Card>;
}

export default function PrepareOutreach({ open, leadIds, batchKey, returnTo, onClose, onChanged, initialChannel = "email", savedDrafts, purpose = "initial", onViewMenus, embedded = false, initialContactId, preferredAnalysisId, dataRevision, selectionRequest }: { onViewMenus?: () => void; embedded?: boolean; dataRevision?: string; selectionRequest?: number; initialContactId?: string; preferredAnalysisId?: string; open: boolean; leadIds: string[]; batchKey?: string; returnTo: string; onClose: () => void; onChanged?: () => void; initialChannel?: string; savedDrafts?: Draft[]; purpose?: "initial" | "followup" }) {
  const [channel, setChannel] = useState(initialChannel);
  const [mode, setMode] = useState("manual");
  const [assigned, setAssigned] = useState<string>();
  const [rows, setRows] = useState<Prepared[]>([]);
  const [assignees, setAssignees] = useState<Assignee[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [note, setNote] = useState<string>();
  const { sender, setSender, optOut, setOptOut, identityError } = useOutreachIdentity();
  const rowsEpoch = useRef(0);
  const changed = useRef(onChanged);
  useEffect(() => { changed.current = onChanged; }, [onChanged]);
  const [context, setContext] = useState<LeadContext>();
  const [loadingContext, setLoadingContext] = useState(false);
  const [targetLink, setTargetLink] = useState<string>();
  const leadKey = leadIds.join(",");
  const identity = leadIds.length === 1 ? leadIds[0] : undefined;
  const selectedRequest = useRef<string | undefined>(undefined);
  const initialized = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (!open) return;
    let active = true;
    const epoch = rowsEpoch.current;
    const resetKey = `${leadKey}:${initialChannel}:${selectionRequest || ""}:${open}`;
    if (!embedded || initialized.current !== resetKey) {
      initialized.current = resetKey;
      setRows((savedDrafts || []).map((draft) => ({ lead_id: draft.lead_id, name: draft.context.lead.name, draft })));
      setError(undefined); setNote(undefined); setTargetLink(undefined); setChannel(savedDrafts?.[0]?.channel || initialChannel); setMode("manual");
    }
    api<Assignee[]>("/api/communication/assignees").then((a) => { if (active) setAssignees(a); }).catch((e) => { if (active) setError(e.message); });
    if (embedded && identity) {
      setLoadingContext(true);
      (async () => {
        const next = await api<LeadContext>(`/api/communication/leads/${identity}`);
        if (!active) return;
        setContext(next);
        if (initialContactId && selectedRequest.current !== `${identity}:${selectionRequest || initialContactId}`) {
          selectedRequest.current = `${identity}:${selectionRequest || initialContactId}`;
          const response = await api<{ items: Prepared[] }>("/api/communication/prepare", json({ lead_ids: [identity], channel: initialChannel, execution_mode: "manual", purpose }));
          if (!active) return;
          const row = response.items[0];
          if (row?.draft) row.draft = await api<Draft>(`/api/communication/drafts/${row.draft.id}`, json({ eligibility_id: initialContactId }, "PATCH"));
          if (active) { setRows(response.items); changed.current?.(); }
        } else {
          const existing = next.drafts?.find((d) => d.channel === initialChannel) || next.drafts?.[0];
          if (existing && epoch === rowsEpoch.current) { setRows([{ lead_id: identity, name: next.lead.name, draft: existing }]); setChannel(existing.channel); setMode(existing.execution_mode); }
        }
      })().catch((e) => { if (active) setError(e.message); }).finally(() => { if (active) setLoadingContext(false); });
    }
    return () => { active = false; };
  }, [open, initialChannel, savedDrafts, embedded, initialContactId, leadKey, purpose, identity, dataRevision, selectionRequest]);

  const check = async () => { rowsEpoch.current++; setBusy(true); setError(undefined); const collected: Prepared[] = []; try { for (let offset = 0; offset < leadIds.length; offset += 25) { const next = await api<{ items: Prepared[] }>("/api/communication/prepare", json({ lead_ids: leadIds.slice(offset, offset + 25), channel, execution_mode: mode, batch_key: batchKey, assigned_to: assigned, purpose })); collected.push(...next.items); setRows([...collected]); setNote(`已检查 ${collected.length}/${leadIds.length} 家`); } onChanged?.(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  const activate = async () => { const candidates = rows.filter((r) => r.draft?.status === "draft" && !r.draft.blockers.length).map((r) => r.draft!.id); const group = crypto.randomUUID(); setBusy(true); setError(undefined); let first: { task: string; lead: string } | undefined; let created = false; try { for (let offset = 0; offset < candidates.length; offset += 100) { const result = await api<{ items: { draft_id: string; task_id?: string; error?: string; reused?: boolean }[] }>("/api/communication/activate", json({ draft_ids: candidates.slice(offset, offset + 100), group_id: group })); result.items.forEach((item) => { const row = rows.find((r) => r.draft?.id === item.draft_id); if (item.task_id && row && !first) first = { task: item.task_id, lead: row.lead_id }; if (item.task_id && !item.reused) created = true; }); setRows((old) => old.map((r) => { const resultRow = result.items.find((i) => i.draft_id === r.draft?.id); return resultRow ? { ...r, error: resultRow.error, activated_task_id: resultRow.task_id, draft: r.draft && resultRow.task_id ? { ...r.draft, status: "converted", task_id: resultRow.task_id } : r.draft } : r; })); } if (first) setTargetLink(taskLink({ lead: first.lead, task: first.task, batch: batchKey, channel, preparation: created ? group : undefined, returnTo })); setNote("任务已准备；尚未发送任何消息。缺项草稿已保留。"); onChanged?.(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  const ready = rows.filter((r) => r.draft?.status === "draft" && !r.draft.blockers.length).length;
  const body = <>
    {!embedded && <OutreachJourney current={1} />}
    {embedded && context && !rows.length && <Typography.Paragraph type="secondary">选择渠道并保存草稿，随后生成文案、确认内容。没有菜单也可以先询问菜单或负责人。</Typography.Paragraph>}


    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
    {!embedded && <Alert type="info" showIcon message="准备草稿可保存缺项；创建任务不会发送消息。已有任务会复用，批量操作逐家显示结果。" style={{ marginBottom: 12 }} />}
    <Space wrap style={{ marginBottom: 12 }}><Select aria-label="触达渠道" value={channel} options={[...CHANNELS, ...Array.from(new Set(context?.contacts.map((c) => c.channel) || [])).filter((c) => !CHANNELS.some((o) => o.value === c)).map((value) => ({ value, label: Array.from(new Set(context?.contacts.filter((c) => c.channel === value).map((c) => channelLabel(c.channel, c.contact_ref)) || [])).join("／") || channelLabel(value) }))]} style={{ width: 180 }} disabled={busy || (!embedded && !!rows.length)} onChange={(v) => { setChannel(v); setMode("manual"); if (embedded) { const existing = context?.drafts?.find((d) => d.channel === v); setRows(existing ? [{ lead_id: existing.lead_id, draft: existing }] : []); } }} />{(!embedded || !rows.length) && <Select aria-label="默认执行方式" value={mode} style={{ width: 220 }} disabled={busy} options={MODES.filter((m) => m.value === "manual" || (m.value === "gmail" && channel === "email") || (m.value === "social" && ["facebook", "instagram"].includes(channel)))} onChange={setMode} />}{(!embedded || !rows.length) && <Select allowClear aria-label="默认负责人" placeholder="负责人（默认门店负责人）" value={assigned} onChange={setAssigned} disabled={busy} style={{ width: 200 }} options={assignees.map((a) => ({ value: a.username, label: a.display_name || a.username }))} /> }<Button loading={busy} onClick={check} disabled={!leadIds.length}>{embedded ? "保存并检查草稿" : "检查并保存草稿"}</Button></Space>
    {identityError && <Alert type="warning" showIcon message={identityError} action={<Link href="/settings?section=profile">检查服务资料</Link>} style={{ marginBottom: 12 }} />}
    {embedded && rows.length ? <Collapse size="small" style={{ marginBottom: 12 }} items={[{ key: "sender", label: "发件身份与退出说明", children: <div className="lead-sender-fields"><Space wrap style={{ marginBottom: 16 }}><label>发件身份<Input.TextArea rows={3} aria-label="发件身份" value={sender} onChange={(e) => setSender(e.target.value)} placeholder="真实发件身份（生成文案时使用）" style={{ width: 300 }} /></label><label>退出说明<Input aria-label="退出说明" value={optOut} onChange={(e) => setOptOut(e.target.value)} placeholder="退出说明" style={{ width: 550 }} /></label></Space></div> }]} /> : <div className="lead-sender-fields"><Space wrap style={{ marginBottom: 16 }}><label>发件身份<Input.TextArea rows={3} aria-label="发件身份" value={sender} onChange={(e) => setSender(e.target.value)} placeholder="真实发件身份（生成文案时使用）" style={{ width: 300 }} /></label><label>退出说明<Input aria-label="退出说明" value={optOut} onChange={(e) => setOptOut(e.target.value)} placeholder="退出说明" style={{ width: 550 }} /></label></Space></div>}

    {note && <Alert type="success" showIcon message={note} style={{ marginBottom: 12 }} />}

    {embedded && rows.map((r) => <div key={r.lead_id}>{r.error && <Alert type="error" message={r.error} />}{r.draft?.status === "draft" ? <DraftEditor key={r.draft.id} draft={r.draft} assignees={assignees} returnTo={returnTo} sender={sender} optOut={optOut} preferredAnalysisId={preferredAnalysisId} onViewMenus={onViewMenus} onChange={(draft) => { rowsEpoch.current++; setRows((old) => old.map((item) => item.lead_id === draft.lead_id ? { ...item, draft, error: undefined } : item)); onChanged?.(); }} /> : <Alert key={r.lead_id} type="info" message="已有触达任务，尚未发送新的消息" action={<Link href={taskLink({ lead: r.lead_id, task: r.existing_task?.id || r.activated_task_id || r.draft?.task_id, returnTo })}>查看任务与会话</Link>} />}</div>)}
    {!ready && rows.some(r => r.draft?.status === "draft") && <Typography.Paragraph type="secondary">还没有满足创建条件的草稿。请处理上方缺项；核验或确认后会自动重新检查，创建任务不会发送消息。</Typography.Paragraph>}
    <Space wrap style={{ marginBottom: 16 }}><Button type="primary" disabled={!ready || busy} loading={busy} onClick={activate}>创建就绪任务（{ready}）</Button>{embedded && <Typography.Text type="secondary">创建后仍需确认发送</Typography.Text>}{targetLink && <Link href={targetLink}>进入本次触达工作台 →</Link>}</Space>
    {!embedded && <Table<Prepared> rowKey="lead_id" size="small" pagination={{ pageSize: 10 }} dataSource={rows} columns={[
      { title: "客户", render: (_, r) => r.name || r.draft?.context.lead.name || r.lead_id },
      { title: "准备结果", render: (_, r) => r.error ? <Typography.Text type="danger">{r.error}</Typography.Text> : r.activated_task_id ? <Tag color="green">任务已就绪，尚未发送</Tag> : r.existing_task ? <Tag color="blue">已有任务 · {r.existing_task.status}</Tag> : <Tag color={r.draft?.blockers.length ? "orange" : "green"}>{r.draft?.blockers.length ? `待补 ${r.draft.blockers.length} 项` : "可创建任务"}</Tag> },
      { title: "缺项／操作", render: (_, r) => r.existing_task || r.activated_task_id ? <Link href={taskLink({ lead: r.lead_id, task: r.existing_task?.id || r.activated_task_id, batch: batchKey, returnTo })}>查看任务与会话</Link> : r.draft?.blockers.join("；") },
    ]} expandable={{ defaultExpandAllRows: leadIds.length === 1, rowExpandable: (r) => !!r.draft && r.draft.status === "draft", expandedRowRender: (r) => r.draft && <DraftEditor draft={r.draft} assignees={assignees} returnTo={returnTo} sender={sender} optOut={optOut} onChange={(draft) => { rowsEpoch.current++; setRows((old) => old.map((item) => item.lead_id === draft.lead_id ? { ...item, draft, error: undefined } : item)); onChanged?.(); }} /> }} />}
  </>;
  return embedded ? <Card title={context?.tasks.length && !rows.length ? "任务与回复" : "准备触达"} id="outreach-content" loading={loadingContext && !context}>{context?.progress.status === "suppressed" ? <Alert type="warning" showIcon message="该客户已停止触达" description="不能继续准备或创建触达任务，可在沟通工作台查看原因和历史记录。" action={<Link href={taskLink({ lead: leadIds[0], returnTo })}>查看沟通记录</Link>} /> : context?.tasks.length && !rows.length && purpose === "initial" ? <><Alert type="info" showIcon message="这家门店已有触达任务" description="在沟通工作台查看发送状态、客户回复并继续跟进。" style={{ marginBottom: 12 }} /><Link href={targetLink || taskLink({ lead: leadIds[0], task: context.progress.task_id, returnTo })}>{targetLink ? "进入本次触达工作台 →" : "查看已有任务与回复 →"}</Link></> : body}</Card> : <Drawer title={`准备触达 · ${leadIds.length} 家${purpose === "followup" ? " · 人工准备跟进" : ""}`} open={open} width={980} onClose={() => { if (!busy) onClose(); }} maskClosable={!busy}>{body}</Drawer>;
}
