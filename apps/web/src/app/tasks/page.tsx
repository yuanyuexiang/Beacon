"use client";
import { Alert, Badge, Card, Checkbox, Collapse, DatePicker, Drawer, Empty, Form, Input, Modal, Select, Space, Table, Tag, Typography } from "antd";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { api, json } from "@/lib/api";
import { useOperator } from "@/lib/auth";
import { useOutreachIdentity } from "@/lib/useOutreachIdentity";
import { Assignee, CHANNELS, CommunicationTask, Draft, LeadContext, Prepared, PROGRESS, Progress, safeReturnTo } from "@/lib/communication";
import { ContactConversation, ConversationMessage } from "@/lib/conversations";
import { channelLabel } from "@/lib/format";
import { defaultExecutionMode, mobilePlatform } from "@/lib/mobile-channels";
import { HeroBand } from "@/components/ui";
import Button from "@/components/AccessButton";
import { UserIdentity } from "@/components/UserAvatar";
import MessageComposer from "@/components/MessageComposer";
import ConversationTimeline from "@/components/ConversationTimeline";
import MobileReplies from "@/components/MobileReplies";
import { MobileTask } from "@/components/MobileChannel";
import GmailOutreach from "@/components/GmailOutreach";
import SocialOutreach from "@/components/SocialOutreach";
import ChannelConditions from "@/components/ChannelConditions";

type Customer = { id:string; name:string; postcode:string|null; progress:Progress; last_message?:string; last_at?:string; unread?:number; assigned_to?:string };
type ManualPreview = { task_id:string; channel:string; url:string|null; text:string };

