import { afterEach, describe, expect, test, vi } from "vitest";
import {
  createStoredOrganizationPolicy,
  importOrganizationPolicyFile,
  isStoredOrganizationPolicy,
  loadOrganizationPolicy,
  MAX_ORGANIZATION_POLICY_BYTES,
  ORGANIZATION_POLICY_STORAGE_KEY,
  OrganizationPolicyError,
  removeOrganizationPolicy,
  validateStoredOrganizationPolicy,
} from "./organizationPolicy";

const LOADED_AT = new Date("2026-08-17T12:00:00.000Z");

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("createStoredOrganizationPolicy", () => {
  test("accepts .md and .txt extensions case-insensitively and hashes raw bytes", async () => {
    const policy = await createStoredOrganizationPolicy(
      new File(["hello"], "SECURITY.MD"),
      LOADED_AT,
    );

    expect(policy).toEqual({
      schemaVersion: 1,
      content: "hello",
      fileName: "SECURITY.MD",
      loadedAt: "2026-08-17T12:00:00.000Z",
      sizeBytes: 5,
      contentHash:
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
    });

    await expect(
      createStoredOrganizationPolicy(
        new File(["policy"], "security.TxT"),
        LOADED_AT,
      ),
    ).resolves.toMatchObject({ content: "policy", fileName: "security.TxT" });
  });

  test("accepts and removes a leading UTF-8 BOM", async () => {
    const bytes = new Uint8Array([0xef, 0xbb, 0xbf, 0x70, 0x6f, 0x6c]);
    const policy = await createStoredOrganizationPolicy(
      new File([bytes], "policy.txt"),
      LOADED_AT,
    );

    expect(policy.content).toBe("pol");
    expect(policy.sizeBytes).toBe(6);
  });

  test.each([
    ["policy.pdf", new File(["text"], "policy.pdf"), "unsupported_file_type"],
    [
      "NUL file name",
      new File(["text"], "policy\0.md"),
      "invalid_file_name",
    ],
    [
      "oversized file name",
      new File(["text"], `${"a".repeat(253)}.md`),
      "invalid_file_name",
    ],
    ["empty", new File([], "policy.md"), "empty_content"],
    ["whitespace", new File([" \n\t"], "policy.txt"), "empty_content"],
    [
      "BOM only",
      new File([new Uint8Array([0xef, 0xbb, 0xbf])], "policy.md"),
      "empty_content",
    ],
    [
      "invalid UTF-8",
      new File([new Uint8Array([0xc3, 0x28])], "policy.txt"),
      "invalid_utf8",
    ],
    ["NUL", new File(["allow\0deny"], "policy.md"), "contains_nul"],
    [
      "oversized",
      new File(
        [new Uint8Array(MAX_ORGANIZATION_POLICY_BYTES + 1)],
        "policy.txt",
      ),
      "file_too_large",
    ],
  ])("rejects %s files", async (_label, file, expectedCode) => {
    await expect(createStoredOrganizationPolicy(file, LOADED_AT)).rejects.toMatchObject({
      name: "OrganizationPolicyError",
      code: expectedCode as OrganizationPolicyError["code"],
    } satisfies Partial<OrganizationPolicyError>);
  });

  test("accepts a file exactly at the 50 KiB boundary", async () => {
    const file = new File(
      ["x".repeat(MAX_ORGANIZATION_POLICY_BYTES)],
      "policy.txt",
    );

    await expect(
      createStoredOrganizationPolicy(file, LOADED_AT),
    ).resolves.toMatchObject({ sizeBytes: MAX_ORGANIZATION_POLICY_BYTES });
  });
});

describe("organization policy storage", () => {
  test("validates persisted policy data and rejects oversized content", async () => {
    const policy = await createStoredOrganizationPolicy(
      new File(["policy"], "policy.txt"),
      LOADED_AT,
    );

    expect(validateStoredOrganizationPolicy(policy)).toBe(policy);
    expect(
      validateStoredOrganizationPolicy({
        ...policy,
        content: "x".repeat(MAX_ORGANIZATION_POLICY_BYTES + 1),
      }),
    ).toBeNull();
    expect(
      validateStoredOrganizationPolicy({
        ...policy,
        sizeBytes: policy.sizeBytes + 1,
      }),
    ).toBeNull();
  });

  test("imports, loads and removes one policy under the exported key", async () => {
    let value: unknown;
    const get = vi.fn(async () => ({
      [ORGANIZATION_POLICY_STORAGE_KEY]: value,
    }));
    const set = vi.fn(async (items: Record<string, unknown>) => {
      value = items[ORGANIZATION_POLICY_STORAGE_KEY];
    });
    const remove = vi.fn(async () => {
      value = undefined;
    });
    vi.stubGlobal("chrome", { storage: { local: { get, set, remove } } });

    const imported = await importOrganizationPolicyFile(
      new File(["# Company policy"], "policy.md"),
    );

    expect(isStoredOrganizationPolicy(imported)).toBe(true);
    await expect(loadOrganizationPolicy()).resolves.toEqual(imported);

    await removeOrganizationPolicy();
    await expect(loadOrganizationPolicy()).resolves.toBeNull();
  });

  test("rejects malformed stored data instead of silently using it", async () => {
    vi.stubGlobal("chrome", {
      storage: {
        local: {
          get: vi.fn(async () => ({
            [ORGANIZATION_POLICY_STORAGE_KEY]: {
              schemaVersion: 1,
              content: "",
            },
          })),
        },
      },
    });

    await expect(loadOrganizationPolicy()).rejects.toMatchObject({
      code: "invalid_stored_policy",
    });
  });

  test("rejects stored content that does not match its SHA-256 identity", async () => {
    const original = await createStoredOrganizationPolicy(
      new File(["policy A"], "policy.md"),
      LOADED_AT,
    );
    const tampered = {
      ...original,
      content: "policy B",
      // Keep the byte size and the old, correctly shaped hash. Structural
      // validation alone must not make this a trusted cache revision.
      sizeBytes: new TextEncoder().encode("policy B").byteLength,
    };
    vi.stubGlobal("chrome", {
      storage: {
        local: {
          get: vi.fn(async () => ({
            [ORGANIZATION_POLICY_STORAGE_KEY]: tampered,
          })),
        },
      },
    });

    await expect(loadOrganizationPolicy()).rejects.toMatchObject({
      code: "invalid_stored_policy",
    });
  });
});
