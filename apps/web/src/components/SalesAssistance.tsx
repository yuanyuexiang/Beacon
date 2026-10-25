"use client";
import { useEffect, useState } from "react";
import { Alert, Card, Collapse, Input, Select, Space, Typography, message } from "antd";
import Button from "@/components/AccessButton";
import { api, json } from "@/lib/api";

type Citation = { document_id: string; quote: string };
type Brief = { result: { summary: string; approach: string; gaps: string[]; citations: Citation[] } | null; stale: boolean };
type Reply = { event_id: string; intent: string; summary: string; suggested_reply: string; citations: Citation[] };
const intents: Record<string, string> = { interested: "有兴趣", quote: "询问报价", referral: "转介", later: "稍后联系", unsubscribe: "退订，已停止触达", reject: "拒绝，已停止触达", unknown: "需要人工判断" };
function Sources({ citations }: { citations: Citation[] }) {
  return <Collapse ghost items={[{ key: "sources", label: "查看依据", children: citations.map((c, i) => <Typography.Paragraph key={i}><blockquote>{c.quote}</blockquote><Typography.Text type="secondary">来源：{c.document_id}</Typography.Text></Typography.Paragraph>) }]} />;
}
export default function SalesAssistance({ leadId, onChanged }: { leadId: string; onChanged: () => void }) {
  const [brief, setBrief] = useState<Brief>();
  const [briefBusy, setBriefBusy] = useState(false);
  const [replyBusy, setReplyBusy] = useState(false);
  const [body, setBody] = useState("");
  const [channel, setChannel] = useState("email");
  const [reply, setReply] = useState<Reply>();
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [sender, setSender] = useState("");
  const [optOut, setOptOut] = useState("Please let me know if you would prefer not to hear from us again.");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { let active = true; api<Brief>(`/api/leads/${leadId}/sales-brief`).then(r => { if (active) setBrief(r); }).catch(() => {}); return () => { active = false; }; }, [leadId]);
  const generate = async () => {
    if (briefBusy) return;
    setBriefBusy(true); setError("");
    try { setBrief(await api<Brief>(`/api/leads/${leadId}/sales-brief`, { method: "POST" })); }
    catch (e) { setError((e as Error).message); }
    finally { setBriefBusy(false); }
  };
  const understand = async () => {
    if (replyBusy) return;
    setReplyBusy(true); setReply(undefined); setError("");
    try { setReply(await api<Reply>(`/api/leads/${leadId}/reply-advice`, json({ body, channel }))); }
    catch (e) { setError((e as Error).message); }
    finally { setReplyBusy(false); onChanged(); }
  };
  return <Card size="small" title="销售助手" style={{ marginBottom: 16, gridColumn: "1 / -1" }} extra={<Button loading={briefBusy} onClick={generate}>{brief?.result ? "更新销售摘要" : "生成销售摘要"}</Button>}>
    {notice && <Alert type="success" showIcon message={notice} />}{error && <Alert type="warning" showIcon message={error} />}
    {brief?.stale && <Alert type="warning" message="门店或菜单资料已变化，请更新摘要" />}
    {brief?.result ? <><Typography.Paragraph>{brief.result.summary}</Typography.Paragraph><Typography.Paragraph><strong>建议切入点：</strong>{brief.result.approach}</Typography.Paragraph>{brief.result.gaps.map((gap, i) => <div key={i}>待补充：{gap}</div>)}<Sources citations={brief.result.citations} /></> : <Typography.Paragraph type="secondary">根据门店资料、已核对菜单和我们的服务生成有依据的销售摘要；缺少菜单也可以继续准备询问消息。</Typography.Paragraph>}
    <Collapse items={[{ key: "reply", label: "理解客户回复与准备跟进", children: <Space direction="vertical" style={{ width: "100%" }}>
      <Typography.Text type="secondary">粘贴实际收到的回复。点击后会记录收到回复并暂停待发任务；识别为拒绝或退订时停止触达。建议文案仍须人工核对，不会自动发送。</Typography.Text>
      <Select value={channel} onChange={setChannel} disabled={replyBusy} options={[{ value: "email", label: "邮件" }, { value: "facebook", label: "Facebook" }, { value: "instagram", label: "Instagram" }, { value: "linkedin", label: "LinkedIn" }, { value: "tiktok", label: "TikTok" }]} />
      <Input.TextArea value={body} onChange={e => { setBody(e.target.value); setReply(undefined); }} maxLength={12000} rows={4} disabled={replyBusy} placeholder="只粘贴本次客户回复，尽量去掉历史引用和签名" />
      <Button loading={replyBusy} disabled={body.trim().length < 5} onClick={understand}>记录回复并由 AI 分析</Button>
      {reply && <><Alert type={reply.intent === "unsubscribe" || reply.intent === "reject" ? "warning" : "info"} message={intents[reply.intent]} description={reply.summary} /><Sources citations={reply.citations} /><Button loading={confirming} onClick={async () => { setConfirming(true); try { await api(`/api/leads/${leadId}/reply-confirm`, json({ event_id: reply.event_id })); setNotice("已确认意向并计入统计"); onChanged(); } catch (e) { setError((e as Error).message); } finally { setConfirming(false); } }}>确认意向并回填统计</Button>{reply.suggested_reply && <><Input.TextArea rows={4} value={reply.suggested_reply} readOnly /><Input aria-label="跟进发送身份" placeholder="发送身份／署名" value={sender} onChange={e => setSender(e.target.value)} /><Input aria-label="跟进退出说明" value={optOut} onChange={e => setOptOut(e.target.value)} /><Button loading={saving} disabled={!sender.trim() || !optOut.trim() || reply.intent === "unknown"} onClick={async () => { setSaving(true); try { await api(`/api/leads/${leadId}/reply-draft`, json({ event_id: reply.event_id, sender_identity: sender, opt_out_text: optOut })); setNotice("跟进草稿已保存，请在下方文案区核对并确认"); onChanged(); } catch (e) { setError((e as Error).message); } finally { setSaving(false); } }}>保存为待确认文案</Button><Button readOnlySafe onClick={() => navigator.clipboard.writeText(reply.suggested_reply).then(() => message.success("已复制，请粘贴到文案编辑区核对并确认")).catch(() => message.error("复制失败，请手动选择文字复制"))}>复制跟进建议</Button></>}</>}
    </Space> }]} />
  </Card>;
}
