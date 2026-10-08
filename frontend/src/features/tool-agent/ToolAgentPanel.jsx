/**
 * Tool-calling AI agent.
 *
 * Distinct from both neighbours: the Copilot (features/copilot) answers from a
 * fixed statistics block, and Guided Analysis (features/agent) runs a fixed
 * pipeline. Here the model chooses which tools to call, so the interesting part
 * of the response is the trace of what it decided to do.
 *
 * The route is synchronous - one POST, everything at the end - so there is no
 * progress to report while it runs and none is invented. The waiting state says
 * what is happening and nothing more; the trace appears only once it is real.
 *
 * Actions never run on their own. With "Allow actions" on, the agent can only
 * propose cleaning or training: the run stops and this panel asks the user to
 * approve or decline. Approving sends nothing but yes/no; the server runs the
 * call it stored. The proposal is shown next to the user's own question so it is
 * easy to see when it is not something they asked for.
 *
 * Every tool result is dataset content that passed through the server's
 * sanitiser, which means it is untrusted by definition. It is rendered as text
 * (never as HTML, never through the Markdown renderer) so that a cell which
 * looks like markup stays a visible value rather than becoming one.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  AlertTriangle, Ban, Check, ChevronRight, CircleAlert, EyeOff, KeyRound,
  Scissors, Send, Sparkles, TriangleAlert, Wrench,
} from "lucide-react";

import { normalizeError } from "../../api/client.js";
import { copilot as copilotApi, toolAgent as toolAgentApi } from "../../api/endpoints.js";
import {
  Alert, Badge, Button, Card, CardBody, CardHeader, EmptyState, Input, Toggle,
} from "../../components/ui/index.jsx";
import Markdown from "../copilot/Markdown.jsx";

/* ----------------------------------------------------------- presentation */

/**
 * Tool names in plain words.
 *
 * `describe` receives the arguments the model sent, which are not validated -
 * a hallucinated or missing field has to degrade to the generic phrasing rather
 * than render "Profiling column undefined".
 */
const TOOL_LABELS = {
  get_dataset_overview: { verb: "Reading the dataset overview" },
  profile_column: {
    verb: "Profiling a column",
    describe: (args) =>
      typeof args?.column === "string" && args.column
        ? `Profiling the column ${args.column}`
        : null,
  },
  get_correlations: { verb: "Looking for correlations" },
  assess_quality: { verb: "Assessing data quality" },
  run_query: {
    verb: "Running a query",
    describe: (args) => {
      const measure = typeof args?.measure === "string" ? args.measure : null;
      const dimension = typeof args?.dimension === "string" ? args.dimension : null;
      if (measure && dimension) return `Totalling ${measure} by ${dimension}`;
      if (measure) return `Querying ${measure}`;
      return null;
    },
  },
  recommend_cleaning: { verb: "Checking what cleaning is needed" },
  get_model_results: { verb: "Reading the model results" },
  explain_model: { verb: "Explaining the model" },
  apply_cleaning: { verb: "Applying the cleaning plan" },
  train_model: {
    verb: "Training a model",
    describe: (args) =>
      typeof args?.target_column === "string" && args.target_column
        ? `Training a model to predict ${args.target_column}`
        : null,
  },
};

function describeTool(step) {
  const entry = TOOL_LABELS[step.tool_name];
  if (!entry) return step.tool_name || "Unknown tool";
  return entry.describe?.(step.arguments) || entry.verb;
}

/** Step statuses, matching the backend's `agent_steps.status` values. */
const STEP_STATUS = {
  ok: { Icon: Check, label: "Done", tone: "success", ring: "border-success bg-success-soft", text: "text-success" },
  invalid_arguments: { Icon: CircleAlert, label: "Invalid arguments", tone: "warning", ring: "border-warning bg-warning-soft", text: "text-warning" },
  tool_error: { Icon: TriangleAlert, label: "Failed", tone: "danger", ring: "border-danger bg-danger-soft", text: "text-danger" },
  blocked_action: { Icon: Ban, label: "Blocked", tone: "neutral", ring: "border-line bg-canvas", text: "text-subtle" },
  rejected_unknown_tool: { Icon: CircleAlert, label: "Unknown tool", tone: "warning", ring: "border-warning bg-warning-soft", text: "text-warning" },
  pending_confirmation: { Icon: CircleAlert, label: "Waiting for approval", tone: "warning", ring: "border-warning bg-warning-soft", text: "text-warning" },
  rejected_by_user: { Icon: Ban, label: "Declined", tone: "neutral", ring: "border-line bg-canvas", text: "text-subtle" },
  expired: { Icon: Ban, label: "Expired", tone: "neutral", ring: "border-line bg-canvas", text: "text-subtle" },
};

