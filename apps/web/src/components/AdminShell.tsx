"use client";
import { Avatar, Breadcrumb, Dropdown, Layout, Menu, Space, Typography } from "antd";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const NAV = [
  { key: "/", label: "仪表盘", icon: "◫" },
  { key: "/leads", label: "批次与线索", icon: "☰" },
  { key: "/tasks", label: "人工任务与回复", icon: "✉" },
  { key: "/settings", label: "设置与说明", icon: "⚙" },
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
        <div style={{ height: 52, display: "flex", alignItems: "center", justifyContent: collapsed ? "center" : "flex-start", padding: collapsed ? 0 : "0 20px", color: "#fff", fontWeight: 700, fontSize: 16, letterSpacing: 1, borderBottom: "1px solid rgba(255,255,255,0.08)" }}>
          {collapsed ? "B" : "Beacon"}
          {!collapsed && <span style={{ marginLeft: 8, fontSize: 11, fontWeight: 400, color: "rgba(255,255,255,0.55)" }}>菜单线索工作台</span>}
        </div>
        <Menu theme="dark" mode="inline" selectedKeys={[section]} style={{ borderRight: 0, marginTop: 8 }}
          items={NAV.map((n) => ({ key: n.key, icon: <span style={{ fontSize: 14 }}>{n.icon}</span>, label: <Link href={n.key}>{n.label}</Link> }))} />
        {!collapsed && (
          <div style={{ position: "absolute", bottom: 56, left: 20, right: 20, color: "rgba(255,255,255,0.45)", fontSize: 11, lineHeight: 1.5 }}>
            系统不发送任何消息。所有对外联系由人执行后回填。
          </div>
        )}
      </Layout.Sider>
      <Layout>
        <Layout.Header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 24px", borderBottom: "1px solid #e5e7eb", position: "sticky", top: 0, zIndex: 10 }}>
          <Breadcrumb items={crumbs} />
          <Dropdown menu={{ items: [{ key: "settings", label: <Link href="/settings">设置与说明</Link> }, { type: "divider" }, { key: "logout", label: "退出登录", onClick: () => api("/api/auth/logout", { method: "POST" }).then(() => router.replace("/login")) }] }}>
            <Space style={{ cursor: "pointer" }}>
              <Avatar size="small" style={{ background: "#1f6feb" }}>{(me ?? "?").slice(0, 1).toUpperCase()}</Avatar>
              <Typography.Text>{me ?? "…"}</Typography.Text>
            </Space>
          </Dropdown>
        </Layout.Header>
        <Layout.Content style={{ padding: "20px 24px 40px", maxWidth: 1400, width: "100%", margin: "0 auto" }}>{children}</Layout.Content>
        <Layout.Footer style={{ textAlign: "center", color: "#9ca3af", fontSize: 12, padding: "12px 24px" }}>Beacon 验证版 · 数据来源 FSA（OGL v3）、Overture Maps（CDLA-Permissive-2.0）· 评分不代表成交概率</Layout.Footer>
      </Layout>
    </Layout>
  );
}
