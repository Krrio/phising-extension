import type { AnalyzeResult, GuardianAuditEntry } from "./messages";

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
  };
}

export function appendGuardianAuditEntry(
  entry: GuardianAuditEntry,
): Promise<void> {
  auditWriteQueue = auditWriteQueue.then(async () => {
    try {
      const stored = (await chrome.storage.local.get(AUDIT_KEY)) as {
        guardianAuditLog?: GuardianAuditEntry[];
      };
      const log = stored.guardianAuditLog ?? [];

      await chrome.storage.local.set({
        [AUDIT_KEY]: [entry, ...log].slice(0, AUDIT_MAX_ENTRIES),
      });
    } catch (error) {
      console.error("[Guardian] nie udało się zapisać audytu:", error);
    }
  });

  return auditWriteQueue;
}
