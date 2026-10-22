#!/usr/bin/env node
import { spawn } from "node:child_process";
import { constants } from "node:os";
import { buildDockerArgs, buildDockerEnv } from "../src/docker-args.mjs";

const EXIT_USAGE = 3; // same as the Python CLI's usage/config error code

const MISSING_DOCKER = `agentlab: docker not found on PATH.
Install Docker Desktop or OrbStack, then build the image once from the repo root:
  docker build -t agentlab <path-to-agentlab-repo>`;

let args;
try {
  args = buildDockerArgs({
    argv: process.argv.slice(2),
    cwd: process.cwd(),
    env: process.env,
    uid: process.getuid?.(),
    gid: process.getgid?.(),
    isTTY: Boolean(process.stdin.isTTY && process.stdout.isTTY),
  });
} catch (err) {
  console.error(`agentlab: ${err.message}`);
  process.exit(EXIT_USAGE);
}

const child = spawn("docker", args, { stdio: "inherit", env: buildDockerEnv(process.env) });

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => child.kill(signal));
}

child.on("error", (err) => {
  console.error(err.code === "ENOENT" ? MISSING_DOCKER : `agentlab: failed to start docker: ${err.message}`);
  process.exit(EXIT_USAGE);
});

child.on("close", (code, signal) => {
  process.exit(code ?? 128 + (constants.signals[signal] ?? 0));
});
