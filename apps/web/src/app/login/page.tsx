"use client";
import { Button, Card, Form, Input, Typography, message } from "antd";
import { useRouter } from "next/navigation";
import { api, json } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  return (
    <div style={{ display: "grid", placeItems: "center", minHeight: "100vh", padding: 16 }}>
      <Card title="Beacon 工作台登录" style={{ width: 360 }}>
        <Form
          layout="vertical"
          onFinish={(v) =>
            api("/api/auth/login", json(v))
              .then(() => router.replace("/"))
              .catch((e) => message.error(e.message))
          }
        >
          <Form.Item name="username" label="操作者" rules={[{ required: true }]}>
            <Input autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" label="口令" rules={[{ required: true }]}>
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>
            登录
          </Button>
        </Form>
        <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>
          系统不发送任何消息；所有对外联系由人执行后回填。
        </Typography.Paragraph>
      </Card>
    </div>
  );
}
