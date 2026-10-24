"use client";
import { UserIdentity } from "@/components/UserAvatar";
import LeadAssignment, { AssignmentHistory } from "@/components/LeadAssignment";
import { issueLabel, menuJourney } from "@/lib/menu-journey";
import WebsiteReview from "@/components/WebsiteReview";
import PrepareOutreach from "@/components/PrepareOutreach";
import Link from "next/link";
import { leadNextAction, ListSummary } from "@/lib/lead-list";
import { PROGRESS, Progress, safeReturnTo, taskLink } from "@/lib/communication";
import Button from "@/components/AccessButton";
import { ConfigProvider, Alert, Collapse, Card, Col, Descriptions, Form, Input, InputNumber, Modal, Popconfirm, Popover, Row, Select, Space, Table, Tabs, Tag, Typography, Upload, message } from "antd";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useOperator } from "@/lib/auth";
import { api, json } from "@/lib/api";
import { channelLabel, approvalText, label } from "@/lib/format";
import { SCREEN_ZH, ScreenTag } from "@/components/ui";
import WebsiteSearch from "@/components/WebsiteSearch";
import AutoResearch from "@/components/AutoResearch";
import WebsiteMenus from "@/components/WebsiteMenus";
import MapsMenu from "@/components/MapsMenu";
import GooglePlaces from "@/components/GooglePlaces";

import ContactReviewActions from "@/components/ContactReviewActions";
import ContactAssessmentView from "@/components/ContactAssessment";
import { AutoAdmission, ContactAssessment } from "@/lib/contact-ranking";

type Lead = { communication_progress?: Progress; list_summary?: ListSummary; contact_count?: number; assigned_to?: string | null; operating_type?: { category: string; reason: string; citations: { quote: string }[] }; google_enrichment?: { status: string; error?: string }; verified_websites?: { url: string }[]; website_history?: { url: string; source?: string }[]; id: string; name: string; source_key: string; address: string | null; postcode: string | null; website: string | null; website_source: string | null; screening_class: string; screening_reason: string | null };
type Asset = { id: string; kind: string; source_url: string | null; original_filename: string | null; fetch_status: string; fetch_error: string | null; storage_path: string | null; sha256: string | null };
type Item = { name: string; price_text: string; deleted?: boolean; evidence: Record<string, unknown> };
type Issue = { issue_code: string; fact: string; severity: string; confirmed: boolean | null; confirmed_by: string | null; note: string | null; deleted?: boolean; evidence: Record<string, unknown> };
type Candidates = { pdf_links?: string[]; image_candidates?: { src: string; alt: string }[]; iframes?: string[] };
type Analysis = { id: string; version: number; parent_version: number | null; status: string; engine: string; engine_version: string | null; review_state: string | null; items: Item[] | null; issues: Issue[] | null; measurements: (Record<string, unknown> & Candidates) | null; error: string | null };
type Elig = { auto_admission?: AutoAdmission | null; recommendation?: ContactAssessment | null; id: string; channel: string; contact_ref: string | null; contact_source: string | null; contact_usable: string; eligibility: string };
type ContactCandidate = { assessment?: ContactAssessment; evidence?: { page_url: string; text: string }[]; kind: string; channel: string; value: string; sources: { type: string; ref: string }[]; personal: boolean; mobile: boolean; recorded: boolean; eligibility: string | null; suppressed: boolean };
type ContactLookup = { ai?: { status: string; reason: string }; candidates: ContactCandidate[]; notice: string; website: { url: string; pages: { url: string; ok: boolean; error: string | null }[] } | null };
const CONTACT_KIND: Record<string, string> = { email: "邮箱", phone: "电话", whatsapp: "WhatsApp", instagram: "Instagram", facebook: "Facebook", tiktok: "TikTok", x: "X", linkedin: "LinkedIn", youtube: "YouTube", contact_form: "联系表单" };
const contactKey = (c: ContactCandidate) => `${c.kind}|${c.value}`;
const contactHref = (channel: string, v: string) => (v.startsWith("http") ? v : channel === "email" ? `mailto:${v}` : channel === "phone" ? `tel:${v}` : channel === "whatsapp" ? `https://wa.me/${v.replace("+", "")}` : undefined);
type Content = { id: string; kind: string; version: number; status: string; approval_valid: boolean; approval_invalid_reason: string | null; body_text: string | null; html_url: string | null; png_url: string | null; spec: Record<string, unknown> | null };

const formatEvidence = (value: Record<string, unknown>) => Object.entries(value || {}).filter(([key]) => !["file", "sha256"].includes(key)).map(([key, v]) => `${({ page: "页码", line: "行", region: "位置", text: "原文", quote: "原文", bbox: "区域" } as Record<string, string>)[key] || key}：${typeof v === "object" ? JSON.stringify(v) : String(v)}`).join("；") || "位置待补充";
const SCREENING = ["unchecked", "candidate", "unknown", "excluded_cafe", "excluded_chain", "excluded_canteen", "excluded_community", "excluded_institution", "excluded_pub", "excluded_closed", "excluded_other"];

