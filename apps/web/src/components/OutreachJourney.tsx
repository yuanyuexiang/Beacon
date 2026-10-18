import { Card, Steps } from "antd";

export default function OutreachJourney({ current }: { current: number }) {
  return <Card size="small" style={{ marginBottom: 16 }} aria-label="客户沟通流程" styles={{ body: { padding: "14px 20px" } }}>
    <Steps size="small" current={current} items={["完善客户资料", "准备触达", "确认发送", "沟通跟进"].map((title, index) => ({ title, status: index === current ? "process" as const : "wait" as const }))} />
  </Card>;
}
