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
