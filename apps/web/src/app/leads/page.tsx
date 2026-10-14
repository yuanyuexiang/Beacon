"use client";
import { Alert, Button, Card, Col, Collapse, Descriptions, Drawer, Form, Input, InputNumber, Modal, Radio, Row, Select, Space, Steps, Switch, Table, Tag, Upload, message } from "antd";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, json } from "@/lib/api";
import { CheckCircleOutlined, CloudDownloadOutlined, GlobalOutlined, ShopOutlined, UserOutlined } from "@ant-design/icons";
import { HeroBand, SCREEN_ZH, ScreenTag, StatCard } from "@/components/ui";
import { label } from "@/lib/format";

type Batch = { id: string; batch_key: string; country: string; region: string | null; source_name: string; candidate_count: number | null };
type Lead = { inspection_pending?: boolean; id: string; source_key: string; name: string; postcode: string | null; website: string | null; screening_class: string; screening_reason: string | null; entity_status: string; contact_count: number };
type Run = { id: string; status: string; totals: { pending: number; running: number; succeeded: number; failed: number } | null };
type Authority = { id: number; name: string; region: string | null; count: number | null };
type DeletePreview = { batch_key: string; leads_in_batch: number; leads_deleted: number; leads_kept_other_batches: number; leads_kept_suppressed: number; menu_assets: number; analyses: number; content_pieces: number; contacts: number; tasks: number; tasks_sent: number; events: number; import_runs: number; batch_runs: number; cost_entries: number };

type CreateValues = { batch_key?: string; region?: string; notes?: string; sample_n?: number | null; exclude_awaiting?: boolean };
type BuildRequest = { key: string; method: "auto" | "csv"; authority_id?: number; sample_n: number | null; seed: number; exclude_awaiting: boolean; file?: File };
const randomSeed = () => crypto.getRandomValues(new Uint32Array(1))[0] & 0x7fffffff;
const listName = (region?: string) => `${(region || "名单").slice(0, 35)}-${new Date().toISOString().replace(/[-:TZ.]/g, "").slice(0, 17)}`;

const SCREENING = ["unchecked", "candidate", "unknown", "excluded_cafe", "excluded_chain", "excluded_canteen", "excluded_community", "excluded_institution", "excluded_pub", "excluded_closed", "excluded_other"];

