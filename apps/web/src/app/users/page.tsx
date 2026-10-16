"use client";
import { Alert, Button, Card, Form, Input, Modal, Popconfirm, Select, Space, Table, Tag } from "antd";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, json } from "@/lib/api";
import { Operator, ROLE_LABELS, useOperator } from "@/lib/auth";
import { HeroBand } from "@/components/ui";
type User = Operator & { is_active: boolean; created_at: string };
const roles = Object.entries(ROLE_LABELS).map(([value, label]) => ({ value, label }));

export default function UsersPage() {
  const { me, refresh } = useOperator();
  const router = useRouter();
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState<string>();
  const [success, setSuccess] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<"create" | "edit" | "reset" | null>(null);
  const [target, setTarget] = useState<User | null>(null);
  const [form] = Form.useForm();
  const load = useCallback(async () => { try { setUsers(await api<User[]>("/api/users")); } catch (e) { setError((e as Error).message); } }, []);
  useEffect(() => { if (me?.role === "admin") void load(); }, [load, me?.role]);
  useEffect(() => { if (mode) { form.resetFields(); if (target) form.setFieldsValue({ display_name: target.display_name, role: target.role }); } }, [mode, target, form]);
  if (me?.role !== "admin") return null;
  const act = async (work: () => Promise<void>) => { setBusy(true); setError(undefined); setSuccess(undefined); try { await work(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } };
  const selfChanged = (id: string) => { if (id === me.id) { setMode(null); router.replace("/login"); return true; } return false; };
  return <>
    <HeroBand kicker="USERS" title="用户管理" subtitle="管理员、业务成员和只读成员共享同一工作空间。" extra={<Button type="primary" disabled={busy} onClick={() => { setTarget(null); setMode("create"); }}>新增用户</Button>} />
    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}
    {success && <Alert type="success" showIcon message={success} style={{ marginBottom: 16 }} />}
    <Alert type="info" showIcon message="初始／临时密码须由你安全交给用户，首次登录强制修改。停用、重置密码或调整角色会使该用户旧会话失效；至少保留一位有效管理员。" style={{ marginBottom: 16 }} />
    <Card extra={<Button onClick={() => void load()} disabled={busy}>刷新用户</Button>}>
      <Table<User> rowKey="id" dataSource={users} scroll={{ x: 850 }} columns={[
        { title: "登录名", dataIndex: "username", render: (v, u) => <>{v}{u.id === me.id && <Tag style={{ marginLeft: 8 }}>当前账号</Tag>}</> },
        { title: "显示名称", dataIndex: "display_name", render: (v) => v || "—" },
        { title: "角色", dataIndex: "role", render: (v: keyof typeof ROLE_LABELS) => ROLE_LABELS[v] },
        { title: "状态", render: (_, u) => <><Tag color={u.is_active ? "green" : "default"}>{u.is_active ? "正常" : "已停用"}</Tag>{u.must_change_password && <Tag color="gold">待修改初始密码</Tag>}</> },
        { title: "操作", render: (_, u) => <Space wrap>
          <Button size="small" disabled={busy} onClick={() => { setTarget(u); setMode("edit"); }}>编辑</Button>
          <Button size="small" disabled={busy} onClick={() => { setTarget(u); setMode("reset"); }}>重置密码</Button>
          <Popconfirm title={u.is_active ? "停用后该用户将无法登录，现有会话失效，确认停用？" : "确认恢复该用户？"} onConfirm={() => act(async () => { await api(`/api/users/${u.id}`, json({ is_active: !u.is_active }, "PATCH")); if (selfChanged(u.id)) return; await load(); setSuccess(u.is_active ? "用户已停用" : "用户已恢复，需重新登录"); })}><Button size="small" danger={u.is_active} disabled={busy}>{u.is_active ? "停用" : "恢复"}</Button></Popconfirm>
        </Space> },
      ]} />
    </Card>
    <Modal title={mode === "create" ? "新增用户" : mode === "reset" ? `重置密码 · ${target?.username}` : `编辑用户 · ${target?.username}`} open={!!mode} onCancel={() => { if (!busy) { setMode(null); form.resetFields(); } }} footer={null} destroyOnHidden>
      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
      <Form form={form} layout="vertical" disabled={busy} initialValues={{ role: "member" }} onFinish={(v) => act(async () => {
        if (mode === "create") { await api("/api/users", json({ username: v.username, display_name: v.display_name, role: v.role, initial_password: v.initial_password })); setSuccess("用户已创建；请交付初始密码，首次登录需修改"); }
        else if (mode === "reset" && target) { await api(`/api/users/${target.id}/reset-password`, json({ temporary_password: v.temporary_password })); if (selfChanged(target.id)) return; setSuccess("密码已重置，旧会话已失效；请交付临时密码"); }
        else if (target) { await api(`/api/users/${target.id}`, json({ display_name: v.display_name, role: v.role }, "PATCH")); if (target.id === me.id && v.role !== target.role) { selfChanged(target.id); return; } if (target.id === me.id) await refresh(); setSuccess("用户资料已保存"); }
        setMode(null); form.resetFields(); await load();
      })}>
        {mode === "create" && <Form.Item name="username" label="登录名" rules={[{ required: true }, { pattern: /^[a-z0-9][a-z0-9_.-]{2,63}$/, message: "3～64 位小写字母、数字、下划线、点或连字符" }]}><Input autoComplete="off" maxLength={64} /></Form.Item>}
        {mode !== "reset" && <><Form.Item name="display_name" label="显示名称" rules={[{ max: 80 }]}><Input maxLength={80} /></Form.Item><Form.Item name="role" label="角色" rules={[{ required: true }]}><Select options={roles} /></Form.Item></>}
        {mode !== "edit" && <Form.Item name={mode === "reset" ? "temporary_password" : "initial_password"} label={mode === "reset" ? "临时密码" : "初始密码"} rules={[{ required: true }, { min: 12, max: 128, message: "密码需为 12～128 个字符" }]}><Input.Password autoComplete="new-password" maxLength={128} /></Form.Item>}
        <Button type="primary" htmlType="submit" loading={busy}>{mode === "create" ? "创建用户" : mode === "reset" ? "重置密码并撤销旧会话" : "保存修改"}</Button>
      </Form>
    </Modal>
  </>;
}
