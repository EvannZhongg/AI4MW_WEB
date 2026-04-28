#!/usr/bin/env node
import { spawn } from "child_process";
import path from "path";
import { fileURLToPath } from "url";

import { getConfiguredFrontendPort, loadRootConfig } from "./root-config.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(scriptDir, "..");
const command = process.argv[2] || "dev";
const args = process.argv.slice(3);

loadRootConfig(frontendDir);

const port = getConfiguredFrontendPort();
const nextBin = path.join(frontendDir, "node_modules", "next", "dist", "bin", "next");
const nextArgs = [nextBin, command, ...args];

if ((command === "dev" || command === "start") && port !== null && !hasPortArg(args)) {
  nextArgs.push("-p", String(port));
}

const child = spawn(process.execPath, nextArgs, {
  cwd: frontendDir,
  env: process.env,
  stdio: "inherit"
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});

function hasPortArg(args) {
  return args.some((arg, index) => {
    if (arg === "-p" || arg === "--port") {
      return true;
    }
    if (arg.startsWith("-p=") || arg.startsWith("--port=")) {
      return true;
    }
    return index > 0 && (args[index - 1] === "-p" || args[index - 1] === "--port");
  });
}
