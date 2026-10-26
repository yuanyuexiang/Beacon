"use client";
import { UserIdentity } from "@/components/UserAvatar";
import { Alert, Button, Card, Col, Collapse, Descriptions, Drawer, Form, Input, Modal, Radio, Row, Select, Space, Steps, Switch, Table, Tag, Typography, Upload, message } from "antd";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import ManualLead from "@/components/ManualLead";
import LeadAssignment from "@/components/LeadAssignment";
import OutreachJourney from "@/components/OutreachJourney";
import WebsiteReview, { ResearchLead } from "@/components/WebsiteReview";
import PrepareOutreach from "@/components/PrepareOutreach";
import { MENU_STATES, ListSummary, leadNextAction, leadPriority } from "@/lib/lead-list";
import { channelLabel } from "@/lib/format";
import { PROGRESS, Progress, taskLink } from "@/lib/communication";
import { useOperator } from "@/lib/auth";
import { api, json } from "@/lib/api";
import { CheckCircleOutlined, CloudDownloadOutlined, GlobalOutlined, ShopOutlined, UserOutlined } from "@ant-design/icons";
import { HeroBand, SCREEN_ZH, ScreenTag, StatCard } from "@/components/ui";
import { label } from "@/lib/format";
import { ListWorkflow, workflowUnfinished, workflowBlocksActions, WORKFLOW_TITLES, workflowSummary, contactFailureLabel, getAllBatchLeads } from "@/lib/list-workflow";

type Batch = { id: string; batch_key: string; country: string; region: string | null; source_name: string; business_type?: string | null; candidate_count: number | null };
type Lead = ResearchLead & { list_summary?: ListSummary | null; assigned_to?: string | null; communication_progress?: Progress; operating_type?: { category: string; reason: string }; google_enrichment?: { status: string }; business_type_id?: number | null; business_type_name?: string | null; inspection_pending?: boolean; id: string; source_key: string; name: string; postcode: string | null; website: string | null; screening_class: string; screening_reason: string | null; contact_count: number };
type Authority = { id: number; name: string; region: string | null; count: number | null; pool_count: number; last_success_at: string | null; type_versions: Record<string, unknown> };
type DeletePreview = { batch_key: string; leads_in_batch: number; leads_deleted: number; leads_kept_other_batches: number; leads_kept_suppressed: number; menu_assets: number; analyses: number; content_pieces: number; contacts: number; tasks: number; tasks_sent: number; events: number; import_runs: number; batch_runs: number; cost_entries: number };

type CreateValues = { batch_key?: string; region?: string; notes?: string; exclude_awaiting?: boolean; business_type_ids?: number[] };
const BUSINESS_TYPES = [{ value: 1, label: "餐厅、咖啡馆、食堂" }, { value: 7844, label: "外卖店、三明治店" }, { value: 7843, label: "酒吧、Pub、夜店" }];
const businessLabel = (id?: number | null, name?: string | null) => BUSINESS_TYPES.find((t) => t.value === id)?.label || name || "未记录";
const listName = (region?: string) => `${(region || "名单").slice(0, 35)}-${new Date().toISOString().replace(/[-:TZ.]/g, "").slice(0, 17)}`;

const SCREENING = ["unchecked", "candidate", "unknown", "excluded_cafe", "excluded_chain", "excluded_canteen", "excluded_community", "excluded_institution", "excluded_pub", "excluded_closed", "excluded_other"];

