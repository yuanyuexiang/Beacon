"use client";
import { Alert, Button, Card, Col, Collapse, Descriptions, Drawer, Form, Input, Modal, Radio, Row, Select, Space, Steps, Switch, Table, Tag, Typography, Upload, message } from "antd";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import PrepareOutreach from "@/components/PrepareOutreach";
import { PROGRESS, Progress, taskLink } from "@/lib/communication";
import { useOperator } from "@/lib/auth";
import { api, json } from "@/lib/api";
import { CheckCircleOutlined, CloudDownloadOutlined, GlobalOutlined, ShopOutlined, UserOutlined } from "@ant-design/icons";
import { HeroBand, SCREEN_ZH, ScreenTag, StatCard } from "@/components/ui";
import { label } from "@/lib/format";
import { ListWorkflow, workflowUnfinished, workflowBlocksActions, WORKFLOW_TITLES, workflowSummary, getAllBatchLeads } from "@/lib/list-workflow";

type Batch = { id: string; batch_key: string; country: string; region: string | null; source_name: string; business_type?: string | null; candidate_count: number | null };
type Lead = { communication_progress?: Progress; operating_type?: { category: string; reason: string }; google_enrichment?: { status: string }; business_type_id?: number | null; business_type_name?: string | null; inspection_pending?: boolean; id: string; source_key: string; name: string; postcode: string | null; website: string | null; screening_class: string; screening_reason: string | null; entity_status: string; contact_count: number };
type Authority = { id: number; name: string; region: string | null; count: number | null; pool_count: number; last_success_at: string | null; type_versions: Record<string, unknown> };
type DeletePreview = { batch_key: string; leads_in_batch: number; leads_deleted: number; leads_kept_other_batches: number; leads_kept_suppressed: number; menu_assets: number; analyses: number; content_pieces: number; contacts: number; tasks: number; tasks_sent: number; events: number; import_runs: number; batch_runs: number; cost_entries: number };

type CreateValues = { batch_key?: string; region?: string; notes?: string; exclude_awaiting?: boolean; business_type_ids?: number[] };
const BUSINESS_TYPES = [{ value: 1, label: "餐厅、咖啡馆、食堂" }, { value: 7844, label: "外卖店、三明治店" }, { value: 7843, label: "酒吧、Pub、夜店" }];
const businessLabel = (id?: number | null, name?: string | null) => BUSINESS_TYPES.find((t) => t.value === id)?.label || name || "未记录";
const listName = (region?: string) => `${(region || "名单").slice(0, 35)}-${new Date().toISOString().replace(/[-:TZ.]/g, "").slice(0, 17)}`;

const SCREENING = ["unchecked", "candidate", "unknown", "excluded_cafe", "excluded_chain", "excluded_canteen", "excluded_community", "excluded_institution", "excluded_pub", "excluded_closed", "excluded_other"];

