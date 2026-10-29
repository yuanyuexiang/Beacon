"use client";
import { displayTime } from "./LeadTimes";
import Link from "next/link";
import { Tooltip } from "antd";
import type { ListSummary } from "@/lib/lead-list";
import { channelLabel } from "@/lib/format";

const items = [
  ["website", "门店与官网", "官网核验结果；有网址不代表已核验"],
  ["contacts", "联系方式", "已记录联系方式，不代表已允许发送"],
  ["menus", "菜单获取", "已获取或上传菜单；没有菜单也可准备触达"],
  ["analysis", "菜单分析", "当前菜单文件的分析结果；人工核对另行进行"],
] as const;
const states: Record<string, { icon: string; text: string; color: string }> = {
  done: { icon: "✓", text: "已完成", color: "#389e0d" },
  pending: { icon: "○", text: "待完善", color: "#888" },
  running: { icon: "◷", text: "处理中", color: "#1677ff" },
  failed: { icon: "!", text: "待重试", color: "#d46b08" },
  not_found: { icon: "○", text: "未找到", color: "#888" },
};
export default function LeadCompleteness({ id, summary, returnTo }: { id: string; summary?: ListSummary | null; returnTo: string }) {
  return <div style={{ display: "grid", gridTemplateColumns: "repeat(2, max-content)", gap: "8px 16px", fontSize: 12 }}>
    {items.map(([key, title, help]) => {
      const state = states[summary?.completeness?.[key] || "pending"] || states.pending;
      const detail = key === "contacts" ? summary?.channels.map((c) => channelLabel(c)).join("／") : "";
      return <Tooltip key={key} title={`${title}：${state.text}。${help}；${({ website: "最近核验", contacts: "最近查找", menus: "最近获取", analysis: "分析创建" })[key]}：${displayTime(summary?.activity_times?.[key])}${detail ? `；${detail}` : ""}`}>
        <Link href={`/leads/${id}?returnTo=${encodeURIComponent(returnTo)}&section=${key}`} aria-label={`${title}：${state.text}`} style={{ color: state.color, whiteSpace: "nowrap" }}>
          <span aria-hidden style={{ marginRight: 5 }}>{state.icon}</span>{title}{["failed", "running", "not_found"].includes(summary?.completeness?.[key] || "") ? ` · ${state.text}` : ""}
        </Link>
      </Tooltip>;
    })}
  </div>;
}
