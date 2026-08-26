import { createHash } from "node:crypto";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { basename, dirname, isAbsolute, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { getLinkRisk } from "../../src/linkRisk";
import { suspiciousWords } from "../../src/phrases";

const DATASET_VERSION = "EVAL_OPENAI_PILOT_POOL_039_V1";
const SIGNALS_MODE = "product_derived_v1";
const CONTENT_RENDERER_VERSION = "visible_text_v1";
const SELECTION_ID = "OPENAI_PILOT_030_V1";
const UUID_NAMESPACE = "6ba7b811-9dad-11d1-80b4-00c04fd430c8";
const UUID_NAME_PREFIX = `urn:phishing-extension:dataset:${DATASET_VERSION}:`;
const UPSTREAM_SOURCE_NAME = "eval_dataset_v3-2.md";
const UPSTREAM_SOURCE_SHA256 =
  "2003ba36e13a4ee1f1635b74cc6177e094541478ff5cccefebb368c6c54a6c19";

const SCRIPT_PATH = fileURLToPath(import.meta.url);
const REPO_ROOT = resolve(dirname(SCRIPT_PATH), "../..");
const DEFAULT_SOURCE = resolve(
  REPO_ROOT,
  "benchmarks/datasets/openai_pilot_pool_v1/source.md",
);
const DEFAULT_OUTPUT_ROOT = resolve(REPO_ROOT, "benchmarks");

const MALICIOUS_CASE_IDS = [
  "case_001",
  "case_003",
  "case_007",
  "case_009",
  "case_011",
  "case_013",
  "case_015",
  "case_017",
  "case_019",
  "case_023",
  "case_025",
  "case_027",
  "case_029",
  "case_033",
  "case_035",
] as const;

const BENIGN_CASE_IDS = [
  "case_002",
  "case_004",
  "case_006",
  "case_012",
  "case_016",
  "case_020",
  "case_022",
  "case_026",
  "case_028",
  "case_030",
  "case_032",
  "case_034",
  "case_036",
  "case_037",
  "case_038",
] as const;

const BENIGN_ALLOW_OR_WARN = new Set([
  "case_004",
  "case_020",
  "case_022",
  "case_030",
  "case_032",
  "case_037",
  "case_038",
]);

const RESERVED_DOMAIN_SUFFIXES = [".example", ".invalid", ".test"] as const;

type ClassLabel = "malicious" | "benign";
type Difficulty = "typical" | "edge" | "adversarial";
type Language = "pl" | "en";
type LabelConfidence = "high" | "medium";
type Channel = "e-mail" | "SMS";

interface LinkRecord {
  text: string;
  href: string;
}

interface SourceCase {
  caseId: string;
  label: ClassLabel;
  scenario: string;
  difficulty: Difficulty;
  sourceType: "synthetic";
  language: Language;
  labelConfidence: LabelConfidence;
  securityProbe: boolean;
  channel: Channel;
  from: string;
  replyTo: string | null;
  subject: string | null;
  body: string;
  links: LinkRecord[];
  annotatorSignalsRaw: string;
  justification: string;
  rawBlock: string;
}

interface DerivedSignals {
  suspiciousPhrases: string[];
  linkMismatches: LinkRecord[];
  suspiciousDomains: string[];
}

interface CliOptions {
  source: string;
  outputRoot: string;
  check: boolean;
}

function fail(message: string): never {
  throw new Error(message);
}

function parseArgs(argv: string[]): CliOptions {
  const options: CliOptions = {
    source: DEFAULT_SOURCE,
    outputRoot: DEFAULT_OUTPUT_ROOT,
    check: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--source") {
      const value = argv[index + 1];
      if (!value) fail("--source requires a path");
      options.source = resolve(value);
      index += 1;
    } else if (argument === "--output-root") {
      const value = argv[index + 1];
      if (!value) fail("--output-root requires a path");
      options.outputRoot = resolve(value);
      index += 1;
    } else if (argument === "--check") {
      options.check = true;
    } else {
      fail(`unknown argument: ${argument}`);
    }
  }

  if (!isAbsolute(options.source) || !isAbsolute(options.outputRoot)) {
    fail("source and output root must resolve to absolute paths");
  }
  return options;
}

