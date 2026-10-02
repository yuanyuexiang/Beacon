"use client";
import { DashboardOutlined, LogoutOutlined, MenuFoldOutlined, MenuUnfoldOutlined, MessageOutlined, SafetyCertificateOutlined, SettingOutlined, ShopOutlined } from "@ant-design/icons";
import { Avatar, Breadcrumb, Dropdown, Layout, Menu, Space, Tooltip, Typography } from "antd";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const NAV_GROUPS = [
  {
    key: "work",
    label: "工作台",
    items: [
      { key: "/", label: "仪表盘", icon: <DashboardOutlined /> },
      { key: "/leads", label: "批次与线索", icon: <ShopOutlined /> },
      { key: "/tasks", label: "人工任务与回复", icon: <MessageOutlined /> },
    ],
  },
  { key: "system", label: "系统", items: [{ key: "/settings", label: "设置与说明", icon: <SettingOutlined /> }] },
];

const TITLES: Record<string, string> = { "/": "仪表盘", "/leads": "批次与线索", "/tasks": "人工任务与回复", "/settings": "设置与说明" };

export function AdminShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [me, setMe] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => {
    if (path === "/login") return;
    api<{ username: string }>("/api/auth/me").then((m) => setMe(m.username)).catch(() => router.replace("/login"));
  }, [path, router]);
  if (path === "/login") return <>{children}</>;
  const section = path.startsWith("/leads") ? "/leads" : path.startsWith("/tasks") ? "/tasks" : path.startsWith("/settings") ? "/settings" : "/";
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
          items={NAV_GROUPS.map((g) => ({ key: g.key, type: "group" as const, label: g.label, children: g.items.map((n) => ({ key: n.key, icon: n.icon, label: <Link href={n.key}>{n.label}</Link> })) }))} />
        <div className="beacon-sider-foot">
          {collapsed ? (
            <Tooltip placement="right" title="系统不发送任何消息，对外联系由人执行后回填"><SafetyCertificateOutlined /></Tooltip>
          ) : (
            <>
              <div className="beacon-sider-note">
                <SafetyCertificateOutlined />
                <div><b>只做人工触达</b>系统不发送任何消息，对外联系由人执行后回填。</div>
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
          <Dropdown menu={{ items: [{ key: "settings", label: <Link href="/settings">设置与说明</Link> }, { type: "divider" }, { key: "logout", icon: <LogoutOutlined />, label: "退出登录", onClick: () => api("/api/auth/logout", { method: "POST" }).then(() => router.replace("/login")) }] }}>
            <Space style={{ cursor: "pointer" }}>
              <Avatar size="small" style={{ background: "#cf010e" }}>{(me ?? "?").slice(0, 1).toUpperCase()}</Avatar>
              <Typography.Text>{me ?? "…"}</Typography.Text>
            </Space>
          </Dropdown>
        </Layout.Header>
        <Layout.Content style={{ padding: "20px 24px 40px", maxWidth: 1400, width: "100%", margin: "0 auto" }}>{children}</Layout.Content>
        <Layout.Footer style={{ textAlign: "center", color: "#9ca3af", fontSize: 12, padding: "12px 24px" }}>小当家 · 销售线索工作台（验证版）· 数据来源 FSA（OGL v3）、Overture Maps（CDLA-Permissive-2.0）· 评分不代表成交概率</Layout.Footer>
      </Layout>
    </Layout>
  );
}
