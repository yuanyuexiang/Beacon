"use client";
import { Alert, Button, Card, Form, InputNumber, Space, Switch, Typography, message } from "antd";
import { useCallback, useEffect, useState } from "react";
import { api, json } from "@/lib/api";

type Policy = { sending_enabled: boolean; queue_enabled: boolean; daily_limit: number };
type Status = { configured: boolean; message?: string; connection_error?: string; connected?: boolean; token_present?: boolean; send_authorized?: boolean; readonly_authorized?: boolean; email?: string; policy?: Policy };
export default function GmailSettings() {
  const [status, setStatus] = useState<Status | null>(null);
  const [credentials, setCredentials] = useState<File | null>(null);
  const [token, setToken] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [form] = Form.useForm<Policy>();
  const refresh = useCallback(async () => {
    const next = await api<Status>("/api/gmail/status");
    setStatus(next); if (next.policy) form.setFieldsValue(next.policy);
  }, [form]);
  useEffect(() => {
    refresh().catch((e) => message.error(e.message));
    const result = new URLSearchParams(window.location.search).get("gmail");
    if (result === "connected") message.success("Gmail 授权完成");
    if (result === "failed") message.error("Gmail 授权未完成，请检查客户端类型及回调地址后重试");
  }, [refresh]);
  const act = async (work: () => Promise<void>) => {
    setBusy(true); try { await work(); } catch (e) { message.error((e as Error).message); await refresh().catch(() => {}); } finally { setBusy(false); }
  };
  const importFiles = async () => {
    if (!credentials) throw new Error("请选择 Google OAuth 客户端 JSON 文件");
    if (credentials.size > 65536 || (token && token.size > 65536)) throw new Error("凭据文件不能超过 64 KB");
    await api("/api/gmail/credentials", json({ credentials: JSON.parse(await credentials.text()), token: token ? JSON.parse(await token.text()) : null }));
    setCredentials(null); setToken(null); await refresh(); message.success("配置已保存，凭据不会显示在页面上");
  };
  return <Card title="Gmail 邮件服务" style={{ marginBottom: 16 }}>
    {status && !status.configured && <Alert type="warning" message={status.message || "Gmail 服务未连接"} />}
    {status?.connection_error && <Alert type="warning" message={status.connection_error} style={{ marginBottom: 12 }} />}
    <Typography.Paragraph>连接：{status?.connected ? "已验证" : "待检查"} · 权限：{status?.send_authorized ? "可发送" : "未授权发送"} · {status?.readonly_authorized ? "可同步回复邮件头" : "未授权读取"}{status?.email && ` · ${status.email}`}</Typography.Paragraph>
    <Space wrap style={{ marginBottom: 16 }}>
      <Button loading={busy} onClick={() => act(async () => { const result = await api<Status>("/api/gmail/check", json({})); await refresh(); setStatus((s) => ({ ...s!, email: result.email })); message.success("连接检查成功，未发送邮件"); })}>检查连接</Button>
      <Button loading={busy} onClick={() => act(async () => { const result = await api<{ url: string }>("/api/gmail/connect", json({})); window.location.assign(result.url); })}>连接 / 重新授权 Gmail</Button>
      <Button danger loading={busy} onClick={() => act(async () => { await api("/api/gmail/disconnect", json({})); await refresh(); })}>断开并暂停发送</Button>
      <Button onClick={() => act(refresh)}>刷新状态</Button>
    </Space>
    <Form form={form} layout="inline" initialValues={{ sending_enabled: false, queue_enabled: false, daily_limit: 0 }} onFinish={(values) => act(async () => { await api("/api/gmail/policy", json(values, "PUT")); await refresh(); message.success("发送设置已保存"); })} style={{ marginBottom: 16, rowGap: 8 }}>
      <Form.Item name="sending_enabled" label="允许发送" valuePropName="checked"><Switch /></Form.Item>
      <Form.Item name="queue_enabled" label="运行批量队列" valuePropName="checked"><Switch /></Form.Item>
      <Form.Item name="daily_limit" label="滚动 24 小时限额"><InputNumber min={0} max={100000} precision={0} /></Form.Item>
      <Button htmlType="submit" loading={busy}>保存设置</Button>
    </Form>
    <Typography.Paragraph type="secondary">两个发送开关默认关闭。只有完整预览并确认的邮件会执行；0 表示不设置本地限额，Google 账户限额仍有效。</Typography.Paragraph>
    <details><summary>配置 OAuth 或导入已有授权</summary>
      <Typography.Paragraph>服务器重新授权使用 Web application 客户端，回调地址需与部署配置一致。已有 Desktop 客户端可与原令牌一起导入检查。只上传客户端文件会清除旧令牌，需重新授权。</Typography.Paragraph>
      <Space direction="vertical">
        <label>OAuth 客户端 JSON <input type="file" accept=".json" onChange={(e) => setCredentials(e.target.files?.[0] ?? null)} /></label>
        <label>已有 Token JSON（可选） <input type="file" accept=".json" onChange={(e) => setToken(e.target.files?.[0] ?? null)} /></label>
        <Button loading={busy} onClick={() => act(importFiles)}>保存授权配置</Button>
      </Space>
    </details>
  </Card>;
}