const FALLBACK_STATUS = {
  Icon: Wrench, label: "Unknown", tone: "neutral", ring: "border-line bg-canvas", text: "text-subtle",
};

/** Run outcomes. `step_limit` is a real outcome, not an error. */
const RUN_OUTCOME = {
  completed: { tone: "success", label: "Completed" },
  step_limit: { tone: "warning", label: "Stopped at the step limit" },
  error: { tone: "danger", label: "Failed" },
  awaiting_confirmation: { tone: "warning", label: "Waiting for your approval" },
  running: { tone: "neutral", label: "Running" },
};

function formatDuration(seconds) {
  if (seconds == null) return null;
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  return `${seconds.toFixed(seconds < 10 ? 2 : 1)}s`;
}

/* ------------------------------------------------------------------ panel */

export default function ToolAgentPanel({ datasetId, dataset }) {
  const [question, setQuestion] = useState("");
  const [allowActions, setAllowActions] = useState(false);
  // The server's answer to the latest decision, shown in place of the ask
  // response it follows. Cleared whenever a new question is asked.
  const [decision, setDecision] = useState(null);
  const queryClient = useQueryClient();

  // The agent and the Copilot are gated by the same GROQ_API_KEY, and this
  // endpoint already derives its questions from the dataset's real columns, so
  // it answers both "is AI configured" and "what can this dataset be asked".
  const suggestions = useQuery({
    queryKey: ["copilot-suggestions", datasetId],
    queryFn: () => copilotApi.suggestions(datasetId),
  });

  const ask = useMutation({
    mutationFn: (text) => toolAgentApi.ask(datasetId, { question: text, allowActions }),
    onMutate: () => {
      setDecision(null);
      decide.reset();
    },
  });

  const decide = useMutation({
    mutationFn: ({ runId, approve }) => toolAgentApi.decide(datasetId, runId, approve),
    onSuccess: (result, { approve }) => {
      setDecision(result);
      if (!approve) return;
      // Approved actions change the dataset or add a model version, so every
      // cached view of it is now stale (same set Guided Analysis refreshes).
      [
        "dataset", "datasets", "datasets-status", "preview", "columns", "quality",
        "clean-plan", "dashboard", "model-history", "explain", "train-options", "user-summary",
      ].forEach((key) => queryClient.invalidateQueries({ queryKey: [key] }));
    },
  });

  const configured = suggestions.data?.copilot_enabled;
  const run = decision && decision.id === ask.data?.id ? decision : ask.data;
  const error = ask.isError ? normalizeError(ask.error) : null;
  const decideError = decide.isError ? normalizeError(decide.error) : null;

  function submit(event) {
    event?.preventDefault();
    const text = question.trim();
    if (!text || ask.isPending) return;
    ask.mutate(text);
  }

  function runSuggested(text) {
    setQuestion(text);
    ask.mutate(text);
  }

  return (
    <div className="space-y-4">
      {!configured && !suggestions.isLoading && (
        <Alert tone="warning" title="The AI agent is not configured">
          <p>
            This server has no <code className="rounded bg-canvas px-1">GROQ_API_KEY</code> set, so
            the agent cannot run. Profiling, cleaning, analytics, models, explainability and reports
            all work without it.
          </p>
          <p className="mt-1.5 flex items-center gap-1.5 text-sm">
            <KeyRound size={12} aria-hidden="true" />
            Add the key to the backend environment and restart to enable it.
          </p>
        </Alert>
      )}

      <Card>
        <CardHeader
          title="Ask the agent"
          description="The agent picks its own tools, runs them against this dataset, and shows every step it took"
        />
        <CardBody className="space-y-4">
          <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row">
            <Input
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder={
                configured ? "Ask a question about this dataset" : "Agent not configured on this server"
              }
              aria-label="Ask the agent a question"
              disabled={!configured || ask.isPending}
              maxLength={2000}
            />
            <Button
              type="submit"
              icon={Send}
              disabled={!configured || !question.trim()}
              loading={ask.isPending}
              className="sm:w-auto"
            >
              Ask
            </Button>
          </form>

          <Toggle
            checked={allowActions}
            onChange={setAllowActions}
            disabled={!configured || ask.isPending}
            label="Let the agent propose changes"
            description={
              allowActions
                ? "The agent may propose applying the recommended cleaning or training a model. Nothing runs until you approve it. Cleaning keeps your original upload and can be reverted; training adds a new model version."
                : "Read-only. The agent can analyse but cannot change the data or train anything - those tools are not offered to it at all."
            }
          />

          {suggestions.data?.questions?.length > 0 && !run && !ask.isPending && (
            <div>
              <p className="mb-1.5 text-2xs font-medium uppercase tracking-wide text-subtle">
                Suggested questions
              </p>
              <div className="flex flex-wrap gap-1.5">
                {suggestions.data.questions.slice(0, 6).map((suggested) => (
                  <button
                    key={suggested}
                    type="button"
                    disabled={!configured}
                    onClick={() => runSuggested(suggested)}
                    className="rounded-full border border-line bg-surface px-2.5 py-1 text-left text-xs
                               text-muted transition-colors hover:border-accent hover:text-accent
                               disabled:cursor-not-allowed disabled:opacity-50
                               focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50"
                  >
                    {suggested}
                  </button>
                ))}
              </div>
            </div>
          )}
        </CardBody>
      </Card>

      {ask.isPending && <ThinkingState allowActions={allowActions} />}

      {error && !ask.isPending && <AskError error={error} onRetry={() => submit()} />}

      {!run && !ask.isPending && !error && (
        <EmptyState
          icon={Sparkles}
          title="Ask a question and watch what it does"
          description="Unlike the Copilot, this agent decides which tools to run - profiling a column, querying totals, checking quality - and reports each step with what it returned."
        />
      )}

      {run && !ask.isPending && (
        <RunResult
          run={run}
          dataset={dataset}
          deciding={decide.isPending}
          decideError={decideError}
          onDecide={(approve) => decide.mutate({ runId: run.id, approve })}
        />
      )}
    </div>
  );
}

