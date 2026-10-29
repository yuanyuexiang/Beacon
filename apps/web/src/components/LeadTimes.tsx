"use client";
import { Tooltip } from "antd";

export function displayTime(value?: string | null) {
  if (!value || !Number.isFinite(Date.parse(value))) return "未记录";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

export default function LeadTimes({ createdAt, updatedAt }: { createdAt?: string; updatedAt?: string }) {
  return <div style={{ fontSize: 12, color: "#888", marginTop: 6, lineHeight: 1.7 }}>
    <Tooltip title="首次加入系统的时间，跨名单复用不会重置；不是餐厅开业或 FSA 登记时间。">
      <div>首次加入：{displayTime(createdAt)}</div>
    </Tooltip>
    <Tooltip title="门店记录、联系方式、菜单或分析的最近变动，包含检查失败及人工修改，不代表全部资料已完善。时间按当前设备时区显示。">
      <div>最近更新：{displayTime(updatedAt)}</div>
    </Tooltip>
  </div>;
}
