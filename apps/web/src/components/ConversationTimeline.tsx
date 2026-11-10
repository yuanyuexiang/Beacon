"use client";
import { Button, Collapse, Empty, Select, Space, Tag, Typography } from "antd";
import { ContactConversation, ConversationMessage, MESSAGE_STATES } from "@/lib/conversations";
import { Contact } from "@/lib/communication";
import { channelLabel } from "@/lib/format";
import { ReactNode, useEffect, useRef } from "react";

const sources: Record<string,string> = { gmail:"Gmail", manual:"人工记录", mobile:"手机执行", meta:"Meta API", social:"Meta API" };
export default function ConversationTimeline({ conversation, contacts, actions, onLink, readOnly = false }: {
  conversation: ContactConversation; contacts: Contact[]; readOnly?: boolean;
  actions: (m:ConversationMessage) => ReactNode; onLink: (eventId:string, contactId:string) => void;
}) {
  const viewport = useRef<HTMLDivElement>(null);
  const atBottom = useRef(true);
  const previous = useRef("");
  const last = conversation.messages.at(-1)?.id;
  useEffect(() => {
    if (viewport.current && (previous.current !== conversation.id || atBottom.current)) {
      viewport.current.scrollTop = viewport.current.scrollHeight;
    }
    previous.current = conversation.id;
  }, [conversation.id,last]);
  return <div className="conversation-history" ref={viewport} aria-label="会话消息记录" onScroll={() => {
    const el=viewport.current; if(el) atBottom.current=el.scrollHeight-el.scrollTop-el.clientHeight < 80;
  }}>
    {!conversation.messages.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚无沟通记录，可在下方写第一条消息" />}
    {conversation.messages.map(m => <article className={`conversation-message ${m.direction}`} key={m.id}>
      <div className="conversation-message-meta">{m.direction === "outbound" ? "我们发出" : m.direction === "note" ? "备注" : "客户回复"} · {new Date(m.at).toLocaleString("zh-CN")}</div>
      <div className="conversation-bubble">
        {m.subject && <Typography.Paragraph strong style={{marginBottom:8}}>{m.subject}</Typography.Paragraph>}
        <div style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{m.body}</div>
        {m.headers_only && <Typography.Paragraph type="secondary" style={{marginTop:8,marginBottom:0}}>仅同步了邮件头，尚未读取回复正文。</Typography.Paragraph>}
        <Space wrap style={{marginTop:10}}><Tag color={m.direction === "inbound" ? "green" : ["failed","blocked","unknown","needs_user"].includes(m.status) ? "orange" : undefined}>{MESSAGE_STATES[m.status] || m.status}</Tag><Typography.Text type="secondary">{sources[m.source] || (m.source.startsWith("mobile") ? "手机回填" : m.source)}</Typography.Text></Space>
        {m.error && <Typography.Paragraph type="warning" style={{marginTop:8,marginBottom:0}}>{m.error}</Typography.Paragraph>}
        {m.task_id && <Collapse ghost size="small" items={[{key:"execution",label:"执行详情／截图",children:actions(m)}]} />}
        {conversation.id === "unlinked" && m.event_id && <div style={{marginTop:12}}><Select disabled={readOnly} aria-label="关联回复联系方式" placeholder="选择对应联系方式" style={{width:"100%"}} options={contacts.filter(c => c.channel === m.channel).map(c => ({value:c.id,label:`${channelLabel(c.channel,c.contact_ref)} · ${c.contact_ref}`}))} onChange={value => onLink(m.event_id!,value)} /></div>}
      </div>
    </article>)}
    {!!conversation.messages.length && <Button type="text" size="small" onClick={() => { const el=viewport.current; if(el) el.scrollTop=el.scrollHeight; }}>回到最新消息</Button>}
  </div>;
}
