"use client";
import { Alert, Descriptions, Modal, Space, Tag, Typography } from "antd";
import Button from "@/components/AccessButton";
import { useState } from "react";
import { api } from "@/lib/api";

type Citation = { document_id?: string; quote: string };
type Evidence = { status?: string; category?: string; reason?: string; website?: string; services?: string[]; citations?: Citation[]; judgment?: { citations: Citation[] }; sources?: { id: string; url: string }[] };
export type ResearchLead = { id: string; name: string; operating_type?: Evidence | null; website_research?: Evidence | null; google_enrichment?: Evidence | null };
export const RESEARCH_LABELS: Record<string, string> = { verified: "已核验", insufficient: "信息不足", retry: "待重试", ai_unavailable: "AI 暂不可用", conflict: "身份冲突，需人工核对", review: "历史待核验", failed: "查询失败，可重试" };
const TYPES: Record<string, string> = { restaurant: "餐厅", cafe: "咖啡馆", takeaway: "外卖店", pub: "Pub／酒吧", institution: "机构餐饮", unknown: "信息不足" };
const SERVICES: Record<string, string> = { dine_in: "堂食", takeaway: "外卖", coffee: "咖啡", food_service: "供应餐食", drinks: "酒水" };

export default function WebsiteReview({ lead, onChanged }: { lead: ResearchLead; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [latest, setLatest] = useState<ResearchLead>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const current = open && latest ? latest : lead;
  const operation = current.operating_type;
  const identity = current.website_research;
  const google = current.google_enrichment;
  const status = identity?.status || google?.status;
  const evidence = (value?: Evidence | null) => <div style={{ width: "100%", minWidth: 0, overflowWrap: "anywhere" }}>
    <Typography.Paragraph>{value?.reason || "尚未执行此项识别"}</Typography.Paragraph>
    {(value?.citations || value?.judgment?.citations || []).map((c, i) => <blockquote key={i} style={{ margin: "8px 0", paddingLeft: 12, borderLeft: "2px solid #ddd" }}><p>{c.quote}</p><Typography.Text type="secondary">来源：{value?.sources?.find((s) => s.id === c.document_id)?.url || c.document_id || "未记录页面"}</Typography.Text></blockquote>)}
  </div>;
  return <>
    <div>{TYPES[operation?.category || ""] || "待识别"}{operation?.status && operation.status !== "verified" && <span style={{ color: "#888", fontSize: 12 }}> · {RESEARCH_LABELS[operation.status]}</span>}</div>
    <Space wrap size={2}>{operation?.services?.map((s) => <Tag key={s}>{SERVICES[s] || s}</Tag>)}</Space>
    {status && <div style={{ color: "#888", fontSize: 12 }}>{identity ? "官网" : "Google"}：{RESEARCH_LABELS[status] || status}</div>}
    <Button readOnlySafe type="link" size="small" onClick={() => { setLatest(undefined); setError(undefined); setOpen(true); }}>查看依据／AI 核验</Button>
    <Modal title={`${lead.name} · 官网与经营类型`} open={open} onCancel={() => { if (!busy) setOpen(false); }} width={760} footer={<Space><Button readOnlySafe disabled={busy} onClick={() => setOpen(false)}>关闭</Button><Button aria-label="AI 核验／重试" type="primary" loading={busy} onClick={async () => { setBusy(true); setError(undefined); try { const result = await api<ResearchLead>(`/api/leads/${lead.id}/website-review`, { method: "POST" }); setLatest(result); onChanged(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }}>AI 核验／重试</Button></Space>}>
      <Alert type="info" showIcon message="先读取已有官网，身份核验后识别经营类型；缺少可靠官网时按设置查询 Google。AI 依据官网原文，不改渠道准入和内容审批。" style={{ marginBottom: 16 }} />
      {error && <Alert type="error" message={error} style={{ marginBottom: 12 }} />}
      <Descriptions column={1} items={[
        { key: "identity", label: "官网身份", children: <div style={{ width: "100%" }}>{identity?.status && <Tag>{RESEARCH_LABELS[identity.status]}</Tag>}{evidence(identity)}</div> },
        { key: "type", label: "经营类型", children: <div style={{ width: "100%" }}><b>{TYPES[operation?.category || ""] || "待识别"}</b><p>{operation?.services?.map((s) => SERVICES[s] || s).join(" / ")}</p>{evidence(operation)}</div> },
        { key: "google", label: "Google 补充", children: google ? <>{RESEARCH_LABELS[google.status || ""] || "未查询"} · {google.reason || "历史记录未保存判断原因，可用 AI 重试"}</> : "未查询；已有官网可独立核验" },
      ]} />
    </Modal>
  </>;
}
