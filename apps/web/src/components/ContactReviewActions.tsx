"use client";
import { Alert, Checkbox, Collapse, DatePicker, Form, Input, Modal, Select, Space, Typography } from "antd";
import Button from "@/components/AccessButton";
import { useState } from "react";
import { api, json } from "@/lib/api";
import { AutoAdmission, ContactAssessment, CONTACT_PURPOSE, CONTACT_RANK_LABELS } from "@/lib/contact-ranking";

type Row = { auto_admission?: AutoAdmission | null; id: string; channel: string; contact_ref: string | null; contact_source: string | null; contact_usable: string; eligibility: string; recommendation?: ContactAssessment | null };
export default function ContactReviewActions({ leadId, row, website, busy, onChanged }: { leadId: string; row: Row; website?: string | null; busy: boolean; onAI: () => void; onAdmission: () => void; onChanged: () => Promise<void> }) {
  const [mode, setMode] = useState<"facts" | "admission">();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>();
  const [confirmed, setConfirmed] = useState(false);
  const [form] = Form.useForm();
  const admission = mode === "admission";
  const eligibility = Form.useWatch("eligibility", form);
  const open = (next: "facts" | "admission") => { form.resetFields(); setConfirmed(false); setError(undefined); form.setFieldsValue(next === "facts" ? { recommendation: row.recommendation?.recommendation || "recommended", affiliation: row.recommendation?.affiliation === "unknown" ? "target" : row.recommendation?.affiliation || "target", owner: row.recommendation?.owner || "", purpose: row.recommendation?.purpose === "unknown" ? "general" : row.recommendation?.purpose || "general", reason: "", source_url: website || undefined, contact_usable: row.contact_usable } : { eligibility: row.eligibility, contact_usable: row.contact_usable, evidence: "" }); setMode(next); };
  return <><Space size={0} wrap><Button size="small" type="link" disabled={busy} onClick={() => open("facts")}>人工确认</Button><Button size="small" type="link" disabled={busy} onClick={() => open("admission")}>准入设置</Button></Space>
    <Modal forceRender title={admission ? "渠道准入确认" : "确认联系方式归属与用途"} open={!!mode} onCancel={() => { if (!saving) setMode(undefined); }} onOk={() => form.submit()} okText={admission ? "保存准入确认" : "保存人工确认"} confirmLoading={saving} okButtonProps={{ disabled: admission && eligibility === "allowed" && !confirmed }}>
      <Typography.Paragraph strong>{row.contact_ref}</Typography.Paragraph>
      <Alert type="info" showIcon message={admission ? "依据实际审核结果确认渠道准入。AI 归属确认不代表允许发送；尚无明确依据时保持待核对。" : "在当前行完成归属与用途确认；结果会保留，后续 AI 不覆盖人工确认，也不会改变渠道准入。"} style={{ marginBottom: 16 }} />
      {row.recommendation && <Collapse size="small" style={{ marginBottom: 12 }} items={[{ key: "evidence", label: "查看已有核验依据", children: <><p>{row.recommendation.reason}</p>{row.recommendation.citations?.map((c, i) => <blockquote key={i}><p>{c.quote}</p>{c.url && <a href={c.url} target="_blank" rel="noreferrer">{c.url}</a>}</blockquote>)}</> }]} />}
      {row.auto_admission && <Alert type={row.auto_admission.status === "allowed" ? "success" : "warning"} style={{ marginBottom: 12 }} message={row.auto_admission.reason} description={<>{row.auto_admission.missing?.map((m) => <div key={m}>{m}</div>)}{row.auto_admission.subscriber_evidence?.citations?.map((c, i) => <blockquote key={i}>{c.quote}{c.url && <div><a href={c.url} target="_blank" rel="noreferrer">{c.url}</a></div>}</blockquote>)}</>} />}
      {error && <Alert type="error" message={error} style={{ marginBottom: 12 }} />}
      <Form form={form} layout="vertical" disabled={saving} onFinish={async (values) => { setSaving(true); setError(undefined); try { if (admission) { await api(`/api/leads/${leadId}/eligibility`, json({ channel: row.channel, contact_ref: row.contact_ref, contact_source: row.contact_source, ...values, rule_version: "contact-admission-manual-v1", review_due_at: values.review_due_at?.toISOString() || null })); } else { await api(`/api/leads/${leadId}/contacts/${row.id}/confirm`, json({ ...values, source_url: values.source_url || null })); } await onChanged(); setMode(undefined); } catch (e) { setError((e as Error).message); } finally { setSaving(false); } }}>
        {admission ? <><Form.Item name="eligibility" label="渠道准入" rules={[{ required: true }]}><Select options={[{ value: "unknown", label: "待核对" }, { value: "allowed", label: "允许" }, { value: "blocked", label: "禁止" }]} /></Form.Item><Form.Item name="evidence" label="准入依据与核对结果" rules={eligibility === "allowed" ? [{ required: true, whitespace: true, message: "请填写实际核对的允许依据" }] : []}><Input.TextArea rows={4} placeholder="填写真实依据、来源及核对结果，不以官网公开或 AI 推荐代替允许依据" /></Form.Item><Form.Item name="review_due_at" label="复核到期时间"><DatePicker showTime /></Form.Item>{eligibility === "allowed" && <Checkbox checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)}>我已核对允许该渠道触达的依据</Checkbox>}</> : <><Form.Item name="recommendation" label="触达建议" rules={[{ required: true }]}><Select options={Object.entries(CONTACT_RANK_LABELS).map(([value, label]) => ({ value, label }))} /></Form.Item><Form.Item name="affiliation" label="归属" rules={[{ required: true }]}><Select options={[{ value: "target", label: "目标门店" }, { value: "group", label: "所属集团" }, { value: "other", label: "其他机构／门店" }, { value: "unknown", label: "仍未确认" }]} /></Form.Item><Form.Item name="owner" label="所属门店／部门" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="purpose" label="用途" rules={[{ required: true }]}><Select options={Object.entries(CONTACT_PURPOSE).map(([value, label]) => ({ value, label }))} /></Form.Item><Form.Item name="source_url" label="来源页面（如有）" rules={[{ type: "url" }]}><Input /></Form.Item><Form.Item name="reason" label="确认依据" rules={[{ required: true, min: 5, message: "请填写至少 5 个字符的实际核对依据" }]}><Input.TextArea rows={3} /></Form.Item></>}
        <Form.Item name="contact_usable" label="联系方式可用性" style={{ marginTop: 12 }}><Select options={[{ value: "unknown", label: "未知（尚未验证可达）" }, { value: "valid", label: "已验证有效" }, { value: "invalid", label: "无效" }]} /></Form.Item>
      </Form>
    </Modal>
  </>;
}
