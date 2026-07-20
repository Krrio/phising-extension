async function initToggle() {
  const toggle = document.getElementById("enabledToggle") as HTMLInputElement;
  if (!toggle) return;

  const stored = await chrome.storage.local.get("enabled");
  toggle.checked = Boolean(stored.enabled ?? true);

  toggle.addEventListener("change", async () => {
    await chrome.storage.local.set({ enabled: toggle.checked });
  });
}

async function initAutonomyLevel() {
  const select = document.getElementById("autonomyLevel") as HTMLSelectElement;

  if (!select) return;

  const stored = await chrome.storage.local.get("autonomyLevel");
  const level = (stored.autonomyLevel ?? "limited") as
    | "limited"
    | "standard"
    | "full";
  select.value = level;

  select.addEventListener("change", async () => {
    await chrome.storage.local.set({ autonomyLevel: select.value });
  });
}

function initDashboardButton(): void {
  const button = document.getElementById("openDashboard");

  if (!(button instanceof HTMLButtonElement)) {
    return;
  }

  button.addEventListener("click", async () => {
    await chrome.tabs.create({
      url: chrome.runtime.getURL("dashboard.html"),
    });

    window.close();
  });
}

initDashboardButton();

initAutonomyLevel();

initToggle();
