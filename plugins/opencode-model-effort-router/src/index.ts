import { Plugin } from "@opencode/plugin";
import { automaticRouteAdvice, routeAdvice } from "./route";

function appendAdvice(text: string, advice: Record<string, unknown>) {
  if (advice.route === "no_route")
    return `${text}\n\n[model-effort-router] No route selected; continue in the main agent.`;
  const models = Array.isArray(advice.model_options)
    ? advice.model_options.filter(
        (model): model is string => typeof model === "string",
      )
    : [advice.model as string];
  const alternatives = models.filter((model) => model !== advice.model);
  const packet =
    advice.role === "review"
      ? "goal, decisions, constraints, actual diff, verification status/results"
      : "task, context, decisions, constraints, relevant_files, expected_result";
  let guidance = `Build a compact Context Packet with ${packet}; label unknowns and send only that packet to the native Subagent. `;
  if (advice.role === "review") {
    guidance +=
      "Mark unrun checks as not run; ask the reviewer to inspect the diff, fix actionable findings, run relevant checks, and report unresolved issues. ";
  }
  const other = alternatives.length
    ? ` Other configured options: ${alternatives.join(", ")} (user-selectable, not automatic fallbacks).`
    : "";
  return (
    `${text}\n\n[model-effort-router] ${advice.role} → ${advice.agent} · ${advice.model} · effort ${advice.effort}. ` +
    `Main: route this task to a native Subagent using OpenCode's model/effort controls. ${guidance}` +
    "Integrate the result and decide whether another worker is needed. The hook advises but does not invoke the Subagent or change this turn's model/settings." +
    other
  );
}

function routingBanner(advice: Record<string, unknown>) {
  if (advice.route === "no_route")
    return "[model-effort-router] No route selected; continue in the main agent.";
  return (
    `[model-effort-router] ${String(advice.role)} → ${String(advice.agent)}` +
    ` · ${String(advice.model)} · effort ${String(advice.effort)}`
  );
}

export default Plugin.define({
  id: "model-effort-router",
  async setup(ctx) {
    await ctx.session.hook("prompt", async (event) => {
      try {
        const session = await ctx.session.get({ sessionID: event.sessionID });
        if (session.parentID) return;
        const advice = await automaticRouteAdvice(
          event.prompt.text,
          session.location.directory,
        );
        if (!advice) return;
        event.prompt.text = appendAdvice(event.prompt.text, advice);
        // Best-effort visible banner. Display failure must never block admission.
        await ctx.session
          .synthetic({
            sessionID: event.sessionID,
            text: routingBanner(advice),
          })
          .catch(() => {});
      } catch (routeError) {
        console.warn(
          "[model-effort-router] automatic routing skipped:",
          routeError,
        );
      }
    });

    type MerToolInput = {
      task: string;
      mode?: string;
      role?: string;
      effort?: string;
    };

    await ctx.tool.transform((editor) => {
      editor.add({
        name: "mer",
        description:
          "Recommend a role, model, and effort. Use automatic mode or omit role/effort to classify the task; provide both for explicit routing.",
        input: {
          type: "object",
          properties: {
            task: { type: "string", minLength: 1, maxLength: 20_000 },
            mode: { type: "string", enum: ["automatic", "explicit"] },
            role: {
              type: "string",
              enum: [
                "implementation",
                "fix",
                "lint",
                "test",
                "plan",
                "design",
                "review",
                "analysis",
              ],
            },
            effort: {
              type: "string",
              enum: ["low", "medium", "high", "xhigh", "max"],
            },
          },
          required: ["task"],
          additionalProperties: false,
        },
        async execute(rawInput, context) {
          const { task, mode, role, effort } = rawInput as MerToolInput;
          const session = await ctx.session.get({
            sessionID: context.sessionID,
          });
          const hasExplicitFields = role !== undefined || effort !== undefined;
          if (mode === "automatic" && hasExplicitFields) {
            throw new Error("automatic mode does not accept role or effort");
          }
          const useExplicit =
            mode === "explicit" || (mode === undefined && hasExplicitFields);
          let advice;
          if (useExplicit) {
            if (role === undefined || effort === undefined) {
              throw new Error("explicit mode requires both role and effort");
            }
            advice = await routeAdvice(
              task,
              role,
              effort,
              session.location.directory,
            );
          } else {
            advice = await automaticRouteAdvice(
              task,
              session.location.directory,
            );
          }
          return { content: JSON.stringify(advice) };
        },
      });
    });
  },
});
