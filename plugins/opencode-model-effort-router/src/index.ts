import { Plugin } from "@opencode/plugin";
import { routeAdvice } from "./route";

export default Plugin.define({
  id: "model-effort-router",
  async setup(ctx) {
    await ctx.tool.transform((editor) => {
      editor.add({
        name: "mer",
        description: "Recommend a role, model, and effort for a task using Model Effort Router.",
        input: {
          type: "object",
          properties: {
            task: { type: "string", minLength: 1, maxLength: 20_000 },
            role: { type: "string", enum: ["implementation", "fix", "lint", "test", "plan", "design", "review", "analysis"] },
            effort: { type: "string", enum: ["low", "medium", "high", "xhigh"] },
          },
          required: ["task", "role", "effort"],
          additionalProperties: false,
        },
        async execute({ task, role, effort }, context) {
          const session = await ctx.session.get({ sessionID: context.sessionID });
          const advice = await routeAdvice(task, role, effort, session.location.directory);
          return { content: JSON.stringify(advice) };
        },
      });
    });
  },
});
