"use client";
import { Alert, Button, Card, Form, Input, InputNumber, Modal, Space, Switch, Typography } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, json } from "@/lib/api";

type Action = "connect" | "replies" | "check" | "refresh" | "disconnect" | "configure" | "policy" | "import" | "testPreview" | "testSend";
type Policy = { sending_enabled: boolean; queue_enabled: boolean; daily_limit: number };
type Status = { configured: boolean; message?: string; connection_error?: string; connected?: boolean; token_present?: boolean; send_authorized?: boolean; readonly_authorized?: boolean; email?: string; policy?: Policy; client_type?: string; redirect_uri?: string; pending_configuration?: boolean; oauth_configured?: boolean };
const ERRORS: Record<string, string> = {
  invalid_grant: "Google 授权失效或授权码不可用，请重新连接。若反复失效，请核对 Google 项目的 Testing 状态。",
  invalid_client: "OAuth 客户端无效，请检查对应环境的 Web 客户端配置。",
  redirect_uri_mismatch: "回调地址不一致，请将下方完整地址登记到 Google 客户端。",
  access_denied: "授权已取消，或账号不在 Google 项目的测试用户中。",
  missing_send_scope: "未授予发送权限，请重新连接并允许发送邮件。",
  missing_read_scope: "未授予回复同步权限，原连接保留，可再次开启回复同步。",
  account_identity_failed: "暂时无法验证邮箱身份，请检查网络和账号身份权限后重试。",
  browser_blocked: "请在正常 Chrome 或 Safari 中完成 Google 登录。",
  oauth_failed: "授权会话过期、登录状态变化或连接失败，请保持管理员登录后重新连接。",
};
export default function GmailSettings() {
  const [testTo, setTestTo] = useState("");
  const [testPreview, setTestPreview] = useState<{to: string[]; subject: string; body: string; from_email: string; approval_token: string; request_key: string} | null>(null);
  const [testResult, setTestResult] = useState<string>();
  const [testSubmitted, setTestSubmitted] = useState(false);
  const [status, setStatus] = useState<Status | null>(null);
  const [webCredentials, setWebCredentials] = useState<File | null>(null);
  const [credentials, setCredentials] = useState<File | null>(null);
  const [token, setToken] = useState<File | null>(null);
  const [activeAction, setActiveAction] = useState<Action | null>(null);
  const inFlight = useRef(false);
  const busy = activeAction !== null;
  const blocked = (action: Action) => busy && activeAction !== action;
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [form] = Form.useForm<Policy>();
  const refresh = useCallback(async () => {
    const next = await api<Status>("/api/gmail/status");
    setStatus(next); if (next.policy) form.setFieldsValue(next.policy);
  }, [form]);
  useEffect(() => {
    refresh().catch((e) => setError(e.message));
    const params = new URLSearchParams(window.location.search);
    if (params.get("gmail") === "connected") setNotice("Gmail 已连接。发送已暂停，请核对邮箱后再开启。");
    if (params.get("gmail") === "failed") setError(ERRORS[params.get("gmail_error") || "oauth_failed"] || ERRORS.oauth_failed);
  }, [refresh]);
  const act = async (action: Action, work: () => Promise<void>) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setActiveAction(action); setError(undefined); setNotice(undefined);
    try { await work(); } catch (e) { setError((e as Error).message); await refresh().catch(() => {}); } finally { inFlight.current = false; setActiveAction(null); }
  };
  const files = async (legacy: boolean) => {
    const selected = legacy ? credentials : webCredentials;
    if (!selected) throw new Error("请选择 Google OAuth 客户端 JSON");
    if (selected.size > 65536 || (token && token.size > 65536)) throw new Error("文件不能超过 64 KB");
    if (legacy && !token) throw new Error("高级导入需同时选择对应的 Token JSON");
    let c, t;
    try { c = JSON.parse(await selected.text()); t = legacy ? JSON.parse(await token!.text()) : undefined; } catch { throw new Error("文件不是有效的 JSON，请重新选择"); }
    if (!legacy && !c.web) throw new Error("请选择 Web application 类型客户端；Desktop 请使用高级导入");
    await api(legacy ? "/api/gmail/credentials" : "/api/gmail/configure", json({ credentials: c, token: t }));
    if (legacy) { setCredentials(null); setToken(null); } else setWebCredentials(null);
    await refresh();
    setNotice(legacy ? "已有授权已验证并导入。发送保持暂停。" : "Web 客户端已保存，原连接保留。现在可以连接 Gmail。");
  };
  const connect = (purpose: "send" | "replies") => act(purpose === "send" ? "connect" : "replies", async () => {
    if (status?.redirect_uri && new URL(status.redirect_uri).origin !== window.location.origin) throw new Error(`当前访问地址与回调不一致，请从 ${new URL(status.redirect_uri).origin}/settings 打开工作台后重新连接。`);
    const result = await api<{ url: string }>("/api/gmail/connect", json({ purpose }));
    window.location.assign(result.url);
  });
  const web = status?.client_type === "web";
  return <Card title="Gmail 邮箱连接" style={{ marginBottom: 16 }}>
    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
    {notice && <Alert type="success" showIcon message={notice} style={{ marginBottom: 12 }} />}
    {status && !status.configured && <Alert type="warning" message={status.message || "Gmail 服务暂不可达"} />}
    {status?.connection_error && <Alert type="warning" message={status.connection_error} style={{ marginBottom: 12 }} />}
    <Typography.Paragraph><strong>{status?.email || "尚未连接邮箱"}</strong> · 连接：{status?.connected ? "已验证" : "待连接／检查"} · 发送权限：{status?.send_authorized ? "已授权" : "未授权"} · 回复同步：{status?.readonly_authorized ? "已授权邮件头读取" : "未开启"}</Typography.Paragraph>
    <Space wrap style={{ marginBottom: 16 }}>
      <Button type="primary" loading={activeAction === "connect"} disabled={blocked("connect") || !web} onClick={() => void connect("send")}>{status?.token_present ? "重新连接 Gmail" : "连接 Gmail"}</Button>
      <Button loading={activeAction === "replies"} disabled={blocked("replies") || !web || !status?.connected} onClick={() => void connect("replies")}>开启／重新授权回复同步</Button>
      <Button disabled={blocked("check") || !status?.token_present} loading={activeAction === "check"} onClick={() => act("check", async () => { await api("/api/gmail/check", json({})); await refresh(); setNotice("连接检查成功，未发送邮件。"); })}>检查连接</Button>
      <Button disabled={blocked("refresh")} loading={activeAction === "refresh"} onClick={() => act("refresh", refresh)}>刷新状态</Button>
      <Button danger disabled={blocked("disconnect") || !status?.token_present} loading={activeAction === "disconnect"} onClick={() => act("disconnect", async () => { await api("/api/gmail/disconnect", json({})); await refresh(); })}>断开并暂停发送</Button>
    </Space>
    {(!web || status?.pending_configuration) && <Alert type="info" showIcon message={status?.client_type === "desktop" ? "现有 Desktop 授权可继续使用；网页重新连接需要配置 Web 客户端" : status?.pending_configuration ? "新客户端等待授权验证，原邮箱连接尚未替换" : "首次由管理员配置 Web OAuth，之后直接点击连接，无需终端或 Token 文件"} style={{ marginBottom: 12 }} />}
    <details open={!status?.oauth_configured}><summary>管理员首次配置／更换 Web 客户端</summary>
      <Typography.Paragraph>在 Google 项目中启用 Gmail API，创建 Web application 客户端，登记以下回调地址后下载 JSON。测试中的项目还需添加登录账号为测试用户。本地与云端建议使用不同客户端。</Typography.Paragraph>
      <Typography.Paragraph copyable={!!status?.redirect_uri} code>{status?.redirect_uri || "等待服务返回当前环境回调地址"}</Typography.Paragraph>
      <Typography.Paragraph type="secondary">本地回调由浏览器访问 localhost，不需要公网连接。本操作先保存候选配置，授权验证成功后才替换原连接。</Typography.Paragraph>
      <Space wrap><label>Web OAuth 客户端 JSON <input disabled={busy} type="file" accept=".json" onChange={(e) => setWebCredentials(e.target.files?.[0] ?? null)} /></label><Button disabled={blocked("configure") || !status?.redirect_uri} loading={activeAction === "configure"} onClick={() => act("configure", () => files(false))}>保存 Web 客户端</Button></Space>
    </details>
    <Form form={form} layout="inline" initialValues={{ sending_enabled: false, queue_enabled: false, daily_limit: 0 }} onFinish={(values) => act("policy", async () => { await api("/api/gmail/policy", json(values, "PUT")); await refresh(); setNotice("发送设置已保存。"); })} style={{ margin: "20px 0 12px", rowGap: 8 }}>
      <Form.Item name="sending_enabled" label="允许发送" valuePropName="checked"><Switch disabled={busy || !status?.connected || !status?.send_authorized} /></Form.Item>
      <Form.Item name="queue_enabled" label="运行批量队列" valuePropName="checked"><Switch disabled={busy || !status?.connected || !status?.send_authorized} /></Form.Item>
      <Form.Item name="daily_limit" label="滚动 24 小时限额"><InputNumber min={0} max={100000} precision={0} /></Form.Item>
      <Button htmlType="submit" loading={activeAction === "policy"} disabled={blocked("policy") || !status?.policy}>保存发送设置</Button>
    </Form>
    <Typography.Paragraph type="secondary">连接成功不会自动发送。首次建议限额 1、批量队列关闭；逐封预览并确认后执行。0 表示不设本地限额。</Typography.Paragraph>
    <div style={{ marginTop: 20, marginBottom: 16 }}>
      <Typography.Title level={5}>发送测试邮件</Typography.Title>
      <Typography.Paragraph type="secondary">输入你自己的邮箱，预览确认后发送一封固定测试邮件。不会开启客户发送或批量队列；仍受发送限额约束。</Typography.Paragraph>
      <Space wrap>
        <Input aria-label="测试收件邮箱" placeholder="你的收件邮箱" value={testTo} disabled={busy} onChange={e => setTestTo(e.target.value)} style={{ width: 320 }} />
        <Button disabled={blocked("testPreview") || !status?.connected || !status?.send_authorized || !testTo.trim()} loading={activeAction === "testPreview"} onClick={() => act("testPreview", async () => {
          const preview = await api<{to: string[]; subject: string; body: string; from_email: string; approval_token: string}>("/api/gmail/test/preview", json({to: [testTo.trim()]}));
          setTestPreview({...preview, request_key: crypto.randomUUID()}); setTestSubmitted(false); setTestResult(undefined);
        })}>预览测试邮件</Button>
      </Space>
      {testResult && <Alert style={{marginTop: 12}} type="info" showIcon message={testResult} />}
      <Modal title="确认发送测试邮件" open={!!testPreview} onCancel={() => { if (!busy) setTestPreview(null); }} footer={[
        <Button key="cancel" disabled={busy} onClick={() => setTestPreview(null)}>关闭</Button>,
        <Button key="send" type="primary" disabled={busy || testSubmitted} loading={activeAction === "testSend"} onClick={() => act("testSend", async () => {
          if (!testPreview) return;
          setTestSubmitted(true);
          setTestResult("正在提交；若连接中断，结果可能未知，请检查收件箱和 Gmail 已发送邮件，勿直接重发。");
          const result = await api<{status: string; sent_at?: string; reason?: string}>("/api/gmail/test/send", json({to: testPreview.to, approval_token: testPreview.approval_token, request_key: testPreview.request_key}));
          setTestResult(result.status === "sent" ? "Gmail 已接受测试邮件，请检查收件箱或垃圾邮件。" : result.status === "failed" ? "测试发送失败：" + (result.reason || "请检查授权、发送限额与服务记录。") : "发送结果未知，请先检查收件箱及 Gmail 已发送邮件，不要直接重发。");
          setTestPreview(null);
        })}>确认发送一封</Button>
      ]}>
        <p>发件人：{testPreview?.from_email}</p><p>收件人：{testPreview?.to.join(", ")}</p>
        <p>主题：{testPreview?.subject}</p><p style={{whiteSpace:"pre-wrap"}}>{testPreview?.body}</p>
      </Modal>
    </div>
    <details><summary>高级：导入已有 Desktop／Web 授权</summary>
      <p>仅迁移已有授权时使用。客户端与 Token 必须配套，服务器先验证再替换；失败保留原连接。</p>
      <Space direction="vertical"><label>原 OAuth 客户端 JSON <input disabled={busy} type="file" accept=".json" onChange={(e) => setCredentials(e.target.files?.[0] ?? null)} /></label><label>对应 Token JSON <input disabled={busy} type="file" accept=".json" onChange={(e) => setToken(e.target.files?.[0] ?? null)} /></label><Button disabled={blocked("import")} loading={activeAction === "import"} onClick={() => act("import", () => files(true))}>验证并导入已有授权</Button></Space>
    </details>
  </Card>;
}
