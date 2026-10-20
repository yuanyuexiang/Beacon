"use client";
import { Alert, Descriptions, Modal, Space, Tag, Typography } from "antd";
import Button from "@/components/AccessButton";
import { useState } from "react";
import { api } from "@/lib/api";

type Citation = { document_id?: string; quote: string };
type Evidence = { website_retry?: boolean; checked_at?: string; adoption_pending?: boolean; google_status?: string; status?: string; category?: string; reason?: string; website?: string; services?: string[]; citations?: Citation[]; judgment?: { citations: Citation[] }; sources?: { id: string; url: string }[] };
export type ResearchLead = { id: string; name: string; operating_type?: Evidence | null; website_research?: Evidence | null; google_enrichment?: Evidence | null; website?: string | null; website_source?: string | null; verified_websites?: { url: string; source?: string; verified_at?: string }[]; website_history?: { url: string; source?: string; recorded_at?: string }[] };
export const RESEARCH_LABELS: Record<string, string> = { verified: "已核验", insufficient: "信息不足", retry: "待重试", ai_unavailable: "AI 暂不可用", conflict: "身份冲突，需人工核对", review: "历史待核验", failed: "查询失败，可重试" };
const TYPES: Record<string, string> = { restaurant: "餐厅", cafe: "咖啡馆", takeaway: "外卖店", pub: "Pub／酒吧", institution: "机构餐饮", unknown: "信息不足" };
const SERVICES: Record<string, string> = { dine_in: "堂食", takeaway: "外卖", coffee: "咖啡", food_service: "供应餐食", drinks: "酒水" };

const sourceLabel = (value?: string) => value === "google_places+official_website" ? "Google 发现 · 官网原文核验" : value === "official_website" ? "官网原文核验" : value?.startsWith("overture:") ? "Overture 历史候选" : value || "来源未记录";

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
    <Button readOnlySafe type="link" size="small" onClick={() => { setLatest(undefined); setError(undefined); setOpen(true); }}>查看核验结果</Button>
    <Modal title={`${lead.name} · 官网与经营类型`} open={open} onCancel={() => { if (!busy) setOpen(false); }} width={760} footer={<Space><Button readOnlySafe disabled={busy} onClick={() => setOpen(false)}>关闭</Button><Button aria-label="AI 核验／重试" type="primary" loading={busy} onClick={async () => { setBusy(true); setError(undefined); try { const result = await api<ResearchLead>(`/api/leads/${lead.id}/website-review`, { method: "POST" }); setLatest(result); onChanged(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }}>刷新 AI 核验／重试</Button></Space>}>
      <Alert type="info" showIcon message="按设置优先查询 Google，再以官网原文核验身份与经营类型；近期结果可复用，人工确认的官网保留。AI 不改变渠道准入和内容审批。" style={{ marginBottom: 16 }} />
      {error && <Alert type="error" message={error} style={{ marginBottom: 12 }} />}
      {identity?.adoption_pending && <Alert type="warning" message="发现已核验的新官网候选；当前官网受人工或导入资料保护，未自动替换。可核对后在基本信息中采用。" style={{ marginBottom: 12 }} />}
      <Descriptions column={1} items={[
        { key: "current", label: "当前采用官网", children: <>{current.website || "尚无官网"}<br />{current.website_source || "来源未记录"}</> },
        { key: "target", label: "本次核验网址", children: identity?.website || "历史记录未保存" },
        { key: "checked", label: "最近核验时间", children: identity?.checked_at ? new Date(identity.checked_at).toLocaleString() : "尚未核验" },
        { key: "websites", label: "已核验候选／历史网址", children: <div style={{ width: "100%", overflowWrap: "anywhere" }}>{[...(current.verified_websites || []).map((w) => <p key={`v-${w.url}`}>{w.url} · {sourceLabel(w.source)} · {w.verified_at ? new Date(w.verified_at).toLocaleString() : "时间未记录"}</p>), ...(current.website_history || []).map((w) => <p key={`h-${w.url}`}>{w.url} · {sourceLabel(w.source)} · {w.recorded_at ? new Date(w.recorded_at).toLocaleString() : "历史时间未记录"}</p>)]}</div> },
        { key: "identity", label: "官网身份", children: <div style={{ width: "100%" }}>{identity?.status && <Tag>{RESEARCH_LABELS[identity.status]}</Tag>}{evidence(identity)}</div> },
        { key: "type", label: "经营类型", children: <div style={{ width: "100%" }}><b>{TYPES[operation?.category || ""] || "待识别"}</b><p>{operation?.services?.map((s) => SERVICES[s] || s).join(" / ")}</p>{evidence(operation)}</div> },
        { key: "google", label: "Google 补充", children: google ? <>{google.google_status === "retry" && <Tag color="orange">Google 查询待重试</Tag>}{google.website_retry && <Tag color="orange">官网候选待重试</Tag>}{RESEARCH_LABELS[google.status || ""] || "未查询"} · {google.reason || "历史记录未保存判断原因，可用 AI 重试"}</> : "尚未查询；首次完善将按设置优先查询 Google" },
      ]} />
    </Modal>
  </>;
}
