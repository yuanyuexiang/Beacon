"use client";
import { Button, Card, Col, Descriptions, Form, Input, InputNumber, Row, Select, Space, Switch, Table, Tag, Upload, message } from "antd";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, json } from "@/lib/api";
import { formatRatio, label, type Ratio } from "@/lib/format";

type Batch = { id: string; batch_key: string; country: string; region: string | null; source_name: string; candidate_count: number | null };
type Lead = { id: string; source_key: string; name: string; postcode: string | null; website: string | null; screening_class: string; entity_status: string };
type Authority = { id: number; name: string; region: string | null; count: number | null };
type Summary = { counts: Record<string, number>; ratios: Record<string, Ratio>; commercial_status: string; by_channel: Record<string, { sent: number; replied: number }> };

export default function LeadsPage() {
  const [batches, setBatches] = useState<Batch[]>([]);
  const [batchKey, setBatchKey] = useState<string>();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [runResult, setRunResult] = useState<string>();
  const [authorities, setAuthorities] = useState<Authority[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  const loadBatches = useCallback(() => api<Batch[]>("/api/batches").then(setBatches).catch((e) => message.error(e.message)), []);
  const loadLeads = useCallback(
    (key?: string) => {
      api<Lead[]>(`/api/leads${key ? `?batch_key=${encodeURIComponent(key)}` : ""}`).then(setLeads).catch((e) => message.error(e.message));
      if (key) api<Summary>(`/api/batches/${encodeURIComponent(key)}/summary`).then(setSummary).catch(() => setSummary(null));
      else setSummary(null);
    },
    [],
  );
  useEffect(() => {
    loadBatches();
    loadLeads();
  }, [loadBatches, loadLeads]);

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Row gutter={16}>
        <Col xs={24} md={10}>
          <Card title="新建批次" size="small">
            <Form
              layout="inline"
              onFinish={(v) =>
                api("/api/batches", json({ ...v, source_licence: "OGL-3.0" }))
                  .then(() => {
                    message.success("批次已创建");
                    loadBatches();
                  })
                  .catch((e) => message.error(e.message))
              }
            >
              <Form.Item name="batch_key" rules={[{ required: true }]}><Input placeholder="batch_key" /></Form.Item>
              <Form.Item name="country" initialValue="GB"><Input style={{ width: 60 }} /></Form.Item>
              <Form.Item name="region"><Input placeholder="地区" /></Form.Item>
              <Form.Item name="source_name" initialValue="fsa"><Input style={{ width: 80 }} /></Form.Item>
              <Button htmlType="submit">创建</Button>
            </Form>
          </Card>
        </Col>
        <Col xs={24} md={14}>
          <Card title="自动建名单：FSA 名录 → Overture 补官网（不需要手工名单）" size="small" style={{ marginBottom: 16 }}>
            <Form
              layout="inline"
              onFinish={(v) => {
                if (!batchKey) return message.warning("先选择批次");
                setBusy("fsa");
                api<{ fetched: number; pool: number; selected: number; created: number; linked: number; skipped: number }>(`/api/batches/${batchKey}/sync/fsa`, json({ authority_id: v.authority_id, business_type_id: 1, exclude_awaiting: v.exclude_awaiting ?? true, sample_n: v.sample_n || null, seed: v.seed ?? null }))
                  .then((r) => { message.success(`FSA：名录 ${r.fetched}，池 ${r.pool}，选入 ${r.selected}，新增 ${r.created}，关联 ${r.linked}，跳过 ${r.skipped}`); loadLeads(batchKey); })
                  .catch((e) => message.error(e.message)).finally(() => setBusy(null));
              }}
            >
              <Form.Item name="authority_id" rules={[{ required: true }]}>
                <Select showSearch placeholder="地方当局（点击加载）" style={{ width: 240 }} optionFilterProp="label" onDropdownVisibleChange={(o) => { if (o && authorities.length === 0) api<Authority[]>("/api/sources/fsa/authorities").then(setAuthorities).catch((e) => message.error(e.message)); }}
                  options={authorities.map((a) => ({ value: a.id, label: `${a.name}${a.region ? `（${a.region}）` : ""} ${a.count ?? ""}` }))} />
              </Form.Item>
              <Form.Item name="sample_n" label="抽样数"><InputNumber min={1} max={5000} placeholder="空=全量" /></Form.Item>
              <Form.Item name="seed" label="种子"><InputNumber /></Form.Item>
              <Form.Item name="exclude_awaiting" label="排除待检查" valuePropName="checked" initialValue={true}><Switch /></Form.Item>
              <Button htmlType="submit" loading={busy === "fsa"} disabled={!batchKey}>从 FSA 建立候选</Button>
              <Button style={{ marginLeft: 8 }} loading={busy === "ov"} disabled={!batchKey} onClick={() => {
                setBusy("ov");
                api<{ leads: number; matched: number; website_set: number; phone_found: number; places: number }>(`/api/batches/${batchKey}/enrich/overture`, json({}))
                  .then((r) => { message.success(`Overture：${r.places} 个地点，匹配 ${r.matched}/${r.leads}，补官网 ${r.website_set}，有电话 ${r.phone_found}`); loadLeads(batchKey); })
                  .catch((e) => message.error(e.message)).finally(() => setBusy(null));
              }}>Overture 补官网</Button>
            </Form>
          </Card>
          <Card title="或：导入 CSV（name + fhrsid/source_key）" size="small">
            <Space>
              <Select
                placeholder="选择批次"
                style={{ width: 200 }}
                value={batchKey}
                options={batches.map((b) => ({ value: b.batch_key, label: `${b.batch_key}（${b.region ?? b.country}）` }))}
                onChange={(k) => {
                  setBatchKey(k);
                  loadLeads(k);
                }}
              />
              <Upload
                accept=".csv"
                showUploadList={false}
                customRequest={({ file }) => {
                  if (!batchKey) return message.warning("先选择批次");
                  const fd = new FormData();
                  fd.append("batch_key", batchKey);
                  fd.append("file", file as File);
                  api<{ created_count: number; linked_count: number; skipped_count: number; error_count: number; errors: { row: number; reason: string }[] }>("/api/imports", { method: "POST", body: fd })
                    .then((r) => {
                      message.success(`新增 ${r.created_count}，关联 ${r.linked_count}，跳过 ${r.skipped_count}，错误 ${r.error_count}`);
                      if (r.errors.length) message.warning(r.errors.map((e) => `第 ${e.row} 行：${e.reason}`).join("；"));
                      loadLeads(batchKey);
                    })
                    .catch((e) => message.error(e.message));
                }}
              >
                <Button>上传 CSV</Button>
              </Upload>
              <Button
                disabled={!batchKey}
                onClick={() =>
                  api<{ status: string; totals: Record<string, number> }>(`/api/batches/${batchKey}/runs`, json({ steps: ["fetch", "analyze"] }))
                    .then((r) => {
                      setRunResult(`${label(r.status)}：${JSON.stringify(r.totals)}`);
                      loadLeads(batchKey);
                    })
                    .catch((e) => message.error(e.message))
                }
              >
                批量抓取+分析
              </Button>
              {runResult && <Tag>{runResult}</Tag>}
            </Space>
          </Card>
        </Col>
      </Row>
      {summary && (
        <Card title={`批次统计 ${batchKey}`} size="small" extra={<a href={`/api/batches/${batchKey}/export.csv`}>导出 CSV</a>}>
          <Descriptions size="small" column={{ xs: 1, md: 4 }}>
            {Object.entries(summary.counts).map(([k, v]) => (
              <Descriptions.Item key={k} label={k}>{v}</Descriptions.Item>
            ))}
            {Object.entries(summary.ratios).map(([k, r]) => (
              <Descriptions.Item key={k} label={k}>{formatRatio(r)}</Descriptions.Item>
            ))}
            <Descriptions.Item label="商业结论">{summary.commercial_status}</Descriptions.Item>
          </Descriptions>
        </Card>
      )}
      <Table<Lead>
        rowKey="id"
        size="small"
        dataSource={leads}
        pagination={{ pageSize: 50 }}
        columns={[
          { title: "门店", dataIndex: "name", render: (v, r) => <Link href={`/leads/${r.id}`}>{v}</Link> },
          { title: "来源键", dataIndex: "source_key" },
          { title: "邮编", dataIndex: "postcode" },
          { title: "官网", dataIndex: "website", render: (v) => (v ? <a href={v} target="_blank" rel="noreferrer">{v}</a> : "-") },
          { title: "筛选", dataIndex: "screening_class", render: (v) => <Tag color={v === "candidate" ? "green" : v === "unchecked" ? "default" : "orange"}>{v}</Tag> },
          { title: "主体", dataIndex: "entity_status", render: label },
        ]}
      />
    </Space>
  );
}
