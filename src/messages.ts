export interface LinkMismatchSignal {
  text: string;
  href: string;
}

export interface AnalyzePayload {
  content: string;
  signals: {
    suspiciousPhrases: string[];
    linkMismatches: LinkMismatchSignal[];
    suspiciousDomains: string[];
  };
}

export type PolicyInfluence = "none" | "supporting" | "material";

export interface PolicyAssessment {
  violated: boolean;
  influence: PolicyInfluence;
  summary: string | null;
  policyHash: string;
  policyFileName: string;
}

export interface AnalyzeResult {
  trustScore: number;
  verdict: "safe" | "suspicious" | "phishing";
  confidence: number;
  reasoning: string;
  categories: Array<
    | "credential_request"
    | "urgency"
    | "impersonation"
    | "suspicious_link"
    | "suspicious_domain"
    | "financial"
  >;
  /**
   * `null` means that no valid organization policy was used for this
   * particular analysis. It is intentionally part of the verdict snapshot so
   * the UI and audit log never infer policy influence from free-form text.
   */
  policyAssessment: PolicyAssessment | null;
}

export interface AnalyzeRequestMessage {
  type: "ANALYZE";
  payload: AnalyzePayload;
}

export type AnalyzeMessageResponse =
  | { ok: true; data: AnalyzeResult }
  | { ok: false; error: string };

export interface GuardianPayload {
  content: string;
  domains: string[];
  phrases: string[];
  trustedDomains: string[];
  linkMismatches: LinkMismatchSignal[];
}

export interface GuardianAuditEntry {
  timestamp: string;
  url: string;
  action: "hidden" | "revealed";
  trustScore: number;
  confidence: number;
  reasoning: string;
  categories: string[];
  excerpt: string;
  policyAssessment: PolicyAssessment | null;
}

export interface GuardianAuditRequestMessage {
  type: "APPEND_GUARDIAN_AUDIT";
  entry: GuardianAuditEntry;
}

export type GuardianAuditMessageResponse =
  | { ok: true }
  | { ok: false; error: string };

export interface GuardianRequestMessage {
  type: "GUARDIAN_ANALYZE";
  payload: GuardianPayload;
}

export type GuardianMessageResponse =
  | { ok: true; data: AnalyzeResult }
  | { ok: false; error: string };
