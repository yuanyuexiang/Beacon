"use client";
import Button from "@/components/AccessButton";
import { Alert, Modal, Space, Table, Typography, message } from "antd";
import { useEffect, useState } from "react";
import { api, json } from "@/lib/api";

type Candidate = { url: string; kind: string; label: string; source_url: string };
type Lookup = { website: string; pages: { url: string; ok: boolean; error: string | null }[]; candidates: Candidate[]; notice: string };

export default function WebsiteMenus({ id, website, onAdded }: { id: string; website: string | null; onAdded: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [lookup, setLookup] = useState<Lookup | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<Candidate | null>(null);
  useEffect(() => { setLookup(null); setPicked(null); setOpen(false); }, [website, id]);
  const search = async () => {
    setOpen(true); setBusy(true); setError(null); setLookup(null);
    try { setLookup(await api<Lookup>(`/api/leads/${id}/menu-candidates`, json({}))); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const adopt = async () => {
    if (!picked || lookup?.website !== website) return;
    setBusy(true);
    try {
      const asset = await api<{ fetch_status: string; fetch_error: string | null }>(`/api/leads/${id}/assets`, json({ url: picked.url }));
      await onAdded(); setPicked(null);
      if (asset.fetch_status === "failed") setError(asset.fetch_error || "文件抓取失败，可在菜单文件中重试");
      else message.success("菜单已抓取，可在菜单文件中分析");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  return <>
    <Button disabled={!website} onClick={search}>查找官网菜单</Button>
    <Modal title="官网菜单候选" open={open} onCancel={() => setOpen(false)} footer={null} width={1000}>
      <Typography.Paragraph>当前官网：{website}</Typography.Paragraph>
      {error && <Alert type="error" message={error} style={{ marginBottom: 12 }} />}
      {lookup && <>
        <Typography.Paragraph type="secondary">{lookup.notice}</Typography.Paragraph>
        <Typography.Paragraph>读取成功 {lookup.pages.filter((p) => p.ok).length} 页，失败 {lookup.pages.filter((p) => !p.ok).length} 页。</Typography.Paragraph>
        {lookup.pages.filter((p) => !p.ok).map((p) => <Alert key={p.url} type="warning" message={`${p.url}：${p.error}`} />)}
      </>}
      <Table<Candidate> rowKey="url" size="small" loading={busy} pagination={false} dataSource={lookup?.candidates ?? []} scroll={{ y: 400 }} locale={{ emptyText: "没有找到候选，可人工填写菜单链接或上传文件" }} columns={[
        { title: "类型", width: 70, render: (_, c) => ({ pdf: "PDF", image: "图片", html: "网页" }[c.kind] || c.kind) },
        { title: "菜单", render: (_, c) => <a href={c.url} target="_blank" rel="noreferrer">{c.label || c.url}</a> },
        { title: "发现页面", render: (_, c) => <a href={c.source_url} target="_blank" rel="noreferrer">来源</a> },
        { title: "操作", width: 100, render: (_, c) => <Button disabled={busy || lookup?.website !== website} onClick={() => setPicked(c)}>核对并抓取</Button> },
      ]} />
    </Modal>
    <Modal title="确认菜单来源" open={!!picked} onCancel={() => setPicked(null)} onOk={adopt} confirmLoading={busy} okText="已核对，抓取菜单">
      <Typography.Paragraph>请打开候选核对餐厅、分店、菜单内容及日期。</Typography.Paragraph>
      <Space direction="vertical"><a href={picked?.url} target="_blank" rel="noreferrer">{picked?.url}</a><Typography.Text type="secondary">获取后仍需人工审核分析结果。</Typography.Text></Space>
    </Modal>
  </>;
}
