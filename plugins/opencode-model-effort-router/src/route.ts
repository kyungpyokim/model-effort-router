import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";

const ROUTE_TIMEOUT_MS = 10_000;
const MAX_OUTPUT_BYTES = 1_048_576;
const MER_BIN = fileURLToPath(new URL("../bin/mer", import.meta.url));

type ExecFile = typeof execFile;

export async function routeAdvice(
  task: string,
  role: string,
  effort: string,
  cwd: string,
  executable = MER_BIN,
  run: ExecFile = execFile,
) {
  return runRoute(task, cwd, ["--role", role, "--effort", effort], executable, run);
}

export async function automaticRouteAdvice(
  task: string,
  cwd: string,
  executable = MER_BIN,
  run: ExecFile = execFile,
) {
  return runRoute(task, cwd, ["--automatic"], executable, run);
}

async function runRoute(
  task: string,
  cwd: string,
  overrides: string[],
  executable: string,
  run: ExecFile,
) {
  if (!task.trim() || task.length > 20_000) throw new Error("task must be 1-20000 characters");
  const argv = ["route", "--host", "opencode", ...overrides, "--json", "--cwd", cwd, "--", task];
  const stdout = await new Promise<string>((resolve, reject) => {
    run(executable, argv, { cwd, timeout: ROUTE_TIMEOUT_MS, maxBuffer: MAX_OUTPUT_BYTES },
      (error, output, stderr) => {
        if (error) {
          const detail = String(stderr || error.message).trim().slice(0, 500);
          reject(new Error(`mer route failed: ${detail}`));
          return;
        }
        resolve(String(output));
      });
  });
  let result: unknown;
  try {
    result = JSON.parse(stdout);
  } catch {
    throw new Error("mer route returned invalid JSON");
  }
  if (!result || typeof result !== "object") throw new Error("mer route returned an invalid result");
  const advice = result as Record<string, unknown>;
  if (advice.route === "no_route") return null;
  if (!["role", "agent", "model", "effort"].every((key) => typeof advice[key] === "string")) {
    throw new Error("mer route result is missing role, agent, model, or effort");
  }
  return advice;
}
