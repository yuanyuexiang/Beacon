"use client";
import { Card, Space, Tag, Typography } from "antd";
import type { ReactNode } from "react";

export const BRAND = { red: "#cf010e", gold: "#fab736", dark: "#1b1b1b", ink: "#1f1f1f" };

/** 页面顶部品牌带：深色渐变，主视觉只作很淡的底纹（样式在 globals.css） */
export function HeroBand({ title, subtitle, extra, kicker, children }: { title: ReactNode; subtitle?: ReactNode; extra?: ReactNode; kicker?: ReactNode; children?: ReactNode }) {
  return (
    <div className="beacon-hero">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: 16, flexWrap: "wrap" }}>
        <div style={{ minWidth: 0 }}>
          {kicker && <div className="beacon-hero-kicker">{kicker}</div>}
          <Typography.Title level={3} style={{ color: "#fff", margin: 0, fontWeight: 700, letterSpacing: 0.5 }}>{title}</Typography.Title>
          {subtitle && <div className="beacon-hero-sub">{subtitle}</div>}
        </div>
        {extra && <Space wrap>{extra}</Space>}
      </div>
      {children}
    </div>
  );
}

/** 指标卡：左侧色块图标 + 标题 + 数值 + 说明 */
export function StatCard({ icon, color = BRAND.red, title, value, hint, onClick }: { icon: ReactNode; color?: string; title: ReactNode; value: ReactNode; hint?: ReactNode; onClick?: () => void }) {
  return (
    <Card className="beacon-stat" size="small" hoverable={!!onClick} onClick={onClick} styles={{ body: { padding: "16px 18px" } }} style={{ height: "100%" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div style={{ width: 46, height: 46, borderRadius: 12, display: "grid", placeItems: "center", background: `linear-gradient(135deg, ${color}22, ${color}0d)`, color, fontSize: 21, flexShrink: 0 }}>{icon}</div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ color: "#8a8178", fontSize: 12 }}>{title}</div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
            <span className="beacon-stat-value" style={{ fontSize: 26, fontWeight: 700, lineHeight: 1.25, color: BRAND.ink }}>{value}</span>
            {hint && <span style={{ color: "#a39a90", fontSize: 12 }}>{hint}</span>}
          </div>
        </div>
      </div>
    </Card>
  );
}

/** 横向条形：漏斗。数值为 0 时不画色条，避免看起来像有数据 */
export function Bars({ rows, max }: { rows: { label: string; code: string; value: number; ratio?: string }[]; max: number }) {
  return (
    <div style={{ display: "grid", gap: 12 }}>
      {rows.map((r) => (
        <div key={r.code} style={{ display: "grid", gridTemplateColumns: "150px 1fr 110px", alignItems: "center", gap: 12, fontSize: 13 }}>
          <div><span style={{ display: "inline-block", width: 18, color: "#a39a90", fontFamily: "ui-monospace, Menlo, monospace" }}>{r.code}</span>{r.label}</div>
          <div className="beacon-bar-track">
            {r.value > 0 && <div className="beacon-bar-fill" style={{ width: `${max ? Math.max(2, (r.value / max) * 100) : 0}%` }} />}
          </div>
          <div style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}><b>{r.value}</b>{r.ratio && <span style={{ color: "#a39a90", marginLeft: 6, fontSize: 12 }}>{r.ratio}</span>}</div>
        </div>
      ))}
    </div>
  );
}

export const SCREEN_ZH: Record<string, string> = { unchecked: "待筛选", candidate: "候选", unknown: "未知", excluded_cafe: "咖啡店", excluded_chain: "连锁", excluded_canteen: "食堂", excluded_community: "社区/机构", excluded_institution: "机构", excluded_pub: "酒吧", excluded_closed: "已关闭", excluded_other: "其他排除" };
export const SCREEN_COLOR: Record<string, string> = { candidate: "green", unchecked: "default", unknown: "gold" };
export function ScreenTag({ value, reason }: { value: string; reason?: string | null }) {
  return <Tag color={SCREEN_COLOR[value] ?? "volcano"} title={reason ?? ""} style={{ marginInlineEnd: 0 }}>{SCREEN_ZH[value] ?? value}</Tag>;
}
