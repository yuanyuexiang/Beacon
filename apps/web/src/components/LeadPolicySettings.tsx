"use client";
import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Card, Form, InputNumber, Select, Space } from "antd";
import { api, json } from "@/lib/api";

type Policy = { version: string; chain_action: string; institution_action: string; cafe_action: string; pub_action: string; brand_action: string; chain_names: string[]; institution_words: string[]; google_mode: string; google_request_limit: number; stale_days: number };
const actions = [{ value: "keep", label: "保留，继续研究" }, { value: "review", label: "标记待复核，继续研究" }, { value: "exclude", label: "排除，跳过联系方式查找" }];
export default function LeadPolicySettings() {
  const [form] = Form.useForm<Policy>();
  const [saved, setSaved] = useState<Policy>();
  const [busy, setBusy] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string>();
  const load = useCallback(async () => { try { const value = await api<Policy>("/api/lead-policy"); setSaved(value); form.setFieldsValue(value); setError(undefined); } catch (e) { setError((e as Error).message); } }, [form]);
  useEffect(() => { void load(); }, [load]);
  return <Card title="客户筛选与数据补充策略" style={{ marginBottom: 24 }}>
    {success && <Alert type="success" showIcon message="策略已保存，新任务生效" style={{ marginBottom: 16 }} />}
    {error && <Alert type="error" showIcon message={error} action={<Button onClick={() => void load()}>刷新策略</Button>} />}
    <Alert type="info" showIcon message="新任务使用保存时的策略快照；已有名单可点击「重新预筛」。人工确认结果保留。待复核仍会查找联系方式，不等于排除。" style={{ marginBottom: 16 }} />
    <Form form={form} layout="vertical" disabled={!saved || busy} onFinish={async (values) => { setBusy(true); setSuccess(false); try { const result = await api<Policy>("/api/lead-policy", json({ ...values, version: saved?.version }, "PUT")); setSaved(result); form.setFieldsValue(result); setError(undefined); setSuccess(true); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }}>
      <Space align="start" wrap>
        {[["chain_action", "名称命中连锁清单"], ["institution_action", "名称含机构词"], ["cafe_action", "咖啡馆／面包店／Deli"], ["pub_action", "Pub／酒吧"], ["brand_action", "Overture 品牌信息"]].map(([key, label]) => <Form.Item key={key} name={key} label={label}><Select style={{ width: 230 }} options={key === "brand_action" ? actions.slice(0, 2) : actions} /></Form.Item>)}
      </Space>
      <Form.Item name="chain_names" label="连锁名称（输入后回车添加；按完整词组匹配）"><Select mode="tags" tokenSeparators={[",", "，"]} /></Form.Item>
      <Form.Item name="institution_words" label="机构关键词（仅作为线索，可能是门店名称）"><Select mode="tags" tokenSeparators={[",", "，"]} /></Form.Item>
      <Space align="start" wrap>
        <Form.Item name="google_mode" label="Overture 后的 Google Places 补充"><Select style={{ width: 260 }} options={[{ value: "off", label: "关闭" }, { value: "needed", label: "按需：缺少可靠官网时查询" }, { value: "all", label: "本次名单全部核验（受预算限制）" }]} /></Form.Item>
        <Form.Item name="google_request_limit" label="每个任务最多 API 尝试次数" rules={[{ required: true }]}><InputNumber min={1} max={200} /></Form.Item>
        <Form.Item name="stale_days" label="核验有效天数" rules={[{ required: true }]}><InputNumber min={1} max={365} /></Form.Item>
      </Space>
      <Alert type="info" message="先用 AI 核验已有官网并识别经营类型，已有可靠官网时按需模式不再查询 Google。关闭 Google 只关闭候选查询，不关闭已有官网识别。网络失败待重试、信息不足保留未知，有原文支持的身份冲突才交人工。供应餐食的咖啡馆／Pub 不仅因类型而自动排除。人工结果保留，Google 尝试计入预算，价格和照片不进入模型。" style={{ marginBottom: 16 }} />
      <Button type="primary" htmlType="submit" loading={busy}>保存策略</Button>
    </Form>
  </Card>;
}
