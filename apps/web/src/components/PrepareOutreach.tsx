"use client";
import { afterCommit } from "@/lib/after-commit";
import { useOutreachIdentity } from "@/lib/useOutreachIdentity";
import { Alert, Card, Collapse, Drawer, Input, Select, Space, Table, Tag, Typography } from "antd";
import Button from "@/components/AccessButton";
import DraftEditor from "./MessageComposer";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, json } from "@/lib/api";
import { Assignee, CHANNELS, Draft, LeadContext, MODES, Prepared, taskLink } from "@/lib/communication";
import { defaultExecutionMode } from "@/lib/mobile-channels";
import { channelLabel } from "@/lib/format";

export default function PrepareOutreach({ open, leadIds, batchKey, returnTo, onClose, onChanged, initialChannel = "email", savedDrafts, purpose = "initial", onViewMenus, embedded = false, initialContactId, preferredAnalysisId, dataRevision, selectionRequest, onSelectedContact, onSelectionBusyChange }: { onSelectedContact?: (id: string | null) => void; onSelectionBusyChange?: (busy: boolean) => void; onViewMenus?: () => void; embedded?: boolean; dataRevision?: string; selectionRequest?: number; initialContactId?: string; preferredAnalysisId?: string; open: boolean; leadIds: string[]; batchKey?: string; returnTo: string; onClose: () => void; onChanged?: () => void; initialChannel?: string; savedDrafts?: Draft[]; purpose?: "initial" | "followup" }) {
  const [channel, setChannel] = useState(initialChannel);
  const channelRef = useRef(channel);
  useEffect(() => { channelRef.current = channel; }, [channel]);
  const [mode, setMode] = useState(defaultExecutionMode(initialChannel));
  const [assigned, setAssigned] = useState<string>();
  const [rows, setRows] = useState<Prepared[]>([]);
  const [assignees, setAssignees] = useState<Assignee[]>([]);
  const [busy, setBusy] = useState(false);
  const [working, setWorking] = useState<Record<string,boolean>>({});
  const workingChange = (id:string,active:boolean) => setWorking(old => old[id] === active ? old : {...old,[id]:active});
  const locked = busy || Object.values(working).some(Boolean);
  const selectionCallback = useRef(onSelectedContact);
  useEffect(() => { selectionCallback.current = onSelectedContact; }, [onSelectedContact]);
  const busyCallback = useRef(onSelectionBusyChange);
  useEffect(() => { busyCallback.current = onSelectionBusyChange; }, [onSelectionBusyChange]);
  const selectedId = rows[0]?.draft?.eligibility_id || rows[0]?.existing_task?.eligibility_id || initialContactId || null;
  useEffect(() => { selectionCallback.current?.(selectedId); }, [selectedId]);

  const [error, setError] = useState<string>();
  const [note, setNote] = useState<string>();
  const { sender, setSender, optOut, setOptOut, identityError } = useOutreachIdentity();
  const rowsEpoch = useRef(0);
  const changed = useRef(onChanged);
  useEffect(() => { changed.current = onChanged; }, [onChanged]);
  const [context, setContext] = useState<LeadContext>();
  const [loadingContext, setLoadingContext] = useState(false);
  useEffect(() => { busyCallback.current?.(locked || loadingContext); return () => busyCallback.current?.(false); }, [locked, loadingContext]);

  const leadKey = leadIds.join(",");
  const identity = leadIds.length === 1 ? leadIds[0] : undefined;
  const selectedRequest = useRef<string | undefined>(undefined);
  const initialized = useRef<string | undefined>(undefined);
  useEffect(() => afterCommit(() => {
    if (!open) return;
    let active = true;
    const epoch = rowsEpoch.current;
    const resetKey = `${leadKey}:${initialChannel}:${selectionRequest || ""}:${open}`;
    if (!embedded || initialized.current !== resetKey) {
      initialized.current = resetKey;
      setRows((savedDrafts || []).map((draft) => ({ lead_id: draft.lead_id, name: draft.context.lead.name, draft })));
      setError(undefined); setNote(undefined); setChannel(savedDrafts?.[0]?.channel || initialChannel); setMode(defaultExecutionMode(initialChannel));
    }
    api<Assignee[]>("/api/communication/assignees").then((a) => { if (active) setAssignees(a); }).catch((e) => { if (active) setError(e.message); });
    if (embedded && identity) {
      setLoadingContext(true);
      (async () => {
        const next = await api<LeadContext>(`/api/communication/leads/${identity}`);
        if (!active) return;
        setContext(next);
        if (initialContactId && selectedRequest.current !== `${identity}:${selectionRequest || initialContactId}`) {
          const response = await api<{ items: Prepared[] }>("/api/communication/prepare", json({ lead_ids: [identity], channel: initialChannel, execution_mode: defaultExecutionMode(initialChannel), purpose, eligibility_id: initialContactId }));
          if (!active) return;
          selectedRequest.current = `${identity}:${selectionRequest || initialContactId}`;
          if (active) { setRows(response.items); changed.current?.(); }
        } else {
          const existing = next.drafts?.find((d) => d.channel === channelRef.current && (!initialContactId || d.eligibility_id === initialContactId));
          if (existing && epoch === rowsEpoch.current) { setRows([{ lead_id: identity, name: next.lead.name, draft: existing }]); setChannel(existing.channel); setMode(existing.execution_mode); }
        }
      })().catch((e) => { if (active) setError(e.message); }).finally(() => { if (active) setLoadingContext(false); });
    }
    return () => { active = false; };
  }), [open, initialChannel, savedDrafts, embedded, initialContactId, leadKey, purpose, identity, dataRevision, selectionRequest]);

  const check = async () => { rowsEpoch.current++; setBusy(true); setError(undefined); const collected: Prepared[] = []; try { for (let offset = 0; offset < leadIds.length; offset += 25) { const next = await api<{ items: Prepared[] }>("/api/communication/prepare", json({ lead_ids: leadIds.slice(offset, offset + 25), channel, execution_mode: mode, batch_key: batchKey, assigned_to: assigned, purpose })); collected.push(...next.items); setRows([...collected]); setNote(leadIds.length > 1 ? `已准备 ${collected.length}/${leadIds.length} 家` : undefined); } onChanged?.(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  const body = <>
    {embedded && context && !rows.length && <Typography.Paragraph type="secondary">请从左侧选择一个联系方式，开始准备消息。渠道会自动确定，无需重复选择。</Typography.Paragraph>}


    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
    {!embedded && <Alert type="info" showIcon message="逐家准备和确认消息；打开页面或生成草稿不会发送。" style={{ marginBottom: 12 }} />}
    {!embedded && <Space wrap style={{ marginBottom: 12 }}><Select aria-label="触达渠道" value={channel} options={[...CHANNELS, ...Array.from(new Set(context?.contacts.map((c) => c.channel) || [])).filter((c) => c !== "post" && !CHANNELS.some((o) => o.value === c)).map((value) => ({ value, label: Array.from(new Set(context?.contacts.filter((c) => c.channel === value).map((c) => channelLabel(c.channel, c.contact_ref)) || [])).join("／") || channelLabel(value) }))]} style={{ width: 180 }} disabled={locked || (!embedded && !!rows.length)} onChange={(v) => { setChannel(v); setMode(defaultExecutionMode(v)); if (embedded) { const existing = context?.drafts?.find((d) => d.channel === v); setRows(existing ? [{ lead_id: existing.lead_id, draft: existing }] : []); } }} />{!rows.length && <Select aria-label="默认执行方式" value={mode} style={{ width: 220 }} disabled={busy} options={MODES.filter((m) => m.value === "manual" || (m.value === "mobile" && defaultExecutionMode(channel) === "mobile") || (m.value === "gmail" && channel === "email") || (m.value === "social" && ["facebook", "instagram"].includes(channel)))} onChange={setMode} />}{!rows.length && <Select allowClear aria-label="默认负责人" placeholder="负责人（默认门店负责人）" value={assigned} onChange={setAssigned} disabled={busy} style={{ width: 200 }} options={assignees.map((a) => ({ value: a.username, label: a.display_name || a.username }))} /> }{!rows.length && <Button loading={busy} onClick={() => check()} disabled={!leadIds.length}>{embedded ? "准备消息" : "准备选中客户"}</Button>}</Space>}
    {identityError && <Alert type="warning" showIcon message={identityError} action={<Link href="/settings?section=profile">检查服务资料</Link>} style={{ marginBottom: 12 }} />}
    {(!embedded || rows.length > 0) && <Collapse size="small" ghost style={{ marginBottom: 12 }} items={[{ key: "sender", label: "署名设置", children: <div className="lead-sender-fields"><Space wrap><label>发件身份<Input.TextArea rows={3} aria-label="发件身份" value={sender} onChange={(e) => setSender(e.target.value)} placeholder="真实发件身份" /></label><label>退出说明<Input aria-label="退出说明" value={optOut} onChange={(e) => setOptOut(e.target.value)} /></label></Space></div> }]} />}

    {note && <Alert type="success" showIcon message={note} style={{ marginBottom: 12 }} />}

    {embedded && rows.map((r) => <div key={r.lead_id}>{r.error && <Alert type="error" message={r.error} />}{r.draft?.status === "draft" ? <DraftEditor onResultChange={() => { changed.current?.(); if (identity) void api<LeadContext>(`/api/communication/leads/${identity}`).then(setContext).catch(e => setError(e.message)); }} onWorkingChange={workingChange} lockedRecipient={embedded} key={r.draft.id} draft={r.draft} assignees={assignees} returnTo={returnTo} sender={sender} optOut={optOut} preferredAnalysisId={preferredAnalysisId} onViewMenus={onViewMenus} onChange={(draft) => { rowsEpoch.current++; setRows((old) => old.map((item) => item.lead_id === draft.lead_id ? { ...item, draft, error: undefined } : item)); onChanged?.(); }} /> : <Alert key={r.lead_id} type="info" message="当前收件人已有触达任务，可查看发送进度" action={<Link href={taskLink({ lead: r.lead_id, task: r.existing_task?.id || r.activated_task_id || r.draft?.task_id, returnTo })}>查看任务与会话</Link>} />}</div>)}
    {!embedded && <Table<Prepared> rowKey="lead_id" size="small" pagination={{ pageSize: 10 }} dataSource={rows} columns={[
      { title: "客户", render: (_, r) => r.name || r.draft?.context.lead.name || r.lead_id },
      { title: "准备结果", render: (_, r) => r.error ? <Typography.Text type="danger">{r.error}</Typography.Text> : r.activated_task_id ? <Tag color="green">任务已就绪，尚未发送</Tag> : r.existing_task ? <Tag color="blue">已有任务 · {r.existing_task.status}</Tag> : <Tag color={r.draft?.blockers.length ? "orange" : "green"}>{r.draft?.blockers.length ? "待准备" : "可预览"}</Tag> },
      { title: "缺项／操作", render: (_, r) => r.existing_task || r.activated_task_id ? <Link href={taskLink({ lead: r.lead_id, task: r.existing_task?.id || r.activated_task_id, batch: batchKey, returnTo })}>查看任务与会话</Link> : r.draft ? "展开准备消息" : "" },
    ]} expandable={{ defaultExpandAllRows: leadIds.length === 1, rowExpandable: (r) => !!r.draft && r.draft.status === "draft", expandedRowRender: (r) => r.draft && <DraftEditor onResultChange={() => { changed.current?.(); if (identity) void api<LeadContext>(`/api/communication/leads/${identity}`).then(setContext).catch(e => setError(e.message)); }} onWorkingChange={workingChange} lockedRecipient={embedded} draft={r.draft} assignees={assignees} returnTo={returnTo} sender={sender} optOut={optOut} onChange={(draft) => { rowsEpoch.current++; setRows((old) => old.map((item) => item.lead_id === draft.lead_id ? { ...item, draft, error: undefined } : item)); onChanged?.(); }} /> }} />}
  </>;
  return embedded ? <Card title="准备触达" id="outreach-content" loading={loadingContext && !context}>{context?.progress.status === "suppressed" ? <Alert type="warning" showIcon message="该客户已停止触达" description="不能继续准备或创建触达任务，可在沟通工作台查看原因和历史记录。" action={<Link href={taskLink({ lead: leadIds[0], returnTo })}>查看沟通记录</Link>} /> : body}{!!context?.tasks.length && <Collapse ghost size="small" style={{marginTop:16}} items={[{key:"history",label:`沟通记录（${context.tasks.length}）`,children:<Space direction="vertical">{context.tasks.map(t => <Link key={t.id} href={taskLink({lead:identity,task:t.id,returnTo})}>{channelLabel(t.channel)} · 查看任务与回复</Link>)}</Space>}]} />}</Card> : <Drawer title={`准备触达 · ${leadIds.length} 家${purpose === "followup" ? " · 人工准备跟进" : ""}`} open={open} width={980} onClose={() => { if (!locked) onClose(); }} maskClosable={!locked}>{body}</Drawer>;
}
