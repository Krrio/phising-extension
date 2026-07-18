import { scanElement } from "./highlight";

const poppinsFonts = [
  { file: "Poppins-Regular.ttf", weight: 400 },
  { file: "Poppins-Medium.ttf", weight: 500 },
  { file: "Poppins-SemiBold.ttf", weight: 600 },
];

export function injectPoppinsFont(): void {
  const styleId = "phishing-extension-poppins-font";

  if (document.getElementById(styleId)) {
    return;
  }

  const style = document.createElement("style");

  style.id = styleId;
  style.textContent = poppinsFonts
    .map(
      ({ file, weight }) => `
        @font-face {
          font-family: "Poppins";
          src: url("${chrome.runtime.getURL(`assets/fonts/${file}`)}") format("truetype");
          font-weight: ${weight};
          font-style: normal;
          font-display: swap;
        }
      `,
    )
    .join("\n");

  (document.head ?? document.documentElement).appendChild(style);
}

export function createWidget(score: number, matches: string[]): void {
  const existingWidget = document.getElementById("phishing-extension-widget");

  if (existingWidget) {
    existingWidget.remove();
  }

  scanElement(document.body);

  const widget = document.createElement("div");

  widget.id = "phishing-extension-widget";
  // widget.innerHTML = `
  //   <strong>Phishing MVP</strong>
  //   <br />
  //   Risk score: ${score}
  //   <br />
  //   Matches: ${matches.length > 0 ? matches.join(", ") : "none"}
  // `;

  // widget.style.position = "fixed";
  // widget.style.right = "20px";
  // widget.style.bottom = "20px";
  // widget.style.zIndex = "999999";
  // widget.style.background = score > 0 ? "#3b0000" : "#111";
  // widget.style.color = "#fff";
  // widget.style.padding = "12px 16px";
  // widget.style.borderRadius = "10px";
  // widget.style.fontSize = "14px";
  // widget.style.fontFamily = "Poppins, sans-serif";
  // widget.style.boxShadow = "0 4px 16px rgba(0,0,0,0.3)";
  // widget.style.maxWidth = "360px";

  document.body.appendChild(widget);
}
