"use client";
import { Space, Typography } from "antd";

export function PageHeader({ title, subtitle, extra }: { title: React.ReactNode; subtitle?: React.ReactNode; extra?: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 16, gap: 16, flexWrap: "wrap" }}>
      <div>
        <Typography.Title level={4} style={{ margin: 0 }}>{title}</Typography.Title>
        {subtitle && <Typography.Text type="secondary">{subtitle}</Typography.Text>}
      </div>
      {extra && <Space wrap>{extra}</Space>}
    </div>
  );
}
