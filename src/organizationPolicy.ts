export const ORGANIZATION_POLICY_STORAGE_KEY = "organizationPolicy";
export const ORGANIZATION_POLICY_SCHEMA_VERSION = 1 as const;
export const MAX_ORGANIZATION_POLICY_BYTES = 50 * 1024;
export const MAX_ORGANIZATION_POLICY_FILE_NAME_LENGTH = 255;

const CONTENT_HASH_PATTERN = /^[a-f0-9]{64}$/;
const ALLOWED_FILE_EXTENSIONS = [".md", ".txt"] as const;

export interface StoredOrganizationPolicy {
  schemaVersion: typeof ORGANIZATION_POLICY_SCHEMA_VERSION;
  content: string;
  fileName: string;
  loadedAt: string;
  sizeBytes: number;
  contentHash: string;
}

export type OrganizationPolicyErrorCode =
  | "unsupported_file_type"
  | "file_too_large"
  | "empty_content"
  | "invalid_utf8"
  | "contains_nul"
  | "invalid_file_name"
  | "invalid_stored_policy";

export class OrganizationPolicyError extends Error {
  constructor(
    readonly code: OrganizationPolicyErrorCode,
    message: string,
  ) {
    super(message);
    this.name = "OrganizationPolicyError";
  }
}

function hasAllowedExtension(fileName: string): boolean {
  const normalizedName = fileName.toLowerCase();
  return ALLOWED_FILE_EXTENSIONS.some((extension) =>
    normalizedName.endsWith(extension),
  );
}

function ensureAllowedFileName(fileName: string): void {
  if (
    !fileName.trim() ||
    fileName.includes("\0") ||
    fileName.length > MAX_ORGANIZATION_POLICY_FILE_NAME_LENGTH
  ) {
    throw new OrganizationPolicyError(
      "invalid_file_name",
      "Nazwa pliku polityki jest nieprawidłowa lub zbyt długa.",
    );
  }
  if (!hasAllowedExtension(fileName)) {
    throw new OrganizationPolicyError(
      "unsupported_file_type",
      "Wybierz plik w formacie .md lub .txt.",
    );
  }
}

function ensureAllowedSize(sizeBytes: number): void {
  if (sizeBytes > MAX_ORGANIZATION_POLICY_BYTES) {
    throw new OrganizationPolicyError(
      "file_too_large",
      "Plik polityki może mieć maksymalnie 50 KiB.",
    );
  }
}

function decodePolicyContent(bytes: ArrayBuffer): string {
  let content: string;

  try {
    content = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    throw new OrganizationPolicyError(
      "invalid_utf8",
      "Plik polityki nie jest poprawnym tekstem UTF-8.",
    );
  }

  // TextDecoder normally consumes a leading UTF-8 BOM. Remove the decoded
  // character as well so this stays deterministic across browser engines.
  if (content.startsWith("\uFEFF")) {
    content = content.slice(1);
  }

  if (content.includes("\0")) {
    throw new OrganizationPolicyError(
      "contains_nul",
      "Plik polityki zawiera niedozwolony znak NUL.",
    );
  }

  if (content.trim().length === 0) {
    throw new OrganizationPolicyError(
      "empty_content",
      "Plik polityki jest pusty lub zawiera tylko białe znaki.",
    );
  }

  return content;
}