function LeadsInner() {
  const sp = useSearchParams();
  const router = useRouter();
  const [mounted, setMounted] = useState(false);
  useEffect(() => { setMounted(true); }, []);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [batchKey, setBatchKey] = useState<string | undefined>(sp.get("batch") ?? undefined);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [screen, setScreen] = useState<string>();
  const [q, setQ] = useState("");
  const [authorities, setAuthorities] = useState<Authority[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [newOpen, setNewOpen] = useState(false);
  const [buildOpen, setBuildOpen] = useState(false);
  const [authFailed, setAuthFailed] = useState(false);
  const [delOpen, setDelOpen] = useState(false);
  const [delPreview, setDelPreview] = useState<DeletePreview | null>(null);
  const [delConfirm, setDelConfirm] = useState("");
  const [delBusy, setDelBusy] = useState(false);
  const [fsaForm] = Form.useForm();
  const [createForm] = Form.useForm<CreateValues>();
  const [createMethod, setCreateMethod] = useState<"auto" | "csv" | "empty">("auto");
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [creating, setCreating] = useState(false);
  const [buildRequest, setBuildRequest] = useState<BuildRequest | null>(null);
  const generatedName = useRef("");
  // step 是下一步待执行位置；失败重试沿用同一名单和随机种子。

  const [autoProg, setAutoProg] = useState<{ step: number; lines: string[]; error?: string } | null>(null);
  const [contactProg, setContactProg] = useState<string | null>(null);
  useEffect(() => { if (newOpen && !autoProg) createForm.resetFields(); }, [newOpen, autoProg, createForm]);
  const err = (e: Error) => message.error(e.message);
  // 地区取自 FSA 地方当局名录；接口不可用时退回手工输入
  const loadAuthorities = useCallback(() => {
    if (authorities.length) return;
    api<Authority[]>("/api/sources/fsa/authorities").then((a) => { setAuthorities(a); setAuthFailed(false); }).catch(() => { setAuthFailed(true); });
  }, [authorities.length]);

  const loadBatches = useCallback(() => api<Batch[]>("/api/batches").then((b) => { setBatches(b); if (!batchKey && b[0]) setBatchKey(b[0].batch_key); }).catch(err), [batchKey]);
  const loadLeads = useCallback((key?: string) => {
    if (!key) return setLeads([]);
    api<Lead[]>(`/api/leads?batch_key=${encodeURIComponent(key)}&limit=500`).then(setLeads).catch(err);
  }, []);
  useEffect(() => { loadBatches(); }, [loadBatches]);
  useEffect(() => { loadLeads(batchKey); router.replace(batchKey ? `/leads?batch=${encodeURIComponent(batchKey)}` : "/leads"); }, [batchKey, loadLeads, router]);
  // 打开“补充数据”时，按批次的地区预选 FSA 地方当局
  useEffect(() => {
    if (!buildOpen) return;
    loadAuthorities();
    const region = batches.find((b) => b.batch_key === batchKey)?.region;
    const match = authorities.find((a) => a.name === region);
    if (match && fsaForm.getFieldValue("authority_id") == null) fsaForm.setFieldsValue({ authority_id: match.id });  // 不覆盖手工选择
  }, [buildOpen, authorities, batches, batchKey, fsaForm, loadAuthorities]);

  // 批量查找联系方式：每次请求处理 20 家（后端并行读官网），循环续跑直到没有待处理的，避免单个请求过长
  const collectContacts = async (key: string, onProgress: (text: string) => void): Promise<string> => {
    const k = encodeURIComponent(key);
    let r = await api<Run>(`/api/batches/${k}/runs`, json({ steps: ["contacts"], max_jobs: 20 }));
    const total = (t: Run["totals"]) => (t ? t.pending + t.running + t.succeeded + t.failed : 0);
    while (r.status === "running" && (r.totals?.pending ?? 0) > 0) {
      onProgress(`已处理 ${(r.totals?.succeeded ?? 0) + (r.totals?.failed ?? 0)}/${total(r.totals)} 家`);
      r = await api<Run>(`/api/runs/${r.id}/continue`, json({ max_jobs: 20 }));
    }
    const t = r.totals;
    if (!total(t)) return "没有需要查找的门店（已排除、没有官网和 Overture 数据，或之前已查过）";
    return `查找 ${total(t)} 家：成功 ${t?.succeeded ?? 0}${t?.failed ? `，失败 ${t.failed}` : ""}`;
  };

  const executeBuild = async (request: BuildRequest, startStep = 0, previousLines: string[] = []) => {
    const key = encodeURIComponent(request.key);
    const lines = previousLines.slice(0, startStep);
    let step = startStep;
    setCreating(true);
    setAutoProg({ step, lines });
    try {
      if (request.method === "csv") {
        const fd = new FormData();
        fd.append("batch_key", request.key);
        fd.append("file", request.file!);
        const result = await api<{ created_count: number; linked_count: number; skipped_count: number; error_count: number }>("/api/imports", { method: "POST", body: fd });
        setAutoProg({ step: 4, lines: [`新增 ${result.created_count}，关联 ${result.linked_count}，跳过 ${result.skipped_count}，错误 ${result.error_count}；有错误的行请修正后重新导入。`] });
        return;
      }
      if (step === 0) {
        const f = await api<{ fetched: number; pool: number; selected: number; created: number; linked: number }>(`/api/batches/${key}/sync/fsa`, json({ authority_id: request.authority_id, business_type_id: 1, exclude_awaiting: request.exclude_awaiting, sample_n: request.sample_n, seed: request.seed }));
        lines.push(`餐厅、咖啡馆、食堂共 ${f.fetched} 家，筛选后可选 ${f.pool} 家，选入 ${f.selected} 家（新增 ${f.created}，关联已有 ${f.linked}）`);
        setAutoProg({ step: (step = 1), lines: [...lines] });
      }
      if (step === 1) {
        const o = await api<{ leads: number; matched: number; website_set: number; phone_found: number }>(`/api/batches/${key}/enrich/overture`, json({}));
        lines.push(`匹配 ${o.matched}/${o.leads}，补官网 ${o.website_set}，有电话 ${o.phone_found}`);
        setAutoProg({ step: (step = 2), lines: [...lines] });
      }
      if (step === 2) {
        const sc = await api<{ counts: Record<string, number> }>(`/api/batches/${key}/screen`, { method: "POST" });
        lines.push(Object.entries(sc.counts).map(([k, n]) => `${SCREEN_ZH[k] ?? k} ${n}`).join("，"));
        setAutoProg({ step: (step = 3), lines: [...lines] });
      }
      const summary = await collectContacts(request.key, (text) => setAutoProg({ step: 3, lines: [...lines, text] }));
      lines.push(summary);
      setAutoProg({ step: 4, lines: [...lines] });
    } catch (e) {
      setAutoProg({ step, lines: [...lines], error: (e as Error).message });
    } finally {
      setCreating(false);
      loadLeads(request.key);
      loadBatches();
    }
  };

  const createBatch = async (v: CreateValues) => {
    const authority = authorities.find((a) => a.name === v.region);
    if (createMethod === "auto" && !authority) return message.error("请选择可用地区；名录暂不可用时可重试加载或改为导入 CSV。");
    if (createMethod === "csv" && !csvFile) return message.error("请先选择 CSV 文件");
    const key = v.batch_key?.trim() || listName(v.region);
    setCreating(true);
    try {
      await api("/api/batches", json({ batch_key: key, region: v.region, notes: v.notes, country: "GB", source_name: createMethod === "auto" ? "fsa" : createMethod === "csv" ? "csv" : "manual", source_licence: createMethod === "auto" ? "OGL-3.0" : null }));
      setBatchKey(key);
      loadBatches();
      if (createMethod === "empty") {
        message.success("空名单已创建，可稍后导入或补充数据");
        setCreating(false);
        return setNewOpen(false);
      }
      const request: BuildRequest = { key, method: createMethod, authority_id: authority?.id, sample_n: v.sample_n || null, seed: randomSeed(), exclude_awaiting: v.exclude_awaiting ?? false, file: csvFile || undefined };
      setBuildRequest(request);
      await executeBuild(request);
    } catch (e) {
      setCreating(false);
      err(e as Error);
    }
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

  const filtered = useMemo(() => leads.filter((l) => (!screen || l.screening_class === screen) && (!q || l.name.toLowerCase().includes(q.toLowerCase()) || (l.postcode ?? "").toLowerCase().includes(q.toLowerCase()))), [leads, screen, q]);
  const stats = useMemo(() => ({ total: leads.length, website: leads.filter((l) => l.website).length, candidate: leads.filter((l) => l.screening_class === "candidate").length, unchecked: leads.filter((l) => l.screening_class === "unchecked").length }), [leads]);
  const run = (name: string, p: Promise<unknown>, done: (r: never) => string) => { setBusy(name); p.then((r) => { message.success(done(r as never)); loadLeads(batchKey); loadBatches(); }).catch(err).finally(() => setBusy(null)); };

  return (
    <>
      <HeroBand kicker="LEADS" title="批次与线索" subtitle="用 FSA 名录自动建立候选，Overture 补官网，规则预筛后交人工确认类型。"
        extra={<>
          <Select style={{ width: 260 }} value={batchKey} disabled={creating} onChange={setBatchKey} placeholder="选择名单" options={batches.map((b) => ({ value: b.batch_key, label: `${b.batch_key}（${b.region ?? b.country}，${b.candidate_count ?? "?"} 家）` }))} />
          <Button type="primary" aria-label="建立名单" icon={<CloudDownloadOutlined />} disabled={!mounted || creating} onClick={() => { setAutoProg(null); setBuildRequest(null); setCsvFile(null); setCreateMethod("auto"); generatedName.current = ""; setNewOpen(true); loadAuthorities(); }}>建立名单</Button>
          <Button danger disabled={!batchKey || creating} onClick={openDelete}>删除批次</Button>
          <Button disabled={!batchKey || creating} onClick={() => { fsaForm.resetFields(["authority_id"]); setContactProg(null); setBuildOpen(true); }}>补充数据</Button>
        </>} />

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} md={6}><StatCard icon={<ShopOutlined />} title="门店" value={stats.total} hint="本批次去重门店" /></Col>
        <Col xs={12} md={6}><StatCard icon={<GlobalOutlined />} color="#d97706" title="有官网" value={stats.website} hint={stats.total ? `${Math.round((stats.website / stats.total) * 100)}% 覆盖` : undefined} /></Col>
        <Col xs={12} md={6}><StatCard icon={<CheckCircleOutlined />} color="#15803d" title="候选（人工确认）" value={stats.candidate} onClick={() => setScreen("candidate")} /></Col>
        <Col xs={12} md={6}><StatCard icon={<UserOutlined />} color="#7c3aed" title="待人工筛选" value={stats.unchecked} hint="点击只看待筛选" onClick={() => setScreen("unchecked")} /></Col>
      </Row>

      <Card size="small" title="线索" extra={<Space>
        <Input.Search allowClear placeholder="搜索名称 / 邮编" style={{ width: 220 }} onSearch={setQ} onChange={(e) => !e.target.value && setQ("")} />
        <Select allowClear placeholder="筛选分类" style={{ width: 160 }} value={screen} onChange={setScreen} options={SCREENING.map((s) => ({ value: s, label: SCREEN_ZH[s] ?? s }))} />
        <Upload accept=".csv" showUploadList={false} customRequest={({ file }) => { if (!batchKey) return message.warning("先选择批次"); const fd = new FormData(); fd.append("batch_key", batchKey); fd.append("file", file as File); run("csv", api("/api/imports", { method: "POST", body: fd }), (r: { created_count: number; linked_count: number; skipped_count: number; error_count: number }) => `导入：新增 ${r.created_count}，关联 ${r.linked_count}，跳过 ${r.skipped_count}，错误 ${r.error_count}`); }}>
          <Button disabled={!batchKey}>追加 CSV</Button>
        </Upload>
        <Button disabled={!batchKey} loading={busy === "run"} onClick={() => run("run", api(`/api/batches/${encodeURIComponent(batchKey!)}/runs`, json({ steps: ["fetch", "analyze"] })), (r: { status: string; totals: Record<string, number> }) => `批量运行 ${label(r.status)}：${JSON.stringify(r.totals)}`)}>批量抓取 + 分析</Button>
        <a href={batchKey ? `/api/batches/${encodeURIComponent(batchKey!)}/export.csv` : undefined}><Button disabled={!batchKey}>导出 CSV</Button></a>
      </Space>}>
        <Table<Lead> rowKey="id" size="small" dataSource={filtered} pagination={{ pageSize: 50, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
          columns={[
            { title: "门店", dataIndex: "name", render: (v, r) => <Space wrap><Link href={`/leads/${r.id}`} style={{ fontWeight: 600 }}>{v}</Link>{r.inspection_pending && <Tag color="gold">待首次检查</Tag>}</Space>, sorter: (a, b) => a.name.localeCompare(b.name) },
            { title: "来源键", dataIndex: "source_key", width: 120 },
            { title: "邮编", dataIndex: "postcode", width: 100 },
            { title: "官网", dataIndex: "website", ellipsis: true, render: (v, r) => (v ? <a href={v} target="_blank" rel="noreferrer"><GlobalOutlined style={{ marginRight: 6, color: "#d97706" }} />{v.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")}</a> : <Link href={`/leads/${r.id}`} title="进入详情页搜索并核对官网">搜索补官网</Link>) },
            { title: "筛选", dataIndex: "screening_class", width: 120, render: (v, r) => <ScreenTag value={v} reason={r.screening_reason} />, filters: SCREENING.map((s) => ({ text: SCREEN_ZH[s] ?? s, value: s })), onFilter: (val, r) => r.screening_class === val },
            { title: "联系方式", dataIndex: "contact_count", width: 90, sorter: (a, b) => a.contact_count - b.contact_count, render: (v) => (v ? <Tag color="blue" style={{ marginInlineEnd: 0 }}>{v} 项</Tag> : <span style={{ color: "#9ca3af" }}>-</span>) },
            { title: "主体", dataIndex: "entity_status", width: 90, render: (v) => (v === "unknown" ? <span className="beacon-muted">未知</span> : <Tag color="green" style={{ marginInlineEnd: 0 }}>{label(v)}</Tag>) },
          ]} />
      </Card>

      <Modal title="建立名单" forceRender={mounted} open={newOpen} onCancel={() => { if (!creating) setNewOpen(false); }} footer={null} destroyOnHidden maskClosable={false} closable={!creating}>
        {autoProg ? (
          <>
            <Steps direction="vertical" size="small" current={buildRequest?.method === "csv" ? (autoProg.step === 4 ? 1 : 0) : autoProg.step} status={autoProg.error ? "error" : autoProg.step === 4 ? "finish" : "process"} items={buildRequest?.method === "csv" ? [{ title: "导入 CSV", description: autoProg.lines[0] }] : [
              { title: "获取餐厅", description: autoProg.lines[0] },
              { title: "补充官网与电话", description: autoProg.lines[1] },
              { title: "预筛", description: autoProg.lines[2] },
              { title: "查找联系方式", description: autoProg.lines[3] },
            ]} />
            {autoProg.error && <Alert type="error" showIcon style={{ marginBottom: 12 }} message="这一步失败，名单已保留" description={`${autoProg.error}。可直接重试这一步，已完成的步骤不用重做。关闭后可在“补充数据”中继续处理。`} />}
            {autoProg.step === 4 && <Alert type="success" showIcon style={{ marginBottom: 12 }} message={buildRequest?.method === "csv" ? "CSV 导入处理完成" : "名单与联系方式已建好"} description="请核对处理结果并确认门店类型。联系方式只是记录，渠道准入仍需逐条核对。" />}
            <Space style={{ width: "100%", justifyContent: "flex-end" }}>
              {autoProg.error && buildRequest && <Button type="primary" onClick={() => executeBuild(buildRequest, autoProg.step, autoProg.lines)}>重试这一步</Button>}
              <Button aria-label={creating ? "正在处理" : "完成"} disabled={creating} loading={creating} onClick={() => setNewOpen(false)}>{creating ? "正在处理…" : "完成"}</Button>
            </Space>
          </>
        ) : (
          <Form form={createForm} layout="vertical" initialValues={{ sample_n: 50, exclude_awaiting: false }} onFinish={createBatch} onValuesChange={(changed, values) => {
            if ("region" in changed && (!values.batch_key || values.batch_key === generatedName.current)) {
              generatedName.current = listName(values.region);
              createForm.setFieldValue("batch_key", generatedName.current);
            }
          }}>
            <Form.Item label="创建方式"><Radio.Group value={createMethod} onChange={(e) => setCreateMethod(e.target.value)} options={[{ value: "auto", label: "自动获取" }, { value: "csv", label: "导入 CSV" }, { value: "empty", label: "仅建空名单" }]} /></Form.Item>
            {authFailed && createMethod === "auto" && <Alert type="warning" showIcon message="地区名录暂不可用" description="可以重试加载，或选择导入 CSV。" action={<Button size="small" onClick={loadAuthorities}>重试加载</Button>} style={{ marginBottom: 12 }} />}
            <Form.Item name="region" label="地区" extra={createMethod === "auto" ? "地区总数包含所有食品经营场所；本次只获取餐厅、咖啡馆、食堂，数量通常少于地区总数。" : undefined} rules={[{ required: createMethod === "auto", message: "请选择地区" }]}>
              {authFailed && createMethod !== "auto" ? <Input placeholder="可选，例如 Camden" /> : <Select showSearch allowClear placeholder={createMethod === "auto" ? "搜索英国地区，例如 Camden" : "可选，选择名单所属地区"} optionFilterProp="label" loading={!authorities.length && !authFailed} options={authorities.map((a) => ({ value: a.name, label: `${a.name}${a.region ? `（${a.region}）` : ""} · 全部食品经营场所 ${a.count ?? "未知"} 家` }))} />}
            </Form.Item>
            {createMethod === "auto" && <Form.Item name="sample_n" label="获取餐厅数量" extra="默认随机选取 50 家，留空获取该地区全部餐厅、咖啡馆、食堂（可能上千家）；数量不代表优质客户数量。"><InputNumber min={1} max={5000} precision={0} style={{ width: "100%" }} placeholder="留空 = 全部" /></Form.Item>}
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
        )}
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

      {mounted && <Drawer forceRender title={`补充数据 · ${batchKey ?? ""}`} open={buildOpen} onClose={() => setBuildOpen(false)} width={520}>
        {authFailed && <Alert type="warning" message="地区名录暂不可用，其他补充步骤仍可操作" action={<Button size="small" onClick={loadAuthorities}>重试加载</Button>} style={{ marginBottom: 16 }} />}
        <Card size="small" title="第 1 步：从 FSA 名录建立候选" style={{ marginBottom: 16 }}>
          <Form form={fsaForm} initialValues={{ sample_n: 50, exclude_awaiting: false }} layout="vertical" onFinish={(v) => run("fsa", api(`/api/batches/${encodeURIComponent(batchKey!)}/sync/fsa`, json({ authority_id: v.authority_id, business_type_id: 1, exclude_awaiting: v.exclude_awaiting ?? false, sample_n: v.sample_n || null, seed: randomSeed() })), (r: { fetched: number; pool: number; selected: number; created: number; linked: number; skipped: number }) => `餐厅、咖啡馆、食堂共 ${r.fetched} 家，筛选后可选 ${r.pool} 家，选入 ${r.selected} 家，新增 ${r.created}，关联 ${r.linked}，跳过 ${r.skipped}`)}>
            <Form.Item name="authority_id" label="地方当局" extra="地区总数包含所有食品经营场所；本次只获取餐厅、咖啡馆、食堂。" rules={[{ required: true }]}>
              <Select showSearch placeholder="默认取批次的地区，可改" optionFilterProp="label" loading={!authorities.length && !authFailed}
                options={authorities.map((a) => ({ value: a.id, label: `${a.name}${a.region ? `（${a.region}）` : ""} · 全部食品经营场所 ${a.count ?? "未知"} 家` }))} />
            </Form.Item>
            <Form.Item name="sample_n" label="获取餐厅数量" extra="从餐厅、咖啡馆、食堂中随机选取指定数量，留空获取该类别全部；已在名单中的门店不会重复新增。"><InputNumber min={1} max={5000} precision={0} style={{ width: "100%" }} placeholder="留空 = 全部" /></Form.Item>
            <Collapse ghost items={[{ key: "filters", label: "高级筛选", children: <Form.Item name="exclude_awaiting" label="排除尚未首次检查的商家" valuePropName="checked" initialValue={false}><Switch /></Form.Item> }]} />
            <Button type="primary" htmlType="submit" loading={busy === "fsa"} block>拉取并建立候选</Button>
          </Form>
        </Card>
        <Card size="small" title="第 2 步：Overture 补官网与电话" style={{ marginBottom: 16 }}>
          <p style={{ color: "#6b7280", marginTop: 0 }}>按批次坐标范围下载 Overture 地点（首次下载约 1 分钟，范围大时更久，之后复用缓存），只填空缺官网，来源与置信度记入线索。</p>
          <Button loading={busy === "ov"} block onClick={() => run("ov", api(`/api/batches/${encodeURIComponent(batchKey!)}/enrich/overture`, json({})), (r: { leads: number; matched: number; website_set: number; phone_found: number; places: number }) => `Overture：${r.places} 个地点，匹配 ${r.matched}/${r.leads}，补官网 ${r.website_set}，有电话 ${r.phone_found}`)}>运行 Overture 补全</Button>
        </Card>
        <Card size="small" title="第 3 步：规则预筛" style={{ marginBottom: 16 }}>
          <p style={{ color: "#6b7280", marginTop: 0 }}>连锁（含 Overture 品牌）、咖啡店、机构、酒吧标为排除并注明规则；其余保持“待筛选”交人工；人工改过的不覆盖。</p>
          <Button loading={busy === "screen"} block onClick={() => run("screen", api(`/api/batches/${encodeURIComponent(batchKey!)}/screen`, { method: "POST" }), (r: { counts: Record<string, number> }) => `预筛：${Object.entries(r.counts).map(([k, v]) => `${k} ${v}`).join("，")}`)}>运行规则预筛</Button>
        </Card>
        <Card size="small" title="第 4 步：查找联系方式">
          <p style={{ color: "#6b7280", marginTop: 0 }}>对未被排除的门店，从官网和 Overture 数据里找邮箱、电话、WhatsApp、社媒账号和联系表单并自动记录（准入保持未知，不放行）。每家几秒；已查过的不重复查；同类过多（疑似分店列表）的留给人工在详情页勾选。</p>
          <Button loading={busy === "contacts"} block onClick={() => { if (!batchKey) return; setBusy("contacts"); setContactProg("开始…"); collectContacts(batchKey, setContactProg).then((t) => { message.success(t); setContactProg(t); loadLeads(batchKey); }).catch((e: Error) => { err(e); setContactProg(`中断：${e.message}。再点一次可从未完成的继续`); }).finally(() => setBusy(null)); }}>批量查找联系方式</Button>
          {contactProg && <p style={{ color: "#6b7280", margin: "8px 0 0" }}>{contactProg}</p>}
        </Card>
      </Drawer>}
    </>
  );
}

export default function LeadsPage() {
  return <Suspense><LeadsInner /></Suspense>;
}