function TasksInner() {
  const { me } = useOperator();
  const canWrite = ["admin","director","member"].includes(me?.role || "");
  const identity = useOutreachIdentity();
  const router = useRouter(), sp = useSearchParams();
  const focusedTaskId = sp.get("task");
  const leadId = sp.get("lead") || "", channel = sp.get("channel") || undefined;
  const batch = sp.get("batch") || undefined, assigned = sp.get("owner") || undefined;
  const query = sp.get("q") || "", page = Math.max(1,Number(sp.get("page")) || 1);
  const group = sp.get("preparation") || undefined;
  const back = safeReturnTo(sp.get("returnTo") || (batch ? `/leads?batch=${encodeURIComponent(batch)}` : "/leads"));
  const [rows,setRows] = useState<Customer[]>([]), [total,setTotal] = useState(0);
  const [batches,setBatches] = useState<{batch_key:string}[]>([]), [owners,setOwners] = useState<Assignee[]>([]);
  const [loadedContext,setContext] = useState<LeadContext>(), [loadedConversations,setConversations] = useState<ContactConversation[]>([]);
  // Keep the list mounted while a different customer loads. Never render or act on the previous customer.
  const context = loadedContext?.lead.id === leadId ? loadedContext : undefined;
  const conversations = context ? loadedConversations : [];
  const [contactId,setContactId] = useState<string>(), [drafts,setDrafts] = useState<Record<string,Draft>>({});
  const [error,setError] = useState<string>(), [notice,setNotice] = useState<string>();
  const [busy,setBusy] = useState(false), [details,setDetails] = useState(false), [replyOpen,setReplyOpen] = useState(false);
  const [manual,setManual] = useState<ManualPreview>(), [confirmed,setConfirmed] = useState(false);
  const [apiTask,setApiTask] = useState<CommunicationTask>();
  const [suppression,setSuppression] = useState<Record<string,string>[]|null>(null);
  const [replyForm] = Form.useForm(), [sentForm] = Form.useForm();
  const working = useRef(new Set<string>()), generation = useRef(0), listGeneration = useRef(0);
  const readWatermarks = useRef(new Set<string>()), eventKey = useRef<string | undefined>(undefined);
  const [editing,setEditing] = useState(false);
  const navigate = useCallback((patch:Record<string,string|undefined>) => {
    const p=new URLSearchParams(sp.toString()); Object.entries(patch).forEach(([k,v]) => v ? p.set(k,v) : p.delete(k));
    router.replace(`/tasks?${p}`,{scroll:false});
  },[sp,router]);
  const refreshList = useCallback(async () => {
    const request=++listGeneration.current;
    const p=new URLSearchParams({page:String(page)});
    if(batch) p.set("batch_key",batch); if(channel) p.set("channel",channel); if(assigned) p.set("assigned_to",assigned);
    if(query) p.set("q",query); if(group) p.set("preparation_group",group);
    const r=await api<{items:Customer[];total:number}>(`/api/communication/overview?${p}`);
    if(request===listGeneration.current) {setRows(r.items);setTotal(r.total);}
  },[page,batch,channel,assigned,query,group]);
  const refreshContext = useCallback(async () => {
    const request=++generation.current;
    if(!leadId) return;
    const [c,r]=await Promise.all([api<LeadContext>(`/api/communication/leads/${leadId}`),api<{items:ContactConversation[]}>(`/api/communication/conversations/${leadId}`)]);
    if(request!==generation.current) return;
    setContext(c);setConversations(r.items);
    const focused=c.tasks.find(t => t.id === focusedTaskId);
    setContactId(old => r.items.some(x => x.id===old) ? old : focused?.eligibility_id || r.items.find(x => x.unread)?.id || r.items.find(x => x.messages.length)?.id || c.drafts?.find(d => d.queued)?.eligibility_id || r.items[0]?.id);
  },[leadId,focusedTaskId]);
  const refresh = useCallback(async () => {await Promise.all([refreshList(),refreshContext()]);},[refreshList,refreshContext]);
  useEffect(() => { api<{batch_key:string}[]>("/api/batches").then(setBatches).catch(e => setError(e.message)); api<Assignee[]>("/api/communication/assignees").then(setOwners).catch(e => setError(e.message)); },[]);
  useEffect(() => { refreshList().catch(e => setError(e.message)); },[refreshList]);
  useEffect(() => { refreshContext().catch(e => setError(e.message)); },[refreshContext]);
  useEffect(() => {if(!leadId && rows[0]) navigate({lead:rows[0].id});},[rows,leadId,navigate]);
  useEffect(() => {
    const tick=() => {if(!document.hidden && !working.current.size && !busy) refresh().catch(() => {});};
    const timer=setInterval(tick,15000);window.addEventListener("focus",tick);
    return () => {clearInterval(timer);window.removeEventListener("focus",tick);};
  },[refresh,busy]);
  const conversation=conversations.find(c => c.id===contactId);
  const selected=context?.contacts.find(c => c.id===contactId);
  useEffect(() => {
    if(!canWrite || document.hidden || !conversation?.read_through || !leadId) return;
    const token=`${leadId}:${conversation.id}:${conversation.read_through}`;
    if(readWatermarks.current.has(token)) return;
    readWatermarks.current.add(token);
    api(`/api/communication/conversations/${leadId}/${conversation.id}/read`,json({through:conversation.read_through},"PUT"))
      .then(() => {setConversations(old => old.map(c => c.id===conversation.id ? {...c,unread:0} : c));void refreshList();})
      .catch(() => readWatermarks.current.delete(token));
  },[conversation,leadId,canWrite,refreshList]);
  const act=async (work:()=>Promise<void>) => {setBusy(true);setError(undefined);try {await work();await refresh();} catch(e) {setError((e as Error).message);} finally {setBusy(false);}};
  const startDraft=async () => {
    if(!context || !selected) return;
    const request=generation.current, target=selected.id;
    const r=await api<{items:Prepared[]}>("/api/communication/prepare",json({lead_ids:[context.lead.id],channel:selected.channel,eligibility_id:target,execution_mode:defaultExecutionMode(selected.channel),purpose:"message"}));
    const item=r.items[0];if(item.error) throw new Error(item.error);
    if(item.draft && request===generation.current) setDrafts(old => ({...old,[target]:item.draft!}));
  };
  const taskActions=(m:ConversationMessage) => {
    const task=context?.tasks.find(t => t.id===m.task_id);if(!task || !context) return null;
    const contact=context.contacts.find(c => c.id===task.eligibility_id);
    return <Space wrap>
      {task.execution_mode==="mobile" ? <MobileTask taskId={task.id} platform={mobilePlatform(task.channel,contact?.contact_ref)} onChanged={refresh} /> : task.execution_mode!=="manual" ? <Button readOnlySafe size="small" onClick={() => setApiTask(task)}>查看发送进度</Button> : ["pending","opened"].includes(task.status) ? <Button size="small" disabled={busy} onClick={() => act(async () => {setManual(await api<ManualPreview>(`/api/communication/tasks/${task.id}/manual-open`,{method:"POST"}));setConfirmed(false);sentForm.resetFields();})}>复制消息／记录发送</Button> : null}
      {task.status==="paused" && <Button size="small" disabled={busy} onClick={() => act(async () => {await api(`/api/tasks/${task.id}/resume`,json({reason:"负责人明确恢复这条消息"}));})}>恢复此消息</Button>}
      {["pending","opened","paused"].includes(task.status) && <Button danger size="small" disabled={busy} onClick={() => act(async () => {await api(`/api/tasks/${task.id}/cancel`,json({reason:"负责人结束此消息"}));})}>结束此消息</Button>}
      {m.deliveries.map(d => <Typography.Text type="secondary" key={d.id}>{d.error}</Typography.Text>)}
    </Space>;
  };
  const activeDraft=contactId ? drafts[contactId] : undefined;
  return <>
    <HeroBand kicker="COMMUNICATION" title="客户沟通" subtitle="按客户和联系方式查看消息，继续发送与跟进。" extra={<Space wrap><Link href={back}><Button readOnlySafe>返回名单</Button></Link><Button readOnlySafe onClick={() => refresh().catch(e => setError(e.message))}>刷新消息</Button><Button readOnlySafe onClick={() => api<Record<string,string>[]>("/api/suppressions").then(setSuppression).catch(e => setError(e.message))}>抑制名单</Button></Space>} />
    {error && <Alert type="error" showIcon message={error} closable onClose={() => setError(undefined)} style={{marginBottom:12}} />}
    {notice && <Alert type="success" showIcon message={notice} closable onClose={() => setNotice(undefined)} style={{marginBottom:12}} />}
    <MobileReplies onChanged={refresh} />
    <Space wrap style={{marginBottom:16}}>
      <Select aria-label="来源名单" allowClear placeholder="全部名单" value={batch} style={{width:200}} options={batches.map(b => ({value:b.batch_key,label:b.batch_key}))} disabled={editing} onChange={v => navigate({batch:v,lead:undefined,page:"1"})} />
      <Select aria-label="沟通渠道筛选" allowClear placeholder="全部渠道" value={channel} options={CHANNELS} style={{width:160}} onChange={v => navigate({channel:v,page:"1"})} />
      <Select aria-label="沟通负责人筛选" allowClear placeholder="全部负责人" value={assigned} options={owners.map(o => ({value:o.username,label:o.display_name || o.username}))} style={{width:160}} onChange={v => navigate({owner:v,page:"1"})} />
      <Input.Search key={query} defaultValue={query} placeholder="搜索客户／邮编" allowClear style={{width:220}} onSearch={q => navigate({q:q || undefined,page:"1"})} />
      {group && <Tag closable onClose={() => navigate({preparation:undefined,page:"1"})}>本次任务</Tag>}
    </Space>
    <div className={`customer-workspace ${details ? "with-details" : ""}`}>
      <Card size="small" title={`客户 · ${total}`} className="customer-list">
        <Table<Customer> tableLayout="fixed" rowKey="id" showHeader={false} size="small" dataSource={rows} pagination={{current:page,pageSize:20,total,showSizeChanger:false,onChange:p => navigate({page:String(p)})}} rowClassName={r => r.id===leadId ? "communication-selected" : ""} columns={[{render:(_,r) => <button className="customer-row" disabled={editing || busy} onClick={() => navigate({lead:r.id,contact:undefined,task:undefined,draft:undefined})}>
          <div className="customer-row-top"><b className="customer-name">{r.name}</b><Badge count={r.unread || 0} size="small" /></div>
          <div className="customer-preview" title={r.last_message}>{r.last_message || "尚未发送消息"}</div>
          <div className="customer-row-top"><Tag>{PROGRESS[r.progress.status]}</Tag><small>{r.last_at ? new Date(r.last_at).toLocaleString("zh-CN",{month:"numeric",day:"numeric",hour:"2-digit",minute:"2-digit"}) : r.postcode}</small></div>
          {r.assigned_to && <small>负责人：{r.assigned_to}</small>}
        </button>}]} />
      </Card>
      <Card key={leadId} size="small" loading={!!leadId && !context} className="customer-chat" title={context?.lead.name || rows.find(r => r.id === leadId)?.name || "选择客户"} extra={<Button readOnlySafe size="small" onClick={() => setDetails(v => !v)}>{details ? "收起资料" : "客户资料"}</Button>}>
        {!context ? <Empty description="从左侧选择客户，或在名单中发起沟通" /> : <>
          <div className="conversation-toolbar"><Select aria-label="客户联系方式" placeholder="选择联系方式" value={contactId} disabled={editing || busy} style={{width:"100%"}} options={conversations.map(c => ({value:c.id,label:`${c.id==="unlinked" ? "未关联记录" : `${channelLabel(c.channel || "",c.contact_ref)} · ${c.contact_ref || "未填写"}`}${c.unread ? ` · ${c.unread} 条未读` : ""}`}))} onChange={id => {setContactId(id);setNotice(undefined);}} />
          {selected && <Button readOnlySafe onClick={() => {replyForm.resetFields();eventKey.current=undefined;setReplyOpen(true);}}>记录回复</Button>}</div>
          {conversation ? <ConversationTimeline readOnly={!canWrite} conversation={conversation} contacts={context.contacts} actions={taskActions} onLink={(eventId,contactId) => act(async () => {await api(`/api/communication/conversations/${leadId}/events/${eventId}/link`,json({contact_id:contactId}));})} /> : <Empty description="请在线索详情添加联系方式" />}
          {selected && <div className="conversation-compose">
            <div className="conversation-compose-heading"><b>写新消息</b><Typography.Text type="secondary">无需等待客户回复，可以继续联系</Typography.Text></div>
            {!activeDraft && <Button type="primary" loading={busy} disabled={!canWrite} onClick={() => act(startDraft)}>写消息／继续草稿</Button>}
            {Object.entries(drafts).filter(([,d]) => d.lead_id === leadId).map(([id,d]) => <div key={d.id} style={{display:id===contactId ? "block" : "none"}}>
              <MessageComposer draft={d} assignees={owners} returnTo={back} sender={identity.sender} optOut={identity.optOut} lockedRecipient conversation onChange={value => setDrafts(old => ({...old,[id]:value}))} onWorkingChange={(key,active) => {if(active) working.current.add(key);else working.current.delete(key);setEditing(working.current.size>0);}} onResultChange={async result => {await refresh();if(result && result.status!=="manual") {setNotice(result.message);await startDraft();}}} />
            </div>)}
          </div>}
        </>}
      </Card>
      {details && <Card size="small" title="客户资料" className="customer-details">
        {!context ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} /> : <>
          <p>{context.lead.address} {context.lead.postcode}</p>
          {context.lead.website && <p><a href={context.lead.website} target="_blank" rel="noreferrer">查看官网</a></p>}
          <p>负责人：<UserIdentity username={rows.find(r => r.id===leadId)?.assigned_to} /></p>
          <Space wrap><Link href={`/leads/${leadId}?returnTo=${encodeURIComponent(back)}`}>完整门店资料</Link><Link href={`/leads/${leadId}?returnTo=${encodeURIComponent(back)}#menu-files`}>菜单资料</Link></Space>
          <Collapse ghost style={{marginTop:16}} items={[{key:"contacts",label:`联系方式 · ${context.contacts.length}`,children:context.contacts.map(c => <div key={c.id} style={{marginBottom:16,overflowWrap:"anywhere"}}><b>{channelLabel(c.channel,c.contact_ref)}</b><p>{c.contact_ref}</p><ChannelConditions leadId={leadId} contactId={c.id} contact={c.contact_ref} busy={busy || !canWrite} onChanged={refresh} /></div>)},{key:"menu",label:"菜单分析",children:context.analyses.length ? context.analyses.map(a => <p key={a.id}>v{a.version} · {a.facts.join("；")}</p>) : "尚无已核对菜单，可先询问菜单或负责人"}]} />
        </>}
      </Card>}
    </div>
    <Modal title={`记录 ${channelLabel(selected?.channel || "",selected?.contact_ref)} 回复`} open={replyOpen} onCancel={() => setReplyOpen(false)} footer={null} destroyOnHidden>
      <p style={{overflowWrap:"anywhere"}}>{selected?.contact_ref}</p><Form form={replyForm} layout="vertical" onFinish={v => act(async () => {eventKey.current ||= `manual:${crypto.randomUUID()}`;await api(`/api/communication/conversations/${leadId}/${contactId}/reply`,json({event_key:eventKey.current,kind:v.kind,summary:v.summary,occurred_at:v.occurred_at?.toISOString() || null}));setReplyOpen(false);setNotice("已记录到当前联系方式会话");})}>
        <Form.Item name="kind" label="沟通结果" initialValue="reply"><Select options={[{value:"reply",label:"客户回复"},{value:"note",label:"沟通备注"},{value:"reject",label:"拒绝联系"},{value:"unsubscribe",label:"退订"},{value:"bounce",label:"退信／无效"}]} /></Form.Item>
        <Form.Item name="summary" label="回复原文／备注" rules={[{required:true}]}><Input.TextArea rows={5} maxLength={10000} /></Form.Item><Form.Item name="occurred_at" label="实际回复时间（可选）"><DatePicker showTime /></Form.Item><Button type="primary" htmlType="submit" loading={busy}>保存回复</Button>
      </Form>
    </Modal>
    <Modal title="人工执行 · 打开平台不等于已发送" open={!!manual} onCancel={() => setManual(undefined)} footer={null} width={720}>
      {error && <Alert type="error" message={error} style={{ marginBottom: 12 }} />}
      {manual && <><Alert type="info" showIcon message="复制已审批文案，到平台人工发送；实际发送后再回填时间。" /><Typography.Paragraph style={{ whiteSpace: "pre-wrap", marginTop: 16 }}>{manual.text}</Typography.Paragraph><Space><Button disabled={busy} onClick={() => act(async () => { const fresh = await api<ManualPreview>(`/api/communication/tasks/${manual.task_id}/manual-open`, { method: "POST" }); setManual(fresh); await navigator.clipboard.writeText(fresh.text); setNotice("已复制已审批文案，尚未记录为发送"); })}>复制已审批文案</Button>{manual.url && <a href={manual.url} target="_blank" rel="noreferrer">打开 {channelLabel(manual.channel)} 联系入口 ↗</a>}</Space>
        <Form form={sentForm} layout="vertical" disabled={!canWrite || busy} style={{ marginTop: 20 }} onFinish={(v) => act(async () => { if (!confirmed) throw new Error("请先确认已经在平台实际发送"); await api(`/api/tasks/${manual.task_id}/sent`, json({ sent_at: v.sent_at.toISOString(), notes: v.notes })); setManual(undefined); setNotice("已记录人工发送，客户进展已更新"); })}><Form.Item name="sent_at" label="实际发送时间" rules={[{ required: true }]}><DatePicker showTime /></Form.Item><Form.Item name="notes" label="发送备注"><Input.TextArea maxLength={1500} /></Form.Item><Checkbox checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)}>我已在平台实际发送，并核对收件人和内容</Checkbox><Button type="primary" htmlType="submit" disabled={!confirmed} loading={busy} style={{ marginLeft: 12 }}>记录已人工发送</Button></Form></>}
    </Modal>
    <Drawer title="接口预览与发送记录" width={1000} open={!!apiTask} onClose={() => setApiTask(undefined)} destroyOnHidden>
      {apiTask?.channel === "email" ? <GmailOutreach tasks={[apiTask]} name={((id:string) => context?.lead.id===id ? context.lead.name : id)} onChanged={refresh} focusTaskId={apiTask.id} /> : apiTask && <SocialOutreach tasks={[apiTask]} name={((id:string) => context?.lead.id===id ? context.lead.name : id)} onChanged={refresh} focusTaskId={apiTask.id} />}
    </Drawer>
    <Modal title="抑制名单" open={!!suppression} onCancel={() => setSuppression(null)} footer={null} width={850}><Table rowKey="id" dataSource={suppression || []} columns={[{ title: "客户", dataIndex: "lead_id" }, { title: "联系值", dataIndex: "contact_ref" }, { title: "原因", dataIndex: "reason" }, { title: "时间", dataIndex: "created_at" }]} /></Modal>
    <style>{`
      .customer-workspace {display:grid;grid-template-columns:280px minmax(0,1fr);gap:16px;align-items:start}
      .customer-workspace.with-details {grid-template-columns:260px minmax(0,1fr) 280px}
      .customer-workspace > * {min-width:0;max-width:100%}
      .customer-list {overflow:hidden}
      .customer-list .ant-table-wrapper,.customer-list .ant-table-container {min-width:0;max-width:100%}
      .customer-list .ant-table-content {max-height:650px;overflow-y:auto!important;overflow-x:hidden!important}
      .customer-list table {width:100%!important;table-layout:fixed}
      .customer-name {min-width:0;overflow-wrap:anywhere;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
      .customer-preview {width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#888;margin:6px 0}
      .customer-row-top > .ant-badge {flex-shrink:0}
      .customer-row {box-sizing:border-box;min-width:0;max-width:100%;display:block;text-align:left;border:0;background:transparent;width:100%;padding:12px 4px;cursor:pointer;color:inherit}
      .customer-row:disabled {cursor:wait;opacity:.7}
      .customer-row-top {min-width:0;display:flex;justify-content:space-between;gap:8px;align-items:start}
      .communication-selected td {background:#fff4f0!important;border-left:3px solid #cf010e}
      .customer-list .ant-card-body {padding:0 8px}
      .customer-list .ant-table-cell {padding:0 8px!important}
      .conversation-toolbar {display:flex;gap:8px;padding-bottom:14px;border-bottom:1px solid #eee}
      .conversation-history {height:420px;overflow:auto;padding:16px 8px;background:#faf9f7;border-radius:8px;margin-top:12px}
      .conversation-message {display:flex;flex-direction:column;align-items:flex-start;margin:0 0 18px}
      .conversation-message.outbound {align-items:flex-end}
      .conversation-message-meta {font-size:12px;color:#888;margin-bottom:6px}
      .conversation-bubble {max-width:90%;padding:12px 16px;background:white;border:1px solid #eee;border-radius:12px;min-width:180px}
      .outbound .conversation-bubble {background:#fff3ef;border-color:#f4ddd6}
      .note .conversation-bubble {background:#f6f6f6}
      .conversation-compose {border-top:1px solid #eee;margin-top:16px;padding-top:16px}
      .conversation-compose-heading {display:flex;gap:12px;align-items:center;margin-bottom:12px;flex-wrap:wrap}
      .customer-chat {overflow:hidden}
      .customer-chat .ant-card-head-title {white-space:normal;overflow-wrap:anywhere}
      .conversation-toolbar > .ant-select {min-width:0;flex:1}
      .conversation-toolbar > button {flex-shrink:0}
      .conversation-bubble {box-sizing:border-box;min-width:0;overflow-wrap:anywhere}
      .customer-chat .outreach-editor > .ant-card-body {padding:0}
      .customer-chat .ant-space {max-width:100%}
      .customer-chat .ant-space-item {min-width:0;max-width:100%}
      @media(max-width:1400px){.customer-workspace.with-details {grid-template-columns:240px minmax(0,1fr)}.customer-details {grid-column:2}}
      @media(max-width:900px){.customer-workspace,.customer-workspace.with-details {grid-template-columns:minmax(0,1fr)}.customer-details {grid-column:auto}.customer-list {max-height:300px;overflow:auto}.conversation-bubble {max-width:96%}}
    `}</style>
  </>;
}
function TasksRoute() {return <TasksInner />;}
export default function TasksPage() {return <Suspense fallback={<p>读取客户沟通…</p>}><TasksRoute /></Suspense>;}
