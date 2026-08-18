import { parse } from "tldts";
import { levenshtein } from "./levensthein";

const knownBrands = [
  // Technologie
  "google",
  "gmail",
  "youtube",
  "android",
  "googleplay",
  "googlecloud",
  "apple",
  "appleid",
  "icloud",
  "appstore",
  "microsoft",
  "microsoftonline",
  "outlook",
  "office",
  "office365",
  "onedrive",
  "azure",
  "xbox",
  "amazon",
  "amazonprime",
  "primevideo",
  "aws",
  "samsung",
  "huawei",
  "xiaomi",
  "lenovo",
  "motorola",
  "nokia",
  "dell",
  "asus",
  "acer",
  "nvidia",
  "intel",
  "amd",
  "adobe",
  "dropbox",
  "cloudflare",
  "github",
  "gitlab",
  "bitbucket",
  "openai",
  "chatgpt",
  "yahoo",
  "protonmail",
  "proton",
  "zoom",
  "slack",
  "notion",
  "canva",

  // Social media
  "facebook",
  "facebookmail",
  "meta",
  "messenger",
  "instagram",
  "whatsapp",
  "threads",
  "linkedin",
  "tiktok",
  "snapchat",
  "discord",
  "telegram",
  "signal",
  "twitter",
  "twitch",
  "reddit",
  "pinterest",

  // Streaming i gry
  "netflix",
  "spotify",
  "disneyplus",
  "hbomax",
  "primevideo",
  "playstation",
  "nintendo",
  "steam",
  "steampowered",
  "steamcommunity",
  "epicgames",
  "battlenet",
  "blizzard",
  "ubisoft",
  "electronicarts",
  "riotgames",
  "roblox",

  // Płatności i finanse
  "paypal",
  "stripe",
  "visa",
  "mastercard",
  "americanexpress",
  "amex",
  "revolut",
  "wise",
  "skrill",
  "payoneer",
  "westernunion",
  "klarna",
  "venmo",
  "cashapp",
  "paysafecard",
  "binance",
  "coinbase",
  "kraken",
  "metamask",
  "blockchain",
  "crypto",
  "ledger",
  "trezor",

  // Zakupy i usługi
  "ebay",
  "aliexpress",
  "temu",
  "shein",
  "booking",
  "airbnb",
  "expedia",
  "tripadvisor",
  "uber",
  "bolt",
  "wolt",
  "glovo",

  // Kurierzy
  "dhl",
  "fedex",
  "ups",
  "dpd",
  "gls",
  "inpost",

  // Polskie sklepy
  "allegro",
  "allegrolokalnie",
  "olx",
  "otomoto",
  "otodom",
  "ceneo",
  "empik",
  "mediaexpert",
  "mediamarkt",
  "euroagd",
  "rtveuroagd",
  "xkom",
  "morele",
  "komputronik",
  "neonet",
  "rossmann",
  "hebe",
  "biedronka",
  "lidl",
  "kaufland",
  "carrefour",
  "auchan",
  "zabka",
  "orlen",
  "pyszne",
  "frisco",

  // Polskie banki
  "pkobp",
  "ipko",
  "inteligo",
  "pekao",
  "mbank",
  "ingbank",
  "santander",
  "santanderconsumer",
  "bankmillennium",
  "millennium",
  "aliorbank",
  "velobank",
  "bosbank",
  "bankpocztowy",
  "creditagricole",
  "bnpparibas",
  "citibank",
  "nestbank",
  "toyotabank",
  "plusbank",

  // Polskie systemy płatności
  "blik",
  "payu",
  "przelewy24",
  "tpay",
  "autopay",
  "bluecash",
  "skycash",

  // Polskie instytucje
  "mobywatel",
  "epuap",
  "zus",
  "puezus",
  "podatki",
  "biznesgov",
  "ceidg",
  "pacjent",
  "internetowekontopacjenta",
  "nfz",
  "pocztapolska",
  "policja",
  "govpl",

  // Operatorzy
  "orange",
  "tmobile",
  "play",
  "nju",
  "virginmobile",
  "vectra",
  "upc",
  "netia",
  "multimedia",
  "polsatbox",

  // Energia
  "pge",
  "tauron",
  "enea",
  "energa",
  "pgnig",

  // Ubezpieczenia
  "pzu",
  "warta",
  "allianz",
  "link4",
  "generali",
  "ergohestia",
  "uniqa",
  "compensa",
  "aviva",

  // Transport
  "pkp",
  "intercity",
  "pkpintercity",
  "koleo",
  "jakdojade",
  "flixbus",
  "lot",
  "lotpolishairlines",
  "ryanair",
  "wizzair",

  // Portale i media
  "onet",
  "interia",
  "gazeta",
  "pocztaonet",
  "pocztainteria",
  "tvp",
  "tvn",
  "polsat",
  "player",
  "canalplus",
  "polsatboxgo",
] as const;

