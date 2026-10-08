"use client";
import { Alert, Button, Checkbox, Form, Input, Modal, Space, Table, Tag, Typography, message } from "antd";
import { useState } from "react";
import { api, json } from "@/lib/api";

type Candidate = { id: string; title: string; url: string; excerpt: string; postcode_seen: boolean; warnings: string[] };
type Lookup = { search_id: string; query: string; searched_at: string; expires_at: string; candidates: Candidate[]; notice: string };
type Website = { website: string; website_source: string };
type Props = { id: string; name: string; address: string | null; postcode: string | null; website: string | null; onConfirmed: (result: Website) => void };

export default function WebsiteSearch({ id, name, address, postcode, website, onConfirmed }: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lookup, setLookup] = useState<Lookup | null>(null);
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<Candidate | null>(null);
  const [saving, setSaving] = useState(false);
  const [review] = Form.useForm();
  const show = async () => {
    setOpen(true); setError(null); setLookup(null); setBusy(true);
    try {
      const result = await api<Lookup | null>(`/api/leads/${id}/website-search`);
      setLookup(result); setQuery(result?.query ?? `${name} ${address ?? ""} ${postcode ?? ""} official restaurant website menu`);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const search = async () => {
    setError(null); setLookup(null); setBusy(true);
    try { setLookup(await api<Lookup>(`/api/leads/${id}/website-search`, json({ query: query.trim() || null }))); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const confirm = async (values: { address_checked: boolean; official_checked: boolean; evidence: string }) => {
    if (!lookup || !picked) return;
    setSaving(true);
    try {
      const result = await api<Website>(`/api/leads/${id}/website-confirm`, json({ ...values, search_id: lookup.search_id, candidate_id: picked.id, expected_website: website }));
      onConfirmed(result); setPicked(null); setOpen(false); message.success("官网已确认并保存，来源与核对依据已记录");
    } catch (e) { message.error((e as Error).message); }
    finally { setSaving(false); }
  };
  const expired = !!lookup && new Date(lookup.expires_at).getTime() < Date.now();
  const requiredCheck = { validator: (_: unknown, value: boolean) => value ? Promise.resolve() : Promise.reject(new Error("请完成核对后勾选")) };
  return <>
    <Button onClick={show}>搜索官网候选</Button>
    <Modal title="搜索官网候选" open={open} onCancel={() => !busy && setOpen(false)} footer={null} width={1050}>
      <Typography.Paragraph>门店：<b>{name}</b><br />地址：{address ?? "未记录"} · {postcode ?? ""}</Typography.Paragraph>
      <Alert type="info" showIcon message="搜索结果只作为候选，打开页面核对后再确认官网" description="不要把同名异店、目录、社媒或概念演示站当作商家官网。邮编出现在摘录中也不表示已核验地址。" style={{ marginBottom: 12 }} />
      <Space.Compact style={{ width: "100%", marginBottom: 12 }}><Input aria-label="官网搜索词" value={query} maxLength={600} onChange={(e) => setQuery(e.target.value)} onPressEnter={() => !busy && search()} /><Button type="primary" loading={busy} onClick={search}>搜索</Button></Space.Compact>
      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
      {lookup && <Typography.Paragraph type="secondary">最近搜索：{new Date(lookup.searched_at).toLocaleString("zh-CN")} · 候选七天内有效</Typography.Paragraph>}
      {expired && <Alert type="warning" showIcon message="候选已过期，请重新搜索后核对" style={{ marginBottom: 12 }} />}
      <Table<Candidate> rowKey="id" size="small" loading={busy} pagination={false} dataSource={lookup?.candidates ?? []} locale={{ emptyText: lookup ? "没有找到候选；可调整店名和地址再搜索" : "点击搜索获取候选" }} columns={[
        { title: "页面", width: 260, render: (_, c) => <><a href={c.url} target="_blank" rel="noreferrer">{c.title || c.url}</a><br /><Typography.Text type="secondary" style={{ overflowWrap: "anywhere" }}>{c.url}</Typography.Text></> },
        { title: "搜索摘录（未经实时核验）", render: (_, c) => <div style={{ whiteSpace: "pre-wrap", maxHeight: 180, overflow: "auto" }}>{c.excerpt || "无摘录，请打开原页面核对"}</div> },
        { title: "提示", width: 180, render: (_, c) => <Space wrap>{c.postcode_seen && <Tag color="blue">摘录含门店邮编</Tag>}{c.warnings.map((w) => <Tag key={w} color="orange" style={{ whiteSpace: "normal" }}>{w}</Tag>)}</Space> },
        { title: "", width: 100, render: (_, c) => <Button disabled={busy || expired} onClick={() => { review.resetFields(); setPicked(c); }}>核对并确认</Button> },
      ]} />
    </Modal>
    <Modal title="人工确认官网" open={!!picked} onCancel={() => !saving && setPicked(null)} footer={null} destroyOnHidden>
      <Typography.Paragraph>门店：{name}<br />地址：{address ?? "未记录"} · {postcode ?? ""}<br />候选：<a href={picked?.url} target="_blank" rel="noreferrer">{picked?.url}</a></Typography.Paragraph>
      {website && <Alert type="warning" message="确认后会替换当前官网" description={website} style={{ marginBottom: 12 }} />}
      <Form form={review} layout="vertical" onFinish={confirm}>
        <Form.Item name="address_checked" valuePropName="checked" rules={[requiredCheck]}><Checkbox>我已核对门店地址，确认不是同名异店</Checkbox></Form.Item>
        <Form.Item name="official_checked" valuePropName="checked" rules={[requiredCheck]}><Checkbox>我已确认该页面由此商家运营，不是第三方目录或演示站</Checkbox></Form.Item>
        <Form.Item name="evidence" label="核对依据" rules={[{ required: true, whitespace: true, message: "请记录页面地址、匹配的门店地址等依据" }]}><Input.TextArea maxLength={1500} rows={3} placeholder="例如：联系页 URL；列出的门牌、街道和邮编与门店一致" /></Form.Item>
        <Button type="primary" htmlType="submit" loading={saving}>确认并保存官网</Button>
      </Form>
    </Modal>
  </>;
}
