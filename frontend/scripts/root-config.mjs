import fs from "fs";
import path from "path";

export function parseKeyValueFile(filePath, separator) {
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

export function loadRootConfig(frontendDir = process.cwd()) {
  const rootDir = path.resolve(frontendDir, "..");
  const envEntries = parseKeyValueFile(path.join(rootDir, ".env"), "=");
  const configEntries = parseKeyValueFile(path.join(rootDir, "config.yaml"), ":");

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

  return { configEntries, envEntries };
}

export function getConfiguredFrontendPort(env = process.env) {
  const rawPort = String(env.FRONTEND_PORT ?? "").trim().toLowerCase();
  if (!rawPort || rawPort === "auto") {
    return null;
  }
  const port = Number(rawPort);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    return null;
  }
  return port;
}