function sha256Bytes(value: Buffer | string): string {
  return createHash("sha256").update(value).digest("hex");
}

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value !== null && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const sorted: Record<string, unknown> = {};
    for (const key of Object.keys(record).sort()) {
      const child = record[key];
      if (child === undefined) fail(`undefined value at JSON key ${key}`);
      sorted[key] = canonicalize(child);
    }
    return sorted;
  }
  return value;
}

function canonicalJson(value: unknown): string {
  return JSON.stringify(canonicalize(value));
}

function prettyCanonicalJson(value: unknown): string {
  return `${JSON.stringify(canonicalize(value), null, 2)}\n`;
}

function canonicalJsonl(records: unknown[]): string {
  return `${records.map(canonicalJson).join("\n")}\n`;
}

function normalizeBlock(lines: string[], field: string): string {
  const normalized = [...lines];
  while (normalized[0] === "") normalized.shift();
  while (normalized.at(-1) === "") normalized.pop();
  const value = normalized.map((line) => line.replace(/[ \t]+$/u, "")).join("\n");
  if (!value.trim()) fail(`${field} must not be empty`);
  return value;
}

function parseBoolean(value: string, field: string): boolean {
  if (value === "true") return true;
  if (value === "false") return false;
  return fail(`${field} must be true or false`);
}

function parseEnum<T extends string>(
  value: string,
  allowed: readonly T[],
  field: string,
): T {
  if (!allowed.includes(value as T)) {
    fail(`${field} has unsupported value: ${value}`);
  }
  return value as T;
}

function parsePossiblyQuoted(value: string, field: string): string {
  if (!value.startsWith('"')) return value;
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch (error) {
    fail(`${field} has invalid quoted JSON string: ${String(error)}`);
  }
  if (typeof parsed !== "string") fail(`${field} must decode to a string`);
  return parsed;
}

function parseLinks(lines: string[], caseId: string): LinkRecord[] {
  const normalized = [...lines];
  while (normalized[0] === "") normalized.shift();
  while (normalized.at(-1) === "") normalized.pop();
  if (normalized.length === 1 && normalized[0] === "- (brak)") return [];
  if (normalized.length === 0 || normalized.length % 2 !== 0) {
    fail(`${caseId} LINKS must be '- (brak)' or text/href pairs`);
  }

  const links: LinkRecord[] = [];
  const seen = new Set<string>();
  for (let index = 0; index < normalized.length; index += 2) {
    const textLine = normalized[index];
    const hrefLine = normalized[index + 1];
    if (!textLine.startsWith("- text: ") || !hrefLine.startsWith("  href: ")) {
      fail(`${caseId} LINKS pair has invalid indentation or field order`);
    }
    const text = parsePossiblyQuoted(textLine.slice("- text: ".length).trim(), `${caseId} link text`);
    const href = parsePossiblyQuoted(hrefLine.slice("  href: ".length).trim(), `${caseId} link href`);
    if (!text || text.length > 200) fail(`${caseId} link text must be 1..200 characters`);
    if (!href || href.length > 2_048) fail(`${caseId} link href must be 1..2048 characters`);
    let parsed: URL;
    try {
      parsed = new URL(href);
    } catch {
      fail(`${caseId} link href is not a URL: ${href}`);
    }
    if (parsed.protocol !== "https:") fail(`${caseId} link href must use HTTPS`);
    if (!RESERVED_DOMAIN_SUFFIXES.some((suffix) => parsed.hostname.endsWith(suffix))) {
      fail(`${caseId} link href uses a non-reserved hostname: ${parsed.hostname}`);
    }
    const token = `${text}\n${href}`;
    if (seen.has(token)) fail(`${caseId} contains a duplicate link`);
    seen.add(token);
    links.push({ text, href });
  }
  return links;
}

