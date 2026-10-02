"use client";
import { Button, Card, Col, Descriptions, Form, Input, InputNumber, Modal, Popconfirm, Row, Select, Space, Switch, Table, Tabs, Tag, Typography, Upload, message } from "antd";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, json } from "@/lib/api";
import { CHANNEL_LABEL, approvalText, label } from "@/lib/format";
import { HeroBand, SCREEN_ZH, ScreenTag } from "@/components/ui";
import { Steps } from "antd";

type Lead = { id: string; name: string; source_key: string; postcode: string | null; website: string | null; screening_class: string; screening_reason: string | null; entity_status: string; entity_evidence: string | null };
type Asset = { id: string; kind: string; source_url: string | null; original_filename: string | null; fetch_status: string; fetch_error: string | null; storage_path: string | null; sha256: string | null };
type Item = { name: string; price_text: string; deleted?: boolean; evidence: Record<string, unknown> };
type Issue = { issue_code: string; fact: string; severity: string; confirmed: boolean | null; confirmed_by: string | null; note: string | null; deleted?: boolean; evidence: Record<string, unknown> };
type Candidates = { pdf_links?: string[]; image_candidates?: { src: string; alt: string }[]; iframes?: string[] };
type Analysis = { id: string; version: number; parent_version: number | null; status: string; engine: string; engine_version: string | null; review_state: string | null; items: Item[] | null; issues: Issue[] | null; measurements: (Record<string, unknown> & Candidates) | null; error: string | null };
type EntityCandidate = { company_number: string; name: string; company_status: string | null; company_type: string | null; date_of_creation: string | null; registered_address: string | null; sic_codes: string[] | null; food_service_sic: boolean | null; name_similarity: number; postcode_match: boolean | null; address_match: boolean | null; sources: string[]; primary: boolean; url: string; suggested_evidence: string };
type EntityLookup = { query: string; candidates: EntityCandidate[]; notice: string; website: { url: string; pages: { url: string; ok: boolean; error: string | null }[]; refs: { kind: string; value: string; page_url: string }[] } | null; postcode: { query: string; hits: number } | null };
const ENTITY_SOURCE: Record<string, { text: string; color?: string }> = { website_number: { text: "官网编号", color: "green" }, website_name: { text: "官网公司名", color: "green" }, registered_postcode: { text: "注册邮编", color: "blue" }, name_search: { text: "名称检索" } };
type Elig = { id: string; channel: string; contact_ref: string | null; contact_source: string | null; contact_usable: string; eligibility: string };
type ContactCandidate = { kind: string; channel: string; value: string; sources: { type: string; ref: string }[]; personal: boolean; mobile: boolean; recorded: boolean; eligibility: string | null; suppressed: boolean };
type ContactLookup = { candidates: ContactCandidate[]; notice: string; website: { url: string; pages: { url: string; ok: boolean; error: string | null }[] } | null };
const CONTACT_KIND: Record<string, string> = { email: "邮箱", phone: "电话", whatsapp: "WhatsApp", instagram: "Instagram", facebook: "Facebook", tiktok: "TikTok", x: "X", linkedin: "LinkedIn", youtube: "YouTube", contact_form: "联系表单" };
const contactKey = (c: ContactCandidate) => `${c.kind}|${c.value}`;
const contactHref = (channel: string, v: string) => (v.startsWith("http") ? v : channel === "email" ? `mailto:${v}` : channel === "phone" ? `tel:${v}` : channel === "whatsapp" ? `https://wa.me/${v.replace("+", "")}` : undefined);
type Content = { id: string; kind: string; version: number; status: string; approval_valid: boolean; approval_invalid_reason: string | null; body_text: string | null; html_url: string | null; png_url: string | null; spec: Record<string, unknown> | null };

const SCREENING = ["unchecked", "candidate", "unknown", "excluded_cafe", "excluded_chain", "excluded_canteen", "excluded_community", "excluded_institution", "excluded_pub", "excluded_closed", "excluded_other"];

