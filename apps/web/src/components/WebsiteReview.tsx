"use client";
import { Descriptions, Modal, Typography } from "antd";
import Button from "@/components/AccessButton";
import { useState } from "react";

type Citation = { document_id?: string; quote: string };
type Evidence = { website_retry?: boolean; checked_at?: string; adoption_pending?: boolean; google_status?: string; status?: string; category?: string; reason?: string; website?: string; services?: string[]; citations?: Citation[]; judgment?: { citations: Citation[] }; sources?: { id: string; url: string }[] };
export type ResearchLead = { id: string; name: string; source_sync?: { status?: string; fetched_at?: string; candidates?: { place_id: string; website?: string | null }[] } | null; operating_type?: Evidence | null; website_research?: Evidence | null; google_enrichment?: Evidence | null; website?: string | null; website_source?: string | null; verified_websites?: { url: string; source?: string; verified_at?: string }[]; website_history?: { url: string; source?: string; recorded_at?: string }[] };
const TYPES: Record<string, string> = { restaurant: "餐厅", cafe: "咖啡馆", takeaway: "外卖店", pub: "Pub／酒吧", institution: "机构餐饮", unknown: "待识别" };
export default function WebsiteReview({ lead }: { lead: ResearchLead; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  return <>
    <div>{TYPES[lead.operating_type?.category || ""] || "待识别"}</div>
    <Button readOnlySafe type="link" size="small" onClick={() => setOpen(true)}>查看网站与来源</Button>
    <Modal title={`${lead.name} · 网站与来源`} open={open} onCancel={() => setOpen(false)} footer={<Button readOnlySafe onClick={() => setOpen(false)}>关闭</Button>}>
      <Typography.Paragraph type="secondary">来源网站可直接用于查找联系方式和菜单；需要时可在完善资料中刷新。</Typography.Paragraph>
      <Descriptions column={1} items={[
        {key:"website",label:"当前网站",children:lead.website ? <a href={lead.website} target="_blank" rel="noreferrer">{lead.website}</a> : "未提供"},
        {key:"source",label:"来源",children:lead.website_source || "未记录"},
        {key:"time",label:"最近同步",children:lead.source_sync?.fetched_at ? new Date(lead.source_sync.fetched_at).toLocaleString() : "未记录"},
        {key:"candidates",label:"来源候选",children:lead.source_sync?.candidates?.map(c => c.website && <p key={c.place_id}><a href={c.website} target="_blank" rel="noreferrer">{c.website}</a></p>)},
        {key:"history",label:"历史网站",children:lead.website_history?.map(w => <p key={w.url}><a href={w.url} target="_blank" rel="noreferrer">{w.url}</a> · {w.source || "未记录"}</p>)},
      ]} />
    </Modal>
  </>;
}
