"use client";
import { Alert, Button, Collapse, Input, Modal, Select, Space, Table } from "antd";
import { useState } from "react";
import { api, json } from "@/lib/api";
import { useOperator } from "@/lib/auth";

type Member = { username: string; display_name: string | null; leads: number; open_tasks: number; drafts?: number; followups_due?: number; last_communication_at?: string | null };
type Preview = { count: number; owners: Record<string, number>; expected: Record<string, string | null> };
type Result = { lead_id: string; assigned_to?: string | null; changed?: boolean; error?: string };

export default function LeadAssignment({ leadIds, onChanged }: { leadIds: string[]; onChanged: () => void }) {
  const { me } = useOperator();
  const [open, setOpen] = useState(false);
  const [members, setMembers] = useState<Member[]>([]);
  const [preview, setPreview] = useState<Preview>();
  const [target, setTarget] = useState<string>();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<Result[]>();
  const openPreview = async () => { setOpen(true); setBusy(true); setError(undefined); setPreview(undefined); setResults(undefined); setTarget(undefined); setReason(""); try { const [m, p] = await Promise.all([api<Member[]>("/api/assignment/members"), api<Preview>("/api/assignment/preview", json({ lead_ids: leadIds }))]); setMembers(m); setPreview(p); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  if (me?.role !== "admin" && me?.role !== "director") return null;
  return <>
    <Button disabled={!leadIds.length} onClick={openPreview}>分配门店</Button>
    <Modal width={780} title="分配／转交门店" open={open} onCancel={() => { if (!busy) setOpen(false); }} confirmLoading={busy} okText="确认分配" cancelText="关闭" okButtonProps={{ disabled: !preview?.count || !target || !reason.trim() || !!results }} onOk={async () => { if (!preview || !target) return; setBusy(true); setError(undefined); try { const r = await api<{ items: Result[] }>("/api/assignment/apply", json({ expected: preview.expected, assigned_to: target === "__unassigned" ? null : target, reason: reason.trim() })); setResults(r.items); onChanged(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }}>
      {error && <Alert type="error" showIcon message={error} />}
      {preview && <p>本次 {preview.count} 家 · {Object.entries(preview.owners).map(([name, count]) => `${name} ${count} 家`).join("；")}</p>}
      <Alert type="info" showIcon message="交接保留历史，待发任务暂停，须由新负责人复核后恢复；不会发送消息。发送中或结果未知的门店先对账再交接。" />
      <Collapse style={{ marginTop: 12 }} items={[{ key: "team", label: "查看团队工作量", children: <Table size="small" rowKey="username" pagination={{ pageSize: 5 }} dataSource={members} columns={[{ title: "成员", render: (_, r) => r.display_name || r.username }, { title: "门店", dataIndex: "leads" }, { title: "未完成任务", dataIndex: "open_tasks" }, { title: "草稿", dataIndex: "drafts" }, { title: "到期待跟进", dataIndex: "followups_due" }, { title: "最近沟通", render: (_, r) => r.last_communication_at ? new Date(r.last_communication_at).toLocaleString() : "暂无" }]} /> }]} />
      <Space direction="vertical" style={{ width: "100%", marginTop: 16 }}>
        <Select aria-label="门店接收人" placeholder="选择业务成员或收回为未分配" value={target} disabled={busy || !!results} style={{ width: "100%" }} options={[{ value: "__unassigned", label: "收回为未分配" }, ...members.map((m) => ({ value: m.username, label: `${m.display_name || m.username} · ${m.leads} 家门店 · ${m.open_tasks} 项未完成任务` }))]} onChange={setTarget} />
        <Input.TextArea aria-label="分配原因" placeholder="分配或转交原因（必填）" value={reason} maxLength={1000} disabled={busy || !!results} onChange={(e) => setReason(e.target.value)} />
      </Space>
      {results && <><Alert style={{ marginTop: 16 }} type={results.some((r) => r.error) ? "warning" : "success"} message={`成功 ${results.filter((r) => !r.error).length} 家，失败 ${results.filter((r) => r.error).length} 家；失败项重新预览后再操作`} /><Table size="small" rowKey="lead_id" pagination={{ pageSize: 5 }} dataSource={results} columns={[{ title: "门店 ID", dataIndex: "lead_id" }, { title: "结果", render: (_, r) => r.error || (r.changed ? "已分配" : "负责人未变") }]} /></>}
    </Modal>
  </>;
}


export function AssignmentHistory({ leadId }: { leadId: string }) {
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<{ at: string; operator: string; before: { assigned_to?: string | null }; after: { assigned_to?: string | null; reason?: string } }[]>([]);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  return <><Button onClick={async () => { setOpen(true); setError(undefined); setBusy(true); try { setRows(await api(`/api/leads/${leadId}/assignment-history`)); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }}>分配记录</Button><Modal title="门店分配记录" open={open} footer={null} width={780} onCancel={() => setOpen(false)}>{error && <Alert type="error" message={error} />}<Table rowKey={(r) => `${r.at}-${r.operator}`} loading={busy} dataSource={rows} pagination={{ pageSize: 10 }} columns={[{ title: "时间", render: (_, r) => new Date(r.at).toLocaleString() }, { title: "操作人", dataIndex: "operator" }, { title: "原负责人", render: (_, r) => r.before?.assigned_to || "未分配" }, { title: "新负责人", render: (_, r) => r.after?.assigned_to || "未分配" }, { title: "原因", render: (_, r) => r.after?.reason }]} /></Modal></>;
}
