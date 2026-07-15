import type { NextConfig } from "next";

const API_PROXY = process.env.API_PROXY_URL || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  reactCompiler: true,
  reactStrictMode: true,
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_PROXY}/api/:path*` },
      { source: "/health", destination: `${API_PROXY}/health` },
    ];
  },
};

export default nextConfig;
