import type { NextConfig } from "next";

// 开发与试点部署：把 /api 代理到后端，保持同源 cookie。生产可改为反向代理。
const API = process.env.BEACON_API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // /api 代理默认 30 秒超时；Overture 首次下载、全量 FSA 同步、批量抓取都可能更久，超时后前端只会看到 Internal Server Error
  experimental: { proxyTimeout: 10 * 60 * 1000 },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
};

export default nextConfig;
