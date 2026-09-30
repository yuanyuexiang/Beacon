import type { NextConfig } from "next";

// 开发与试点部署：把 /api 代理到后端，保持同源 cookie。生产可改为反向代理。
const API = process.env.BEACON_API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
};

export default nextConfig;
