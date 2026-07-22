// ─── helpers ───────────────────────────────────────────────────────────────

function setDot(id, status /* "ok" | "error" | "warn" | "idle" */) {
  document.getElementById(id).className = "dot dot--" + status;
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function getOrigin() {
  return (document.getElementById("daemonOrigin").value || "http://127.0.0.1:3200").trim();
}

async function safeFetch(url) {
  const r = await fetch(url, { signal: AbortSignal.timeout(3000) });
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}

// ─── main refresh ──────────────────────────────────────────────────────────

async function refreshState() {
  const origin = getOrigin();

  // ① Get WebSocket state from service worker
  let swState = { connected: false, lastSnapshot: null, lastEvents: [], daemonOrigin: origin };
  try {
    swState = await chrome.runtime.sendMessage({ type: "get-state" });
    document.getElementById("daemonOrigin").value = swState.daemonOrigin || origin;
  } catch (_) { /* service worker suspended */ }

  // WebSocket indicator
  if (swState.connected) {
    setDot("dot-ws", "ok");
    setText("detail-ws", "Connected");
  } else {
    setDot("dot-ws", "error");
    setText("detail-ws", "Disconnected — click Reconnect");
  }

  // ② Daemon HTTP health (fetch directly from sidepanel)
  let daemonOk = false;
  try {
    await safeFetch(origin + "/api/health");
    daemonOk = true;
    setDot("dot-daemon", "ok");
    setText("detail-daemon", "Reachable (" + origin + ")");
  } catch (e) {
    setDot("dot-daemon", "error");
    setText("detail-daemon", "Unreachable — is the daemon running?");
  }

  // ③ Client registration check (daemon sees this extension as a client)
  if (daemonOk) {
    try {
      const data = await safeFetch(origin + "/api/cdm-agent/browser/clients");
      const clients = (data && data.clients) || [];
      const extClients = clients.filter(c => c.runner === "extension");
      if (extClients.length > 0) {
        const last = extClients[0];
        setDot("dot-client", "ok");
        setText("detail-client", `Registered · last seen ${formatAge(last.lastSeenAt)}`);
      } else if (clients.length > 0) {
        setDot("dot-client", "warn");
        setText("detail-client", `${clients.length} client(s) but runner≠extension`);
      } else {
        setDot("dot-client", "error");
        setText("detail-client", "Not registered — WebSocket never sent hello");
      }
    } catch (e) {
      setDot("dot-client", "idle");
      setText("detail-client", "Could not check");
    }
  } else {
    setDot("dot-client", "idle");
    setText("detail-client", "–");
  }

  // ④ Active page info from service worker's lastSnapshot
  const snap = swState.lastSnapshot;
  const errorRow = document.getElementById("infoErrorRow");
  if (snap && snap.error) {
    setText("infoPage", "–");
    setText("infoUrl", "–");
    setText("infoRows", "–");
    setText("infoInvalid", "–");
    setText("infoError", snap.error);
    errorRow.style.display = "";
  } else if (snap) {
    setText("infoPage", snap.pageLabel || "–");
    setText("infoUrl", snap.pathname || snap.url || "–");
    setText("infoRows", (snap.visibleRows || []).slice(0, 5).join(", ") + (snap.visibleRows && snap.visibleRows.length > 5 ? " …" : "") || "–");
    setText("infoInvalid", String(snap.invalidCount || 0));
    errorRow.style.display = "none";
  } else {
    setText("infoPage", "–");
    setText("infoUrl", "–");
    setText("infoRows", "–");
    setText("infoInvalid", "–");
    errorRow.style.display = "none";
  }

  // ⑤ Events log (only if visible)
  if (!document.getElementById("events").classList.contains("hidden")) {
    document.getElementById("events").textContent =
      JSON.stringify(swState.lastEvents || [], null, 2);
  }

  setText("updateTime", new Date().toLocaleTimeString());
}

function formatAge(iso) {
  if (!iso) return "–";
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 5000) return "just now";
  if (diff < 60000) return Math.round(diff / 1000) + "s ago";
  return Math.round(diff / 60000) + "m ago";
}

// ─── event listeners ───────────────────────────────────────────────────────

document.getElementById("reconnectBtn").addEventListener("click", async () => {
  const btn = document.getElementById("reconnectBtn");
  btn.disabled = true;
  btn.textContent = "Reconnecting…";
  try {
    await chrome.runtime.sendMessage({ type: "force-reconnect" });
  } catch (_) {}
  await new Promise(r => setTimeout(r, 1500));
  await refreshState();
  btn.disabled = false;
  btn.textContent = "⟳ Reconnect";
});

document.getElementById("saveOrigin").addEventListener("click", async () => {
  const origin = getOrigin();
  try {
    await chrome.runtime.sendMessage({ type: "set-daemon-origin", daemonOrigin: origin });
  } catch (_) {}
  await refreshState();
});

document.getElementById("inspectPage").addEventListener("click", async () => {
  try {
    await chrome.runtime.sendMessage({ type: "request-inspect-active-page" });
  } catch (_) {}
  await refreshState();
});

let eventsVisible = false;
document.getElementById("toggleEvents").addEventListener("click", () => {
  eventsVisible = !eventsVisible;
  const pre = document.getElementById("events");
  const btn = document.getElementById("toggleEvents");
  pre.classList.toggle("hidden", !eventsVisible);
  btn.textContent = eventsVisible ? "Hide" : "Show";
  if (eventsVisible) refreshState();
});

// ─── auto-refresh every 2 s ────────────────────────────────────────────────

refreshState();
setInterval(refreshState, 2000);
