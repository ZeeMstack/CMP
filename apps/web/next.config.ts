import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Enables the standalone server output (`.next/standalone`) consumed by
  // apps/web/Dockerfile's runtime stage (DEPLOY-001B) -- a self-contained
  // server.js plus only the node_modules subset actually required at
  // runtime, instead of shipping the full node_modules tree.
  output: "standalone",
};

export default nextConfig;
