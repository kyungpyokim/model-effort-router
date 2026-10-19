import { Plugin } from "@opencode/plugin";
import { automaticRouteAdvice, routeAdvice, routeReport } from "./route";

function appendAdvice(text: string, advice: Record<string, unknown>) {
  if (advice.route === "no_route")
    return `${text}\n\n${String(advice.message)}`;
  const models = Array.isArray(advice.model_options)
    ? advice.model_options.filter(
        (model): model is string => typeof model === "string",
      )
    : [advice.model as string];
  const alternatives = models.filter((model) => model !== advice.model);
  const other = alternatives.length
    ? ` Other configured options: ${alternatives.join(", ")} (user-selectable, not automatic fallbacks).`
    : "";
  return (
    `${text}\n\n[model-effort-router] ${advice.role} → ${advice.agent} · ${advice.model} · effort ${advice.effort}. ` +
    "Model/effort recommendation only; select these settings in OpenCode as needed. The hook does not change this turn's active settings." +
    other
  );
}

function routingBanner(advice: Record<string, unknown>) {
  if (advice.route === "no_route") return String(advice.message);
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
          undefined,
          undefined,
          event.sessionID,
        );
        if (!advice) return;
        event.prompt.text = appendAdvice(event.prompt.text, advice);
        const banner = routingBanner(advice);
        // Best-effort visible banner. Display failure must never block admission.
        // OpenCode renders synthetic inputs as timeline notices only when
        // `description` is non-empty; `text` alone stays model-context-only.
        await ctx.session
          .synthetic({
            sessionID: event.sessionID,
            text: banner,
            description: banner,
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
              undefined,
              undefined,
              context.sessionID,
            );
          } else {
            advice = await automaticRouteAdvice(
              task,
              session.location.directory,
              undefined,
              undefined,
              context.sessionID,
            );
          }
          return { content: JSON.stringify(advice) };
        },
      });
      editor.add({
        name: "mer_report",
        description:
          "Show which model and effort each routed request used, with token usage, from the router logs. Omit session to include every session.",
        input: {
          type: "object",
          properties: {
            session: { type: "string", minLength: 1, maxLength: 200 },
            limit: { type: "integer", minimum: 1, maximum: 200 },
          },
          additionalProperties: false,
        },
        async execute(rawInput, context) {
          const { session, limit } = rawInput as {
            session?: string;
            limit?: number;
          };
          const info = await ctx.session.get({ sessionID: context.sessionID });
          return {
            content: await routeReport(info.location.directory, session, limit),
          };
        },
      });
    });
  },
});
