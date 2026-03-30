import { useEffect, useState } from "react";

export function EventStream({
  autoScroll,
  height,
  threadId,
  title,
}) {
  const [lines, setLines] = useState([]);

  useEffect(() => {
    if (!threadId) {
      return undefined;
    }
    setLines([]);
    const source = new EventSource(`/stream/${threadId}`);
    source.onmessage = (event) => {
      setLines((prev) => [
        ...prev,
        { id: crypto.randomUUID(), kind: "message", text: event.data },
      ]);
    };
    source.addEventListener("state", (event) => {
      setLines((prev) => [
        ...prev,
        { id: crypto.randomUUID(), kind: "state", text: event.data },
      ]);
    });
    source.addEventListener("phase", (event) => {
      setLines((prev) => [
        ...prev,
        { id: crypto.randomUUID(), kind: "phase", text: event.data },
      ]);
    });
    source.addEventListener("error", (event) => {
      setLines((prev) => [
        ...prev,
        { id: crypto.randomUUID(), kind: "error", text: event.data },
      ]);
    });
    source.addEventListener("complete", () => {
      setLines((prev) => [
        ...prev,
        { id: crypto.randomUUID(), kind: "complete", text: "stream complete" },
      ]);
      source.close();
    });
    source.onerror = () => {
      source.close();
    };
    return () => {
      source.close();
    };
  }, [threadId]);

  useEffect(() => {
    if (!autoScroll) {
      return;
    }
    const el = document.getElementById("event-stream-panel");
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [lines, autoScroll]);

  return (
    <section
      style={{
        padding: "1.5rem",
        borderRadius: "12px",
        background: "#0b1224",
        border: "1px solid #1e293b",
        minHeight: height,
        display: "flex",
        flexDirection: "column",
        gap: "0.75rem",
      }}
    >
      <header>
        <h3 style={{ margin: 0 }}>{title}</h3>
        <p style={{ margin: "0.35rem 0 0", color: "#94a3b8" }}>
          Thread <code>{threadId || "none"}</code>
        </p>
      </header>
      <div
        id="event-stream-panel"
        style={{
          flex: 1,
          overflowY: "auto",
          background: "#020617",
          borderRadius: "8px",
          padding: "0.75rem",
          fontFamily: "Consolas, monospace",
          fontSize: "0.85rem",
        }}
      >
        {lines.length === 0 ? (
          <p style={{ margin: 0, color: "#64748b" }}>
            Waiting for workflow events…
          </p>
        ) : (
          lines.map((line) => (
            <div
              key={line.id}
              style={{
                marginBottom: "0.5rem",
                borderLeft: `3px solid ${
                  line.kind === "error"
                    ? "#f87171"
                    : line.kind === "phase"
                      ? "#facc15"
                      : "#38bdf8"
                }`,
                paddingLeft: "0.5rem",
              }}
            >
              <div style={{ color: "#cbd5f5", fontSize: "0.75rem" }}>
                {line.kind}
              </div>
              <pre
                style={{
                  margin: "0.25rem 0 0",
                  whiteSpace: "pre-wrap",
                  color: "#e2e8f0",
                }}
              >
                {line.text}
              </pre>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
