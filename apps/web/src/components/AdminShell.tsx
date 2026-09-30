"use client";
import { DashboardOutlined, LogoutOutlined, SendOutlined, SettingOutlined, UnorderedListOutlined } from "@ant-design/icons";
import { Avatar, Breadcrumb, Dropdown, Layout, Menu, Space, Typography } from "antd";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const NAV = [
  { key: "/", label: "仪表盘", icon: <DashboardOutlined /> },
  { key: "/leads", label: "批次与线索", icon: <UnorderedListOutlined /> },
  { key: "/tasks", label: "人工任务与回复", icon: <SendOutlined /> },
  { key: "/settings", label: "设置与说明", icon: <SettingOutlined /> },
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
      <Layout.Sider collapsible collapsed={collapsed} onCollapse={setCollapsed} width={220} style={{ position: "sticky", top: 0, height: "100vh" }}>
        <div style={{ height: 64, display: "flex", alignItems: "center", justifyContent: collapsed ? "center" : "flex-start", padding: collapsed ? 0 : "0 16px", gap: 10, borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/brand/logo.png" alt="小当家" style={{ height: 34, width: "auto" }} />
          {!collapsed && (
            <div style={{ lineHeight: 1.2 }}>
              <div style={{ color: "#fab736", fontWeight: 700, fontSize: 14, letterSpacing: 1 }}>小当家</div>
              <div style={{ color: "rgba(255,255,255,0.6)", fontSize: 11 }}>菜单线索工作台</div>
            </div>
          )}
        </div>
        <Menu theme="dark" mode="inline" selectedKeys={[section]} style={{ borderRight: 0, marginTop: 8 }}
          items={NAV.map((n) => ({ key: n.key, icon: n.icon, label: <Link href={n.key}>{n.label}</Link> }))} />
        {!collapsed && (
          <div style={{ position: "absolute", bottom: 56, left: 20, right: 20, color: "rgba(255,255,255,0.45)", fontSize: 11, lineHeight: 1.6 }}>
            <div style={{ color: "#fab736", marginBottom: 4 }}>南京小当家文化咨询有限公司</div>
            系统不发送任何消息。所有对外联系由人执行后回填。
          </div>
        )}
      </Layout.Sider>
      <Layout>
        <Layout.Header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 24px", borderBottom: "1px solid #e8e3dc", borderTop: "3px solid #cf010e", position: "sticky", top: 0, zIndex: 10 }}>
          <Breadcrumb items={crumbs} />
          <Dropdown menu={{ items: [{ key: "settings", label: <Link href="/settings">设置与说明</Link> }, { type: "divider" }, { key: "logout", icon: <LogoutOutlined />, label: "退出登录", onClick: () => api("/api/auth/logout", { method: "POST" }).then(() => router.replace("/login")) }] }}>
            <Space style={{ cursor: "pointer" }}>
              <Avatar size="small" style={{ background: "#cf010e" }}>{(me ?? "?").slice(0, 1).toUpperCase()}</Avatar>
              <Typography.Text>{me ?? "…"}</Typography.Text>
            </Space>
          </Dropdown>
        </Layout.Header>
        <Layout.Content style={{ padding: "20px 24px 40px", maxWidth: 1400, width: "100%", margin: "0 auto" }}>{children}</Layout.Content>
        <Layout.Footer style={{ textAlign: "center", color: "#9ca3af", fontSize: 12, padding: "12px 24px" }}>小当家 · 菜单线索工作台（验证版）· 数据来源 FSA（OGL v3）、Overture Maps（CDLA-Permissive-2.0）· 评分不代表成交概率</Layout.Footer>
      </Layout>
    </Layout>
  );
}
