import type { Metadata } from "next";
import { AntdRegistry } from "@ant-design/nextjs-registry";
import { Shell } from "@/components/Shell";

export const metadata: Metadata = { title: "Beacon 工作台", description: "菜单线索研究与人工联系记录" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body style={{ margin: 0 }}>
        <AntdRegistry>
          <Shell>{children}</Shell>
        </AntdRegistry>
      </body>
    </html>
  );
}
