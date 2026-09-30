"use client";
import { Card, Descriptions, Typography } from "antd";
import { PageHeader } from "@/components/PageHeader";

export default function SettingsPage() {
  return (
    <>
      <PageHeader title="设置与说明" subtitle="运行参数在服务端 .env 中配置；这里只做说明。" />
      <Card size="small" title="工作流程">
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="1 建名单">批次与线索 → 新建批次 → 从 FSA 建立候选（地方当局、抽样数、种子）→ Overture 补官网 → 规则预筛</Descriptions.Item>
          <Descriptions.Item label="2 菜单证据">线索详情 → 抓取菜单 URL 或上传文件 → 规则分析 / 模型转录 → 逐条核对、确认问题 → 完成审核</Descriptions.Item>
          <Descriptions.Item label="3 样稿与文案">详情页生成局部样稿与短文案（只引用已确认问题）→ 审批；内容或源数据变化会使审批失效</Descriptions.Item>
          <Descriptions.Item label="4 准入与任务">人工任务页 → 记录渠道准入（allowed 必须有证据与规则版本）→ 创建任务 → 打开 → 人工发送后回填</Descriptions.Item>
          <Descriptions.Item label="5 回复与抑制">回复事件按 event_key 幂等；回复暂停任务，拒绝/退订进入抑制名单并取消任务</Descriptions.Item>
        </Descriptions>
      </Card>
      <Card size="small" title="边界" style={{ marginTop: 16 }}>
        <Typography.Paragraph>系统不调用任何发送接口。模型结果一律需人工核对；准入状态只能由操作者依据证据设置。评分与排序不代表成交概率。数据来源：FSA（OGL v3）、Overture Maps（CDLA-Permissive-2.0）；不使用 Google Maps 抓取。</Typography.Paragraph>
        <Typography.Text type="secondary">接口文档：<a href="/api/docs" target="_blank" rel="noreferrer">/api/docs</a></Typography.Text>
      </Card>
    </>
  );
}
