"use client";
import { Card, Space, Tag, Typography } from "antd";
import type { ReactNode } from "react";

export const BRAND = { red: "#cf010e", gold: "#fab736", dark: "#1b1b1b", ink: "#1f1f1f" };

/** 页面顶部品牌带：深色渐变 + 主视觉底纹 */
export function HeroBand({ title, subtitle, extra, kicker, children }: { title: ReactNode; subtitle?: ReactNode; extra?: ReactNode; kicker?: ReactNode; children?: ReactNode }) {
  return (
    <div style={{ position: "relative", overflow: "hidden", borderRadius: 10, padding: "26px 28px", marginBottom: 20, color: "#fff",
      backgroundImage: "linear-gradient(110deg, rgba(27,27,27,0.97) 0%, rgba(27,27,27,0.88) 60%, rgba(207,1,14,0.45) 100%), url(/brand/banner.jpg)", backgroundSize: "cover", backgroundPosition: "center 40%" }}>
      <div style={{ position: "absolute", left: 0, top: 0, right: 0, height: 3, background: `linear-gradient(90deg, ${BRAND.red}, ${BRAND.gold})` }} />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: 16, flexWrap: "wrap" }}>
        <div>
          {kicker && <div style={{ color: BRAND.gold, fontSize: 12, letterSpacing: 2, marginBottom: 6 }}>{kicker}</div>}
          <Typography.Title level={3} style={{ color: "#fff", margin: 0, fontWeight: 700 }}>{title}</Typography.Title>
          {subtitle && <div style={{ color: "rgba(255,255,255,0.72)", marginTop: 6, fontSize: 13 }}>{subtitle}</div>}
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
    <Card size="small" hoverable={!!onClick} onClick={onClick} styles={{ body: { padding: 16 } }} style={{ height: "100%" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div style={{ width: 42, height: 42, borderRadius: 10, display: "grid", placeItems: "center", background: `${color}14`, color, fontSize: 20, flexShrink: 0 }}>{icon}</div>
        <div style={{ minWidth: 0 }}>
          <div style={{ color: "#8a8a8a", fontSize: 12 }}>{title}</div>
          <div style={{ fontSize: 24, fontWeight: 700, lineHeight: 1.2, color: BRAND.ink }}>{value}</div>
          {hint && <div style={{ color: "#a3a3a3", fontSize: 11, marginTop: 2 }}>{hint}</div>}
        </div>
      </div>
    </Card>
  );
}

/** 横向条形：漏斗 */
export function Bars({ rows, max }: { rows: { label: string; code: string; value: number; ratio?: string }[]; max: number }) {
  return (
    <div style={{ display: "grid", gap: 10 }}>
      {rows.map((r) => (
        <div key={r.code} style={{ display: "grid", gridTemplateColumns: "150px 1fr 120px", alignItems: "center", gap: 12, fontSize: 13 }}>
          <div><span style={{ color: "#8a8a8a", marginRight: 6, fontFamily: "monospace" }}>{r.code}</span>{r.label}</div>
          <div style={{ background: "#f1ede8", borderRadius: 4, height: 18, overflow: "hidden" }}>
            <div style={{ width: `${max ? Math.max(2, (r.value / max) * 100) : 0}%`, height: "100%", background: `linear-gradient(90deg, ${BRAND.red}, #f05a5a)`, borderRadius: 4, transition: "width .3s" }} />
          </div>
          <div style={{ textAlign: "right" }}><b>{r.value}</b>{r.ratio && <span style={{ color: "#8a8a8a", marginLeft: 6, fontSize: 12 }}>{r.ratio}</span>}</div>
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
