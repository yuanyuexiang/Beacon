"use client";
import { useEffect, useRef, useState } from "react";
import { Alert, AutoComplete, Button, Card, Collapse, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Switch, Table, Tag, Typography, message } from "antd";
import { api, json } from "@/lib/api";
import { useSettingsDraft, useSettingsStatus } from "./SettingsState";
import AiObservations from "./AiObservations";

type Check = { status: string; error?: string; duration_ms: number };
type Test = { at: string; status: string; checks: Record<string, Check> };
type Connection = { id: string; label: string; provider: string; protocol: string; base_url: string; model: string; vision: boolean; enabled: boolean; json_mode: boolean; timeout: number; key_configured?: boolean; key?: string; test?: Test };
type Configuration = { version: string | null; connections: Connection[]; routes: Record<string, string | null>; source: string; environment?: Connection; presets: { id: string; label: string; base_url: string; protocol: string; docs: string }[] };
const fields = ["id", "label", "provider", "protocol", "base_url", "model", "vision", "enabled", "json_mode", "timeout", "key"] as const;
const purposeLabels = { default: "默认模型", research: "资料理解", vision: "菜单识别", writing: "文案生成" };
const checkLabels: Record<string, string> = {text: "文本返回", structured: "JSON 解析", vision: "图片识别"};