function LeadsInner() {
  const { me } = useOperator();
  const canWrite = me?.role === "admin" || me?.role === "director" || me?.role === "member";
  const canManage = me?.role === "admin" || me?.role === "director";
  const [ownerView, setOwnerView] = useState("all");
  const [ownerFilter, setOwnerFilter] = useState<string>();
  const sp = useSearchParams();
  const router = useRouter();
  const [mounted, setMounted] = useState(false);
  useEffect(() => { setMounted(true); }, []);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [batchKey, setBatchKey] = useState<string | undefined>(sp.get("batch") ?? undefined);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [businessType, setBusinessType] = useState<number | undefined>(Number(sp.get("type")) || undefined);
  const [screen, setScreen] = useState<string | undefined>(sp.get("screen") || undefined);
  const [q, setQ] = useState(sp.get("q") || "");
  const [listPage, setListPage] = useState(Number(sp.get("page")) || 1);
  const [pageSize, setPageSize] = useState(Number(sp.get("pageSize")) || 50);
  const [selectedRows, setSelectedRows] = useState<React.Key[]>([]);
  const [prepareOpen, setPrepareOpen] = useState(false);
  const [contactRun, setContactRun] = useState<{ totals: Record<string, number>; jobs: { id: string; lead_id: string; step: string; status: string; error: string | null; contact_result?: { page_errors?: { url?: string; error: string }[] } | null }[] } | null>(null);
  const [contactError, setContactError] = useState<string>();
  const [prepareLeadIds, setPrepareLeadIds] = useState<string[] | null>(null);
  const selectionKey = `beacon-list-selection:${me?.id}:${batchKey}`;
  useEffect(() => { try { setSelectedRows(JSON.parse(sessionStorage.getItem(selectionKey) || "[]")); } catch { setSelectedRows([]); } }, [selectionKey]);
  const selectRows = (keys: React.Key[]) => { setSelectedRows(keys); sessionStorage.setItem(selectionKey, JSON.stringify(keys)); };
  const locationParams = new URLSearchParams();
  if (batchKey) locationParams.set("batch", batchKey);
  if (q) locationParams.set("q", q);
  if (businessType) locationParams.set("type", String(businessType));
  if (screen) locationParams.set("screen", screen);
  if (listPage > 1) locationParams.set("page", String(listPage));
  if (pageSize !== 50) locationParams.set("pageSize", String(pageSize));
  const returnTo = `/leads${locationParams.size ? `?${locationParams}` : ""}`;
  const [authorities, setAuthorities] = useState<Authority[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [manualOpen, setManualOpen] = useState(false);
  const [newOpen, setNewOpen] = useState(false);
  const [buildOpen, setBuildOpen] = useState(false);
  const [cancelTarget, setCancelTarget] = useState<{ key: string; id: string }>();
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string>();
  const [authFailed, setAuthFailed] = useState(false);
  const [authoritiesLoading, setAuthoritiesLoading] = useState(false);
  const [delOpen, setDelOpen] = useState(false);
  const [delPreview, setDelPreview] = useState<DeletePreview | null>(null);
  const [delConfirm, setDelConfirm] = useState("");
  const [delBusy, setDelBusy] = useState(false);
  const [fsaForm] = Form.useForm();
  const [createForm] = Form.useForm<CreateValues>();
  const [createMethod, setCreateMethod] = useState<"auto" | "csv" | "empty">("auto");
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [creating, setCreating] = useState(false);
  const [workflow, setWorkflow] = useState<ListWorkflow | null>(null);
  const [workflowLoading, setWorkflowLoading] = useState(true);
  const [workflowLoadError, setWorkflowLoadError] = useState(false);
  const [enrichPhase, setEnrichPhase] = useState<"sync" | "review">("sync");
  const [mode, setMode] = useState<"enrich" | "append" | "progress">("enrich");
  const activeKey = useRef(batchKey);
  activeKey.current = batchKey;
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const locked = !canManage || creating || !!busy || workflowLoading || workflowLoadError || workflowBlocksActions(workflow);
  const generatedName = useRef("");
  useEffect(() => { if (newOpen) createForm.resetFields(); }, [newOpen, createForm]);
  const err = (e: Error) => message.error(e.message);
  // 地区取自 FSA 地方当局名录；接口不可用时退回手工输入
  const loadAuthorities = useCallback(() => {
    setAuthoritiesLoading(true);
    api<Authority[]>("/api/directory/regions").then((a) => { setAuthorities(a.filter((r) => !!r.last_success_at)); setAuthFailed(false); }).catch(() => { setAuthFailed(true); }).finally(() => setAuthoritiesLoading(false));
  }, []);

  const loadBatches = useCallback(() => api<Batch[]>("/api/batches").then((b) => { setBatches(b); if (!batchKey && b[0]) setBatchKey(b[0].batch_key); }).catch(err), [batchKey]);
  const loadLeads = useCallback((key?: string) => {
    if (!key) return setLeads([]);
    getAllBatchLeads<Lead>(key).then((rows) => { if (activeKey.current === key) setLeads(rows); }).catch(err);
  }, []);
  useEffect(() => { loadBatches(); }, [loadBatches]);
  useEffect(() => { loadLeads(batchKey); }, [batchKey, loadLeads]);
  useEffect(() => { router.replace(returnTo, { scroll: false }); }, [returnTo, router]);
  const workflowRefresh = useRef("");
  const loadWorkflow = useCallback(async (key: string) => {
    const task = await api<ListWorkflow | null>(`/api/batches/${encodeURIComponent(key)}/workflow`);
    if (activeKey.current === key) { setWorkflow(task); setWorkflowLoadError(false); const signature = task ? `${task.id}:${task.step}:${task.status}` : ""; if (signature !== workflowRefresh.current && task) { workflowRefresh.current = signature; loadLeads(key); } }
    return task;
  }, [loadLeads]);
  useEffect(() => {
    setWorkflow(null);
    setWorkflowLoadError(false);
    if (!batchKey) { setWorkflowLoading(false); return; }
    setWorkflowLoading(true);
    loadWorkflow(batchKey).catch((e: Error) => { if (activeKey.current === batchKey) setWorkflowLoadError(true); err(e); }).finally(() => { if (activeKey.current === batchKey) setWorkflowLoading(false); });
  }, [batchKey, loadWorkflow]);
  useEffect(() => {
    if (!batchKey || creating) return;
    const timer = setInterval(() => { loadWorkflow(batchKey).catch(() => {}); }, 5000);
    return () => clearInterval(timer);
  }, [batchKey, creating, loadWorkflow]);
  const currentBatch = batches.find((b) => b.batch_key === batchKey);
  const appendAuthority = authorities.find((a) => a.name === currentBatch?.region);
  useEffect(() => {
    if (!buildOpen || mode !== "append") return;
    loadAuthorities();
    const ids = currentBatch?.business_type?.startsWith("fsa:") ? currentBatch.business_type.slice(4).split(",").map(Number).filter((id) => BUSINESS_TYPES.some((t) => t.value === id)) : [1];
    fsaForm.setFieldsValue({ exclude_awaiting: false, business_type_ids: ids.length ? ids : [1] });
  }, [buildOpen, mode, currentBatch?.business_type, fsaForm, loadAuthorities]);

  const executeWorkflow = async (key: string, task: ListWorkflow) => {
    setCreating(true);
    setMode("progress");
    setBuildOpen(true);
    setWorkflow(task);
    try {
      const next = await api<ListWorkflow>(`/api/batches/${encodeURIComponent(key)}/workflow/${task.id}/resume`, { method: "POST" });
      if (alive.current && activeKey.current === key) setWorkflow(next);
    } catch (e) {
      err(e as Error);
      await loadWorkflow(key).catch(() => {});
    } finally {
      if (alive.current) { setCreating(false); loadLeads(key); loadBatches(); }
    }
  };
  const startWorkflow = async (kind: "enrich" | "append", values?: CreateValues) => {
    if (!batchKey) return;
    const key = batchKey;
    setCreating(true);
    try {
      const task = await api<ListWorkflow>(`/api/batches/${encodeURIComponent(key)}/workflow`, json({ kind, phase: kind === "enrich" ? enrichPhase : "sync", ...(kind === "enrich" && enrichPhase === "review" && selectedRows.length ? { lead_ids: leads.filter(l => selectedRows.includes(l.id)).map(l => l.id) } : {}), ...(kind === "append" ? { authority_id: appendAuthority?.id, authority_name: currentBatch?.region, business_type_ids: values?.business_type_ids || [1], sample_n: null, exclude_awaiting: values?.exclude_awaiting ?? false } : {}) }));
      await executeWorkflow(key, task);
    } catch (e) { err(e as Error); } finally { setCreating(false); }
  };
  const cancelWorkflow = () => {
    if (!batchKey || !workflow) return;
    setCancelError(undefined);
    setCancelTarget({ key: batchKey, id: workflow.id });
  };
  const confirmCancelWorkflow = async () => {
    if (!cancelTarget || cancelling) return;
    const { key, id } = cancelTarget;
    setCancelling(true);
    setCancelError(undefined);
    try {
      const task = await api<ListWorkflow>(`/api/batches/${encodeURIComponent(key)}/workflow/${id}/cancel`, { method: "POST" });
      if (activeKey.current === key) { setWorkflow(task); setBuildOpen(false); }
      setCancelTarget(undefined);
      message.success("任务已结束，已有结果保留");
    } catch (e) {
      setCancelError((e as Error).message || "结束任务失败，请重试");
    } finally { setCancelling(false); }
  };
  const createBatch = async (v: CreateValues) => {
    const authority = authorities.find((a) => a.name === v.region);
    if (createMethod === "auto" && !authority) return message.error("请选择已同步的门店池地区；可先到门店池同步，或改为导入 CSV。");
    if (createMethod === "csv" && !csvFile) return message.error("请先选择 CSV 文件");
    const key = v.batch_key?.trim() || listName(v.region);
    const metadata = { batch_key: key, region: v.region, notes: v.notes, country: "GB", source_name: createMethod === "auto" ? "fsa" : createMethod === "csv" ? "csv" : "manual", source_licence: createMethod === "auto" ? "OGL-3.0" : null };
    setCreating(true);
    try {
      if (createMethod === "auto") {
        const result = await api<{ workflow: ListWorkflow }>("/api/lists", json({ ...metadata, workflow: { kind: "create", authority_id: authority!.id, authority_name: authority!.name, business_type_ids: v.business_type_ids || [1], sample_n: null, exclude_awaiting: v.exclude_awaiting ?? false } }));
        activeKey.current = key;
        setBatchKey(key);
        setNewOpen(false);
        loadBatches();
        await executeWorkflow(key, result.workflow);
      } else {
        await api("/api/batches", json(metadata));
        activeKey.current = key;
        setBatchKey(key);
        setNewOpen(false);
        if (createMethod === "csv") {
          const fd = new FormData(); fd.append("batch_key", key); fd.append("file", csvFile!);
          const r = await api<{ created_count: number; linked_count: number; error_count: number }>("/api/imports", { method: "POST", body: fd });
          message.info(`CSV 导入：新增 ${r.created_count}，关联 ${r.linked_count}，错误 ${r.error_count}。可继续完善名单。`);
        } else message.success("空名单已创建，可追加商户或导入 CSV");
        loadLeads(key); loadBatches();
      }
    } catch (e) { err(e as Error); loadBatches(); } finally { setCreating(false); }
  };

  const openDelete = () => {
    if (!batchKey) return;
    setDelConfirm("");
    setDelPreview(null);
    setDelOpen(true);
    api<DeletePreview>(`/api/batches/${encodeURIComponent(batchKey)}/delete-preview`).then(setDelPreview).catch(err);
  };
  const doDelete = () => {
    if (!batchKey || delConfirm !== batchKey) return;
    setDelBusy(true);
    api<DeletePreview>(`/api/batches/${encodeURIComponent(batchKey)}?confirm=${encodeURIComponent(batchKey)}`, { method: "DELETE" })
      .then((r) => {
        message.success(`已删除批次 ${r.batch_key}：删除门店 ${r.leads_deleted} 家，保留 ${r.leads_kept_other_batches + r.leads_kept_suppressed} 家`);
        setDelOpen(false);
        return api<Batch[]>("/api/batches").then((b) => { setBatches(b); setBatchKey(b[0]?.batch_key); });
      })
      .catch(err)
      .finally(() => setDelBusy(false));
  };

  useEffect(() => {
    let current = true;
    const result = workflow?.results[workflow.steps.indexOf("contacts")];
    setContactRun(null); setContactError(undefined);
    if (buildOpen && result?.run_id) api<NonNullable<typeof contactRun>>(`/api/runs/${result.run_id}`).then((value) => { if (current) setContactRun(value); }).catch((e) => { if (current) setContactError(e.message); });
    return () => { current = false; };
  }, [buildOpen, workflow]);
  const filtered = useMemo(() => leads.filter((l) => (me?.role !== "member" ? (ownerView !== "mine" || l.assigned_to === me?.username) && (ownerView !== "unassigned" || !l.assigned_to) && (!ownerFilter || l.assigned_to === ownerFilter) : true) && (!businessType || l.business_type_id === businessType) && (!screen || l.screening_class === screen) && (!q || l.name.toLowerCase().includes(q.toLowerCase()) || (l.postcode ?? "").toLowerCase().includes(q.toLowerCase()))), [leads, businessType, screen, q, me?.role, me?.username, ownerView, ownerFilter]);
  const stats = useMemo(() => ({ total: leads.length, website: leads.filter((l) => l.website).length, candidate: leads.filter((l) => l.screening_class === "candidate").length, unchecked: leads.filter((l) => l.screening_class === "unchecked").length }), [leads]);
  const run = (name: string, p: Promise<unknown>, done: (r: never) => string) => { setBusy(name); p.then((r) => { message.success(done(r as never)); loadLeads(batchKey); loadBatches(); }).catch(err).finally(() => setBusy(null)); };

  return (
    <>
      <HeroBand kicker="LEADS" title="批次与线索" subtitle="从门店池建立名单，补充官网与联系方式；来源同步与销售处理分开。"
        extra={<>
          <Select style={{ width: 260 }} value={batchKey} disabled={creating || !!busy} onChange={(key) => { setListPage(1); setBatchKey(key); }} placeholder="选择名单" options={batches.map((b) => ({ value: b.batch_key, label: `${b.batch_key}（${b.region ?? b.country}，${b.candidate_count ?? "?"} 家）` }))} />
          <Button disabled={!canWrite || !mounted} onClick={() => setManualOpen(true)}>新增门店</Button>
          <Button type="primary" aria-label="建立名单" icon={<CloudDownloadOutlined />} disabled={!mounted || locked} onClick={() => { setCsvFile(null); setCreateMethod("auto"); generatedName.current = ""; setNewOpen(true); loadAuthorities(); }}>建立名单</Button>
          <Button type="primary" disabled={!canWrite || !leads.length || !!busy} onClick={() => { setPrepareLeadIds(null); setPrepareOpen(true); }}>准备触达</Button>
          <Link href={taskLink({ batch: batchKey, returnTo })}>查看沟通进展</Link>
          <Button danger disabled={!batchKey || locked} onClick={openDelete}>删除批次</Button>
          <Button disabled={!batchKey || locked || !leads.length} onClick={() => { setMode("enrich"); setBuildOpen(true); }}>完善名单</Button>
          <Button disabled={!batchKey || locked} onClick={() => { setMode("append"); setBuildOpen(true); }}>追加商户</Button>
        </>} />

      <OutreachJourney current={0} />
      {workflowLoadError && <Alert type="warning" showIcon message="任务进度暂时读取失败" description="重新读取后再处理这份名单。" action={<Button onClick={() => batchKey && loadWorkflow(batchKey).catch(err)}>重试读取</Button>} style={{ marginBottom: 16 }} />}
      {workflowUnfinished(workflow) && <Alert showIcon type={workflow?.status === "failed" ? "warning" : "info"} style={{ marginBottom: 16 }} message={workflow?.status === "failed" ? "部分补充数据未完成，名单可以继续使用" : "这份名单有任务等待继续或正在处理"} description={workflow?.status === "failed" ? "已取得的数据保留；可重试失败项，也可追加商户、完善名单或处理现有线索。" : "任务参数与进度已保存，继续时从未完成步骤接续。"} action={<Button disabled={!!busy || creating} onClick={() => { setMode("progress"); setBuildOpen(true); }}>查看 / 继续任务</Button>} />}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} md={6}><StatCard icon={<ShopOutlined />} title="门店" value={stats.total} hint="本批次去重门店" /></Col>
        <Col xs={12} md={6}><StatCard icon={<GlobalOutlined />} color="#d97706" title="有官网" value={stats.website} hint={stats.total ? `${Math.round((stats.website / stats.total) * 100)}% 覆盖` : undefined} /></Col>
        <Col xs={12} md={6}><StatCard icon={<CheckCircleOutlined />} color="#15803d" title="候选（人工确认）" value={stats.candidate} onClick={() => setScreen("candidate")} /></Col>
        <Col xs={12} md={6}><StatCard icon={<UserOutlined />} color="#7c3aed" title="待人工筛选" value={stats.unchecked} hint="点击只看待筛选" onClick={() => setScreen("unchecked")} /></Col>
      </Row>

      {me?.role === "member" && <Alert type="info" showIcon message="仅显示分配给你的门店。可进入门店详情补充资料、准备触达和跟进；名单分配及整批管理由销售总监处理。" style={{ marginBottom: 12 }} />}
      <Space wrap style={{ marginBottom: 12 }}>
        <Select aria-label="门店归属视图" value={me?.role === "member" ? "mine" : ownerView} disabled={me?.role === "member"} onChange={(v) => { setOwnerView(v); setListPage(1); }} style={{ width: 150 }} options={[{ value: "all", label: "全部门店" }, { value: "mine", label: "我的门店" }, { value: "unassigned", label: "未分配" }]} />
        {me?.role !== "member" && <Select aria-label="门店负责人筛选" allowClear placeholder="筛选已有负责人" value={ownerFilter} onChange={(v) => { setOwnerFilter(v); setListPage(1); }} style={{ width: 180 }} notFoundContent="当前名单尚无已分配负责人，请使用右侧分配门店" options={[...new Set(leads.map((l) => l.assigned_to).filter((v): v is string => !!v))].map((v) => ({ value: v, label: v }))} />}
        <LeadAssignment leadIds={leads.filter((l) => selectedRows.includes(l.id)).map((l) => l.id)} filteredLeadIds={filtered.map((l) => l.id)} onChanged={() => { loadLeads(batchKey); loadBatches(); selectRows([]); }} />
      </Space>
      <Card size="small" title="线索" extra={<Space>
        <Input.Search allowClear key={q} defaultValue={q} placeholder="搜索名称 / 邮编" style={{ width: 220 }} onSearch={(v) => { setQ(v); setListPage(1); }} onChange={(e) => { if (!e.target.value) { setQ(""); setListPage(1); } }} />
        <Select allowClear placeholder="FSA 登记类型" style={{ width: 200 }} value={businessType} onChange={(v) => { setBusinessType(v); setListPage(1); }} options={BUSINESS_TYPES} />
        <Button disabled={!canWrite || !batchKey || !!busy || workflowBlocksActions(workflow)} onClick={async () => { if (!batchKey) return; try { await api(`/api/batches/${encodeURIComponent(batchKey)}/screen`, json({})); message.success("已按当前策略重新预筛，人工判断保留"); await loadLeads(batchKey); } catch (e) { message.error((e as Error).message); } }}>重新预筛</Button>
        {me?.role === "admin" && <a href="/settings">配置筛选策略</a>}
        <Select allowClear placeholder="筛选分类" style={{ width: 160 }} value={screen} onChange={(v) => { setScreen(v); setListPage(1); }} options={SCREENING.map((s) => ({ value: s, label: SCREEN_ZH[s] ?? s }))} />
        <Upload disabled={!batchKey || locked} accept=".csv" showUploadList={false} customRequest={({ file }) => { if (!batchKey) return message.warning("先选择批次"); const fd = new FormData(); fd.append("batch_key", batchKey); fd.append("file", file as File); run("csv", api("/api/imports", { method: "POST", body: fd }), (r: { created_count: number; linked_count: number; skipped_count: number; error_count: number }) => `导入：新增 ${r.created_count}，关联 ${r.linked_count}，跳过 ${r.skipped_count}，错误 ${r.error_count}`); }}>
          <Button disabled={!batchKey || locked}>追加 CSV</Button>
        </Upload>
        <Button disabled={!batchKey || locked} loading={busy === "run"} onClick={() => run("run", api(`/api/batches/${encodeURIComponent(batchKey!)}/runs`, json({ steps: ["fetch", "analyze"] })), (r: { status: string; totals: Record<string, number> }) => `批量运行 ${label(r.status)}：${JSON.stringify(r.totals)}`)}>批量抓取 + 分析</Button>
        <a href={batchKey ? `/api/batches/${encodeURIComponent(batchKey!)}/export.csv` : undefined}><Button disabled={!batchKey}>导出 CSV</Button></a>
      </Space>}>
        <Typography.Text type="secondary">已选择 {leads.filter((l) => selectedRows.includes(l.id)).length} 家；未勾选时，“准备触达”使用当前筛选结果 {filtered.length} 家；分配门店需在弹窗明确选择范围。</Typography.Text>
        <Table<Lead> scroll={{ x: 1120 }} rowSelection={{ selectedRowKeys: selectedRows, onChange: selectRows, preserveSelectedRowKeys: true }} rowKey="id" size="small" dataSource={filtered} pagination={{ current: listPage, pageSize, onChange: (p, size) => { setListPage(p); setPageSize(size); }, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
          expandable={{ expandedRowRender: (r) => <Space align="start" size={32} wrap><div><div>来源：{r.source_key}</div><div>FSA 登记类型：{businessLabel(r.business_type_id, r.business_type_name)}</div><div>官网：{r.website ? <a href={r.website} target="_blank" rel="noreferrer">{r.website}</a> : "未登记"}</div><ScreenTag value={r.screening_class} reason={r.screening_reason} /></div><WebsiteReview lead={r} onChanged={() => loadLeads(batchKey)} /></Space> }}
          columns={[
            { title: "门店", dataIndex: "name", width: 260, fixed: "left", render: (v, r) => <div><Link href={`/leads/${r.id}?returnTo=${encodeURIComponent(returnTo)}`} style={{ fontWeight: 600 }}>{v}</Link><div style={{ marginTop: 4, fontSize: 12, color: "#888" }}>{r.postcode || "邮编未登记"}{r.operating_type?.category && r.operating_type.category !== "unknown" && <Tag style={{ marginLeft: 8 }}>{({ restaurant: "餐厅", cafe: "咖啡馆", takeaway: "外卖店", pub: "Pub／酒吧", institution: "机构餐饮" } as Record<string, string>)[r.operating_type.category] || r.operating_type.category}</Tag>}{r.inspection_pending && <Tag color="gold">待首次检查</Tag>}</div></div>, sorter: (a, b) => a.name.localeCompare(b.name) },
            ...(["admin", "director"].includes(me?.role || "") ? [{ title: "负责人", width: 110, render: (_: unknown, r: Lead) => <UserIdentity username={r.assigned_to} /> }] : []),
            { title: "沟通进展", width: 120, render: (_, r) => <Tag color={r.communication_progress?.status === "suppressed" ? "red" : r.communication_progress?.status === "replied" ? "green" : "blue"}>{PROGRESS[r.communication_progress?.status || "not_started"] || "未准备"}</Tag> },
            { title: "下一步", width: 200, sorter: (a, b) => leadPriority(a).rank - leadPriority(b).rank, showSorterTooltip: { title: "按工作优先级排序：回复、待执行、待完善；不是成交概率" }, render: (_, r) => { const action = leadNextAction(r); return <Button type="link" size="small" disabled={!canWrite && action.target === "prepare"} onClick={() => { if (action.target === "tasks") router.push(taskLink({ lead: r.id, task: r.communication_progress?.task_id, batch: batchKey, returnTo })); else if (action.target === "prepare") { setPrepareLeadIds([r.id]); setPrepareOpen(true); } else router.push(`/leads/${r.id}?returnTo=${encodeURIComponent(returnTo)}${action.target === "contacts" ? "#customer-contacts" : ""}`); }}>{action.text}</Button>; } },
            { title: "联系方式", width: 180, render: (_, r) => r.contact_count ? <div>{r.list_summary?.channels.map((c) => channelLabel(c)).join("／") || "已记录"}<div style={{ fontSize: 12, color: "#888" }}>{r.contact_count} 项 · 准入见详情</div></div> : <span className="beacon-muted">待补充</span> },
            { title: "菜单", width: 110, render: (_, r) => <Tag color={r.list_summary?.menu_status === "reviewed" ? "green" : undefined}>{MENU_STATES[r.list_summary?.menu_status || ""] || "待检查"}</Tag> },
            { title: "操作", width: 100, render: (_, r) => <Link href={`/leads/${r.id}?returnTo=${encodeURIComponent(returnTo)}`}>查看详情</Link> },
          ]} />
      </Card>

      <PrepareOutreach open={prepareOpen} leadIds={prepareLeadIds || (leads.some((l) => selectedRows.includes(l.id)) ? leads.filter((l) => selectedRows.includes(l.id)) : filtered).map((l) => l.id)} batchKey={batchKey} returnTo={returnTo} onClose={() => { setPrepareOpen(false); loadLeads(batchKey); }} onChanged={() => loadLeads(batchKey)} />
      <ManualLead open={manualOpen} onClose={() => setManualOpen(false)} batches={batches} batchKey={batchKey} onSaved={() => { loadBatches(); loadLeads(batchKey); }} />
      <Modal title="建立名单" forceRender={mounted} open={newOpen} onCancel={() => { if (!creating) setNewOpen(false); }} footer={null} destroyOnHidden maskClosable={false} closable={!creating}>
          <Form name="create-list" form={createForm} layout="vertical" initialValues={{ exclude_awaiting: false, business_type_ids: [1] }} onFinish={createBatch} onValuesChange={(changed, values) => {
            if ("region" in changed && (!values.batch_key || values.batch_key === generatedName.current)) {
              generatedName.current = listName(values.region);
              createForm.setFieldValue("batch_key", generatedName.current);
            }
          }}>
            {createMethod === "auto" && !authorities.length && !authFailed && <Alert type="info" showIcon message="还没有已同步的门店池" description={<Link href="/directory">前往门店池，选择地区并同步后即可建立名单</Link>} style={{ marginBottom: 16 }} />}
            <Form.Item label="创建方式"><Radio.Group value={createMethod} onChange={(e) => setCreateMethod(e.target.value)} options={[{ value: "auto", label: "自动获取" }, { value: "csv", label: "导入 CSV" }, { value: "empty", label: "仅建空名单" }]} /></Form.Item>
            {authFailed && createMethod === "auto" && <Alert type="warning" showIcon message="门店池暂不可用" description="可以重试读取，或选择导入 CSV。" action={<Button size="small" onClick={loadAuthorities}>重试加载</Button>} style={{ marginBottom: 12 }} />}
            <Form.Item name="region" label="地区" extra={createMethod === "auto" ? "从已经同步的门店池选入所选类型全部商户，不会在这里请求 FSA。" : undefined} rules={[{ required: createMethod === "auto", message: "请选择地区" }]}>
              {authFailed && createMethod !== "auto" ? <Input placeholder="可选，例如 Camden" /> : <Select showSearch allowClear placeholder={createMethod === "auto" ? "搜索英国地区，例如 Camden" : "可选，选择名单所属地区"} optionFilterProp="label" loading={authoritiesLoading} options={authorities.map((a) => ({ value: a.name, label: `${a.name}${a.region ? `（${a.region}）` : ""} · 门店池 ${a.pool_count} 家 · ${a.last_success_at ? new Date(a.last_success_at).toLocaleDateString("zh-CN") : "未同步"}` }))} />}
            </Form.Item>
            {createMethod === "auto" && <Alert type="info" showIcon message="从门店池选入所选类型的全部商户" description="名单成员固定，来源同步不会自动改变已有名单。" style={{ marginBottom: 16 }} />}
            {createMethod === "auto" && <Form.Item name="business_type_ids" label="商户类型" rules={[{ required: true, type: "array", min: 1, message: "请至少选择一种商户类型" }]} extra="默认餐厅类；其他类型按需选入。Pub 类包含夜店，是否有菜单需进一步核实。"><Select mode="multiple" options={BUSINESS_TYPES} /></Form.Item>}
            <Form.Item name="batch_key" label="名单名称" rules={[{ max: 64, message: "最多 64 个字符" }, { validator: (_, value) => value && !value.trim() ? Promise.reject(new Error("名称不能只有空格")) : Promise.resolve() }]} extra="根据地区自动生成，可修改；留空也会自动生成。"><Input maxLength={64} placeholder="选择地区后自动生成" /></Form.Item>
            {createMethod === "csv" && <Form.Item label="CSV 文件" required extra="至少包含 name，以及 source_key、source_id 或 fhrsid 中的一项。">
              <Upload accept=".csv" fileList={csvFile ? [{ uid: "selected", name: csvFile.name, status: "done" }] : []} maxCount={1} beforeUpload={(file) => { setCsvFile(file); return false; }} onRemove={() => { setCsvFile(null); }}><Button>选择 CSV 文件</Button></Upload>
            </Form.Item>}
            <Collapse ghost items={[{ key: "advanced", label: "高级选项", children: <>
              {createMethod === "auto" && <Form.Item name="exclude_awaiting" label="排除尚未首次检查的商家" valuePropName="checked" extra="默认保留。待检查不等于不适合联系，也不代表已确认新开业。"><Switch /></Form.Item>}
              <Form.Item name="notes" label="备注"><Input.TextArea rows={2} /></Form.Item>
            </> }]} />
            <Button type="primary" htmlType="submit" block loading={creating} disabled={createMethod === "auto" && (authFailed || !authorities.length)}>{createMethod === "auto" ? "创建并开始获取" : createMethod === "csv" ? "创建并导入" : "创建空名单"}</Button>
          </Form>
      </Modal>

      <Modal title={`删除批次 · ${batchKey ?? ""}`} open={delOpen} onCancel={() => setDelOpen(false)} okText="永久删除" okButtonProps={{ danger: true, disabled: !delPreview || delConfirm !== batchKey, loading: delBusy }} onOk={doDelete} cancelText="取消" destroyOnHidden>
        {!delPreview ? <p>正在统计影响范围…</p> : (
          <>
            <Alert type="error" showIcon style={{ marginBottom: 12 }} message="删除后不可恢复" description={`将删除 ${delPreview.leads_deleted} 家只属于本批次的门店，连同它们的菜单文件、分析、样稿文案、联系方式、任务和回复记录。`} />
            <Descriptions size="small" column={2} bordered style={{ marginBottom: 12 }} items={[
              { key: "a", label: "批次内门店", children: delPreview.leads_in_batch },
              { key: "b", label: "将删除门店", children: delPreview.leads_deleted },
              { key: "c", label: "保留（属于其他批次）", children: delPreview.leads_kept_other_batches },
              { key: "d", label: "保留（有拒收 / 退订记录）", children: delPreview.leads_kept_suppressed },
              { key: "e", label: "菜单文件", children: delPreview.menu_assets },
              { key: "f", label: "分析版本", children: delPreview.analyses },
              { key: "g", label: "样稿 / 文案", children: delPreview.content_pieces },
              { key: "h", label: "联系方式与准入", children: delPreview.contacts },
              { key: "i", label: "任务（其中已发送）", children: `${delPreview.tasks}（${delPreview.tasks_sent}）` },
              { key: "j", label: "回复 / 事件", children: delPreview.events },
              { key: "k", label: "导入与运行记录", children: delPreview.import_runs + delPreview.batch_runs },
              { key: "l", label: "成本记录", children: delPreview.cost_entries },
            ]} />
            {delPreview.tasks_sent > 0 && <Alert type="warning" showIcon style={{ marginBottom: 12 }} message={`有 ${delPreview.tasks_sent} 个任务已发送，真实联系记录会一并删除`} />}
            {delPreview.leads_kept_suppressed > 0 && <Alert type="info" showIcon style={{ marginBottom: 12 }} message="有拒收 / 退订记录的门店不会删除，以保证抑制继续生效；它们会脱离本批次" />}
            <p style={{ marginBottom: 6 }}>输入批次键 <b>{batchKey}</b> 以确认：</p>
            <Input value={delConfirm} onChange={(e) => setDelConfirm(e.target.value)} placeholder={batchKey} />
          </>
        )}
      </Modal>

      {mounted && <Drawer forceRender title={`${mode === "append" ? "追加商户" : mode === "enrich" ? "完善名单" : "名单任务"} · ${batchKey ?? ""}`} open={buildOpen} onClose={() => setBuildOpen(false)} width={520}>
        {mode === "progress" ? workflow ? <>
          <p>目标名单：<b>{batchKey}</b> · {workflow.kind === "enrich" ? "完善现有门店" : workflow.kind === "append" ? "追加商户" : "建立名单"}</p>
          {workflow.params.authority_name && <p>地区：{workflow.params.authority_name} · 本次数量：{workflow.params.sample_n ?? "全部"}<br />类型：{workflow.params.business_type_ids?.map((id) => businessLabel(id)).join(" / ")}</p>}
          <Steps direction="vertical" size="small" current={workflow.step} status={workflow.status === "failed" ? "error" : workflow.status === "completed" ? "finish" : "process"} items={workflow.steps.map((stage, i) => ({ title: WORKFLOW_TITLES[stage], description: workflowSummary(stage, stage === "contacts" && contactRun ? { totals: contactRun.totals } : workflow.results[i]) }))} />
          {contactError && <Alert type="warning" message={`读取失败明细暂不可用：${contactError}`} />}
          {contactRun && <Typography.Paragraph type="secondary">“找到联系方式”包含官网与已有 Overture 候选，不代表已获得邮箱或允许触达。部分读取和读取失败可重试，已记录结果会保留。</Typography.Paragraph>}
          {contactRun?.jobs.some((j) => j.step === "contacts" && j.status === "failed") && <Collapse style={{ marginTop: 12 }} items={[{ key: "contact-errors", label: "查看未完成门店与具体原因", children: <Table rowKey="id" size="small" pagination={{ pageSize: 5 }} dataSource={contactRun.jobs.filter((j) => j.step === "contacts" && j.status === "failed")} columns={[
            { title: "门店", render: (_, j) => <Link href={`/leads/${j.lead_id}`}>{leads.find((l) => l.id === j.lead_id)?.name || j.lead_id}</Link> },
            { title: "失败原因", render: (_, j) => <><div>{contactFailureLabel(j.contact_result?.page_errors?.map((p) => p.error).join("；") || j.error || "")}</div><details><summary>原始记录</summary>{j.contact_result?.page_errors?.length ? j.contact_result.page_errors.map((p, i) => <p key={i} style={{ overflowWrap: "anywhere" }}>{p.url}<br />{p.error}</p>) : <p>{j.error}；历史任务未保存逐页错误时，需重试确认。</p>}</details></> },
          ]} /> }]} />}
          {workflow.error && <Alert type="warning" showIcon message="部分数据未补齐，不影响名单使用" description={workflow.error.replace(/^ValueError:\s*/, "")} style={{ margin: "16px 0" }} />}
          {workflow.status === "completed" ? <Alert type="success" showIcon message="处理完成" description={workflow.params.phase === "sync" ? "名单可以使用。未完成的来源查询可再次同步；AI 核验与联系方式查找可在完善名单中单独启动。" : "请核对门店类型与联系方式，渠道准入仍需逐条确认。"} style={{ marginTop: 16 }} /> : workflow.status === "cancelled" ? <Alert type="info" message="任务已结束，已有结果保留" /> : <>
            <p style={{ color: "#6b7280" }}>{workflow.status === "failed" ? "本次补充已停止。关闭面板即可继续操作名单；重试只处理未完成项。" : "任务由后台执行，关闭页面不影响处理。服务重启后从检查点恢复；已完成步骤不重做。"}</p>
            <Space>
              <Button type="primary" loading={creating} disabled={!canWrite || creating || !!busy || (!!workflow.params.background && ["pending", "running"].includes(workflow.status))} onClick={() => executeWorkflow(batchKey!, workflow)}>{workflow.status === "failed" ? "重试未完成步骤" : "继续任务"}</Button>
              <Button disabled={!canWrite || cancelling} onClick={cancelWorkflow}>结束任务</Button>
            </Space>
          </>}
        </> : <p>正在读取任务进度…</p> : mode === "enrich" ? <>
          <Alert showIcon type="info" message={`完善名单内现有 ${leads.length} 家门店`} description="先同步来源资料，名单即可使用；AI 核验、筛选和联系方式查找可稍后单独运行。保留人工官网及人工判断。" style={{ marginBottom: 16 }} />
          <Radio.Group value={enrichPhase} onChange={e => setEnrichPhase(e.target.value)} style={{ marginBottom: 16 }} options={[{ value: "sync", label: "同步来源资料" }, { value: "review", label: "AI 核验与完善" }]} />
          {enrichPhase === "review" && <p>核验范围：{selectedRows.length ? `已勾选 ${selectedRows.length} 家` : `名单全部 ${leads.length} 家`}。已完成的来源查询可复用。</p>}
          <Steps direction="vertical" size="small" items={enrichPhase === "sync" ? [{ title: "Overture 补充官网与电话" }, { title: "Google 来源资料同步（待核验）" }] : [{ title: "AI 核验官网与经营类型" }, { title: "客户筛选策略" }, { title: "查找联系方式" }]} />
          <Button type="primary" block disabled={locked} loading={creating} style={{ marginTop: 16 }} onClick={() => startWorkflow("enrich")}>{enrichPhase === "sync" ? "开始同步资料" : "开始 AI 核验与完善"}</Button>
        </> : <>
          <Alert showIcon type="info" message={`追加到 ${currentBatch?.region || "未设置地区"}`} description="从门店池选入所选类型的全部剩余商户，自动排除已有成员。追加后同步来源资料；AI 核验与联系方式查找可稍后进行。" style={{ marginBottom: 16 }} />
          {authFailed && <Alert type="warning" message="门店池暂不可用" action={<Button size="small" onClick={loadAuthorities}>重试加载</Button>} style={{ marginBottom: 16 }} />}
          {!authFailed && authorities.length > 0 && !appendAuthority && <Alert type="warning" message="该地区尚未同步到门店池，请先前往门店池同步，或追加 CSV" style={{ marginBottom: 16 }} />}
          <Form name="append-list" form={fsaForm} layout="vertical" initialValues={{ business_type_ids: [1], exclude_awaiting: false }} onFinish={(v) => startWorkflow("append", v)}>
            <Form.Item label="地区" htmlFor="append-list-region"><Input id="append-list-region" disabled value={currentBatch?.region ?? "未设置"} /></Form.Item>
            <Form.Item name="business_type_ids" label="商户类型" rules={[{ required: true, type: "array", min: 1, message: "请至少选择一种类型" }]}><Select mode="multiple" options={BUSINESS_TYPES} /></Form.Item>
            <Collapse ghost items={[{ key: "filters", label: "高级筛选", children: <Form.Item name="exclude_awaiting" label="排除尚未首次检查的商家" valuePropName="checked"><Switch /></Form.Item> }]} />
            <Button type="primary" htmlType="submit" block disabled={locked || !appendAuthority} loading={creating}>追加并完善</Button>
          </Form>
        </>}
        <Modal title="结束这个未完成任务？" open={!!cancelTarget} onCancel={() => { if (!cancelling) setCancelTarget(undefined); }} onOk={confirmCancelWorkflow} confirmLoading={cancelling} closable={!cancelling} maskClosable={!cancelling} cancelButtonProps={{ disabled: cancelling }} okText="结束任务" cancelText="返回">
          <p>已加入的门店和已完成的结果会保留。正在进行的请求可能需要收尾，收尾期间请稍候再开始新任务。</p>
          {cancelError && <Alert type="error" showIcon message="未能结束任务" description={cancelError} />}
        </Modal>
      </Drawer>}

    </>
  );
}

export default function LeadsPage() {
  return <Suspense><LeadsInner /></Suspense>;
}
