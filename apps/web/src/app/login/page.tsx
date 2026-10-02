"use client";
import { Button, Form, Input, Typography, message } from "antd";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, json } from "@/lib/api";

const RED = "#cf010e";
const GOLD = "#fab736";
const SERVICES = ["菜单设计与印刷", "折页 / 坐台菜单", "代金券 / 名片", "智能点餐系统", "智能后厨设备"];
const REGIONS = ["英国", "法国", "德国", "西班牙", "意大利", "美国"];

export default function LoginPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  return (
    <div style={{ minHeight: "100vh", display: "grid", gridTemplateColumns: "minmax(0, 1.15fr) minmax(400px, 0.85fr)", background: "#111" }} className="login-grid">
      <style>{`
        @media (max-width: 900px) {
          .login-grid { grid-template-columns: 1fr !important; }
          .login-brand { padding: 24px 24px !important; gap: 20px; }
          .login-brand .brand-title { font-size: 24px !important; }
          .login-brand .brand-desc, .login-brand .brand-services, .login-brand .brand-foot { display: none !important; }
        }
        .login-input .ant-input, .login-input .ant-input-affix-wrapper { padding: 10px 12px; }
        .login-input .ant-input-affix-wrapper .ant-input { padding: 0; }
      `}</style>

      {/* 左：品牌区 */}
      <section className="login-brand" style={{ position: "relative", overflow: "hidden", display: "flex", flexDirection: "column", justifyContent: "space-between", padding: "40px 48px", color: "#fff", backgroundImage: "linear-gradient(115deg, rgba(17,17,17,0.94) 0%, rgba(17,17,17,0.72) 55%, rgba(207,1,14,0.35) 100%), url(/brand/banner.jpg)", backgroundSize: "cover", backgroundPosition: "center" }}>
        <div style={{ position: "absolute", left: 0, top: 0, right: 0, height: 4, background: `linear-gradient(90deg, ${RED}, ${GOLD})` }} />
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/brand/logo.png" alt="小当家" style={{ height: 44 }} />
          <div style={{ lineHeight: 1.25 }}>
            <div style={{ fontWeight: 700, fontSize: 16, letterSpacing: 1 }}>南京小当家文化咨询有限公司</div>
            <div style={{ fontSize: 12, color: "rgba(255,255,255,0.65)" }}>海外中餐 · 菜单设计印刷 · 智能餐饮科技</div>
          </div>
        </div>

        <div style={{ maxWidth: 560 }}>
          <div style={{ display: "inline-block", padding: "4px 10px", border: `1px solid ${GOLD}`, color: GOLD, borderRadius: 999, fontSize: 12, letterSpacing: 2, marginBottom: 18 }}>销售线索工作台</div>
          <Typography.Title className="brand-title" style={{ color: "#fff", margin: 0, fontSize: 40, lineHeight: 1.2, fontWeight: 800 }}>
            找到最需要<span style={{ color: GOLD }}>改版菜单</span>的餐厅，
            <br />把时间留给真正有意向的客户。
          </Typography.Title>
          <Typography.Paragraph className="brand-desc" style={{ color: "rgba(255,255,255,0.78)", fontSize: 15, marginTop: 18, marginBottom: 28, lineHeight: 1.8 }}>
            自动发现餐厅、采集菜单、标出可核对的真实问题，生成改版样稿与各渠道话术；每一次联系由销售确认后发出，全程留痕可审计。
          </Typography.Paragraph>
          <div className="brand-services" style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {SERVICES.map((s) => (
              <span key={s} style={{ padding: "6px 12px", background: "rgba(255,255,255,0.08)", border: "1px solid rgba(255,255,255,0.14)", borderRadius: 6, fontSize: 12 }}>{s}</span>
            ))}
          </div>
        </div>

        <div className="brand-foot" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12, fontSize: 12, color: "rgba(255,255,255,0.6)" }}>
          <div>全球业务分布：{REGIONS.join(" · ")}</div>
          <div>数据来源 FSA（OGL v3）· Overture Maps · 不使用地图抓取</div>
        </div>
      </section>

      {/* 右：登录表单 */}
      <section style={{ background: "#fff", display: "flex", alignItems: "center", justifyContent: "center", padding: "48px 40px" }}>
        <div style={{ width: "100%", maxWidth: 380 }}>
          <div style={{ marginBottom: 32 }}>
            <div style={{ width: 40, height: 4, background: RED, borderRadius: 2, marginBottom: 20 }} />
            <Typography.Title level={2} style={{ margin: 0, fontWeight: 700 }}>操作者登录</Typography.Title>
            <Typography.Text type="secondary">请使用管理员分配的操作者账号</Typography.Text>
          </div>
          <Form layout="vertical" size="large" requiredMark={false} className="login-input"
            onFinish={(v) => { setLoading(true); api("/api/auth/login", json(v)).then(() => router.replace("/")).catch((e) => { message.error(e.message); setLoading(false); }); }}>
            <Form.Item name="username" label={<span style={{ fontWeight: 600 }}>操作者</span>} rules={[{ required: true, message: "请输入操作者" }]}>
              <Input autoComplete="username" placeholder="admin" />
            </Form.Item>
            <Form.Item name="password" label={<span style={{ fontWeight: 600 }}>口令</span>} rules={[{ required: true, message: "请输入口令" }]} style={{ marginBottom: 28 }}>
              <Input.Password autoComplete="current-password" placeholder="请输入口令" />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading} style={{ height: 46, fontSize: 15, fontWeight: 600, boxShadow: "0 8px 20px rgba(207,1,14,0.25)" }}>登 录</Button>
          </Form>
          <div style={{ marginTop: 28, padding: "12px 14px", background: "#faf7f2", borderLeft: `3px solid ${GOLD}`, borderRadius: 4, fontSize: 12, color: "#6b6b6b", lineHeight: 1.7 }}>
            系统不发送任何消息；所有对外联系由销售确认后执行并回填。评分与排序不代表成交概率。
          </div>
          <div style={{ marginTop: 36, fontSize: 12, color: "#9a9a9a", textAlign: "center" }}>© 南京小当家文化咨询有限公司 · 销售线索工作台 验证版</div>
        </div>
      </section>
    </div>
  );
}