export default function AiSettings() {
  const [state, setState] = useState<Configuration>();
  const [rows, setRows] = useState<Connection[]>([]);
  const [routes, setRoutes] = useState<Record<string, string | null>>({});
  const [dirty, setDirty] = useState(false);
  const [editing, setEditing] = useState<Connection>();
  const [formDirty, setFormDirty] = useState(false);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const locks = useRef(new Set<string>());
  const [error, setError] = useState("");
  const [allowed, setAllowed] = useState<boolean>();
  const [models, setModels] = useState<string[]>([]);
  const [modelError, setModelError] = useState("");
  const [modelsOpen, setModelsOpen] = useState(false);
  const [modelSearch, setModelSearch] = useState("");
  const modelRequest = useRef(0);
  const [form] = Form.useForm<Connection>();
  useSettingsDraft("ai", dirty || formDirty);
  useSettingsStatus("ai", !state ? "未检查" : state.source === "environment" ? state.environment ? "服务器配置" : "未配置" : routes.default ? "已配置" : "待选模型");
  const load = async () => {
    const next = await api<Configuration>("/api/ai/settings");
    setState(next); setRows(next.connections); setRoutes(next.routes); setDirty(false);
  };
  useEffect(() => { api<{role: string}>("/api/auth/me").then(op => {
    setAllowed(op.role === "admin"); if (op.role === "admin") return load();
  }).catch(e => setError(e.message)); }, []);
  const act = async (key: string, work: () => Promise<void>) => {
    if (locks.current.size) return;
    locks.current.add(key); setBusy({[key]: true}); setError("");
    try { await work(); } catch (e) { setError((e as Error).message); }
    finally { locks.current.delete(key); setBusy({}); }
  };
  const locked = Object.values(busy).some(Boolean);
  const edit = (row?: Connection) => {
    const initial = row ? {...row, key: row.key || ""} : { id: crypto.randomUUID(), label: "", provider: "deepseek", protocol: "chat", base_url: "https://api.deepseek.com", model: "", enabled: true, vision: false, json_mode: true, timeout: 90 };
    modelRequest.current++; setModelsOpen(false); setModelSearch(""); setModels([]); setModelError(""); setEditing(initial as Connection); setFormDirty(false); form.setFieldsValue(initial);
  };
  const save = () => act("save", async () => {
    const payload = rows.map(row => Object.fromEntries(fields.filter(k => row[k] !== undefined).map(k => [k, row[k]])));
    await api("/api/ai/settings", json({version: state?.version, connections: payload, routes}, "PUT"));
    await load(); message.success("AI 配置已保存，新任务使用新配置");
  });
  const test = (row: Connection) => act(`test:${row.id}`, async () => {
    await api<Test>(`/api/ai/connections/${row.id}/test`, json({version: state?.version}));
    await load();
  });
  const fetchModels = async () => {
    try { await form.validateFields(["provider", "base_url", "key"]); } catch { return; }
    const request = ++modelRequest.current;
    setBusy({models: true}); setModelError(""); setModels([]);
    const values = form.getFieldsValue(true);
    try {
      const next = await api<{models: string[]}>("/api/ai/models", json({
        ...Object.fromEntries(fields.filter(k => values[k] !== undefined).map(k => [k, values[k]])),
        model: values.model || "", version: state?.version,
        saved_id: state?.connections.some(r => r.id === editing?.id) ? editing?.id : undefined,
      }));
      if (request !== modelRequest.current) return;
      setModels(next.models); setModelSearch(""); setModelsOpen(next.models.length > 0);
      if (!next.models.length) setModelError("供应商未返回模型列表，可直接手动输入模型 ID。");
    } catch (e) { if (request === modelRequest.current) setModelError((e as Error).message); }
    finally { if (request === modelRequest.current) setBusy({}); }
  };
  if (allowed === false) return <Card title="AI 模型"><Alert type="info" message="AI 模型由管理员配置；业务功能使用工作空间的模型设置。" /></Card>;
  const options = rows.filter(r => r.enabled).map(r => ({value: r.id, label: `${r.label} · ${r.model}`}));
  return <>
    <Card title="AI 模型" extra={<Button type="primary" disabled={locked || !state} onClick={() => edit()}>添加连接</Button>}>
      {error && <Alert type="error" showIcon message={error} style={{marginBottom: 16}} />}
      <Typography.Paragraph type="secondary">添加模型连接，选择默认模型即可开始。资料理解、菜单识别和英文文案可按需使用不同模型。</Typography.Paragraph>
      {state?.source === "environment" && <Alert type="info" showIcon message={state.environment ? `当前使用服务器配置：${state.environment.provider} · ${state.environment.model}` : "尚未配置真实 AI"} description="网页管理配置保存后优先使用；运行中的任务保留原配置版本。" action={state.environment && <Button disabled={locked || dirty} loading={busy.import} onClick={() => act("import", async () => {await api("/api/ai/import-environment", json({version: state.version})); await load();})}>导入现有配置</Button>} style={{marginBottom: 16}} />}
      <Table<Connection> rowKey="id" size="small" dataSource={rows} pagination={false} scroll={{x: 760}} locale={{emptyText: "添加连接或导入现有服务器配置"}} columns={[
        {title: "连接", render: (_, r) => <><strong>{r.label}</strong><br /><Typography.Text type="secondary">{state?.presets.find(p => p.id === r.provider)?.label || r.provider}</Typography.Text></>},
        {title: "模型", dataIndex: "model"},
        {title: "状态", render: (_, r) => <Space direction="vertical" size={4}><Space wrap><Tag color={r.enabled ? "green" : "default"}>{r.enabled ? "启用" : "停用"}</Tag><Tag>{r.key || r.key_configured ? "密钥已配置" : "待填密钥"}</Tag>{r.vision && <Tag>图片输入</Tag>}</Space>{r.test ? <><Tag color={r.test.status === "passed" ? "green" : "red"}>{r.test.status === "passed" ? "测试通过" : "测试失败"}</Tag>{Object.entries(r.test.checks).map(([key, result]) => <Typography.Text key={key} type={result.status === "passed" ? "secondary" : "danger"}>{checkLabels[key]}：{result.status === "passed" ? "通过" : result.error} · {(result.duration_ms/1000).toFixed(1)} 秒</Typography.Text>)}<Typography.Text type="secondary">{new Date(r.test.at).toLocaleString()}</Typography.Text></> : <Typography.Text type="secondary">未测试或配置已修改</Typography.Text>}</Space>},
        {title: "操作", render: (_, r) => <Space wrap><Button size="small" disabled={locked} onClick={() => edit(r)}>编辑</Button><Button size="small" disabled={locked || dirty} loading={busy[`test:${r.id}`]} onClick={() => test(r)}>测试能力</Button><Popconfirm title="移除这个连接？" description="保存后，引用该连接的旧任务将停止 AI 调用。" onConfirm={() => {setRows(rows.filter(x => x.id !== r.id)); setRoutes(Object.fromEntries(Object.entries(routes).map(([key, value]) => [key, value === r.id ? null : value]))); setDirty(true);}}><Button size="small" danger disabled={locked}>移除</Button></Popconfirm></Space>},
      ]} />
      <Typography.Paragraph type="secondary" style={{marginTop: 12}}>能力测试使用固定测试内容，产生少量 API 调用。结果会保留；密钥无效、模型不存在和供应商限流会显示具体原因。</Typography.Paragraph>
      <div style={{maxWidth: 700, marginTop: 24}}>
        <Typography.Title level={5}>使用设置</Typography.Title>
        <Form layout="vertical">
          <Form.Item label="默认模型"><Select aria-label="默认模型" allowClear placeholder="选择默认模型连接" value={routes.default || undefined} options={options} disabled={locked} onChange={value => {setRoutes({...routes, default: value || null}); setDirty(true);}} /></Form.Item>
          <Collapse items={[{key: "purposes", label: "按用途指定模型（可选）", children: <>{(["research", "vision", "writing"] as const).map(key => <Form.Item key={key} label={purposeLabels[key]}><Select aria-label={purposeLabels[key]} allowClear placeholder="继承默认模型" value={routes[key] || undefined} options={key === "vision" ? options.filter(o => rows.find(r => r.id === o.value)?.vision) : options} disabled={locked} onChange={value => {setRoutes({...routes, [key]: value || null}); setDirty(true);}} /></Form.Item>)}</>}]} />
        </Form>
        {routes.default && !rows.find(r => r.id === (routes.vision || routes.default))?.vision && <Alert type="info" message="当前未选择支持图片的菜单识别模型，图片或扫描菜单将提示配置；文本资料功能可正常使用。" style={{marginTop: 12}} />}
        <Space wrap style={{marginTop: 16}}><Button type="primary" loading={busy.save} disabled={locked || !dirty} onClick={save}>保存 AI 配置</Button><Button disabled={locked || !dirty} onClick={() => act("reload", load)}>放弃修改</Button>{dirty && <Typography.Text type="secondary">先保存修改，再测试连接。</Typography.Text>}</Space>
      </div>
    </Card>
    <div style={{marginTop: 20}}><AiObservations source="/api/ai/calls" /></div>
    <Modal title={rows.some(r => r.id === editing?.id) ? "编辑模型连接" : "添加模型连接"} open={!!editing} okButtonProps={{disabled: !!busy.models}} onCancel={() => {modelRequest.current++; setBusy({}); setEditing(undefined); setFormDirty(false); form.resetFields();}} okText="加入配置" onOk={() => form.submit()} width={660} destroyOnHidden>
      <Form form={form} disabled={busy.models} layout="vertical" onValuesChange={changed => {setFormDirty(true); if (["provider", "base_url", "key", "protocol"].some(k => k in changed)) {modelRequest.current++; setModels([]); setModelError("");}}} onFinish={values => {const row = {...editing!, ...values, test: undefined}; setRows(old => old.some(r => r.id === row.id) ? old.map(r => r.id === row.id ? row : r) : [...old, row]); setDirty(true); setFormDirty(false); setEditing(undefined); form.resetFields();}}>
        <Form.Item name="label" label="连接名称" rules={[{required: true}]}><Input placeholder="例如：日常资料处理" /></Form.Item>
        <Form.Item name="provider" label="供应商" rules={[{required: true}]}><Select options={state?.presets.map(p => ({value:p.id, label:p.label}))} onChange={value => {const preset = state?.presets.find(p => p.id === value); if (preset) form.setFieldsValue({base_url:preset.base_url, protocol:preset.protocol, model: ""});}} /></Form.Item>
        <Form.Item name="base_url" label="接口地址（Base URL）" rules={[{required: true}]}><Input /></Form.Item>
        <Typography.Paragraph type="secondary">接口与密钥需属于同一区域和套餐。豆包可填写模型 ID 或推理接入点 ID；请勿填写完整的 chat/completions 地址。</Typography.Paragraph>
        <Form.Item name="key" label="API Key" extra={editing?.key_configured ? "留空保留原密钥；完整密钥不会回显。" : "密钥只在服务器加密保存。"} rules={[{required: !editing?.key_configured}]}><Input.Password autoComplete="new-password" visibilityToggle={false} /></Form.Item>
        <Form.Item label="模型 ID" required>
          <Space.Compact style={{width: "100%"}}>
            <Form.Item name="model" noStyle rules={[{required: true, message: "请选择或输入模型 ID"}]}>
              <AutoComplete aria-label="模型 ID" style={{width: "100%"}} options={models.map(value => ({value}))} open={modelsOpen} onOpenChange={setModelsOpen} onSearch={value => {setModelSearch(value); setModelsOpen(true);}} onSelect={() => setModelsOpen(false)} filterOption={(_, option) => String(option?.value).toLowerCase().includes(modelSearch.toLowerCase())} placeholder="获取后下拉选择，也可手动输入模型 ID" />
            </Form.Item>
            <Button loading={busy.models} onClick={fetchModels}>获取模型</Button>
          </Space.Compact>
          {modelError && <Alert type="warning" showIcon message={modelError} style={{marginTop: 8}} />}
          {!!models.length && <Typography.Text type="secondary">已获取 {models.length} 个模型，可搜索选择；图片能力需单独测试。</Typography.Text>}
        </Form.Item>
        <Form.Item name="vision" label="该模型支持图片输入" valuePropName="checked"><Switch /></Form.Item>
        <Collapse items={[{key:"advanced", label:"高级设置", children:<><Form.Item name="protocol" label="接口协议"><Select options={[{value:"chat",label:"OpenAI 兼容 Chat Completions"},{value:"responses",label:"OpenAI Responses"},{value:"anthropic",label:"Anthropic Messages"}]} /></Form.Item><Form.Item name="json_mode" label="请求原生 JSON／结构化输出" valuePropName="checked"><Switch /></Form.Item><Form.Item name="timeout" label="请求超时（秒）"><InputNumber min={10} max={300} /></Form.Item><Form.Item name="enabled" label="启用连接" valuePropName="checked"><Switch /></Form.Item></>}]} />
      </Form>
    </Modal>
  </>;
}