const officialDomains = [
  // Google
  "google.com",
  "google.pl",
  "gmail.com",
  "youtube.com",

  // Apple
  "apple.com",
  "icloud.com",

  // Microsoft
  "microsoft.com",
  "microsoftonline.com",
  "live.com",
  "outlook.com",
  "office.com",
  "office365.com",
  "onedrive.com",
  "azure.com",
  "xbox.com",

  // Amazon
  "amazon.com",
  "amazon.pl",
  "amazon.de",
  "amazon.co.uk",
  "amazonaws.com",
  "primevideo.com",

  // Social media
  "facebook.com",
  "fb.com",
  "meta.com",
  "messenger.com",
  "instagram.com",
  "whatsapp.com",
  "threads.net",
  "linkedin.com",
  "tiktok.com",
  "snapchat.com",
  "discord.com",
  "discord.gg",
  "telegram.org",
  "signal.org",
  "twitter.com",
  "x.com",
  "twitch.tv",
  "reddit.com",
  "pinterest.com",

  // Technologie
  "samsung.com",
  "huawei.com",
  "mi.com",
  "xiaomi.com",
  "lenovo.com",
  "motorola.com",
  "dell.com",
  "asus.com",
  "acer.com",
  "nvidia.com",
  "intel.com",
  "amd.com",
  "adobe.com",
  "dropbox.com",
  "cloudflare.com",
  "github.com",
  "gitlab.com",
  "bitbucket.org",
  "openai.com",
  "chatgpt.com",
  "yahoo.com",
  "proton.me",
  "protonmail.com",
  "zoom.us",
  "slack.com",
  "notion.so",
  "canva.com",

  // Streaming i gry
  "netflix.com",
  "spotify.com",
  "disneyplus.com",
  "hbomax.com",
  "max.com",
  "playstation.com",
  "nintendo.com",
  "steampowered.com",
  "steamcommunity.com",
  "epicgames.com",
  "battle.net",
  "blizzard.com",
  "ubisoft.com",
  "ea.com",
  "riotgames.com",
  "roblox.com",

  // Płatności
  "paypal.com",
  "stripe.com",
  "visa.com",
  "mastercard.com",
  "americanexpress.com",
  "revolut.com",
  "wise.com",
  "skrill.com",
  "payoneer.com",
  "westernunion.com",
  "klarna.com",
  "paysafecard.com",
  "binance.com",
  "coinbase.com",
  "kraken.com",
  "metamask.io",
  "blockchain.com",
  "crypto.com",
  "ledger.com",
  "trezor.io",

  // Zakupy i podróże
  "ebay.com",
  "aliexpress.com",
  "temu.com",
  "shein.com",
  "booking.com",
  "airbnb.com",
  "expedia.com",
  "tripadvisor.com",
  "uber.com",
  "bolt.eu",
  "wolt.com",
  "glovoapp.com",

  // Kurierzy
  "dhl.com",
  "fedex.com",
  "ups.com",
  "dpd.com",
  "dpdgroup.com",
  "gls-group.com",
  "gls-poland.com",
  "inpost.pl",

  // Polskie sklepy
  "allegro.pl",
  "allegrolokalnie.pl",
  "olx.pl",
  "otomoto.pl",
  "otodom.pl",
  "ceneo.pl",
  "empik.com",
  "mediaexpert.pl",
  "mediamarkt.pl",
  "euro.com.pl",
  "x-kom.pl",
  "morele.net",
  "komputronik.pl",
  "neonet.pl",
  "rossmann.pl",
  "hebe.pl",
  "biedronka.pl",
  "lidl.pl",
  "kaufland.pl",
  "carrefour.pl",
  "auchan.pl",
  "zabka.pl",
  "orlen.pl",
  "pyszne.pl",
  "frisco.pl",

  // Polskie banki
  "pkobp.pl",
  "ipko.pl",
  "inteligo.pl",
  "pekao.com.pl",
  "mbank.pl",
  "ing.pl",
  "santander.pl",
  "santanderconsumer.pl",
  "bankmillennium.pl",
  "aliorbank.pl",
  "velobank.pl",
  "bosbank.pl",
  "pocztowy.pl",
  "credit-agricole.pl",
  "bnpparibas.pl",
  "citibankonline.pl",
  "citi.com",
  "nestbank.pl",
  "toyotabank.pl",
  "plusbank.pl",

  // Polskie płatności
  "blik.com",
  "payu.com",
  "przelewy24.pl",
  "tpay.com",
  "autopay.pl",
  "bluecash.pl",
  "skycash.com",

  // Administracja
  "gov.pl",
  "zus.pl",
  "epuap.gov.pl",
  "podatki.gov.pl",
  "biznes.gov.pl",
  "ceidg.gov.pl",
  "pacjent.gov.pl",
  "nfz.gov.pl",
  "poczta-polska.pl",
  "policja.pl",

  // Telekomunikacja
  "orange.pl",
  "t-mobile.pl",
  "play.pl",
  "plus.pl",
  "nju.pl",
  "virginmobile.pl",
  "vectra.pl",
  "upc.pl",
  "netia.pl",
  "multimedia.pl",
  "polsatbox.pl",

  // Energia
  "pge.pl",
  "tauron.pl",
  "enea.pl",
  "energa.pl",
  "pgnig.pl",

  // Ubezpieczenia
  "pzu.pl",
  "warta.pl",
  "allianz.pl",
  "link4.pl",
  "generali.pl",
  "ergohestia.pl",
  "uniqa.pl",
  "compensa.pl",

  // Transport
  "pkp.pl",
  "intercity.pl",
  "koleo.pl",
  "jakdojade.pl",
  "flixbus.pl",
  "lot.com",
  "ryanair.com",
  "wizzair.com",

  // Portale i media
  "onet.pl",
  "wp.pl",
  "interia.pl",
  "o2.pl",
  "gazeta.pl",
  "tvp.pl",
  "tvn.pl",
  "polsat.pl",
  "player.pl",
  "canalplus.com",
  "polsatboxgo.pl",
] as const;

