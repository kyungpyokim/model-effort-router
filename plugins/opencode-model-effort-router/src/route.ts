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
  sessionID?: string,
) {
  return runRoute(
    task,
    cwd,
    ["--role", role, "--effort", effort, ...sessionArgs(sessionID)],
    executable,
    run,
  );
}

export async function automaticRouteAdvice(
  task: string,
  cwd: string,
  executable = MER_BIN,
  run: ExecFile = execFile,
  sessionID?: string,
) {
  return runRoute(
    task,
    cwd,
    ["--automatic", ...sessionArgs(sessionID)],
    executable,
    run,
  );
}

// Lets `mer route` record the route in this session's log, which `mer report` reads.
function sessionArgs(sessionID?: string) {
  return sessionID ? ["--session", sessionID] : [];
}

export async function routeReport(
  cwd: string,
  session?: string,
  limit?: number,
  executable = MER_BIN,
  run: ExecFile = execFile,
) {
  const argv = ["report"];
  if (session) argv.push("--session", session);
  if (limit !== undefined) argv.push("--limit", String(limit));
  return execMer("mer report", argv, cwd, executable, run);
}

async function runRoute(
  task: string,
  cwd: string,
  overrides: string[],
  executable: string,
  run: ExecFile,
) {
  if (!task.trim() || task.length > 20_000)
    throw new Error("task must be 1-20000 characters");
  const argv = [
    "route",
    "--host",
    "opencode",
    ...overrides,
    "--json",
    "--cwd",
    cwd,
    "--",
    task,
  ];
  const stdout = await execMer("mer route", argv, cwd, executable, run);
  let result: unknown;
  try {
    result = JSON.parse(stdout);
  } catch {
    throw new Error("mer route returned invalid JSON");
  }
  if (!result || typeof result !== "object")
    throw new Error("mer route returned an invalid result");
  const advice = result as Record<string, unknown>;
  if (advice.route === "no_route")
    return advice.mode === "auto" && typeof advice.message === "string"
      ? advice
      : null;
  if (
    !["role", "agent", "model", "effort"].every(
      (key) => typeof advice[key] === "string",
    )
  ) {
    throw new Error(
      "mer route result is missing role, agent, model, or effort",
    );
  }
  return advice;
}

function execMer(
  label: string,
  argv: string[],
  cwd: string,
  executable: string,
  run: ExecFile,
) {
  return new Promise<string>((resolve, reject) => {
    run(
      executable,
      argv,
      { cwd, timeout: ROUTE_TIMEOUT_MS, maxBuffer: MAX_OUTPUT_BYTES },
      (error, output, stderr) => {
        if (error) {
          const detail = String(stderr || error.message)
            .trim()
            .slice(0, 500);
          reject(new Error(`${label} failed: ${detail}`));
          return;
        }
        resolve(String(output));
      },
    );
  });
}