export default function LeadDetail() {
  const { me } = useOperator();
  const router = useRouter();
  const [tab, setTab] = useState("sales");
  const [selectedMenu, setSelectedMenu] = useState<string>();
  const [sectionErrors, setSectionErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [websiteConflict, setWebsiteConflict] = useState(false);
  const generation = useRef(0);
  const [manualContactOpen, setManualContactOpen] = useState(false);
  const [manualContactBusy, setManualContactBusy] = useState(false);
  const [manualContactForm] = Form.useForm();
  const manualChannel = Form.useWatch("channel", manualContactForm);
  const [contactFilter, setContactFilter] = useState(false);
  const [composerContact, setComposerContact] = useState<{ id: string; channel: string; request: number }>();
  const { id } = useParams<{ id: string }>();
  const [analysing, setAnalysing] = useState<string | null>(null);
  const [ingesting, setIngesting] = useState(false);
  const [pendingReview, setPendingReview] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string>();
  const [back, setBack] = useState("/leads");
  useEffect(() => { setBack(safeReturnTo(new URLSearchParams(window.location.search).get("returnTo") || "/leads")); }, [id]);
  const [lead, setLead] = useState<Lead | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [analyses, setAnalyses] = useState<Record<string, Analysis[]>>({});
  const [content, setContent] = useState<Content[]>([]);
  const [form] = Form.useForm();
  const [eligs, setEligs] = useState<Elig[]>([]);
  const [contactOpen, setContactOpen] = useState(false);
  const [contactLoading, setContactLoading] = useState(false);
  const [showAllContacts, setShowAllContacts] = useState(false);
  const [contactLookup, setContactLookup] = useState<ContactLookup | null>(null);
  const [contactPicked, setContactPicked] = useState<string[]>([]);
  const err = (e: Error) => message.error(e.message);
  const reload = useCallback(async () => {
    const ticket = ++generation.current;
    setLoading(true);
    const jobs = [
      api<Lead>(`/api/leads/${id}`).then((l) => { if (ticket !== generation.current) return; setLead(l); if (form.isFieldTouched("website") && form.getFieldValue("website") !== l.website) setWebsiteConflict(true); else form.setFields([{ name: "website", value: l.website, touched: false }]); if (!form.isFieldTouched("screening_class")) form.setFields([{ name: "screening_class", value: l.screening_class, touched: false }]); if (!form.isFieldTouched("screening_reason")) form.setFields([{ name: "screening_reason", value: l.screening_reason, touched: false }]); }),
      api<{ assets: Asset[]; analyses: Record<string, Analysis[]> }>(`/api/leads/${id}/menu-workspace`).then((m) => { if (ticket !== generation.current) return; setAssets(m.assets); setAnalyses(m.analyses); }),
      api<Content[]>(`/api/leads/${id}/content`).then((c) => { if (ticket === generation.current) setContent(c); }),
      api<Elig[]>(`/api/leads/${id}/eligibility`).then((c) => { if (ticket === generation.current) setEligs(c); }),
    ];
    const results = await Promise.allSettled(jobs);
    if (ticket !== generation.current) return;
    const names = ["基本资料", "菜单资料", "文案", "联系方式"];
    setSectionErrors(Object.fromEntries(results.flatMap((r, i) => r.status === "rejected" ? [[names[i], r.reason?.message || "读取失败"]] : [])));
    setLoading(false);
  }, [id, form]);
  useEffect(() => { setLead(null); setTab("sales"); form.resetFields(); setWebsiteConflict(false); setSelectedMenu(undefined); setComposerContact(undefined); void reload(); return () => { generation.current += 1; }; }, [reload, form]);
  useEffect(() => {
    if (!pendingReview || tab !== "menus") return;
    const target = document.getElementById(`menu-review-${pendingReview}`);
    if (target) { target.scrollIntoView({ behavior: "smooth", block: "start" }); setPendingReview(null); }
  }, [pendingReview, analyses, tab]);
  useEffect(() => { setContactLookup(null); setContactPicked([]); setContactOpen(false); }, [id, lead?.website]);
  if (!lead) return <Card loading={loading}>{!loading && <Alert type="error" showIcon message={sectionErrors["基本资料"] || "无法读取门店资料"} action={<Button readOnlySafe onClick={() => void reload()}>重试加载</Button>} />}</Card>;

  // 显式 AI 查找会保存证据并评估既有渠道准入；新候选勾选记录后按缓存证据再评估。
  const searchContacts = (showResults = true, refresh = false) => {
    if (showResults && !refresh && contactLookup) { setContactOpen(true); return; }
    if (showResults) setContactOpen(true);
    setContactLoading(true);
    setShowAllContacts(false);
    setContactPicked([]);
    setContactLookup(null);
    api<ContactLookup>(`/api/leads/${id}/contact-review`, { method: "POST" })
      .then((r) => { setContactLookup(r); setContactPicked(r.candidates.filter((c) => c.assessment?.recommendation === "recommended" && !c.recorded && !c.suppressed).map(contactKey)); if (!showResults) { const count = r.candidates.filter((c) => c.assessment?.recommendation === "recommended").length; message.info(r.ai?.status === "completed" ? `AI 核验完成，优先推荐 ${count} 项；待确认项可在当前行人工确认` : r.ai?.reason || "本次核验未完成，可重试"); } return reload(); })
      .catch(err)
      .finally(() => setContactLoading(false));
  };
  const runAutoAdmission = async () => {
    setContactLookup(null); setContactPicked([]);
    setContactLoading(true);
    try {
      const result = await api<{ summary: { allowed: number; blocked: number; unknown: number; manual_preserved: number } }>(`/api/leads/${id}/auto-admission?refresh=false`, { method: "POST" });
      message.info(`自动允许 ${result.summary.allowed} 项，暂不准入 ${result.summary.blocked} 项，待补证据 ${result.summary.unknown} 项；保留人工结果 ${result.summary.manual_preserved} 项`);
      await reload();
    } catch (e) { err(e as Error); } finally { setContactLoading(false); }
  };
  const recordContacts = () => {
    const items = (contactLookup?.candidates ?? []).filter((c) => contactPicked.includes(contactKey(c)) && !c.recorded)
      .map((c) => ({ channel: c.channel, contact_ref: c.value, contact_source: c.sources.map((s) => (s.type === "website" ? `官网 ${s.ref}` : s.ref)).join("；").slice(0, 256) }));
    if (!items.length) return;
    api<{ created: number; skipped: number }>(`/api/leads/${id}/contacts`, json({ items }))
      .then((r) => { message.success(`已记录 ${r.created} 项${r.skipped ? `，跳过已存在 ${r.skipped} 项` : ""}`); setContactOpen(false); setContactLookup(null); reload(); })
      .catch(err);
  };

  const latest = (aid: string) => analyses[aid]?.[analyses[aid].length - 1];
  const correct = (a: Analysis, corrections: { field_path: string; new_value: unknown; reason?: string }[]) =>
    api(`/api/analyses/${a.id}`, json({ corrections }, "PATCH")).then(reload).catch(err);
  const reviewedAnalyses = Object.values(analyses).flatMap((list) => list.filter((a) => ["succeeded", "needs_review"].includes(a.status) && a.review_state === "reviewed" && a.id === list[list.length - 1]?.id));
  const journey = menuJourney(assets, analyses);
  const scrollTo = (target: string) => document.getElementById(target)?.scrollIntoView({ behavior: "smooth", block: "start" });
  const analyse = async (assetId: string, force = false) => {
    setSelectedMenu(assetId); setAnalysing(assetId); setActionError(undefined);
    try { const result = await api<Analysis>(`/api/assets/${assetId}/analyses?engine=auto${force ? "&force=true" : ""}`, { method: "POST" }); await reload(); if (result.status === "failed") setActionError(result.error || "分析未完成，可重试；已有资料保留"); else { setPendingReview(assetId); } }
    catch (e) { setActionError((e as Error).message); }
    finally { setAnalysing(null); }
  };
  const ingest = async (request: Promise<Pick<Asset, "id" | "fetch_status" | "fetch_error">>) => {
    setTab("menus"); setIngesting(true); setActionError(undefined);
    try { const asset = await request; await reload(); if (asset.fetch_status === "fetched") await analyse(asset.id); else setActionError(asset.fetch_error || "菜单获取未完成，可以重试；已有资料保留"); }
    catch (e) { setActionError((e as Error).message); }
    finally { setIngesting(false); }
  };
  const action = leadNextAction({ ...lead, contact_count: sectionErrors["联系方式"] ? (lead.contact_count || eligs.length) : eligs.length });
  const openPrepare = () => { setTab("sales"); setTimeout(() => scrollTo("sales-composer"), 50); };
  const nextStep = () => { if (action.target === "tasks") router.push(taskLink({ lead: id, task: lead.communication_progress?.task_id, returnTo: back })); else if (action.target === "contacts") { setTab("sales"); setTimeout(() => scrollTo("customer-contacts"), 50); } else if (action.target === "detail") { setTab("menus"); setSelectedMenu(journey.assetId); } else openPrepare(); };
  const progress = lead.communication_progress?.status || "not_started";
  const selectedAsset = assets.find((a) => a.id === selectedMenu) || assets.find((a) => a.id === journey.assetId) || assets[0];
  const selectedReviewed = reviewedAnalyses.find((an) => an.id === (selectedAsset && latest(selectedAsset.id)?.id));

  return (
    <ConfigProvider><div>
      <header className="lead-workspace-header">
        <div className="lead-header-top"><Link href={back}>← 返回名单</Link><Space size={8}><Tag>{PROGRESS[progress] || "未准备"}</Tag><ScreenTag value={lead.screening_class} reason={lead.screening_reason} /></Space></div>
        <div className="lead-header-main"><div className="lead-identity"><h1>{lead.name}</h1><Typography.Text type="secondary">{lead.address || "地址未登记"}{lead.postcode ? ` · ${lead.postcode}` : ""}</Typography.Text><div className="lead-owner">负责人：{<UserIdentity username={lead.assigned_to} />}<Popover trigger="click" placement="bottomLeft" content={<Space direction="vertical"><LeadAssignment leadIds={[id]} onChanged={() => void reload()} /><AssignmentHistory leadId={id} /></Space>}><Button readOnlySafe size="small" type="text">管理 ···</Button></Popover></div></div><Button readOnlySafe={action.target !== "prepare"} type="primary" onClick={nextStep}>{action.text}</Button></div>
      </header>
      {Object.keys(sectionErrors).length > 0 && <Alert type="warning" showIcon message="部分资料未能加载，已读取的结果仍可使用" description={Object.entries(sectionErrors).map(([name, error]) => <div key={name}>{name}：{error}</div>)} action={<Button readOnlySafe onClick={() => void reload()}>重试加载</Button>} style={{ marginBottom: 16 }} />}
      {actionError && <Alert type="error" showIcon message={actionError} style={{ marginBottom: 16 }} />}
      <Tabs className="lead-workspace-tabs" activeKey={tab} onChange={setTab} items={[
        { key: "sales", label: "销售准备", forceRender: true, children: <div className="lead-sales-grid"><Card id="customer-contacts" size="small" title={`联系方式${eligs.length ? ` · ${eligs.length}` : ""}`} extra={<Button size="small" onClick={() => { manualContactForm.resetFields(); setManualContactOpen(true); }}>手动添加</Button>}>
        {!eligs.length ? <div className="lead-contact-empty"><div className="lead-empty-icon">＠</div><Typography.Title level={5}>先找到合适的联系人</Typography.Title><Typography.Paragraph type="secondary">从官网查找邮箱、电话和社媒，也可以添加你已知的联系方式。</Typography.Paragraph><Button type="primary" loading={contactLoading} onClick={() => searchContacts()}>查找联系方式</Button>{!lead.website && <Button type="link" onClick={() => setTab("sources")}>补充官网</Button>}</div> : <>
          <div className="lead-contact-toolbar"><Button size="small" loading={contactLoading} onClick={() => searchContacts()}>查找联系方式</Button><Popover trigger="click" content={<Button loading={contactLoading} onClick={runAutoAdmission}>重新评估准入</Button>}><Button size="small" readOnlySafe>更多 ···</Button></Popover></div>
          {eligs.some((e) => e.recommendation?.recommendation === "recommended") && <Button readOnlySafe size="small" type="link" onClick={() => setContactFilter(!contactFilter)}>{contactFilter ? "仅看推荐" : `查看全部（${eligs.length}）`}</Button>}
          <div className="lead-contact-list">{(contactFilter || !eligs.some((e) => e.recommendation?.recommendation === "recommended") ? eligs : eligs.filter((e) => e.recommendation?.recommendation === "recommended")).map((e) => <article className={`lead-contact-item${composerContact?.id === e.id ? " is-selected" : ""}`} key={e.id}>
            <Space size={4} wrap><strong>{channelLabel(e.channel, e.contact_ref)}</strong><Tag>{({ recommended: "优先推荐", backup: "备选", not_recommended: "不推荐", review: "待确认" } as Record<string, string>)[e.recommendation?.recommendation || "review"]}</Tag><Tag color={e.eligibility === "allowed" ? "green" : "orange"}>{e.eligibility === "allowed" ? "允许触达" : e.eligibility === "blocked" ? "暂不准入" : "待补准入"}</Tag></Space>
            <div className="lead-contact-value">{e.contact_ref && contactHref(e.channel, e.contact_ref) ? <a href={contactHref(e.channel, e.contact_ref)} target="_blank" rel="noreferrer">{e.contact_ref}</a> : e.contact_ref || "未填写"}</div>
            <div className="lead-contact-actions"><Button size="small" disabled={progress === "suppressed"} onClick={() => { setComposerContact({ id: e.id, channel: e.channel, request: Date.now() }); openPrepare(); }}>{composerContact?.id === e.id ? "已选用" : "用于本次触达"}</Button><Popover trigger="click" placement="bottomLeft" overlayStyle={{ maxWidth: 460 }} content={<><p>来源：{e.contact_source || "尚未记录"}</p><p>可达性：{e.contact_usable === "unknown" ? "未验证" : label(e.contact_usable)}</p><ContactAssessmentView value={e.recommendation} />{e.auto_admission && <p>{e.auto_admission.reason}</p>}<ContactReviewActions leadId={id} row={e} website={lead.website} busy={contactLoading} onAI={() => searchContacts(false)} onAdmission={runAutoAdmission} onChanged={async () => { setContactLookup(null); setContactPicked([]); await reload(); }} /></>}><Button size="small" type="link" readOnlySafe>核验与设置</Button></Popover></div>
          </article>)}</div>
        </>}
      </Card>
      <div id="sales-composer"><PrepareOutreach embedded onViewMenus={() => setTab("menus")} open={true} leadIds={[id]} returnTo={back} onClose={() => {}} onChanged={() => void reload()} initialChannel={composerContact?.channel || "email"} initialContactId={composerContact?.id} preferredAnalysisId={selectedReviewed?.id} selectionRequest={composerContact?.request} dataRevision={`${JSON.stringify(eligs)}:${content.map((c) => c.id).join(",")}:${Object.values(analyses).flat().map((a) => `${a.id}:${a.review_state}`).join(",")}`} /></div></div> },
        { key: "menus", label: "菜单资料", children: <><Alert type="info" showIcon message={journey.message} action={<Button onClick={openPrepare}>转到销售准备</Button>} style={{ marginBottom: 16 }} />      <Card id="menu-files" size="small" title="菜单资料" style={{ marginBottom: 16 }} extra={
        <Space wrap>
          <MapsMenu key={`maps-${id}`} id={id} onAdded={reload} />
          <WebsiteMenus id={id} website={lead.website} onAdded={reload} onIngest={ingest} />
          <Form layout="inline" onFinish={(v) => ingest(api<Asset>(`/api/leads/${id}/assets`, json(v)))}>
            <Form.Item name="url" rules={[{ required: true }]}><Input placeholder="菜单文件链接" style={{ width: 320 }} /></Form.Item>
            <Button htmlType="submit" loading={!!analysing || ingesting}>获取并分析</Button>
          </Form>
          <Upload disabled={ingesting || !!analysing || me?.role === "viewer"} showUploadList={false} customRequest={({ file }) => { const fd = new FormData(); fd.append("file", file as File); ingest(api<Asset>(`/api/leads/${id}/assets/upload`, { method: "POST", body: fd })); }}>
            <Button loading={!!analysing || ingesting}>上传并分析</Button>
          </Upload>
        </Space>
      }>
        <Table<Asset> rowKey="id" size="small" pagination={false} dataSource={assets} columns={[
          { title: "类型", dataIndex: "kind", width: 80 },
          { title: "来源", ellipsis: true, render: (_, a) => a.source_url ?? a.original_filename ?? "-" },
          { title: "状态", width: 120, render: (_, a) => <>{label(a.fetch_status)} {a.fetch_error && <Typography.Text type="danger">{a.fetch_error}</Typography.Text>}</> },
          { title: "文件", width: 70, render: (_, a) => a.storage_path ? <a href={`/api/files/${a.storage_path}`} target="_blank" rel="noreferrer">打开</a> : "-" },
          { title: "操作", width: 330, render: (_, a) => <Space>
            {a.source_url && a.fetch_status !== "fetched" && <Button size="small" onClick={() => api(`/api/assets/${a.id}/retry`, { method: "POST" }).then(reload).catch(err)}>重试</Button>}
            {a.fetch_status === "fetched" && <><Button readOnlySafe={!!analyses[a.id]?.length} size="small" type="primary" loading={analysing === a.id} disabled={ingesting || (!!analysing && analysing !== a.id)} onClick={() => { setSelectedMenu(a.id); if (analyses[a.id]?.length) setPendingReview(a.id); else void analyse(a.id); }}>{analyses[a.id]?.length ? "查看分析" : "开始分析"}</Button>{analyses[a.id]?.length > 0 && <Popconfirm title="重新生成分析版本？" description="已有版本保留，新版本需重新核对；依赖旧分析的文案可能需重新审批。" onConfirm={() => analyse(a.id, true)}><Button size="small" disabled={!!analysing || ingesting}>重新分析</Button></Popconfirm>}</>}
            <Button readOnlySafe size="small" onClick={() => setSelectedMenu(a.id)}>选用此菜单</Button>{latest(a.id) && <Tag>v{latest(a.id).version} {label(latest(a.id).status)}{latest(a.id).review_state === "reviewed" ? " · 已核对" : ""}</Tag>}
          </Space> },
        ]} />
      </Card>

      {!!assets.length && <Select aria-label="当前菜单" value={selectedAsset?.id} onChange={setSelectedMenu} style={{ width: "100%", marginBottom: 16 }} options={assets.map((a, i) => ({ value: a.id, label: `${i + 1}. ${a.original_filename || a.source_url || "菜单文件"}${latest(a.id)?.review_state === "reviewed" ? " · 已核对" : ""}` }))} />}
      {assets.filter((a) => a.id === selectedAsset?.id && latest(a.id)).map((a) => {
        const an = latest(a.id)!;
        const items = an.items ?? [];
        const issues = an.issues ?? [];
        const editable = an.review_state !== "reviewed" && me?.role !== "viewer";
        return (
          <Card id={`menu-review-${a.id}`} key={a.id} size="small" style={{ marginBottom: 16 }} title={`核对菜单事实 · ${a.kind} · 分析 v${an.version}（${label(an.status)}）`} extra={
            editable && ["succeeded", "needs_review"].includes(an.status) && <Button type="primary" onClick={() => api(`/api/analyses/${an.id}/review`, { method: "POST" }).then(reload).catch(err)}>完成事实核对</Button>
          }>
            {an.error && <Typography.Paragraph type="warning">{an.error}</Typography.Paragraph>}
            {(an.measurements?.pdf_links?.length || an.measurements?.image_candidates?.length) ? (
              <Card type="inner" size="small" title="页面里发现的候选菜单文件（一键接入后再分析；图片可能是菜品照片，请先打开确认）" style={{ marginBottom: 8 }}>
                {(an.measurements?.pdf_links ?? []).map((u) => (
                  <div key={u}><a href={u} target="_blank" rel="noreferrer">{u}</a> <Button size="small" onClick={() => ingest(api<Asset>(`/api/leads/${id}/assets`, json({ url: u })))}>接入并分析 PDF</Button></div>
                ))}
                {(an.measurements?.image_candidates ?? []).map((c) => (
                  <div key={c.src}><a href={c.src} target="_blank" rel="noreferrer">{c.src.slice(-60)}</a> {c.alt && <Typography.Text type="secondary">{c.alt}</Typography.Text>} <Button size="small" onClick={() => ingest(api<Asset>(`/api/leads/${id}/assets`, json({ url: c.src })))}>接入并分析图片</Button></div>
                ))}
              </Card>
            ) : null}
            <Typography.Paragraph type="secondary">当前核对的菜单用于提供文案事实依据；仅引用已确认属实的问题。可随时回到销售准备询问菜单或负责人。</Typography.Paragraph>
            <Row gutter={20}><Col xs={24} xl={12}><Typography.Title level={5}>原文件</Typography.Title>{a.storage_path ? (a.kind === "image" ? <img alt="菜单原图" src={`/api/files/${a.storage_path}`} style={{ maxWidth: "100%" }} /> : <iframe title="菜单原文件" src={`/api/files/${a.storage_path}`} style={{ width: "100%", height: 680, border: "1px solid #ddd" }} />) : <Alert type="info" message="原文件暂不可用" />}</Col><Col xs={24} xl={12}>
            <Tabs defaultActiveKey="issues" items={[
              { key: "items", label: `菜品与价格（${items.length}）`, children: (
                <Table<Item> rowKey={(_, i) => String(i)} size="small" pagination={false} dataSource={items} columns={[
                  { title: "#", render: (_, __, i) => i },
                  { title: "菜名", dataIndex: "name", render: (v, r, i) => editable ? <Typography.Text editable={{ onChange: (nv) => nv !== v && correct(an, [{ field_path: `items[${i}].name`, new_value: nv }]) }} delete={r.deleted}>{v}</Typography.Text> : v },
                  { title: "价格", dataIndex: "price_text", render: (v, _, i) => editable ? <Typography.Text editable={{ onChange: (nv) => nv !== v && correct(an, [{ field_path: `items[${i}].price_text`, new_value: nv }]) }}>{v}</Typography.Text> : v },
                  { title: "位置", render: (_, r) => formatEvidence(r.evidence) },
                  { title: "", render: (_, r, i) => editable && !r.deleted && <Popconfirm title="标记为无效条目？" onConfirm={() => correct(an, [{ field_path: `items[${i}].deleted`, new_value: true }])}><a>删除</a></Popconfirm> },
                ]} />
              ) },
              { key: "issues", label: `问题候选（${issues.length}）`, children: (
                <Table<Issue> rowKey={(_, i) => String(i)} size="small" pagination={false} dataSource={issues} columns={[
                  { title: "待核对问题", dataIndex: "issue_code", render: (v, r) => <Tag title={v} color={r.severity === "blocking" ? "red" : r.severity === "candidate" ? "gold" : "blue"}>{issueLabel(v)}</Tag> },
                  { title: "事实（测量值）", dataIndex: "fact", render: (v, r) => <>{v}{(r as Issue & { fact_zh?: string | null }).fact_zh && <div><Typography.Text type="secondary">{(r as Issue & { fact_zh?: string | null }).fact_zh}</Typography.Text></div>}</> },
                  { title: "证据", render: (_, r) => formatEvidence(r.evidence) },
                  { title: "人工确认", render: (_, r, i) => <Select aria-label={`问题 ${i + 1} 核对结果`} value={r.confirmed === true ? "confirmed" : r.confirmed === false ? "rejected" : "pending"} disabled={!editable} style={{ width: 110 }} options={[{ value: "confirmed", label: "属实" }, { value: "rejected", label: "不属实" }, { value: "pending", label: "待核对" }]} onChange={(v) => correct(an, [{ field_path: `issues[${i}].confirmed`, new_value: v === "confirmed" ? true : v === "rejected" ? false : null }])} /> },
                  { title: "备注", dataIndex: "note", render: (v, _, i) => editable ? <Typography.Text editable={{ onChange: (nv) => correct(an, [{ field_path: `issues[${i}].note`, new_value: nv }]) }}>{v ?? ""}</Typography.Text> : v },
                ]} />
              ) },
              { key: "add", label: "补充遗漏问题", children: editable ? (
                <Form layout="inline" onFinish={(v) => correct(an, [{ field_path: "issues[new]", new_value: { issue_code: v.issue_code, fact: v.fact, evidence: { region: v.region, file: a.storage_path }, severity: "candidate" }, reason: "人工目视" }])}>
                  <Form.Item name="issue_code" rules={[{ required: true }]}><Select placeholder="问题代码" style={{ width: 200 }} options={["text_overlap", "missing_spaces", "low_resolution", "price_format_mixed_decimals", "price_format_mixed_symbol", "small_text", "typo", "other"].map((c) => ({ value: c, label: issueLabel(c) }))} /></Form.Item>
                  <Form.Item name="fact" rules={[{ required: true }]}><Input placeholder="可核对的事实（英文，用于对外文案）" style={{ width: 360 }} /></Form.Item>
                  <Form.Item name="region" rules={[{ required: true }]}><Input placeholder="位置（如：中栏 Signature 第 3 条）" style={{ width: 240 }} /></Form.Item>
                  <Button htmlType="submit">新增问题（记为人工确认）</Button>
                </Form>
              ) : <Typography.Text type="secondary">已审核的版本不能再新增。</Typography.Text> },
            ]} /></Col></Row>
            <Collapse ghost size="small" items={[{ key: "analysis-details", label: `分析详情与历史版本（${analyses[a.id].length}）`, children: <><pre style={{ fontSize: 12, whiteSpace: "pre-wrap" }}>{JSON.stringify(an.measurements, null, 1)}</pre>{analyses[a.id].map((x) => <div key={x.id}>v{x.version} · {x.engine} · {label(x.status)} · {x.review_state === "reviewed" ? "事实已核对" : "未核对"}</div>)}</> }]} />
          </Card>
        );
      })}

      <Collapse style={{ marginBottom: 16 }} items={[{ key: "optional-materials", label: "可选样稿与历史文案（首次触达不必制作样稿）", children: <Card id="optional-materials" size="small" title="可选样稿与历史内容" extra={!!selectedReviewed && (
        <Space>
          <Form layout="inline" onFinish={(v) => api(`/api/leads/${id}/content`, json({ kind: "sample_partial", analysis_id: selectedReviewed!.id, section: v.section, item_indexes: v.n ? Array.from({ length: v.n }, (_, i) => i) : undefined })).then(reload).catch(err)}>
            <Form.Item name="section" initialValue="Sample section"><Input style={{ width: 160 }} /></Form.Item>
            <Form.Item name="n" label="前 N 项"><InputNumber min={1} max={30} /></Form.Item>
            <Button htmlType="submit">生成样稿</Button>
          </Form>

        </Space>
      )}>
        {!selectedReviewed && <Typography.Text type="secondary">核对菜单事实后可按需生成样稿；首次准备触达无需样稿。</Typography.Text>}
        {content.map((c) => (
          <Card key={c.id} type="inner" size="small" style={{ marginTop: 8 }} title={<>{c.kind === "message_short" ? "触达文案" : "局部样稿"} v{c.version} <Tag>{label(c.status)}</Tag> <Typography.Text type={c.approval_valid ? "success" : "warning"}>{approvalText(c.approval_valid, c.approval_invalid_reason)}</Typography.Text></>} extra={
            <Space>
              {c.kind === "message_short" ? <Button size="small" onClick={openPrepare}>在准备触达中编辑与审批</Button> : <><Button size="small" type="primary" disabled={c.approval_valid} onClick={() => api(`/api/content/${c.id}/approve`, json({ decision: "approved" })).then(reload).catch(err)}>审批通过</Button>
              <Button size="small" danger onClick={() => api(`/api/content/${c.id}/approve`, json({ decision: "rejected" })).then(reload).catch(err)}>驳回</Button></>}
            </Space>
          }>
            {c.body_text && <Typography.Paragraph editable={c.kind === "message_short" ? false : { onChange: (t) => t !== c.body_text && api(`/api/content/${c.id}/revise`, json({ body_text: t })).then(reload).catch(err) }} style={{ whiteSpace: "pre-wrap" }}>{c.body_text}</Typography.Paragraph>}
            {c.png_url && <img alt="sample" src={c.png_url} style={{ maxWidth: 375, border: "1px solid #eee" }} />}
            {c.html_url && !c.png_url && <a href={c.html_url} target="_blank" rel="noreferrer">打开 HTML 样稿</a>}
            <Descriptions size="small" column={1} style={{ marginTop: 8 }}>
              <Descriptions.Item label="数据来源">{String(c.spec?.source ?? c.spec?.template ?? "")}</Descriptions.Item>
            </Descriptions>
          </Card>
        ))}
      </Card> }]} />
</> },
        { key: "sources", label: "来源与历史", children: <>      <Card size="small" title="门店资料" style={{ marginBottom: 16 }}>
        {websiteConflict && <Alert type="warning" message="官网已有更新，当前输入尚未保存" description="请选择采用已更新的官网，或明确保留你的输入，避免覆盖新资料。" action={<Space><Button onClick={() => { form.setFields([{ name: "website", value: lead.website, touched: false }]); setWebsiteConflict(false); }}>采用最新官网</Button><Button onClick={() => setWebsiteConflict(false)}>保留我的输入</Button></Space>} style={{ marginBottom: 12 }} />}
        <Form
          form={form}
          disabled={me?.role === "viewer"}
          layout="vertical"
          className="beacon-form-grid"
          initialValues={lead}
          onFinish={(v) => { if (websiteConflict) return; const changes = Object.fromEntries(Object.entries(v).filter(([k, value]) => value !== lead[k as keyof Lead])); if ("website" in changes) changes.expected_website = lead.website; api(`/api/leads/${id}`, json(changes, "PATCH")).then(() => { form.resetFields(); message.success("已保存"); void reload(); }).catch(err); }}
        >
          <Row gutter={16}>
            <Col xs={24} md={9}><Form.Item name="website" label="官网" extra={lead.website_source ? `来源：${lead.website_source}` : undefined}><Input placeholder="https://" /></Form.Item></Col>
            <Col xs={24} md={5}><Form.Item name="screening_class" label="筛选分类"><Select options={SCREENING.map((s) => ({ value: s, label: SCREEN_ZH[s] ?? s }))} /></Form.Item></Col>
            <Col xs={24} md={10}><Form.Item name="screening_reason" label="筛选原因"><Input /></Form.Item></Col>
          </Row>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
            <WebsiteSearch key={id} id={id} name={lead.name} address={lead.address} postcode={lead.postcode} website={lead.website} onConfirmed={(result) => { form.setFields([{ name: "website", value: result.website, touched: false }]); reload().catch(err); }} />
            <Button type="primary" htmlType="submit" disabled={websiteConflict}>保存</Button>
          </div>
        </Form>
      </Card>
<Collapse items={[{ key: "source", label: "数据来源", children: <p>{lead.source_key}</p> }]} style={{ marginBottom: 16 }} />      <Card title="官网与经营类型" style={{ marginBottom: 16 }}>
        <WebsiteReview lead={lead} onChanged={() => reload().catch(err)} />
        {lead.verified_websites?.map((w) => <p key={w.url}>经官网原文验证：<a href={w.url} target="_blank" rel="noreferrer">{w.url}</a></p>)}
        {lead.website_history?.map((w) => <p key={w.url}>历史官网（{w.source ?? "原记录"}）：<a href={w.url} target="_blank" rel="noreferrer">{w.url}</a></p>)}
      </Card>
      <Collapse style={{ marginBottom: 16 }} items={[{ key: "research-tools", label: "补充来源与查询工具", children: <>      <AutoResearch key={`auto-${id}`} id={id} onFinished={async () => { setContactLookup(null); setContactPicked([]); await reload(); }} />
      <GooglePlaces key={`${id}:${JSON.stringify(lead.google_enrichment)}`} id={id} name={lead.name} address={lead.address} postcode={lead.postcode} website={lead.website} onWebsiteChanged={async () => { setContactLookup(null); setContactPicked([]); await reload(); }} /></> }]} />



</> },
      ]} />
      <Modal title="手动添加联系方式" open={manualContactOpen} onCancel={() => { if (!manualContactBusy) setManualContactOpen(false); }} onOk={() => manualContactForm.submit()} okText="保存联系方式" confirmLoading={manualContactBusy}>
        <Form name="manual-contact" form={manualContactForm} layout="vertical" initialValues={{ channel: "email" }} disabled={manualContactBusy} onFinish={async (values) => { setManualContactBusy(true); try { await api(`/api/leads/${id}/contacts`, json({ items: [{ channel: values.channel, contact_ref: values.contact_ref.trim(), contact_source: values.contact_source.trim() }] })); setManualContactOpen(false); setContactLookup(null); setContactFilter(true); await reload(); message.success("联系方式已保存，可继续核验和准备触达"); } catch (e) { err(e as Error); } finally { setManualContactBusy(false); } }}>
          <Form.Item name="channel" label="渠道" rules={[{ required: true }]}><Select options={Object.entries(CONTACT_KIND).filter(([key]) => !["x", "youtube"].includes(key)).map(([value, label]) => ({ value, label })).concat([{ value: "other_social", label: "X／YouTube／其他平台主页" }])} /></Form.Item>
          <Form.Item name="contact_ref" label="联系方式" rules={[{ required: true, whitespace: true }, ...(manualChannel === "email" ? [{ type: "email" as const, message: "请输入有效的邮箱地址" }] : [])]}><Input placeholder={manualChannel === "email" ? "hello@example.com" : "电话号码或平台主页链接"} /></Form.Item>
          <Form.Item name="contact_source" label="来源" rules={[{ required: true, whitespace: true }]}><Input placeholder="例如官网联系页 URL、客户提供或名片" /></Form.Item>
          <Typography.Text type="secondary">保存后会列入联系方式；核验与渠道准入结果在当前行查看。</Typography.Text>
        </Form>
      </Modal>
      <Modal title="联系方式 · AI 推荐" open={contactOpen} onCancel={() => setContactOpen(false)} width={1180} okText={`记录所选 ${contactPicked.length} 项`} okButtonProps={{ disabled: !contactPicked.length || contactLoading }} onOk={recordContacts} cancelText="关闭">
        <Button loading={contactLoading} onClick={() => searchContacts(true, true)} style={{ marginBottom: 12 }}>重新查找并核验联系方式</Button>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>{contactLookup?.notice ?? "候选仅供人工核对。"}</Typography.Paragraph>
        {contactLookup && !contactLoading && (() => {
          const web = contactLookup.website;
          const okPages = web?.pages.filter((p) => p.ok).length ?? 0;
          return <Typography.Paragraph style={{ marginBottom: 8 }} type={web && !okPages ? "warning" : undefined}>官网：{web ? (okPages ? `读取 ${okPages} 个页面` : `抓取失败（${web.pages[0]?.error ?? "无页面"}）`) : "未登记"}；共找到 {contactLookup.candidates.length} 项，其中邮箱 {contactLookup.candidates.filter((c) => c.kind === "email").length} 项。勾选后点击“记录所选”才会加入下方渠道表。</Typography.Paragraph>;
        })()}
        {contactLookup?.ai && <Alert type={contactLookup.ai.status === "completed" ? "info" : "warning"} showIcon message={contactLookup.ai.reason} description={`优先推荐 ${contactLookup.candidates.filter((c) => c.assessment?.recommendation === "recommended").length} 项；推荐只表示业务相关，不代表准入允许。`} style={{ marginBottom: 12 }} />}
        {contactLookup && <Button readOnlySafe size="small" style={{ marginBottom: 12 }} onClick={() => setShowAllContacts(!showAllContacts)}>{showAllContacts ? "仅看推荐" : `查看全部候选（${contactLookup.candidates.length}）`}</Button>}
        <Table<ContactCandidate> rowKey={contactKey} size="small" pagination={false} loading={contactLoading} dataSource={(contactLookup?.candidates ?? []).filter((c) => showAllContacts || c.assessment?.recommendation === "recommended")} scroll={{ y: 420 }}
          expandable={{ expandedRowRender: (c) => <div>{(c.assessment?.citations?.length ? c.assessment.citations : c.evidence?.map((e) => ({ quote: e.text, url: e.page_url })) || []).map((q, i) => <blockquote key={i}><p>{q.quote || "链接未提供可读上下文"}</p><a href={q.url} target="_blank" rel="noreferrer">{q.url}</a></blockquote>)}</div> }}
          locale={{ emptyText: showAllContacts ? "没有找到联系方式" : "暂未找到有可靠依据的推荐，可查看全部候选或重新查找" }}
          rowSelection={{ selectedRowKeys: contactPicked, onChange: (keys) => setContactPicked(keys as string[]), getCheckboxProps: (c) => ({ disabled: c.recorded || c.suppressed }) }}
          columns={[
            { title: "类型", width: 100, render: (_, c) => CONTACT_KIND[c.kind] ?? c.kind },
            { title: "联系值", render: (_, c) => contactHref(c.channel, c.value) ? <a href={contactHref(c.channel, c.value)} target="_blank" rel="noreferrer">{c.value}</a> : c.value },
            { title: "AI 归属与用途", width: 300, render: (_, c) => <ContactAssessmentView value={c.assessment} /> },
            { title: "来源", width: 150, render: (_, c) => <Space size={[0, 4]} wrap>{c.sources.map((s) => s.type === "website" ? <Tag key={`${s.type}-${s.ref}`} color="green"><a href={s.ref} target="_blank" rel="noreferrer">官网页面</a></Tag> : <Tag key={s.type} color="blue" title={s.ref}>Overture</Tag>)}</Space> },
            { title: "提示", width: 220, render: (_, c) => <Space size={[0, 4]} wrap>
              {c.personal && <Tag color="orange">可能是个人邮箱</Tag>}
              {c.mobile && <Tag>手机号</Tag>}
              {c.suppressed && <Tag color="red">在抑制名单</Tag>}
              {c.recorded && <Tag color="default">已记录 · 准入{label(c.eligibility)}</Tag>}
            </Space> },
          ]} />
      </Modal>

    </div></ConfigProvider>
  );
}
