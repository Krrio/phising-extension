import type {
  AnalyzeMessageResponse,
  AnalyzePayload,
  AnalyzeRequestMessage,
  AnalyzeResult,
  LinkMismatchSignal,
} from "./messages";

const ANALYZE_URL = "http://127.0.0.1:8000/analyze";
const MAX_CONTENT_LENGTH = 100_000;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isLinkMismatch(value: unknown): value is LinkMismatchSignal {
  return (
    isRecord(value) &&
    typeof value.text === "string" &&
    typeof value.href === "string"
  );
}

function isAnalyzePayload(value: unknown): value is AnalyzePayload {
  if (!isRecord(value) || !isRecord(value.signals)) return false;

  return (
    typeof value.content === "string" &&
    value.content.length <= MAX_CONTENT_LENGTH &&
    isStringArray(value.signals.suspiciousPhrases) &&
    Array.isArray(value.signals.linkMismatches) &&
    value.signals.linkMismatches.every(isLinkMismatch) &&
    isStringArray(value.signals.suspiciousDomains)
  );
}

function isAnalyzeRequestMessage(
  value: unknown,
): value is AnalyzeRequestMessage {
  return (
    isRecord(value) &&
    value.type === "ANALYZE" &&
    isAnalyzePayload(value.payload)
  );
}

async function requestAnalysis(payload: AnalyzePayload): Promise<AnalyzeResult> {
  const response = await fetch(ANALYZE_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(`Backend returned status ${response.status}`);
  }

  return (await response.json()) as AnalyzeResult;
}

chrome.runtime.onMessage.addListener((message: unknown, sender, sendResponse) => {
  if (!isAnalyzeRequestMessage(message)) return false;

  if (sender.id !== chrome.runtime.id) {
    const response: AnalyzeMessageResponse = {
      ok: false,
      error: "Unauthorized message sender.",
    };
    sendResponse(response);
    return false;
  }

  void requestAnalysis(message.payload)
    .then((data) => {
      const response: AnalyzeMessageResponse = { ok: true, data };
      sendResponse(response);
    })
    .catch((error: unknown) => {
      const response: AnalyzeMessageResponse = {
        ok: false,
        error: error instanceof Error ? error.message : "Analysis failed.",
      };
      sendResponse(response);
    });

  return true;
});
