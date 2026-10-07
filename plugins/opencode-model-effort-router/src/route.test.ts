import { describe, expect, it } from "bun:test";
import { fileURLToPath } from "node:url";
import ModelEffortRouterPlugin from "./index";
import { routeAdvice } from "./route";

describe("OpenCode plugin tool schema", () => {
  it("registers the visible mer tool with supported roles and efforts", async () => {
    const registered: {
      name: string;
      input: { properties: Record<string, { enum?: string[] }> };
      execute: (input: { task: string; role: string; effort: string }, context: unknown) => Promise<{ content?: string }>;
    }[] = [];
    const previousCorePath = process.env.MER_CORE_PATH;
    process.env.MER_CORE_PATH = fileURLToPath(new URL("../../../", import.meta.url));
    try {
      await ModelEffortRouterPlugin.setup({
        tool: {
          transform: async (register) => register({ add: (definition) => registered.push(definition as never) }),
        },
        session: { get: async () => ({ location: { directory: process.cwd() } }) },
      } as never);
      expect(registered.map(({ name }) => name)).toEqual(["mer"]);
      expect(registered[0].input.properties.role.enum)
        .toEqual(["implementation", "fix", "lint", "test", "plan", "design", "review", "analysis"]);
      expect(registered[0].input.properties.effort.enum).toEqual(["low", "medium", "high", "xhigh", "max"]);
      const result = await registered[0].execute(
        { task: "Add an OpenCode plugin", role: "plan", effort: "medium" },
        { sessionID: "test" },
      );
      expect(JSON.parse(result.content ?? "{}").role).toBe("plan");
    } finally {
      if (previousCorePath === undefined) delete process.env.MER_CORE_PATH;
      else process.env.MER_CORE_PATH = previousCorePath;
    }
  });
});

describe("routeAdvice", () => {
  it("passes task text as an argument and parses JSON advice", async () => {
    let seen: { file: string; args: string[]; options: unknown } | undefined;
    const advice = await routeAdvice("--host=claude", "plan", "medium", "/work", "/mer",
      ((file, args, options, callback) => {
        seen = { file, args, options };
        callback(null, JSON.stringify({ role: "plan", agent: "reasoning", model: "opencode/nemotron-3-ultra-free", effort: "medium" }), "");
        return {} as ReturnType<typeof Bun.spawn>;
      }) as never);
    expect(seen?.file).toBe("/mer");
    expect(seen?.args).toContain("--host=claude");
    expect(seen?.args).toContain("--host");
    expect(seen?.args.slice(-2)).toEqual(["--", "--host=claude"]);
    expect(advice.model).toBe("opencode/nemotron-3-ultra-free");
  });

  it("surfaces subprocess failures and malformed output", async () => {
    const failure = ((_, __, ___, callback) => {
      callback(new Error("exit 2"), "", "route rejected");
      return {};
    }) as never;
    await expect(routeAdvice("task", "plan", "medium", "/work", "/mer", failure)).rejects.toThrow("route rejected");
    const malformed = ((_, __, ___, callback) => {
      callback(null, "not json", "");
      return {};
    }) as never;
    await expect(routeAdvice("task", "plan", "medium", "/work", "/mer", malformed)).rejects.toThrow("invalid JSON");
  });
});
