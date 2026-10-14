"use client";
import { Alert, Button, Card, Collapse, Drawer, Form, Modal, Select, Space, Switch, Table, Tag, Input, message } from "antd";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, json } from "@/lib/api";
import { HeroBand } from "@/components/ui";

const TYPES = [{ value: 1, label: "餐厅、咖啡馆、食堂" }, { value: 7844, label: "外卖店、三明治店" }, { value: 7843, label: "酒吧、Pub、夜店" }];
const typeLabel = (id: number) => TYPES.find((t) => t.value === id)?.label || String(id);
const time = (v?: string | null) => v ? new Date(v).toLocaleString("zh-CN") : "未同步";
const statusLabels: Record<string, string> = { queued: "等待同步", running: "同步中", completed: "同步完成", failed: "同步失败" };
type Sync = { id: string; status: string; business_type_ids: number[]; created_at: string; finished_at: string | null; error: string | null; counts: Record<string, number> | null };
type Authority = { id: number; name: string; region: string | null; count: number | null };
type Region = Authority & { business_type_ids: number[]; auto_sync: boolean; interval_hours: number; next_sync_at: string | null; last_success_at: string | null; pool_count: number; counts: Record<string, number>; type_versions: Record<string, { synced_at: string; extract_date?: string | null }>; latest_sync: Sync | null };
type Entry = { fhrsid: number; name: string; address: string | null; postcode: string | null; business_type_id: number; present: boolean; discovery_kind: string; last_change_kind: string; first_seen_at: string; last_seen_at: string; last_changed_at: string; inspection_pending: boolean };
type Values = { authority_id: number; business_type_ids: number[]; auto_sync: boolean; interval_hours: number };

