export function renderResult(resultBox: HTMLElement, result: any) {
  resultBox.style.display = "block";
  resultBox.innerHTML = "";

  const sep = document.createElement("hr");
  sep.style.border = "none";
  sep.style.borderTop = "1px solid #e4e4e7";
  sep.style.margin = "0 0 12px 0";
  resultBox.appendChild(sep);

  const verdict = document.createElement("div");
  verdict.textContent = result.verdict.toUpperCase();
  verdict.style.fontWeight = "600";
  verdict.style.fontSize = "16px";
  verdict.style.marginBottom = "6px";
  verdict.style.color = verdictColor(result.verdict);
  resultBox.appendChild(verdict);

  const score = document.createElement("div");
  score.textContent = `Trust score: ${result.trustScore}/100`;
  score.style.fontSize = "13px";
  score.style.marginBottom = "8px";
  resultBox.appendChild(score);

  const reasoning = document.createElement("div");
  reasoning.textContent = result.reasoning;
  reasoning.style.fontSize = "13px";
  reasoning.style.color = "#52525b";
  reasoning.style.lineHeight = "1.4";
  resultBox.appendChild(reasoning);
}

function verdictColor(verdict: string): string {
  if (verdict === "phishing") return "#dc2626";
  if (verdict === "suspicious") return "#ca8a04";
  return "#16a34a";
}
