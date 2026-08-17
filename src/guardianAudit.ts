import type {
  AnalyzeResult,
  GuardianAuditEntry,
  GuardianAuditMessageResponse,
  GuardianAuditRequestMessage,
} from "./messages";

const AUDIT_KEY = "guardianAuditLog";
const AUDIT_MAX_ENTRIES = 100;
const AUDIT_EXCERPT_LENGTH = 180;

let auditWriteQueue: Promise<void> = Promise.resolve();

export function createGuardianAuditEntry(
  action: GuardianAuditEntry["action"],
  verdict: AnalyzeResult,
  content: string,
  url: string,
  timestamp = new Date().toISOString(),
): GuardianAuditEntry {
  const compactContent = content.replace(/\s+/g, " ").trim();
  const excerpt =
    compactContent.length > AUDIT_EXCERPT_LENGTH
      ? `${compactContent.slice(0, AUDIT_EXCERPT_LENGTH)}…`
      : compactContent;

  return {
    timestamp,
    url,
    action,
    trustScore: verdict.trustScore,
    confidence: verdict.confidence,
    reasoning: verdict.reasoning,
    categories: [...verdict.categories],
    excerpt,
    policyAssessment:
      verdict.policyAssessment === null ?
        null
      : { ...verdict.policyAssessment },
  };
}

export function persistGuardianAuditEntry(
  entry: GuardianAuditEntry,
): Promise<void> {
  auditWriteQueue = auditWriteQueue.then(async () => {
    try {
      const stored = (await chrome.storage.local.get(AUDIT_KEY)) as {
        guardianAuditLog?: GuardianAuditEntry[];
      };
      const log =
        Array.isArray(stored.guardianAuditLog) ?
          stored.guardianAuditLog.filter(isGuardianAuditEntry)
        : [];

      await chrome.storage.local.set({
        [AUDIT_KEY]: [entry, ...log].slice(0, AUDIT_MAX_ENTRIES),
      });
    } catch (error) {
      console.error("[Guardian] nie udało się zapisać audytu:", error);
    }
  });

  return auditWriteQueue;
}

export async function appendGuardianAuditEntry(
  entry: GuardianAuditEntry,
): Promise<void> {
  const message: GuardianAuditRequestMessage = {
    type: "APPEND_GUARDIAN_AUDIT",
    entry,
  };

  try {
    const response = (await chrome.runtime.sendMessage(
      message,
    )) as GuardianAuditMessageResponse | undefined;
    if (!response?.ok) {
      throw new Error(response?.error ?? "Brak odpowiedzi service workera.");
    }
  } catch (error) {
    console.error("[Guardian] nie udało się przekazać wpisu audytu:", error);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function isGuardianAuditEntry(value: unknown): value is GuardianAuditEntry {
  if (!isRecord(value)) return false;
  const policy = value.policyAssessment;
  const validPolicy =
    policy === undefined ||
    policy === null ||
    (isRecord(policy) &&
      typeof policy.violated === "boolean" &&
      ["none", "supporting", "material"].includes(String(policy.influence)) &&
      (typeof policy.summary === "string" || policy.summary === null) &&
      typeof policy.policyHash === "string" &&
      typeof policy.policyFileName === "string");

  let validUrl = false;
  try {
    new URL(String(value.url));
    validUrl = true;
  } catch {
    validUrl = false;
  }

  return (
    typeof value.timestamp === "string" &&
    !Number.isNaN(Date.parse(value.timestamp)) &&
    typeof value.url === "string" &&
    validUrl &&
    (value.action === "hidden" || value.action === "revealed") &&
    typeof value.trustScore === "number" &&
    value.trustScore >= 0 &&
    value.trustScore <= 100 &&
    typeof value.confidence === "number" &&
    value.confidence >= 0 &&
    value.confidence <= 1 &&
    typeof value.reasoning === "string" &&
    Array.isArray(value.categories) &&
    value.categories.every((category) => typeof category === "string") &&
    typeof value.excerpt === "string" &&
    validPolicy
  );
}