export default function DirectoryPage() {
  const [regions, setRegions] = useState<Region[]>([]);
  const [authorities, setAuthorities] = useState<Authority[]>([]);
  const [selected, setSelected] = useState<number>();
  const [entries, setEntries] = useState<Entry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [view, setView] = useState("current");
  const [kind, setKind] = useState<number>();
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState<string>();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Region | null>(null);
  const [history, setHistory] = useState<Sync[] | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);
  const [form] = Form.useForm<Values>();
  const error = (e: Error) => message.error(e.message);
  const load = useCallback(async () => {
    const [rows, worker] = await Promise.all([api<Region[]>("/api/directory/regions"), api<{ online: boolean }>("/api/directory/status")]);
    setRegions(rows); setOnline(worker.online);
    setSelected((value) => value ?? rows[0]?.id);
  }, []);
  useEffect(() => { load().catch(error); const timer = setInterval(() => load().catch(() => {}), 5000); return () => clearInterval(timer); }, [load]);
  const region = regions.find((r) => r.id === selected);
  const latest = region?.latest_sync;
  const loadEntries = useCallback(async () => {
    if (!selected) { setEntries([]); setTotal(0); return; }
    const params = new URLSearchParams({ authority_id: String(selected), view, page: String(page), q });
    if (kind) params.set("business_type_id", String(kind));
    const result = await api<{ items: Entry[]; total: number }>(`/api/directory/entries?${params}`);
    setEntries(result.items); setTotal(result.total);
  }, [selected, view, page, q, kind]);
  useEffect(() => { loadEntries().catch(error); }, [loadEntries, latest?.id, latest?.status]);
  const refreshAuthorities = async () => {
    setBusy("authorities");
    try { await api("/api/directory/authorities/refresh", { method: "POST" }); setAuthorities(await api<Authority[]>("/api/directory/authorities")); message.success("地区名录已更新"); }
    catch (e) { error(e as Error); } finally { setBusy(undefined); }
  };
  const openForm = async (value: Region | null) => {
    setEditing(value); setOpen(true);
    if (!value) setAuthorities(await api<Authority[]>("/api/directory/authorities"));
  };
  useEffect(() => {
    if (!open) return;
    form.resetFields();
    if (editing) form.setFieldsValue({ authority_id: editing.id, business_type_ids: editing.business_type_ids, auto_sync: editing.auto_sync, interval_hours: editing.interval_hours });
  }, [open, editing, form]);
  const save = async (values: Values) => {
    setBusy("save");
    try {
      if (editing) await api(`/api/directory/regions/${editing.id}`, json(values, "PATCH"));
      else { await api("/api/directory/regions", json(values)); setSelected(values.authority_id); }
      setOpen(false); await load(); message.success(editing ? "同步设置已保存；调整类型后可点击立即同步" : "地区已加入门店池，首次同步已排队");
    } catch (e) { error(e as Error); } finally { setBusy(undefined); }
  };
  const sync = async () => {
    if (!selected) return;
    setBusy("sync");
    try { await api(`/api/directory/regions/${selected}/sync`, { method: "POST" }); await load(); message.success("同步已排队，离开页面后也会继续"); }
    catch (e) { error(e as Error); } finally { setBusy(undefined); }
  };
  const showHistory = async () => {
    if (!selected) return;
    try { setHistory(await api<Sync[]>(`/api/directory/regions/${selected}/syncs`)); } catch (e) { error(e as Error); }
  };
  return <>
    <HeroBand kicker="DIRECTORY" title="门店池" subtitle="先同步 FSA 来源数据，再从池中建立名单。来源变化与销售记录分别保存。" extra={<>
      <Select style={{ width: 250 }} placeholder="选择关注地区" value={selected} onChange={(id) => { setSelected(id); setPage(1); }} options={regions.map((r) => ({ value: r.id, label: `${r.name} · ${r.pool_count} 家` }))} />
      <Button type="primary" onClick={() => openForm(null).catch(error)}>添加地区</Button>
      <Button disabled={!region || !!busy || ["queued", "running"].includes(latest?.status || "")} loading={busy === "sync"} onClick={sync}>立即同步</Button>
      <Button disabled={!region} onClick={() => openForm(region!).catch(error)}>同步设置</Button>
    </>} />
    {online === false && <Alert type="warning" showIcon message="同步服务暂不可用，排队任务会保留" description="已成功同步的门店池仍可浏览和建立名单，服务恢复后接续同步。" style={{ marginBottom: 16 }} />}
    {region ? <Card size="small" style={{ marginBottom: 16 }} title={`${region.name} · 来源状态`} extra={<Space><Button onClick={showHistory}>同步记录</Button><Link href="/leads"><Button>建立销售名单</Button></Link></Space>}>
      <Space wrap><Tag color={latest?.status === "failed" ? "orange" : "blue"}>{statusLabels[latest?.status || ""] || "尚未同步"}</Tag><span>最后成功：{time(region.last_success_at)}</span><span>{region.auto_sync ? `每 ${region.interval_hours} 小时同步 · 下次 ${time(region.next_sync_at)}` : "定期同步已关闭"}</span></Space>
      <p style={{ color: "#6b7280" }}>定期同步范围：{region.business_type_ids.map(typeLabel).join(" / ")}。各类型最后成功：{Object.entries(region.type_versions).map(([id, version]) => `${typeLabel(Number(id))} ${time(version.synced_at)}`).join("；") || "尚未同步"}</p>
      <p>门店池现有 {region.pool_count} 家：{Object.entries(region.counts).map(([id, count]) => `${typeLabel(Number(id))} ${count} 家`).join("，") || "等待首次同步"}</p>
      {region.business_type_ids.some((id) => !region.type_versions[String(id)]) && <Alert type="info" message="所选类型尚未全部同步，成功同步后才能从这些类型建立名单" style={{ marginBottom: 12 }} />}
      {latest?.error && <Alert type="warning" showIcon message="本次同步失败，继续使用最后成功的数据" description={latest.error} />}
      {latest?.counts && <p style={{ marginBottom: 0 }}>本次：基线 {latest.counts.baseline}，新增 {latest.counts.added}，变更 {latest.counts.changed}，本次未发现 {latest.counts.missing}，重新发现 {latest.counts.reappeared}</p>}
    </Card> : <Alert type="info" showIcon message="添加关注地区，先同步门店池" description="只同步关注地区和所选类型；初次导入作为基线，后续新增才标记为新增发现。" style={{ marginBottom: 16 }} />}
    <Card size="small" title="来源门店" extra={<Space wrap>
      <Input.Search placeholder="搜索门店名称" allowClear onSearch={(value) => { setQ(value); setPage(1); }} />
      <Select value={view} style={{ width: 150 }} onChange={(value) => { setView(value); setPage(1); }} options={[{ value: "current", label: "当前名录" }, { value: "added", label: "后续新增发现" }, { value: "changed", label: "有变更记录" }, { value: "missing", label: "本次未发现" }, { value: "all", label: "全部历史记录" }]} />
      <Select allowClear style={{ width: 200 }} placeholder="商户类型" value={kind} options={TYPES} onChange={(value) => { setKind(value); setPage(1); }} />
    </Space>}>
      <Table<Entry> rowKey="fhrsid" size="small" dataSource={entries} pagination={{ current: page, pageSize: 100, total, showSizeChanger: false, onChange: setPage, showTotal: (count) => `共 ${count} 家` }} columns={[
        { title: "门店", dataIndex: "name", render: (name, row) => <Space wrap>{name}{row.inspection_pending && <Tag color="gold">待首次检查</Tag>}</Space> },
        { title: "FSA ID", dataIndex: "fhrsid", width: 100 },
        { title: "类型", dataIndex: "business_type_id", render: typeLabel, width: 160 },
        { title: "地址", dataIndex: "address", ellipsis: true },
        { title: "邮编", dataIndex: "postcode", width: 100 },
        { title: "发现状态", render: (_, row) => !row.present ? <Tag color="orange">本次未发现</Tag> : row.discovery_kind === "added" ? <Tag color="green">后续新增</Tag> : <Tag>初始基线</Tag>, width: 120 },
        { title: "首次发现", dataIndex: "first_seen_at", render: time, width: 165 },
        { title: "最近确认", dataIndex: "last_seen_at", render: time, width: 165 },
      ]} />
      <p style={{ color: "#6b7280", marginBottom: 0 }}>首次发现不是新开业证明；本次未发现不直接视为关闭。同步不会改变已有名单成员、人工官网或跟进记录。</p>
    </Card>
    <Modal title={editing ? `同步设置 · ${editing.name}` : "添加关注地区"} open={open} onCancel={() => !busy && setOpen(false)} footer={null} destroyOnHidden>
      <Form name="directory-config" form={form} layout="vertical" initialValues={{ business_type_ids: [1, 7843, 7844], auto_sync: true, interval_hours: 24 }} onFinish={save}>
        {!editing && <>
          <Form.Item name="authority_id" label="地区" rules={[{ required: true }]}><Select showSearch optionFilterProp="label" options={authorities.filter((a) => !regions.some((r) => r.id === a.id)).map((a) => ({ value: a.id, label: `${a.name} · 全部食品经营场所 ${a.count ?? "未知"} 家` }))} /></Form.Item>
          <Button loading={busy === "authorities"} onClick={refreshAuthorities} style={{ marginBottom: 16 }}>更新地区名录</Button>
        </>}
        <Form.Item name="business_type_ids" label="同步类型" rules={[{ required: true, type: "array", min: 1 }]}><Select mode="multiple" options={TYPES} /></Form.Item>
        <Form.Item name="auto_sync" label="定期同步" valuePropName="checked"><Switch /></Form.Item>
        <Form.Item name="interval_hours" label="同步频率"><Select options={[{ value: 24, label: "每天" }, { value: 72, label: "每三天" }, { value: 168, label: "每周" }]} /></Form.Item>
        <Button type="primary" htmlType="submit" block loading={busy === "save"}>{editing ? "保存设置" : "添加并首次同步"}</Button>
      </Form>
    </Modal>
    <Drawer title={`${region?.name ?? ""} · 同步记录`} open={history !== null} onClose={() => setHistory(null)} width={600}>
      {(history || []).map((run) => <Card key={run.id} size="small" title={`${time(run.created_at)} · ${statusLabels[run.status]}`} style={{ marginBottom: 12 }}>
        <p>{run.business_type_ids.map(typeLabel).join(" / ")}</p>
        {run.counts && <p>总数 {run.counts.total} · 基线 {run.counts.baseline} · 新增 {run.counts.added} · 变更 {run.counts.changed} · 未发现 {run.counts.missing} · 重新发现 {run.counts.reappeared}</p>}
        {run.error && <Alert type="warning" message={run.error} />}
        {run.status === "completed" && <Changes syncId={run.id} />}
      </Card>)}
    </Drawer>
  </>;
}
function Changes({ syncId }: { syncId: string }) {
  const [rows, setRows] = useState<{ fhrsid: number; name: string; kind: string; diff: Record<string, { before: unknown; after: unknown }> }[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [opened, setOpened] = useState(false);
  useEffect(() => {
    if (!opened) return;
    api<{ total: number; items: typeof rows }>(`/api/directory/syncs/${syncId}/changes?page=${page}`).then((r) => { setRows(r.items); setTotal(r.total); }).catch((e: Error) => message.error(e.message));
  }, [syncId, opened, page]);
  return <Collapse ghost onChange={(keys) => setOpened(!!keys.length)} items={[{ key: "changes", label: "查看新增与变更", children: <Table rowKey="fhrsid" size="small" dataSource={rows} pagination={{ current: page, total, pageSize: 100, showSizeChanger: false, onChange: setPage }} columns={[
    { title: "门店", dataIndex: "name" }, { title: "变化", dataIndex: "kind", render: (kind: string) => ({ baseline: "基线", added: "新增", changed: "变更", missing: "本次未发现", reappeared: "重新发现" }[kind] || kind) },
    { title: "明细", dataIndex: "diff", render: (diff: Record<string, { before: unknown; after: unknown }>) => Object.entries(diff).map(([key, value]) => `${({ name: "名称", address: "地址", postcode: "邮编", lat: "纬度", lng: "经度", raw: "登记信息", authority_id: "地区" }[key] || key)}：${typeof value.before === "object" ? "登记信息" : String(value.before ?? "未记录")} → ${typeof value.after === "object" ? "登记信息更新" : String(value.after ?? "未记录")}`).join("；") },
  ]} /> }]} />;
}
