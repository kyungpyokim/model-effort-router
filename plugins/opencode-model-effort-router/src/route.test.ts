import { describe, expect, it } from "bun:test";
import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";
import ModelEffortRouterPlugin from "./index";
import { automaticRouteAdvice, routeAdvice } from "./route";

type ExecFile = typeof execFile;
type ExecCallback = (error: Error | null, stdout: string, stderr: string) => void;

function fakeExec(
  emit: (
    info: { file: string; args: string[] },
    callback: ExecCallback,
  ) => void,
): ExecFile {
  const run = ((file: string, args: string[], _options: unknown, callback: ExecCallback) => {
    emit({ file, args }, callback);
    return {} as unknown as ReturnType<typeof execFile>;
  }) as unknown as ExecFile;
  return run;
}

function failingExec(message: string, stderr: string): ExecFile {
  return fakeExec((_info, callback) => {
    callback(new Error(message), "", stderr);
  });
}

describe("OpenCode plugin tool schema", () => {
  it("registers the visible mer tool with supported roles and efforts", async () => {
    const registered: {
      name: string;
      input: {
        properties: Record<string, { enum?: string[] }>;
        required: string[];
      };
      execute: (
        input: { task: string; mode?: string; role?: string; effort?: string },
        context: unknown,
      ) => Promise<{ content?: string }>;
    }[] = [];
    const previousCorePath = process.env.MER_CORE_PATH;
    process.env.MER_CORE_PATH = fileURLToPath(
      new URL("../../../", import.meta.url),
    );
    try {
      await ModelEffortRouterPlugin.setup({
        tool: {
          transform: async (
            register: (callbacks: {
              add: (definition: unknown) => void;
            }) => unknown,
          ) =>
            register({
              add: (definition) => registered.push(definition as never),
            }),
        },
        session: {
          get: async () => ({ location: { directory: process.cwd() } }),
          hook: async () => undefined,
        },
      } as never);
      expect(registered.map(({ name }) => name)).toEqual(["mer"]);
      expect(registered[0].input.properties.role.enum).toEqual([
        "implementation",
        "fix",
        "lint",
        "test",
        "plan",
        "design",
        "review",
        "analysis",
      ]);
      expect(registered[0].input.properties.effort.enum).toContain("max");
      expect(registered[0].input.properties.mode.enum).toEqual([
        "automatic",
        "explicit",
      ]);
      expect(registered[0].input.required).toEqual(["task"]);
      const result = await registered[0].execute(
        { task: "Add an OpenCode plugin", role: "plan", effort: "medium" },
        { sessionID: "test" },
      );
      expect(JSON.parse(result.content ?? "{}").role).toBe("plan");
      const automatic = await registered[0].execute(
        { task: "What is the capital of France?" },
        { sessionID: "test" },
      );
      expect(automatic.content).toBe("null");
      await expect(
        registered[0].execute(
          { task: "Review auth", mode: "explicit", role: "review" },
          { sessionID: "test" },
        ),
      ).rejects.toThrow("explicit mode requires both role and effort");
      await expect(
        registered[0].execute(
          {
            task: "Review auth",
            mode: "automatic",
            role: "review",
            effort: "high",
          },
          { sessionID: "test" },
        ),
      ).rejects.toThrow("automatic mode does not accept role or effort");
    } finally {
      if (previousCorePath === undefined) delete process.env.MER_CORE_PATH;
      else process.env.MER_CORE_PATH = previousCorePath;
    }
  });
});

