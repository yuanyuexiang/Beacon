"use client";
import { useState } from "react";
import { Alert, Card, Table } from "antd";
import Button from "@/components/AccessButton";
import { api } from "@/lib/api";
type Call = { at: string; purpose: string; model: string; duration_ms: number; status: string; provider?: string; connection_id?: string; configuration_version?: string; usage?: Record<string, number> | Record<string, number>[]; error?: string; error_type?: string };
export default function AiObservations({ source = "/api/ai/observations" }: {source?: string}) {
  const [rows, setRows] = useState<Call[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return <Card title="AI 调用记录" extra={<Button readOnlySafe loading={busy} onClick={async () => { setBusy(true); setError(""); try { setRows(await api<Call[]>(source)); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }}>读取记录</Button>}>
    {error && <Alert type="warning" message={error} />}<p>记录最近 100 次 AI 调用，不保存提示词或密钥。成功只表示调用完成，不代表结论已通过人工核对。</p>
    <Table size="small" rowKey={r => r.at + r.purpose} dataSource={rows} pagination={{ pageSize: 10 }} scroll={{ x: 640 }} columns={[{ title: "时间", dataIndex: "at", render: t => new Date(t).toLocaleString() }, { title: "用途", dataIndex: "purpose" }, { title: "连接／模型", render: (_, r) => <>{r.provider || "历史记录"} · {r.model}<br /><small>{r.connection_id || ""}{r.configuration_version ? ` · ${r.configuration_version.slice(0, 8)}` : ""}</small></> }, { title: "Token（输入／输出）", render: (_, r) => { const rows = Array.isArray(r.usage) ? r.usage : r.usage ? [r.usage] : []; return rows.length ? `${rows.reduce((n,u) => n + (u.input_tokens || u.prompt_tokens || 0),0)} / ${rows.reduce((n,u) => n + (u.output_tokens || u.completion_tokens || 0),0)}` : "—"; } }, { title: "耗时", dataIndex: "duration_ms", render: n => `${(n / 1000).toFixed(1)} 秒` }, { title: "结果", dataIndex: "status", render: (s, r) => s === "succeeded" ? "完成" : `失败：${r.error || r.error_type}` }]} />
  </Card>;
}
