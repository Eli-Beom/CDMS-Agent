const DEFAULT_DAEMON_ORIGIN = "http://127.0.0.1:3100";

let daemonOrigin = DEFAULT_DAEMON_ORIGIN;
let websocket = null;
let lastSnapshot = null;
let lastEvents = [];
let preferredTabId = null;

function wsUrl(origin) {
  return origin.replace(/^http/i, "ws") + "/ws/cdm-agent";
}

function sendToDaemon(message) {
  if (!websocket || websocket.readyState !== WebSocket.OPEN) {
    return false;
  }
  websocket.send(JSON.stringify(message));
  return true;
}

function waitForOpenSocket(timeoutMs) {
  const timeout = timeoutMs || 5000;
  const startedAt = Date.now();

  return new Promise((resolve, reject) => {
    function check() {
      if (websocket && websocket.readyState === WebSocket.OPEN) {
        resolve(websocket);
        return;
      }

      if (Date.now() - startedAt >= timeout) {
        reject(new Error("Browser bridge is not connected to the daemon."));
        return;
      }

      setTimeout(check, 100);
    }

    check();
  });
}

function broadcast(message) {
  chrome.runtime.sendMessage(message).catch(() => undefined);
}

async function getActiveTab() {
  const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  const tab = tabs[0];
  if (!tab || !tab.id) {
    throw new Error("No active CDMS tab is available.");
  }

  return tab;
}

async function getPreferredTab() {
  if (preferredTabId) {
    try {
      const tab = await chrome.tabs.get(preferredTabId);
      if (tab && tab.id) {
        return tab;
      }
    } catch (error) {
      preferredTabId = null;
    }
  }

  const tab = await getActiveTab();
  preferredTabId = tab.id;
  return tab;
}

async function ensureRunnerOnTab(tabId) {
  await chrome.scripting.executeScript({
    target: { tabId },
    files: ["browser-runner-core.js"],
    world: "MAIN",
  });
}

async function executeRunnerCommand(tabId, command, payload) {
  await ensureRunnerOnTab(tabId);
  const results = await chrome.scripting.executeScript({
    target: { tabId },
    world: "MAIN",
    args: [command, payload || null],
    func: async (runnerCommand, runnerPayload) => {
      const runner = window.__CDMAgentRunner;
      if (!runner) {
        throw new Error("CDM Agent runner is unavailable on the page.");
      }

      if (runnerCommand === "inspect_active_page") {
        return runner.inspectActivePage();
      }

      if (runnerCommand === "capture_page") {
        return runner.capturePage();
      }

      if (runnerCommand === "run_case") {
        return runner.runCase((runnerPayload && runnerPayload.case) || {});
      }

      throw new Error("Unsupported command " + runnerCommand);
    },
  });

  if (!results || !results.length) {
    throw new Error("No result returned from the active CDMS tab.");
  }

  return results[0].result;
}

function toSnapshotPayload(snapshot) {
  return {
    clientId: "extension:" + snapshot.pathname,
    runner: "extension",
    url: snapshot.url,
    pathname: snapshot.pathname,
    pageLabel: snapshot.pageLabel,
    visibleRows: snapshot.visibleRows,
    enabledActions: snapshot.enabledActions,
    invalidRowLabels: snapshot.invalidRowLabels,
    invalidCount: snapshot.invalidCount,
    timestamp: snapshot.timestamp,
  };
}

async function refreshActiveTabSnapshot(tabId) {
  const inspected = await executeRunnerCommand(tabId, "inspect_active_page");
  const snapshot = toSnapshotPayload(inspected);
  lastSnapshot = snapshot;
  sendToDaemon({ type: "page_snapshot", snapshot });
  return snapshot;
}

async function sendHello() {
  let currentUrl = undefined;
  let pageLabel = undefined;
  let pathname = undefined;

  try {
    const tab = await getPreferredTab();
    currentUrl = tab.url;
    try {
      const snapshot = await refreshActiveTabSnapshot(tab.id);
      pageLabel = snapshot.pageLabel;
      pathname = snapshot.pathname;
      currentUrl = snapshot.url || currentUrl;
    } catch (snapshotError) {
      // Page may not support runner yet — still register with tab URL
      try { pathname = new URL(currentUrl).pathname; } catch (e) {}
    }
  } catch (error) {}

  sendToDaemon({
    type: "hello",
    clientId: pathname ? "extension:" + pathname : "extension:unknown",
    runner: "extension",
    url: currentUrl,
    pathname: pathname,
    pageLabel: pageLabel,
  });
}

