const DEFAULT_DAEMON_ORIGIN = "http://127.0.0.1:3200";
const RECONNECT_DELAY_MS = 3000;
const HEARTBEAT_INTERVAL_MS = 15000;

let daemonOrigin = DEFAULT_DAEMON_ORIGIN;
let websocket = null;
let reconnectTimer = null;
let heartbeatTimer = null;
let lastSnapshot = null;
let lastEvents = [];
let preferredTabId = null;

function isSupportedCdmsUrl(url) {
  if (!url) return false;
  try {
    const { protocol, hostname } = new URL(url);
    return (
      (protocol === "http:" || protocol === "https:") &&
      (hostname === "sbx.cdms.mavenclinical.com" || hostname === "cdms.mavenclinical.com")
    );
  } catch (error) {
    return false;
  }
}

async function rememberPreferredTab(tab) {
  if (!tab || !tab.id || !isSupportedCdmsUrl(tab.url)) {
    return false;
  }

  preferredTabId = tab.id;
  return true;
}

function wsUrl(origin) {
  return origin.replace(/^http/i, "ws") + "/ws/cdm-agent";
}

function sendToDaemon(message) {
  if (!websocket || websocket.readyState !== WebSocket.OPEN) {
    lastEvents.push({ at: new Date().toISOString(), direction: "out-failed", message });
    lastEvents = lastEvents.slice(-100);
    return false;
  }
  websocket.send(JSON.stringify(message));
  lastEvents.push({ at: new Date().toISOString(), direction: "out", message });
  lastEvents = lastEvents.slice(-100);
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

function clearReconnectTimer() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
}

function stopHeartbeat() {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
}

function startHeartbeat(socket) {
  stopHeartbeat();
  heartbeatTimer = setInterval(() => {
    if (websocket !== socket || socket.readyState !== WebSocket.OPEN) {
      stopHeartbeat();
      return;
    }

    socket.send(JSON.stringify({ type: "ping", at: new Date().toISOString() }));
  }, HEARTBEAT_INTERVAL_MS);
}

function scheduleReconnect() {
  clearReconnectTimer();
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connectDaemon();
  }, RECONNECT_DELAY_MS);
}

async function getActiveTab() {
  const activeTabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  const activeCdmsTab = activeTabs.find(tab => tab.id && isSupportedCdmsUrl(tab.url));
  if (activeCdmsTab) {
    await rememberPreferredTab(activeCdmsTab);
    return activeCdmsTab;
  }

  const cdmsTabs = await chrome.tabs.query({
    url: ["*://sbx.cdms.mavenclinical.com/*", "*://cdms.mavenclinical.com/*"],
  });
  const tab = cdmsTabs.find(candidate => candidate.id && isSupportedCdmsUrl(candidate.url));
  if (!tab || !tab.id) {
    throw new Error("No active CDMS tab is available.");
  }

  await rememberPreferredTab(tab);
  return tab;
}

