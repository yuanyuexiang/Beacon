"use client";
import { Alert, Button, Card, Col, Descriptions, Divider, Drawer, Form, Input, InputNumber, Modal, Row, Select, Space, Steps, Switch, Table, Tag, Upload, message } from "antd";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { api, json } from "@/lib/api";
import { CheckCircleOutlined, CloudDownloadOutlined, GlobalOutlined, ShopOutlined, UserOutlined } from "@ant-design/icons";
import { HeroBand, SCREEN_ZH, ScreenTag, StatCard } from "@/components/ui";
import { label } from "@/lib/format";

type Batch = { id: string; batch_key: string; country: string; region: string | null; source_name: string; candidate_count: number | null };
type Lead = { id: string; source_key: string; name: string; postcode: string | null; website: string | null; screening_class: string; screening_reason: string | null; entity_status: string; contact_count: number };
type Run = { id: string; status: string; totals: { pending: number; running: number; succeeded: number; failed: number } | null };
type Authority = { id: number; name: string; region: string | null; count: number | null };
type DeletePreview = { batch_key: string; leads_in_batch: number; leads_deleted: number; leads_kept_other_batches: number; leads_kept_suppressed: number; menu_assets: number; analyses: number; content_pieces: number; contacts: number; tasks: number; tasks_sent: number; events: number; import_runs: number; batch_runs: number; cost_entries: number };

const SCREENING = ["unchecked", "candidate", "unknown", "excluded_cafe", "excluded_chain", "excluded_canteen", "excluded_community", "excluded_institution", "excluded_pub", "excluded_closed", "excluded_other"];