function validateSyntheticText(value: string, caseId: string): void {
  const emailPattern = /\b[A-Z0-9._%+-]+@([A-Z0-9.-]+\.[A-Z]{2,})\b/giu;
  const urlPattern = /https?:\/\/([^/\s:]+)/giu;
  const hostnamePattern = /(?<![A-Z0-9_-])(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,63}|XN--[A-Z0-9-]{2,59})(?![A-Z0-9_-])/giu;
  const domains: string[] = [];
  for (const match of value.matchAll(emailPattern)) domains.push(match[1].toLowerCase());
  for (const match of value.matchAll(urlPattern)) domains.push(match[1].toLowerCase());
  for (const match of value.matchAll(hostnamePattern)) domains.push(match[0].toLowerCase());
  const unsafe = domains.find(
    (domain) => !RESERVED_DOMAIN_SUFFIXES.some((suffix) => domain.endsWith(suffix)),
  );
  if (unsafe) fail(`${caseId} contains a non-reserved domain: ${unsafe}`);
  if (/\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b/u.test(value)) {
    fail(`${caseId} contains an IBAN-like value`);
  }
  if (/\b(?:sk|rk|pk)-[A-Za-z0-9_-]{8,}\b/iu.test(value)) {
    fail(`${caseId} contains a secret-like value`);
  }
  if (/(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)/u.test(value)) {
    fail(`${caseId} contains an IP address`);
  }
}

function parseCaseBlock(caseId: string, blockLines: string[], rawBlock: string): SourceCase {
  const sectionHeaders = ["BODY:", "LINKS:", "ANNOTATOR_SIGNALS:", "JUSTIFICATION:"];
  for (const header of sectionHeaders) {
    const count = blockLines.filter((line) => line === header).length;
    if (count !== 1) fail(`${caseId} must contain exactly one ${header}`);
  }

  let cursor = 0;
  const skipBlanks = (): void => {
    while (blockLines[cursor] === "") cursor += 1;
  };
  const scalar = (name: string): string => {
    skipBlanks();
    const prefix = `${name}:`;
    const line = blockLines[cursor];
    if (line === undefined || !line.startsWith(prefix)) {
      fail(`${caseId} expected ${prefix}, got ${String(line)}`);
    }
    const value = line.slice(prefix.length).trim();
    if (!value) fail(`${caseId} ${name} must not be empty`);
    cursor += 1;
    return value;
  };
  const expectHeader = (name: string): void => {
    skipBlanks();
    if (blockLines[cursor] !== name) {
      fail(`${caseId} expected ${name}, got ${String(blockLines[cursor])}`);
    }
    cursor += 1;
  };
  const collectUntil = (nextHeader: string): string[] => {
    const next = blockLines.indexOf(nextHeader, cursor);
    if (next < 0) fail(`${caseId} is missing ${nextHeader}`);
    const value = blockLines.slice(cursor, next);
    cursor = next;
    return value;
  };

  skipBlanks();
  const label = parseEnum(scalar("LABEL"), ["malicious", "benign"] as const, `${caseId} LABEL`);
  const scenario = scalar("SCENARIO");
  if (!/^[a-z0-9_]+$/u.test(scenario)) fail(`${caseId} SCENARIO must be a snake_case slug`);
  const difficulty = parseEnum(
    scalar("DIFFICULTY"),
    ["typical", "edge", "adversarial"] as const,
    `${caseId} DIFFICULTY`,
  );
  const sourceType = parseEnum(scalar("SOURCE_TYPE"), ["synthetic"] as const, `${caseId} SOURCE_TYPE`);
  const language = parseEnum(scalar("LANGUAGE"), ["pl", "en"] as const, `${caseId} LANGUAGE`);
  const labelConfidence = parseEnum(
    scalar("LABEL_CONFIDENCE"),
    ["high", "medium"] as const,
    `${caseId} LABEL_CONFIDENCE`,
  );
  const securityProbe = parseBoolean(scalar("SECURITY_PROBE"), `${caseId} SECURITY_PROBE`);
  const channel = parseEnum(scalar("CHANNEL"), ["e-mail", "SMS"] as const, `${caseId} CHANNEL`);
  const from = scalar("FROM");
  skipBlanks();
  const replyTo = blockLines[cursor]?.startsWith("REPLY_TO:") ? scalar("REPLY_TO") : null;
  const rawSubject = scalar("SUBJECT");
  const subject = rawSubject === "(brak)" ? null : rawSubject;

  expectHeader("BODY:");
  const body = normalizeBlock(collectUntil("LINKS:"), `${caseId} BODY`);
  expectHeader("LINKS:");
  const links = parseLinks(collectUntil("ANNOTATOR_SIGNALS:"), caseId);
  expectHeader("ANNOTATOR_SIGNALS:");
  const annotatorSignalsRaw = normalizeBlock(
    collectUntil("JUSTIFICATION:"),
    `${caseId} ANNOTATOR_SIGNALS`,
  );
  expectHeader("JUSTIFICATION:");
  const justification = normalizeBlock(blockLines.slice(cursor), `${caseId} JUSTIFICATION`);

  const sourceCase: SourceCase = {
    caseId,
    label,
    scenario,
    difficulty,
    sourceType,
    language,
    labelConfidence,
    securityProbe,
    channel,
    from,
    replyTo,
    subject,
    body,
    links,
    annotatorSignalsRaw,
    justification,
    rawBlock,
  };
  validateSyntheticText(
    [from, replyTo ?? "", subject ?? "", body, ...links.flatMap((link) => [link.text, link.href])].join("\n"),
    caseId,
  );
  return sourceCase;
}

