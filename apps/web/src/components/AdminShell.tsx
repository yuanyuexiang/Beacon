"use client";
import { DashboardOutlined, LogoutOutlined, MenuFoldOutlined, MenuUnfoldOutlined, MessageOutlined, SafetyCertificateOutlined, SettingOutlined, ShopOutlined } from "@ant-design/icons";
import { Alert, Avatar, Breadcrumb, Dropdown, Layout, Menu, Space, Tooltip, Typography } from "antd";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { AuthContext, Operator, ROLE_LABELS } from "@/lib/auth";
import { api } from "@/lib/api";

const NAV_GROUPS = [
  {
    key: "work",
    label: "工作台",
    items: [
      { key: "/", label: "仪表盘", icon: <DashboardOutlined /> },
      { key: "/directory", label: "门店池", icon: <ShopOutlined /> },
      { key: "/leads", label: "批次与线索", icon: <ShopOutlined /> },
      { key: "/tasks", label: "触达任务与回复", icon: <MessageOutlined /> },
    ],
  },
  { key: "system", label: "系统", items: [{ key: "/settings", label: "设置与说明", icon: <SettingOutlined /> }, { key: "/users", label: "用户管理", icon: <SafetyCertificateOutlined /> }] },
];

const TITLES: Record<string, string> = { "/": "仪表盘", "/leads": "批次与线索", "/directory": "门店池", "/tasks": "触达任务与回复", "/settings": "设置与说明", "/users": "用户管理", "/account": "个人账号" };

export function AdminShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [me, setMe] = useState<Operator | null>(null);
  const refresh = useCallback(async () => { const value = await api<Operator>("/api/auth/me"); setMe(value); }, []);
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => {
    if (path === "/login") { setMe(null); return; }
    if (["/terms", "/privacy"].includes(path)) return;
    refresh().catch(() => { setMe(null); router.replace("/login"); });
  }, [path, router, refresh]);
  useEffect(() => {
    const invalid = () => { setMe(null); router.replace("/login"); };
    const password = () => router.replace("/account");
    window.addEventListener("beacon-auth-invalid", invalid);
    window.addEventListener("beacon-password-required", password);
    return () => { window.removeEventListener("beacon-auth-invalid", invalid); window.removeEventListener("beacon-password-required", password); };
  }, [router]);
  useEffect(() => { if (me?.must_change_password && path !== "/account") router.replace("/account"); }, [me, path, router]);
  if (["/login", "/terms", "/privacy"].includes(path)) return <>{children}</>;
  const section = path.startsWith("/account") ? "/account" : path.startsWith("/users") ? "/users" : path.startsWith("/directory") ? "/directory" : path.startsWith("/leads") ? "/leads" : path.startsWith("/tasks") ? "/tasks" : path.startsWith("/settings") ? "/settings" : "/";
  const crumbs = [{ title: <Link href="/">首页</Link> }, { title: TITLES[section] }];
  if (path.startsWith("/leads/") && path !== "/leads") crumbs.push({ title: "线索详情" });
  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Layout.Sider className="beacon-sider" trigger={null} collapsible collapsed={collapsed} onCollapse={setCollapsed} breakpoint="lg" width={232} collapsedWidth={68} style={{ position: "sticky", top: 0, height: "100vh" }}>
        <Link href="/" className="beacon-brand">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/brand/logo.png" alt="小当家" />
          {!collapsed && (
            <div>
              <div className="beacon-brand-name">小当家</div>
              <div className="beacon-brand-sub">销售线索工作台</div>
            </div>
          )}
        </Link>
        <Menu className="beacon-nav" theme="dark" mode="inline" selectedKeys={[section]}
          items={NAV_GROUPS.filter((g) => g.key !== "system" || me?.role === "admin").map((g) => ({ key: g.key, type: "group" as const, label: g.label, children: g.items.filter((n) => !(me?.role === "member" && n.key === "/directory")).map((n) => ({ key: n.key, icon: n.icon, label: <Link href={n.key}>{n.label}</Link> })) }))} />
        <div className="beacon-sider-foot">
          {collapsed ? (
            <Tooltip placement="right" title="邮件与已连接社媒会话预览确认后发送，其余渠道人工触达"><SafetyCertificateOutlined /></Tooltip>
          ) : (
            <>
              <div className="beacon-sider-note">
                <SafetyCertificateOutlined />
                <div><b>触达需确认</b>邮件与已连接社媒会话预览确认后发送，其余渠道人工触达。</div>
              </div>
              <div className="beacon-sider-company">南京小当家文化咨询有限公司</div>
            </>
          )}
        </div>
      </Layout.Sider>
      <Layout>
        <Layout.Header className="beacon-header" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 24px", borderBottom: "1px solid #e8e3dc", borderTop: "3px solid #cf010e", position: "sticky", top: 0, zIndex: 10 }}>
          <div style={{ display: "flex", alignItems: "center" }}>
            <button type="button" className="beacon-fold" aria-label={collapsed ? "展开侧边栏" : "收起侧边栏"} onClick={() => setCollapsed(!collapsed)}>
              {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            </button>
            <Breadcrumb items={crumbs} />
          </div>
          <Dropdown menu={{ items: [{ key: "account", label: <Link href="/account">个人账号与密码</Link> }, ...(me?.role === "admin" ? [{ key: "settings", label: <Link href="/settings">设置与说明</Link> }, { key: "users", label: <Link href="/users">用户管理</Link> }] : []), { type: "divider" }, { key: "logout", icon: <LogoutOutlined />, label: "退出登录", onClick: () => api("/api/auth/logout", { method: "POST" }).then(() => router.replace("/login")) }] }}>
            <Space style={{ cursor: "pointer" }}>
              <Avatar size="small" style={{ background: "#cf010e" }}>{(me?.display_name || me?.username || "?").slice(0, 1).toUpperCase()}</Avatar>
              <Typography.Text>{me ? me.display_name || me.username : "…"}</Typography.Text>{me && <Typography.Text type="secondary">{ROLE_LABELS[me.role]}</Typography.Text>}
            </Space>
          </Dropdown>
        </Layout.Header>
        <Layout.Content style={{ padding: "20px 24px 40px", maxWidth: 1400, width: "100%", margin: "0 auto" }}><AuthContext.Provider value={{ me, refresh }}>
          {me?.role === "viewer" && path !== "/account" && <Alert type="info" showIcon message="当前为只读账号，可查看业务资料；不能修改、运行任务或发送消息。" style={{ marginBottom: 16 }} />}
          {!me ? <p>正在验证登录…</p> : me.must_change_password && path !== "/account" ? <p>请先修改初始密码…</p> : ["/settings", "/users"].includes(section) && me.role !== "admin" ? <Alert type="warning" showIcon message="此页面仅限管理员使用" /> : children}
        </AuthContext.Provider></Layout.Content>
        <Layout.Footer style={{ textAlign: "center", color: "#9ca3af", fontSize: 12, padding: "12px 24px" }}>小当家 · 销售线索工作台（验证版）· 数据来源 FSA（OGL v3）、Overture Maps（CDLA-Permissive-2.0）· 评分不代表成交概率</Layout.Footer>
      </Layout>
    </Layout>
  );
}
