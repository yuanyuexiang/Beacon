"use client";
import { Card, Col, Empty, Row, Select, Statistic, Table, Tag, Typography } from "antd";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { formatRatio, type Ratio } from "@/lib/format";

type Batch = { batch_key: string; region: string | null; country: string; candidate_count: number | null; source_version: string | null; created_at: string };
type Summary = { counts: Record<string, number>; ratios: Record<string, Ratio>; commercial_status: string; by_channel: Record<string, { sent: number; replied: number }>; costs: Record<string, { minutes: number; entries: number; amount_by_currency: Record<string, string> }>; unit_costs: Record<string, unknown> };

const FUNNEL: [string, string][] = [["N", "候选门店"], ["M", "取得菜单"], ["I", "人工确认问题"], ["E", "可联系"], ["S", "已人工发送"], ["R", "收到回复"], ["P", "正向意向"], ["Q", "请求报价"]];

export default function Dashboard() {
  const [batches, setBatches] = useState<Batch[]>([]);
  const [key, setKey] = useState<string>();
  const [s, setS] = useState<Summary | null>(null);
  useEffect(() => { api<Batch[]>("/api/batches").then((b) => { setBatches(b); if (b[0]) setKey(b[0].batch_key); }).catch(() => undefined); }, []);
  useEffect(() => { if (key) api<Summary>(`/api/batches/${encodeURIComponent(key)}/summary`).then(setS).catch(() => setS(null)); }, [key]);
  const b = batches.find((x) => x.batch_key === key);
  return (
    <>
      <PageHeader title="仪表盘" subtitle="按批次查看漏斗、渠道与成本。所有数字按门店去重，分母为零记为不适用。"
        extra={<Select style={{ width: 280 }} value={key} onChange={setKey} options={batches.map((x) => ({ value: x.batch_key, label: `${x.batch_key}（${x.region ?? x.country}，${x.candidate_count ?? "?"} 家）` }))} placeholder="选择批次" />} />
      {!s ? <Card><Empty description="没有批次。先到「批次与线索」用 FSA 建立候选。" /></Card> : (
        <>
          <Row gutter={[16, 16]}>
            {FUNNEL.map(([k, label]) => (
              <Col xs={12} md={6} xl={3} key={k}>
                <Card size="small"><Statistic title={<span>{label} <Typography.Text type="secondary">{k}</Typography.Text></span>} value={s.counts[k] ?? 0} /></Card>
              </Col>
            ))}
          </Row>
          <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
            <Col xs={24} lg={12}>
              <Card title="漏斗比率" size="small" extra={<Tag color={s.commercial_status.startsWith("未验证") ? "default" : "processing"}>{s.commercial_status}</Tag>}>
                <Table size="small" pagination={false} rowKey="k" dataSource={Object.entries(s.ratios).map(([k, r]) => ({ k, v: formatRatio(r) }))}
                  columns={[{ title: "指标", dataIndex: "k", width: 100 }, { title: "分子/分母", dataIndex: "v" }]} />
              </Card>
            </Col>
            <Col xs={24} lg={12}>
              <Card title="分渠道（发送 / 回复，按门店）" size="small">
                {Object.keys(s.by_channel).length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚无人工发送记录" /> : (
                  <Table size="small" pagination={false} rowKey="ch" dataSource={Object.entries(s.by_channel).map(([ch, v]) => ({ ch, ...v }))}
                    columns={[{ title: "渠道", dataIndex: "ch" }, { title: "发送", dataIndex: "sent" }, { title: "回复", dataIndex: "replied" }]} />
                )}
              </Card>
              <Card title="成本（分类）" size="small" style={{ marginTop: 16 }}>
                {Object.keys(s.costs).length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚无成本记录" /> : (
                  <Table size="small" pagination={false} rowKey="cat" dataSource={Object.entries(s.costs).map(([cat, v]) => ({ cat, minutes: v.minutes, entries: v.entries, amount: Object.entries(v.amount_by_currency).map(([c, a]) => `${a} ${c}`).join("，") || "-" }))}
                    columns={[{ title: "类别", dataIndex: "cat" }, { title: "分钟", dataIndex: "minutes" }, { title: "金额", dataIndex: "amount" }, { title: "条目", dataIndex: "entries" }]} />
                )}
              </Card>
            </Col>
          </Row>
          {b && <Card size="small" style={{ marginTop: 16 }} title="批次信息">
            <Typography.Text type="secondary">来源版本 {b.source_version ?? "-"} · 建立于 {b.created_at.slice(0, 10)} · </Typography.Text>
            <Link href={`/leads?batch=${encodeURIComponent(b.batch_key)}`}>查看线索</Link>
          </Card>}
        </>
      )}
    </>
  );
}
