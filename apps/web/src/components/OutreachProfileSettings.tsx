"use client";
import { Alert, Card, Form, Input } from "antd";
import Button from "@/components/AccessButton";
import { useEffect, useState } from "react";
import { api, json } from "@/lib/api";
import { useOperator } from "@/lib/auth";

type Profile = { version: string; company: string; services: string; proof: string; constraints: string };
export default function OutreachProfileSettings() {
  const { me } = useOperator();
  const [form] = Form.useForm();
  const [profile, setProfile] = useState<Profile>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const load = () => api<Profile>("/api/outreach-profile").then((p) => { setProfile(p); form.setFieldsValue(p); setError(undefined); }).catch((e) => setError(e.message));
  useEffect(() => { void load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return <Card title="我们的服务 · AI 触达资料" style={{ marginBottom: 16 }} extra={<Button readOnlySafe onClick={() => void load()}>重新加载</Button>}>
    <p>AI 将这些资料与门店、菜单信息结合起草消息。仅填写真实提供的服务；没有案例、价格或交付承诺可以留空。修改后旧 AI 消息需要重新生成并确认。</p>
    {saved && <Alert type="success" showIcon message="服务资料已保存" style={{ marginBottom: 12 }} />}
    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
    <Form form={form} layout="vertical" disabled={busy || me?.role !== "admin" || !profile} onFinish={async (v) => { setBusy(true); setError(undefined); setSaved(false); try { const p = await api<Profile>("/api/outreach-profile", json({ ...v, version: profile?.version }, "PUT")); setProfile(p); setSaved(true); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }}>
      <Form.Item name="company" label="公司／品牌介绍" rules={[{ required: true, whitespace: true }]}><Input maxLength={300} placeholder="真实公司或品牌名称、简要定位" /></Form.Item>
      <Form.Item name="services" label="菜单设计与印刷服务" rules={[{ required: true, whitespace: true }]}><Input.TextArea rows={3} maxLength={4000} placeholder="具体能提供什么、适合哪些需求、希望客户采取的下一步" /></Form.Item>
      <Form.Item name="proof" label="可验证案例与优势（可选）"><Input.TextArea rows={2} maxLength={4000} placeholder="只填真实可用的案例、作品链接或有依据的优势" /></Form.Item>
      <Form.Item name="constraints" label="服务范围与承诺限制（可选）"><Input.TextArea rows={2} maxLength={2000} placeholder="服务地区、语言、交付限制，以及不能承诺的事项" /></Form.Item>
      {me?.role === "admin" && <Button htmlType="submit" type="primary" loading={busy} disabled={!profile}>保存服务资料</Button>}
    </Form>
  </Card>;
}