/* ------------------------------------------------------------- sub-views */

/**
 * Waiting state.
 *
 * Deliberately not a progress bar: the request is one synchronous POST, so the
 * client knows nothing about how far along it is, and a moving bar would be
 * fiction. The pulsing dots are the same idle indicator the Copilot uses.
 */
function ThinkingState({ allowActions }) {
  return (
    <Card>
      <CardBody>
        <div className="flex items-start gap-3" role="status" aria-live="polite">
          <span
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent"
            aria-hidden="true"
          >
            <Sparkles size={13} />
          </span>
          <div className="min-w-0">
            <p className="flex items-center gap-2 text-base font-medium text-ink">
              The agent is working
              <span className="flex gap-1" aria-hidden="true">
                {[0, 1, 2].map((index) => (
                  <span
                    key={index}
                    className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent"
                    style={{ animationDelay: `${index * 150}ms` }}
                  />
                ))}
              </span>
            </p>
            <p className="mt-0.5 text-sm text-muted">
              It runs to completion and returns everything at once, so there is nothing to show
              until it finishes.{" "}
              {allowActions
                ? "If the agent wants to change something it will stop and ask you first. This is usually a few seconds."
                : "This is usually a few seconds."}
            </p>
          </div>
        </div>
      </CardBody>
    </Card>
  );
}

/** Errors the agent route returns, each said plainly rather than as a code. */
function AskError({ error, onRetry }) {
  if (error.status === 429) {
    return (
      <Alert tone="warning" title="Hourly limit reached">
        <p>{error.message}</p>
        <p className="mt-1 text-sm">
          Agent runs are capped per hour because each one makes several model calls. Try again
          later, or use the Copilot for a single question.
        </p>
      </Alert>
    );
  }

  if (error.status === 503) {
    return (
      <Alert tone="warning" title="The AI agent is not configured">
        <p>{error.message}</p>
      </Alert>
    );
  }

  return (
    <Alert
      tone="danger"
      title="That question could not be answered"
      action={
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Retry
        </Button>
      }
    >
      <p>{error.message}</p>
    </Alert>
  );
}

