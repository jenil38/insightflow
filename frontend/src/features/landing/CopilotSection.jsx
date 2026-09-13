/**
 * AI Copilot section.
 *
 * Shows the grounding contract rather than a generic chat mockup: the answer
 * cites the columns it used, and the panel alongside spells out what is and
 * isn't sent to the model. The prompt-injection line is real behaviour: cell
 * values that look like instructions are redacted before the prompt is built.
 */
import { useRef } from "react";
import { motion, useInView } from "framer-motion";
import { Ban, Database, Lock, MessageSquare, Sparkles } from "lucide-react";

import { Reveal } from "../../components/scroll/index.jsx";

const GUARANTEES = [
  {
    icon: Database,
    title: "Grounded in computed statistics",
    body: "Column types, ranges, correlations and quality scores, not a dump of your rows.",
  },
  {
    icon: Lock,
    title: "Minimal data leaves the server",
    body: "Five sample rows, truncated per cell. Everything else is aggregate.",
  },
  {
    icon: Ban,
    title: "Prompt-injection resistant",
    body: "Cell values resembling instructions are redacted and the sample is fenced as untrusted.",
  },
  {
    icon: Sparkles,
    title: "Says when it cannot answer",
    body: "No invented numbers. If the statistics don't cover it, it says so.",
  },
];

const CONVERSATION = [
  { role: "user", text: "Which columns have the most missing values?" },
  {
    role: "assistant",
    text:
      "Two columns have gaps. **notes** is 62% empty (31 of 50 rows), and **region** is missing 4 values. " +
      "Everything else is complete. The notes column is empty enough that imputing it would mostly invent data, so " +
      "consider excluding it before modelling.",
    columns: ["notes", "region"],
  },
];

export default function CopilotSection() {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-100px" });

  return (
    <section id="copilot" className="relative border-t border-line py-24 sm:py-32">
      <div className="mx-auto max-w-6xl px-6">
        <div className="grid gap-12 lg:grid-cols-2 lg:items-center">
          {/* ----------------------------------------------- conversation */}
          <div ref={ref} className="order-2 lg:order-1">
            <div className="glass sheen glass-glow overflow-hidden rounded-2xl">
              <div className="flex items-center gap-2 border-b border-line/40 px-4 py-3">
                <MessageSquare size={14} className="text-accent" aria-hidden="true" />
                <span className="text-sm font-medium text-ink">AI Copilot</span>
                <span className="glass-chip ml-auto rounded-full px-2 py-0.5 font-mono text-[10px] text-muted">
                  customers.csv
                </span>
              </div>

              <div className="space-y-4 px-4 py-5">
                {CONVERSATION.map((message, index) => (
                  <motion.div
                    key={message.role}
                    initial={{ opacity: 0, y: 10 }}
                    animate={inView ? { opacity: 1, y: 0 } : {}}
                    transition={{ delay: 0.2 + index * 0.55, duration: 0.4 }}
                    className={message.role === "user" ? "flex justify-end" : ""}
                  >
                    {message.role === "user" ? (
                      <p className="max-w-[85%] rounded-lg rounded-br-sm bg-accent px-3.5 py-2.5 text-sm text-accent-contrast">
                        {message.text}
                      </p>
                    ) : (
                      <div className="max-w-[92%]">
                        <p className="glass glass-strong rounded-xl rounded-bl-sm px-3.5 py-2.5 text-sm leading-relaxed text-ink">
                          {renderEmphasis(message.text)}
                        </p>
                        <motion.div
                          initial={{ opacity: 0 }}
                          animate={inView ? { opacity: 1 } : {}}
                          transition={{ delay: 1.1, duration: 0.3 }}
                          className="mt-2 flex flex-wrap items-center gap-1.5"
                        >
                          <span className="text-[10px] uppercase tracking-wide text-subtle">
                            Columns used
                          </span>
                          {message.columns.map((column) => (
                            <code
                              key={column}
                              className="glass-chip rounded px-1.5 py-0.5 font-mono text-[11px] text-muted"
                            >
                              {column}
                            </code>
                          ))}
                        </motion.div>
                      </div>
                    )}
                  </motion.div>
                ))}
              </div>

              <div className="border-t border-line/40 px-4 py-3">
                <p className="text-xs text-muted">
                  History persists per dataset, so the conversation is still there tomorrow.
                </p>
              </div>
            </div>
          </div>

          {/* ---------------------------------------------------- copy */}
          <div className="order-1 lg:order-2">
            <Reveal>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">
                AI Copilot
              </p>
              <h2 className="mt-3 text-balance text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
                Ask questions. Get cited answers.
              </h2>
              <p className="mt-4 text-base leading-relaxed text-muted">
                The Copilot answers from statistics the server computed, and names the columns
                behind every claim. If the numbers aren&rsquo;t there, it tells you instead of
                guessing.
              </p>
            </Reveal>

            <dl className="mt-8 space-y-5">
              {GUARANTEES.map((item, index) => (
                <Reveal key={item.title} delay={index * 0.08}>
                  <div className="flex gap-3.5">
                    <span className="glass mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-xl text-accent">
                      <item.icon size={15} aria-hidden="true" />
                    </span>
                    <div>
                      <dt className="text-sm font-medium text-ink">{item.title}</dt>
                      <dd className="mt-0.5 text-sm leading-relaxed text-muted">{item.body}</dd>
                    </div>
                  </div>
                </Reveal>
              ))}
            </dl>

            <Reveal delay={0.35}>
              <p className="glass glass-subtle mt-7 rounded-xl px-3.5 py-3 text-xs leading-relaxed text-muted">
                Optional feature. Without an API key configured, the Copilot shows a clear
                &ldquo;not configured&rdquo; state, and every other part of the product works
                exactly as before.
              </p>
            </Reveal>
          </div>
        </div>
      </div>
    </section>
  );
}

/** Renders **bold** spans without pulling in a markdown dependency. */
function renderEmphasis(text) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((chunk, index) =>
    chunk.startsWith("**") && chunk.endsWith("**") ? (
      <strong key={index} className="font-mono text-[0.92em] font-semibold text-ink">
        {chunk.slice(2, -2)}
      </strong>
    ) : (
      chunk
    )
  );
}
