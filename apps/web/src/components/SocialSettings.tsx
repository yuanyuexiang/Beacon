"use client";
import { Alert, Button, Card, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Switch, Table, Tag, Typography, message } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSettingsDraft, useSettingsStatus } from "./SettingsState";
import { api, json } from "@/lib/api";
import { ChannelAccount } from "@/lib/outreach";
import { channelLabel } from "@/lib/format";

type Status = { configured: boolean; message?: string; app?: { configured: boolean; app_id?: string; version: string; redirect_uri?: string; webhook_configured: boolean } };
export default function SocialSettings() {
  const [drafts, setDrafts] = useState<Record<string, boolean>>({});
  const dirty = (key: string, value: boolean) => setDrafts(old => ({ ...old, [key]: value }));
  useSettingsDraft("meta", Object.values(drafts).some(Boolean));
  const [status, setStatus] = useState<Status>();
  const [accounts, setAccounts] = useState<ChannelAccount[]>([]);
  useSettingsStatus("meta", !status ? "未检查" : !status.configured ? "服务不可用" : !status.app?.configured ? "未配置" : accounts.some(a => a.connection_diagnostics?.state === "check_failed") ? "连接异常" : accounts.some(a => a.connected) ? "身份已核验" : "待授权");
  const [active, setActive] = useState<Record<string, string>>({});
  const locks = useRef(new Set<string>());
  const scopeOf = (key: string) => key.split(":")[0];
  const blocked = (scope: string) => !!active.app || !!active[scope] || (scope === "app" && Object.values(active).some(Boolean));
  const loading = (key: string) => active[scopeOf(key)] === key;
  const [editing, setEditing] = useState<ChannelAccount>();
  const [tokenAccount, setTokenAccount] = useState<ChannelAccount>();
  const [token, setToken] = useState("");
  const [appForm] = Form.useForm();
  const [accountForm] = Form.useForm();
  const [policyForm] = Form.useForm();
  const refresh = useCallback(async () => {
    const [next, rows] = await Promise.all([api<Status>("/api/outreach/status"), api<ChannelAccount[]>("/api/outreach/accounts")]);
    setStatus(next); setAccounts(rows);
  }, []);
  useEffect(() => { appForm.setFieldsValue({ redirect_uri: window.location.origin + "/api/outreach/oauth/callback" }); refresh().catch((e) => message.error(e.message));
    const result = new URLSearchParams(window.location.search).get("meta");
    if (result === "connected") message.success("Meta 账号身份已核验，发送已暂停；消息权限与订阅仍需联调");
    if (result === "failed") message.error("Meta 授权未完成，原连接已保留；请从当前管理员会话重试并核对应用权限与回调地址");
  }, [refresh, appForm]);
  const act = async (key: string, work: () => Promise<void>) => {
    const scope = scopeOf(key);
    if (locks.current.has("app") || locks.current.has(scope) || (scope === "app" && locks.current.size)) return;
    locks.current.add(scope); setActive(previous => ({...previous, [scope]: key}));
    try { await work(); await refresh(); } catch (e) { message.error((e as Error).message); await refresh().catch(() => undefined); }
    finally {
      locks.current.delete(scope);
      setActive(previous => { const next = {...previous}; delete next[scope]; return next; });
    }
  };
  return <Card title="Facebook / Instagram 渠道" style={{ marginBottom: 16 }}>
    {!status?.configured && <Alert type="warning" message={status?.message || "正在检查服务连接"} style={{ marginBottom: 12 }} />}
    <Typography.Paragraph>支持本方主页或专业账号的普通文字回复。餐厅公开主页保留在线索中；API 回复需要对方先发消息，再在任务页面关联会话。发送与队列默认暂停。</Typography.Paragraph>
    {!status?.app?.configured && <Alert type="info" message="等待客户提供 Meta 应用与本方主页信息。可先添加账号；配置应用后再授权。" style={{ marginBottom: 12 }} />}
    <Typography.Paragraph>身份核验仅确认 Token 对应账号；消息权限、Webhook 订阅与真实收发尚需分别验收。</Typography.Paragraph>
    <Typography.Paragraph>应用：{status?.app?.configured ? `已配置 ${status.app.app_id}` : "待配置"} · Webhook：{status?.app?.webhook_configured ? "已配置验证凭据，仍需在 Meta 控制台订阅" : "待配置"}</Typography.Paragraph>
    <details style={{ marginBottom: 16 }}><summary>配置 Meta 应用</summary>
      <Form onValuesChange={() => dirty("app", true)} disabled={blocked("app")} form={appForm} layout="vertical" initialValues={{ version: "v25.0", redirect_uri: "http://localhost:3000/api/outreach/oauth/callback" }} onFinish={(values) => act("app:save", async () => { await api("/api/outreach/app", json(values, "PUT")); appForm.resetFields(["app_secret", "verify_token"]); dirty("app", false); message.success("应用配置已保存；凭据不会回显"); })} style={{ maxWidth: 600 }}>
        <Form.Item name="app_id" label="App ID" rules={[{ required: true }]}><Input autoComplete="off" /></Form.Item>
        <Form.Item name="app_secret" label="App Secret" rules={[{ required: true }]}><Input.Password autoComplete="new-password" /></Form.Item>
        <Form.Item name="verify_token" label="Webhook Verify Token（自设至少 16 字符）" rules={[{ required: true, min: 16 }]}><Input.Password autoComplete="new-password" /></Form.Item>
        <Form.Item name="version" label="Graph API 版本" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="redirect_uri" label="OAuth 回调地址" rules={[{ required: true }]}><Input /></Form.Item>
        <Typography.Paragraph type="secondary">Webhook 地址：部署域名 + /api/outreach/webhook。公网需 HTTPS。Facebook Login 可浏览器授权；Instagram Login 首期导入已有 Token。</Typography.Paragraph>
        <Button htmlType="submit" loading={loading("app:save")} disabled={blocked("app") || !status?.configured}>保存应用</Button>
      </Form>
    </details>
    <Table<ChannelAccount> size="small" rowKey="id" dataSource={accounts} pagination={false} columns={[
      { title: "账号", render: (_, a) => <>{a.label}<br /><Typography.Text type="secondary">{channelLabel(a.platform)} · {a.sender_id}</Typography.Text></> },
      { title: "状态", render: (_, a) => <Space wrap><Tag color={a.connected ? "green" : "default"}>{a.connected ? "身份已核验" : ({ pending_check: "令牌已保存 · 待检查", missing_token: "未导入令牌", check_failed: "连接检查失败", disconnected: "已断开 · 需重新导入" }[a.connection_diagnostics?.state || ""] || "尚未检查")}</Tag><Tag>{a.sending_enabled ? "允许发送" : "发送暂停"}</Tag><Tag>{a.queue_enabled ? "队列运行" : "队列暂停"}</Tag>{a.connection_diagnostics?.error && <Alert type="error" showIcon message={a.connection_diagnostics.error} description="令牌无需因检查失败而断开；修正后点击检查连接。" />}{a.connection_diagnostics?.updated_at && <Typography.Text type="secondary">最近更新：{new Date(a.connection_diagnostics.updated_at).toLocaleString()}</Typography.Text>}</Space> },
      { title: "操作", render: (_, a) => <Space wrap>
        <Button size="small" disabled={blocked(a.id)} onClick={() => { setTokenAccount(a); setToken(""); dirty("token", false); }}>导入 Token</Button>
        {a.auth_mode === "facebook_login" && <Button size="small" loading={loading(`${a.id}:connect`)} disabled={blocked(a.id) || !status?.app?.configured} onClick={() => act(`${a.id}:connect`, async () => { const r = await api<{ url: string }>(`/api/outreach/accounts/${a.id}/connect`, json({})); window.location.assign(r.url); })}>浏览器授权</Button>}
        <Button size="small" loading={loading(`${a.id}:check`)} disabled={blocked(a.id)} onClick={() => act(`${a.id}:check`, async () => { await api(`/api/outreach/accounts/${a.id}/check`, json({})); message.success("身份检查通过；真实消息权限仍需账号联调"); })}>检查连接</Button>
        <Button size="small" disabled={blocked(a.id)} onClick={() => { setEditing(a); policyForm.setFieldsValue(a); }}>发送设置</Button>
        <Popconfirm title="断开并清除该账号的令牌？" description="这不会修复连接错误；重新连接需再次授权或导入令牌。" onConfirm={() => act(`${a.id}:disconnect`, async () => { await api(`/api/outreach/accounts/${a.id}/disconnect`, json({})); })}><Button size="small" danger loading={loading(`${a.id}:disconnect`)} disabled={blocked(a.id)}>断开</Button></Popconfirm>
      </Space> },
    ]} />
    <details style={{ marginTop: 16 }}><summary>添加发送账号（可以暂不授权）</summary>
      <Form onValuesChange={() => dirty("create", true)} disabled={blocked("create")} form={accountForm} layout="vertical" initialValues={{ platform: "facebook", auth_mode: "facebook_login" }} style={{ maxWidth: 600 }} onFinish={(v) => act("create:account", async () => { await api("/api/outreach/accounts", json(v)); accountForm.resetFields(); dirty("create", false); message.success("账号已建立，可稍后补齐授权"); })}>
        <Form.Item name="label" label="账号名称" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="platform" label="渠道"><Select options={[{ value: "facebook", label: "Facebook" }, { value: "instagram", label: "Instagram" }]} /></Form.Item>
        <Form.Item name="auth_mode" label="认证路线"><Select options={[{ value: "facebook_login", label: "Facebook Login（FB 或关联 Page 的 INS）" }, { value: "instagram_login", label: "Instagram Login（INS Token 导入）" }]} /></Form.Item>
        <Form.Item name="sender_id" label="发送账号 ID（FB Page ID 或 INS 专业账号 ID）" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="page_id" label="关联 Facebook Page ID（INS 浏览器授权需要）"><Input /></Form.Item>
        <Button htmlType="submit" loading={loading("create:account")} disabled={blocked("create")}>添加账号</Button>
      </Form>
    </details>
    <Modal title={`导入 ${tokenAccount?.label || ""} 的 Access Token`} open={!!tokenAccount} onCancel={() => { if (tokenAccount && blocked(tokenAccount.id)) return; setTokenAccount(undefined); setToken(""); dirty("token", false); }} onOk={() => act(`${tokenAccount!.id}:token`, async () => { await api(`/api/outreach/accounts/${tokenAccount!.id}/credentials`, json({ token }, "PUT")); setToken(""); dirty("token", false); setTokenAccount(current => current?.id === tokenAccount!.id ? undefined : current); await api(`/api/outreach/accounts/${tokenAccount!.id}/check`, json({})); message.success("令牌已保存，账号身份检查通过"); })} okText="保存并检查连接" confirmLoading={!!tokenAccount && loading(`${tokenAccount.id}:token`)} okButtonProps={{ disabled: !token.trim() || (!!tokenAccount && blocked(tokenAccount.id)) }}>
      <Typography.Paragraph>Facebook 使用 Page Token；INS Facebook Login 使用关联 Page Token；INS Instagram Login 使用该专业账号的 Token。导入会暂停发送并使旧预览失效。</Typography.Paragraph>
      <Input.Password disabled={!!tokenAccount && blocked(tokenAccount.id)} value={token} onChange={(e) => { setToken(e.target.value); dirty("token", !!e.target.value); }} autoComplete="new-password" />
    </Modal>
    <Modal title={`发送设置 ${editing?.label || ""}`} open={!!editing} onCancel={() => { if (editing && blocked(editing.id)) return; setEditing(undefined); dirty("policy", false); }} onOk={() => policyForm.submit()} confirmLoading={!!editing && loading(`${editing.id}:policy`)} okButtonProps={{disabled: !!editing && blocked(editing.id)}}>
      <Form onValuesChange={() => dirty("policy", true)} disabled={!!editing && blocked(editing.id)} form={policyForm} layout="vertical" onFinish={(v) => act(`${editing!.id}:policy`, async () => { await api(`/api/outreach/accounts/${editing!.id}/policy`, json(v, "PUT")); dirty("policy", false); setEditing(current => current?.id === editing!.id ? undefined : current); })}>
        <Form.Item name="sending_enabled" label="允许发送" valuePropName="checked"><Switch /></Form.Item>
        <Form.Item name="queue_enabled" label="运行批量队列" valuePropName="checked"><Switch /></Form.Item>
        <Form.Item name="daily_limit" label="滚动 24 小时尝试限额" rules={[{ required: true }]}><InputNumber min={1} max={100000} precision={0} /></Form.Item>
      </Form>
      <Typography.Paragraph type="secondary">仍需完整预览确认、渠道准入和有效会话；开启开关不会自动生成营销任务。</Typography.Paragraph>
    </Modal>
  </Card>;
}
