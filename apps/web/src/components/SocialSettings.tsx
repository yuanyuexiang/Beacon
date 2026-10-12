"use client";
import { Alert, Button, Card, Form, Input, InputNumber, Modal, Select, Space, Switch, Table, Tag, Typography, message } from "antd";
import { useCallback, useEffect, useState } from "react";
import { api, json } from "@/lib/api";
import { ChannelAccount } from "@/lib/outreach";
import { channelLabel } from "@/lib/format";

type Status = { configured: boolean; message?: string; app?: { configured: boolean; app_id?: string; version: string; redirect_uri?: string; webhook_configured: boolean } };
export default function SocialSettings() {
  const [status, setStatus] = useState<Status>();
  const [accounts, setAccounts] = useState<ChannelAccount[]>([]);
  const [busy, setBusy] = useState(false);
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
    if (result === "connected") message.success("Meta 账号已连接，发送默认暂停");
    if (result === "failed") message.error("Meta 授权未完成，请核对应用权限与回调地址");
  }, [refresh, appForm]);
  const act = async (work: () => Promise<void>) => {
    setBusy(true); try { await work(); await refresh(); } catch (e) { message.error((e as Error).message); } finally { setBusy(false); }
  };
  return <Card title="Facebook / Instagram 渠道" style={{ marginBottom: 16 }}>
    {!status?.configured && <Alert type="warning" message={status?.message || "正在检查服务连接"} style={{ marginBottom: 12 }} />}
    <Typography.Paragraph>支持本方主页或专业账号的普通文字回复。餐厅公开主页保留在线索中；API 回复需要对方先发消息，再在任务页面关联会话。发送与队列默认暂停。</Typography.Paragraph>
    <Typography.Paragraph>应用：{status?.app?.configured ? `已配置 ${status.app.app_id}` : "待配置"} · Webhook：{status?.app?.webhook_configured ? "已配置验证凭据，仍需在 Meta 控制台订阅" : "待配置"}</Typography.Paragraph>
    <details style={{ marginBottom: 16 }}><summary>配置 Meta 应用</summary>
      <Form form={appForm} layout="vertical" initialValues={{ version: "v25.0", redirect_uri: "http://localhost:3000/api/outreach/oauth/callback" }} onFinish={(values) => act(async () => { await api("/api/outreach/app", json(values, "PUT")); appForm.resetFields(["app_secret", "verify_token"]); message.success("应用配置已保存；凭据不会回显"); })} style={{ maxWidth: 600 }}>
        <Form.Item name="app_id" label="App ID" rules={[{ required: true }]}><Input autoComplete="off" /></Form.Item>
        <Form.Item name="app_secret" label="App Secret" rules={[{ required: true }]}><Input.Password autoComplete="new-password" /></Form.Item>
        <Form.Item name="verify_token" label="Webhook Verify Token（自设至少 16 字符）" rules={[{ required: true, min: 16 }]}><Input.Password autoComplete="new-password" /></Form.Item>
        <Form.Item name="version" label="Graph API 版本" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="redirect_uri" label="OAuth 回调地址" rules={[{ required: true }]}><Input /></Form.Item>
        <Typography.Paragraph type="secondary">Webhook 地址：部署域名 + /api/outreach/webhook。公网需 HTTPS。Facebook Login 可浏览器授权；Instagram Login 首期导入已有 Token。</Typography.Paragraph>
        <Button htmlType="submit" loading={busy} disabled={!status?.configured}>保存应用</Button>
      </Form>
    </details>
    <Table<ChannelAccount> size="small" rowKey="id" dataSource={accounts} pagination={false} columns={[
      { title: "账号", render: (_, a) => <>{a.label}<br /><Typography.Text type="secondary">{channelLabel(a.platform)} · {a.sender_id}</Typography.Text></> },
      { title: "状态", render: (_, a) => <Space wrap><Tag color={a.connected ? "green" : "default"}>{a.connected ? "连接已检查" : "待授权 / 检查"}</Tag><Tag>{a.sending_enabled ? "允许发送" : "发送暂停"}</Tag><Tag>{a.queue_enabled ? "队列运行" : "队列暂停"}</Tag></Space> },
      { title: "操作", render: (_, a) => <Space wrap>
        <Button size="small" onClick={() => { setTokenAccount(a); setToken(""); }}>导入 Token</Button>
        {a.auth_mode === "facebook_login" && <Button size="small" loading={busy} onClick={() => act(async () => { const r = await api<{ url: string }>(`/api/outreach/accounts/${a.id}/connect`, json({})); window.location.assign(r.url); })}>浏览器授权</Button>}
        <Button size="small" loading={busy} onClick={() => act(async () => { await api(`/api/outreach/accounts/${a.id}/check`, json({})); message.success("身份检查通过；真实消息权限仍需账号联调"); })}>检查连接</Button>
        <Button size="small" onClick={() => { setEditing(a); policyForm.setFieldsValue(a); }}>发送设置</Button>
        <Button size="small" danger loading={busy} onClick={() => act(async () => { await api(`/api/outreach/accounts/${a.id}/disconnect`, json({})); })}>断开</Button>
      </Space> },
    ]} />
    <details style={{ marginTop: 16 }}><summary>添加发送账号（可以暂不授权）</summary>
      <Form form={accountForm} layout="vertical" initialValues={{ platform: "facebook", auth_mode: "facebook_login" }} style={{ maxWidth: 600 }} onFinish={(v) => act(async () => { await api("/api/outreach/accounts", json(v)); accountForm.resetFields(); message.success("账号已建立，可稍后补齐授权"); })}>
        <Form.Item name="label" label="账号名称" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="platform" label="渠道"><Select options={[{ value: "facebook", label: "Facebook" }, { value: "instagram", label: "Instagram" }]} /></Form.Item>
        <Form.Item name="auth_mode" label="认证路线"><Select options={[{ value: "facebook_login", label: "Facebook Login（FB 或关联 Page 的 INS）" }, { value: "instagram_login", label: "Instagram Login（INS Token 导入）" }]} /></Form.Item>
        <Form.Item name="sender_id" label="发送账号 ID（FB Page ID 或 INS 专业账号 ID）" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="page_id" label="关联 Facebook Page ID（INS 浏览器授权需要）"><Input /></Form.Item>
        <Button htmlType="submit" loading={busy}>添加账号</Button>
      </Form>
    </details>
    <Modal title={`导入 ${tokenAccount?.label || ""} 的 Access Token`} open={!!tokenAccount} onCancel={() => { setTokenAccount(undefined); setToken(""); }} onOk={() => act(async () => { await api(`/api/outreach/accounts/${tokenAccount!.id}/credentials`, json({ token }, "PUT")); setToken(""); setTokenAccount(undefined); message.success("授权已保存，请检查连接"); })} confirmLoading={busy} okButtonProps={{ disabled: !token.trim() }}>
      <Typography.Paragraph>Facebook 使用 Page Token；INS Facebook Login 使用关联 Page Token；INS Instagram Login 使用该专业账号的 Token。导入会暂停发送并使旧预览失效。</Typography.Paragraph>
      <Input.Password value={token} onChange={(e) => setToken(e.target.value)} autoComplete="new-password" />
    </Modal>
    <Modal title={`发送设置 ${editing?.label || ""}`} open={!!editing} onCancel={() => setEditing(undefined)} onOk={() => policyForm.submit()} confirmLoading={busy}>
      <Form form={policyForm} layout="vertical" onFinish={(v) => act(async () => { await api(`/api/outreach/accounts/${editing!.id}/policy`, json(v, "PUT")); setEditing(undefined); })}>
        <Form.Item name="sending_enabled" label="允许发送" valuePropName="checked"><Switch /></Form.Item>
        <Form.Item name="queue_enabled" label="运行批量队列" valuePropName="checked"><Switch /></Form.Item>
        <Form.Item name="daily_limit" label="滚动 24 小时尝试限额" rules={[{ required: true }]}><InputNumber min={1} max={100000} precision={0} /></Form.Item>
      </Form>
      <Typography.Paragraph type="secondary">仍需完整预览确认、渠道准入和有效会话；开启开关不会自动生成营销任务。</Typography.Paragraph>
    </Modal>
  </Card>;
}
