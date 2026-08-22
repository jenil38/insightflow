/**
 * AI Copilot.
 *
 * History is loaded from and written to the database, so a conversation
 * survives a page reload (the original kept messages in component state only).
 * When GROQ_API_KEY is not configured the panel says so plainly instead of
 * offering an input that always errors.
 */
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import clsx from "clsx";
import {
  Check, Copy, KeyRound, MessageSquare, RotateCcw, Send, Sparkles, Trash2, User,
} from "lucide-react";

import { errorMessage, normalizeError } from "../../api/client.js";
import { copilot as copilotApi } from "../../api/endpoints.js";
import {
  Alert, Badge, Button, Card, CardBody, ConfirmDialog, EmptyState, IconButton,
  Input, Skeleton,
} from "../../components/ui/index.jsx";
import { formatDate } from "../../lib/format.js";
import Markdown from "./Markdown.jsx";

export default function CopilotPanel({ datasetId, dataset }) {
  const queryClient = useQueryClient();
  const [question, setQuestion] = useState("");
  const [confirmClear, setConfirmClear] = useState(false);
  const [copiedId, setCopiedId] = useState(null);
  const endRef = useRef(null);

  const suggestions = useQuery({
    queryKey: ["copilot-suggestions", datasetId],
    queryFn: () => copilotApi.suggestions(datasetId),
  });

  const history = useQuery({
    queryKey: ["copilot-history", datasetId],
    queryFn: () => copilotApi.history(datasetId),
  });

  const ask = useMutation({
    mutationFn: (text) => copilotApi.ask(datasetId, text),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["copilot-history", datasetId] });
      queryClient.invalidateQueries({ queryKey: ["dataset", String(datasetId)] });
    },
    onError: (error) => {
      // The question is persisted before the provider call, so refresh either way.
      queryClient.invalidateQueries({ queryKey: ["copilot-history", datasetId] });
      toast.error(errorMessage(error, "The Copilot could not answer."));
    },
  });

  const clear = useMutation({
    mutationFn: () => copilotApi.clear(datasetId),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["copilot-history", datasetId] });
      setConfirmClear(false);
      toast.success(result.deleted ? `Cleared ${result.deleted} message(s)` : "Nothing to clear");
    },
    onError: (error) => toast.error(errorMessage(error, "Could not clear the conversation.")),
  });

  const messages = history.data || [];
  const enabled = suggestions.data?.copilot_enabled;

  // Keep the newest message in view as the conversation grows.
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, ask.isPending]);

  function submit(event) {
    event?.preventDefault();
    const text = question.trim();
    if (!text || ask.isPending) return;
    setQuestion("");
    ask.mutate(text);
  }

  async function copy(message) {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopiedId(message.id);
      setTimeout(() => setCopiedId(null), 1500);
    } catch {
      toast.error("Could not copy to the clipboard.");
    }
  }

  const lastUserMessage = [...messages].reverse().find((m) => m.role === "user");
  const askError = ask.isError ? normalizeError(ask.error) : null;

  return (
    <div className="space-y-4">
      {!enabled && !suggestions.isLoading && (
        <Alert tone="warning" title="The AI Copilot is not configured">
          <p>
            This server has no <code className="rounded bg-canvas px-1">GROQ_API_KEY</code> set, so the
            Copilot cannot answer questions. Every other feature - profiling, cleaning, analytics,
            models, explainability, and reports - works without it.
          </p>
          <p className="mt-1.5 flex items-center gap-1.5 text-sm">
            <KeyRound size={12} aria-hidden="true" />
            Add the key to the backend environment and restart to enable it.
          </p>
        </Alert>
      )}

      <Card className="flex h-[32rem] flex-col">
        {/* Context header - makes it explicit what the Copilot can see. */}
        <div className="flex shrink-0 items-center gap-2 border-b border-line px-4 py-2.5">
          <Sparkles size={14} className="shrink-0 text-accent" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-ink">
              Grounded on {dataset?.filename}
            </p>
            <p className="text-2xs text-subtle">
              Answers use computed statistics for this dataset only
              {dataset?.has_cleaned_version ? ", from the cleaned data" : ""}.
            </p>
          </div>
          {messages.length > 0 && (
            <IconButton
              icon={Trash2}
              label="Clear conversation"
              size="sm"
              onClick={() => setConfirmClear(true)}
            />
          )}
        </div>

        {/* Transcript */}
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
          {history.isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-16 w-3/4" />
              <Skeleton className="ml-auto h-10 w-1/2" />
            </div>
          ) : messages.length === 0 ? (
            <EmptyState
              icon={MessageSquare}
              title="Ask about this dataset"
              description="The Copilot answers from computed statistics - column types, distributions, correlations, and data-quality findings. It will say so when something cannot be determined."
            />
          ) : (
            messages.map((message) => (
              <div
                key={message.id}
                className={clsx("flex gap-2.5", message.role === "user" && "flex-row-reverse")}
              >
                <span
                  aria-hidden="true"
                  className={clsx(
                    "flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
                    message.role === "user" ? "bg-canvas text-muted" : "bg-accent-soft text-accent",
                  )}
                >
                  {message.role === "user" ? <User size={13} /> : <Sparkles size={13} />}
                </span>

                <div className={clsx("group min-w-0 max-w-[85%]", message.role === "user" && "text-right")}>
                  <div
                    className={clsx(
                      "inline-block rounded-lg px-3 py-2 text-left text-base",
                      message.role === "user"
                        ? "bg-accent text-accent-contrast"
                        : "border border-line bg-canvas text-ink",
                    )}
                  >
                    {message.role === "assistant" ? (
                      <Markdown content={message.content} />
                    ) : (
                      <p className="whitespace-pre-wrap">{message.content}</p>
                    )}
                  </div>

                  <div
                    className={clsx(
                      "mt-0.5 flex items-center gap-2 text-2xs text-subtle",
                      message.role === "user" && "justify-end",
                    )}
                  >
                    <span>{formatDate(message.created_at, { withTime: true })}</span>
                    {message.role === "assistant" && (
                      <button
                        type="button"
                        onClick={() => copy(message)}
                        className="flex items-center gap-1 opacity-0 transition-opacity hover:text-ink
                                   focus-visible:opacity-100 group-hover:opacity-100"
                      >
                        {copiedId === message.id ? (
                          <><Check size={10} aria-hidden="true" /> Copied</>
                        ) : (
                          <><Copy size={10} aria-hidden="true" /> Copy</>
                        )}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))
          )}

          {ask.isPending && (
            <div className="flex gap-2.5">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent" aria-hidden="true">
                <Sparkles size={13} />
              </span>
              <div
                className="flex items-center gap-1 surface-inset rounded-lg px-3 py-3"
                role="status"
                aria-live="polite"
              >
                <span className="sr-only">The Copilot is thinking</span>
                {[0, 1, 2].map((index) => (
                  <span
                    key={index}
                    className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent"
                    style={{ animationDelay: `${index * 150}ms` }}
                    aria-hidden="true"
                  />
                ))}
              </div>
            </div>
          )}

          {askError && (
            <Alert tone="danger" title="That question could not be answered">
              <p>{askError.message}</p>
              {lastUserMessage && (
                <Button
                  variant="secondary"
                  size="sm"
                  icon={RotateCcw}
                  className="mt-2"
                  onClick={() => ask.mutate(lastUserMessage.content)}
                >
                  Retry
                </Button>
              )}
            </Alert>
          )}

          <div ref={endRef} />
        </div>

        {/* Suggestions */}
        {messages.length === 0 && suggestions.data?.questions?.length > 0 && (
          <div className="shrink-0 border-t border-line px-4 py-2.5">
            <p className="mb-1.5 text-2xs font-medium uppercase tracking-wide text-subtle">
              Suggested questions
            </p>
            <div className="flex flex-wrap gap-1.5">
              {suggestions.data.questions.map((suggested) => (
                <button
                  key={suggested}
                  type="button"
                  disabled={!enabled}
                  onClick={() => { setQuestion(suggested); ask.mutate(suggested); }}
                  className="rounded-full border border-line bg-surface px-2.5 py-1 text-xs text-muted
                             transition-colors hover:border-accent hover:text-accent
                             disabled:cursor-not-allowed disabled:opacity-50
                             focus-visible:ring-2 focus-visible:ring-accent/50"
                >
                  {suggested}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Composer */}
        <form onSubmit={submit} className="flex shrink-0 gap-2 border-t border-line px-4 py-3">
          <Input
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder={enabled ? "Ask about this dataset" : "Copilot not configured on this server"}
            aria-label="Ask the Copilot a question"
            disabled={!enabled || ask.isPending}
            maxLength={2000}
          />
          <Button
            type="submit"
            icon={Send}
            disabled={!enabled || !question.trim()}
            loading={ask.isPending}
          >
            <span className="hidden sm:inline">Ask</span>
          </Button>
        </form>
      </Card>

      <p className="text-xs text-subtle">
        The Copilot sees summary statistics and a handful of sample rows, never the full dataset.
        It is instructed not to invent figures, and to say when something cannot be determined from
        the available statistics.
      </p>

      <ConfirmDialog
        open={confirmClear}
        onClose={() => setConfirmClear(false)}
        onConfirm={() => clear.mutate()}
        loading={clear.isPending}
        title="Clear this conversation?"
        message="Every message for this dataset will be deleted. This cannot be undone."
        confirmLabel="Clear conversation"
      />
    </div>
  );
}
