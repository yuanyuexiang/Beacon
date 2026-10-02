"use client";
import { CheckCircleOutlined, DollarOutlined, FileSearchOutlined, MessageOutlined, PhoneOutlined, ShopOutlined, StarOutlined, TagsOutlined } from "@ant-design/icons";
import { Button, Card, Col, Empty, Row, Select, Table, Tag, Typography } from "antd";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { BRAND, Bars, HeroBand, StatCard } from "@/components/ui";
import { formatRatio, type Ratio } from "@/lib/format";

type Batch = { batch_key: string; region: string | null; country: string; candidate_count: number | null; source_version: string | null; created_at: string; sampling_method: string | null };
type Summary = { counts: Record<string, number>; ratios: Record<string, Ratio>; commercial_status: string; by_channel: Record<string, { sent: number; replied: number }>; costs: Record<string, { minutes: number; entries: number; amount_by_currency: Record<string, string> }>; unit_costs: Record<string, unknown> };

const STEPS: { code: string; label: string; icon: React.ReactNode; color: string }[] = [
  { code: "N", label: "候选门店", icon: <ShopOutlined />, color: BRAND.red },
  { code: "M", label: "取得菜单", icon: <FileSearchOutlined />, color: "#d97706" },
  { code: "I", label: "确认问题", icon: <TagsOutlined />, color: "#b45309" },
  { code: "E", label: "可联系", icon: <CheckCircleOutlined />, color: "#15803d" },
  { code: "S", label: "已人工发送", icon: <PhoneOutlined />, color: "#0369a1" },
  { code: "R", label: "收到回复", icon: <MessageOutlined />, color: "#7c3aed" },
  { code: "P", label: "正向意向", icon: <StarOutlined />, color: BRAND.gold },
  { code: "Q", label: "请求报价", icon: <DollarOutlined />, color: "#be123c" },
];

export default function Dashboard() {
  const [batches, setBatches] = useState<Batch[]>([]);
  const [key, setKey] = useState<string>();
  const [s, setS] = useState<Summary | null>(null);
  useEffect(() => { api<Batch[]>("/api/batches").then((b) => { setBatches(b); if (b[0]) setKey(b[0].batch_key); }).catch(() => undefined); }, []);
  useEffect(() => { if (key) api<Summary>(`/api/batches/${encodeURIComponent(key)}/summary`).then(setS).catch(() => setS(null)); }, [key]);
  const b = batches.find((x) => x.batch_key === key);
  const ratioOf = (code: string) => { const m: Record<string, string> = { M: "M/N", I: "I/M", E: "E/N", R: "R/S", P: "P/S", Q: "Q/S" }; const r = s?.ratios[m[code]]; return r && r.value !== null ? `${(r.value * 100).toFixed(0)}%` : undefined; };
  return (
    <>
      <HeroBand kicker="DASHBOARD" title="仪表盘" subtitle="按批次查看从候选到报价的完整漏斗；所有数字按门店去重，分母为零记为不适用。"
        extra={<>
          <Select style={{ width: 300 }} value={key} onChange={setKey} placeholder="选择批次" options={batches.map((x) => ({ value: x.batch_key, label: `${x.batch_key}（${x.region ?? x.country}，${x.candidate_count ?? "?"} 家）` }))} />
          <Link href="/leads"><Button type="primary">去建名单</Button></Link>
        </>}>
        {s && <div style={{ marginTop: 18, display: "flex", gap: 24, flexWrap: "wrap", fontSize: 12, color: "rgba(255,255,255,0.75)" }}>
          <span>商业结论：<Tag color={s.commercial_status.startsWith("未验证") ? "default" : "gold"} style={{ marginInlineEnd: 0 }}>{s.commercial_status}</Tag></span>
          {b?.source_version && <span>来源版本 {b.source_version.slice(0, 10)}</span>}
          {b && <span>建立于 {b.created_at.slice(0, 10)}</span>}
        </div>}
      </HeroBand>
      {!s ? <Card><Empty description="没有批次。先到「批次与线索」用 FSA 建立候选。" /></Card> : (
        <>
          <Row gutter={[16, 16]}>
            {STEPS.map((st) => (
              <Col xs={12} md={6} key={st.code}>
                <StatCard icon={st.icon} color={st.color} title={<>{st.label} <span style={{ fontFamily: "monospace" }}>{st.code}</span></>} value={s.counts[st.code] ?? 0} hint={ratioOf(st.code)} />
              </Col>
            ))}
          </Row>
          <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
            <Col xs={24} lg={14}>
              <Card title="漏斗" size="small" extra={<Typography.Text type="secondary">分子 / 分母见右侧比率</Typography.Text>}>
                <Bars max={s.counts.N ?? 0} rows={STEPS.map((st) => ({ code: st.code, label: st.label, value: s.counts[st.code] ?? 0, ratio: ratioOf(st.code) }))} />
                <div style={{ marginTop: 16, display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 8 }}>
                  {Object.entries(s.ratios).map(([k, r]) => (
                    <div key={k} className="beacon-ratio"><span>{k}</span><b>{formatRatio(r)}</b></div>
                  ))}
                </div>
              </Card>
            </Col>
            <Col xs={24} lg={10}>
              <Card title="分渠道（发送 / 回复，按门店）" size="small" style={{ marginBottom: 16 }}>
                {Object.keys(s.by_channel).length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚无人工发送记录" /> : (
                  <Table size="small" pagination={false} rowKey="ch" dataSource={Object.entries(s.by_channel).map(([ch, v]) => ({ ch, ...v }))}
                    columns={[{ title: "渠道", dataIndex: "ch" }, { title: "发送", dataIndex: "sent" }, { title: "回复", dataIndex: "replied" }]} />
                )}
              </Card>
              <Card title="成本（setup / processing / outreach）" size="small">
                {Object.keys(s.costs).length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚无成本记录" /> : (
                  <Table size="small" pagination={false} rowKey="cat" dataSource={Object.entries(s.costs).map(([cat, v]) => ({ cat, minutes: v.minutes, entries: v.entries, amount: Object.entries(v.amount_by_currency).map(([c, a]) => `${a} ${c}`).join("，") || "-" }))}
                    columns={[{ title: "类别", dataIndex: "cat" }, { title: "分钟", dataIndex: "minutes" }, { title: "金额", dataIndex: "amount" }, { title: "条目", dataIndex: "entries" }]} />
                )}
              </Card>
            </Col>
          </Row>
          {b?.sampling_method && <Card size="small" style={{ marginTop: 16 }} title="抽样方法"><Typography.Text type="secondary">{b.sampling_method}</Typography.Text></Card>}
        </>
      )}
    </>
  );
}
