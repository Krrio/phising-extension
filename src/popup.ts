import {
  importOrganizationPolicyFile,
  loadOrganizationPolicy,
  OrganizationPolicyError,
  removeOrganizationPolicy,
  type StoredOrganizationPolicy,
} from "./organizationPolicy";

const POLICY_PREVIEW_CHARACTER_LIMIT = 3_000;

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
    | "full"
    | "guardian";
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

async function initApiKey(): Promise<void> {
  const inputElement = document.getElementById("apiKey");

  if (!(inputElement instanceof HTMLInputElement)) {
    return;
  }

  const stored = (await chrome.storage.local.get("apiKey")) as {
    apiKey?: string;
  };

  inputElement.value = stored.apiKey ?? "";

  inputElement.addEventListener("change", async () => {
    await chrome.storage.local.set({ apiKey: inputElement.value });
  });
}

function formatPolicySize(sizeBytes: number): string {
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  return `${(sizeBytes / 1024).toFixed(1)} KiB`;
}

function formatPolicyLoadedAt(loadedAt: string): string {
  return new Intl.DateTimeFormat("pl-PL", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(loadedAt));
}

function policyErrorMessage(error: unknown): string {
  if (error instanceof OrganizationPolicyError) return error.message;
  return "Nie udało się zapisać polityki. Spróbuj ponownie.";
}

async function initOrganizationPolicy(): Promise<void> {
  const section = document.querySelector<HTMLElement>(
    "section[aria-labelledby='organizationPolicyHeading']",
  );
  const badge = document.getElementById("organizationPolicyBadge");
  const emptyState = document.getElementById("organizationPolicyEmpty");
  const loadedState = document.getElementById("organizationPolicyLoaded");
  const fileInput = document.getElementById("organizationPolicyFile");
  const removeButton = document.getElementById("removeOrganizationPolicy");
  const removeInvalidButton = document.getElementById(
    "removeInvalidOrganizationPolicy",
  );
  const fileName = document.getElementById("organizationPolicyFileName");
  const size = document.getElementById("organizationPolicySize");
  const loadedAt = document.getElementById("organizationPolicyLoadedAt");
  const hash = document.getElementById("organizationPolicyHash");
  const preview = document.getElementById("organizationPolicyPreview");
  const errorRegion = document.getElementById("organizationPolicyError");
  const feedbackRegion = document.getElementById(
    "organizationPolicyFeedback",
  );

  if (
    !section ||
    !badge ||
    !emptyState ||
    !loadedState ||
    !(fileInput instanceof HTMLInputElement) ||
    !(removeButton instanceof HTMLButtonElement) ||
    !(removeInvalidButton instanceof HTMLButtonElement) ||
    !fileName ||
    !size ||
    !loadedAt ||
    !hash ||
    !preview ||
    !errorRegion ||
    !feedbackRegion
  ) {
    return;
  }

  const setError = (message = "") => {
    errorRegion.textContent = message;
    errorRegion.hidden = message.length === 0;
  };

  const announce = (message: string) => {
    feedbackRegion.textContent = "";
    requestAnimationFrame(() => {
      feedbackRegion.textContent = message;
    });
  };

  const renderNoPolicy = (canRemoveInvalidRecord = false) => {
    emptyState.hidden = false;
    loadedState.hidden = true;
    badge.textContent = canRemoveInvalidRecord ? "Błąd" : "Brak";
    badge.className =
      canRemoveInvalidRecord ?
        "rounded-full bg-red-100 px-2 py-1 text-[11px] font-medium text-red-700"
      : "rounded-full bg-zinc-100 px-2 py-1 text-[11px] font-medium text-zinc-600";
    fileName.textContent = "";
    size.textContent = "";
    loadedAt.textContent = "";
    hash.textContent = "";
    hash.removeAttribute("title");
    preview.textContent = "";
    removeInvalidButton.hidden = !canRemoveInvalidRecord;
  };

  const renderLoadedPolicy = (policy: StoredOrganizationPolicy) => {
    emptyState.hidden = true;
    loadedState.hidden = false;
    badge.textContent = "Wczytana";
    badge.className =
      "rounded-full bg-green-100 px-2 py-1 text-[11px] font-medium text-green-700";
    fileName.textContent = policy.fileName;
    size.textContent = formatPolicySize(policy.sizeBytes);
    loadedAt.textContent = formatPolicyLoadedAt(policy.loadedAt);
    hash.textContent = `${policy.contentHash.slice(0, 12)}…`;
    hash.title = policy.contentHash;

    const isTruncated =
      policy.content.length > POLICY_PREVIEW_CHARACTER_LIMIT;
    preview.textContent =
      policy.content.slice(0, POLICY_PREVIEW_CHARACTER_LIMIT) +
      (isTruncated ? "\n\n[… dalsza część ukryta w podglądzie]" : "");
    removeInvalidButton.hidden = true;
  };

  const setBusy = (busy: boolean) => {
    section.setAttribute("aria-busy", String(busy));
    fileInput.disabled = busy;
    removeButton.disabled = busy;
    removeInvalidButton.disabled = busy;
    removeButton.classList.toggle("opacity-50", busy);
    removeButton.classList.toggle("cursor-not-allowed", busy);
    removeInvalidButton.classList.toggle("opacity-50", busy);
    removeInvalidButton.classList.toggle("cursor-not-allowed", busy);
  };

  fileInput.addEventListener("change", async () => {
    const file = fileInput.files?.[0];
    if (!file) return;

    setError();
    setBusy(true);
    badge.textContent = "Wczytywanie…";

    try {
      const policy = await importOrganizationPolicyFile(file);
      renderLoadedPolicy(policy);
      announce(`Wczytano politykę ${policy.fileName}.`);
    } catch (error) {
      setError(policyErrorMessage(error));

      try {
        const existingPolicy = await loadOrganizationPolicy();
        if (existingPolicy) renderLoadedPolicy(existingPolicy);
        else renderNoPolicy();
      } catch {
        renderNoPolicy(true);
      }
    } finally {
      fileInput.value = "";
      setBusy(false);
    }
  });

  removeButton.addEventListener("click", async () => {
    const confirmed = window.confirm(
      "Czy na pewno chcesz usunąć politykę organizacji?",
    );
    if (!confirmed) return;

    setError();
    setBusy(true);

    try {
      await removeOrganizationPolicy();
      renderNoPolicy();
      announce("Usunięto politykę organizacji.");
    } catch (error) {
      setError(policyErrorMessage(error));
    } finally {
      setBusy(false);
    }
  });

  removeInvalidButton.addEventListener("click", async () => {
    const confirmed = window.confirm(
      "Czy na pewno chcesz usunąć uszkodzony zapis polityki?",
    );
    if (!confirmed) return;

    setError();
    setBusy(true);
    try {
      await removeOrganizationPolicy();
      renderNoPolicy();
      announce("Usunięto uszkodzony zapis polityki organizacji.");
    } catch (error) {
      setError(policyErrorMessage(error));
      renderNoPolicy(true);
    } finally {
      setBusy(false);
    }
  });

  setBusy(true);
  try {
    const policy = await loadOrganizationPolicy();
    if (policy) renderLoadedPolicy(policy);
    else renderNoPolicy();
  } catch (error) {
    renderNoPolicy(true);
    setError(policyErrorMessage(error));
  } finally {
    setBusy(false);
  }
}

initDashboardButton();

initAutonomyLevel();

initToggle();

void initApiKey();

void initOrganizationPolicy();
