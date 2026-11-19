import type { NextConfig } from "next";

// 开发与试点部署：把 /api 代理到后端，保持同源 cookie。生产可改为反向代理。
const API = process.env.BEACON_API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // /api 代理默认 30 秒超时；Overture 首次下载、全量 FSA 同步、批量抓取都可能更久，超时后前端只会看到 Internal Server Error
  experimental: {
    proxyTimeout: 10 * 60 * 1000,
    // Next 15 的 rewrite 代理同样使用请求体克隆，默认 10 MB 会截断 APK，
    // 原 Content-Length 却仍传给 API，导致后端等待剩余数据直至断连。
    // 与 API 的 APK 上限保持一致；API 仍负责权限、流式计数与签名校验。
    middlewareClientMaxBodySize: "256mb",
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
};

export default nextConfig;
