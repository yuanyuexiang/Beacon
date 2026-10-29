"use client";
import { Alert, Button, Collapse, Input, Modal, Radio, Select, Space, Table } from "antd";
import { useState } from "react";
import { api, json } from "@/lib/api";
import { useOperator } from "@/lib/auth";

type Member = { username: string; display_name: string | null; leads: number; open_tasks: number; drafts?: number; followups_due?: number; last_communication_at?: string | null };
type Preview = { count: number; owners: Record<string, number>; expected: Record<string, string | null>; names?: Record<string, string> };
type Result = { lead_id: string; assigned_to?: string | null; changed?: boolean; error?: string };

export default function LeadAssignment({ leadIds, filteredLeadIds, onChanged }: { leadIds: string[]; filteredLeadIds?: string[]; onChanged: () => void }) {
  const { me } = useOperator();
  const [open, setOpen] = useState(false);
  const [members, setMembers] = useState<Member[]>([]);
  const [preview, setPreview] = useState<Preview>();
  const [target, setTarget] = useState<string>();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<Result[]>();
  const [scope, setScope] = useState<"selected" | "filtered">();
  const [choices, setChoices] = useState<{ selected: string[]; filtered?: string[] }>({ selected: [] });
  const previewScope = async (ids: string[]) => { setBusy(true); setError(undefined); setPreview(undefined); try { setPreview(await api<Preview>("/api/assignment/preview", json({ lead_ids: ids }))); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  const openPreview = async () => { const selected = [...new Set(leadIds)]; setChoices({ selected, filtered: filteredLeadIds ? [...new Set(filteredLeadIds)] : undefined }); setScope(selected.length ? "selected" : undefined); setOpen(true); setBusy(true); setError(undefined); setMembers([]); setPreview(undefined); setResults(undefined); setTarget(undefined); setReason(""); try { const [m, p] = await Promise.all([api<Member[]>("/api/assignment/members"), selected.length ? api<Preview>("/api/assignment/preview", json({ lead_ids: selected })) : Promise.resolve(undefined)]); setMembers(m); setPreview(p); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  if (me?.role !== "admin" && me?.role !== "director") return null;
  return <>
    <Button disabled={!leadIds.length && !filteredLeadIds?.length} onClick={openPreview}>分配门店</Button>
    <Modal width={780} title="分配／转交门店" open={open} onCancel={() => { if (!busy) setOpen(false); }} confirmLoading={busy} okText="确认分配" cancelText="关闭" okButtonProps={{ disabled: !preview?.count || !target || !reason.trim() || !!results }} onOk={async () => { if (!preview || !target) return; setBusy(true); setError(undefined); try { const r = await api<{ items: Result[] }>("/api/assignment/apply", json({ expected: preview.expected, assigned_to: target === "__unassigned" ? null : target, reason: reason.trim() })); setResults(r.items); onChanged(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }}>
      {error && <Alert type="error" showIcon message={error} />}
      {choices.filtered && <><p>分配范围（必须明确选择）</p><Radio.Group aria-label="分配范围" value={scope} disabled={busy || !!results} onChange={(e) => { const value = e.target.value as "selected" | "filtered"; setScope(value); void previewScope(choices[value] || []); }} options={[{ value: "selected", label: `所选门店 ${choices.selected.length} 家`, disabled: !choices.selected.length }, { value: "filtered", label: `当前筛选全部 ${choices.filtered.length} 家（包含其他分页）`, disabled: !choices.filtered.length }]} />{!scope && <Alert style={{ marginTop: 12 }} type="info" message="尚未选择分配范围。可先勾选门店，或在这里明确选择当前筛选全部门店。" />}</>}
      {preview && <p>本次 {preview.count} 家 · {Object.entries(preview.owners).map(([name, count]) => `${name} ${count} 家`).join("；")}</p>}
      <Alert type="info" showIcon message="交接保留历史，待发任务暂停，须由新负责人复核后恢复；不会发送消息。发送中或结果未知的门店先对账再交接。" />
      <Collapse style={{ marginTop: 12 }} items={[{ key: "team", label: "查看团队工作量", children: <Table size="small" rowKey="username" pagination={{ pageSize: 5 }} dataSource={members} columns={[{ title: "成员", render: (_, r) => r.display_name || r.username }, { title: "门店", dataIndex: "leads" }, { title: "未完成任务", dataIndex: "open_tasks" }, { title: "草稿", dataIndex: "drafts" }, { title: "到期待跟进", dataIndex: "followups_due" }, { title: "最近沟通", render: (_, r) => r.last_communication_at ? new Date(r.last_communication_at).toLocaleString() : "暂无" }]} /> }]} />
      <Space direction="vertical" style={{ width: "100%", marginTop: 16 }}>
        <span>接收业务成员</span>
        {!members.length && !busy && <Alert type="info" message="暂无有效业务成员，请管理员或销售总监在用户管理中添加或启用业务成员。管理员和销售总监不作为接收业务成员。" />}
        <Select aria-label="门店接收人" placeholder="选择业务成员或收回为未分配" value={target} disabled={busy || !!results} style={{ width: "100%" }} options={[{ value: "__unassigned", label: "收回为未分配" }, ...members.map((m) => ({ value: m.username, label: `${m.display_name ? `${m.display_name}（${m.username}）` : m.username} · ${m.leads} 家门店 · ${m.open_tasks} 项未完成任务` }))]} onChange={setTarget} />
        <Input.TextArea aria-label="分配原因" placeholder="分配或转交原因（必填）" value={reason} maxLength={1000} disabled={busy || !!results} onChange={(e) => setReason(e.target.value)} />
      </Space>
      {results && <><Alert style={{ marginTop: 16 }} type={results.some((r) => r.error) ? "warning" : "success"} message={`成功 ${results.filter((r) => !r.error).length} 家，失败 ${results.filter((r) => r.error).length} 家；失败项重新预览后再操作`} /><Table size="small" rowKey="lead_id" pagination={{ pageSize: 5 }} dataSource={results} columns={[{ title: "门店", render: (_, r) => preview?.names?.[r.lead_id] || r.lead_id }, { title: "结果", render: (_, r) => r.error || (r.changed ? "已分配" : "负责人未变") }]} /></>}
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

export type AssignmentReturn = { returned_by: string; returned_at: string; category: string; reason: string };

export function ReturnAssignment({ leadId, onReturned }: { leadId: string; onReturned: () => void }) {
  const [open, setOpen] = useState(false);
  const [category, setCategory] = useState<string>();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  return <><Button size="small" onClick={() => { setOpen(true); setError(undefined); }}>退回门店</Button><Modal title="退回门店" open={open} okText="确认退回" cancelText="取消" confirmLoading={busy} okButtonProps={{ disabled: busy || !category || !reason.trim() }} onCancel={() => { if (!busy) setOpen(false); }} onOk={async () => {
    if (busy || !category || !reason.trim()) return;
    setBusy(true); setError(undefined);
    try { await api(`/api/leads/${leadId}/return-assignment`, json({ category, reason: reason.trim() })); setOpen(false); onReturned(); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }}><p>退回后由销售总监重新分配。资料和沟通记录会保留，未发送任务将暂停，门店会移出你的名单。</p>{error && <Alert type="error" showIcon message={error} />}<Space direction="vertical" style={{ width: "100%" }}><Select aria-label="退回原因" placeholder="选择退回原因" value={category} disabled={busy} style={{ width: "100%" }} onChange={setCategory} options={["业务不匹配", "联系困难", "区域不合适", "重复线索", "其他"].map(value => ({ value, label: value }))} /><Input.TextArea aria-label="退回说明" placeholder="说明具体情况，方便重新分配（必填）" value={reason} disabled={busy} maxLength={1000} rows={4} onChange={e => setReason(e.target.value)} /></Space></Modal></>;
}
