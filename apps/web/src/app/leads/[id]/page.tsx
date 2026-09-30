"use client";
import { Button, Card, Descriptions, Form, Input, InputNumber, Popconfirm, Select, Space, Switch, Table, Tabs, Tag, Typography, Upload, message } from "antd";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, json } from "@/lib/api";
import { approvalText, label } from "@/lib/format";

type Lead = { id: string; name: string; source_key: string; website: string | null; screening_class: string; screening_reason: string | null; entity_status: string; entity_evidence: string | null };
type Asset = { id: string; kind: string; source_url: string | null; original_filename: string | null; fetch_status: string; fetch_error: string | null; storage_path: string | null; sha256: string | null };
type Item = { name: string; price_text: string; deleted?: boolean; evidence: Record<string, unknown> };
type Issue = { issue_code: string; fact: string; severity: string; confirmed: boolean | null; confirmed_by: string | null; note: string | null; deleted?: boolean; evidence: Record<string, unknown> };
type Candidates = { pdf_links?: string[]; image_candidates?: { src: string; alt: string }[]; iframes?: string[] };
type Analysis = { id: string; version: number; parent_version: number | null; status: string; engine: string; engine_version: string | null; review_state: string | null; items: Item[] | null; issues: Issue[] | null; measurements: (Record<string, unknown> & Candidates) | null; error: string | null };
type Content = { id: string; kind: string; version: number; status: string; approval_valid: boolean; approval_invalid_reason: string | null; body_text: string | null; html_url: string | null; png_url: string | null; spec: Record<string, unknown> | null };

const SCREENING = ["unchecked", "candidate", "unknown", "excluded_cafe", "excluded_chain", "excluded_canteen", "excluded_community", "excluded_institution", "excluded_pub", "excluded_closed", "excluded_other"];

