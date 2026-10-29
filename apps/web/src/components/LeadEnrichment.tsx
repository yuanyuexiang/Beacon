"use client";

import { Alert, Checkbox, Drawer, List, Space, Tag, Typography } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import Button from "@/components/AccessButton";
import EnrichmentHistory from "./EnrichmentHistory";
import { api, json } from "@/lib/api";

type Item = { key: string; title: string; needed: boolean; updated_at: string | null; description: string };
type Task = { id: string; status: string; single: boolean; step: number; steps: string[]; error: string | null; message: string; updated_at: string; results: { key: string; status: string; message: string; at: string }[] };
type State = { items: Item[]; task: Task | null };
const NAMES: Record<string, string> = { website: "门店与官网", contacts: "联系方式", menus: "菜单获取", analysis: "菜单 AI 分析", overture: "Overture 资料同步", google_sync: "Google 资料同步", google: "官网核验", screen: "客户筛选", pool: "同步门店池" };
const time = (value: string | null) => value ? new Date(value).toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "尚未处理";

export default function LeadEnrichment({ leadId, onChanged, onMenus, dataRevision }: { dataRevision: string; leadId: string; onChanged: () => void; onMenus: () => void }) {
  const [state, setState] = useState<State>();
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"continue" | "refresh">("continue");
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const revision = useRef<string | undefined>(undefined);
  const changed = useRef(onChanged);
  changed.current = onChanged;
  const load = useCallback(async () => {
    const value = await api<State>(`/api/leads/${leadId}/enrichment`);
    const next = value.task ? `${value.task.id}:${value.task.step}:${value.task.status}` : "none";
    if (revision.current && revision.current !== next) changed.current();
    revision.current = next;
    setState(value);
    if (value.task && !["pending", "running"].includes(value.task.status)) setNotice(undefined);
  }, [leadId]);
  useEffect(() => { void load().catch((e) => setError(e.message)); }, [load, dataRevision]);
  const active = !!state?.task && ["pending", "running"].includes(state.task.status);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => void load().catch((e) => setError(e.message)), 3000);
    return () => clearInterval(timer);
  }, [active, load]);
  const show = (next: "continue" | "refresh") => {
    setMode(next); setSelected(state?.items.filter((i) => next === "refresh" || i.needed).map((i) => i.key) || []);
    setNotice(undefined); setOpen(true);
    void load().catch((e) => setError(e.message));
  };
  const start = async (keys = selected, next = mode) => {
    setBusy(true); setError(undefined); setNotice(undefined);
    try {
      const result = await api<{ task: Task | null; reused: boolean; message?: string }>(`/api/leads/${leadId}/enrichment`, json({ mode: next, items: keys }));
      setNotice(result.message || (result.reused ? "已展示正在执行的任务，没有重复启动" : "已开始后台完善，关闭面板后仍会继续"));
      await load();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const stop = async () => {
    if (!state?.task) return;
    setBusy(true); setError(undefined);
    try { await api(`/api/leads/${leadId}/enrichment/${state.task.id}/cancel`, { method: "POST" }); await load(); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const missing = state?.items.filter((i) => i.needed).length || 0;
  return <>
    <section className="lead-enrichment-bar" aria-label="门店资料完善">
      <div><strong>门店资料</strong><Typography.Text type="secondary">{active ? "后台完善中" : !state ? "读取资料状态…" : missing ? `${missing} 项可继续完善` : "已有资料可用"}</Typography.Text>
        <div className="lead-enrichment-summary">{state?.items.map((i) => <span key={i.key} className={i.needed ? "needs-data" : "has-data"}>{i.needed ? "○" : "✓"} {i.title}</span>)}</div>
      </div>
      <Space wrap><Button readOnlySafe onClick={() => show("refresh")} disabled={!state || active}>重新完善</Button><Button readOnlySafe type="primary" onClick={() => show("continue")}>{active ? "查看完善进度" : "继续完善"}</Button></Space>
    </section>
    <EnrichmentHistory leadId={leadId} />
    {!open && error && <Alert showIcon type="warning" message="资料状态未能加载" description={error} action={<Button readOnlySafe onClick={() => void load().then(() => setError(undefined)).catch((e) => setError(e.message))}>重试</Button>} />}
    <Drawer title={active ? "完善进度" : mode === "refresh" ? "重新完善这家门店" : "继续完善这家门店"} open={open} width={640} onClose={() => setOpen(false)} footer={<Space wrap>{active ? state?.task?.single ? <Button loading={busy} onClick={stop}>结束本次完善</Button> : <Typography.Text type="secondary">批量任务请在名单页面管理</Typography.Text> : <Button type="primary" loading={busy} disabled={!state || !selected.length} onClick={() => void start()}>{mode === "refresh" ? "更新所选资料" : "开始完善所选项"}</Button>}<Button readOnlySafe onClick={() => setOpen(false)}>关闭</Button></Space>}>
      <Typography.Paragraph type="secondary">{mode === "refresh" ? "重新获取所选资料。人工确认资料保留，新分析生成独立版本；更新后请重新核对相关文案。" : "复用批量处理和单家已有结果，只补充缺失、失败或过期的资料。打开页面不会自动查询或调用 AI。"}</Typography.Paragraph>
      {error && <Alert showIcon type="error" message={error} style={{ marginBottom: 16 }} />}
      {notice && <Alert showIcon type="info" message={notice} style={{ marginBottom: 16 }} />}
      {active && <Alert showIcon type="info" message={state?.task?.message} description={`当前：${NAMES[state?.task?.steps[state.task.step] || ""] || "等待处理"}。关闭页面后仍会继续，已取得结果会保存。`} style={{ marginBottom: 16 }} />}
      {!active && state?.task?.error && <Alert showIcon type="warning" message={state.task.error} style={{ marginBottom: 16 }} />}
      {!active && state?.task?.status === "cancelled" && <Alert type="info" showIcon message="本次完善已结束，已取得的结果保留" style={{ marginBottom: 16 }} />}
      <List dataSource={state?.items || []} renderItem={(item) => {
        const result = state?.task?.single ? state.task.results.find((r) => r.key === item.key) : undefined;
        const running = active && state?.task?.single && state.task.steps[state.task.step] === item.key;
        return <List.Item key={item.key} className="lead-enrichment-item"><div style={{ width: "100%" }}>
          <div className="lead-enrichment-item-heading"><Checkbox disabled={active || busy || (mode === "continue" && !item.needed)} checked={selected.includes(item.key)} onChange={(e) => setSelected((old) => e.target.checked ? [...old, item.key] : old.filter((k) => k !== item.key))}><strong>{item.title}</strong></Checkbox><Tag color={running ? "processing" : result?.status === "failed" ? "orange" : undefined}>{running ? "处理中" : result?.status === "failed" ? "待处理" : item.needed ? "可完善" : "已有结果"}</Tag></div>
          <Typography.Paragraph type="secondary" style={{ margin: "8px 0" }}>{item.description}</Typography.Paragraph>
          <Typography.Text type="secondary">最近处理：{time(result?.at || item.updated_at)}</Typography.Text>
          {result && <div style={{ marginTop: 8 }}><Typography.Text type={result.status === "failed" ? "warning" : undefined}>{result.message}</Typography.Text></div>}
          {!active && <div style={{ marginTop: 8 }}><Button size="small" disabled={busy} onClick={() => void start([item.key], "refresh")}>{result?.status === "failed" ? "重试此项" : "更新此项"}</Button>{["menus", "analysis"].includes(item.key) && <Button readOnlySafe size="small" type="link" onClick={() => { setOpen(false); onMenus(); }}>查看 / 上传菜单</Button>}</div>}
        </div></List.Item>;
      }} />
      <Typography.Paragraph type="secondary" style={{ marginTop: 20 }}>没有菜单也可以继续准备触达，询问菜单或负责人。更新资料不会发送消息；菜单事实、文案与渠道仍按原流程确认。</Typography.Paragraph>
    </Drawer>
  </>;
}