describe("routeAdvice", () => {
  it("passes task text as an argument and parses JSON advice", async () => {
    let seen: { file: string; args: string[]; options: unknown } | undefined;
    const advice = await routeAdvice(
      "--host=claude",
      "plan",
      "medium",
      "/work",
      "/mer",
      fakeExec(({ file, args }, callback) => {
        seen = { file, args, options: undefined };
        callback(
          null,
          JSON.stringify({
            role: "plan",
            agent: "reasoning",
            model: "opencode/nemotron-3-ultra-free",
            effort: "medium",
          }),
          "",
        );
      }),
    );
    expect(seen?.file).toBe("/mer");
    expect(seen?.args).toContain("--host=claude");
    expect(seen?.args).toContain("--host");
    expect(seen?.args.slice(-2)).toEqual(["--", "--host=claude"]);
    expect(advice?.model).toBe("opencode/nemotron-3-ultra-free");
  });

  it("passes automatic classification through the existing CLI path", async () => {
    let seen: { file: string; args: string[] } | undefined;
    const advice = await automaticRouteAdvice(
      "Fix auth and payment boundaries",
      "/work",
      "/mer",
      fakeExec(({ file, args }, callback) => {
        seen = { file, args };
        callback(
          null,
          JSON.stringify({
            role: "review",
            agent: "reasoning",
            model: "opencode-go/glm-5.3",
            effort: "high",
          }),
          "",
        );
      }),
    );
    expect(seen?.file).toBe("/mer");
    expect(seen?.args).toContain("--automatic");
    expect(seen?.args.slice(-2)).toEqual([
      "--",
      "Fix auth and payment boundaries",
    ]);
    expect(advice?.effort).toBe("high");
  });

  it("surfaces subprocess failures and malformed output", async () => {
    await expect(
      routeAdvice("task", "plan", "medium", "/work", "/mer", failingExec("exit 2", "route rejected")),
    ).rejects.toThrow("route rejected");
    const malformed = fakeExec((_info, callback) => {
      callback(null, "not json", "");
    });
    await expect(
      routeAdvice("task", "plan", "medium", "/work", "/mer", malformed),
    ).rejects.toThrow("invalid JSON");
  });
});

describe("prompt hook routing banner", () => {
  const previousCorePath = process.env.MER_CORE_PATH;

  function fakeCtx(
    synthetic: (input: { sessionID: string; text: string }) => Promise<unknown>,
  ) {
    const harness: {
      hookFn?: (event: {
        sessionID: string;
        prompt: { text: string };
      }) => Promise<void>;
    } = {};
    return {
      harness,
      ctx: {
        tool: { transform: async () => undefined },
        session: {
          get: async () => ({
            parentID: undefined,
            location: { directory: process.cwd() },
          }),
          hook: async (
            _name: string,
            fn: (event: {
              sessionID: string;
              prompt: { text: string };
            }) => Promise<void>,
          ) => {
            harness.hookFn = fn;
          },
          synthetic: async (input: { sessionID: string; text: string }) =>
            synthetic(input),
        },
      },
    };
  }

  function runHook(
    harness: {
      hookFn?: (event: {
        sessionID: string;
        prompt: { text: string };
      }) => Promise<void>;
    },
    text: string,
  ) {
    return harness.hookFn?.({ sessionID: "test", prompt: { text } });
  }

  it("posts a visible synthetic banner when advice is produced", async () => {
    process.env.MER_CORE_PATH = fileURLToPath(
      new URL("../../../", import.meta.url),
    );
    try {
      const posted: { sessionID: string; text: string }[] = [];
      const { harness, ctx } = fakeCtx(async (input) => {
        posted.push(input);
      });
      await ModelEffortRouterPlugin.setup(ctx as never);
      await runHook(
        harness,
        "Fix the payment double-charge race in the checkout ledger",
      );
      expect(posted).toHaveLength(1);
      expect(posted[0].sessionID).toBe("test");
      expect(posted[0].text).toMatch(
        /^\[model-effort-router\] \S+ → \S+ · effort \S+$/,
      );
    } finally {
      if (previousCorePath === undefined) delete process.env.MER_CORE_PATH;
      else process.env.MER_CORE_PATH = previousCorePath;
    }
  });

  it("never blocks admission when the display call fails", async () => {
    process.env.MER_CORE_PATH = fileURLToPath(
      new URL("../../../", import.meta.url),
    );
    try {
      const { harness, ctx } = fakeCtx(async () => {
        throw new Error("display unavailable");
      });
      await ModelEffortRouterPlugin.setup(ctx as never);
      let settled = false;
      await runHook(
        harness,
        "Fix the payment double-charge race in the checkout ledger",
      );
      settled = true;
      expect(settled).toBe(true);
    } finally {
      if (previousCorePath === undefined) delete process.env.MER_CORE_PATH;
      else process.env.MER_CORE_PATH = previousCorePath;
    }
  });
});