function connectDaemon() {
  if (websocket && websocket.readyState === WebSocket.OPEN) {
    return;
  }

  websocket = new WebSocket(wsUrl(daemonOrigin));

  websocket.onopen = () => {
    sendHello().catch(() => undefined);
    broadcast({ type: "daemon-state", connected: true, daemonOrigin });
  };

  websocket.onmessage = async event => {
    const message = JSON.parse(event.data);
    lastEvents.push({ at: new Date().toISOString(), direction: "in", message });
    lastEvents = lastEvents.slice(-100);

    if (message.type === "command") {
      let tab;
      try {
        tab = await getPreferredTab();
      } catch (error) {
        sendToDaemon({
          type: "tool_result",
          requestId: message.requestId,
          payload: { outcome: "failed", failureReason: error.message || String(error) },
        });
        return;
      }

      executeRunnerCommand(tab.id, message.command, message.payload)
        .then(payload => {
          sendToDaemon({
            type: "tool_result",
            requestId: message.requestId,
            payload,
          });
        })
        .catch(error => {
          lastSnapshot = { error: error.message || String(error), timestamp: new Date().toISOString() };
        sendToDaemon({
          type: "tool_result",
          requestId: message.requestId,
          payload: { outcome: "failed", failureReason: error.message || String(error) },
        });
        });
    }
  };

  websocket.onclose = () => {
    broadcast({ type: "daemon-state", connected: false, daemonOrigin });
    setTimeout(connectDaemon, 3000);
  };

  websocket.onerror = () => {
    try {
      websocket.close();
    } catch (error) {}
  };
}

chrome.runtime.onInstalled.addListener(() => {
  connectDaemon();
});

chrome.runtime.onStartup.addListener(() => {
  connectDaemon();
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "page-ready") {
    preferredTabId = sender && sender.tab && sender.tab.id ? sender.tab.id : preferredTabId;
    connectDaemon();
    waitForOpenSocket()
      .then(() => sendHello())
      .then(() => {
        sendResponse({ ok: true, daemonOrigin });
      })
      .catch(error => {
        sendResponse({ ok: false, daemonOrigin, error: error.message || String(error) });
      });
    return true;
  }

  if (message.type === "sync-active-tab-snapshot") {
    connectDaemon();
    const tabId = sender && sender.tab && sender.tab.id;
    if (!tabId) {
      sendResponse({ ok: false, error: "No sender tab." });
      return true;
    }
    preferredTabId = tabId;

    waitForOpenSocket()
      .then(() => refreshActiveTabSnapshot(tabId))
      .then(snapshot => {
        sendResponse({ ok: true, snapshot });
      })
      .catch(error => {
        lastSnapshot = { error: error.message || String(error), timestamp: new Date().toISOString() };
        sendResponse({ ok: false, error: error.message || String(error) });
      });
    return true; // keep message port open for async sendResponse
  }

  if (message.type === "tool-result") {
    sendToDaemon({ type: "tool_result", requestId: message.requestId, payload: message.payload });
    sendResponse({ ok: true });
    return;
  }

  if (message.type === "get-state") {
    connectDaemon();
    sendResponse({
      daemonOrigin,
      connected: websocket && websocket.readyState === WebSocket.OPEN,
      lastSnapshot,
      lastEvents,
    });
    return true;
  }

  if (message.type === "set-daemon-origin") {
    daemonOrigin = message.daemonOrigin || DEFAULT_DAEMON_ORIGIN;
    try {
      if (websocket) websocket.close();
    } catch (error) {}
    connectDaemon();
    sendResponse({ ok: true, daemonOrigin });
    return true;
  }

  if (message.type === "request-inspect-active-page") {
    connectDaemon();
    waitForOpenSocket()
      .then(() => getPreferredTab())
      .then(tab => refreshActiveTabSnapshot(tab.id))
      .then(sendResponse)
      .catch(error => {
        lastSnapshot = { error: error.message || String(error), timestamp: new Date().toISOString() };
        sendResponse({ ok: false, error: error.message || String(error) });
      });
    return true;
  }

  return false;
});