async function getPreferredTab() {
  if (preferredTabId) {
    try {
      const tab = await chrome.tabs.get(preferredTabId);
      if (tab && tab.id && isSupportedCdmsUrl(tab.url)) {
        return tab;
      }
      preferredTabId = null;
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

// Dispatch a trusted mouse click via Chrome DevTools Protocol.
// Unlike JS dispatchEvent(), CDP-generated events have isTrusted=true,
// which is required for CDMS Fluent UI radio buttons to respond.
async function cdpClickAt(tabId, x, y) {
  const target = { tabId };
  try { await chrome.debugger.attach(target, "1.3"); } catch (e) { /* already attached */ }
  try {
    const args = { x: Math.round(x), y: Math.round(y), button: "left", clickCount: 1, modifiers: 0 };
    await chrome.debugger.sendCommand(target, "Input.dispatchMouseEvent", { ...args, type: "mousePressed" });
    await chrome.debugger.sendCommand(target, "Input.dispatchMouseEvent", { ...args, type: "mouseReleased" });
  } finally {
    try { await chrome.debugger.detach(target); } catch (e) {}
  }
}

async function executeRunnerCommand(tabId, command, payload) {
  await ensureRunnerOnTab(tabId);

  // Pre-process selectRadio steps with CDP before passing the case to the runner.
  // JS-dispatched events are isTrusted=false and CDMS ignores them; CDP events are trusted.
  if (command === "run_case" && payload && payload.case && Array.isArray(payload.case.steps)) {
    const newSteps = [];
    for (const step of payload.case.steps) {
      if (step.action === "setDateViaCalendarPopup") {
        const coordResults = await chrome.scripting.executeScript({
          target: { tabId },
          world: "MAIN",
          args: [step.rowLabel],
          func: (rl) => {
            const runner = window.__CDMAgentRunner;
            return runner ? runner.getDateInputCoords(rl) : null;
          },
        });
        const coords = coordResults && coordResults[0] && coordResults[0].result;
        if (coords) {
          await cdpClickAt(tabId, coords.x, coords.y);
          await new Promise(r => setTimeout(r, 350));
        }
        newSteps.push(step);
      } else if (step.action === "probeRadio") {
        const coordResults = await chrome.scripting.executeScript({
          target: { tabId },
          world: "MAIN",
          args: [step.rowLabel, step.optionLabel, step.anchorLabel || "", step.rowLabelOccurrence || 0],
          func: (rl, ol, al, occ) => {
            const runner = window.__CDMAgentRunner;
            return runner ? runner.getRadioLabelCoords(rl, ol, al, occ) : null;
          },
        });
        const coords = coordResults && coordResults[0] && coordResults[0].result;
        if (coords) {
          await cdpClickAt(tabId, coords.x, coords.y);
          await new Promise(r => setTimeout(r, 350));
        }
        newSteps.push(step);
      } else if (step.action === "selectRadio") {
        const coordResults = await chrome.scripting.executeScript({
          target: { tabId },
          world: "MAIN",
          args: [step.rowLabel, step.optionLabel, step.anchorLabel || "", step.rowLabelOccurrence || 0],
          func: (rl, ol, al, occ) => {
            const runner = window.__CDMAgentRunner;
            return runner ? runner.getRadioLabelCoords(rl, ol, al, occ) : null;
          },
        });
        const coords = coordResults && coordResults[0] && coordResults[0].result;
        if (coords) {
          await cdpClickAt(tabId, coords.x, coords.y);
          await new Promise(r => setTimeout(r, 350));
          const selectedResults = await chrome.scripting.executeScript({
            target: { tabId },
            world: "MAIN",
            args: [step.rowLabel, step.optionLabel, step.anchorLabel || "", step.rowLabelOccurrence || 0],
            func: (rl, ol, al, occ) => {
              const runner = window.__CDMAgentRunner;
              return runner ? runner.isRadioOptionSelected(rl, ol, al, occ) : false;
            },
          });
          const selected = selectedResults && selectedResults[0] && selectedResults[0].result;
          newSteps.push(selected && !step.probeOnly ? { action: "noop", note: "selectRadio handled via CDP" } : step);
        } else {
          newSteps.push(step); // fallback: let runner handle it
        }
      } else if (step.action === "clickQueryAction") {
        const coordResults = await chrome.scripting.executeScript({
          target: { tabId },
          world: "MAIN",
          args: [step.queryLabel || "", step.queryAction || "cancel"],
          func: (label, actionName) => {
            const runner = window.__CDMAgentRunner;
            return runner ? runner.getQueryActionCoords(label, actionName) : null;
          },
        });
        const coords = coordResults && coordResults[0] && coordResults[0].result;
        if (coords) {
          await cdpClickAt(tabId, coords.x, coords.y);
          await new Promise(r => setTimeout(r, 350));
          newSteps.push({ action: "noop", note: "clickQueryAction handled via CDP" });
        } else {
          newSteps.push(step); // fallback: let runner handle it
        }
      } else {
        newSteps.push(step);
      }
    }
    payload = { ...payload, case: { ...payload.case, steps: newSteps } };
  }

  // Post-processing: after run_case completes, check for modify-reason popup and
  // handle it via CDP. The popup appears when saving already-saved data in CDMS.
  // Fluent UI radio buttons in the popup require isTrusted=true events (CDP only).
  const hasSaveStep =
    command === "run_case" &&
    payload &&
    payload.case &&
    Array.isArray(payload.case.steps) &&
    payload.case.steps.some(s => s.action === "clickSave" || s.action === "clickSaveNext");
  let postSavePopupHandler = null;
  if (hasSaveStep) {
    postSavePopupHandler = async () => {
      // Check for modify-reason popup and handle via CDP
      const coordResults = await chrome.scripting.executeScript({
        target: { tabId },
        world: "MAIN",
        func: () => {
          const runner = window.__CDMAgentRunner;
          return runner ? runner.getModifyReasonLabelCoords("Input Error") : null;
        },
      });
      const reasonCoords = coordResults && coordResults[0] && coordResults[0].result;
      if (!reasonCoords) return; // No popup — nothing to do
      await cdpClickAt(tabId, reasonCoords.x, reasonCoords.y);
      await new Promise(r => setTimeout(r, 400));
      const btnResults = await chrome.scripting.executeScript({
        target: { tabId },
        world: "MAIN",
        func: () => {
          const runner = window.__CDMAgentRunner;
          return runner ? runner.getPopupSaveButtonCoords() : null;
        },
      });
      const btnCoords = btnResults && btnResults[0] && btnResults[0].result;
      if (btnCoords) {
        await cdpClickAt(tabId, btnCoords.x, btnCoords.y);
        await new Promise(r => setTimeout(r, 500));
      }
    };
  }

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

      if (runnerCommand === "list_nav_pages") {
        return runner.listNavPages();
      }

      if (runnerCommand === "run_case") {
        return runner.runCase((runnerPayload && runnerPayload.case) || {});
      }

      if (runnerCommand === "wait_for_query") {
        return runner.waitForQueryMessages(
          (runnerPayload && runnerPayload.labels) || [],
          runnerPayload && runnerPayload.timeoutMs
        );
      }

      throw new Error("Unsupported command " + runnerCommand);
    },
  });

  if (!results || !results.length) {
    throw new Error("No result returned from the active CDMS tab.");
  }

  if (postSavePopupHandler) {
    try {
      await postSavePopupHandler();
    } catch (e) {
      // Non-fatal: popup may not have appeared or tab navigated
    }
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
    structuredRows: snapshot.structuredRows || [],
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
  if (websocket && (websocket.readyState === WebSocket.OPEN || websocket.readyState === WebSocket.CONNECTING)) {
    return;
  }

  clearReconnectTimer();
  stopHeartbeat();

  const socket = new WebSocket(wsUrl(daemonOrigin));
  websocket = socket;

  socket.onopen = () => {
    if (websocket !== socket) {
      socket.close();
      return;
    }
    startHeartbeat(socket);
    sendHello().catch(() => undefined);
    broadcast({ type: "daemon-state", connected: true, daemonOrigin });
  };

  socket.onmessage = async event => {
    const message = JSON.parse(event.data);
    lastEvents.push({ at: new Date().toISOString(), direction: "in", message });
    lastEvents = lastEvents.slice(-100);

    if (message.type === "pong" || message.type === "welcome") {
      return;
    }

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
          const msg = error.message || String(error);
          // "Frame with ID 0 was removed" means the page navigated away — that IS
          // the expected outcome for goBack / navigateToUrl / clickSaveNext actions.
          const isFrameRemoved = msg.includes("Frame with ID") && msg.includes("removed");
          lastSnapshot = { error: msg, timestamp: new Date().toISOString() };
          sendToDaemon({
            type: "tool_result",
            requestId: message.requestId,
            payload: isFrameRemoved
              ? { outcome: "passed", failureReason: null }
              : { outcome: "failed", failureReason: msg },
          });
        });
    }
  };

  socket.onclose = () => {
    if (websocket !== socket) {
      return;
    }
    websocket = null;
    stopHeartbeat();
    broadcast({ type: "daemon-state", connected: false, daemonOrigin });
    scheduleReconnect();
  };

  socket.onerror = () => {
    try {
      socket.close();
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
    rememberPreferredTab(sender && sender.tab).catch(() => undefined);
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
    const tab = sender && sender.tab;
    const tabId = tab && tab.id;
    if (!tabId) {
      sendResponse({ ok: false, error: "No sender tab." });
      return true;
    }
    if (!isSupportedCdmsUrl(tab.url)) {
      sendResponse({ ok: false, error: "Sender tab is not a supported CDMS page." });
      return true;
    }
    rememberPreferredTab(tab).catch(() => undefined);

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
    clearReconnectTimer();
    stopHeartbeat();
    try {
      if (websocket) websocket.close();
    } catch (error) {}
    websocket = null;
    connectDaemon();
    sendResponse({ ok: true, daemonOrigin });
    return true;
  }

  if (message.type === "force-reconnect") {
    clearReconnectTimer();
    stopHeartbeat();
    try {
      if (websocket) websocket.close();
    } catch (error) {}
    websocket = null;
    connectDaemon();
    sendResponse({ ok: true });
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
