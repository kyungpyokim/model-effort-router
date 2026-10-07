import { tool } from "@opencode-ai/plugin";
import type { Plugin } from "@opencode-ai/plugin";
import { routeAdvice } from "./route";

export const ModelEffortRouterPlugin: Plugin = async () => ({
  tool: {
    route_advice: tool({
      description: "Return a Model Effort Router role, model, and effort recommendation for a task. This does not change the current OpenCode model or launch a worker.",
      args: {
        task: tool.schema.string().min(1).max(20_000),
        role: tool.schema.enum(["implementation", "fix", "lint", "test", "plan", "design", "review", "analysis"]),
        effort: tool.schema.enum(["low", "medium", "high", "xhigh"]),
      },
      async execute({ task, role, effort }, context) {
        const advice = await routeAdvice(task, role, effort, context.directory);
        return JSON.stringify(advice);
      },
    }),
  },
});
