"use client";
import { Button, Card, Form, Input, Typography, message } from "antd";
import { useRouter } from "next/navigation";
import { api, json } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", background: "linear-gradient(135deg,#0f172a 0%,#1e3a8a 100%)", padding: 16 }}>
      <Card style={{ width: 380, boxShadow: "0 20px 60px rgba(0,0,0,0.35)" }} styles={{ body: { padding: 32 } }}>
        <div style={{ marginBottom: 24 }}>
          <Typography.Title level={3} style={{ margin: 0 }}>Beacon</Typography.Title>
          <Typography.Text type="secondary">餐厅菜单线索工作台 · 操作者登录</Typography.Text>
        </div>
        <Form layout="vertical" size="large" onFinish={(v) => api("/api/auth/login", json(v)).then(() => router.replace("/")).catch((e) => message.error(e.message))}>
          <Form.Item name="username" label="操作者" rules={[{ required: true, message: "请输入操作者" }]}><Input autoComplete="username" placeholder="admin" /></Form.Item>
          <Form.Item name="password" label="口令" rules={[{ required: true, message: "请输入口令" }]}><Input.Password autoComplete="current-password" /></Form.Item>
          <Button type="primary" htmlType="submit" block>登录</Button>
        </Form>
        <Typography.Paragraph type="secondary" style={{ marginTop: 20, marginBottom: 0, fontSize: 12 }}>系统不发送任何消息；所有对外联系由人执行后回填。</Typography.Paragraph>
      </Card>
    </div>
  );
}
