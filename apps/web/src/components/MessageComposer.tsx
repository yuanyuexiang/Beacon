"use client";
import { Alert, Card, Checkbox, Collapse, DatePicker, Form, Input, Modal, Select, Space, Typography } from "antd";
import Link from "next/link";
import dayjs from "dayjs";
import { useEffect, useRef, useState } from "react";
import Button from "@/components/AccessButton";
import ChannelConditions from "./ChannelConditions";
import { api, json } from "@/lib/api";
import { Assignee, Draft, MODES, taskLink } from "@/lib/communication";
import { contactRank } from "@/lib/contact-ranking";
import { useOperator } from "@/lib/auth";
import { nextSendIssue } from "@/lib/sendflow";

type Preview = { preview_hash: string; issues: string[]; payload: { from: string; to: string; subject: string; body: string; mode: string } };
export default function MessageComposer({ draft, assignees, returnTo, sender, optOut, preferredAnalysisId, onViewMenus, onChange, onWorkingChange }: { draft: Draft; assignees: Assignee[]; returnTo: string; sender: string; optOut: string; preferredAnalysisId?: string; onViewMenus?: () => void; onChange: (d: Draft) => void; onWorkingChange?: (id:string,active:boolean) => void }) {
  const { me } = useOperator();
  const readOnly = !["admin", "director", "member"].includes(me?.role || "");
  const piece = draft.context.contents.find(c => c.id === draft.content_id);
  const contact = draft.context.contacts.find(c => c.id === draft.eligibility_id);
  const [body, setBody] = useState(piece?.body_text || ""), [subject, setSubject] = useState(piece?.subject || "");
  const [busy, setBusy] = useState(false), [saving, setSaving] = useState(false), [error, setError] = useState<string>();
  const [preview, setPreview] = useState<Preview>(), [confirmed, setConfirmed] = useState(false);
  const [issues, setIssues] = useState<string[]>([]), [section, setSection] = useState<string[]>([]);
  const [manual, setManual] = useState<{url?:string;address?:string;text:string}>();
  const workingCallback = useRef(onWorkingChange); workingCallback.current = onWorkingChange;
  const [result, setResult] = useState<{task_id:string; status:string; message:string}>();
  const [analysis, setAnalysis] = useState(preferredAnalysisId || piece?.analysis_id || draft.context.analyses[0]?.id);
  const [form] = Form.useForm();
  const latest = useRef(draft), edits = useRef({body,subject}), dirty = useRef(false), pending = useRef<Promise<Draft> | null>(null);
  const checked = useRef(new Set<string>());
  latest.current = draft;
  useEffect(() => { workingCallback.current?.(draft.id,busy || saving || dirty.current); }, [draft.id,busy,saving,body,subject]);
  useEffect(() => () => workingCallback.current?.(draft.id,false), [draft.id]);
  const update = (d: Draft) => { latest.current = d; onChange(d); };
  const refresh = async () => { const d = await api<Draft>(`/api/communication/drafts/${draft.id}`); update(d); return d; };
  useEffect(() => { if (!dirty.current) { const value = {body:piece?.body_text || "",subject:piece?.subject || ""}; edits.current = value; setBody(value.body); setSubject(value.subject); } }, [piece?.id,piece?.body_text,piece?.subject]);
  const save = async (): Promise<Draft> => {
    if (pending.current) { await pending.current; return save(); }
    if (!dirty.current || !latest.current.content_id) return latest.current;
    const value = {...edits.current}, current = latest.current;
    setSaving(true);
    const request = api<Draft>(`/api/communication/drafts/${current.id}/message`, json({content_id:current.content_id,body_text:value.body,subject:value.subject},"PUT"));
    pending.current = request;
    try { const d = await request; dirty.current = edits.current.body !== value.body || edits.current.subject !== value.subject; update(d); return d; }
    finally { pending.current = null; setSaving(false); }
  };
  useEffect(() => {
    if (!dirty.current) return;
    const timer = setTimeout(() => { save().catch(e => setError(e.message)); }, 1000);
    return () => clearTimeout(timer);
    // The editor refs serialize saves and protect newer keystrokes from older responses.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [body,subject]);
  useEffect(() => { const guard = (e: BeforeUnloadEvent) => { if (dirty.current || pending.current) { e.preventDefault(); e.returnValue = ""; } }; window.addEventListener("beforeunload",guard); return () => window.removeEventListener("beforeunload",guard); }, []);
  const act = async (fn: () => Promise<void>) => { if (busy) return; setBusy(true); setError(undefined); try { await fn(); } catch(e) { setError((e as Error).message); } finally { setBusy(false); } };
  const patch = async (changes: Record<string,unknown>) => { await save(); const d = await api<Draft>(`/api/communication/drafts/${draft.id}`,json(changes,"PATCH")); update(d); setIssues([]); };
  const inspect = async () => {
    await save();
    const d = latest.current;
    const c = d.context.contacts.find(c => c.id === d.eligibility_id);
    if (d.channel !== "email" && c && c.eligibility !== "allowed" && c.eligibility !== "blocked" && !c.suppressed && !checked.current.has(c.id)) {
      checked.current.add(c.id);
      // Reuse existing facts first; only fetch when no saved recommendation exists. Never loop on missing evidence.
      await api(`/api/leads/${d.lead_id}/auto-admission?refresh=${!c.recommendation || c.auto_admission?.needs_refresh || c.auto_admission?.status === "unknown"}`,{method:"POST"});
      await refresh();
    }
    const p = await api<Preview>(`/api/communication/drafts/${draft.id}/preview`,{method:"POST"});
    setIssues(p.issues); setConfirmed(false);
    if (!p.issues.length) setPreview(p);
  };
  const issue = nextSendIssue(issues);
  const modes = MODES.filter(m => m.value === "manual" || draft.channel === "email" && m.value === "gmail" || ["facebook","instagram"].includes(draft.channel) && m.value === "social");
  const actionLabel = draft.execution_mode === "manual" ? draft.channel === "phone" ? "查看拨打准备" : "预览并打开联系入口" : "预览并发送";
  return <Card size="small" title="收件人与消息">
    {error && !preview && <Alert type="error" showIcon message={error} style={{marginBottom:12}} />}
    {result ? <><Alert type="info" message={result.message} action={<Link href={taskLink({lead:draft.lead_id,task:result.task_id,returnTo})}>查看沟通记录</Link>} />{manual && <Space wrap style={{marginTop:12}}><Button onClick={() => navigator.clipboard.writeText(manual.text).catch(() => setError("复制失败，请选择正文手动复制"))}>复制消息</Button>{manual.url && <a href={manual.url} target="_blank" rel="noreferrer">打开联系入口 ↗</a>}{manual.address && <Typography.Text>{manual.address}</Typography.Text>}<Typography.Text type="secondary">完成后在沟通记录中回填结果。</Typography.Text></Space>}</> : <>
      <Form layout="vertical">
        {draft.channel === "email" && <Form.Item label="发送方式"><Select aria-label="邮件发送方式" value={draft.execution_mode} options={modes} disabled={busy || readOnly} onChange={execution_mode => act(() => patch({execution_mode}))} />{draft.execution_mode === "manual" && <Typography.Text type="secondary">当前只打开邮箱客户端；要由系统发送，请选择 Gmail 接口。</Typography.Text>}</Form.Item>}
        <Form.Item label="发给谁"><Space.Compact style={{width:"100%"}}><Select aria-label="收件人" placeholder="选择联系方式" style={{flex:1,minWidth:0,width:0}} value={draft.eligibility_id || undefined} disabled={busy || readOnly} options={draft.context.contacts.filter(c => c.channel === draft.channel).sort((a,b) => contactRank(a.recommendation)-contactRank(b.recommendation)).map(c => ({value:c.id,label:`${c.contact_ref || "未填写"}${c.recommendation?.owner ? ` · ${c.recommendation.owner}` : ""}${c.suppressed ? " · 已拒收" : ""}`}))} onChange={id => act(() => patch({eligibility_id:id}))} /><Button disabled={busy || readOnly} onClick={() => setSection(["contact"])}>添加</Button></Space.Compact></Form.Item>
        {draft.channel === "email" && <Form.Item label="主题"><Input aria-label="邮件主题" value={subject} disabled={!piece || busy || readOnly} maxLength={200} onChange={e => { dirty.current=true; edits.current.subject=e.target.value; setSubject(e.target.value); setIssues([]); }} /></Form.Item>}
        <Form.Item label="消息正文"><Input.TextArea aria-label="文案内容" value={body} rows={9} disabled={!piece || busy || readOnly} placeholder="点击 AI 起草，根据门店和菜单资料生成消息后可直接修改" onChange={e => { dirty.current=true; edits.current.body=e.target.value; setBody(e.target.value); setIssues([]); }} /></Form.Item>
      </Form>
      <Space wrap style={{display:"flex",marginBottom:16}}><Button disabled={busy || readOnly || !sender.trim() || !optOut.trim()} onClick={() => act(async () => { await save(); const c = await api<{id:string}>(`/api/leads/${draft.lead_id}/outreach-message`,json({analysis_id:analysis || null,eligibility_id:draft.eligibility_id,channel:draft.channel,sender_identity:sender,opt_out_text:optOut})); await patch({content_id:c.id}); })}>{piece ? "AI 重新起草" : "AI 起草消息"}</Button><Typography.Text type="secondary">{saving ? "正在保存…" : dirty.current ? "修改尚未保存" : piece ? "草稿已保存" : "生成后可直接编辑"}</Typography.Text>{(!sender.trim() || !optOut.trim()) && <Link href="/account">完善发件署名</Link>}</Space>
      {issue && <Alert type="warning" showIcon message={issue.title} description={<>
        {issue.action === "settings" ? <Link href="/settings?section=gmail">检查发件邮箱</Link> : issue.action === "contact" ? <Button onClick={() => setSection(["contact"])}>查找或添加联系方式</Button> : issue.action === "ownership" ? <Space wrap><Button loading={busy} disabled={busy || readOnly} onClick={() => act(async () => { await save(); if (contact) checked.current.add(contact.id); await api(`/api/leads/${draft.lead_id}/auto-admission?refresh=true`,{method:"POST"}); await refresh(); await inspect(); })}>AI 补查联系方式</Button>{contact && <ChannelConditions leadId={draft.lead_id} contactId={contact.id} contact={contact.contact_ref} busy={busy} buttonLabel="人工核对" onChanged={async () => { await refresh(); setIssues([]); }} />}</Space> : issue.action === "basis" && contact ? <ChannelConditions leadId={draft.lead_id} contactId={contact.id} contact={contact.contact_ref} busy={busy} buttonLabel="补充确认" onChanged={async () => { await refresh(); setIssues([]); }} /> : null}
        <Collapse ghost size="small" items={[{key:"details",label:"查看检查详情",children:<ul>{issues.map(x => <li key={x}>{x}</li>)}</ul>}]} />
      </>} style={{marginBottom:12}} />}
      <Space wrap style={{display:"flex",marginBottom:16}}><Button type="primary" loading={busy} disabled={readOnly || busy} onClick={() => act(inspect)}>{busy ? "正在准备…" : actionLabel}</Button><Button disabled={busy || readOnly} onClick={() => act(() => patch({queued:!draft.queued}))}>{draft.queued ? "移出准备待办" : "稍后处理"}</Button>{draft.queued && <Link href={taskLink({lead:draft.lead_id,returnTo})}>查看待办</Link>}</Space>
      <Collapse size="small" activeKey={section} onChange={keys => setSection(typeof keys === "string" ? [keys] : keys)} items={[
        {key:"options",label:`更多选项 · ${draft.execution_mode === "gmail" ? "Gmail 发送" : draft.execution_mode === "social" ? "已连接社媒发送" : "人工联系"}`,children:<Space wrap>
          {draft.channel !== "email" && <Select aria-label="执行方式" value={draft.execution_mode} options={modes} disabled={busy || readOnly} style={{width:200}} onChange={execution_mode => act(() => patch({execution_mode}))} />}
          <Select aria-label="负责人" value={draft.assigned_to || undefined} options={assignees.map(a => ({value:a.username,label:a.display_name || a.username}))} disabled={busy || readOnly} style={{width:150}} onChange={assigned_to => act(() => patch({assigned_to}))} />
          <DatePicker showTime placeholder="跟进提醒" value={draft.follow_up_at ? dayjs(draft.follow_up_at) : null} onChange={v => act(() => patch({follow_up_at:v?.toISOString() || null}))} />
          <Select aria-label="引用菜单" allowClear placeholder="无菜单，询问菜单或负责人" value={analysis} style={{width:260}} options={draft.context.analyses.map(a => ({value:a.id,label:`${a.label || "菜单"} v${a.version}`}))} onChange={setAnalysis} />
          {onViewMenus && <Button onClick={() => act(async () => { await save(); onViewMenus(); })}>查看菜单</Button>}
          <Select aria-label="历史消息" placeholder="选择历史消息" value={draft.content_id || undefined} style={{width:220}} options={draft.context.contents.map(c => ({value:c.id,label:`v${c.version} · ${c.subject || "消息"}`}))} onChange={content_id => act(() => patch({content_id}))} />
        </Space>},
        {key:"contact",label:"联系方式与检查详情",children:<>
          {contact && <ChannelConditions leadId={draft.lead_id} contactId={contact.id} contact={contact.contact_ref} busy={busy} onChanged={async () => { await refresh(); setIssues([]); }} />}
          <Button disabled={busy || readOnly} onClick={() => act(async () => { await api(`/api/leads/${draft.lead_id}/contact-review`,{method:"POST"}); await refresh(); })}>查找联系方式</Button>
          <Form form={form} layout="vertical" onFinish={v => act(async () => { await api(`/api/leads/${draft.lead_id}/contacts`,json({items:[{channel:draft.channel,...v}]})); const d=await refresh(); const c=d.context.contacts.find(c => c.channel===d.channel && c.contact_ref?.toLowerCase()===v.contact_ref.trim().toLowerCase()); if(c) await patch({eligibility_id:c.id}); setSection([]); })}>
            <Form.Item name="contact_ref" label="联系值" rules={[{required:true}]}><Input /></Form.Item><Form.Item name="contact_source" label="来源"><Input /></Form.Item><Button htmlType="submit" disabled={busy || readOnly}>添加并选择</Button>
          </Form>
        </>},
        ...(piece?.rationale ? [{key:"evidence",label:"AI 起草依据",children:<><p>{piece.rationale}</p>{piece.missing?.map(x => <p key={x}>{x}</p>)}</>}] : []),
      ]} />
    </>}
    <Modal title={preview?.payload.mode === "manual" ? "确认联系内容" : "确认发送"} open={!!preview} width={720} onCancel={() => { if(!busy) setPreview(undefined); }} styles={{body:{maxHeight:"65vh",overflowY:"auto"}}} footer={<Button type="primary" disabled={!confirmed || busy} loading={busy} onClick={() => act(async () => { const r=await api<{task_id:string;status:string;message:string}>(`/api/communication/drafts/${draft.id}/confirm`,json({preview_hash:preview!.preview_hash,confirmed:true})); setResult(r); setPreview(undefined); if(r.status === "manual") setManual(await api(`/api/communication/tasks/${r.task_id}/manual-open`,{method:"POST"})); })}>{preview?.payload.mode === "manual" ? "确认并准备联系" : "确认发送"}</Button>}>
      {error && <Alert type="error" showIcon message={error} style={{marginBottom:12}} />}
      {preview && <><Typography.Paragraph>发件账号：{preview.payload.from || "人工联系"}</Typography.Paragraph><Typography.Paragraph strong>收件人：{preview.payload.to}</Typography.Paragraph>{preview.payload.subject && <Typography.Paragraph strong>主题：{preview.payload.subject}</Typography.Paragraph>}<Typography.Paragraph style={{whiteSpace:"pre-wrap"}}>{preview.payload.body}</Typography.Paragraph><Checkbox checked={confirmed} onChange={e => setConfirmed(e.target.checked)}>我已核对收件人和完整内容，确认{preview.payload.mode === "manual" ? "用于本次联系" : "发送"}</Checkbox></>}
    </Modal>
  </Card>;
}
