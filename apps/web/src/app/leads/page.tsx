"use client";
import { Button, Card, Col, Drawer, Form, Input, InputNumber, Modal, Row, Select, Space, Switch, Table, Tag, Upload, message } from "antd";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { api, json } from "@/lib/api";
import { CheckCircleOutlined, CloudDownloadOutlined, GlobalOutlined, ShopOutlined, UserOutlined } from "@ant-design/icons";
import { HeroBand, SCREEN_ZH, ScreenTag, StatCard } from "@/components/ui";
import { label } from "@/lib/format";

type Batch = { id: string; batch_key: string; country: string; region: string | null; source_name: string; candidate_count: number | null };
type Lead = { id: string; source_key: string; name: string; postcode: string | null; website: string | null; screening_class: string; screening_reason: string | null; entity_status: string };
type Authority = { id: number; name: string; region: string | null; count: number | null };

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
  const err = (e: Error) => message.error(e.message);

  const loadBatches = useCallback(() => api<Batch[]>("/api/batches").then((b) => { setBatches(b); if (!batchKey && b[0]) setBatchKey(b[0].batch_key); }).catch(err), [batchKey]);
  const loadLeads = useCallback((key?: string) => {
    if (!key) return setLeads([]);
    api<Lead[]>(`/api/leads?batch_key=${encodeURIComponent(key)}&limit=500`).then(setLeads).catch(err);
  }, []);
  useEffect(() => { loadBatches(); }, [loadBatches]);
  useEffect(() => { loadLeads(batchKey); if (batchKey) router.replace(`/leads?batch=${encodeURIComponent(batchKey)}`); }, [batchKey, loadLeads, router]);

  const filtered = useMemo(() => leads.filter((l) => (!screen || l.screening_class === screen) && (!q || l.name.toLowerCase().includes(q.toLowerCase()) || (l.postcode ?? "").toLowerCase().includes(q.toLowerCase()))), [leads, screen, q]);
  const stats = useMemo(() => ({ total: leads.length, website: leads.filter((l) => l.website).length, candidate: leads.filter((l) => l.screening_class === "candidate").length, unchecked: leads.filter((l) => l.screening_class === "unchecked").length }), [leads]);
  const run = (name: string, p: Promise<unknown>, done: (r: never) => string) => { setBusy(name); p.then((r) => { message.success(done(r as never)); loadLeads(batchKey); loadBatches(); }).catch(err).finally(() => setBusy(null)); };

  return (
    <>
      <HeroBand kicker="LEADS" title="批次与线索" subtitle="用 FSA 名录自动建立候选，Overture 补官网，规则预筛后交人工确认类型。"
        extra={<>
          <Select style={{ width: 260 }} value={batchKey} onChange={setBatchKey} placeholder="选择批次" options={batches.map((b) => ({ value: b.batch_key, label: `${b.batch_key}（${b.region ?? b.country}，${b.candidate_count ?? "?"} 家）` }))} />
          <Button onClick={() => setNewOpen(true)}>新建批次</Button>
          <Button type="primary" icon={<CloudDownloadOutlined />} disabled={!batchKey} onClick={() => setBuildOpen(true)}>自动建名单</Button>
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
            { title: "主体", dataIndex: "entity_status", width: 90, render: label },
          ]} />
      </Card>

      <Modal title="新建批次" open={newOpen} onCancel={() => setNewOpen(false)} footer={null} destroyOnHidden>
        <Form layout="vertical" onFinish={(v) => api("/api/batches", json({ ...v, source_licence: "OGL-3.0" })).then(() => { message.success("批次已创建"); setNewOpen(false); setBatchKey(v.batch_key); loadBatches(); }).catch(err)}>
          <Form.Item name="batch_key" label="批次键" rules={[{ required: true }]}><Input placeholder="例如 v3-camden" /></Form.Item>
          <Form.Item name="region" label="地区" rules={[{ required: true }]}><Input placeholder="例如 Camden" /></Form.Item>
          <Form.Item name="country" label="国家" initialValue="GB"><Input /></Form.Item>
          <Form.Item name="source_name" label="来源" initialValue="fsa"><Input /></Form.Item>
          <Form.Item name="notes" label="备注"><Input.TextArea rows={2} /></Form.Item>
          <Button type="primary" htmlType="submit" block>创建</Button>
        </Form>
      </Modal>

      <Drawer title={`自动建名单 · ${batchKey ?? ""}`} open={buildOpen} onClose={() => setBuildOpen(false)} width={520}>
        <Card size="small" title="第 1 步：从 FSA 名录建立候选" style={{ marginBottom: 16 }}>
          <Form layout="vertical" onFinish={(v) => run("fsa", api(`/api/batches/${batchKey}/sync/fsa`, json({ authority_id: v.authority_id, business_type_id: 1, exclude_awaiting: v.exclude_awaiting ?? true, sample_n: v.sample_n || null, seed: v.seed ?? null })), (r: { fetched: number; pool: number; selected: number; created: number; linked: number; skipped: number }) => `FSA：名录 ${r.fetched}，池 ${r.pool}，选入 ${r.selected}，新增 ${r.created}，关联 ${r.linked}，跳过 ${r.skipped}`)}>
            <Form.Item name="authority_id" label="地方当局" rules={[{ required: true }]}>
              <Select showSearch placeholder="点击加载列表" optionFilterProp="label" onDropdownVisibleChange={(o) => { if (o && authorities.length === 0) api<Authority[]>("/api/sources/fsa/authorities").then(setAuthorities).catch(err); }}
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
          <p style={{ color: "#6b7280", marginTop: 0 }}>按批次坐标范围下载 Overture 地点（首次约 30 秒，之后复用缓存），只填空缺官网，来源与置信度记入线索。</p>
          <Button loading={busy === "ov"} block onClick={() => run("ov", api(`/api/batches/${batchKey}/enrich/overture`, json({})), (r: { leads: number; matched: number; website_set: number; phone_found: number; places: number }) => `Overture：${r.places} 个地点，匹配 ${r.matched}/${r.leads}，补官网 ${r.website_set}，有电话 ${r.phone_found}`)}>运行 Overture 补全</Button>
        </Card>
        <Card size="small" title="第 3 步：规则预筛">
          <p style={{ color: "#6b7280", marginTop: 0 }}>连锁（含 Overture 品牌）、咖啡店、机构、酒吧标为排除并注明规则；其余保持“待筛选”交人工；人工改过的不覆盖。</p>
          <Button loading={busy === "screen"} block onClick={() => run("screen", api(`/api/batches/${batchKey}/screen`, { method: "POST" }), (r: { counts: Record<string, number> }) => `预筛：${Object.entries(r.counts).map(([k, v]) => `${k} ${v}`).join("，")}`)}>运行规则预筛</Button>
        </Card>
      </Drawer>
    </>
  );
}

export default function LeadsPage() {
  return <Suspense><LeadsInner /></Suspense>;
}