async function sha256Hex(bytes: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

async function hashPolicyContent(content: string): Promise<string> {
  const bytes = new TextEncoder().encode(content);
  return sha256Hex(bytes.buffer as ArrayBuffer);
}

export async function createStoredOrganizationPolicy(
  file: File,
  loadedAt = new Date(),
): Promise<StoredOrganizationPolicy> {
  ensureAllowedFileName(file.name);
  ensureAllowedSize(file.size);

  const bytes = await file.arrayBuffer();
  // Recheck the bytes read rather than relying only on File metadata.
  ensureAllowedSize(bytes.byteLength);

  const content = decodePolicyContent(bytes);
  // Hash the exact normalized text that will be sent to the model. This keeps
  // the cache identity tied to policy semantics rather than file metadata or
  // an optional UTF-8 BOM.
  const contentHash = await hashPolicyContent(content);

  return {
    schemaVersion: ORGANIZATION_POLICY_SCHEMA_VERSION,
    content,
    fileName: file.name,
    loadedAt: loadedAt.toISOString(),
    sizeBytes: bytes.byteLength,
    contentHash,
  };
}

export function isStoredOrganizationPolicy(
  value: unknown,
): value is StoredOrganizationPolicy {
  if (typeof value !== "object" || value === null) return false;

  const policy = value as Partial<StoredOrganizationPolicy>;
  if (
    policy.schemaVersion !== ORGANIZATION_POLICY_SCHEMA_VERSION ||
    typeof policy.content !== "string" ||
    typeof policy.fileName !== "string" ||
    typeof policy.loadedAt !== "string" ||
    typeof policy.sizeBytes !== "number" ||
    typeof policy.contentHash !== "string"
  ) {
    return false;
  }

  if (
    policy.content.trim().length === 0 ||
    policy.content.includes("\0") ||
    policy.content.startsWith("\uFEFF") ||
    new TextEncoder().encode(policy.content).byteLength >
      MAX_ORGANIZATION_POLICY_BYTES ||
    !policy.fileName.trim() ||
    policy.fileName.includes("\0") ||
    policy.fileName.length > MAX_ORGANIZATION_POLICY_FILE_NAME_LENGTH ||
    !hasAllowedExtension(policy.fileName) ||
    !Number.isInteger(policy.sizeBytes) ||
    policy.sizeBytes <= 0 ||
    policy.sizeBytes > MAX_ORGANIZATION_POLICY_BYTES ||
    !CONTENT_HASH_PATTERN.test(policy.contentHash)
  ) {
    return false;
  }

  const contentSize = new TextEncoder().encode(policy.content).byteLength;
  // A leading UTF-8 BOM is removed from `content` but retained in the file's
  // byte metadata. No other discrepancy is valid for an imported text file.
  if (
    policy.sizeBytes !== contentSize &&
    policy.sizeBytes !== contentSize + 3
  ) {
    return false;
  }

  const loadedAt = new Date(policy.loadedAt);
  return (
    !Number.isNaN(loadedAt.getTime()) &&
    loadedAt.toISOString() === policy.loadedAt
  );
}

export function validateStoredOrganizationPolicy(
  value: unknown,
): StoredOrganizationPolicy | null {
  return isStoredOrganizationPolicy(value) ? value : null;
}

export async function loadOrganizationPolicy(): Promise<
  StoredOrganizationPolicy | null
> {
  const stored = await chrome.storage.local.get(
    ORGANIZATION_POLICY_STORAGE_KEY,
  );
  const value = stored[ORGANIZATION_POLICY_STORAGE_KEY];

  if (value === undefined) return null;
  const policy = validateStoredOrganizationPolicy(value);
  if (policy && (await hashPolicyContent(policy.content)) === policy.contentHash) {
    return policy;
  }

  throw new OrganizationPolicyError(
    "invalid_stored_policy",
    "Zapisana polityka organizacji ma nieprawidłowy format.",
  );
}

export async function saveOrganizationPolicy(
  policy: StoredOrganizationPolicy,
): Promise<void> {
  if (
    !isStoredOrganizationPolicy(policy) ||
    (await hashPolicyContent(policy.content)) !== policy.contentHash
  ) {
    throw new OrganizationPolicyError(
      "invalid_stored_policy",
      "Nie można zapisać polityki o nieprawidłowym formacie.",
    );
  }

  await chrome.storage.local.set({
    [ORGANIZATION_POLICY_STORAGE_KEY]: policy,
  });
}

export async function importOrganizationPolicyFile(
  file: File,
): Promise<StoredOrganizationPolicy> {
  const policy = await createStoredOrganizationPolicy(file);
  await saveOrganizationPolicy(policy);
  return policy;
}

export async function removeOrganizationPolicy(): Promise<void> {
  await chrome.storage.local.remove(ORGANIZATION_POLICY_STORAGE_KEY);
}
