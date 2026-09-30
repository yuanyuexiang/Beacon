"use client";
import { Layout, Menu, Typography } from "antd";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [me, setMe] = useState<string | null>(null);
  useEffect(() => {
    if (path === "/login") return;
    api<{ username: string }>("/api/auth/me")
      .then((m) => setMe(m.username))
      .catch(() => router.replace("/login"));
  }, [path, router]);
  if (path === "/login") return <>{children}</>;
  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Layout.Header style={{ display: "flex", alignItems: "center", gap: 24 }}>
        <Typography.Text strong style={{ color: "#fff" }}>Beacon</Typography.Text>
        <Menu
          theme="dark"
          mode="horizontal"
          selectedKeys={[path.startsWith("/tasks") ? "/tasks" : "/"]}
          items={[
            { key: "/", label: <Link href="/">线索与批次</Link> },
            { key: "/tasks", label: <Link href="/tasks">人工任务与回复</Link> },
          ]}
          style={{ flex: 1 }}
        />
        <Typography.Text style={{ color: "#ddd" }}>
          {me ?? "…"}{" "}
          <a onClick={() => api("/api/auth/logout", { method: "POST" }).then(() => router.replace("/login"))}>退出</a>
        </Typography.Text>
      </Layout.Header>
      <Layout.Content style={{ padding: 24, maxWidth: 1200, width: "100%", margin: "0 auto" }}>{children}</Layout.Content>
    </Layout>
  );
}
