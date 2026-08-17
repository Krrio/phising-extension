import Chart from "chart.js/auto";
import type { GuardianAuditEntry } from "./messages";
import { isGuardianAuditEntry } from "./guardianAudit";

const API_BASE_URL = "http://127.0.0.1:8000";

interface TrustScorePoint {
  timestamp: string;
  trustScore: number;
}
interface VerdictDistribution {
  safe: number;
  suspicious: number;
  phishing: number;
}

interface CategoryDistribution {
  credential_request: number;
  urgency: number;
  impersonation: number;
  suspicious_link: number;
  suspicious_domain: number;
  financial: number;
}

const dateFormatter = new Intl.DateTimeFormat("pl-PL", {
  dateStyle: "short",
  timeStyle: "short",
});

function getCanvas(id: string): HTMLCanvasElement {
  const element = document.getElementById(id);

  if (!(element instanceof HTMLCanvasElement)) {
    throw new Error(`Could not finde canvas element: ${id}`);
  }

  return element;
}

function renderTrustScoreChart(points: TrustScorePoint[]): void {
  new Chart(getCanvas("trustScoreChart"), {
    type: "line",
    data: {
      labels: points.map((point) =>
        dateFormatter.format(new Date(point.timestamp)),
      ),
      datasets: [
        {
          label: "Trust score",
          data: points.map((point) => point.trustScore),
          borderColor: "#16a34a",
          backgroundColor: "rgba(22, 163, 74, 0.12)",
          borderWidth: 2,
          pointRadius: 4,
          pointHoverRadius: 6,
          tension: 0.25,
          fill: true,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: false,
        },
      },
      scales: {
        y: {
          min: 0,
          max: 100,
          ticks: {
            stepSize: 20,
          },
        },
        x: {
          grid: {
            display: false,
          },
        },
      },
    },
  });
}

function renderVerdictChart(data: VerdictDistribution): void {
  const verdicts: Array<keyof VerdictDistribution> = [
    "safe",
    "suspicious",
    "phishing",
  ] as const;

  new Chart(getCanvas("verdictChart"), {
    type: "doughnut",
    data: {
      labels: verdicts,
      datasets: [
        {
          data: verdicts.map((verdict) => data[verdict]),
          backgroundColor: ["#16a34a", "#f59e0b", "#dc2626"],
          borderColor: "#ffffff",
          borderWidth: 2,
          hoverOffset: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: "62%",
      plugins: {
        legend: {
          position: "bottom",
          labels: {
            usePointStyle: true,
            padding: 20,
          },
        },
      },
    },
  });
}

function renderCategoryChart(data: CategoryDistribution): void {
  const categories: Array<keyof CategoryDistribution> = [
    "credential_request",
    "urgency",
    "impersonation",
    "suspicious_link",
    "suspicious_domain",
    "financial",
  ];

  new Chart(getCanvas("categoryChart"), {
    type: "bar",
    data: {
      labels: categories,
      datasets: [
        {
          label: "Liczba analiz",
          data: categories.map((category) => data[category]),
          backgroundColor: [
            "#dc2626",
            "#f59e0b",
            "#7c3aed",
            "#2563eb",
            "#0891b2",
            "#db2777",
          ],
          borderRadius: 4,
          borderSkipped: false,
          maxBarThickness: 28,
        },
      ],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: false,
        },
      },
      scales: {
        x: {
          beginAtZero: true,
          ticks: {
            precision: 0,
          },
        },
        y: {
          grid: {
            display: false,
          },
        },
      },
    },
  });
}

async function renderAuditLog(): Promise<void> {
  const container = document.getElementById("auditLog");
  if (!container) return;

  const stored = (await chrome.storage.local.get("guardianAuditLog")) as {
    guardianAuditLog?: GuardianAuditEntry[];
  };
  const log =
    Array.isArray(stored.guardianAuditLog) ?
      stored.guardianAuditLog.filter(isGuardianAuditEntry)
    : [];

  container.innerHTML = "";

  if (log.length === 0) {
    const empty = document.createElement("p");
    empty.className = "text-zinc-500";
    empty.textContent = "Guardian nie podjął jeszcze żadnych działań.";
    container.appendChild(empty);
    return;
  }

  for (const entry of log) {
    container.appendChild(createAuditCard(entry));
  }
}

