import { Plugin } from "@opencode/plugin";
import { automaticRouteAdvice, routeAdvice } from "./route";

function appendAdvice(text: string, advice: Record<string, unknown>) {
  const models = Array.isArray(advice.model_options)
    ? advice.model_options.filter((model): model is string => typeof model === "string")
    : [advice.model as string];
  const alternatives = models.filter((model) => model !== advice.model);
  const packet = advice.role === "review"
    ? "goal, decisions, constraints, actual diff, verification status/results"
    : "task, context, decisions, constraints, relevant_files, expected_result";
  let guidance = `Build a compact Context Packet with ${packet}; label unknowns and send only that packet to the native Subagent. `;
  if (advice.role === "review") {
    guidance += "Mark unrun checks as not run; ask the reviewer to inspect the diff, fix actionable findings, run relevant checks, and report unresolved issues. ";
  }
  const modelAdvice = `recommended model: ${advice.model}` +
    (alternatives.length ? `; other configured options: ${alternatives.join(", ")} (user-selectable, not automatic fallbacks)` : "");
  return `${text}\n\n[model-effort-router] Main: route this task to a native Subagent using OpenCode's model/effort controls. ` +
    `Role: ${advice.role}; worker lane: ${advice.agent}; ${modelAdvice}; effort: ${advice.effort}. ${guidance}` +
    "Integrate the result and decide whether another worker is needed. The hook advises but does not invoke the Subagent or change this turn's model/settings.";
}

export default Plugin.define({
  id: "model-effort-router",
  async setup(ctx) {
    await ctx.session.hook("prompt", async (event) => {
      try {
        const session = await ctx.session.get({ sessionID: event.sessionID });
        if (session.parentID) return;
        const advice = await automaticRouteAdvice(event.prompt.text, session.location.directory);
        if (advice) event.prompt.text = appendAdvice(event.prompt.text, advice);
      } catch {
        console.warn("[model-effort-router] automatic routing skipped");
      }
    });

    await ctx.tool.transform((editor) => {
      editor.add({
        name: "mer",
        description: "Recommend a role, model, and effort for a task using Model Effort Router.",
        input: {
          type: "object",
          properties: {
            task: { type: "string", minLength: 1, maxLength: 20_000 },
            role: { type: "string", enum: ["implementation", "fix", "lint", "test", "plan", "design", "review", "analysis"] },
            effort: { type: "string", enum: ["low", "medium", "high", "xhigh", "max"] },
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
