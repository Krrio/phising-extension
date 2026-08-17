import { afterAll, beforeAll, beforeEach, describe, expect, test, vi } from "vitest";
import type { AnalyzeResult, GuardianRequestMessage } from "./messages";

type RuntimeMessageListener = (
  message: unknown,
  sender: chrome.runtime.MessageSender,
  sendResponse: (response: unknown) => void,
) => boolean | undefined;

const extensionId = "test-extension-id";
const fetchMock = vi.fn();
let runtimeMessageListener: RuntimeMessageListener | undefined;

const verdict: AnalyzeResult = {
  trustScore: 15,
  verdict: "phishing",
  confidence: 0.98,
  reasoning: "Wiadomość próbuje wyłudzić dane logowania.",
  categories: ["credential_request", "suspicious_domain"],
};

const guardianMessage: GuardianRequestMessage = {
  type: "GUARDIAN_ANALYZE",
  payload: {
    content: "Pilnie potwierdź hasło.",
    domains: ["paypa1.com"],
    phrases: ["potwierdź hasło"],
    linkMismatches: [
      { text: "paypal.com", href: "https://paypa1.com/login" },
    ],
  },
};

beforeAll(async () => {
  const addListener = vi.fn((listener: RuntimeMessageListener) => {
    runtimeMessageListener = listener;
  });

  vi.stubGlobal("chrome", {
    runtime: {
      id: extensionId,
      onMessage: { addListener },
    },
    storage: {
      local: { get: vi.fn() },
    },
  });
  vi.stubGlobal("fetch", fetchMock);

  await import("./background");
});

beforeEach(() => {
  fetchMock.mockReset();
});

afterAll(() => {
  vi.unstubAllGlobals();
});

function dispatchGuardianMessage(): {
  keepAlive: boolean | undefined;
  response: Promise<unknown>;
} {
  if (!runtimeMessageListener) {
    throw new Error("Background message listener was not registered.");
  }

  let resolveResponse: (response: unknown) => void = () => undefined;
  const response = new Promise<unknown>((resolve) => {
    resolveResponse = resolve;
  });
  const keepAlive = runtimeMessageListener(
    guardianMessage,
    { id: extensionId } as chrome.runtime.MessageSender,
    resolveResponse,
  );

  return { keepAlive, response };
}

describe("Guardian background flow", () => {
  test("responds even when best-effort history persistence is still pending", async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(JSON.stringify(verdict), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockImplementationOnce(() => new Promise<Response>(() => undefined));

    const { keepAlive, response } = dispatchGuardianMessage();

    expect(keepAlive).toBe(true);
    await expect(response).resolves.toEqual({ ok: true, data: verdict });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8000/guardian/analyze",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(guardianMessage.payload),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8000/history/save",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify(verdict),
      }),
    );
  });

  test("does not write history when Guardian analysis fails", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 502 }));

    const { response } = dispatchGuardianMessage();

    await expect(response).resolves.toEqual({
      ok: false,
      error: "Guardian backend returned status 502",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
