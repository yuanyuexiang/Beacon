"use client";
import { Alert, Button, Collapse, Drawer, Empty, Space, Tag, Typography } from "antd";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { WORKFLOW_TITLES, workflowSummary } from "@/lib/list-workflow";
export type HistoryEntry = { id: string; phase: string; status: string; created_at: string; finished_at: string | null; scope: string; scope_count: number | null; step: number; steps: string[]; results: Record<string, unknown>[]; error: string | null; operator: string };
const phases: Record<string, string> = { sync: "同步来源资料", review: "AI 核验与完善", legacy: "历史综合任务" };
const statuses: Record<string, string> = { pending: "等待处理", running: "进行中", completed: "已完成", partial: "部分完成，仍有待处理项", failed: "未完成", cancelled: "已结束" };
export const historyTime = (row: HistoryEntry) => `${row.finished_at ? (["completed", "partial"].includes(row.status) ? "完成本轮" : "结束本轮") : "发起"}：${new Date(row.finished_at || row.created_at).toLocaleString("zh-CN", { hour12: false })}`;
export const historyScope = (row: HistoryEntry) => `${row.scope === "batch" ? "本批次" : row.scope === "selected" ? "所选门店" : "历史范围未记录"}${row.scope_count == null ? "" : ` · ${row.scope_count} 家`}`;
export default function EnrichmentHistory({ batchKey, leadId }: { batchKey?: string; leadId?: string }) {
  const [rows, setRows] = useState<HistoryEntry[]>([]);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [open, setOpen] = useState(false);
  const url = leadId ? `/api/leads/${leadId}/enrichment-history` : batchKey ? `/api/batches/${encodeURIComponent(batchKey)}/enrichment-history` : "";
  useEffect(() => {
    let active = true;
    setRows([]); setLoaded(false); setError("");
    if (!url) return;
    const load = () => api<HistoryEntry[]>(url).then(value => { if (active) { setRows(value); setLoaded(true); setError(""); } }).catch(e => { if (active) setError(e.message); });
    void load();
    const timer = setInterval(() => void load(), 5000);
    return () => { active = false; clearInterval(timer); };
  }, [url]);
  if (!url) return null;
  const latest = rows[0];
  return <>
    <div style={{ margin: "12px 0 20px", padding: "12px 16px", background: "#fff", border: "1px solid #eee", borderRadius: 10 }} aria-label="名单完善记录">
      <Space wrap><Typography.Text strong>最近完善</Typography.Text>{error ? <Typography.Text type="warning">记录读取失败</Typography.Text> : latest ? <><span>{phases[latest.phase]}</span><Tag color={latest.status === "completed" ? "green" : "blue"}>{statuses[latest.status]}</Tag><span>{historyTime(latest)}</span><Typography.Text type="secondary">{historyScope(latest)}{["running", "pending"].includes(latest.status) ? ` · 步骤 ${Math.min(latest.step + 1, latest.steps.length)}/${latest.steps.length}` : ""}</Typography.Text></> : <span>{loaded ? "暂无可追溯的完善记录" : "正在读取…"}</span>}<Button type="link" onClick={() => setOpen(true)}>查看记录</Button></Space>
    </div>
    <Drawer title="名单完善记录" open={open} width={640} onClose={() => setOpen(false)}>
      {error && <Alert type="warning" message={error} />}
      <Typography.Paragraph type="secondary">最近 100 条任务。历史缺少准确完成时间时仅显示发起时间，不用门店更新时间替代。单家仅展示明确记录了该门店范围的任务。</Typography.Paragraph>
      {(["sync", "review"] as const).map(phase => { const row = rows.find(r => r.phase === phase); return <Typography.Paragraph key={phase}><strong>{phases[phase]}：</strong>{row ? `${historyTime(row)} · ${statuses[row.status]} · ${historyScope(row)}` : "暂无记录"}</Typography.Paragraph>; })}
      {!rows.length && <Empty description="暂无记录" />}
      <Collapse items={rows.map(row => ({ key: row.id, label: `${phases[row.phase]} · ${statuses[row.status]} · ${historyTime(row)}`, children: <><Typography.Paragraph>{historyScope(row)} · 操作人：{row.operator}</Typography.Paragraph>{!row.finished_at && !["running", "pending"].includes(row.status) && <Typography.Paragraph type="secondary">未记录准确完成时间</Typography.Paragraph>}{row.error && <Alert type="warning" message={row.error} />}{row.steps.map((step, i) => <Typography.Paragraph key={`${step}-${i}`}><strong>{WORKFLOW_TITLES[step] || step}：</strong>{workflowSummary(step, row.results[i]) || (i < row.step ? "步骤已完成，未记录统计" : "尚未取得结果")}</Typography.Paragraph>)}</> }))} />
    </Drawer>
  </>;
}
