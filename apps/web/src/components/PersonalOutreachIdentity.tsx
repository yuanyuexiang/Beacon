"use client";
import { Alert, Card, Form, Input, Space } from "antd";
import Button from "./AccessButton";
import { useEffect, useState } from "react";
import { api, json } from "@/lib/api";
import { useOperator } from "@/lib/auth";
import { useSettingsDraft } from "./SettingsState";
type Identity = { version: string; name: string; role: string; sender_identity: string; configuration_error?: string };
export default function PersonalOutreachIdentity() {
  const { me } = useOperator();
  const [form] = Form.useForm<Identity>();
  const [own, setOwn] = useState<Identity>();
  const [dirty, setDirty] = useState(false);
  useSettingsDraft("personal-identity", dirty);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [saved, setSaved] = useState(false);
  const load = () => api<Identity>("/api/outreach-identity").then(p => { setOwn(p); form.setFieldsValue(p); setDirty(false); setError(undefined); }).catch(e => setError(e.message));
  useEffect(() => { void load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return <Card title="我的英文署名" style={{ marginBottom: 16 }} extra={<Button readOnlySafe disabled={busy} onClick={() => { if (!dirty || window.confirm("重新加载将放弃未保存的个人署名，是否继续？")) void load(); }}>重新加载署名</Button>}>
    <p>只影响你新起草的消息。留空沿用公司默认姓名／职务，品牌与官网共用公司设置。</p>
    {own?.configuration_error && <Alert type="warning" message={own.configuration_error} />}{error && <Alert type="error" message={error} />}{saved && <Alert type="success" message="个人署名已保存" />}
    <Form form={form} layout="vertical" onValuesChange={() => { setDirty(true); setSaved(false); }} disabled={!own || busy || me?.role === "viewer"} onFinish={async v => {
      setBusy(true); setError(undefined);
      try { const next = await api<Identity>("/api/outreach-identity", json({ ...v, version: own?.version }, "PUT")); setOwn(next); setDirty(false); setSaved(true); }
      catch (e) { setError((e as Error).message); } finally { setBusy(false); }
    }}><Space wrap><Form.Item name="name" label="我的英文姓名"><Input maxLength={100} /></Form.Item><Form.Item name="role" label="我的英文职务（可选）"><Input maxLength={100} /></Form.Item></Space><p style={{ whiteSpace: "pre-wrap" }}>{own?.sender_identity || "尚未设置署名"}</p><Button htmlType="submit" loading={busy}>保存我的署名</Button></Form>
  </Card>;
}
