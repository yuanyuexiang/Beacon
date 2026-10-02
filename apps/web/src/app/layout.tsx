import "./globals.css";
import type { Metadata } from "next";
import { AntdRegistry } from "@ant-design/nextjs-registry";
import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { AdminShell } from "@/components/AdminShell";

export const metadata: Metadata = { title: "小当家 · 销售线索工作台", description: "餐厅菜单线索研究与人工联系记录", icons: { icon: "/brand/logo-64.png" } };

// 品牌色取自客户官网：主红 #cf010e，金黄 #fab736 / #f6a508，深色底 #1b1b1b；字体微软雅黑
const theme = {
  token: { colorPrimary: "#cf010e", colorInfo: "#cf010e", colorLink: "#1f1f1f", colorLinkHover: "#cf010e", colorWarning: "#f6a508", borderRadius: 8, fontSize: 13, colorBgLayout: "#f6f4f1", colorBorderSecondary: "#efe9e1", colorTextHeading: "#1f1f1f", fontFamily: "'Microsoft YaHei', 'PingFang SC', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif" },
  components: {
    Layout: { siderBg: "#1b1b1b", headerBg: "#ffffff", headerHeight: 52, triggerBg: "#111111", triggerColor: "#fab736" },
    Menu: { darkItemBg: "#1b1b1b", darkSubMenuItemBg: "#1b1b1b", darkItemSelectedBg: "#cf010e", darkItemHoverBg: "#2a2a2a", darkItemColor: "rgba(255,255,255,0.72)" },
    Card: { headerFontSize: 14, borderRadiusLG: 12 },
    Table: { headerBg: "#faf7f2", headerColor: "#6b6259", headerSplitColor: "transparent", rowHoverBg: "#fdf8f1", borderColor: "#f1ece5" },
    Tabs: { titleFontSize: 13 },
    Modal: { borderRadiusLG: 14 },
    Statistic: { titleFontSize: 12 },
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body style={{ margin: 0 }}>
        <AntdRegistry>
          <ConfigProvider locale={zhCN} theme={theme}>
            <AdminShell>{children}</AdminShell>
          </ConfigProvider>
        </AntdRegistry>
      </body>
    </html>
  );
}
