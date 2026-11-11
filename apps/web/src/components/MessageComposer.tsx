"use client";
import { Alert, Card, Checkbox, Collapse, DatePicker, Form, Input, Modal, Radio, Select, Space, Typography } from "antd";
import Link from "next/link";
import dayjs from "dayjs";
import { useEffect, useRef, useState } from "react";
import Button from "@/components/AccessButton";
import { phoneStatusLabel, MOBILE_ACTIONS, MOBILE_LABELS, mobilePlatform, phoneUnavailableReason, ExecutionPhone } from "@/lib/mobile-channels";
import { MobileTask } from "./MobileChannel";
import ChannelConditions from "./ChannelConditions";
import { api, json } from "@/lib/api";
import { Assignee, Draft, MODES, taskLink } from "@/lib/communication";
import { channelLabel } from "@/lib/format";
import { contactRank } from "@/lib/contact-ranking";
import { useOperator } from "@/lib/auth";
import { nextSendIssue } from "@/lib/sendflow";

type Phone = ExecutionPhone;
type Preview = { preview_hash: string; issues: string[]; payload: { from: string; to: string; subject: string; body: string; mode: string; mobile_context?: { device_id: string; device_label: string; payload: { sender: string; action: string } } } };
export default function MessageComposer({ draft, assignees, returnTo, sender, optOut, preferredAnalysisId, onViewMenus, onChange, onWorkingChange, onResultChange, lockedRecipient = false, conversation = false }: { onResultChange?: (result?: {status:string;task_id:string;message:string}) => void | Promise<void>; conversation?: boolean; lockedRecipient?: boolean; draft: Draft; assignees: Assignee[]; returnTo: string; sender: string; optOut: string; preferredAnalysisId?: string; onViewMenus?: () => void; onChange: (d: Draft) => void; onWorkingChange?: (id:string,active:boolean) => void }) {
  const { me } = useOperator();
  const readOnly = !["admin", "director", "member"].includes(me?.role || "");
  const piece = draft.context.contents.find(c => c.id === draft.content_id);
  const contact = draft.context.contacts.find(c => c.id === draft.eligibility_id);
  const [body, setBody] = useState(piece?.body_text || ""), [subject, setSubject] = useState(piece?.subject || "");
  const [operation, setOperation] = useState<string>();
  const [busy, setBusy] = useState(false), [saving, setSaving] = useState(false), [error, setError] = useState<string>();
  const [preview, setPreview] = useState<Preview>(), [confirmed, setConfirmed] = useState(false);
  const [issues, setIssues] = useState<string[]>([]), [section, setSection] = useState<string[]>([]);
  const [manual, setManual] = useState<{url?:string;address?:string;text:string}>();
  const workingCallback = useRef(onWorkingChange);
  useEffect(() => {workingCallback.current = onWorkingChange;},[onWorkingChange]);
  const [result, setResult] = useState<{task_id:string; status:string; message:string}>();
  const [recordSent, setRecordSent] = useState(false), [sentAt, setSentAt] = useState(dayjs());
  const [analysis, setAnalysis] = useState(preferredAnalysisId || piece?.analysis_id || draft.context.analyses[0]?.id);
  const platform = mobilePlatform(draft.channel, contact?.contact_ref);
  const [phones, setPhones] = useState<Phone[]>([]), [deviceId, setDeviceId] = useState<string>();
  const [phoneLoading, setPhoneLoading] = useState(false), [phoneError, setPhoneError] = useState<string>();
  const [action, setAction] = useState("direct_message");
  const [phoneRevision, setPhoneRevision] = useState(0);
  useEffect(() => { queueMicrotask(() => {setAction(MOBILE_ACTIONS[platform || ""]?.[0]?.value || "direct_message"); setResult(undefined); setPreview(undefined); setIssues([]);}); }, [draft.id, draft.eligibility_id, draft.execution_mode, platform]);
  useEffect(() => {
    if (draft.execution_mode !== "mobile") return;
    let active = true;
    const load = () => { setPhoneError(undefined);
    api<Phone[]>("/api/mobile/devices").then(list => {
      if (!active) return;
      const visible = list.filter(d => d.status !== "revoked");
      const ready = visible.filter(d => !phoneUnavailableReason(d, platform));
      setPhones(visible); setDeviceId(old => visible.some(d => d.id === old) ? old : ready.length === 1 ? ready[0].id : visible.length === 1 ? visible[0].id : undefined);
    }).catch(e => { if(active) { setPhones([]); setDeviceId(undefined); setPhoneError(e.message); } }).finally(() => { if(active) setPhoneLoading(false); });
    };
    queueMicrotask(() => {if(active) {setPhoneLoading(true);load();}});
    const timer = setInterval(load, 10000);
    return () => { active = false; clearInterval(timer); };
  }, [draft.execution_mode, platform, phoneRevision]);
  const [form] = Form.useForm();
  const latest = useRef(draft), edits = useRef({body,subject}), dirty = useRef(false), pending = useRef<Promise<Draft> | null>(null);
  const checked = useRef(new Set<string>());
  useEffect(() => {latest.current = draft;},[draft]);
  useEffect(() => { workingCallback.current?.(draft.id,busy || saving || dirty.current || !!preview || recordSent); }, [draft.id,busy,saving,body,subject,preview,recordSent]);
  useEffect(() => () => workingCallback.current?.(draft.id,false), [draft.id]);
  const update = (d: Draft) => { latest.current = d; onChange(d); };
  const refresh = async () => { const d = await api<Draft>(`/api/communication/drafts/${draft.id}`); update(d); return d; };
  useEffect(() => { if (!dirty.current) { const value = {body:piece?.body_text || "",subject:piece?.subject || ""}; edits.current = value; setBody(value.body); setSubject(value.subject); } }, [piece?.id,piece?.body_text,piece?.subject]);
  const save = async (): Promise<Draft> => {
    if (pending.current) { await pending.current; return save(); }
    if (!dirty.current) return latest.current;
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
  const act = async (fn: () => Promise<void>, action = "update") => { if (busy) return; setBusy(true); setOperation(action); setError(undefined); try { await fn(); } catch(e) { setError((e as Error).message); } finally { setBusy(false); setOperation(undefined); } };
  const patch = async (changes: Record<string,unknown>) => { await save(); const d = await api<Draft>(`/api/communication/drafts/${draft.id}`,json(changes,"PATCH")); update(d); setIssues([]); };
  const inspect = async () => {
    if (draft.execution_mode === "mobile" && !deviceId) { setPhoneError("请连接手机并选择执行设备"); return; }
    await save();
    const d = latest.current;
    const p = await api<Preview>(`/api/communication/drafts/${draft.id}/preview`,json(d.execution_mode === "mobile" ? {device_id:deviceId,action} : {}));
    setIssues(p.issues); setConfirmed(false);
    if (!p.issues.length) setPreview(p);
  };
  const issue = nextSendIssue(issues);
  const modes = MODES.filter(m => m.value === "manual" || m.value === "mobile" && !!mobilePlatform(draft.channel, contact?.contact_ref) || draft.channel === "email" && m.value === "gmail" || ["facebook","instagram"].includes(draft.channel) && m.value === "social");
  const actionLabel = draft.execution_mode === "mobile" ? "预览手机触达" : draft.execution_mode === "manual" ? draft.channel === "phone" ? "查看拨打准备" : "预览人工触达" : draft.channel === "email" ? "预览邮件" : "预览并发送";
  const generate = async (writing_action = "initial") => {
    await save();
    const c = await api<{id:string}>(`/api/leads/${draft.lead_id}/outreach-message`,json({analysis_id:analysis || null,eligibility_id:draft.eligibility_id,channel:draft.channel,sender_identity:sender,opt_out_text:optOut,
      ...(conversation ? {conversation_draft_id:draft.id,writing_action} : {})}));
    await patch({content_id:c.id});
  };
  return <Card size="small" title={lockedRecipient ? undefined : "收件人与消息"} className={lockedRecipient ? "outreach-editor" : undefined} variant={lockedRecipient ? "borderless" : "outlined"}>
    {error && !preview && <Alert type="error" showIcon message={error} style={{marginBottom:12}} />}
    {result ? <>{result.status === "mobile" && <MobileTask taskId={result.task_id} platform={mobilePlatform(draft.channel, contact?.contact_ref)} onChanged={() => { void refresh(); }} />}<Alert type={result.status === "mobile_queued" ? "success" : "info"} message={result.message} action={<Link href={taskLink({lead:draft.lead_id,task:result.task_id,returnTo})}>查看沟通记录</Link>} />{manual && <div style={{marginTop:16}}><Input.TextArea aria-label="人工触达消息" value={manual.text} readOnly autoSize={{minRows:5,maxRows:14}} /><Space wrap style={{marginTop:12}}><Button onClick={() => navigator.clipboard.writeText(manual.text).catch(() => setError("复制失败，请选择正文手动复制"))}>复制消息</Button>{manual.url && <a href={manual.url} target="_blank" rel="noreferrer">{draft.channel === "email" ? "打开邮箱客户端" : draft.channel === "whatsapp" ? "打开 WhatsApp 会话" : draft.channel === "contact_form" ? "打开联系表单" : `打开 ${channelLabel(draft.channel,contact?.contact_ref)} 主页`}</a>}<Button type="primary" disabled={busy || readOnly} onClick={() => {setSentAt(dayjs()); setRecordSent(true);}}>已发送，记录结果</Button></Space><Typography.Paragraph type="secondary" style={{marginTop:8}}>复制或打开主页不会标记已发送；请实际发送后再记录。</Typography.Paragraph></div>}</> : <>
      <Form layout="vertical">
        {lockedRecipient && conversation ? null : lockedRecipient ? <div className="outreach-recipient" aria-label="当前收件人"><Typography.Text type="secondary">{channelLabel(draft.channel, contact?.contact_ref)}收件人</Typography.Text><Typography.Paragraph strong style={{margin:"6px 0 0",overflowWrap:"anywhere"}}>{contact?.contact_ref || "请从左侧选择联系方式"}</Typography.Paragraph></div> : <Form.Item label="发给谁"><Space.Compact style={{width:"100%"}}><Select aria-label="收件人" placeholder="选择联系方式" style={{flex:1,minWidth:0,width:0}} value={draft.eligibility_id || undefined} disabled={busy || readOnly} options={draft.context.contacts.filter(c => c.channel === draft.channel).sort((a,b) => contactRank(a.recommendation)-contactRank(b.recommendation)).map(c => ({value:c.id,label:`${c.contact_ref || "未填写"}${c.recommendation?.owner ? ` · ${c.recommendation.owner}` : ""}${c.suppressed ? " · 已拒收" : ""}`}))} onChange={id => act(() => patch({eligibility_id:id}))} /><Button disabled={busy || readOnly} onClick={() => setSection(["contact"])}>添加</Button></Space.Compact></Form.Item>}
        {!!platform ? <Form.Item label="触达方式"><Radio.Group aria-label="触达方式" value={draft.execution_mode} disabled={busy || readOnly} onChange={e => act(() => patch({execution_mode:e.target.value}))} options={[{value:"mobile",label:"手机触达"},{value:"manual",label:"人工触达"}, ...(draft.execution_mode === "social" ? [{value:"social",label:"已连接 API 会话"}] : [])]} />{draft.execution_mode === "manual" && <Typography.Paragraph type="secondary" style={{margin:"8px 0 0"}}>复制消息，打开对方主页后自行粘贴发送。不需要连接手机或配置社媒 API。</Typography.Paragraph>}</Form.Item> : draft.channel === "email" ? <Typography.Paragraph type="secondary">{draft.execution_mode === "gmail" ? "通过 Gmail 发送" : "通过邮箱客户端人工发送"}</Typography.Paragraph> : null}
        {draft.execution_mode === "mobile" && <Form.Item label={`通过手机 ${MOBILE_LABELS[platform || ""] || "社媒"} 联系`}>
          <Space wrap><Select aria-label="执行手机" placeholder="选择已绑定手机" value={deviceId} loading={phoneLoading} disabled={busy || readOnly} style={{width:260}} options={phones.map(d => ({value:d.id,label:`${d.label} · ${phoneUnavailableReason(d,platform) ? !d.online ? "离线" : "待就绪" : phoneStatusLabel(d)}`}))} onChange={setDeviceId} /><Button disabled={phoneLoading || busy} onClick={() => setPhoneRevision(v => v+1)}>刷新手机</Button>{(MOBILE_ACTIONS[platform || ""]?.length || 0) > 1 && <Select aria-label="手机联系动作" value={action} options={MOBILE_ACTIONS[platform || ""]} style={{width:240}} disabled={busy || readOnly} onChange={setAction} />}</Space>
          {phoneError && <Typography.Paragraph type="danger">{phoneError}</Typography.Paragraph>}
          {deviceId && phones.find(d => d.id === deviceId) && phoneUnavailableReason(phones.find(d => d.id === deviceId)!, platform) && <Typography.Paragraph type="warning" style={{margin:"8px 0"}}>{phoneUnavailableReason(phones.find(d => d.id === deviceId)!, platform)}。手机状态每 10 秒自动更新。</Typography.Paragraph>}
          {!phoneLoading && !phones.length && <Typography.Paragraph type="secondary">尚未找到当前账号绑定的手机。<Link href="/settings?section=mobile">配对或管理手机</Link></Typography.Paragraph>}
        </Form.Item>}
        {draft.channel === "email" && <Form.Item label="主题"><Input aria-label="邮件主题" value={subject} disabled={(!piece && !conversation) || busy || readOnly} maxLength={200} onChange={e => { dirty.current=true; edits.current.subject=e.target.value; setSubject(e.target.value); setIssues([]); }} /></Form.Item>}
        <Form.Item label="消息正文"><Input.TextArea aria-label="文案内容" value={body} rows={conversation ? 4 : 9} disabled={(!piece && !conversation) || busy || readOnly} placeholder={conversation ? "直接填写消息，或让 AI 根据当前会话起草" : "点击 AI 起草，根据门店和菜单资料生成消息后可直接修改"} onChange={e => { dirty.current=true; edits.current.body=e.target.value; setBody(e.target.value); setIssues([]); }} /></Form.Item>
      </Form>
      <Space wrap style={{display:"flex",marginBottom:16}}><Button loading={busy && operation === "ai"} disabled={busy || readOnly || !sender.trim() || !optOut.trim()} onClick={() => act(() => generate(conversation ? "followup" : "initial"), "ai")}>{conversation ? "AI 起草跟进" : piece ? "AI 重新起草" : "AI 起草消息"}</Button>{conversation && <Select aria-label="AI 写作操作" placeholder="更多 AI 写作" value={undefined} disabled={busy || readOnly || !sender.trim() || !optOut.trim()} style={{width:160}} options={[{value:"initial",label:"AI 首次介绍"},{value:"reply",label:"AI 回复客户"},{value:"shorten",label:"AI 缩短草稿"}]} onChange={value => act(() => generate(value), "ai")} />}<Typography.Text type="secondary">{saving ? "正在保存…" : body !== (piece?.body_text || "") || subject !== (piece?.subject || "") ? "修改尚未保存" : piece ? "草稿已保存" : "生成后可直接编辑"}</Typography.Text>{(!sender.trim() || !optOut.trim()) && <Link href="/account">完善发件署名</Link>}</Space>
      {issue && <Alert type="warning" showIcon message={issue.title} description={<>
        {issue.action === "settings" ? <Link href="/settings?section=gmail">检查发件邮箱</Link> : issue.action === "contact" ? <Button onClick={() => setSection(["contact"])}>查找或添加联系方式</Button> : issue.action === "ownership" ? <Space wrap><Button loading={busy} disabled={busy || readOnly} onClick={() => act(async () => { await save(); if (contact) checked.current.add(contact.id); await api(`/api/leads/${draft.lead_id}/auto-admission?refresh=true`,{method:"POST"}); await refresh(); await inspect(); })}>AI 补查联系方式</Button>{contact && <ChannelConditions leadId={draft.lead_id} contactId={contact.id} contact={contact.contact_ref} busy={busy} buttonLabel="人工核对" onChanged={async () => { await refresh(); setIssues([]); }} />}</Space> : issue.action === "basis" && contact ? <ChannelConditions leadId={draft.lead_id} contactId={contact.id} contact={contact.contact_ref} busy={busy} buttonLabel="补充确认" onChanged={async () => { await refresh(); setIssues([]); }} /> : null}
        <Collapse ghost size="small" items={[{key:"details",label:"查看检查详情",children:<ul>{issues.map(x => <li key={x}>{x}</li>)}</ul>}]} />
      </>} style={{marginBottom:12}} />}
      <Space wrap style={{display:"flex",marginBottom:16}}><Button type="primary" aria-label={actionLabel} loading={busy && operation === "preview"} disabled={readOnly || busy} onClick={() => act(inspect, "preview")}>{busy && operation === "preview" ? "正在准备…" : actionLabel}</Button><Button disabled={busy || readOnly} onClick={() => act(() => patch({queued:!draft.queued}))}>{draft.queued ? "移出准备待办" : "稍后处理"}</Button>{draft.queued && <Link href={taskLink({lead:draft.lead_id,returnTo})}>查看待办</Link>}</Space>
      <Collapse size="small" activeKey={section} onChange={keys => setSection(typeof keys === "string" ? [keys] : keys)} items={[
        {key:"options",label:`更多选项 · ${draft.execution_mode === "gmail" ? "Gmail 发送" : draft.execution_mode === "social" ? "已连接社媒发送" : draft.execution_mode === "mobile" ? "手机执行" : "人工联系"}`,children:<Space wrap>
          {!platform && <Select aria-label="执行方式" value={draft.execution_mode} options={modes} disabled={busy || readOnly} style={{width:200}} onChange={execution_mode => act(() => patch({execution_mode}))} />}
          <Select aria-label="负责人" value={draft.assigned_to || undefined} options={assignees.map(a => ({value:a.username,label:a.display_name || a.username}))} disabled={busy || readOnly} style={{width:150}} onChange={assigned_to => act(() => patch({assigned_to}))} />
          <DatePicker showTime placeholder="跟进提醒" value={draft.follow_up_at ? dayjs(draft.follow_up_at) : null} onChange={v => act(() => patch({follow_up_at:v?.toISOString() || null}))} />
          <Select aria-label="引用菜单" allowClear placeholder="无菜单，询问菜单或负责人" value={analysis} style={{width:260}} options={draft.context.analyses.map(a => ({value:a.id,label:`${a.label || "菜单"} v${a.version}`}))} onChange={setAnalysis} />
          {onViewMenus && <Button onClick={() => act(async () => { await save(); onViewMenus(); })}>查看菜单</Button>}
          <Select aria-label="历史消息" placeholder="选择历史消息" value={draft.content_id || undefined} style={{width:220}} options={draft.context.contents.map(c => ({value:c.id,label:`v${c.version} · ${c.subject || "消息"}`}))} onChange={content_id => act(() => patch({content_id}))} />
        </Space>},
        {key:"contact",label:"联系方式与检查详情",children:<>
          {contact && <ChannelConditions leadId={draft.lead_id} contactId={contact.id} contact={contact.contact_ref} busy={busy} onChanged={async () => { await refresh(); setIssues([]); }} />}
          {!lockedRecipient && <><Button disabled={busy || readOnly} onClick={() => act(async () => { await api(`/api/leads/${draft.lead_id}/contact-review`,{method:"POST"}); await refresh(); })}>查找联系方式</Button>
          <Form form={form} layout="vertical" onFinish={v => act(async () => { await api(`/api/leads/${draft.lead_id}/contacts`,json({items:[{channel:draft.channel,...v}]})); const d=await refresh(); const c=d.context.contacts.find(c => c.channel===d.channel && c.contact_ref?.toLowerCase()===v.contact_ref.trim().toLowerCase()); if(c) await patch({eligibility_id:c.id}); setSection([]); })}>
            <Form.Item name="contact_ref" label="联系值" rules={[{required:true}]}><Input /></Form.Item><Form.Item name="contact_source" label="来源"><Input /></Form.Item><Button htmlType="submit" disabled={busy || readOnly}>添加并选择</Button>
          </Form></>}
        </>},
        ...(piece?.rationale ? [{key:"evidence",label:"AI 起草依据",children:<><p>{piece.rationale}</p>{piece.missing?.map(x => <p key={x}>{x}</p>)}</>}] : []),
      ]} />
    </>}
    <Modal title="记录人工发送" open={recordSent} onCancel={() => {if(!busy) setRecordSent(false);}} okText="确认已实际发送" cancelText="还未发送" confirmLoading={busy} onOk={() => act(async () => { await api(`/api/tasks/${result!.task_id}/sent`,json({sent_at:sentAt.toISOString(),notes:"用户在触达编辑区确认已人工发送"})); setRecordSent(false); setManual(undefined); setResult({...result!,status:"sent_manual",message:"已记录人工发送，可在沟通记录查看回复与跟进"}); await onResultChange?.({...result!,status:"sent_manual",message:"已记录人工发送"}); })}>
      {error && <Alert type="error" showIcon message={error} />}<p>确认你已向 {contact?.contact_ref} 实际发送了这条消息。</p><DatePicker aria-label="人工发送时间" showTime value={sentAt} allowClear={false} onChange={value => {if(value) setSentAt(value);}} />
    </Modal>
    {draft.execution_mode === "mobile" && action === "public_comment" && <Alert showIcon type="warning" message="本次将发布公开作品留言" description="内容会对外显示；请核对正文。不会将私信失败自动改为留言。" />}
    <Modal title={preview?.payload.mode === "mobile" ? "确认手机触达" : preview?.payload.mode === "manual" ? "确认联系内容" : "确认发送"} open={!!preview} width={720} onCancel={() => { if(!busy) setPreview(undefined); }} styles={{body:{maxHeight:"65vh",overflowY:"auto"}}} footer={<Button type="primary" disabled={!confirmed || busy} loading={busy} onClick={() => act(async () => { const r=await api<{task_id:string;status:string;message:string}>(`/api/communication/drafts/${draft.id}/confirm`,json({preview_hash:preview!.preview_hash,confirmed:true,...(preview!.payload.mobile_context ? {device_id:preview!.payload.mobile_context.device_id,action:preview!.payload.mobile_context.payload.action} : {})})); setResult(r); setPreview(undefined); await onResultChange?.(r); if(r.status === "manual") setManual(await api(`/api/communication/tasks/${r.task_id}/manual-open`,{method:"POST"})); })}>{preview?.payload.mode === "mobile" ? "确认并交给手机" : preview?.payload.mode === "manual" ? "确认并准备联系" : "确认发送"}</Button>}>
      {error && <Alert type="error" showIcon message={error} style={{marginBottom:12}} />}
      {preview && <>{preview.payload.mobile_context?.payload.action === "public_comment" && <Alert type="warning" showIcon message="本次发布公开作品留言，内容会对外显示" style={{marginBottom:12}} />}<Typography.Paragraph>发件账号：{preview.payload.mobile_context?.payload.sender || preview.payload.from || "人工联系"}</Typography.Paragraph>{preview.payload.mobile_context && <Typography.Paragraph>执行手机：{preview.payload.mobile_context.device_label} · {MOBILE_ACTIONS[platform || ""]?.find(a => a.value === preview.payload.mobile_context?.payload.action)?.label}</Typography.Paragraph>}<Typography.Paragraph strong>收件人：{preview.payload.to}</Typography.Paragraph>{preview.payload.subject && <Typography.Paragraph strong>主题：{preview.payload.subject}</Typography.Paragraph>}<Typography.Paragraph style={{whiteSpace:"pre-wrap"}}>{preview.payload.body}</Typography.Paragraph><Checkbox checked={confirmed} onChange={e => setConfirmed(e.target.checked)}>我已核对收件人和完整内容，确认{preview.payload.mode === "manual" ? "用于本次联系" : "发送"}</Checkbox></>}
    </Modal>
  </Card>;
}