function LeadsInner() {
  const sp = useSearchParams();
  const router = useRouter();
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
  // 新建批次后自动建名单的进度：step 为正在进行的步骤（3 = 全部完成）
  const [autoProg, setAutoProg] = useState<{ step: number; lines: string[]; error?: string } | null>(null);
  const [contactProg, setContactProg] = useState<string | null>(null);
  const err = (e: Error) => message.error(e.message);
  // 地区取自 FSA 地方当局名录；接口不可用时退回手工输入
  const loadAuthorities = useCallback(() => {
    if (authorities.length) return;
    api<Authority[]>("/api/sources/fsa/authorities").then((a) => { setAuthorities(a); setAuthFailed(false); }).catch((e: Error) => { setAuthFailed(true); message.error(e.message); });
  }, [authorities.length]);

  const loadBatches = useCallback(() => api<Batch[]>("/api/batches").then((b) => { setBatches(b); if (!batchKey && b[0]) setBatchKey(b[0].batch_key); }).catch(err), [batchKey]);
  const loadLeads = useCallback((key?: string) => {
    if (!key) return setLeads([]);
    api<Lead[]>(`/api/leads?batch_key=${encodeURIComponent(key)}&limit=500`).then(setLeads).catch(err);
  }, []);
  useEffect(() => { loadBatches(); }, [loadBatches]);
  useEffect(() => { loadLeads(batchKey); router.replace(batchKey ? `/leads?batch=${encodeURIComponent(batchKey)}` : "/leads"); }, [batchKey, loadLeads, router]);
  // 打开“自动建名单”时，按批次的地区预选 FSA 地方当局
  useEffect(() => {
    if (!buildOpen) return;
    loadAuthorities();
    const region = batches.find((b) => b.batch_key === batchKey)?.region;
    const match = authorities.find((a) => a.name === region);
    if (match && fsaForm.getFieldValue("authority_id") == null) fsaForm.setFieldsValue({ authority_id: match.id });  // 不覆盖手工选择
  }, [buildOpen, authorities, batches, batchKey, fsaForm, loadAuthorities]);

  // 批量查找联系方式：每次请求只处理几家，循环续跑直到没有待处理的，避免单个请求过长
  const collectContacts = async (key: string, onProgress: (text: string) => void): Promise<string> => {
    const k = encodeURIComponent(key);
    let r = await api<Run>(`/api/batches/${k}/runs`, json({ steps: ["contacts"], max_jobs: 5 }));
    const total = (t: Run["totals"]) => (t ? t.pending + t.running + t.succeeded + t.failed : 0);
    while (r.status === "running" && (r.totals?.pending ?? 0) > 0) {
      onProgress(`已处理 ${(r.totals?.succeeded ?? 0) + (r.totals?.failed ?? 0)}/${total(r.totals)} 家`);
      r = await api<Run>(`/api/runs/${r.id}/continue`, json({ max_jobs: 5 }));
    }
    const t = r.totals;
    if (!total(t)) return "没有需要查找的门店（已排除、没有官网和 Overture 数据，或之前已查过）";
    return `查找 ${total(t)} 家：成功 ${t?.succeeded ?? 0}${t?.failed ? `，失败 ${t.failed}` : ""}`;
  };

  // 新建批次；勾选“创建后自动建名单”时依次跑 FSA 同步、Overture 补全、规则预筛，任一步失败即停并保留已完成的结果
  const createBatch = async (v: { batch_key: string; region: string; source_name: string; notes?: string; auto?: boolean; sample_n?: number | null; seed?: number | null }) => {
    const { auto, sample_n, seed, ...body } = v;
    const authority = authorities.find((a) => a.name === v.region);
    try {
      await api("/api/batches", json({ ...body, country: "GB", source_licence: "OGL-3.0" }));
    } catch (e) {
      return err(e as Error);
    }
    setBatchKey(v.batch_key);
    loadBatches();
    if (!auto || !authority) {
      message.success("批次已创建");
      return setNewOpen(false);
    }
    const key = encodeURIComponent(v.batch_key);
    const lines: string[] = [];
    let step = 0;
    try {
      setAutoProg({ step, lines: [] });
      const f = await api<{ fetched: number; pool: number; selected: number; created: number; linked: number }>(`/api/batches/${key}/sync/fsa`, json({ authority_id: authority.id, business_type_id: 1, exclude_awaiting: true, sample_n: sample_n || null, seed: seed ?? null }));
      lines.push(`FSA：名录 ${f.fetched} 家，可选 ${f.pool}，选入 ${f.selected}（新增 ${f.created}，关联已有 ${f.linked}）`);
      setAutoProg({ step: (step = 1), lines: [...lines] });
      const o = await api<{ leads: number; matched: number; website_set: number; phone_found: number }>(`/api/batches/${key}/enrich/overture`, json({}));
      lines.push(`Overture：匹配 ${o.matched}/${o.leads}，补官网 ${o.website_set}，有电话 ${o.phone_found}`);
      setAutoProg({ step: (step = 2), lines: [...lines] });
      const sc = await api<{ counts: Record<string, number> }>(`/api/batches/${key}/screen`, { method: "POST" });
      lines.push(`预筛：${Object.entries(sc.counts).map(([k, n]) => `${SCREEN_ZH[k] ?? k} ${n}`).join("，")}`);
      setAutoProg({ step: (step = 3), lines: [...lines] });
      const summary = await collectContacts(v.batch_key, (text) => setAutoProg({ step: 3, lines: [...lines, text] }));
      lines.push(`联系方式：${summary}`);
      setAutoProg({ step: 4, lines: [...lines] });
    } catch (e) {
      setAutoProg({ step, lines: [...lines], error: (e as Error).message });
    } finally {
      loadLeads(v.batch_key);
      loadBatches();
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
          <Select style={{ width: 260 }} value={batchKey} onChange={setBatchKey} placeholder="选择批次" options={batches.map((b) => ({ value: b.batch_key, label: `${b.batch_key}（${b.region ?? b.country}，${b.candidate_count ?? "?"} 家）` }))} />
          <Button onClick={() => { setAutoProg(null); setNewOpen(true); loadAuthorities(); }}>新建批次</Button>
          <Button danger disabled={!batchKey} onClick={openDelete}>删除批次</Button>
          <Button type="primary" icon={<CloudDownloadOutlined />} disabled={!batchKey} onClick={() => { fsaForm.resetFields(["authority_id"]); setContactProg(null); setBuildOpen(true); }}>自动建名单</Button>
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
          <Button disabled={!batchKey}>导入 CSV</Button>
        </Upload>
        <Button disabled={!batchKey} loading={busy === "run"} onClick={() => run("run", api(`/api/batches/${batchKey}/runs`, json({ steps: ["fetch", "analyze"] })), (r: { status: string; totals: Record<string, number> }) => `批量运行 ${label(r.status)}：${JSON.stringify(r.totals)}`)}>批量抓取 + 分析</Button>
        <a href={batchKey ? `/api/batches/${batchKey}/export.csv` : undefined}><Button disabled={!batchKey}>导出 CSV</Button></a>
      </Space>}>
        <Table<Lead> rowKey="id" size="small" dataSource={filtered} pagination={{ pageSize: 50, showSizeChanger: true, showTotal: (t) => `共 ${t} 条` }}
          columns={[
            { title: "门店", dataIndex: "name", render: (v, r) => <Link href={`/leads/${r.id}`} style={{ fontWeight: 600 }}>{v}</Link>, sorter: (a, b) => a.name.localeCompare(b.name) },
            { title: "来源键", dataIndex: "source_key", width: 120 },
            { title: "邮编", dataIndex: "postcode", width: 100 },
            { title: "官网", dataIndex: "website", ellipsis: true, render: (v) => (v ? <a href={v} target="_blank" rel="noreferrer"><GlobalOutlined style={{ marginRight: 6, color: "#d97706" }} />{v.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")}</a> : <Tag style={{ marginInlineEnd: 0 }}>无</Tag>) },
            { title: "筛选", dataIndex: "screening_class", width: 120, render: (v, r) => <ScreenTag value={v} reason={r.screening_reason} />, filters: SCREENING.map((s) => ({ text: SCREEN_ZH[s] ?? s, value: s })), onFilter: (val, r) => r.screening_class === val },
            { title: "联系方式", dataIndex: "contact_count", width: 90, sorter: (a, b) => a.contact_count - b.contact_count, render: (v) => (v ? <Tag color="blue" style={{ marginInlineEnd: 0 }}>{v} 项</Tag> : <span style={{ color: "#9ca3af" }}>-</span>) },
            { title: "主体", dataIndex: "entity_status", width: 90, render: label },
          ]} />
      </Card>

      <Modal title="新建批次" open={newOpen} onCancel={() => setNewOpen(false)} footer={null} destroyOnHidden maskClosable={false} closable={!autoProg || autoProg.step === 4 || !!autoProg.error}>
        {autoProg ? (
          <>
            <Steps direction="vertical" size="small" current={autoProg.step} status={autoProg.error ? "error" : autoProg.step === 4 ? "finish" : "process"} items={[
              { title: "从 FSA 名录建立候选", description: autoProg.lines[0] },
              { title: "Overture 补官网与电话（首次下载约 1 分钟，范围大时更久）", description: autoProg.lines[1] },
              { title: "规则预筛", description: autoProg.lines[2] },
              { title: "查找联系方式（未排除的门店，每家几秒）", description: autoProg.lines[3] },
            ]} />
            {autoProg.error && <Alert type="error" showIcon style={{ marginBottom: 12 }} message="这一步失败，批次已创建" description={`${autoProg.error}。可在「自动建名单」里从失败的一步继续，已完成的步骤不用重做。`} />}
            {autoProg.step === 4 && <Alert type="success" showIcon style={{ marginBottom: 12 }} message="批次已创建，名单与联系方式已建好" description="接下来在线索列表里人工确认“待筛选”的门店类型。联系方式只是记录，准入仍需逐条核对。" />}
            <Button type="primary" block disabled={autoProg.step < 4 && !autoProg.error} loading={autoProg.step < 4 && !autoProg.error} onClick={() => setNewOpen(false)}>{autoProg.step === 4 || autoProg.error ? "完成" : "正在建名单…"}</Button>
          </>
        ) : (
          <Form layout="vertical" initialValues={{ source_name: "fsa", auto: true, sample_n: 50, seed: Number(new Date().toISOString().slice(0, 10).replace(/-/g, "")) }} onFinish={createBatch}>
            <Form.Item name="batch_key" label="批次键" rules={[{ required: true }]}><Input placeholder="例如 v3-camden" /></Form.Item>
            <Form.Item name="region" label="地区（英国地方当局，来自 FSA 名录）" rules={[{ required: true, message: "请选择地区" }]}>
              {authFailed
                ? <Input placeholder="FSA 名录暂不可用，请手工填写，例如 Camden" />
                : <Select showSearch placeholder="输入名称搜索，例如 Camden" optionFilterProp="label" loading={!authorities.length} options={authorities.map((a) => ({ value: a.name, label: `${a.name}${a.region ? `（${a.region}）` : ""} · ${a.count ?? "?"} 家` }))} />}
            </Form.Item>
            <Form.Item name="source_name" label="来源"><Input /></Form.Item>
            <Form.Item name="notes" label="备注"><Input.TextArea rows={2} /></Form.Item>
            <Divider style={{ margin: "4px 0 12px" }} />
            <Form.Item name="auto" label="创建后自动建名单" valuePropName="checked" extra={authFailed ? "FSA 名录不可用，无法自动建名单；创建后可在「自动建名单」里手动操作" : "依次执行：FSA 餐厅名录抽样 → Overture 补官网与电话 → 规则预筛 → 查找联系方式"}>
              <Switch disabled={authFailed} />
            </Form.Item>
            <Form.Item noStyle shouldUpdate={(p, c) => p.auto !== c.auto}>
              {({ getFieldValue }) => getFieldValue("auto") && !authFailed && (
                <Row gutter={12}>
                  <Col span={12}><Form.Item name="sample_n" label="抽样数" extra="留空为该地区全部餐厅，可能上千家"><InputNumber min={1} max={5000} style={{ width: "100%" }} placeholder="空 = 全量" /></Form.Item></Col>
                  <Col span={12}><Form.Item name="seed" label="随机种子" extra="同一种子可复现同一份抽样"><InputNumber style={{ width: "100%" }} /></Form.Item></Col>
                </Row>
              )}
            </Form.Item>
            <Button type="primary" htmlType="submit" block>创建</Button>
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
            {delPreview.tasks_sent > 0 && <Alert type="warning" showIcon style={{ marginBottom: 12 }} message={`有 ${delPreview.tasks_sent} 个任务已人工发送，真实联系记录会一并删除`} />}
            {delPreview.leads_kept_suppressed > 0 && <Alert type="info" showIcon style={{ marginBottom: 12 }} message="有拒收 / 退订记录的门店不会删除，以保证抑制继续生效；它们会脱离本批次" />}
            <p style={{ marginBottom: 6 }}>输入批次键 <b>{batchKey}</b> 以确认：</p>
            <Input value={delConfirm} onChange={(e) => setDelConfirm(e.target.value)} placeholder={batchKey} />
          </>
        )}
      </Modal>

      <Drawer forceRender title={`自动建名单 · ${batchKey ?? ""}`} open={buildOpen} onClose={() => setBuildOpen(false)} width={520}>
        <Card size="small" title="第 1 步：从 FSA 名录建立候选" style={{ marginBottom: 16 }}>
          <Form form={fsaForm} layout="vertical" onFinish={(v) => run("fsa", api(`/api/batches/${batchKey}/sync/fsa`, json({ authority_id: v.authority_id, business_type_id: 1, exclude_awaiting: v.exclude_awaiting ?? true, sample_n: v.sample_n || null, seed: v.seed ?? null })), (r: { fetched: number; pool: number; selected: number; created: number; linked: number; skipped: number }) => `FSA：名录 ${r.fetched}，池 ${r.pool}，选入 ${r.selected}，新增 ${r.created}，关联 ${r.linked}，跳过 ${r.skipped}`)}>
            <Form.Item name="authority_id" label="地方当局" rules={[{ required: true }]}>
              <Select showSearch placeholder="默认取批次的地区，可改" optionFilterProp="label" loading={!authorities.length && !authFailed}
                options={authorities.map((a) => ({ value: a.id, label: `${a.name}${a.region ? `（${a.region}）` : ""} · ${a.count ?? ""}` }))} />
            </Form.Item>
            <Row gutter={12}>
              <Col span={8}><Form.Item name="sample_n" label="抽样数"><InputNumber min={1} max={5000} style={{ width: "100%" }} placeholder="空=全量" /></Form.Item></Col>
              <Col span={8}><Form.Item name="seed" label="随机种子"><InputNumber style={{ width: "100%" }} /></Form.Item></Col>
              <Col span={8}><Form.Item name="exclude_awaiting" label="排除待检查" valuePropName="checked" initialValue={true}><Switch /></Form.Item></Col>
            </Row>
            <Button type="primary" htmlType="submit" loading={busy === "fsa"} block>拉取并建立候选</Button>
          </Form>
        </Card>
        <Card size="small" title="第 2 步：Overture 补官网与电话" style={{ marginBottom: 16 }}>
          <p style={{ color: "#6b7280", marginTop: 0 }}>按批次坐标范围下载 Overture 地点（首次下载约 1 分钟，范围大时更久，之后复用缓存），只填空缺官网，来源与置信度记入线索。</p>
          <Button loading={busy === "ov"} block onClick={() => run("ov", api(`/api/batches/${batchKey}/enrich/overture`, json({})), (r: { leads: number; matched: number; website_set: number; phone_found: number; places: number }) => `Overture：${r.places} 个地点，匹配 ${r.matched}/${r.leads}，补官网 ${r.website_set}，有电话 ${r.phone_found}`)}>运行 Overture 补全</Button>
        </Card>
        <Card size="small" title="第 3 步：规则预筛" style={{ marginBottom: 16 }}>
          <p style={{ color: "#6b7280", marginTop: 0 }}>连锁（含 Overture 品牌）、咖啡店、机构、酒吧标为排除并注明规则；其余保持“待筛选”交人工；人工改过的不覆盖。</p>
          <Button loading={busy === "screen"} block onClick={() => run("screen", api(`/api/batches/${batchKey}/screen`, { method: "POST" }), (r: { counts: Record<string, number> }) => `预筛：${Object.entries(r.counts).map(([k, v]) => `${k} ${v}`).join("，")}`)}>运行规则预筛</Button>
        </Card>
        <Card size="small" title="第 4 步：查找联系方式">
          <p style={{ color: "#6b7280", marginTop: 0 }}>对未被排除的门店，从官网和 Overture 数据里找邮箱、电话、WhatsApp、社媒账号和联系表单并自动记录（准入保持未知，不放行）。每家几秒；已查过的不重复查；同类过多（疑似分店列表）的留给人工在详情页勾选。</p>
          <Button loading={busy === "contacts"} block onClick={() => { if (!batchKey) return; setBusy("contacts"); setContactProg("开始…"); collectContacts(batchKey, setContactProg).then((t) => { message.success(t); setContactProg(t); loadLeads(batchKey); }).catch((e: Error) => { err(e); setContactProg(`中断：${e.message}。再点一次可从未完成的继续`); }).finally(() => setBusy(null)); }}>批量查找联系方式</Button>
          {contactProg && <p style={{ color: "#6b7280", margin: "8px 0 0" }}>{contactProg}</p>}
        </Card>
      </Drawer>
    </>
  );
}

export default function LeadsPage() {
  return <Suspense><LeadsInner /></Suspense>;
}
