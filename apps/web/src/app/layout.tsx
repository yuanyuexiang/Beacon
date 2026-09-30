import type { Metadata } from "next";
import { AntdRegistry } from "@ant-design/nextjs-registry";
import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { AdminShell } from "@/components/AdminShell";

export const metadata: Metadata = { title: "Beacon 工作台", description: "餐厅菜单线索研究与人工联系记录" };

const theme = {
  token: { colorPrimary: "#1f6feb", borderRadius: 6, fontSize: 13, colorBgLayout: "#f5f6f8" },
  components: { Layout: { siderBg: "#0f172a", headerBg: "#ffffff", headerHeight: 52 }, Menu: { darkItemBg: "#0f172a", darkSubMenuItemBg: "#0f172a", darkItemSelectedBg: "#1f6feb" }, Card: { headerFontSize: 14 } },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body style={{ margin: 0, fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Helvetica Neue', Arial, sans-serif" }}>
        <AntdRegistry>
          <ConfigProvider locale={zhCN} theme={theme}>
            <AdminShell>{children}</AdminShell>
          </ConfigProvider>
        </AntdRegistry>
      </body>
    </html>
  );
}
