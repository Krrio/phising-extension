import Chart from "chart.js/auto";

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
