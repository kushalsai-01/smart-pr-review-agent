import { useState } from "react";

export function ReviewForm({
  disabled,
  githubToken,
  onBusy,
  onError,
  onScheduled,
  title,
  subtitle,
}) {
  const [prUrl, setPrUrl] = useState("https://github.com/octocat/Hello-World/pull/1347");
  const [repoFullName, setRepoFullName] = useState("octocat/Hello-World");
  const [prNumber, setPrNumber] = useState("1347");
  const [mode, setMode] = useState("review_only");

  const submit = async (event) => {
    event.preventDefault();
    if (disabled) {
      return;
    }
    onBusy?.(true);
    onError?.("");
    try {
      const threadId = crypto.randomUUID();
      const headers = { "Content-Type": "application/json" };
      if (githubToken) {
        headers.Authorization = `Bearer ${githubToken}`;
      }
      const body = {
        pr_url: prUrl,
        repo_full_name: repoFullName,
        pr_number: Number(prNumber),
        mode,
        thread_id: threadId,
      };
      const response = await fetch("/review", {
        method: "POST",
        headers,
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || response.statusText);
      }
      const payload = await response.json();
      onScheduled({ threadId: payload.thread_id, mode });
    } catch (err) {
      onError?.(err.message || "request_failed");
    } finally {
      onBusy?.(false);
    }
  };

  return (
    <section
      style={{
        padding: "1.5rem",
        borderRadius: "12px",
        background: "#111827",
        border: "1px solid #1f2937",
      }}
    >
      <header style={{ marginBottom: "1rem" }}>
        <h2 style={{ margin: "0 0 0.35rem" }}>{title}</h2>
        <p style={{ margin: 0, color: "#94a3b8" }}>{subtitle}</p>
      </header>
      <form
        onSubmit={submit}
        style={{ display: "grid", gap: "0.75rem" }}
      >
        <label style={{ display: "grid", gap: "0.35rem" }}>
          <span>Pull request URL</span>
          <input
            value={prUrl}
            onChange={(event) => setPrUrl(event.target.value)}
            required
            style={inputStyle}
          />
        </label>
        <label style={{ display: "grid", gap: "0.35rem" }}>
          <span>Repository (owner/name)</span>
          <input
            value={repoFullName}
            onChange={(event) => setRepoFullName(event.target.value)}
            required
            style={inputStyle}
          />
        </label>
        <label style={{ display: "grid", gap: "0.35rem" }}>
          <span>Pull request number</span>
          <input
            type="number"
            min="1"
            value={prNumber}
            onChange={(event) => setPrNumber(event.target.value)}
            required
            style={inputStyle}
          />
        </label>
        <label style={{ display: "grid", gap: "0.35rem" }}>
          <span>Automation mode</span>
          <select
            value={mode}
            onChange={(event) => setMode(event.target.value)}
            style={inputStyle}
          >
            <option value="review_only">review_only</option>
            <option value="human_in_loop">human_in_loop</option>
            <option value="auto_pilot">auto_pilot</option>
          </select>
        </label>
        <button
          type="submit"
          disabled={disabled}
          style={{
            marginTop: "0.5rem",
            padding: "0.75rem 1rem",
            borderRadius: "8px",
            border: "none",
            background: disabled ? "#334155" : "#22d3ee",
            color: "#0f172a",
            fontWeight: 600,
            cursor: disabled ? "not-allowed" : "pointer",
          }}
        >
          {disabled ? "Run in progress" : "Start review run"}
        </button>
      </form>
    </section>
  );
}

const inputStyle = {
  padding: "0.65rem 0.75rem",
  borderRadius: "8px",
  border: "1px solid #334155",
  background: "#0f172a",
  color: "#e2e8f0",
};
