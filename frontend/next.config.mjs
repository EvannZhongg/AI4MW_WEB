import path from "path";
import { fileURLToPath } from "url";

import { loadRootConfig } from "./scripts/root-config.mjs";

const frontendDir = path.dirname(fileURLToPath(import.meta.url));
loadRootConfig(frontendDir);

/** @type {import("next").NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: {
    optimizePackageImports: ["react"]
  }
};

export default nextConfig;
