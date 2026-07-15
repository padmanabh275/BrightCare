import type { NextConfig } from "next";

/**
 * Prefer App Router proxy at app/api/[...path]/route.ts (runtime API_PROXY_URL).
 * Keep /health rewrite for local health checks.
 */
const API_PROXY = process.env.API_PROXY_URL || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  reactCompiler: true,
  reactStrictMode: true,
  async rewrites() {
    return [{ source: "/health", destination: `${API_PROXY}/health` }];
  },
};

export default nextConfig;