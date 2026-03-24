import fs from "fs";
import path from "path";

const rootDir = path.resolve(process.cwd(), "..");
const rootEnvPath = path.join(rootDir, ".env");
const rootConfigPath = path.join(rootDir, "config.yaml");

function parseKeyValueFile(filePath, separator) {
  if (!fs.existsSync(filePath)) {
    return {};
  }
  const lines = fs.readFileSync(filePath, "utf-8").split(/\r?\n/);
  const entries = {};
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes(separator)) {
      continue;
    }
    const parts = trimmed.split(separator);
    const key = parts.shift().trim();
    const value = parts.join(separator).trim().replace(/^['"]|['"]$/g, "");
    if (key) {
      entries[key] = value;
    }
  }
  return entries;
}

const envEntries = parseKeyValueFile(rootEnvPath, "=");
const configEntries = parseKeyValueFile(rootConfigPath, ":");

for (const [key, value] of Object.entries(configEntries)) {
  if (process.env[key] === undefined && envEntries[key] === undefined) {
    process.env[key] = value;
  }
}

for (const [key, value] of Object.entries(envEntries)) {
  if (process.env[key] === undefined) {
    process.env[key] = value;
  }
}

/** @type {import("next").NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: {
    optimizePackageImports: ["react"]
  }
};

export default nextConfig;
