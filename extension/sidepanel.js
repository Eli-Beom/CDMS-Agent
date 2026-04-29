async function refreshState() {
  const state = await chrome.runtime.sendMessage({ type: "get-state" });
  document.getElementById("daemonOrigin").value = state.daemonOrigin || "http://127.0.0.1:3100";
  document.getElementById("status").textContent = state.connected ? "Connected" : "Disconnected";
  document.getElementById("status").className = state.connected ? "status status--ok" : "status status--idle";
  document.getElementById("snapshot").textContent = JSON.stringify(state.lastSnapshot || {}, null, 2);
  document.getElementById("events").textContent = JSON.stringify(state.lastEvents || [], null, 2);
}

document.getElementById("saveOrigin").addEventListener("click", async () => {
  const daemonOrigin = document.getElementById("daemonOrigin").value;
  await chrome.runtime.sendMessage({ type: "set-daemon-origin", daemonOrigin });
  refreshState();
});

document.getElementById("refreshState").addEventListener("click", refreshState);

document.getElementById("inspectPage").addEventListener("click", async () => {
  const snapshot = await chrome.runtime.sendMessage({ type: "request-inspect-active-page" });
  document.getElementById("snapshot").textContent = JSON.stringify(snapshot || {}, null, 2);
});

refreshState();
setInterval(refreshState, 3000);
