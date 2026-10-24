"use client";
import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Card, Form, InputNumber, Select, Space, Switch } from "antd";
import { useSettingsDraft } from "./SettingsState";
import { api, json } from "@/lib/api";

type Policy = { auto_admission_enabled: boolean; corporate_email_auto: boolean; admission_valid_days: number; version: string; chain_action: string; institution_action: string; cafe_action: string; pub_action: string; brand_action: string; chain_names: string[]; institution_words: string[]; google_mode: string; stale_days: number };
const actions = [{ value: "keep", label: "保留，继续研究" }, { value: "review", label: "标记待复核，继续研究" }, { value: "exclude", label: "排除，跳过联系方式查找" }];
export default function LeadPolicySettings({ section = "screen" }: { section?: "screen" | "data" }) {
  const [dirty, setDirty] = useState(false);
  useSettingsDraft("policy", dirty);
  const [form] = Form.useForm<Policy>();
  const [saved, setSaved] = useState<Policy>();
  const [busy, setBusy] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string>();
  const load = useCallback(async () => { try { const value = await api<Policy>("/api/lead-policy"); setSaved(value); form.setFieldsValue(value); setDirty(false); setError(undefined); } catch (e) { setError((e as Error).message); } }, [form]);
  useEffect(() => { void load(); }, [load]);
  return <Card title={section === "screen" ? "客户筛选与准入" : "数据补充"} style={{ marginBottom: 24 }}>
    {success && <Alert type="success" showIcon message="策略已保存，新任务生效" style={{ marginBottom: 16 }} />}
    {error && <Alert type="error" showIcon message={error} action={<Button onClick={() => { if (!dirty || window.confirm("刷新会放弃未保存的策略，是否继续？")) void load(); }}>刷新策略</Button>} />}
    <Alert type="info" showIcon message="筛选与数据补充共用一份策略，保存时会一并保存两处修改。新任务使用保存时的策略快照；已有名单可点击「重新预筛」。人工确认结果保留。待复核仍会查找联系方式，不等于排除。" style={{ marginBottom: 16 }} />
    <Form onValuesChange={() => setDirty(true)} form={form} layout="vertical" disabled={!saved || busy} onFinish={async (values) => { setBusy(true); setSuccess(false); try { const result = await api<Policy>("/api/lead-policy", json({ ...saved, ...values, version: saved?.version }, "PUT")); setSaved(result); form.setFieldsValue(result); setError(undefined); setSuccess(true); setDirty(false); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }}>
      <div hidden={section !== "screen"}><Space align="start" wrap>
        {[["chain_action", "名称命中连锁清单"], ["institution_action", "名称含机构词"], ["cafe_action", "咖啡馆／面包店／Deli"], ["pub_action", "Pub／酒吧"], ["brand_action", "Overture 品牌信息"]].map(([key, label]) => <Form.Item key={key} name={key} label={label}><Select style={{ width: 230 }} options={key === "brand_action" ? actions.slice(0, 2) : actions} /></Form.Item>)}
      </Space>
      <Form.Item name="chain_names" label="连锁名称（输入后回车添加；按完整词组匹配）"><Select mode="tags" tokenSeparators={[",", "，"]} /></Form.Item>
      <Form.Item name="institution_words" label="机构关键词（仅作为线索，可能是门店名称）"><Select mode="tags" tokenSeparators={[",", "，"]} /></Form.Item>
      </div><div hidden={section !== "data"}><Space align="start" wrap>
        <Form.Item name="google_mode" label="当前官网查询策略"><Select style={{ width: 260 }} options={[{ value: "off", label: "关闭" }, { value: "needed", label: "Google 优先：首次、过期或异常时查询" }, { value: "all", label: "本次名单全部查询" }]} /></Form.Item>
        <Form.Item name="stale_days" label="来源数据复用天数" rules={[{ required: true }]}><InputNumber min={1} max={365} /></Form.Item>
      </Space>
      <Alert type="info" message="同步阶段先保存 Overture 和 Google 官网候选；AI 核验与完善可稍后对整批或所选门店执行。近期结果复用，失败保留旧成果，人工官网不覆盖。关闭 Google 仍可核验已有官网。Google 项目级每分钟与每日调用保护仍生效。" style={{ marginBottom: 16 }} />
      </div><div hidden={section !== "screen"}><Space align="start" wrap><Form.Item name="auto_admission_enabled" label="AI 自动准入" valuePropName="checked"><Switch /></Form.Item><Form.Item name="corporate_email_auto" label="英国公司通用业务邮箱自动准入" valuePropName="checked"><Switch /></Form.Item><Form.Item name="admission_valid_days" label="自动准入复核天数"><InputNumber min={1} max={90} /></Form.Item></Space>
      <Alert type="info" message="AI 核实公司运营主体与联系方式，规则引擎决定是否允许；电话缺 TPS／CTPS、个人邮箱缺适用依据及平台缺会话授权时列出缺项，不推测放行。人工审核结果保留，自动允许仍需文案审批、发送身份与退出说明，发送前再次复查。" style={{ marginBottom: 16 }} />
      </div><Button type="primary" htmlType="submit" loading={busy}>保存策略</Button>
    </Form>
  </Card>;
}
