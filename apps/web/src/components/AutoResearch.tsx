"use client";
import Button from "@/components/AccessButton";
import { Alert, Card, Collapse, Space, Table, Tag, Typography } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, json } from "@/lib/api";

type Result = { url?: string; label?: string; kind?: string; status: string; reason: string; asset_id?: string; analysis_status?: string; judgment?: { category: string; date: string | null; citations: { document_id: string; quote: string; kind: string }[] }; sources?: { id: string; url: string }[] };
type Run = { id: string; status: string; stage: string; started_at: string; message?: string; error?: string; model?: string; websites: Result[]; menus: Result[]; candidate_count?: number; usage: Record<string, unknown>[] };
type State = { configured: boolean; run: Run | null };
const active = (r: Run | null) => !!r && ["queued", "running"].includes(r.status);
const statusName: Record<string, string> = { queued: "等待", running: "运行中", completed: "处理完成", needs_review: "部分结果需复核", conflict: "资料已改变", failed: "失败", interrupted: "已中断", accepted: "自动确认", review: "待复核", reject: "已排除", reference: "发现新官网" };
export default function AutoResearch({ id, onFinished }: { id: string; onFinished: () => Promise<void> }) {
  const [state, setState] = useState<State | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const callback = useRef(onFinished);
  const notified = useRef<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { callback.current = onFinished; }, [onFinished]);
  const refresh = useCallback(async () => {
    const next = await api<State>(`/api/leads/${id}/auto-research`, { cache: "no-store" });
    if (!mounted.current) return next;
    setState(next); setError(null);
    if (next.run && !active(next.run) && notified.current !== next.run.id) {
      notified.current = next.run.id;
      await callback.current();
    }
    return next;
  }, [id]);
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try { const next = await refresh(); if (!disposed && active(next.run)) timer = setTimeout(poll, 2000); }
      catch (e) { if (!disposed) { setError((e as Error).message); timer = setTimeout(poll, 5000); } }
    };
    poll();
    return () => { disposed = true; clearTimeout(timer); };
  }, [refresh, state?.run?.id]);
  const start = async () => {
    setBusy(true); setError(null);
    try {
      const run = await api<Run>(`/api/leads/${id}/auto-research`, json({}));
      setState((s) => ({ configured: s?.configured ?? true, run }));
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const run = state?.run ?? null;
  const results = [...(run?.websites ?? []).map((r) => ({ ...r, group: "官网" })), ...(run?.menus ?? []).map((r) => ({ ...r, group: "菜单" }))];
  return <Card size="small" title="AI 自动补全官网与菜单" style={{ marginBottom: 16 }} extra={<Button type="primary" loading={busy} disabled={!state?.configured || active(run)} onClick={start}>{active(run) ? "正在处理" : run ? "重新运行 / 重试" : "自动补全官网与菜单"}</Button>}>
    <Typography.Paragraph type="secondary">AI 根据官网证据选择网址与菜单，匹配明确时自动获取并分析；不确定的项目集中复核。菜单名称、价格和问题仍需审核。</Typography.Paragraph>
    {state && !state.configured && <Alert type="warning" message="需要配置真实 DeepSeek 模型才能自动研究；人工查找仍可使用。" />}
    {error && <Alert type="error" message={error} action={<Button size="small" onClick={() => refresh().catch((e) => setError(e.message))}>刷新状态</Button>} />}
    {run && <>
      <Space wrap style={{ marginBottom: 12 }}><Tag color={active(run) ? "processing" : run.status === "completed" ? "green" : "orange"}>{statusName[run.status] || run.status}</Tag><span>{run.stage}</span><Typography.Text type="secondary">{run.model} · {run.usage.length} 次已记录模型调用</Typography.Text></Space>
      {(run.message || run.error) && <Typography.Paragraph>{run.message || run.error}</Typography.Paragraph>}
      {!!run.candidate_count && run.candidate_count > 6 && <Alert type="info" message={`发现 ${run.candidate_count} 个候选，本次最多处理前 6 个，其余可用“查找官网菜单”查看。`} />}
      <Table rowKey={(_, i) => String(i)} size="small" pagination={false} dataSource={results} columns={[
        { title: "对象", dataIndex: "group", width: 60 },
        { title: "来源", render: (_, r) => r.url ? <a href={r.url} target="_blank" rel="noreferrer">{r.label || r.url}</a> : "Google 官网候选" },
        { title: "结果", width: 110, render: (_, r) => <Tag>{statusName[r.status] || r.status}</Tag> },
        { title: "判断依据", render: (_, r) => <><div>{r.reason}</div>{r.judgment && <><Typography.Text type="secondary">类别：{({ website: "官网", food: "食物", drinks: "饮品", buffet: "Buffet", offer: "优惠", other: "其他", unknown: "未知" } as Record<string, string>)[r.judgment.category]} · 日期：{r.judgment.date || "未知"}</Typography.Text><Collapse ghost size="small" items={[{ key: "evidence", label: "查看引用证据", children: r.judgment.citations.map((c, i) => <Typography.Paragraph key={i}><Typography.Text type="secondary">{r.sources?.find((s) => s.id === c.document_id)?.url || c.document_id}</Typography.Text><br />{c.quote}</Typography.Paragraph>) }]} /></>}</> },
      ]} />
    </>}
  </Card>;
}
