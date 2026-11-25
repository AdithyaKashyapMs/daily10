import type { NextConfig } from "next";

// The browser only ever talks to this Next.js server: /api/* is proxied to the FastAPI backend.
// So a phone on the same Wi-Fi needs just one address, and no CORS setup is required.
const API_URL = process.env.API_URL ?? "http://localhost:8000";

const config: NextConfig = {
  // Self-contained server for the Docker image (web/Dockerfile); `npm run dev` is unaffected.
  output: "standalone",
  // Question generation calls an LLM per topic and can take a few minutes.
  experimental: { proxyTimeout: 10 * 60 * 1000 },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/:path*` }];
  },
};

export default config;
