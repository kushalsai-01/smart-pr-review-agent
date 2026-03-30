import { useState } from "react";

export function ApprovalBar({
  busy,
  description,
  disabled,
  githubToken,
  onDecision,
  threadId,
  title,
}) {
  const [message, setMessage] = useState("");
  const [fault, setFault] = useState("");

  const postDecision = async (approved) => {
    if (!threadId || disabled || busy) {
      return;
    }
    setFault("");
    try {
      const headers = { "Content-Type": "application/json" };
      if (githubToken) {
        headers.Authorization = `Bearer ${githubToken}`;
      }
      const response = await fetch("/approve", {
        method: "POST",
        headers,
        body: JSON.stringify({ thread_id: threadId, approved }),
      });
      let payload = {};
      try {
        payload = await response.json();
      } catch {
        payload = {};
      }
      if (!response.ok) {
        const detail = payload.detail;
        const normalized =
          typeof detail === "string"
            ? detail
            : Array.isArray(detail)
              ? detail.map((item) => item.msg || item).join(", ")
              : JSON.stringify(detail || {});
        throw new Error(normalized || response.statusText);
      }
      setMessage(`${payload.approval_status}:${payload.fix_patch.slice(0, 120)}`);
      onDecision({ approved, payload });
    } catch (err) {
      setFault(err.message || "approval_failed");
    }
  };

  return (
    <section
      style={{
        padding: "1.5rem",
        borderRadius: "12px",
        background: "#111827",
        border: "1px solid #312e81",
      }}
    >
      <header style={{ marginBottom: "1rem" }}>
        <h3 style={{ margin: "0 0 0.35rem" }}>{title}</h3>
        <p style={{ margin: 0, color: "#94a3b8" }}>{description}</p>
      </header>
      <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
        <button
          type="button"
          disabled={disabled || busy || !threadId}
          onClick={() => postDecision(true)}
          style={buttonStyle(true)}
        >
          Approve fix drafting
        </button>
        <button
          type="button"
          disabled={disabled || busy || !threadId}
          onClick={() => postDecision(false)}
          style={buttonStyle(false)}
        >
          Reject automation
        </button>
      </div>
      {fault ? (
        <p style={{ color: "#f87171", marginTop: "0.75rem" }}>{fault}</p>
      ) : null}
      {message ? (
        <pre
          style={{
            marginTop: "1rem",
            background: "#020617",
            padding: "0.75rem",
            borderRadius: "8px",
            whiteSpace: "pre-wrap",
          }}
        >
          {message}
        </pre>
      ) : null}
    </section>
  );
}

function buttonStyle(primary) {
  return {
    padding: "0.65rem 1rem",
    borderRadius: "8px",
    border: `1px solid ${primary ? "#22d3ee" : "#f87171"}`,
    background: primary ? "#0ea5e9" : "#7f1d1d",
    color: "#f8fafc",
    cursor: "pointer",
  };
}
