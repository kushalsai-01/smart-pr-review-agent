import { useMemo, useState } from "react";

const MODE_OPTIONS = [
  {
    value: "review_only",
    label: "Review Only",
    help: "Run review and optionally open issues. Skip fix drafting unless triggered by low-confidence review.",
  },
  {
    value: "human_in_loop",
    label: "Human-in-the-loop",
    help: "Run review, then pause for approval before drafting and applying fixes.",
  },
  {
    value: "auto_pilot",
    label: "Auto Pilot",
    help: "Run review, hunt bugs, and draft fixes automatically.",
  },
];

const LLM_PROVIDER_OPTIONS = [
  {
    value: "groq",
    label: "Default Groq",
    help: "Uses the server-side Groq key (no extra input).",
  },
  {
    value: "claude",
    label: "Claude (BYOK)",
    help: "Uses your own Anthropic API key for this run.",
  },
  {
    value: "gemini",
    label: "Gemini (BYOK)",
    help: "Uses your own Google Gemini API key for this run.",
  },
];

function isValidGithubPrUrl(url) {
  const re = /^https?:\/\/github\.com\/[^/]+\/[^/]+\/pull\/\d+\/?$/i;
  return re.test(String(url || ""));
}

export default function PRInput({
  disabled,
  mode,
  onModeChange,
  onStart,
}) {
  const [prUrl, setPrUrl] = useState("");
  const [error, setError] = useState("");
  const [llmProvider, setLlmProvider] = useState("groq");
  const [llmApiKey, setLlmApiKey] = useState("");
  const [llmModel, setLlmModel] = useState("");
  const selectedHelp = useMemo(() => {
    const match = MODE_OPTIONS.find((m) => m.value === mode);
    return match ? match.help : "";
  }, [mode]);

  const selectedProviderHelp = useMemo(() => {
    const match = LLM_PROVIDER_OPTIONS.find((p) => p.value === llmProvider);
    return match ? match.help : "";
  }, [llmProvider]);

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    if (disabled) {
      return;
    }
    if (!isValidGithubPrUrl(prUrl)) {
      setError("Enter a valid GitHub pull request URL.");
      return;
    }

    if (llmProvider !== "groq" && !String(llmApiKey || "").trim()) {
      setError("Enter your LLM API key for the selected provider.");
      return;
    }

    const body = {
      pr_url: prUrl,
      mode,
      llm_provider: llmProvider,
      llm_api_key: llmProvider === "groq" ? null : llmApiKey.trim(),
      llm_model: llmModel.trim() ? llmModel.trim() : null,
    };
    const response = await fetch("/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || payload.message || response.statusText);
    }
    const payload = await response.json();
    onStart({ threadId: payload.thread_id, mode });
  };

  return (
    <section className="rounded-xl border border-slate-700 bg-slate-950 p-4">
      <h2 className="text-lg font-semibold text-slate-100">Start a review run</h2>
      <p className="mt-1 text-sm text-slate-400">
        Provide a GitHub pull request URL and choose an automation mode.
      </p>
      <form onSubmit={submit} className="mt-4 grid gap-3">
        <label className="grid gap-1">
          <span className="text-sm text-slate-200">Pull request URL</span>
          <input
            className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-sm text-slate-100"
            value={prUrl}
            onChange={(event) => setPrUrl(event.target.value)}
            placeholder="https://github.com/<owner>/<repo>/pull/<number>"
            required
            disabled={disabled}
          />
        </label>
        <label className="grid gap-1">
          <span className="text-sm text-slate-200">Automation mode</span>
          <select
            className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
            value={mode}
            onChange={(event) => onModeChange(event.target.value)}
            disabled={disabled}
            title={selectedHelp}
          >
            {MODE_OPTIONS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
          <div className="text-xs text-slate-400">{selectedHelp}</div>
        </label>

        <label className="grid gap-1">
          <span className="text-sm text-slate-200">LLM provider</span>
          <select
            className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100"
            value={llmProvider}
            onChange={(event) => setLlmProvider(event.target.value)}
            disabled={disabled}
            title={selectedProviderHelp}
          >
            {LLM_PROVIDER_OPTIONS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
          <div className="text-xs text-slate-400">{selectedProviderHelp}</div>
        </label>

        {llmProvider !== "groq" ? (
          <label className="grid gap-1">
            <span className="text-sm text-slate-200">API key (BYOK)</span>
            <input
              className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-sm text-slate-100"
              value={llmApiKey}
              onChange={(event) => setLlmApiKey(event.target.value)}
              placeholder="Paste your provider API key"
              disabled={disabled}
            />
          </label>
        ) : null}

        <label className="grid gap-1">
          <span className="text-sm text-slate-200">Model override (optional)</span>
          <input
            className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-sm text-slate-100"
            value={llmModel}
            onChange={(event) => setLlmModel(event.target.value)}
            placeholder="Leave empty for defaults"
            disabled={disabled}
          />
        </label>

        {error ? <p className="text-sm text-red-400">{error}</p> : null}
        <button
          type="submit"
          className="mt-1 rounded-lg bg-cyan-400 px-4 py-2 text-sm font-semibold text-slate-950 disabled:bg-slate-600"
          disabled={disabled}
        >
          {disabled ? "Starting..." : "Run review"}
        </button>
      </form>
    </section>
  );
}