export default function LeadDetail() {
  const { id } = useParams<{ id: string }>();
  const [lead, setLead] = useState<Lead | null>(null);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [analyses, setAnalyses] = useState<Record<string, Analysis[]>>({});
  const [content, setContent] = useState<Content[]>([]);
  const [form] = Form.useForm();
  const [entityOpen, setEntityOpen] = useState(false);
  const [entityLoading, setEntityLoading] = useState(false);
  const [entityLookup, setEntityLookup] = useState<EntityLookup | null>(null);
  const [entityAll, setEntityAll] = useState(false);
  const [eligs, setEligs] = useState<Elig[]>([]);
  const [contactOpen, setContactOpen] = useState(false);
  const [contactLoading, setContactLoading] = useState(false);
  const [contactLookup, setContactLookup] = useState<ContactLookup | null>(null);
  const [contactPicked, setContactPicked] = useState<string[]>([]);
  const err = (e: Error) => message.error(e.message);
  // 主体候选只读检索；采用后只填入表单，人工核对并保存才生效
  const searchEntity = (q?: string) => {
    setEntityOpen(true);
    setEntityLoading(true);
    setEntityAll(false);
    api<EntityLookup>(`/api/leads/${id}/entity-candidates${q ? `?q=${encodeURIComponent(q)}` : ""}`)
      .then(setEntityLookup)
      .catch(err)
      .finally(() => setEntityLoading(false));
  };

  const reload = useCallback(async () => {
    const l = await api<Lead>(`/api/leads/${id}`);
    setLead(l);
    const as = await api<Asset[]>(`/api/leads/${id}/assets`);
    setAssets(as);
    const map: Record<string, Analysis[]> = {};
    for (const a of as) map[a.id] = await api<Analysis[]>(`/api/assets/${a.id}/analyses`);
    setAnalyses(map);
    setContent(await api<Content[]>(`/api/leads/${id}/content`));
    setEligs(await api<Elig[]>(`/api/leads/${id}/eligibility`));
  }, [id]);
  useEffect(() => {
    reload().catch(err);
  }, [reload]);
  if (!lead) return null;

  // 联系方式候选只读查找；勾选并记录后才入库，且准入保持未知
  const searchContacts = () => {
    setContactOpen(true);
    setContactLoading(true);
    api<ContactLookup>(`/api/leads/${id}/contact-candidates`)
      .then((r) => { setContactLookup(r); setContactPicked(r.candidates.filter((c) => !c.recorded && !c.suppressed).map(contactKey)); })
      .catch(err)
      .finally(() => setContactLoading(false));
  };
  const recordContacts = () => {
    const items = (contactLookup?.candidates ?? []).filter((c) => contactPicked.includes(contactKey(c)) && !c.recorded)
      .map((c) => ({ channel: c.channel, contact_ref: c.value, contact_source: c.sources.map((s) => (s.type === "website" ? `官网 ${s.ref}` : s.ref)).join("；").slice(0, 256) }));
    if (!items.length) return;
    api<{ created: number; skipped: number }>(`/api/leads/${id}/contacts`, json({ items }))
      .then((r) => { message.success(`已记录 ${r.created} 项${r.skipped ? `，跳过已存在 ${r.skipped} 项` : ""}`); setContactOpen(false); reload(); })
      .catch(err);
  };

  const latest = (aid: string) => analyses[aid]?.[analyses[aid].length - 1];
  const correct = (a: Analysis, corrections: { field_path: string; new_value: unknown; reason?: string }[]) =>
    api(`/api/analyses/${a.id}`, json({ corrections }, "PATCH")).then(reload).catch(err);
  const reviewedAnalyses = Object.values(analyses).flatMap((list) => list.filter((a) => a.review_state === "reviewed" && a.id === list[list.length - 1]?.id));
  const progress = content.some((c) => c.approval_valid) ? 5 : content.length ? 4 : reviewedAnalyses.length ? 3 : Object.values(analyses).some((l) => l.length) ? 2 : assets.some((a) => a.fetch_status === "fetched") ? 1 : 0;

  return (
    <div>
      <HeroBand kicker="LEAD" title={lead.name} subtitle={<>{lead.source_key} · {lead.postcode ?? ""} · {lead.website ? <a href={lead.website} target="_blank" rel="noreferrer" style={{ color: "#fab736" }}>{lead.website}</a> : "无官网"}</>}
        extra={<><ScreenTag value={lead.screening_class} reason={lead.screening_reason} /><Tag style={{ marginInlineEnd: 0 }}>主体 {label(lead.entity_status)}</Tag></>}>
      </HeroBand>
      <Card size="small" style={{ marginBottom: 16 }} styles={{ body: { padding: "14px 20px" } }}>
        <Steps size="small" current={progress} items={[{ title: "菜单文件" }, { title: "分析" }, { title: "人工审核" }, { title: "样稿 / 文案" }, { title: "审批" }, { title: "准入与任务" }]} />
      </Card>
      <Card size="small" title="基本信息与人工判断" style={{ marginBottom: 16 }}>
        <Form
          form={form}
          layout="vertical"
          className="beacon-form-grid"
          initialValues={lead}
          onFinish={(v) => api(`/api/leads/${id}`, json(v, "PATCH")).then(() => { message.success("已保存"); reload(); }).catch(err)}
        >
          <Row gutter={16}>
            <Col xs={24} md={9}><Form.Item name="website" label="官网"><Input placeholder="https://" /></Form.Item></Col>
            <Col xs={24} md={5}><Form.Item name="screening_class" label="筛选分类"><Select options={SCREENING.map((s) => ({ value: s, label: SCREEN_ZH[s] ?? s }))} /></Form.Item></Col>
            <Col xs={24} md={10}><Form.Item name="screening_reason" label="筛选原因"><Input /></Form.Item></Col>
            <Col xs={24} md={5}><Form.Item name="entity_status" label="经营主体"><Select options={["unknown", "company", "sole_trader", "other"].map((s) => ({ value: s, label: label(s) }))} /></Form.Item></Col>
            <Col xs={24} md={19}><Form.Item name="entity_evidence" label="主体证据"><Input placeholder="例如 Companies House 编号与来源；点右下“查 Companies House”可带出" /></Form.Item></Col>
          </Row>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
            <Button onClick={() => searchEntity()}>查 Companies House</Button>
            <Button type="primary" htmlType="submit">保存</Button>
          </div>
        </Form>
      </Card>
      <Modal title="Companies House 主体候选" open={entityOpen} onCancel={() => setEntityOpen(false)} footer={null} width={1080}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>{entityLookup?.notice ?? "候选仅供人工核对。"}采用后只填入表单，核对后点“保存”才生效。</Typography.Paragraph>
        <Input.Search key={entityLookup?.query ?? lead.name} defaultValue={entityLookup?.query ?? lead.name} placeholder="店名，或官网页脚 / 隐私政策里的公司名" enterButton="按名称检索" loading={entityLoading} onSearch={(v) => v.trim() && searchEntity(v.trim())} style={{ marginBottom: 12 }} />
        {(() => {
          const all = entityLookup?.candidates ?? [];
          const shown = all.filter((c) => entityAll || c.primary);
          const web = entityLookup?.website;
          const okPages = web?.pages.filter((p) => p.ok).length ?? 0;
          const webNumbers = web?.refs.filter((r) => r.kind === "number").length ?? 0;
          return (
            <>
              {entityLookup && !entityLoading && (
                <Space size={[16, 4]} wrap style={{ marginBottom: 8 }}>
                  {web ? <Typography.Text type={okPages ? undefined : "warning"}>官网：{okPages ? `读取 ${okPages} 个页面，${webNumbers ? `找到公司编号 ${webNumbers} 个` : "未找到公司编号"}` : `抓取失败（${web.pages[0]?.error ?? "无页面"}）`}</Typography.Text> : entityLookup.postcode ? <Typography.Text type="secondary">官网：未登记</Typography.Text> : null}
                  {entityLookup.postcode && <Typography.Text>注册邮编 {entityLookup.postcode.query}：餐饮类在营公司 {entityLookup.postcode.hits} 家</Typography.Text>}
                  <span><Switch size="small" checked={entityAll} onChange={setEntityAll} /> 显示全部 {all.length} 个（默认 {all.filter((c) => c.primary).length} 个）</span>
                </Space>
              )}
              <Table<EntityCandidate> rowKey="company_number" size="small" pagination={false} loading={entityLoading} dataSource={shown} scroll={{ y: 420 }}
                locale={{ emptyText: all.length ? "没有依据较强的候选。可打开“显示全部”，或用官网 / 场所许可登记上的公司名检索；查不到不代表个体经营" : "未查到候选（不代表个体经营）" }}
                columns={[
                  { title: "公司", render: (_, c) => <><a href={c.url} target="_blank" rel="noreferrer">{c.name}</a><br /><Typography.Text type="secondary">{c.company_number}</Typography.Text></> },
                  { title: "依据", width: 150, render: (_, c) => <Space size={[0, 4]} wrap>{c.sources.map((s) => <Tag key={s} color={ENTITY_SOURCE[s]?.color}>{ENTITY_SOURCE[s]?.text ?? s}</Tag>)}{c.address_match && <Tag color="green">门牌一致</Tag>}</Space> },
                  { title: "状态", width: 86, render: (_, c) => <Tag color={c.company_status === "active" ? "green" : undefined}>{c.company_status ?? "-"}</Tag> },
                  { title: "成立", dataIndex: "date_of_creation", width: 100 },
                  { title: "注册地址", dataIndex: "registered_address", ellipsis: true },
                  { title: "邮编", width: 70, render: (_, c) => c.postcode_match === null ? "-" : c.postcode_match ? <Tag color="green">一致</Tag> : <Tag>不一致</Tag> },
                  { title: "SIC", width: 120, render: (_, c) => c.sic_codes === null ? "-" : <>{c.sic_codes.join(" / ") || "无"} {c.food_service_sic && <Tag color="gold">餐饮</Tag>}</> },
                  { title: "名称相似", dataIndex: "name_similarity", width: 76 },
                  { title: "", width: 66, render: (_, c) => <Button size="small" onClick={() => { form.setFieldsValue({ entity_status: "company", entity_evidence: c.suggested_evidence }); setEntityOpen(false); message.info("已填入表单，核对后点保存"); }}>采用</Button> },
                ]} />
            </>
          );
        })()}
      </Modal>

      <Card size="small" title="联系方式" style={{ marginBottom: 16 }} extra={<Button onClick={searchContacts}>查找联系方式</Button>}>
        <Table<Elig> rowKey="id" size="small" pagination={false} dataSource={eligs} locale={{ emptyText: "尚未记录联系方式。点“查找联系方式”从官网和 Overture 数据里找" }} columns={[
          { title: "渠道", width: 110, render: (_, e) => CHANNEL_LABEL[e.channel] ?? e.channel },
          { title: "联系值", render: (_, e) => e.contact_ref ? (contactHref(e.channel, e.contact_ref) ? <a href={contactHref(e.channel, e.contact_ref)} target="_blank" rel="noreferrer">{e.contact_ref}</a> : e.contact_ref) : "-" },
          { title: "来源", dataIndex: "contact_source", ellipsis: true },
          { title: "可用", width: 80, render: (_, e) => label(e.contact_usable) },
          { title: "准入", width: 80, render: (_, e) => <Tag color={e.eligibility === "allowed" ? "green" : e.eligibility === "blocked" ? "red" : "default"}>{label(e.eligibility)}</Tag> },
        ]} />
        {eligs.length > 0 && <Typography.Paragraph type="secondary" style={{ margin: "8px 0 0" }}>记录不等于允许使用。准入在「任务 → 渠道准入」逐条核对，未知不放行。</Typography.Paragraph>}
      </Card>
      <Modal title="联系方式候选" open={contactOpen} onCancel={() => setContactOpen(false)} width={980} okText={`记录所选 ${contactPicked.length} 项`} okButtonProps={{ disabled: !contactPicked.length || contactLoading }} onOk={recordContacts} cancelText="关闭">
        <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>{contactLookup?.notice ?? "候选仅供人工核对。"}</Typography.Paragraph>
        {contactLookup && !contactLoading && (() => {
          const web = contactLookup.website;
          const okPages = web?.pages.filter((p) => p.ok).length ?? 0;
          return <Typography.Paragraph style={{ marginBottom: 8 }} type={web && !okPages ? "warning" : undefined}>官网：{web ? (okPages ? `读取 ${okPages} 个页面` : `抓取失败（${web.pages[0]?.error ?? "无页面"}）`) : "未登记"}；共找到 {contactLookup.candidates.length} 项</Typography.Paragraph>;
        })()}
        <Table<ContactCandidate> rowKey={contactKey} size="small" pagination={false} loading={contactLoading} dataSource={contactLookup?.candidates ?? []} scroll={{ y: 420 }}
          locale={{ emptyText: "没有找到联系方式" }}
          rowSelection={{ selectedRowKeys: contactPicked, onChange: (keys) => setContactPicked(keys as string[]), getCheckboxProps: (c) => ({ disabled: c.recorded }) }}
          columns={[
            { title: "类型", width: 100, render: (_, c) => CONTACT_KIND[c.kind] ?? c.kind },
            { title: "联系值", render: (_, c) => contactHref(c.channel, c.value) ? <a href={contactHref(c.channel, c.value)} target="_blank" rel="noreferrer">{c.value}</a> : c.value },
            { title: "来源", width: 260, render: (_, c) => <Space size={[0, 4]} wrap>{c.sources.map((s) => s.type === "website" ? <Tag key={s.type} color="green"><a href={s.ref} target="_blank" rel="noreferrer">官网页面</a></Tag> : <Tag key={s.type} color="blue" title={s.ref}>Overture</Tag>)}</Space> },
            { title: "提示", width: 220, render: (_, c) => <Space size={[0, 4]} wrap>
              {c.personal && <Tag color="orange">可能是个人邮箱</Tag>}
              {c.mobile && <Tag>手机号</Tag>}
              {c.suppressed && <Tag color="red">在抑制名单</Tag>}
              {c.recorded && <Tag color="default">已记录 · 准入{label(c.eligibility)}</Tag>}
            </Space> },
          ]} />
      </Modal>

      <Card size="small" title="菜单文件" style={{ marginBottom: 16 }} extra={
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
          { title: "类型", dataIndex: "kind", width: 80 },
          { title: "来源", ellipsis: true, render: (_, a) => a.source_url ?? a.original_filename ?? "-" },
          { title: "状态", width: 120, render: (_, a) => <>{label(a.fetch_status)} {a.fetch_error && <Typography.Text type="danger">{a.fetch_error}</Typography.Text>}</> },
          { title: "文件", width: 70, render: (_, a) => a.storage_path ? <a href={`/api/files/${a.storage_path}`} target="_blank" rel="noreferrer">打开</a> : "-" },
          { title: "操作", width: 330, render: (_, a) => <Space>
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
          <Card key={a.id} size="small" style={{ marginBottom: 16 }} title={`证据与修正 · ${a.kind} · 分析 v${an.version}（${an.engine}，${label(an.status)}）`} extra={
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
    </div>
  );
}