const suspiciousAdditions = [
  "login",
  "logowanie",
  "signin",
  "secure",
  "security",
  "verify",
  "verification",
  "weryfikacja",
  "account",
  "konto",
  "support",
  "pomoc",
  "payment",
  "platnosc",
  "bank",
  "auth",
  "authentication",
  "update",
  "aktualizacja",
  "confirm",
  "confirmation",
  "potwierdzenie",
  "customer",
  "client",
  "unlock",
  "unblock",
  "recovery",
] as const;

function normalizeToken(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
}

function normalizeHostname(value: string): string {
  const trimmedValue = value.trim();

  if (!trimmedValue) {
    return "";
  }

  try {
    const hasProtocol = /^[a-z][a-z\d+\-.]*:\/\//i.test(trimmedValue);

    const url = new URL(hasProtocol ? trimmedValue : `https://${trimmedValue}`);

    return url.hostname.toLowerCase().replace(/\.$/, "");
  } catch {
    return "";
  }
}

function createCharacterVariants(value: string): string[] {
  return [
    value,

    value
      .replace(/0/g, "o")
      .replace(/1/g, "l")
      .replace(/3/g, "e")
      .replace(/5/g, "s")
      .replace(/7/g, "t"),

    value
      .replace(/0/g, "o")
      .replace(/1/g, "i")
      .replace(/3/g, "e")
      .replace(/5/g, "s")
      .replace(/7/g, "t"),
  ];
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function removeSuspiciousAdditions(value: string): string {
  let result = value;

  for (const addition of suspiciousAdditions) {
    const normalizedAddition = normalizeToken(addition);

    result = result.replace(
      new RegExp(escapeRegExp(normalizedAddition), "g"),
      "",
    );
  }

  return result.replace(/^\d+|\d+$/g, "");
}

function getAllowedDistance(brand: string): number {
  /*
   * Krótkie marki generują dużo fałszywych wyników.
   * Dlatego dla np. PZU, PGE, PKP wymagamy dokładnej nazwy.
   */
  if (brand.length <= 4) {
    return 0;
  }

  if (brand.length <= 7) {
    return 1;
  }

  return 2;
}

const normalizedBrands = Array.from(
  new Set(knownBrands.map((brand) => normalizeToken(brand))),
);

/**
 * A label receives the regional-domain policy only if the allowlist proves
 * that the same label is already used as an official registrable domain. This
 * scales to brands such as `huawei`, `lenovo` and `visa` without enumerating
 * every country suffix, while aliases with no official root (for example
 * `appleid`) remain high-risk outside the allowlist.
 */
const normalizedBrandSet = new Set(normalizedBrands);
const regionalBrandLabels = new Set<string>();
const officialBrandLabelForms = new Map<string, Set<string>>();

for (const officialDomain of officialDomains) {
  const parsedDomain = parse(officialDomain, {
    allowPrivateDomains: true,
    extractHostname: false,
  });
  const rawLabel = parsedDomain.domainWithoutSuffix?.toLowerCase() ?? "";
  const normalizedLabel = normalizeToken(rawLabel);

  if (!normalizedBrandSet.has(normalizedLabel)) {
    continue;
  }

  regionalBrandLabels.add(normalizedLabel);

  const forms = officialBrandLabelForms.get(normalizedLabel) ?? new Set();
  forms.add(rawLabel);
  officialBrandLabelForms.set(normalizedLabel, forms);
}

const riskyPublicSuffixes = new Set([
  "buzz",
  "cf",
  "click",
  "ga",
  "gq",
  "icu",
  "ml",
  "mov",
  "tk",
  "top",
  "work",
  "xyz",
  "zip",
]);

/*
 * Most of these are already represented in the private section of the Public
 * Suffix List. The explicit entries also protect us if a provider changes or
 * removes its PSL rule. In particular, `amazonaws.com` is an official Amazon
 * domain but its tenants must not inherit Amazon's allowlist entry.
 */
const sharedHostingSuffixes = new Set([
  "amazonaws.com",
  "appspot.com",
  "cloudfront.net",
  "github.io",
  "netlify.app",
  "pages.dev",
  "vercel.app",
  "web.app",
]);

export type DomainMatchProvenance =
  | "raw"
  | "split"
  | "addition-stripped"
  | "leet"
  | "fuzzy";

export type SuspiciousDomainReason =
  | "unverified-regional-brand"
  | "non-regional-brand-domain"
  | "suspicious-addition"
  | "brand-in-foreign-subdomain"
  | "character-substitution"
  | "numeric-affix"
  | "brand-label-obfuscation"
  | "lookalike-spelling"
  | "risky-public-suffix"
  | "private-or-shared-hosting";

export interface DomainAnalysis {
  hostname: string;
  isSuspicious: boolean;
  isOfficial: boolean;
  score: number;
  reasons: SuspiciousDomainReason[];
  matchedBrand: string | null;
  provenance: DomainMatchProvenance | null;
}

type CandidateLocation = "registrable" | "subdomain";

interface DomainCandidate {
  value: string;
  provenance: Exclude<DomainMatchProvenance, "fuzzy">;
  location: CandidateLocation;
  normalizedLabel: string;
  sourceLabel: string;
}

interface ParsedHostname {
  domain: string | null;
  domainWithoutSuffix: string | null;
  publicSuffix: string | null;
  subdomain: string | null;
  isIcann: boolean | null;
  isPrivate: boolean | null;
  isIp: boolean | null;
}

interface MatchEvidence {
  score: number;
  reasons: SuspiciousDomainReason[];
  matchedBrand: string;
  provenance: DomainMatchProvenance;
}

const suspiciousScoreThreshold = 3;

function emptyAnalysis(hostname: string): DomainAnalysis {
  return {
    hostname,
    isSuspicious: false,
    isOfficial: false,
    score: 0,
    reasons: [],
    matchedBrand: null,
    provenance: null,
  };
}

function isSharedHostingHostname(hostname: string): boolean {
  return Array.from(sharedHostingSuffixes).some((suffix) => {
    return hostname !== suffix && hostname.endsWith(`.${suffix}`);
  });
}

function isOfficialDomain(
  hostname: string,
  parsedHostname: ParsedHostname,
): boolean {
  return officialDomains.some((officialDomain) => {
    if (hostname === officialDomain) {
      return true;
    }

    if (!hostname.endsWith(`.${officialDomain}`)) {
      return false;
    }

    if (sharedHostingSuffixes.has(officialDomain)) {
      return false;
    }

    /*
     * A hostname below an official domain is trusted only while it stays inside
     * the same registrable-domain boundary. This prevents a private PSL tenant
     * from inheriting an allowlist entry owned by its hosting provider.
     */
    return parsedHostname.domain === officialDomain;
  });
}

function getPlainRegionalBrand(
  hostname: string,
  parsedHostname: ParsedHostname,
): string | null {
  const registrableLabel = normalizeToken(
    parsedHostname.domainWithoutSuffix ?? "",
  );
  const sourceLabel = parsedHostname.domainWithoutSuffix?.toLowerCase() ?? "";

  if (
    !regionalBrandLabels.has(registrableLabel) ||
    !isKnownBrandLabelForm(sourceLabel, registrableLabel)
  ) {
    return null;
  }

  if (
    !parsedHostname.isIcann ||
    parsedHostname.isPrivate ||
    isSharedHostingHostname(hostname) ||
    (parsedHostname.publicSuffix &&
      riskyPublicSuffixes.has(parsedHostname.publicSuffix))
  ) {
    return null;
  }

  return registrableLabel;
}

function isKnownBrandLabelForm(sourceLabel: string, brand: string): boolean {
  return (
    sourceLabel === brand ||
    officialBrandLabelForms.get(brand)?.has(sourceLabel) === true
  );
}

function addCandidate(
  candidates: DomainCandidate[],
  seenCandidates: Set<string>,
  value: string,
  provenance: Exclude<DomainMatchProvenance, "fuzzy">,
  location: CandidateLocation,
  normalizedLabel: string,
  sourceLabel: string,
): void {
  if (value.length < 3) {
    return;
  }

  const key = `${location}:${normalizedLabel}:${provenance}:${value}`;

  if (seenCandidates.has(key)) {
    return;
  }

  seenCandidates.add(key);
  candidates.push({
    value,
    provenance,
    location,
    normalizedLabel,
    sourceLabel,
  });
}

function getLabelCandidates(
  label: string,
  location: CandidateLocation,
): DomainCandidate[] {
  const candidates: DomainCandidate[] = [];
  const seenCandidates = new Set<string>();
  const normalizedLabel = normalizeToken(label);
  const sourceLabel = label.toLowerCase();

  addCandidate(
    candidates,
    seenCandidates,
    normalizedLabel,
    "raw",
    location,
    normalizedLabel,
    sourceLabel,
  );

  for (const part of label.split(/[-_]/)) {
    addCandidate(
      candidates,
      seenCandidates,
      normalizeToken(part),
      "split",
      location,
      normalizedLabel,
      sourceLabel,
    );
  }

  const withoutSuspiciousAdditions = removeSuspiciousAdditions(normalizedLabel);

  if (withoutSuspiciousAdditions !== normalizedLabel) {
    addCandidate(
      candidates,
      seenCandidates,
      withoutSuspiciousAdditions,
      "addition-stripped",
      location,
      normalizedLabel,
      sourceLabel,
    );
  }

  for (const brand of normalizedBrands) {
    const brandIndex = normalizedLabel.indexOf(brand);

    if (brandIndex === -1) {
      continue;
    }

    const beforeBrand = normalizedLabel.slice(0, brandIndex);
    const afterBrand = normalizedLabel.slice(brandIndex + brand.length);
    const hasExtraDigits = beforeBrand.length > 0 || afterBrand.length > 0;

    if (
      hasExtraDigits &&
      /^\d*$/.test(beforeBrand) &&
      /^\d*$/.test(afterBrand)
    ) {
      addCandidate(
        candidates,
        seenCandidates,
        brand,
        "addition-stripped",
        location,
        normalizedLabel,
        sourceLabel,
      );
    }
  }

  const baseCandidates = [...candidates];

  for (const candidate of baseCandidates) {
    for (const variant of createCharacterVariants(candidate.value)) {
      if (variant !== candidate.value) {
        addCandidate(
          candidates,
          seenCandidates,
          variant,
          "leet",
          location,
          normalizedLabel,
          sourceLabel,
        );
      }
    }
  }

  return candidates;
}

function getDomainCandidates(
  parsedHostname: ParsedHostname,
): DomainCandidate[] {
  const candidates: DomainCandidate[] = [];

  if (parsedHostname.domainWithoutSuffix) {
    candidates.push(
      ...getLabelCandidates(parsedHostname.domainWithoutSuffix, "registrable"),
    );
  }

  if (parsedHostname.subdomain) {
    for (const label of parsedHostname.subdomain.split(".").filter(Boolean)) {
      candidates.push(...getLabelCandidates(label, "subdomain"));
    }
  }

  return candidates;
}

function getAdditionsBesideBrand(
  normalizedLabel: string,
  brand: string,
): string[] {
  const brandIndex = normalizedLabel.indexOf(brand);

  if (brandIndex === -1) {
    return [];
  }

  /*
   * Remove the matched brand before looking for additions. Otherwise brands
   * such as `bankmillennium` would match the addition `bank` inside themselves.
   */
  const textBesideBrand =
    normalizedLabel.slice(0, brandIndex) +
    normalizedLabel.slice(brandIndex + brand.length);

  return suspiciousAdditions.filter((addition) => {
    return textBesideBrand.includes(normalizeToken(addition));
  });
}

function getTextBesideBrand(normalizedLabel: string, brand: string): string {
  const brandIndex = normalizedLabel.indexOf(brand);

  if (brandIndex === -1) {
    return "";
  }

  return (
    normalizedLabel.slice(0, brandIndex) +
    normalizedLabel.slice(brandIndex + brand.length)
  );
}

function addReason(
  evidence: MatchEvidence,
  reason: SuspiciousDomainReason,
  score: number,
): void {
  if (evidence.reasons.includes(reason)) {
    return;
  }

  evidence.reasons.push(reason);
  evidence.score += score;
}

function createEvidence(
  candidate: DomainCandidate,
  brand: string,
  parsedHostname: ParsedHostname,
  hostname: string,
  fuzzyMatch: boolean,
): MatchEvidence {
  const provenance: DomainMatchProvenance =
    fuzzyMatch ? "fuzzy" : candidate.provenance;
  const evidence: MatchEvidence = {
    score: 0,
    reasons: [],
    matchedBrand: brand,
    provenance,
  };
  const registrableBrand = normalizeToken(
    parsedHostname.domainWithoutSuffix ?? "",
  );
  const brandIsInForeignSubdomain =
    candidate.location === "subdomain" && registrableBrand !== brand;

  if (fuzzyMatch) {
    addReason(evidence, "lookalike-spelling", 3);
  } else if (candidate.provenance === "leet") {
    addReason(evidence, "character-substitution", 3);
  } else if (brandIsInForeignSubdomain) {
    addReason(evidence, "brand-in-foreign-subdomain", 3);
  } else if (regionalBrandLabels.has(brand)) {
    addReason(evidence, "unverified-regional-brand", 1);
  } else {
    addReason(evidence, "non-regional-brand-domain", 3);
  }

  if (
    candidate.location === "registrable" &&
    getAdditionsBesideBrand(candidate.normalizedLabel, brand).length > 0
  ) {
    addReason(evidence, "suspicious-addition", 2);
  }

  if (
    candidate.location === "registrable" &&
    /\d/.test(getTextBesideBrand(candidate.normalizedLabel, brand))
  ) {
    addReason(evidence, "numeric-affix", 2);
  }

  if (
    candidate.location === "registrable" &&
    normalizeToken(candidate.sourceLabel) === brand &&
    !isKnownBrandLabelForm(candidate.sourceLabel, brand)
  ) {
    addReason(evidence, "brand-label-obfuscation", 2);
  }

  if (
    parsedHostname.publicSuffix &&
    riskyPublicSuffixes.has(parsedHostname.publicSuffix)
  ) {
    addReason(evidence, "risky-public-suffix", 2);
  }

  if (parsedHostname.isPrivate || isSharedHostingHostname(hostname)) {
    addReason(evidence, "private-or-shared-hosting", 2);
  }

  return evidence;
}

const provenancePriority: Record<DomainMatchProvenance, number> = {
  raw: 0,
  split: 1,
  "addition-stripped": 2,
  fuzzy: 3,
  leet: 4,
};

function isBetterEvidence(
  candidate: MatchEvidence,
  current: MatchEvidence | null,
): boolean {
  if (!current || candidate.score !== current.score) {
    return !current || candidate.score > current.score;
  }

  const candidatePriority = provenancePriority[candidate.provenance];
  const currentPriority = provenancePriority[current.provenance];

  if (candidatePriority !== currentPriority) {
    return candidatePriority > currentPriority;
  }

  return candidate.matchedBrand.length > current.matchedBrand.length;
}

export function analyzeDomain(domain: string): DomainAnalysis {
  const hostname = normalizeHostname(domain);

  if (!hostname) {
    return emptyAnalysis(hostname);
  }

  const parsedHostname = parse(hostname, {
    allowPrivateDomains: true,
    extractHostname: false,
  }) as ParsedHostname;

  if (
    parsedHostname.isIp ||
    (!parsedHostname.isIcann && !parsedHostname.isPrivate) ||
    !parsedHostname.domain ||
    !parsedHostname.domainWithoutSuffix ||
    !parsedHostname.publicSuffix
  ) {
    return emptyAnalysis(hostname);
  }

  if (isOfficialDomain(hostname, parsedHostname)) {
    return { ...emptyAnalysis(hostname), isOfficial: true };
  }

  /*
   * Accepting an exact company label on an ordinary public suffix is the
   * deliberate regional-domain policy. Once that registrable domain is
   * accepted, its subdomains inherit the same result: `mail.google.de` is not
   * a case of a brand decorating a foreign domain. Risky and shared-hosting
   * suffixes are intentionally excluded from this shortcut.
   */
  const plainRegionalBrand = getPlainRegionalBrand(hostname, parsedHostname);

  if (plainRegionalBrand) {
    return {
      hostname,
      isSuspicious: false,
      isOfficial: false,
      score: 1,
      reasons: ["unverified-regional-brand"],
      matchedBrand: plainRegionalBrand,
      provenance: "raw",
    };
  }

  const candidates = getDomainCandidates(parsedHostname);
  let bestEvidence: MatchEvidence | null = null;

  for (const candidate of candidates) {
    for (const brand of normalizedBrands) {
      if (candidate.value === brand) {
        const evidence = createEvidence(
          candidate,
          brand,
          parsedHostname,
          hostname,
          false,
        );

        if (isBetterEvidence(evidence, bestEvidence)) {
          bestEvidence = evidence;
        }

        continue;
      }

      const allowedDistance = getAllowedDistance(brand);

      if (
        allowedDistance === 0 ||
        Math.abs(candidate.value.length - brand.length) > allowedDistance
      ) {
        continue;
      }

      const distance = levenshtein(candidate.value, brand);

      if (distance === 0 || distance > allowedDistance) {
        continue;
      }

      const evidence = createEvidence(
        candidate,
        brand,
        parsedHostname,
        hostname,
        true,
      );

      if (isBetterEvidence(evidence, bestEvidence)) {
        bestEvidence = evidence;
      }
    }
  }

  if (!bestEvidence) {
    return emptyAnalysis(hostname);
  }

  return {
    hostname,
    isSuspicious: bestEvidence.score >= suspiciousScoreThreshold,
    isOfficial: false,
    score: bestEvidence.score,
    reasons: bestEvidence.reasons,
    matchedBrand: bestEvidence.matchedBrand,
    provenance: bestEvidence.provenance,
  };
}

export function isSuspiciousDomain(domain: string): boolean {
  return analyzeDomain(domain).isSuspicious;
}
