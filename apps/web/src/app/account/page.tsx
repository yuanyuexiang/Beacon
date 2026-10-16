"use client";
import { Alert, Button, Card, Form, Input, Space, Typography } from "antd";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, json } from "@/lib/api";
import { ROLE_LABELS, useOperator } from "@/lib/auth";
import { HeroBand } from "@/components/ui";

export default function AccountPage() {
  const { me, refresh } = useOperator();
  const router = useRouter();
  const [error, setError] = useState<string>();
  const [success, setSuccess] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [passwordForm] = Form.useForm();
  if (!me) return null;
  const act = async (work: () => Promise<void>) => { setBusy(true); setError(undefined); setSuccess(undefined); try { await work(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  return <>
    <HeroBand kicker="ACCOUNT" title="个人账号" subtitle="管理个人资料与登录密码。" />
    {me.must_change_password && <Alert type="warning" showIcon message="请先修改初始密码" description="管理员创建或重置的临时密码只能用于修改密码，完成后才能使用工作台。" style={{ marginBottom: 16 }} />}
    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}
    {success && <Alert type="success" showIcon message={success} style={{ marginBottom: 16 }} />}
    <Card title="个人资料" style={{ marginBottom: 20 }}>
      <Typography.Paragraph>登录名：{me.username} · 角色：{ROLE_LABELS[me.role]}</Typography.Paragraph>
      <Form key={me.id + (me.display_name || "")} layout="vertical" initialValues={{ display_name: me.display_name }} disabled={busy || me.must_change_password} onFinish={(v) => act(async () => { await api("/api/auth/profile", json(v, "PATCH")); await refresh(); setSuccess("个人资料已保存"); })}>
        <Form.Item name="display_name" label="显示名称" rules={[{ max: 80 }]}><Input maxLength={80} style={{ maxWidth: 400 }} /></Form.Item>
        <Button type="primary" htmlType="submit">保存资料</Button>
      </Form>
    </Card>
    <Card title="修改密码">
      <Form form={passwordForm} layout="vertical" disabled={busy} onFinish={(v) => act(async () => { await api("/api/auth/password", json({ current_password: v.current_password, new_password: v.new_password })); passwordForm.resetFields(); await refresh(); setSuccess("密码已修改，其他登录会话已失效"); })} style={{ maxWidth: 440 }}>
        <Form.Item name="current_password" label={me.must_change_password ? "当前临时密码" : "当前密码"} rules={[{ required: true, message: "请输入当前密码" }]}><Input.Password autoComplete="current-password" /></Form.Item>
        <Form.Item name="new_password" label="新密码" rules={[{ required: true, message: "请输入新密码" }, { min: 12, max: 128, message: "密码需为 12～128 个字符" }]}><Input.Password autoComplete="new-password" maxLength={128} /></Form.Item>
        <Form.Item name="confirm_password" label="再次输入新密码" dependencies={["new_password"]} rules={[{ required: true }, ({ getFieldValue }) => ({ validator(_, value) { return value === getFieldValue("new_password") ? Promise.resolve() : Promise.reject(new Error("两次输入的密码不一致")); } })]}><Input.Password autoComplete="new-password" maxLength={128} /></Form.Item>
        <Space><Button type="primary" htmlType="submit" loading={busy}>修改密码</Button>{!me.must_change_password && <Button onClick={() => router.push("/")}>返回工作台</Button>}</Space>
      </Form>
    </Card>
  </>;
}
