import { useMemo, useState } from "react";
import { ApprovalBar } from "./components/ApprovalBar.jsx";
import { EventStream } from "./components/EventStream.jsx";
import { ReviewForm } from "./components/ReviewForm.jsx";

export default function App() {
  const [threadId, setThreadId] = useState("");
  const [mode, setMode] = useState("review_only");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [githubToken, setGithubToken] = useState("");

  const showApproval = useMemo(() => mode === "human_in_loop", [mode]);

  const handleScheduled = (payload) => {
    setThreadId(payload.threadId);
    setMode(payload.mode);
  };

  return (
    <div style={{ maxWidth: "1200px", margin: "0 auto", padding: "2rem" }}>
      <header style={{ marginBottom: "1.5rem" }}>
        <h1 style={{ margin: "0 0 0.5rem" }}>Pull request automation desk</h1>
        <p style={{ margin: 0, color: "#94a3b8" }}>
          Coordinate review agents, streaming output, and optional human gating.
        </p>
      </header>
      <label
        style={{
          display: "grid",
          gap: "0.35rem",
          marginBottom: "1rem",
        }}
      >
        <span>Optional GitHub token (enforces Authorization when set)</span>
        <input
          type="password"
          value={githubToken}
          onChange={(event) => setGithubToken(event.target.value)}
          placeholder="ghp_..."
          style={{
            padding: "0.65rem 0.75rem",
            borderRadius: "8px",
            border: "1px solid #334155",
            background: "#0f172a",
            color: "#e2e8f0",
          }}
        />
      </label>
      {error ? (
        <p style={{ color: "#f87171", marginBottom: "1rem" }}>{error}</p>
      ) : null}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
          gap: "1rem",
        }}
      >
        <ReviewForm
          disabled={busy}
          githubToken={githubToken}
          onBusy={setBusy}
          onError={setError}
          onScheduled={handleScheduled}
          title="Launch review"
          subtitle="Provide the pull request targets the backend agents should analyze."
        />
        <EventStream
          autoScroll
          height="520px"
          threadId={threadId}
          title="Live SSE timeline"
        />
      </div>
      {showApproval ? (
        <div style={{ marginTop: "1rem" }}>
          <ApprovalBar
            busy={busy}
            description="Approve only after the workflow pauses pending human review."
            disabled={!threadId}
            githubToken={githubToken}
            threadId={threadId}
            title="Human-in-the-loop approvals"
            onDecision={() => {}}
          />
        </div>
      ) : null}
    </div>
  );
}