function parseSource(sourceBytes: Buffer): SourceCase[] {
  const decoded = sourceBytes.toString("utf8");
  if (decoded.includes("\uFFFD")) fail("source is not valid UTF-8");
  if (/\r(?!\n)/u.test(decoded)) fail("source contains a bare carriage return");
  const source = decoded.replace(/\r\n/gu, "\n").normalize("NFC");
  if (!source.startsWith("# Zestaw ewaluacyjny — phishing detection (39 przypadków)\n")) {
    fail("source title must declare exactly 39 cases");
  }
  if (!source.includes(`Wersja: \`${DATASET_VERSION}\``)) {
    fail(`source must declare version ${DATASET_VERSION}`);
  }
  if (!source.includes(`SIGNALS_MODE: \`${SIGNALS_MODE}\``)) {
    fail(`source must declare SIGNALS_MODE ${SIGNALS_MODE}`);
  }
  if (/^SIGNALS:$/mu.test(source)) fail("source must use ANNOTATOR_SIGNALS, never ambiguous SIGNALS");

  const lines = source.split("\n");
  const headings: Array<{ index: number; caseId: string }> = [];
  for (let index = 0; index < lines.length; index += 1) {
    const match = /^### (case_\d{3})$/u.exec(lines[index]);
    if (match) headings.push({ index, caseId: match[1] });
  }
  if (headings.length !== 39) fail(`source has ${headings.length} cases; expected 39`);

  const cases: SourceCase[] = [];
  const scenarios = new Set<string>();
  for (let offset = 0; offset < headings.length; offset += 1) {
    const heading = headings[offset];
    const expectedCaseId = `case_${String(offset + 1).padStart(3, "0")}`;
    if (heading.caseId !== expectedCaseId) {
      fail(`case IDs must be contiguous; expected ${expectedCaseId}, got ${heading.caseId}`);
    }
    const trailingSectionIndex = lines.findIndex(
      (line, index) => index > heading.index && /^## [^#]/u.test(line),
    );
    const nextHeadingIndex =
      headings[offset + 1]?.index ?? (trailingSectionIndex >= 0 ? trailingSectionIndex : lines.length);
    const delimiters: number[] = [];
    for (let index = heading.index + 1; index < nextHeadingIndex; index += 1) {
      if (lines[index] === "---") delimiters.push(index);
    }
    if (delimiters.length !== 1) {
      fail(`${heading.caseId} must end with exactly one --- delimiter`);
    }
    const delimiter = delimiters[0];
    const between = lines.slice(delimiter + 1, nextHeadingIndex);
    if (between.some((line) => line !== "")) {
      fail(`${heading.caseId} has unexpected content after its delimiter`);
    }
    const blockLines = lines.slice(heading.index + 1, delimiter);
    const rawBlock = `${lines.slice(heading.index, delimiter).join("\n")}\n`;
    const sourceCase = parseCaseBlock(heading.caseId, blockLines, rawBlock);
    if (scenarios.has(sourceCase.scenario)) fail(`duplicate SCENARIO: ${sourceCase.scenario}`);
    scenarios.add(sourceCase.scenario);
    cases.push(sourceCase);
  }

  const count = (predicate: (value: SourceCase) => boolean): number => cases.filter(predicate).length;
  const expectedCounts: Array<[string, number, number]> = [
    ["malicious", count((value) => value.label === "malicious"), 18],
    ["benign", count((value) => value.label === "benign"), 21],
    ["typical", count((value) => value.difficulty === "typical"), 16],
    ["edge", count((value) => value.difficulty === "edge"), 14],
    ["adversarial", count((value) => value.difficulty === "adversarial"), 9],
    ["security_probe", count((value) => value.securityProbe), 2],
  ];
  for (const [name, actual, expected] of expectedCounts) {
    if (actual !== expected) fail(`source ${name} count is ${actual}; expected ${expected}`);
  }
  return cases;
}

