"use client";

import { useEffect, useState } from "react";

import { ApiError, queryRuns } from "@/lib/api";
import { useIntlLocale, useT } from "@/lib/i18n";
import type { PipelineRun, StepTrace } from "@/types/contract";

interface TraceViewProps {
  // injectable so tests never hit the network
  runsFn?: typeof queryRuns;
}

function runStatus(run: PipelineRun): "failed" | "skipped" | "ok" {
  if (run.steps.some((s) => s.status === "failed")) return "failed";
  if (run.steps.some((s) => s.status === "skipped")) return "skipped";
  return "ok";
}

const STATUS_CLASS: Record<string, string> = {
  failed: "bg-bad-bg text-bad-fg",
  skipped: "bg-warn-bg text-warn-fg",
  ok: "bg-ok-bg text-ok-fg",
};

/** Run trace (§4/§7): a read-only debug list of verify/poll/digest runs, each with
 * its ordered steps so a half-failed run ("captions failed → whisper ok; stance #3
 * failed") is inspectable — the operator can replay where the pipeline got stuck.
 * A debug trace, deliberately not a telemetry platform. */
export function TraceView({ runsFn = queryRuns }: TraceViewProps) {
  const [runs, setRuns] = useState<PipelineRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const t = useT();

  useEffect(() => {
    let active = true;
    runsFn()
      .then((r) => active && setRuns(r))
      .catch(
        (err) =>
          active && setError(err instanceof ApiError ? err.message : t("trace.errLoad")),
      );
    return () => {
      active = false;
    };
  }, [runsFn]);

  return (
    <div className="space-y-4">
      {error && (
        <p role="alert" className="text-sm text-bad-fg">
          {error}
        </p>
      )}
      {!error && runs === null && (
        <p className="text-sm text-muted">{t("trace.loading")}</p>
      )}
      {runs && runs.length === 0 && (
        <p className="text-sm text-muted">{t("trace.none")}</p>
      )}
      {runs && runs.length > 0 && (
        <ul className="space-y-3" aria-label={t("trace.runs.aria")}>
          {runs.map((run) => (
            <RunRow key={run.id} run={run} />
          ))}
        </ul>
      )}
    </div>
  );
}

function RunRow({ run }: { run: PipelineRun }) {
  const t = useT();
  const intlLocale = useIntlLocale();
  const status = runStatus(run);
  return (
    <li className="space-y-2 rounded border border-line p-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">{run.trigger}</span>
        <span className={`rounded px-2 py-0.5 text-xs ${STATUS_CLASS[status]}`}>{status}</span>
        <span className="text-xs text-muted">
          {new Date(run.started_at).toLocaleString(intlLocale)}
          {run.finished_at ? "" : t("trace.run.unfinished")}
        </span>
      </div>
      <ol className="space-y-1" aria-label={t("trace.run.steps.aria", { trigger: run.trigger })}>
        {run.steps.map((step, i) => (
          <StepRow key={`${step.step}:${i}`} step={step} />
        ))}
      </ol>
    </li>
  );
}

function StepRow({ step }: { step: StepTrace }) {
  const t = useT();
  return (
    <li className="text-xs">
      <span className="inline-flex items-center gap-2">
        <span className={`rounded px-1.5 py-0.5 ${STATUS_CLASS[step.status]}`}>{step.status}</span>
        <span className="font-medium">{step.step}</span>
        {step.fallback_used && (
          <span className="text-muted">{t("trace.step.fallback", { fallback: step.fallback_used })}</span>
        )}
      </span>
      {step.error && <p className="mt-0.5 text-bad-fg">{step.error}</p>}
    </li>
  );
}