function createAuditCard(entry: GuardianAuditEntry): HTMLElement {
  const isHidden = entry.action === "hidden";

  const card = document.createElement("div");
  card.className = `rounded-xl border p-4 ${
    isHidden ? "border-red-200 bg-red-50" : "border-zinc-200 bg-white"
  }`;

  const header = document.createElement("div");
  header.className = "flex items-center justify-between mb-2";

  const action = document.createElement("span");
  action.className = `text-sm font-semibold ${
    isHidden ? "text-red-700" : "text-zinc-600"
  }`;
  action.textContent = isHidden ? "Ukryto treść" : "Użytkownik odsłonił";
  header.appendChild(action);

  const time = document.createElement("span");
  time.className = "text-xs text-zinc-500";
  time.textContent = new Intl.DateTimeFormat("pl-PL", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(entry.timestamp));
  header.appendChild(time);

  card.appendChild(header);

  const excerpt = document.createElement("div");
  excerpt.className = "text-sm text-zinc-800 mb-2 italic";
  excerpt.textContent = `„${entry.excerpt}”`;
  card.appendChild(excerpt);

  const reasoning = document.createElement("div");
  reasoning.className = "text-sm text-zinc-600 mb-2";
  reasoning.textContent = entry.reasoning;
  card.appendChild(reasoning);

  if (entry.policyAssessment) {
    const policy = document.createElement("div");
    policy.className = `mb-2 rounded-lg px-2.5 py-1.5 text-xs ${
      entry.policyAssessment.violated ?
        "bg-amber-100 text-amber-800"
      : "bg-zinc-100 text-zinc-600"
    }`;
    policy.textContent =
      entry.policyAssessment.violated ?
        `Polityka ${entry.policyAssessment.policyFileName}: ${entry.policyAssessment.summary ?? "wykryto naruszenie"}`
      : `Analiza z polityką: ${entry.policyAssessment.policyFileName}`;
    card.appendChild(policy);
  }

  const meta = document.createElement("div");
  meta.className = "flex items-center gap-3 text-xs text-zinc-500";
  meta.textContent = `Trust score: ${entry.trustScore}/100 · pewność ${Math.round(
    entry.confidence * 100,
  )}% · ${new URL(entry.url).hostname}`;
  card.appendChild(meta);

  if (entry.categories.length > 0) {
    const cats = document.createElement("div");
    cats.className = "flex flex-wrap gap-2 mt-2";
    for (const category of entry.categories) {
      const tag = document.createElement("span");
      tag.className =
        "rounded-full bg-zinc-200 px-2 py-0.5 text-xs text-zinc-700";
      tag.textContent = category;
      cats.appendChild(tag);
    }
    card.appendChild(cats);
  }

  return card;
}

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`);

  if (!response.ok) {
    throw new Error(`API returned status ${response.status}`);
  }

  return response.json() as Promise<T>;
}

async function initDashboard(): Promise<void> {
  const status = document.getElementById("dashboardStatus");

  try {
    const [trustScores, verdicts, categories] = await Promise.all([
      fetchJson<TrustScorePoint[]>("/history/trust-score"),
      fetchJson<VerdictDistribution>("/history/verdicts"),
      fetchJson<CategoryDistribution>("/history/categories"),
    ]);

    renderTrustScoreChart(trustScores);
    renderVerdictChart(verdicts);
    renderCategoryChart(categories);

    console.log({ trustScores, verdicts, categories });

    if (status) {
      status.textContent = `${trustScores.length} saved analysis`;
    }
  } catch (error) {
    console.log(error);

    if (status) {
      status.textContent = "Could not fetch the data";
      status.classList.add("text-red-600");
    }
  }
}

void initDashboard();
void renderAuditLog();