function renderContent(sourceCase: SourceCase): string {
  const bodyLines = sourceCase.body.split("\n");
  const lines = [
    `Kanał: ${sourceCase.channel}`,
    `From: ${sourceCase.from}`,
    ...(sourceCase.replyTo ? [`Reply-To: ${sourceCase.replyTo}`] : []),
    `Subject: ${sourceCase.subject ?? "(brak)"}`,
    `Treść: ${bodyLines[0]}`,
    ...bodyLines.slice(1),
    ...sourceCase.links.map((link) => `Link: ${link.text}`),
  ];
  const content = lines.join("\n");
  if (!content.trim() || content.length > 20_000) {
    fail(`${sourceCase.caseId} rendered content must be 1..20000 characters`);
  }
  for (const link of sourceCase.links) {
    if (content.includes(link.href)) {
      fail(`${sourceCase.caseId} hidden href leaked into visible content`);
    }
  }
  return content;
}

function deriveSignals(sourceCase: SourceCase, content: string): DerivedSignals {
  const normalizedContent = content.toLowerCase();
  const suspiciousPhrases = suspiciousWords.filter((phrase) =>
    normalizedContent.includes(phrase.toLowerCase()),
  );
  const linkMismatches: LinkRecord[] = [];
  const suspiciousDomains = new Set<string>();
  for (const link of sourceCase.links) {
    const risk = getLinkRisk(link.text, link.href);
    if (risk.mismatch) linkMismatches.push({ text: link.text, href: risk.effectiveHref });
    if (risk.hostname && risk.suspiciousDomain) suspiciousDomains.add(risk.hostname);
  }
  return {
    suspiciousPhrases: [...suspiciousPhrases],
    linkMismatches,
    suspiciousDomains: Array.from(suspiciousDomains),
  };
}

function uuidToBytes(value: string): Buffer {
  const hex = value.replace(/-/gu, "");
  if (!/^[0-9a-f]{32}$/u.test(hex)) fail(`invalid UUID namespace: ${value}`);
  return Buffer.from(hex, "hex");
}

