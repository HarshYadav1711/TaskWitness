/* TaskWitness operator frontend — thin view over server snapshots. */
(function () {
  "use strict";

  const POLL_MS = 500;
  const state = {
    runId: null,
    polling: false,
    pollTimer: null,
    inFlight: false,
    config: null,
    lastFocus: null,
    approvalOpen: false,
    pendingApprovalId: null,
  };

  const el = (id) => document.getElementById(id);

  function setHidden(node, hidden) {
    if (!node) return;
    node.hidden = !!hidden;
  }

  async function fetchJSON(url, options) {
    const res = await fetch(url, {
      headers: { Accept: "application/json", ...(options && options.headers) },
      ...options,
    });
    let body = null;
    try {
      body = await res.json();
    } catch (_) {
      body = null;
    }
    if (!res.ok) {
      const detail = body && body.detail ? body.detail : res.statusText;
      const err = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      err.status = res.status;
      throw err;
    }
    return body;
  }

  function stateLabel(value) {
    return String(value || "ready").replace(/_/g, " ").toUpperCase();
  }

  function verificationLabel(value) {
    const v = String(value || "").toLowerCase();
    if (v === "passed") return "VERIFIED";
    if (v === "incomplete") return "INCOMPLETE";
    if (v === "failed") return "FAILED";
    if (v === "blocked") return "BLOCKED";
    return stateLabel(value);
  }

  function markForEvent(ev) {
    const t = ev.event_type || "";
    const s = ev.run_state || "";
    const msg = (ev.message || "").toLowerCase();
    if (t === "error" || s === "failed") return { sym: "×", cls: "danger" };
    if (s === "awaiting_approval" || t === "approval" || msg.includes("approval required")) {
      return { sym: "!", cls: "warn" };
    }
    if (s === "recovering" || msg.includes("uncertain") || msg.includes("recovered")) {
      return { sym: "↻", cls: "recover" };
    }
    if (s === "paused" || msg.includes("pause")) return { sym: "Ⅱ", cls: "warn" };
    if (t === "clarification") return { sym: "?", cls: "warn" };
    if (t === "verification" && msg.toLowerCase().includes("not")) return { sym: "○", cls: "warn" };
    if (msg.includes("incomplete") || msg.includes("rejected")) return { sym: "○", cls: "warn" };
    if (s === "completed" || t === "verification") return { sym: "✓", cls: "ok" };
    return { sym: "·", cls: "info" };
  }

  function formatTime(iso) {
    if (!iso) return "";
    try {
      return new Date(iso).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch (_) {
      return "";
    }
  }

  function renderTrace(events) {
    const list = el("trace-list");
    list.innerHTML = "";
    events.forEach((ev) => {
      const li = document.createElement("li");
      const mark = markForEvent(ev);
      const m = document.createElement("span");
      m.className = "trace-mark " + mark.cls;
      m.textContent = mark.sym;
      m.setAttribute("aria-hidden", "true");

      const body = document.createElement("div");
      body.className = "trace-body";
      const msg = document.createElement("p");
      msg.className = "trace-msg";
      msg.textContent = ev.message || "";
      body.appendChild(msg);
      if (ev.candidate_id || ev.action) {
        const ctx = document.createElement("p");
        ctx.className = "trace-ctx";
        ctx.textContent = [ev.candidate_id, ev.action, ev.run_state].filter(Boolean).join(" · ");
        body.appendChild(ctx);
      }

      const time = document.createElement("span");
      time.className = "trace-time";
      time.textContent = formatTime(ev.timestamp);

      li.appendChild(m);
      li.appendChild(body);
      li.appendChild(time);
      list.appendChild(li);
    });
    if (events.length) {
      list.lastElementChild.scrollIntoView({ block: "nearest" });
    }
  }

  function openApproval(pending) {
    const dialog = el("approval-dialog");
    state.lastFocus = document.activeElement;
    state.pendingApprovalId = pending.approval_id || null;
    el("apr-action").textContent = pending.action || "";
    el("apr-candidate").textContent = pending.candidate_id || "";
    el("apr-target").textContent = pending.target || "";
    el("apr-reason").textContent = pending.reason || "";
    if (pending.operation_id) {
      setHidden(el("apr-op-row"), false);
      el("apr-op").textContent = pending.operation_id;
    } else {
      setHidden(el("apr-op-row"), true);
    }
    setHidden(el("approval-error"), true);
    setHidden(dialog, false);
    state.approvalOpen = true;
    el("btn-reject").focus();
  }

  function closeApproval() {
    setHidden(el("approval-dialog"), true);
    state.approvalOpen = false;
    state.pendingApprovalId = null;
    if (state.lastFocus && typeof state.lastFocus.focus === "function") {
      state.lastFocus.focus();
    }
  }

  function renderVerification(snap) {
    const v = snap.verification;
    const exec = el("exec-summary");
    const verify = el("verify-summary");
    const vmsg = el("verify-message");

    exec.textContent = snap.execution_state
      ? stateLabel(snap.execution_state)
      : snap.terminal
        ? stateLabel(snap.run_state)
        : "—";

    if (!v) {
      verify.textContent = snap.run_state === "verifying" ? "VERIFYING…" : "—";
      vmsg.textContent = "";
      setHidden(el("verify-counts"), true);
      setHidden(el("verify-checks"), true);
      setHidden(el("incomplete-box"), true);
      setHidden(el("evidence-box"), true);
      return;
    }

    verify.textContent = verificationLabel(v.overall_status);
    vmsg.textContent =
      v.verified_complete === true
        ? "Goal verified"
        : snap.final_message || "Goal not fully completed";

    const counts = v.counts || {};
    const countsEl = el("verify-counts");
    countsEl.innerHTML = "";
    ["passed", "incomplete", "failed", "blocked"].forEach((k) => {
      const span = document.createElement("span");
      span.textContent = `${counts[k] || 0} ${k}`;
      countsEl.appendChild(span);
    });
    setHidden(countsEl, false);

    const checksEl = el("verify-checks");
    checksEl.innerHTML = "";
    const byCand = {};
    (v.checks || []).forEach((c) => {
      const key = c.candidate_id || "(global)";
      (byCand[key] = byCand[key] || []).push(c);
    });
    Object.keys(byCand).forEach((cid) => {
      const group = document.createElement("div");
      group.className = "check-group";
      const h = document.createElement("h4");
      h.textContent = cid;
      const ul = document.createElement("ul");
      byCand[cid].forEach((c) => {
        const li = document.createElement("li");
        const mark =
          c.status === "passed"
            ? "✓"
            : c.status === "incomplete"
              ? "○"
              : c.status === "blocked"
                ? "▣"
                : "×";
        li.textContent = `${mark} ${c.description} [${c.status}]`;
        ul.appendChild(li);
      });
      group.appendChild(h);
      group.appendChild(ul);
      checksEl.appendChild(group);
    });
    setHidden(checksEl, false);

    const incomplete = (v.checks || []).filter((c) => c.status === "incomplete");
    const box = el("incomplete-box");
    const list = el("incomplete-list");
    list.innerHTML = "";
    if (incomplete.length) {
      incomplete.forEach((c) => {
        const li = document.createElement("li");
        li.textContent = `${c.candidate_id || ""}: ${c.description}${
          c.note ? " — " + c.note : ""
        }`;
        list.appendChild(li);
      });
      setHidden(box, false);
    } else {
      setHidden(box, true);
    }

    if (snap.evidence_path) {
      el("evidence-path").textContent = snap.evidence_path;
      el("evidence-check-count").textContent = String((v.checks || []).length);
      setHidden(el("evidence-box"), false);
    }
  }

  function applySnapshot(snap) {
    if (!snap) return;
    state.runId = snap.run_id;

    const label = el("run-state-label");
    const displayState = snap.pause_label === "pausing" ? "pausing…" : snap.run_state;
    label.textContent = stateLabel(displayState);
    label.dataset.state = snap.run_state;

    el("meta-run-id").textContent = snap.run_id || "—";
    el("meta-journal-id").textContent = snap.journal_run_id || "—";
    el("meta-mode").textContent = snap.mode || "—";

    const events = snap.events || [];
    renderTrace(events);
    if (events.length) {
      el("current-step").textContent = events[events.length - 1].message;
    }

    const active = !snap.terminal;
    const awaiting = !!snap.pending_approval;
    const paused = snap.run_state === "paused";
    const canPause =
      active &&
      !awaiting &&
      !paused &&
      ["running", "recovering", "verifying"].includes(snap.run_state);
    const canResume = active && (paused || snap.pause_requested);

    setHidden(el("btn-pause"), !canPause);
    setHidden(el("btn-resume"), !canResume);
    el("btn-run").disabled = active;
    if (el("btn-demo-plan")) el("btn-demo-plan").disabled = active;

    if (snap.clarification_question) {
      el("clarify-text").textContent = snap.clarification_question;
      setHidden(el("clarify-panel"), false);
    } else if (snap.terminal) {
      setHidden(el("clarify-panel"), true);
    }

    if (snap.error && snap.interpretation_status === "model_error") {
      el("start-error").textContent = snap.error;
      setHidden(el("start-error"), false);
    }

    if (snap.pending_approval) {
      if (!state.approvalOpen || state.pendingApprovalId !== snap.pending_approval.approval_id) {
        openApproval(snap.pending_approval);
      }
    } else if (state.approvalOpen) {
      closeApproval();
    }

    renderVerification(snap);

    if (snap.terminal) stopPolling();
    else ensurePolling();
  }

  async function pollOnce() {
    if (!state.runId || state.inFlight) return;
    state.inFlight = true;
    try {
      const snap = await fetchJSON("/api/runs/" + encodeURIComponent(state.runId));
      applySnapshot(snap);
    } catch (_) {
      /* keep UI; retry next tick */
    } finally {
      state.inFlight = false;
    }
  }

  function ensurePolling() {
    if (state.pollTimer) return;
    state.pollTimer = setInterval(pollOnce, POLL_MS);
  }

  function stopPolling() {
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  }

  async function startRun(mode) {
    setHidden(el("start-error"), true);
    setHidden(el("clarify-panel"), true);
    const goal = el("goal-input").value;
    try {
      const body = { mode: mode || "natural_language" };
      if (mode !== "validated_plan") body.goal = goal;
      else if (goal.trim()) body.goal = goal;
      const snap = await fetchJSON("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      applySnapshot(snap);
      ensurePolling();
    } catch (err) {
      el("start-error").textContent = err.message || String(err);
      setHidden(el("start-error"), false);
    }
  }

  async function postControl(path) {
    if (!state.runId) return;
    try {
      const snap = await fetchJSON(
        "/api/runs/" + encodeURIComponent(state.runId) + path,
        { method: "POST" }
      );
      applySnapshot(snap);
    } catch (err) {
      el("start-error").textContent = err.message || String(err);
      setHidden(el("start-error"), false);
    }
  }

  async function resolveApproval(decision) {
    if (!state.runId || !state.pendingApprovalId) return;
    setHidden(el("approval-error"), true);
    try {
      const snap = await fetchJSON(
        "/api/runs/" +
          encodeURIComponent(state.runId) +
          "/approvals/" +
          encodeURIComponent(state.pendingApprovalId),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decision }),
        }
      );
      applySnapshot(snap);
    } catch (err) {
      el("approval-error").textContent = err.message || String(err);
      setHidden(el("approval-error"), false);
    }
  }

  async function init() {
    const cfg = await fetchJSON("/api/config");
    state.config = cfg;
    el("source-label").textContent = cfg.source_label || "candidates.csv";
    if (cfg.demo_mode) {
      setHidden(el("demo-banner"), false);
      setHidden(el("btn-demo-plan"), false);
      el("goal-hint").textContent =
        "Validated Plan Demo Mode is active. Use “Start validated plan” to exercise the full operator path without live model credentials. Plain-English Run still requires LLM configuration.";
    }

    const active = await fetchJSON("/api/runs/active");
    if (active && active.run) applySnapshot(active.run);

    el("btn-run").addEventListener("click", () => startRun("natural_language"));
    el("btn-demo-plan").addEventListener("click", () => startRun("validated_plan"));
    el("btn-pause").addEventListener("click", () => postControl("/pause"));
    el("btn-resume").addEventListener("click", () => postControl("/resume"));
    el("btn-reject").addEventListener("click", () => resolveApproval("rejected"));
    el("btn-approve").addEventListener("click", () => resolveApproval("approved"));

    document.addEventListener("keydown", (ev) => {
      if (!state.approvalOpen) return;
      if (ev.key === "Escape") ev.preventDefault();
    });
  }

  init().catch((err) => {
    el("start-error").textContent = "Failed to load operator config: " + err.message;
    setHidden(el("start-error"), false);
  });
})();
