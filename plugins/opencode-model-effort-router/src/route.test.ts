import { describe, expect, it } from "bun:test";
import { ModelEffortRouterPlugin } from "./index";
import { routeAdvice } from "./route";

describe("OpenCode plugin tool schema", () => {
  it("offers only efforts supported by the shared router", async () => {
    const plugin = await ModelEffortRouterPlugin({} as never);
    expect((plugin.tool.route_advice.args.effort as { options: string[] }).options)
      .toEqual(["low", "medium", "high", "xhigh"]);
  });
});

describe("routeAdvice", () => {
  it("passes task text as an argument and parses JSON advice", async () => {
    let seen: { file: string; args: string[]; options: unknown } | undefined;
    const advice = await routeAdvice("--host=claude", "plan", "medium", "/work", "/mer",
      ((file, args, options, callback) => {
        seen = { file, args, options };
        callback(null, JSON.stringify({ role: "plan", agent: "reasoning", model: "openai/gpt-5.2", effort: "medium" }), "");
        return {} as ReturnType<typeof Bun.spawn>;
      }) as never);
    expect(seen?.file).toBe("/mer");
    expect(seen?.args).toContain("--host=claude");
    expect(seen?.args).toContain("--host");
    expect(seen?.args.slice(-2)).toEqual(["--", "--host=claude"]);
    expect(advice.model).toBe("openai/gpt-5.2");
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