function uuidV5(name: string): string {
  const digest = createHash("sha1")
    .update(uuidToBytes(UUID_NAMESPACE))
    .update(Buffer.from(name, "utf8"))
    .digest();
  const bytes = Buffer.from(digest.subarray(0, 16));
  bytes[6] = (bytes[6] & 0x0f) | 0x50;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = bytes.toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function sampleId(caseId: string): string {
  return uuidV5(`${UUID_NAME_PREFIX}${caseId}`);
}

function repoRelative(path: string): string {
  const value = relative(REPO_ROOT, path).replaceAll("\\", "/");
  if (!value || value.startsWith("../")) fail(`path is outside repository: ${path}`);
  return value;
}

function logicalSourcePath(path: string): string {
  const value = relative(REPO_ROOT, path).replaceAll("\\", "/");
  if (value && !value.startsWith("../") && !isAbsolute(value)) return value;
  return `external:${basename(path)}`;
}

function packageVersion(packageName: string): string {
  const packagePath = resolve(REPO_ROOT, "node_modules", packageName, "package.json");
  const parsed = JSON.parse(readFileSync(packagePath, "utf8")) as { version?: unknown };
  if (typeof parsed.version !== "string") fail(`missing version for ${packageName}`);
  return parsed.version;
}

function buildArtifacts(sourcePath: string): Map<string, string> {
  if (!existsSync(sourcePath)) fail(`source does not exist: ${sourcePath}`);
  const sourceBytes = readFileSync(sourcePath);
  const sourceCases = parseSource(sourceBytes);
  const sourceById = new Map(sourceCases.map((sourceCase) => [sourceCase.caseId, sourceCase]));
  const requested = [...MALICIOUS_CASE_IDS, ...BENIGN_CASE_IDS];
  if (new Set(requested).size !== 30) fail("selection contains duplicate case IDs");
  for (const caseId of MALICIOUS_CASE_IDS) {
    if (sourceById.get(caseId)?.label !== "malicious") fail(`selection label mismatch for ${caseId}`);
  }
  for (const caseId of BENIGN_CASE_IDS) {
    if (sourceById.get(caseId)?.label !== "benign") fail(`selection label mismatch for ${caseId}`);
  }
  const orderedCaseIds = [...requested].sort((left, right) => left.localeCompare(right));
  const selected = orderedCaseIds.map((caseId) => {
    const value = sourceById.get(caseId);
    if (!value) fail(`selected case does not exist: ${caseId}`);
    return value;
  });

  const runnerRecords: unknown[] = [];
  const labels: unknown[] = [];
  const metadata: unknown[] = [];
  for (const sourceCase of selected) {
    const id = sampleId(sourceCase.caseId);
    const analysisClusterId = `cluster_${sourceCase.caseId}`;
    const content = renderContent(sourceCase);
    const signals = deriveSignals(sourceCase, content);
    runnerRecords.push({
      sample_id: id,
      organization_policy: null,
      untrusted_analysis: { content, signals },
    });
    const acceptableActions =
      sourceCase.label === "malicious"
        ? ["warn", "hide"]
        : BENIGN_ALLOW_OR_WARN.has(sourceCase.caseId)
          ? ["allow", "warn"]
          : ["allow"];
    labels.push({
      sample_id: id,
      case_name: sourceCase.caseId,
      class_label: sourceCase.label,
      acceptable_actions: acceptableActions,
      security_probe: sourceCase.securityProbe,
      scenario: sourceCase.scenario,
      difficulty: sourceCase.difficulty,
      language: sourceCase.language,
      label_confidence: sourceCase.labelConfidence,
      analysis_cluster_id: analysisClusterId,
    });
    metadata.push({
      sample_id: id,
      case_id: sourceCase.caseId,
      source_dataset_version: DATASET_VERSION,
      source_type: sourceCase.sourceType,
      channel: sourceCase.channel,
      reply_to_present: sourceCase.replyTo !== null,
      link_count: sourceCase.links.length,
      links: sourceCase.links,
      analysis_cluster_id: analysisClusterId,
      annotator_justification: sourceCase.justification,
      annotator_signals_raw: sourceCase.annotatorSignalsRaw,
      annotator_signals_used_for_runner: false,
      signals_mode: SIGNALS_MODE,
      derived_signals: signals,
      content_renderer_version: CONTENT_RENDERER_VERSION,
      rendered_content_sha256: sha256Bytes(content),
      source_block_sha256: sha256Bytes(sourceCase.rawBlock),
    });
  }

  const sourceSha256 = sha256Bytes(sourceBytes);
  const runnerPayload = canonicalJsonl(runnerRecords);
  const labelsPayload = canonicalJsonl(labels);
  const metadataPayload = canonicalJsonl(metadata);
  const selectionManifest = {
    schema_version: "1.0",
    selection_id: SELECTION_ID,
    dataset_version: DATASET_VERSION,
    source_sha256: sourceSha256,
    source_pool_count: sourceCases.length,
    sample_count: selected.length,
    class_counts: { malicious: MALICIOUS_CASE_IDS.length, benign: BENIGN_CASE_IDS.length },
    selection_policy: "explicit_preregistered_case_ids",
    malicious_case_ids: [...MALICIOUS_CASE_IDS],
    benign_case_ids: [...BENIGN_CASE_IDS],
    ordered_case_ids: orderedCaseIds,
    ordering: "ascending_case_id",
    analysis_cluster_policy: "one_independent_cluster_per_case",
  };
  const selectionPayload = prettyCanonicalJson(selectionManifest);

  const generatorSha256 = sha256Bytes(readFileSync(SCRIPT_PATH));
  const publicDatasetManifest = {
    schema_version: "1.0",
    dataset_id: "OPENAI_PILOT_030_V1",
    sample_count: 30,
    source_pool_count: 39,
    source_type: "synthetic",
    data_class: "synthetic_reserved_domains_only",
    signals_mode: SIGNALS_MODE,
    renderer_version: CONTENT_RENDERER_VERSION,
    source_pool_sha256: sourceSha256,
    selection_manifest_sha256: sha256Bytes(selectionPayload),
    generator_sha256: generatorSha256,
  };
  const publicDatasetManifestPayload = prettyCanonicalJson(publicDatasetManifest);

  const productionFiles = [
    "src/phrases.ts",
    "src/linkRisk.ts",
    "src/links.ts",
    "src/suspiciousDomain.ts",
    "src/levensthein.ts",
  ];
  const productionSourceHashes = Object.fromEntries(
    productionFiles.map((path) => [path, sha256Bytes(readFileSync(resolve(REPO_ROOT, path)))]),
  );
  const provenanceManifest = {
    schema_version: "1.0",
    dataset_version: DATASET_VERSION,
    data_class: "synthetic_reserved_domains_only",
    canonical_source_path: logicalSourcePath(sourcePath),
    canonical_source_sha256: sourceSha256,
    upstream_source_name: UPSTREAM_SOURCE_NAME,
    upstream_source_sha256: UPSTREAM_SOURCE_SHA256,
    importer_path: repoRelative(SCRIPT_PATH),
    importer_sha256: generatorSha256,
    signals_mode: SIGNALS_MODE,
    annotator_signals_policy: "preserved_in_secure_metadata_but_ignored_for_runner",
    content_renderer_version: CONTENT_RENDERER_VERSION,
    content_link_policy: "visible_text_only; hidden href only in production-derived signals",
    uuid_version: 5,
    uuid_namespace: UUID_NAMESPACE,
    uuid_name_template: `${UUID_NAME_PREFIX}{case_id}`,
    production_source_sha256: productionSourceHashes,
    package_lock_sha256: sha256Bytes(readFileSync(resolve(REPO_ROOT, "package-lock.json"))),
    dependency_versions: {
      tldts: packageVersion("tldts"),
      "vite-node": packageVersion("vite-node"),
    },
    selection_manifest_sha256: sha256Bytes(selectionPayload),
    outputs_sha256: {
      runner_input_jsonl: sha256Bytes(runnerPayload),
      dataset_manifest_json: sha256Bytes(publicDatasetManifestPayload),
      labels_jsonl: sha256Bytes(labelsPayload),
      metadata_jsonl: sha256Bytes(metadataPayload),
    },
  };
  const provenancePayload = prettyCanonicalJson(provenanceManifest);

  return new Map([
    ["fixtures/openai_pilot_030_v1/runner_input.jsonl", runnerPayload],
    ["fixtures/openai_pilot_030_v1/dataset_manifest.json", publicDatasetManifestPayload],
    ["secure_scoring/openai_pilot_030_v1/labels.jsonl", labelsPayload],
    ["secure_scoring/openai_pilot_030_v1/metadata.jsonl", metadataPayload],
    ["secure_scoring/openai_pilot_030_v1/selection_manifest.json", selectionPayload],
    ["secure_scoring/openai_pilot_030_v1/provenance_manifest.json", provenancePayload],
  ]);
}

function writeAtomic(path: string, payload: string): void {
  mkdirSync(dirname(path), { recursive: true, mode: 0o755 });
  const temporary = resolve(dirname(path), `.${path.split("/").at(-1)}.${process.pid}.tmp`);
  try {
    writeFileSync(temporary, payload, { encoding: "utf8", mode: 0o644 });
    renameSync(temporary, path);
    chmodSync(path, 0o644);
  } finally {
    if (existsSync(temporary)) unlinkSync(temporary);
  }
}

function applyArtifacts(outputRoot: string, artifacts: Map<string, string>, check: boolean): void {
  for (const [relativePath, payload] of artifacts) {
    const outputPath = resolve(outputRoot, relativePath);
    const relativeOutput = relative(outputRoot, outputPath);
    if (!relativeOutput || relativeOutput.startsWith("../") || isAbsolute(relativeOutput)) {
      fail(`output path escapes output root: ${outputPath}`);
    }
    if (check) {
      if (!existsSync(outputPath)) fail(`generated artifact is missing: ${outputPath}`);
      const actual = readFileSync(outputPath, "utf8");
      if (actual !== payload) fail(`generated artifact drift: ${outputPath}`);
    } else {
      writeAtomic(outputPath, payload);
    }
  }
}

function main(): void {
  const options = parseArgs(process.argv.slice(2));
  const artifacts = buildArtifacts(options.source);
  applyArtifacts(options.outputRoot, artifacts, options.check);
  process.stdout.write(
    `${options.check ? "CHECK_OK" : "IMPORT_OK"} dataset=${DATASET_VERSION} selection=${SELECTION_ID} records=30\n`,
  );
}

try {
  main();
} catch (error) {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`IMPORT_ERROR: ${message}\n`);
  process.exitCode = 2;
}
