"use client";
import { Alert, Card, Collapse, Form, Input, Select, Space, Tag, Typography } from "antd";
import Button from "@/components/AccessButton";
import { useEffect, useRef, useState } from "react";
import { api, json } from "@/lib/api";
import { useSettingsDraft } from "./SettingsState";
import PersonalOutreachIdentity from "./PersonalOutreachIdentity";
import { useOperator } from "@/lib/auth";

type Profile = { version: string; company: string; services: string; proof: string; constraints: string; english_brand: string; english_summary: string; sender_name: string; sender_role: string; website: string; tone: string; opt_out_text: string };
type Suggestion = { english_summary: string; missing: string[] };
type Preview = { subject: string; body: string; translation_zh: string; rationale: string; missing: string[] };
export default function OutreachProfileSettings() {
  const { me } = useOperator();
  const [form] = Form.useForm<Profile>();
  const [profile, setProfile] = useState<Profile>();
  const [dirty, setDirty] = useState(false);
  useSettingsDraft("profile", dirty);
  const [error, setError] = useState<string>();
  const [saved, setSaved] = useState<string>();
  const [busy, setBusy] = useState<string>();
  const [suggestion, setSuggestion] = useState<Suggestion>();
  const [preview, setPreview] = useState<Preview>();
  const revision = useRef(0);
  const changed = () => { revision.current++; setDirty(true); setSaved(undefined); setSuggestion(undefined); setPreview(undefined); };
  const load = async () => {
    setBusy("load"); setError(undefined);
    try {
      const p = await api<Profile>("/api/outreach-profile");
      revision.current++; setProfile(p); form.setFieldsValue(p);
      setDirty(false); setSuggestion(undefined); setPreview(undefined);
    } catch (e) { setError((e as Error).message); } finally { setBusy(undefined); }
  };
  useEffect(() => { void load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const runAI = async (action: "organise" | "preview") => {
    const at = revision.current;
    setBusy(action); setError(undefined);
    try {
      const values = await form.validateFields();
      const result = await api<Suggestion & Preview>(`/api/outreach-profile/${action}`, json({ ...values, version: profile?.version }));
      if (at !== revision.current) { setError("资料已修改，请根据最新资料重新生成。"); return; }
      if (action === "organise") setSuggestion(result); else setPreview(result);
    } catch (e) { setError((e as Error).message || "请补全必填资料"); } finally { setBusy(undefined); }
  };
  return <>
    <Card title="我们的服务 · AI 触达资料" style={{ marginBottom: 16 }} extra={<Button readOnlySafe loading={busy === "load"} disabled={!!busy} onClick={() => { if (!dirty || window.confirm("重新加载会放弃未保存的资料，是否继续？")) void load(); }}>重新加载</Button>}>
      <p>内部资料可用中文填写，客户收到的消息统一使用英式英语。AI 只根据真实服务及门店证据起草，生成后仍需核对确认。</p>
      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
      {saved && <Alert type="success" showIcon message={saved} style={{ marginBottom: 12 }} />}
      <Form form={form} layout="vertical" onValuesChange={changed} disabled={busy === "save" || busy === "load" || me?.role !== "admin" || !profile} onFinish={async v => {
        setBusy("save"); setError(undefined);
        try { const p = await api<Profile>("/api/outreach-profile", json({ ...v, version: profile?.version }, "PUT")); setProfile(p); setDirty(false); setSaved("服务资料已保存"); }
        catch (e) { setError((e as Error).message); } finally { setBusy(undefined); }
      }}>
        <Typography.Title level={5}>1. 服务事实 · 可用中文填写</Typography.Title>
        <Form.Item name="company" label="公司／品牌介绍" rules={[{ required: true, whitespace: true }]}><Input maxLength={300} placeholder="填写真实公司名称及业务定位" /></Form.Item>
        <Form.Item name="services" label="菜单设计与印刷服务" rules={[{ required: true, whitespace: true }]} extra="例如：菜单排版、印刷文件制作。印刷、配送等仅填写实际可提供的内容。"><Input.TextArea rows={3} maxLength={4000} /></Form.Item>
        <Form.Item name="proof" label="可验证案例与优势（可选）"><Input.TextArea rows={2} maxLength={4000} placeholder="真实作品链接、案例与有依据的优势；没有可以留空" /></Form.Item>
        <Form.Item name="constraints" label="服务范围与承诺限制（可选）"><Input.TextArea rows={2} maxLength={2000} placeholder="例如：报价和交期需确认需求后提供；请按真实情况填写" /></Form.Item>
        <Typography.Title level={5}>2. 对外资料 · 使用英文</Typography.Title>
        <Form.Item name="english_brand" label="英文品牌名称" rules={[{ max: 80, message: "只填写简短品牌名，不要粘贴服务介绍" }, { pattern: /^(?!\s*(?:we (?:help|provide|offer|work)|our (?:services|company))\b)/i, message: "这里填写品牌名称，例如 Xiaodangjia；服务介绍请填到下方" }]} extra="填写你确认使用的名称，AI 不会擅自翻译公司名称。"><Input maxLength={80} placeholder="例如 Xiaodangjia，仅填写品牌名" /></Form.Item>
        <Form.Item name="english_summary" label="英文服务介绍（可选）" extra="可以自行填写，也可以让 AI 从上面的事实整理后核对采用。"><Input.TextArea rows={3} maxLength={3000} /></Form.Item>
        {me?.role === "admin" && <Button loading={busy === "organise"} disabled={!!busy} onClick={() => void runAI("organise")}>AI 整理英文介绍</Button>}
        {suggestion && <Alert style={{ marginTop: 12 }} type="info" message="待核对的英文介绍" description={<><p style={{ whiteSpace: "pre-wrap" }}>{suggestion.english_summary}</p>{suggestion.missing.map(x => <p key={x}>{x}</p>)}<Button onClick={() => { form.setFieldValue("english_summary", suggestion.english_summary); changed(); }}>采用英文介绍</Button></>} />}
        <Typography.Title level={5}>3. 默认署名与表达偏好</Typography.Title>
        <Space wrap align="start"><Form.Item name="sender_name" label="默认发件人英文姓名"><Input maxLength={100} placeholder="真实英文名或拼音" /></Form.Item><Form.Item name="sender_role" label="英文职务（可选）"><Input maxLength={100} /></Form.Item></Space>
        <Form.Item name="website" label="公司官网（可选）"><Input maxLength={500} placeholder="https://…" /></Form.Item>
        <p>客户消息语言：<Tag>English (UK)</Tag> AI 分析说明：中文</p>
        <Form.Item name="tone" label="表达风格" initialValue="professional"><Select options={[{ value: "professional", label: "专业简洁" }, { value: "warm", label: "自然友好" }]} /></Form.Item>
        <Form.Item name="opt_out_text" label="英文退出说明"><Input.TextArea rows={2} maxLength={1000} /></Form.Item>
        {me?.role === "admin" && <Space wrap><Button type="primary" htmlType="submit" loading={busy === "save"} disabled={!!busy}>保存服务资料</Button><Button loading={busy === "preview"} disabled={!!busy} onClick={() => void runAI("preview")}>预览英文示例</Button></Space>}
      </Form>
      <p style={{ marginTop: 12, color: "#777" }}>示例使用虚构门店 Example Restaurant，可预览未保存的资料；不会创建任务或发送邮件。真实门店起草时会使用其菜单与已核验信息。</p>
      {preview && <Card size="small" title="英文邮件示例 · 未发送" style={{ marginTop: 16 }}><Typography.Text strong>{preview.subject}</Typography.Text><p style={{ whiteSpace: "pre-wrap" }}>{preview.body}</p><Collapse items={[{ key: "zh", label: "中文对照与起草说明（仅内部查看）", children: <><p style={{ whiteSpace: "pre-wrap" }}>{preview.translation_zh || "本次未返回中文对照"}</p><p>署名与退出说明已附在英文预览末尾。</p><p>{preview.rationale}</p>{preview.missing.map(x => <p key={x}>{x}</p>)}</> }]} /></Card>}
    </Card>
    <PersonalOutreachIdentity />
  </>;
}
