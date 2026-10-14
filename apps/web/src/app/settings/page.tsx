"use client";
import { ApiOutlined, AuditOutlined, FileProtectOutlined, SafetyCertificateOutlined, SendOutlined, ShopOutlined } from "@ant-design/icons";
import { Card, Col, Row, Typography } from "antd";
import SocialSettings from "@/components/SocialSettings";
import GmailSettings from "@/components/GmailSettings";
import { BRAND, HeroBand } from "@/components/ui";

const FLOW = [
  { icon: <ShopOutlined />, title: "建名单", text: "批次与线索 → 建立名单 → 选择地区、餐厅数量和名单名称 → 自动获取餐厅、补充官网与电话、预筛、查找联系方式；已有名单可通过“补充数据”继续处理。" },
  { icon: <FileProtectOutlined />, title: "菜单证据", text: "线索详情 → AI 自动补全官网与菜单（异常复核），或手动抓取 / 上传 → 分析 → 逐条核对名称价格、确认问题 → 完成审核。" },
  { icon: <AuditOutlined />, title: "样稿与文案", text: "生成局部样稿与短文案（只引用已确认问题）→ 审批；内容或源数据变化会使审批失效。" },
  { icon: <SafetyCertificateOutlined />, title: "准入与任务", text: "记录渠道准入（allowed 必须有证据与规则版本）→ 创建任务 → 邮件或已连接社媒会话预览确认后发送，其余渠道人工回填。" },
  { icon: <SendOutlined />, title: "回复与抑制", text: "回复事件按 event_key 幂等；回复暂停任务，拒绝/退订进入抑制名单并取消任务。" },
];

export default function SettingsPage() {
  return (
    <>
      <HeroBand kicker="SETTINGS" title="设置与说明" subtitle="管理邮件与社媒授权及发送设置，查看工作流程和系统边界。" extra={<a href="/api/docs" target="_blank" rel="noreferrer" style={{ color: BRAND.gold }}><ApiOutlined /> 接口文档</a>} />
      <GmailSettings />
      <SocialSettings />
      <Row gutter={[16, 16]}>
        {FLOW.map((f, i) => (
          <Col xs={24} md={12} xl={8} key={f.title}>
            <Card size="small" style={{ height: "100%" }}>
              <div style={{ display: "flex", gap: 14 }}>
                <div style={{ width: 40, height: 40, borderRadius: 10, background: `${BRAND.red}14`, color: BRAND.red, display: "grid", placeItems: "center", fontSize: 18, flexShrink: 0 }}>{f.icon}</div>
                <div>
                  <div style={{ fontWeight: 700, marginBottom: 4 }}><span style={{ color: BRAND.gold, marginRight: 6 }}>0{i + 1}</span>{f.title}</div>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>{f.text}</Typography.Text>
                </div>
              </div>
            </Card>
          </Col>
        ))}
        <Col xs={24} md={12} xl={8}>
          <Card size="small" style={{ height: "100%", borderTop: `3px solid ${BRAND.red}` }} title="系统边界">
            <Typography.Paragraph style={{ fontSize: 12, marginBottom: 0 }}>Gmail 邮件在完整预览并确认后可由独立服务发送；Facebook／Instagram 已连接会话支持确认后文字回复；其余渠道人工执行。官网与菜单来源可由 AI + 程序证据校验自动处理；菜单名称、价格和问题仍需人工核对；准入状态只能由操作者依据证据设置。数据来源：FSA（OGL v3）、Overture Maps（CDLA-Permissive-2.0）。Google Places 按需补充官网候选、价格参考与地点照片；门店关联人工确认，官网可经 AI + 程序校验采用；测试阶段支持单家从 Google Maps 菜单区获取图片并转录；专用浏览器会话可用性需逐次验证，菜单日期未知时保持未知。</Typography.Paragraph>
          </Card>
        </Col>
      </Row>
    </>
  );
}
