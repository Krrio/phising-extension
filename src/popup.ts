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
initAutonomyLevel();

async function testCall() {
  const test_data = {
    content: "Urgent action required, verify your account",
    signals: {
      suspiciousPhrases: ["urgent action"],
      linkMismatches: [],
      suspiciousDomains: [],
    },
  };

  const answer = await fetch("http://localhost:8000/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(test_data),
  });

  const result = await answer.json();
  console.log("Backend mowi:", result);
}

initToggle();
testCall();
