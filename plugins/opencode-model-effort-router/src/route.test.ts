import { describe, expect, it } from "bun:test";
import { fileURLToPath } from "node:url";
import ModelEffortRouterPlugin from "./index";
import { automaticRouteAdvice, routeAdvice } from "./route";

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
          transform: async (register) =>
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
      ((file, args, options, callback) => {
        seen = { file, args, options };
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
        return {} as ReturnType<typeof Bun.spawn>;
      }) as never,
    );
    expect(seen?.file).toBe("/mer");
    expect(seen?.args).toContain("--host=claude");
    expect(seen?.args).toContain("--host");
    expect(seen?.args.slice(-2)).toEqual(["--", "--host=claude"]);
    expect(advice.model).toBe("opencode/nemotron-3-ultra-free");
  });

  it("passes automatic classification through the existing CLI path", async () => {
    let seen: { file: string; args: string[] } | undefined;
    const advice = await automaticRouteAdvice(
      "Fix auth and payment boundaries",
      "/work",
      "/mer",
      ((file, args, _options, callback) => {
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
        return {} as ReturnType<typeof Bun.spawn>;
      }) as never,
    );
    expect(seen?.file).toBe("/mer");
    expect(seen?.args).toContain("--automatic");
    expect(seen?.args.slice(-2)).toEqual([
      "--",
      "Fix auth and payment boundaries",
    ]);
    expect(advice.effort).toBe("high");
  });

  it("surfaces subprocess failures and malformed output", async () => {
    const failure = ((_, __, ___, callback) => {
      callback(new Error("exit 2"), "", "route rejected");
      return {};
    }) as never;
    await expect(
      routeAdvice("task", "plan", "medium", "/work", "/mer", failure),
    ).rejects.toThrow("route rejected");
    const malformed = ((_, __, ___, callback) => {
      callback(null, "not json", "");
      return {};
    }) as never;
    await expect(
      routeAdvice("task", "plan", "medium", "/work", "/mer", malformed),
    ).rejects.toThrow("invalid JSON");
  });
});
