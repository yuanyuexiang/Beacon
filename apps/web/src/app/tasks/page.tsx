"use client";
import { Button, Card, DatePicker, Form, Input, Select, Space, Table, Tag, Typography, message } from "antd";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, json } from "@/lib/api";
import { label } from "@/lib/format";

type Lead = { id: string; name: string; source_key: string };
type Elig = { id: string; channel: string; contact_ref: string | null; contact_usable: string; eligibility: string; rule_version: string | null; evidence: string | null; reviewed_by: string | null };
type Content = { id: string; kind: string; version: number; status: string; approval_valid: boolean };
type Task = { id: string; lead_id: string; channel: string; status: string; status_reason: string | null; opened_at: string | null; sent_at: string | null; sent_by: string | null; content_id: string };
type Event = { id: string; event_key: string; kind: string; channel: string | null; recorded_at: string; actions: { action: string }[] | null; duplicate?: boolean };
type Sup = { id: string; lead_id: string | null; scope: string; contact_ref: string | null; reason: string; created_at: string };

const CHANNELS = ["email", "whatsapp", "phone", "instagram", "contact_form", "post"];

export default function TasksPage() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [leadId, setLeadId] = useState<string>();
  const [eligs, setEligs] = useState<Elig[]>([]);
  const [content, setContent] = useState<Content[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [events, setEvents] = useState<Event[]>([]);
  const [sups, setSups] = useState<Sup[]>([]);
  const err = (e: Error) => message.error(e.message);

  const reload = useCallback(async (lid?: string) => {
    setTasks(await api<Task[]>("/api/tasks"));
    setSups(await api<Sup[]>("/api/suppressions"));
    if (lid) {
      setEligs(await api<Elig[]>(`/api/leads/${lid}/eligibility`));
      setContent((await api<Content[]>(`/api/leads/${lid}/content`)).filter((c) => c.approval_valid));
      setEvents(await api<Event[]>(`/api/leads/${lid}/events`));
    }
  }, []);
  useEffect(() => {
    api<Lead[]>("/api/leads?limit=500").then(setLeads).catch(err);
    reload().catch(err);
  }, [reload]);
  const pick = (lid: string) => { setLeadId(lid); reload(lid).catch(err); };
  const name = (lid: string) => leads.find((l) => l.id === lid)?.name ?? lid;

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Card size="small" title="选择线索">
        <Select showSearch style={{ width: 400 }} placeholder="门店" optionFilterProp="label" value={leadId} onChange={pick}
          options={leads.map((l) => ({ value: l.id, label: `${l.name}（${l.source_key}）` }))} />
        {leadId && <Link href={`/leads/${leadId}`} style={{ marginLeft: 12 }}>查看详情</Link>}
      </Card>

      {leadId && (
        <Card size="small" title="渠道准入（allowed 必须有证据与规则版本；unknown 不放行）">
          <Form layout="inline" onFinish={(v) => api(`/api/leads/${leadId}/eligibility`, json(v)).then(() => reload(leadId)).catch(err)} style={{ marginBottom: 12 }}>
            <Form.Item name="channel" rules={[{ required: true }]}><Select placeholder="渠道" style={{ width: 130 }} options={CHANNELS.map((c) => ({ value: c }))} /></Form.Item>
            <Form.Item name="contact_ref"><Input placeholder="联系值（规范化）" style={{ width: 200 }} /></Form.Item>
            <Form.Item name="contact_source"><Input placeholder="来源" style={{ width: 140 }} /></Form.Item>
            <Form.Item name="contact_usable" initialValue="unknown"><Select style={{ width: 100 }} options={["unknown", "valid", "invalid"].map((c) => ({ value: c, label: label(c) }))} /></Form.Item>
            <Form.Item name="eligibility" initialValue="unknown"><Select style={{ width: 100 }} options={["unknown", "allowed", "blocked"].map((c) => ({ value: c, label: label(c) }))} /></Form.Item>
            <Form.Item name="rule_version"><Input placeholder="规则版本" style={{ width: 140 }} /></Form.Item>
            <Form.Item name="evidence"><Input placeholder="证据（授权/筛查记录）" style={{ width: 260 }} /></Form.Item>
            <Button htmlType="submit">保存</Button>
          </Form>
          <Table<Elig> rowKey="id" size="small" pagination={false} dataSource={eligs} columns={[
            { title: "渠道", dataIndex: "channel" }, { title: "联系值", dataIndex: "contact_ref" },
            { title: "可用", dataIndex: "contact_usable", render: label },
            { title: "准入", dataIndex: "eligibility", render: (v) => <Tag color={v === "allowed" ? "green" : v === "blocked" ? "red" : "default"}>{label(v)}</Tag> },
            { title: "规则", dataIndex: "rule_version" }, { title: "证据", dataIndex: "evidence" }, { title: "审核人", dataIndex: "reviewed_by" },
            { title: "建任务", render: (_, e) => (
              <Select placeholder="选审批有效的内容" style={{ width: 220 }} disabled={e.eligibility !== "allowed"} onChange={(cid) => api(`/api/leads/${leadId}/tasks`, json({ eligibility_id: e.id, content_id: cid })).then(() => reload(leadId)).catch(err)}
                options={content.map((c) => ({ value: c.id, label: `${c.kind} v${c.version}` }))} />
            ) },
          ]} />
        </Card>
      )}

      <Card size="small" title="人工任务（系统不发送；销售执行后回填）">
        <Table<Task> rowKey="id" size="small" pagination={{ pageSize: 20 }} dataSource={leadId ? tasks.filter((t) => t.lead_id === leadId) : tasks} columns={[
          { title: "门店", dataIndex: "lead_id", render: (v) => <a onClick={() => pick(v)}>{name(v)}</a> },
          { title: "渠道", dataIndex: "channel" },
          { title: "状态", dataIndex: "status", render: (v, t) => <>{label(v)} {t.status_reason && <Typography.Text type="secondary">{t.status_reason}</Typography.Text>}</> },
          { title: "发送", render: (_, t) => t.sent_at ? `${t.sent_at} · ${t.sent_by}` : "-" },
          { title: "操作", render: (_, t) => (
            <Space>
              {t.status === "pending" && <Button size="small" onClick={() => api(`/api/tasks/${t.id}/open`, { method: "POST" }).then(() => reload(leadId)).catch(err)}>打开</Button>}
              {t.status === "opened" && <Form layout="inline" onFinish={(v) => api(`/api/tasks/${t.id}/sent`, json({ sent_at: v.sent_at.toISOString(), notes: v.notes })).then(() => reload(leadId)).catch(err)}>
                <Form.Item name="sent_at" rules={[{ required: true }]}><DatePicker showTime size="small" /></Form.Item>
                <Form.Item name="notes"><Input size="small" placeholder="备注" /></Form.Item>
                <Button size="small" htmlType="submit">记录已人工发送</Button>
              </Form>}
              {t.status === "paused" && <Button size="small" onClick={() => api(`/api/tasks/${t.id}/resume`, json({ reason: "负责人确认继续" })).then(() => reload(leadId)).catch(err)}>恢复</Button>}
              {!["sent_manual", "cancelled"].includes(t.status) && <Button size="small" danger onClick={() => api(`/api/tasks/${t.id}/cancel`, json({ reason: "人工取消" })).then(() => reload(leadId)).catch(err)}>取消</Button>}
            </Space>
          ) },
        ]} />
      </Card>

      {leadId && (
        <Card size="small" title="回复 / 拒收 / 退信回填（event_key 幂等）">
          <Form layout="inline" onFinish={(v) => api<Event>(`/api/leads/${leadId}/events`, json({ ...v, payload: { intent: v.intent, contact_ref: v.contact_ref, summary: v.summary } })).then((e) => { if (e.duplicate) message.warning("重复事件，未重复执行"); reload(leadId); }).catch(err)} style={{ marginBottom: 12 }}>
            <Form.Item name="event_key" rules={[{ required: true }]}><Input placeholder="事件键（如 mail:<id>）" style={{ width: 180 }} /></Form.Item>
            <Form.Item name="kind" rules={[{ required: true }]}><Select placeholder="类型" style={{ width: 120 }} options={["reply", "reject", "unsubscribe", "bounce", "note"].map((k) => ({ value: k }))} /></Form.Item>
            <Form.Item name="channel"><Select placeholder="渠道" style={{ width: 120 }} allowClear options={CHANNELS.map((c) => ({ value: c }))} /></Form.Item>
            <Form.Item name="intent"><Select placeholder="意向" style={{ width: 110 }} allowClear options={["positive", "quote", "later", "no", "unknown"].map((c) => ({ value: c }))} /></Form.Item>
            <Form.Item name="contact_ref"><Input placeholder="联系值" style={{ width: 160 }} /></Form.Item>
            <Form.Item name="summary"><Input placeholder="摘要（不存原文）" style={{ width: 200 }} /></Form.Item>
            <Button htmlType="submit">记录</Button>
          </Form>
          <Table<Event> rowKey="id" size="small" pagination={false} dataSource={events} columns={[
            { title: "键", dataIndex: "event_key" }, { title: "类型", dataIndex: "kind" }, { title: "渠道", dataIndex: "channel" },
            { title: "录入时间", dataIndex: "recorded_at" }, { title: "动作", dataIndex: "actions", render: (a: { action: string }[] | null) => (a ?? []).map((x) => x.action).join(", ") },
          ]} />
        </Card>
      )}

      <Card size="small" title={`抑制名单（${sups.length}）`}>
        <Table<Sup> rowKey="id" size="small" pagination={false} dataSource={sups} columns={[
          { title: "门店", dataIndex: "lead_id", render: (v) => (v ? name(v) : "-") }, { title: "范围", dataIndex: "scope" },
          { title: "联系值", dataIndex: "contact_ref" }, { title: "原因", dataIndex: "reason" }, { title: "时间", dataIndex: "created_at" },
        ]} />
      </Card>
    </Space>
  );
}
