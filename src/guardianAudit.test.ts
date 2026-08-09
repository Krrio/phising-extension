import { afterEach, describe, expect, test, vi } from "vitest";
import {
  appendGuardianAuditEntry,
  createGuardianAuditEntry,
} from "./guardianAudit";
import type { AnalyzeResult, GuardianAuditEntry } from "./messages";

const verdict: AnalyzeResult = {
  trustScore: 12,
  verdict: "phishing",
  confidence: 0.97,
  reasoning: "Wiadomość wyłudza dane logowania.",
  categories: ["credential_request", "urgency"],
};

function makeEntry(
  action: GuardianAuditEntry["action"],
  timestamp: string,
): GuardianAuditEntry {
  return createGuardianAuditEntry(
    action,
    verdict,
    "Pilnie zaloguj się do konta.",
    "https://example.com/inbox",
    timestamp,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("createGuardianAuditEntry", () => {
  test("normalizes and truncates the content excerpt", () => {
    const entry = createGuardianAuditEntry(
      "hidden",
      verdict,
      `  Pilna\nwiadomość   ${"x".repeat(200)}  `,
      "https://example.com/inbox",
      "2026-08-07T18:00:00.000Z",
    );

    expect(entry).toMatchObject({
      action: "hidden",
      timestamp: "2026-08-07T18:00:00.000Z",
      url: "https://example.com/inbox",
      trustScore: 12,
      confidence: 0.97,
      reasoning: verdict.reasoning,
      categories: verdict.categories,
    });
    expect(entry.excerpt).not.toMatch(/\s{2,}|\n/);
    expect(entry.excerpt).toHaveLength(181);
    expect(entry.excerpt.endsWith("…")).toBe(true);
  });
});

describe("appendGuardianAuditEntry", () => {
  test("serializes concurrent writes so no audit action is lost", async () => {
    let log: GuardianAuditEntry[] = [];
    const get = vi.fn(async () => ({ guardianAuditLog: [...log] }));
    const set = vi.fn(async (values: { guardianAuditLog: GuardianAuditEntry[] }) => {
      log = values.guardianAuditLog;
    });
    vi.stubGlobal("chrome", { storage: { local: { get, set } } });

    const hidden = makeEntry("hidden", "2026-08-07T18:00:00.000Z");
    const revealed = makeEntry("revealed", "2026-08-07T18:01:00.000Z");

    await Promise.all([
      appendGuardianAuditEntry(hidden),
      appendGuardianAuditEntry(revealed),
    ]);

    expect(log).toEqual([revealed, hidden]);
    expect(get).toHaveBeenCalledTimes(2);
    expect(set).toHaveBeenCalledTimes(2);
  });

  test("keeps only the newest 100 entries", async () => {
    let log = Array.from({ length: 100 }, (_, index) =>
      makeEntry("hidden", new Date(index).toISOString()),
    );
    const originalNewest = log[0];
    const get = vi.fn(async () => ({ guardianAuditLog: [...log] }));
    const set = vi.fn(async (values: { guardianAuditLog: GuardianAuditEntry[] }) => {
      log = values.guardianAuditLog;
    });
    vi.stubGlobal("chrome", { storage: { local: { get, set } } });

    const newest = makeEntry("revealed", "2026-08-07T18:02:00.000Z");
    await appendGuardianAuditEntry(newest);

    expect(log).toHaveLength(100);
    expect(log[0]).toEqual(newest);
    expect(log[1]).toEqual(originalNewest);
  });
});
