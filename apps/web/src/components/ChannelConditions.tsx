"use client";
import { Alert, Checkbox, DatePicker, Form, Input, Modal, Select, Space, Typography } from "antd";
import dayjs, { Dayjs } from "dayjs";
import { useState } from "react";
import Button from "@/components/AccessButton";
import { api, json } from "@/lib/api";
type Evidence = { key: string; source: string; detail: string; checked_at: string; expires_at: string; result: string };
type Conditions = { reply_requirements: { key: string; label: string; hint: string }[]; requirements: { key: string; label: string; hint: string }[]; record?: {purpose?: string; content_id?: string; decision: string; note: string; evidence: Evidence[]}; missing: string[]; execution: string; legacy: boolean };
export default function ChannelConditions({ leadId, contactId, contact, busy, onChanged, buttonLabel = "联系条件" }: { leadId: string; contactId: string; contact?: string | null; busy?: boolean; buttonLabel?: string; onChanged: () => Promise<void> }) {
  const [open, setOpen] = useState(false), [loading, setLoading] = useState(false), [saving, setSaving] = useState(false);
  const [researching, setResearching] = useState(false);
  const [data, setData] = useState<Conditions>(), [error, setError] = useState<string>(), [confirmed, setConfirmed] = useState(false);
  const [form] = Form.useForm();
  const decision = Form.useWatch("decision", form);
  const purpose = Form.useWatch("purpose", form) || "business_marketing";
  const [messages, setMessages] = useState<{id:string; subject?:string; approved:boolean; version:number}[]>([]);
  const requirements = purpose === "requested_reply" ? data?.reply_requirements : data?.requirements;
  const load = async () => { setOpen(true); setLoading(true); setData(undefined); setError(undefined); setConfirmed(false); form.resetFields(); try {
    const next = await api<Conditions>(`/api/leads/${leadId}/contacts/${contactId}/conditions`); setData(next);
    const context = await api<{contents: {id:string; subject?:string; approved:boolean; version:number}[]}>(`/api/communication/leads/${leadId}`); setMessages(context.contents);
    form.setFieldsValue({ purpose: next.record?.purpose || "business_marketing", content_id: next.record?.content_id, decision: next.record?.decision || "unknown", note: next.record?.note || "", evidence: (next.record?.purpose === "requested_reply" ? next.reply_requirements : next.requirements).map(r => { const e = next.record?.evidence.find(e => e.key === r.key); return { ...e, key: r.key, checked_at: e?.checked_at ? dayjs(e.checked_at) : undefined, expires_at: e?.expires_at ? dayjs(e.expires_at) : undefined }; }) });
  } catch(e) { setError((e as Error).message); } finally { setLoading(false); } };
  return <><Button size="small" type="link" disabled={busy} onClick={load}>{buttonLabel}</Button>
    <Modal title="核对本次业务联系条件" open={open} onCancel={() => { if (!saving && !loading && !researching) setOpen(false); }} onOk={() => form.submit()} okText="保存核对结果" confirmLoading={saving} okButtonProps={{disabled: loading || researching || !data || (decision === "allowed" && !confirmed)}} width={680} style={{top:24}} styles={{body:{maxHeight:"calc(100vh - 180px)",overflowY:"auto",paddingRight:8}}}>
      <Typography.Paragraph strong>{contact}</Typography.Paragraph>
      <Alert type="info" showIcon message="这里只记录实际依据，不发送消息，也不会授予平台 API 权限。" description={data?.execution} style={{marginBottom:16}} />
      {data?.legacy && <Typography.Paragraph type="secondary">旧审核记录保留。本表保存后按本渠道依据及到期时间复核；没有依据可保存为待补充。</Typography.Paragraph>}
      <Button loading={researching} disabled={loading || saving || researching} onClick={async () => { setResearching(true); setError(undefined); try { await api(`/api/leads/${leadId}/auto-admission`, {method:"POST"}); await onChanged(); const next = await api<Conditions>(`/api/leads/${leadId}/contacts/${contactId}/conditions`); setData(next); } catch(e) { setError((e as Error).message); } finally { setResearching(false); } }} style={{marginBottom:12}}>AI 补查归属与依据</Button>
      <Typography.Paragraph type="secondary">AI 查找官网事实，不会推断客户同意、TPS 筛查结果或平台权限。表单中未保存的内容会保留。</Typography.Paragraph>
      {error && <Alert type="error" message={error} />}
      <Form form={form} layout="vertical" disabled={loading || saving || researching} onFinish={async values => { setSaving(true); setError(undefined); try {
        await api(`/api/leads/${leadId}/contacts/${contactId}/conditions`, json({ purpose: values.purpose, content_id: values.purpose === "requested_reply" ? values.content_id : null, decision: values.decision, note: values.note, confirmed, evidence: (values.evidence || []).map((e: Evidence, i: number) => ({...e, key: requirements?.[i]?.key})).filter((e: Evidence) => e.source || e.detail).map((e: Omit<Evidence, "checked_at" | "expires_at"> & {checked_at?: Dayjs; expires_at?: Dayjs}) => ({ ...e, result: e.result || "verified", checked_at: e.checked_at?.toISOString(), expires_at: e.expires_at?.toISOString() })) }));
        await onChanged(); setOpen(false);
      } catch(e) { setError((e as Error).message); } finally { setSaving(false); } }}>
        <Form.Item name="purpose" label="本次动作"><Select onChange={() => { form.setFieldsValue({evidence: [], decision:"unknown"}); setConfirmed(false); }} options={[{value:"business_marketing",label:"主动业务联系／营销跟进"},{value:"requested_reply",label:"回复客户明确提出的请求"}]} /></Form.Item>
        {purpose === "requested_reply" && <Form.Item name="content_id" label="仅适用于这份回复" rules={decision === "allowed" ? [{required:true}] : []}><Select options={messages.map(m => ({value:m.id,label:`v${m.version} · ${m.subject || "回复消息"}`}))} /></Form.Item>}
        <Form.Item name="decision" label="本次联系条件" rules={[{required:true}]}><Select options={[{value:"unknown",label:"待补充依据"},{value:"allowed",label:"依据已核对"},{value:"blocked",label:"不应联系"}]} /></Form.Item>
        {requirements?.map((r,i) => <div key={r.key} style={{padding:12, border:"1px solid #eee",borderRadius:8,marginBottom:12}}>
          <Typography.Text strong>{r.label}</Typography.Text><Typography.Paragraph type="secondary">{r.hint}</Typography.Paragraph>
          <Form.Item name={["evidence",i,"key"]} initialValue={r.key} hidden><Input /></Form.Item>
          <Form.Item name={["evidence",i,"source"]} label="证据来源／记录编号" rules={decision === "allowed" ? [{required:true,min:3}] : []}><Input placeholder="来源页面、客户授权记录或筛查记录编号" /></Form.Item>
          <Form.Item name={["evidence",i,"detail"]} label="原文及核对结果" rules={decision === "allowed" ? [{required:true,min:10}] : []}><Input.TextArea rows={3} /></Form.Item>
          {["tps","ctps"].includes(r.key) && <Form.Item name={["evidence",i,"result"]} label="筛查结果" rules={decision === "allowed" ? [{required:true}] : []}><Select options={[{value:"clear",label:"查询未登记（系统有效期最长 28 天）"},{value:"specific_consent",label:"已有针对本方的有效来电同意"}]} /></Form.Item>}
          <Space wrap><Form.Item name={["evidence",i,"checked_at"]} label="实际核对时间" rules={decision === "allowed" ? [{required:true}] : []}><DatePicker showTime /></Form.Item><Form.Item name={["evidence",i,"expires_at"]} label="下次复核／依据到期" rules={decision === "allowed" ? [{required:true}] : []}><DatePicker showTime /></Form.Item></Space>
        </div>)}
        <Form.Item name="note" label="本次联系目的与审核说明" rules={[{required:true,min:5}]}><Input.TextArea rows={2} placeholder="说明本次业务联系目的；普通回复或同意不自动覆盖其他营销用途" /></Form.Item>
        {decision === "allowed" && <Checkbox checked={confirmed} onChange={e => setConfirmed(e.target.checked)}>我已核对上述真实依据及适用范围</Checkbox>}
      </Form>
    </Modal>
  </>;
}