function LeadsInner() {
  const { me } = useOperator();
  const canWrite = me?.role === "admin" || me?.role === "member";
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
  const [newOpen, setNewOpen] = useState(false);
  const [buildOpen, setBuildOpen] = useState(false);
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
  const [mode, setMode] = useState<"enrich" | "append" | "progress">("enrich");
  const activeKey = useRef(batchKey);
  activeKey.current = batchKey;
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const locked = !canWrite || creating || !!busy || workflowLoading || workflowLoadError || workflowBlocksActions(workflow);
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
  const loadWorkflow = useCallback(async (key: string) => {
    const task = await api<ListWorkflow | null>(`/api/batches/${encodeURIComponent(key)}/workflow`);
    if (activeKey.current === key) { setWorkflow(task); setWorkflowLoadError(false); }
    return task;
  }, []);
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
      let next = task;
      do {
        next = await api<ListWorkflow>(`/api/batches/${encodeURIComponent(key)}/workflow/${next.id}/advance`, { method: "POST" });
        if (!alive.current || activeKey.current !== key) break;
        setWorkflow(next);
      } while (next.status === "pending");
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
      const task = await api<ListWorkflow>(`/api/batches/${encodeURIComponent(key)}/workflow`, json({ kind, ...(kind === "append" ? { authority_id: appendAuthority?.id, authority_name: currentBatch?.region, business_type_ids: values?.business_type_ids || [1], sample_n: null, exclude_awaiting: values?.exclude_awaiting ?? false } : {}) }));
      await executeWorkflow(key, task);
    } catch (e) { err(e as Error); } finally { setCreating(false); }
  };
  const cancelWorkflow = () => {
    if (!batchKey || !workflow) return;
    const key = batchKey, id = workflow.id;
    Modal.confirm({ title: "结束这个未完成任务？", content: "已加入的门店和已完成的结果会保留。结束后可开始新任务。", okText: "结束任务", cancelText: "返回", onOk: async () => {
      const task = await api<ListWorkflow>(`/api/batches/${encodeURIComponent(key)}/workflow/${id}/cancel`, { method: "POST" });
      if (activeKey.current === key) { setWorkflow(task); setBuildOpen(false); }
    } });
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

  const filtered = useMemo(() => leads.filter((l) => (!businessType || l.business_type_id === businessType) && (!screen || l.screening_class === screen) && (!q || l.name.toLowerCase().includes(q.toLowerCase()) || (l.postcode ?? "").toLowerCase().includes(q.toLowerCase()))), [leads, businessType, screen, q]);
  const stats = useMemo(() => ({ total: leads.length, website: leads.filter((l) => l.website).length, candidate: leads.filter((l) => l.screening_class === "candidate").length, unchecked: leads.filter((l) => l.screening_class === "unchecked").length }), [leads]);
  const run = (name: string, p: Promise<unknown>, done: (r: never) => string) => { setBusy(name); p.then((r) => { message.success(done(r as never)); loadLeads(batchKey); loadBatches(); }).catch(err).finally(() => setBusy(null)); };

  return (
    <>
      <HeroBand kicker="LEADS" title="批次与线索" subtitle="从门店池建立名单，补充官网与联系方式；来源同步与销售处理分开。"
        extra={<>
          <Select style={{ width: 260 }} value={batchKey} disabled={creating || !!busy} onChange={(key) => { setListPage(1); setBatchKey(key); }} placeholder="选择名单" options={batches.map((b) => ({ value: b.batch_key, label: `${b.batch_key}（${b.region ?? b.country}，${b.candidate_count ?? "?"} 家）` }))} />
          <Button type="primary" aria-label="建立名单" icon={<CloudDownloadOutlined />} disabled={!mounted || locked} onClick={() => { setCsvFile(null); setCreateMethod("auto"); generatedName.current = ""; setNewOpen(true); loadAuthorities(); }}>建立名单</Button>
          <Button type="primary" disabled={!canWrite || !leads.length || creating || !!busy} onClick={() => { setPrepareLeadIds(null); setPrepareOpen(true); }}>准备触达</Button>
          <Link href={taskLink({ batch: batchKey, returnTo })}>查看沟通进展</Link>
          <Button danger disabled={!batchKey || locked} onClick={openDelete}>删除批次</Button>
          <Button disabled={!batchKey || locked || !leads.length} onClick={() => { setMode("enrich"); setBuildOpen(true); }}>完善名单</Button>
          <Button disabled={!batchKey || locked} onClick={() => { setMode("append"); setBuildOpen(true); }}>追加商户</Button>
        </>} />

      {workflowLoadError && <Alert type="warning" showIcon message="任务进度暂时读取失败" description="重新读取后再处理这份名单。" action={<Button onClick={() => batchKey && loadWorkflow(batchKey).catch(err)}>重试读取</Button>} style={{ marginBottom: 16 }} />}
      {workflowUnfinished(workflow) && <Alert showIcon type={workflow?.status === "failed" ? "warning" : "info"} style={{ marginBottom: 16 }} message={workflow?.status === "failed" ? "部分补充数据未完成，名单可以继续使用" : "这份名单有任务等待继续或正在处理"} description={workflow?.status === "failed" ? "已取得的数据保留；可重试失败项，也可追加商户、完善名单或处理现有线索。" : "任务参数与进度已保存，继续时从未完成步骤接续。"} action={<Button disabled={!!busy || creating} onClick={() => { setMode("progress"); setBuildOpen(true); }}>查看 / 继续任务</Button>} />}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} md={6}><StatCard icon={<ShopOutlined />} title="门店" value={stats.total} hint="本批次去重门店" /></Col>
        <Col xs={12} md={6}><StatCard icon={<GlobalOutlined />} color="#d97706" title="有官网" value={stats.website} hint={stats.total ? `${Math.round((stats.website / stats.total) * 100)}% 覆盖` : undefined} /></Col>
        <Col xs={12} md={6}><StatCard icon={<CheckCircleOutlined />} color="#15803d" title="候选（人工确认）" value={stats.candidate} onClick={() => setScreen("candidate")} /></Col>
        <Col xs={12} md={6}><StatCard icon={<UserOutlined />} color="#7c3aed" title="待人工筛选" value={stats.unchecked} hint="点击只看待筛选" onClick={() => setScreen("unchecked")} /></Col>
      </Row>

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
        <Typography.Text type="secondary">已选择 {leads.filter((l) => selectedRows.includes(l.id)).length} 家；未勾选时，“准备触达”使用当前筛选结果 {filtered.length} 家。</Typography.Text>
        <Table<Lead> scroll={{ x: 1700 }} rowSelection={{ selectedRowKeys: selectedRows, onChange: selectRows, preserveSelectedRowKeys: true }} rowKey="id" size="small" dataSource={filtered} pagination={{ current: listPage, pageSize, onChange: (p, size) => { setListPage(p); setPageSize(size); }, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
          columns={[
            { title: "门店", dataIndex: "name", render: (v, r) => <Space wrap><Link href={`/leads/${r.id}?returnTo=${encodeURIComponent(returnTo)}`} style={{ fontWeight: 600 }}>{v}</Link>{r.inspection_pending && <Tag color="gold">待首次检查</Tag>}</Space>, sorter: (a, b) => a.name.localeCompare(b.name) },
            { title: "FSA 登记类型", width: 160, render: (_, r) => businessLabel(r.business_type_id, r.business_type_name) },
            { title: "经营类型／Google 核验", width: 170, render: (_, r) => <span title={r.operating_type?.reason}>{({ restaurant: "餐厅", cafe: "咖啡馆", takeaway: "外卖店", pub: "Pub／酒吧", institution: "机构餐饮" } as Record<string, string>)[r.operating_type?.category ?? ""] ?? "待识别"}{r.google_enrichment && <div style={{ color: "#888", fontSize: 12 }}>{({ verified: "官网已核验", review: "Google 待复核", failed: "Google 补充失败" } as Record<string, string>)[r.google_enrichment.status]}</div>}</span> },
            { title: "沟通进展", width: 120, render: (_, r) => ["not_started", "preparing"].includes(r.communication_progress?.status || "not_started") ? <Button type="link" size="small" disabled={!canWrite} onClick={() => { setPrepareLeadIds([r.id]); setPrepareOpen(true); }}>{r.communication_progress?.status === "preparing" ? "继续准备" : "准备触达"}</Button> : <Link href={taskLink({ lead: r.id, task: r.communication_progress?.task_id, batch: batchKey, returnTo })}><Tag color={r.communication_progress?.status === "suppressed" ? "red" : "blue"}>{PROGRESS[r.communication_progress?.status || "not_started"] || "未准备"}</Tag></Link> },
            { title: "来源键", dataIndex: "source_key", width: 120 },
            { title: "邮编", dataIndex: "postcode", width: 100 },
            { title: "官网", dataIndex: "website", ellipsis: true, render: (v, r) => (v ? <a href={v} target="_blank" rel="noreferrer"><GlobalOutlined style={{ marginRight: 6, color: "#d97706" }} />{v.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")}</a> : <Link href={`/leads/${r.id}`} title="进入详情页搜索并核对官网">搜索补官网</Link>) },
            { title: "筛选", dataIndex: "screening_class", width: 120, render: (v, r) => <ScreenTag value={v} reason={r.screening_reason} />, filters: SCREENING.map((s) => ({ text: SCREEN_ZH[s] ?? s, value: s })), onFilter: (val, r) => r.screening_class === val },
            { title: "联系方式", dataIndex: "contact_count", width: 90, sorter: (a, b) => a.contact_count - b.contact_count, render: (v) => (v ? <Tag color="blue" style={{ marginInlineEnd: 0 }}>{v} 项</Tag> : <span style={{ color: "#9ca3af" }}>-</span>) },
            { title: "主体", dataIndex: "entity_status", width: 90, render: (v) => (v === "unknown" ? <span className="beacon-muted">未知</span> : <Tag color="green" style={{ marginInlineEnd: 0 }}>{label(v)}</Tag>) },
          ]} />
      </Card>

      <PrepareOutreach open={prepareOpen} leadIds={prepareLeadIds || (leads.some((l) => selectedRows.includes(l.id)) ? leads.filter((l) => selectedRows.includes(l.id)) : filtered).map((l) => l.id)} batchKey={batchKey} returnTo={returnTo} onClose={() => { setPrepareOpen(false); loadLeads(batchKey); }} onChanged={() => loadLeads(batchKey)} />
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
          <Steps direction="vertical" size="small" current={workflow.step} status={workflow.status === "failed" ? "error" : workflow.status === "completed" ? "finish" : "process"} items={workflow.steps.map((stage, i) => ({ title: WORKFLOW_TITLES[stage], description: workflowSummary(stage, workflow.results[i]) }))} />
          {workflow.error && <Alert type="warning" showIcon message="部分数据未补齐，不影响名单使用" description={workflow.error.replace(/^ValueError:\s*/, "")} style={{ margin: "16px 0" }} />}
          {workflow.status === "completed" ? <Alert type="success" showIcon message="处理完成" description="请核对门店类型与联系方式，渠道准入仍需逐条确认。" style={{ marginTop: 16 }} /> : workflow.status === "cancelled" ? <Alert type="info" message="任务已结束，已有结果保留" /> : <>
            <p style={{ color: "#6b7280" }}>{workflow.status === "failed" ? "本次补充已停止。关闭面板即可继续操作名单；重试只处理未完成项。" : "关闭面板后本页会继续执行。刷新或离开页面后，可从保存的步骤继续；已完成步骤不重做。"}</p>
            <Space>
              <Button type="primary" loading={creating} disabled={!canWrite || creating || !!busy} onClick={() => executeWorkflow(batchKey!, workflow)}>{workflow.status === "failed" ? "重试未完成步骤" : "继续任务"}</Button>
              <Button disabled={!canWrite || creating || !!busy} onClick={cancelWorkflow}>结束任务</Button>
            </Space>
          </>}
        </> : <p>正在读取任务进度…</p> : mode === "enrich" ? <>
          <Alert showIcon type="info" message={`完善名单内现有 ${leads.length} 家门店`} description="Overture 补充后按设置使用 Google 核验官网，再运行筛选策略与联系方式查找。保留人工官网及人工判断，旧官网可追溯。" style={{ marginBottom: 16 }} />
          <Steps direction="vertical" size="small" items={[{ title: "补充官网与电话" }, { title: "Google Places 按需补充" }, { title: "客户筛选策略" }, { title: "查找联系方式" }]} />
          <Button type="primary" block disabled={locked} loading={creating} style={{ marginTop: 16 }} onClick={() => startWorkflow("enrich")}>开始完善名单</Button>
        </> : <>
          <Alert showIcon type="info" message={`追加到 ${currentBatch?.region || "未设置地区"}`} description="从门店池选入所选类型的全部剩余商户，自动排除本名单已有成员。其他地区请建立新名单。追加后自动补全官网与联系方式。" style={{ marginBottom: 16 }} />
          {authFailed && <Alert type="warning" message="门店池暂不可用" action={<Button size="small" onClick={loadAuthorities}>重试加载</Button>} style={{ marginBottom: 16 }} />}
          {!authFailed && authorities.length > 0 && !appendAuthority && <Alert type="warning" message="该地区尚未同步到门店池，请先前往门店池同步，或追加 CSV" style={{ marginBottom: 16 }} />}
          <Form name="append-list" form={fsaForm} layout="vertical" initialValues={{ business_type_ids: [1], exclude_awaiting: false }} onFinish={(v) => startWorkflow("append", v)}>
            <Form.Item label="地区" htmlFor="append-list-region"><Input id="append-list-region" disabled value={currentBatch?.region ?? "未设置"} /></Form.Item>
            <Form.Item name="business_type_ids" label="商户类型" rules={[{ required: true, type: "array", min: 1, message: "请至少选择一种类型" }]}><Select mode="multiple" options={BUSINESS_TYPES} /></Form.Item>
            <Collapse ghost items={[{ key: "filters", label: "高级筛选", children: <Form.Item name="exclude_awaiting" label="排除尚未首次检查的商家" valuePropName="checked"><Switch /></Form.Item> }]} />
            <Button type="primary" htmlType="submit" block disabled={locked || !appendAuthority} loading={creating}>追加并完善</Button>
          </Form>
        </>}
      </Drawer>}

    </>
  );
}

export default function LeadsPage() {
  return <Suspense><LeadsInner /></Suspense>;
}