export default function LeadDetail() {
  const { id } = useParams<{ id: string }>();
  const [lead, setLead] = useState<Lead | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [analyses, setAnalyses] = useState<Record<string, Analysis[]>>({});
  const [content, setContent] = useState<Content[]>([]);
  const err = (e: Error) => message.error(e.message);

  const reload = useCallback(async () => {
    const l = await api<Lead>(`/api/leads/${id}`);
    setLead(l);
    const as = await api<Asset[]>(`/api/leads/${id}/assets`);
    setAssets(as);
    const map: Record<string, Analysis[]> = {};
    for (const a of as) map[a.id] = await api<Analysis[]>(`/api/assets/${a.id}/analyses`);
    setAnalyses(map);
    setContent(await api<Content[]>(`/api/leads/${id}/content`));
  }, [id]);
  useEffect(() => {
    reload().catch(err);
  }, [reload]);
  if (!lead) return null;

  const latest = (aid: string) => analyses[aid]?.[analyses[aid].length - 1];
  const correct = (a: Analysis, corrections: { field_path: string; new_value: unknown; reason?: string }[]) =>
    api(`/api/analyses/${a.id}`, json({ corrections }, "PATCH")).then(reload).catch(err);
  const reviewedAnalyses = Object.values(analyses).flatMap((list) => list.filter((a) => a.review_state === "reviewed" && a.id === list[list.length - 1]?.id));

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Card size="small" title={<>{lead.name} <Typography.Text type="secondary">{lead.source_key}</Typography.Text></>}>
        <Form
          layout="inline"
          initialValues={lead}
          onFinish={(v) => api(`/api/leads/${id}`, json(v, "PATCH")).then(() => { message.success("已保存"); reload(); }).catch(err)}
        >
          <Form.Item name="website" label="官网"><Input style={{ width: 260 }} /></Form.Item>
          <Form.Item name="screening_class" label="筛选"><Select style={{ width: 170 }} options={SCREENING.map((s) => ({ value: s }))} /></Form.Item>
          <Form.Item name="screening_reason" label="原因"><Input style={{ width: 220 }} /></Form.Item>
          <Form.Item name="entity_status" label="主体"><Select style={{ width: 120 }} options={["unknown", "company", "sole_trader", "other"].map((s) => ({ value: s }))} /></Form.Item>
          <Form.Item name="entity_evidence" label="主体证据"><Input style={{ width: 200 }} /></Form.Item>
          <Button htmlType="submit">保存</Button>
        </Form>
      </Card>

      <Card size="small" title="菜单文件" extra={
        <Space>
          <Form layout="inline" onFinish={(v) => api(`/api/leads/${id}/assets`, json(v)).then(reload).catch(err)}>
            <Form.Item name="url" rules={[{ required: true }]}><Input placeholder="人工核对过的菜单 URL" style={{ width: 320 }} /></Form.Item>
            <Button htmlType="submit">抓取</Button>
          </Form>
          <Upload showUploadList={false} customRequest={({ file }) => { const fd = new FormData(); fd.append("file", file as File); api(`/api/leads/${id}/assets/upload`, { method: "POST", body: fd }).then(reload).catch(err); }}>
            <Button>上传文件</Button>
          </Upload>
        </Space>
      }>
        <Table<Asset> rowKey="id" size="small" pagination={false} dataSource={assets} columns={[
          { title: "类型", dataIndex: "kind" },
          { title: "来源", render: (_, a) => a.source_url ?? a.original_filename ?? "-" },
          { title: "状态", render: (_, a) => <>{label(a.fetch_status)} {a.fetch_error && <Typography.Text type="danger">{a.fetch_error}</Typography.Text>}</> },
          { title: "文件", render: (_, a) => a.storage_path ? <a href={`/api/files/${a.storage_path}`} target="_blank" rel="noreferrer">打开</a> : "-" },
          { title: "操作", render: (_, a) => <Space>
            {a.source_url && a.fetch_status !== "fetched" && <Button size="small" onClick={() => api(`/api/assets/${a.id}/retry`, { method: "POST" }).then(reload).catch(err)}>重试</Button>}
            {a.fetch_status === "fetched" && <Button size="small" onClick={() => api(`/api/assets/${a.id}/analyses`, { method: "POST" }).then(reload).catch(err)}>分析（规则）</Button>}
            {a.fetch_status === "fetched" && <Button size="small" onClick={() => api(`/api/assets/${a.id}/analyses?engine=provider`, { method: "POST" }).then(reload).catch(err)}>模型转录</Button>}
            {latest(a.id) && <Tag>v{latest(a.id).version} {label(latest(a.id).status)}{latest(a.id).review_state === "reviewed" ? " · 已审核" : ""}</Tag>}
          </Space> },
        ]} />
      </Card>

      {assets.filter((a) => latest(a.id)).map((a) => {
        const an = latest(a.id)!;
        const items = an.items ?? [];
        const issues = an.issues ?? [];
        const editable = an.review_state !== "reviewed";
        return (
          <Card key={a.id} size="small" title={`证据与修正 · ${a.kind} · 分析 v${an.version}（${an.engine}，${label(an.status)}）`} extra={
            editable && <Button type="primary" onClick={() => api(`/api/analyses/${an.id}/review`, { method: "POST" }).then(reload).catch(err)}>完成审核</Button>
          }>
            {an.error && <Typography.Paragraph type="warning">{an.error}</Typography.Paragraph>}
            {(an.measurements?.pdf_links?.length || an.measurements?.image_candidates?.length) ? (
              <Card type="inner" size="small" title="页面里发现的候选菜单文件（一键接入后再分析；图片可能是菜品照片，请先打开确认）" style={{ marginBottom: 8 }}>
                {(an.measurements?.pdf_links ?? []).map((u) => (
                  <div key={u}><a href={u} target="_blank" rel="noreferrer">{u}</a> <Button size="small" onClick={() => api(`/api/leads/${id}/assets`, json({ url: u })).then(reload).catch(err)}>接入 PDF</Button></div>
                ))}
                {(an.measurements?.image_candidates ?? []).map((c) => (
                  <div key={c.src}><a href={c.src} target="_blank" rel="noreferrer">{c.src.slice(-60)}</a> {c.alt && <Typography.Text type="secondary">{c.alt}</Typography.Text>} <Button size="small" onClick={() => api(`/api/leads/${id}/assets`, json({ url: c.src })).then(reload).catch(err)}>接入图片</Button></div>
                ))}
              </Card>
            ) : null}
            <Tabs items={[
              { key: "file", label: "原文件", children: a.storage_path ? (a.kind === "image" ? <img alt="menu" src={`/api/files/${a.storage_path}`} style={{ maxWidth: "100%" }} /> : <iframe title="file" src={`/api/files/${a.storage_path}`} style={{ width: "100%", height: 600, border: 0 }} />) : null },
              { key: "items", label: `菜品与价格（${items.length}）`, children: (
                <Table<Item> rowKey={(_, i) => String(i)} size="small" pagination={false} dataSource={items} columns={[
                  { title: "#", render: (_, __, i) => i },
                  { title: "菜名", dataIndex: "name", render: (v, r, i) => editable ? <Typography.Text editable={{ onChange: (nv) => nv !== v && correct(an, [{ field_path: `items[${i}].name`, new_value: nv }]) }} delete={r.deleted}>{v}</Typography.Text> : v },
                  { title: "价格", dataIndex: "price_text", render: (v, _, i) => editable ? <Typography.Text editable={{ onChange: (nv) => nv !== v && correct(an, [{ field_path: `items[${i}].price_text`, new_value: nv }]) }}>{v}</Typography.Text> : v },
                  { title: "位置", render: (_, r) => JSON.stringify(r.evidence) },
                  { title: "", render: (_, r, i) => editable && !r.deleted && <Popconfirm title="标记为无效条目？" onConfirm={() => correct(an, [{ field_path: `items[${i}].deleted`, new_value: true }])}><a>删除</a></Popconfirm> },
                ]} />
              ) },
              { key: "issues", label: `问题候选（${issues.length}）`, children: (
                <Table<Issue> rowKey={(_, i) => String(i)} size="small" pagination={false} dataSource={issues} columns={[
                  { title: "代码", dataIndex: "issue_code", render: (v, r) => <Tag color={r.severity === "blocking" ? "red" : r.severity === "candidate" ? "gold" : "blue"}>{v}</Tag> },
                  { title: "事实（测量值）", dataIndex: "fact", render: (v, r) => <>{v}{(r as Issue & { fact_zh?: string | null }).fact_zh && <div><Typography.Text type="secondary">{(r as Issue & { fact_zh?: string | null }).fact_zh}</Typography.Text></div>}</> },
                  { title: "证据", render: (_, r) => JSON.stringify(r.evidence) },
                  { title: "人工确认", render: (_, r, i) => <Switch checked={r.confirmed === true} disabled={!editable} checkedChildren="属实" unCheckedChildren="未确认" onChange={(c) => correct(an, [{ field_path: `issues[${i}].confirmed`, new_value: c ? true : null }])} /> },
                  { title: "备注", dataIndex: "note", render: (v, _, i) => editable ? <Typography.Text editable={{ onChange: (nv) => correct(an, [{ field_path: `issues[${i}].note`, new_value: nv }]) }}>{v ?? ""}</Typography.Text> : v },
                ]} />
              ) },
              { key: "add", label: "人工新增", children: editable ? (
                <Form layout="inline" onFinish={(v) => correct(an, [{ field_path: "issues[new]", new_value: { issue_code: v.issue_code, fact: v.fact, evidence: { region: v.region, file: a.storage_path }, severity: "candidate" }, reason: "人工目视" }])}>
                  <Form.Item name="issue_code" rules={[{ required: true }]}><Select placeholder="问题代码" style={{ width: 200 }} options={["text_overlap", "missing_spaces", "low_resolution", "price_format_mixed_decimals", "price_format_mixed_symbol", "small_text", "typo", "other"].map((c) => ({ value: c }))} /></Form.Item>
                  <Form.Item name="fact" rules={[{ required: true }]}><Input placeholder="可核对的事实（英文，用于对外文案）" style={{ width: 360 }} /></Form.Item>
                  <Form.Item name="region" rules={[{ required: true }]}><Input placeholder="位置（如：中栏 Signature 第 3 条）" style={{ width: 240 }} /></Form.Item>
                  <Button htmlType="submit">新增问题（记为人工确认）</Button>
                </Form>
              ) : <Typography.Text type="secondary">已审核的版本不能再新增。</Typography.Text> },
              { key: "m", label: "测量", children: <pre style={{ fontSize: 12 }}>{JSON.stringify(an.measurements, null, 1)}</pre> },
              { key: "v", label: `版本（${analyses[a.id].length}）`, children: analyses[a.id].map((x) => <div key={x.id}>v{x.version} ← v{x.parent_version ?? "-"} · {x.engine}{x.engine_version ? ` ${x.engine_version}` : ""} · {label(x.status)} · {x.review_state ?? "未审核"}</div>) },
            ]} />
          </Card>
        );
      })}

      <Card size="small" title="样稿与文案" extra={reviewedAnalyses.length > 0 && (
        <Space>
          <Form layout="inline" onFinish={(v) => api(`/api/leads/${id}/content`, json({ kind: "sample_partial", analysis_id: reviewedAnalyses[0].id, section: v.section, item_indexes: v.n ? Array.from({ length: v.n }, (_, i) => i) : undefined })).then(reload).catch(err)}>
            <Form.Item name="section" initialValue="Sample section"><Input style={{ width: 160 }} /></Form.Item>
            <Form.Item name="n" label="前 N 项"><InputNumber min={1} max={30} /></Form.Item>
            <Button htmlType="submit">生成样稿</Button>
          </Form>
          <Form layout="inline" onFinish={(v) => api(`/api/leads/${id}/content`, json({ kind: "message_short", analysis_id: reviewedAnalyses[0].id, ...v })).then(reload).catch(err)}>
            <Form.Item name="sender_identity" rules={[{ required: true }]}><Input placeholder="发送身份" style={{ width: 200 }} /></Form.Item>
            <Form.Item name="opt_out_text" rules={[{ required: true }]}><Input placeholder="退出方式" style={{ width: 220 }} /></Form.Item>
            <Button htmlType="submit">生成文案</Button>
          </Form>
        </Space>
      )}>
        {reviewedAnalyses.length === 0 && <Typography.Text type="secondary">完成分析审核后才能生成对外内容。</Typography.Text>}
        {content.map((c) => (
          <Card key={c.id} type="inner" size="small" style={{ marginTop: 8 }} title={<>{c.kind} v{c.version} <Tag>{label(c.status)}</Tag> <Typography.Text type={c.approval_valid ? "success" : "warning"}>{approvalText(c.approval_valid, c.approval_invalid_reason)}</Typography.Text></>} extra={
            <Space>
              <Button size="small" type="primary" disabled={c.approval_valid} onClick={() => api(`/api/content/${c.id}/approve`, json({ decision: "approved" })).then(reload).catch(err)}>审批通过</Button>
              <Button size="small" danger onClick={() => api(`/api/content/${c.id}/approve`, json({ decision: "rejected" })).then(reload).catch(err)}>驳回</Button>
            </Space>
          }>
            {c.body_text && <Typography.Paragraph editable={{ onChange: (t) => t !== c.body_text && api(`/api/content/${c.id}/revise`, json({ body_text: t })).then(reload).catch(err) }} style={{ whiteSpace: "pre-wrap" }}>{c.body_text}</Typography.Paragraph>}
            {c.png_url && <img alt="sample" src={c.png_url} style={{ maxWidth: 375, border: "1px solid #eee" }} />}
            {c.html_url && !c.png_url && <a href={c.html_url} target="_blank" rel="noreferrer">打开 HTML 样稿</a>}
            <Descriptions size="small" column={1} style={{ marginTop: 8 }}>
              <Descriptions.Item label="数据来源">{String(c.spec?.source ?? c.spec?.template ?? "")}</Descriptions.Item>
            </Descriptions>
          </Card>
        ))}
      </Card>
    </Space>
  );
}
