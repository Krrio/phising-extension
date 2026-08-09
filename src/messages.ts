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
}

export interface GuardianRequestMessage {
  type: "GUARDIAN_ANALYZE";
  payload: GuardianPayload;
}

export type GuardianMessageResponse =
  | { ok: true; data: AnalyzeResult }
  | { ok: false; error: string };
