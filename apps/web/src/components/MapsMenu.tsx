"use client";
import { Alert, Button, Descriptions, Modal, Space, Switch, Table, Tag, Typography } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, json } from "@/lib/api";

type ImageResult = { asset_id: string; file_url: string; viewer_url: string; sha256: string; created: boolean; analysis_status?: string };
type Run = { headless?: boolean; id: string; status: string; stage: string; message?: string; source_notice?: string; observed_at?: string; observed_website?: string | null; maps_url: string; images: ImageResult[]; thumbnail_count?: number; capture_status?: string; target?: { name: string; address: string; postcode: string; website?: string | null }; observed_name?: string | null; observed_address?: string | null; identity_check?: { name_matches: boolean; street_matches: boolean; postcode_matches: boolean } };
type Observation = { observed_at: string; name: string; address: string; website?: string | null; asset_ids: string[] };
type State = { configured: boolean; worker_online: boolean; run: Run | null; observations?: Observation[] };
const active = (run: Run | null) => !!run && ["queued", "running", "analyzing"].includes(run.status);
const labels: Record<string, string> = { queued: "等待执行", running: "获取中", analyzing: "AI 转录中", completed: "获取完成", needs_review: "待复核", interrupted: "已中断", conflict: "门店资料已改变", needs_review_analysis: "转录待审核", failed: "失败" };
export default function MapsMenu({ id, onAdded }: { id: string; onAdded: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<State | null>(null);
  const [showBrowser, setShowBrowser] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const callback = useRef(onAdded);
  const notified = useRef<string | null>(null);
  useEffect(() => { callback.current = onAdded; }, [onAdded]);
  const refresh = useCallback(async () => {
    const next = await api<State>(`/api/leads/${id}/maps-menu`, { cache: "no-store" });
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
      try {
        const next = await refresh();
        if (!disposed && (open || active(next.run))) timer = setTimeout(poll, 2000);
      } catch (e) {
        if (!disposed) { setError((e as Error).message); timer = setTimeout(poll, 5000); }
      }
    };
    poll();
    return () => { disposed = true; clearTimeout(timer); };
  }, [refresh, open, state?.run?.id]);
  const start = async () => {
    setBusy(true); setError(null);
    try {
      const run = await api<Run>(`/api/leads/${id}/maps-menu`, json({ show_browser: showBrowser }));
      setState((s) => ({ observations: s?.observations, configured: s?.configured ?? true, worker_online: s?.worker_online ?? true, run }));
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const run = state?.run ?? null;
  return <>
    <Button onClick={() => setOpen(true)}>{active(run) ? "Google Maps 菜单获取中" : "从 Google Maps 获取菜单"}</Button>
    <Modal title="从 Google Maps 获取菜单" open={open} onCancel={() => setOpen(false)} footer={null} width={850}>
      <Typography.Paragraph>按已关联的 Google 门店打开详情，进入菜单页签并下载图片。各来源资料分别保留，名称、地址和邮编差异不会阻止已关联门店的菜单获取。单次最多 5 张；获取日期不代表菜单拍摄或生效日期。</Typography.Paragraph>
      {state && !state.configured && <Alert type="warning" message="尚未配置 Maps 浏览器执行器，请按操作手册启动。" />}
      {state?.configured && !state.worker_online && !active(run) && <Alert type="warning" message="浏览器执行器未连接，启动后可重试。" />}
      {error && <Alert type="error" message={error} />}
      <Space wrap style={{ margin: "12px 0" }}>
        <Space><Switch size="small" aria-label="显示浏览器（测试）" checked={showBrowser} disabled={busy || active(run)} onChange={setShowBrowser} /><span>显示浏览器（测试）</span></Space>
        <Button type="primary" loading={busy} disabled={!state?.configured || !state.worker_online || active(run)} onClick={start}>{active(run) ? "正在处理" : run ? "重新获取 / 重试" : "开始获取菜单"}</Button>
        <Button onClick={() => refresh().catch((e) => setError(e.message))}>刷新状态</Button>
        {run && <a href={run.maps_url} target="_blank" rel="noreferrer">在 Google Maps 查看餐厅</a>}
      </Space>
      {run && <>
        <Typography.Paragraph><Tag color={active(run) ? "processing" : "default"}>{labels[run.status] || run.status}</Tag>{run.stage}{run.headless !== undefined && <Typography.Text type="secondary"> · {run.headless ? "无头运行" : "显示浏览器"}</Typography.Text>}</Typography.Paragraph>
        {run.message && <Alert type={run.status === "completed" ? "success" : "info"} message={run.message} style={{ marginBottom: 12 }} />}
        {run.source_notice && <Typography.Paragraph type="secondary">{run.source_notice}</Typography.Paragraph>}
        {(run.observed_name || run.observed_address) && <Descriptions size="small" bordered column={1} title="来源资料（分别保留）" style={{ marginBottom: 12 }} items={[
          { key: "target_name", label: "登记名称", children: run.target?.name || "未知" },
          { key: "original_website", label: "原线索官网", children: run.target?.website || "未知" },
          { key: "observed_name", label: "Maps 名称", children: run.observed_name || "未读取到" },
          { key: "target_address", label: "登记地址", children: `${run.target?.address || "未知"} ${run.target?.postcode || ""}` },
          { key: "observed_address", label: "Maps 地址", children: run.observed_address || "未读取到" },
          { key: "website", label: "Maps 官网", children: run.observed_website || "未读取到" },
          { key: "time", label: "Maps 观测时间", children: run.observed_at ? new Date(run.observed_at).toLocaleString() : "未知" },
        ]} />}
        {run.capture_status === "place_mismatch" && !run.observed_name && !run.observed_address && <Typography.Paragraph type="secondary">旧任务未记录页面名称和地址，重新获取后可查看具体对照。</Typography.Paragraph>}
        {!!run.thumbnail_count && run.thumbnail_count > 5 && <Typography.Paragraph type="secondary">当前找到 {run.thumbnail_count} 张缩略图，本次最多获取前 5 张。</Typography.Paragraph>}
        <Table<ImageResult> rowKey="sha256" size="small" pagination={false} dataSource={run.images} locale={{ emptyText: active(run) ? "正在获取菜单图片" : "尚无菜单图片" }} columns={[
          { title: "菜单图片", render: (_, image, i) => <a href={image.file_url} target="_blank" rel="noreferrer">打开图片 {i + 1}</a> },
          { title: "来源", render: (_, image) => <a href={image.viewer_url} target="_blank" rel="noreferrer">Google Maps 原图</a> },
          { title: "入库", render: (_, image) => image.created ? "新文件" : "已存在，复用" },
          { title: "分析", render: (_, image) => image.analysis_status === "needs_review" ? "转录待审核" : image.analysis_status === "failed" ? "失败，可重试" : "见菜单文件" },
          { title: "菜单日期", render: () => "未知" },
        ]} />
      </>}
      {!!state?.observations?.length && <>
        <Typography.Paragraph style={{ marginTop: 16 }}>Maps 来源记录（历史保留）</Typography.Paragraph>
        <Table<Observation> size="small" rowKey="observed_at" pagination={{ pageSize: 5 }} dataSource={state.observations} columns={[
          { title: "观测时间", render: (_, item) => new Date(item.observed_at).toLocaleString() },
          { title: "名称", dataIndex: "name" },
          { title: "地址", dataIndex: "address" },
          { title: "官网", render: (_, item) => item.website || "未读取到" },
          { title: "菜单文件", render: (_, item) => item.asset_ids.length },
        ]} />
      </>}
    </Modal>
  </>;
}