function RunResult({ run, dataset, onDecide, deciding, decideError }) {
  const outcome = RUN_OUTCOME[run.status] || RUN_OUTCOME.running;
  const steps = run.steps || [];
  const tokens = (run.total_prompt_tokens || 0) + (run.total_completion_tokens || 0);

  return (
    <div className="space-y-4">
      {run.status === "step_limit" && (
        <Alert tone="warning" title="The agent hit its step limit">
          It ran out of allowed tool calls before reaching an answer. Everything it did get to is
          below. A narrower question usually finishes well inside the limit.
        </Alert>
      )}

      {run.status === "awaiting_confirmation" && run.pending_action && (
        <ConfirmationCard
          run={run}
          onDecide={onDecide}
          deciding={deciding}
          decideError={decideError}
        />
      )}

      {/* Trace */}
      <Card>
        <CardHeader
          title="What the agent did"
          description={
            steps.length
              ? `${steps.length} tool ${steps.length === 1 ? "call" : "calls"} against ${dataset?.filename || "this dataset"}`
              : "No tools were called - it answered directly"
          }
          actions={<Badge tone={outcome.tone}>{outcome.label}</Badge>}
        />
        <CardBody>
          {steps.length === 0 ? (
            <p className="text-sm text-muted">
              The agent answered from the question alone without calling any tool.
            </p>
          ) : (
            <ol className="space-y-0">
              {steps.map((step, index) => (
                <StepRow
                  key={step.step_number ?? index}
                  step={step}
                  isLast={index === steps.length - 1}
                />
              ))}
            </ol>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line pt-3 text-2xs text-subtle">
            {run.duration_seconds != null && (
              <span className="tabular-nums">Total {formatDuration(run.duration_seconds)}</span>
            )}
            {tokens > 0 && <span className="tabular-nums">{tokens.toLocaleString()} tokens</span>}
            <span>Run #{run.id}</span>
            {run.allow_actions && <span>Actions were allowed</span>}
          </div>
        </CardBody>
      </Card>

      {/* Answer */}
      {run.answer && (
        <Card>
          <CardHeader title="Answer" />
          <CardBody>
            <Markdown content={run.answer} />
          </CardBody>
        </Card>
      )}

      {run.action_result != null && (
        <Card>
          <CardHeader
            title="What the action returned"
            description="The tool's own result, exactly as it ran"
          />
          <CardBody>
            {/* Dataset-derived content: rendered as text, never as markup. */}
            <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-md border border-line bg-canvas p-2 text-2xs text-muted">
              {typeof run.action_result === "string"
                ? run.action_result
                : JSON.stringify(run.action_result, null, 2)}
            </pre>
          </CardBody>
        </Card>
      )}
    </div>
  );
}

/**
 * The agent's request to change something, waiting for a yes or no.
 *
 * Decline is the default focus so a stray Enter cannot approve. The warning for
 * a redacted value is a hint, not detection: the sanitiser only catches
 * phrasings it knows, so its absence says nothing about whether the proposal is
 * what the user wanted. That is why the user's own question sits right here.
 */
function ConfirmationCard({ run, onDecide, deciding, decideError }) {
  const pending = run.pending_action;
  const flagged = (run.steps || []).some((step) => step.redacted);
  const args =
    pending.arguments && Object.keys(pending.arguments).length ? pending.arguments : null;

  return (
    <Card>
      <CardHeader
        title="The agent is asking permission"
        description="Nothing has been changed yet"
        actions={<Badge tone="warning">Needs your decision</Badge>}
      />
      <CardBody className="space-y-3">
        <p className="text-sm text-ink">
          <span className="font-medium">Proposed: </span>
          {describeTool({ tool_name: pending.tool_name, arguments: pending.arguments })}
        </p>

        {args && (
          <pre className="overflow-x-auto rounded-md border border-line bg-canvas p-2 text-2xs text-muted">
            <code>{JSON.stringify(args, null, 2)}</code>
          </pre>
        )}

        <p className="text-sm text-muted">
          <span className="font-medium text-ink">You asked: </span>
          {run.question}
        </p>

        {flagged && (
          <Alert tone="warning" title="A value in your data looked like an instruction">
            During this run a value in the data was replaced because it resembled an instruction
            to the agent. Approve only if this change is something you asked for.
          </Alert>
        )}

        <p className="text-xs text-subtle">
          Approve only if this is what you wanted. Training can take a few minutes.
        </p>

        {decideError && (
          <Alert tone="danger" title="That decision could not be applied">
            <p>{decideError.message}</p>
          </Alert>
        )}

        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => onDecide(false)} disabled={deciding} autoFocus>
            Decline
          </Button>
          <Button icon={Check} onClick={() => onDecide(true)} loading={deciding}>
            Approve
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}

/**
 * One tool call, expandable.
 *
 * A plain <button> with aria-expanded rather than <details>/<summary>, to match
 * the focus-ring treatment used elsewhere and keep the disclosure state in
 * React where the chevron rotation can follow it.
 */
function StepRow({ step, isLast }) {
  const [open, setOpen] = useState(false);
  const meta = STEP_STATUS[step.status] || FALLBACK_STATUS;
  const duration = formatDuration(step.duration_seconds);
  const hasDetail = step.arguments != null || step.result_summary;

  return (
    <li className="relative flex gap-3 pb-3 last:pb-0">
      {!isLast && <span className="absolute left-[13px] top-7 h-full w-px bg-line" aria-hidden="true" />}

      <span
        className={clsx(
          "relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border",
          meta.ring,
        )}
      >
        <meta.Icon size={13} className={meta.text} aria-hidden="true" />
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <p className="text-base font-medium text-ink">{describeTool(step)}</p>
          <Badge tone={meta.tone}>{meta.label}</Badge>
          {duration && <span className="text-xs tabular-nums text-subtle">{duration}</span>}
          {step.redacted && (
            <Badge tone="warning" icon={EyeOff}>
              Redacted
            </Badge>
          )}
          {step.truncated && (
            <Badge tone="neutral" icon={Scissors}>
              Shortened
            </Badge>
          )}
        </div>

        {step.redacted && (
          <p className="mt-1 flex items-start gap-1.5 text-xs text-warning">
            <AlertTriangle size={11} className="mt-0.5 shrink-0" aria-hidden="true" />
            A value in this result looked like an instruction and was replaced before the agent saw
            it.
          </p>
        )}

        {hasDetail && (
          <>
            <button
              type="button"
              onClick={() => setOpen((previous) => !previous)}
              aria-expanded={open}
              className="mt-1 flex items-center gap-1 rounded text-xs text-subtle transition-colors
                         hover:text-ink focus-visible:outline-none focus-visible:ring-2
                         focus-visible:ring-accent/50"
            >
              <ChevronRight
                size={11}
                aria-hidden="true"
                className={clsx("transition-transform", open && "rotate-90")}
              />
              {open ? "Hide detail" : "Show detail"}
            </button>

            {open && (
              <div className="mt-2 space-y-2">
                {step.arguments != null && (
                  <div>
                    <p className="mb-1 text-2xs font-medium uppercase tracking-wide text-subtle">
                      Arguments the model sent
                    </p>
                    {/* Pre-validation, so this is exactly what the model asked
                        for - including fields that were rejected. */}
                    <pre className="overflow-x-auto rounded-md border border-line bg-canvas p-2 text-2xs text-muted">
                      <code>{JSON.stringify(step.arguments, null, 2)}</code>
                    </pre>
                  </div>
                )}
                {step.result_summary && (
                  <div>
                    <p className="mb-1 text-2xs font-medium uppercase tracking-wide text-subtle">
                      Result {step.truncated && "(shortened)"}
                    </p>
                    {/* Dataset content: rendered as text, never as markup. */}
                    <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-md border border-line bg-canvas p-2 text-2xs text-muted">
                      {step.result_summary}
                    </pre>
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </li>
  );
}
