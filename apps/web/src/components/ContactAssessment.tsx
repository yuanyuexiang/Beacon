import { Tag, Typography } from "antd";
import { CONTACT_PURPOSE, CONTACT_RANK_LABELS, ContactAssessment as Assessment } from "@/lib/contact-ranking";

export default function ContactAssessment({ value }: { value?: Assessment | null }) {
  if (!value) return <Typography.Text type="secondary">尚未 AI 筛选</Typography.Text>;
  return <div><Tag color={value.recommendation === "recommended" ? "green" : value.recommendation === "not_recommended" ? "default" : "orange"}>{CONTACT_RANK_LABELS[value.recommendation] || "待确认"}</Tag><span>{value.owner || "归属未明"} · {CONTACT_PURPOSE[value.purpose || "unknown"]}</span><div style={{ color: "#888", fontSize: 12, marginTop: 4 }}>{value.reason}</div></div>;
}
