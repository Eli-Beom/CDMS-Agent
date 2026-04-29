(async function contentScriptBridge() {
  const SNAPSHOT_INTERVAL_MS = 5000;

  async function syncSnapshotSafely() {
    try {
      await chrome.runtime.sendMessage({ type: "sync-active-tab-snapshot" });
    } catch (error) {
      return;
    }
  }

  await chrome.runtime.sendMessage({ type: "page-ready" });
  await syncSnapshotSafely();
  setInterval(syncSnapshotSafely, SNAPSHOT_INTERVAL_MS);
})();
