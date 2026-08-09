import re
import unicodedata
from dataclasses import dataclass
from typing import Literal, TypeAlias
from urllib.parse import urlparse

import tldextract
from Levenshtein import distance as levenshtein

# --- DANE (przepisz z TS) ---
KNOWN_BRANDS = [
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
  "dhl",
  "fedex",
  "ups",
  "dpd",
  "gls",
  "inpost",
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
  "blik",
  "payu",
  "przelewy24",
  "tpay",
  "autopay",
  "bluecash",
  "skycash",
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
  "pge",
  "tauron",
  "enea",
  "energa",
  "pgnig",
  "pzu",
  "warta",
  "allianz",
  "link4",
  "generali",
  "ergohestia",
  "uniqa",
  "compensa",
  "aviva",
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
]

OFFICIAL_DOMAINS = [
    "google.com",
  "google.pl",
  "gmail.com",
  "youtube.com",

  "apple.com",
  "icloud.com",

  "microsoft.com",
  "microsoftonline.com",
  "live.com",
  "outlook.com",
  "office.com",
  "office365.com",
  "onedrive.com",
  "azure.com",
  "xbox.com",

  "amazon.com",
  "amazon.pl",
  "amazon.de",
  "amazon.co.uk",
  "amazonaws.com",
  "primevideo.com",

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


  "dhl.com",
  "fedex.com",
  "ups.com",
  "dpd.com",
  "dpdgroup.com",
  "gls-group.com",
  "gls-poland.com",
  "inpost.pl",


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


  "blik.com",
  "payu.com",
  "przelewy24.pl",
  "tpay.com",
  "autopay.pl",
  "bluecash.pl",
  "skycash.com",


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


  "pge.pl",
  "tauron.pl",
  "enea.pl",
  "energa.pl",
  "pgnig.pl",


  "pzu.pl",
  "warta.pl",
  "allianz.pl",
  "link4.pl",
  "generali.pl",
  "ergohestia.pl",
  "uniqa.pl",
  "compensa.pl",


  "pkp.pl",
  "intercity.pl",
  "koleo.pl",
  "jakdojade.pl",
  "flixbus.pl",
  "lot.com",
  "ryanair.com",
  "wizzair.com",


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
]

SUSPICIOUS_ADDITIONS = [
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
]

# The bundled PSL snapshot makes parsing deterministic and keeps runtime fully
# offline. ``cache_dir=None`` also avoids cache writes outside the application.
_TLD_EXTRACT = tldextract.TLDExtract(
    suffix_list_urls=(),
    include_psl_private_domains=True,
    cache_dir=None,
)

DomainMatchProvenance: TypeAlias = Literal[
    "raw",
    "split",
    "addition-stripped",
    "leet",
    "fuzzy",
]
SuspiciousDomainReason: TypeAlias = Literal[
    "unverified-regional-brand",
    "non-regional-brand-domain",
    "suspicious-addition",
    "brand-in-foreign-subdomain",
    "character-substitution",
    "numeric-affix",
    "brand-label-obfuscation",
    "lookalike-spelling",
    "risky-public-suffix",
    "private-or-shared-hosting",
]
CandidateLocation: TypeAlias = Literal["registrable", "subdomain"]


@dataclass(frozen=True, slots=True)
class DomainAnalysis:
    hostname: str
    is_suspicious: bool
    score: int
    reasons: tuple[SuspiciousDomainReason, ...]
    matched_brand: str | None
    provenance: DomainMatchProvenance | None


@dataclass(frozen=True, slots=True)
class ParsedHostname:
    domain: str
    domain_without_suffix: str
    public_suffix: str
    subdomain: str
    is_icann: bool
    is_private: bool


@dataclass(frozen=True, slots=True)
class DomainCandidate:
    value: str
    provenance: Literal["raw", "split", "addition-stripped", "leet"]
    location: CandidateLocation
    normalized_label: str
    source_label: str


@dataclass(slots=True)
class MatchEvidence:
    score: int
    reasons: list[SuspiciousDomainReason]
    matched_brand: str
    provenance: DomainMatchProvenance


RISKY_PUBLIC_SUFFIXES = {
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
}

# Most entries are private PSL suffixes. Explicit entries keep the policy clear
# and cover shared providers such as amazonaws.com whose tenant boundary is not
# represented by a single private PSL rule.
SHARED_HOSTING_SUFFIXES = {
    "amazonaws.com",
    "appspot.com",
    "cloudfront.net",
    "github.io",
    "netlify.app",
    "pages.dev",
    "vercel.app",
    "web.app",
}

SUSPICIOUS_SCORE_THRESHOLD = 3
PROVENANCE_PRIORITY: dict[DomainMatchProvenance, int] = {
    "raw": 0,
    "split": 1,
    "addition-stripped": 2,
    "fuzzy": 3,
    "leet": 4,
}


def normalize_token(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = re.sub(r"[\u0300-\u036f]", "", value)
    return re.sub(r"[^a-z0-9]", "", value.lower())


def normalize_hostname(value: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        return ""

    has_protocol = re.match(r"^[a-z][a-z\d+\-.]*://", trimmed, re.IGNORECASE)
    try:
        parsed = urlparse(trimmed if has_protocol else f"https://{trimmed}")
        hostname = parsed.hostname or ""
        return hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except (UnicodeError, ValueError):
        return ""


def parse_hostname(hostname: str) -> ParsedHostname | None:
    extracted = _TLD_EXTRACT(hostname)

    if not extracted.domain or not extracted.suffix:
        return None

    return ParsedHostname(
        domain=extracted.top_domain_under_public_suffix,
        domain_without_suffix=extracted.domain,
        public_suffix=extracted.suffix,
        subdomain=extracted.subdomain,
        # With no extra suffixes configured, every recognized non-private rule
        # comes from the ICANN section of the bundled PSL snapshot.
        is_icann=not extracted.is_private,
        is_private=extracted.is_private,
    )


# A label receives the regional-domain policy only if the allowlist proves that
# it is already used as an official registrable domain. This avoids maintaining
# country-by-country variants while keeping aliases without an official root,
# such as appleid, outside the policy.
_NORMALIZED_BRAND_SET = {normalize_token(brand) for brand in KNOWN_BRANDS}
REGIONAL_BRAND_LABELS: set[str] = set()
OFFICIAL_BRAND_LABEL_FORMS: dict[str, set[str]] = {}

for official_domain in OFFICIAL_DOMAINS:
    parsed_official_domain = parse_hostname(official_domain)
    if parsed_official_domain is None:
        continue

    source_label = parsed_official_domain.domain_without_suffix.lower()
    normalized_label = normalize_token(source_label)
    if normalized_label not in _NORMALIZED_BRAND_SET:
        continue

    REGIONAL_BRAND_LABELS.add(normalized_label)
    OFFICIAL_BRAND_LABEL_FORMS.setdefault(normalized_label, set()).add(source_label)


def is_shared_hosting_hostname(hostname: str) -> bool:
    return any(
        hostname != suffix and hostname.endswith(f".{suffix}")
        for suffix in SHARED_HOSTING_SUFFIXES
    )


def is_official_domain(
    hostname: str,
    parsed_hostname: ParsedHostname | None = None,
) -> bool:
    parsed_hostname = parsed_hostname or parse_hostname(hostname)

    for official_domain in OFFICIAL_DOMAINS:
        if hostname == official_domain:
            return True

        if not hostname.endswith(f".{official_domain}"):
            continue

        if official_domain in SHARED_HOSTING_SUFFIXES:
            continue

        # A subdomain is trusted only while it remains within the same
        # registrable-domain boundary. Private/shared tenants must not inherit
        # the hosting provider's allowlist entry.
        if parsed_hostname and parsed_hostname.domain == official_domain:
            return True

    return False


def get_plain_regional_brand(
    hostname: str,
    parsed_hostname: ParsedHostname,
) -> str | None:
    registrable_label = normalize_token(parsed_hostname.domain_without_suffix)
    source_label = parsed_hostname.domain_without_suffix.lower()

    if registrable_label not in REGIONAL_BRAND_LABELS or not is_known_brand_label_form(
        source_label,
        registrable_label,
    ):
        return None

    if (
        not parsed_hostname.is_icann
        or parsed_hostname.is_private
        or is_shared_hosting_hostname(hostname)
        or parsed_hostname.public_suffix in RISKY_PUBLIC_SUFFIXES
    ):
        return None

    return registrable_label


def is_known_brand_label_form(source_label: str, brand: str) -> bool:
    return source_label == brand or source_label in OFFICIAL_BRAND_LABEL_FORMS.get(
        brand,
        set(),
    )


def create_character_variants(value: str) -> list[str]:
    return [
        value,
        value.replace("0", "o")
        .replace("1", "l")
        .replace("3", "e")
        .replace("5", "s")
        .replace("7", "t"),
        value.replace("0", "o")
        .replace("1", "i")
        .replace("3", "e")
        .replace("5", "s")
        .replace("7", "t"),
    ]


def remove_suspicious_additions(value: str) -> str:
    result = value
    for addition in SUSPICIOUS_ADDITIONS:
        result = result.replace(normalize_token(addition), "")
    return re.sub(r"^\d+|\d+$", "", result)


def add_candidate(
    candidates: list[DomainCandidate],
    seen_candidates: set[tuple[str, str, str, str]],
    value: str,
    provenance: Literal["raw", "split", "addition-stripped", "leet"],
    location: CandidateLocation,
    normalized_label: str,
    source_label: str,
) -> None:
    if len(value) < 3:
        return

    key = (location, normalized_label, provenance, value)
    if key in seen_candidates:
        return

    seen_candidates.add(key)
    candidates.append(
        DomainCandidate(
            value=value,
            provenance=provenance,
            location=location,
            normalized_label=normalized_label,
            source_label=source_label,
        )
    )


def get_label_candidates(
    label: str,
    location: CandidateLocation,
) -> list[DomainCandidate]:
    candidates: list[DomainCandidate] = []
    seen_candidates: set[tuple[str, str, str, str]] = set()
    normalized_label = normalize_token(label)
    source_label = label.lower()

    add_candidate(
        candidates,
        seen_candidates,
        normalized_label,
        "raw",
        location,
        normalized_label,
        source_label,
    )

    for part in re.split(r"[-_]", label):
        add_candidate(
            candidates,
            seen_candidates,
            normalize_token(part),
            "split",
            location,
            normalized_label,
            source_label,
        )

    without_additions = remove_suspicious_additions(normalized_label)
    if without_additions != normalized_label:
        add_candidate(
            candidates,
            seen_candidates,
            without_additions,
            "addition-stripped",
            location,
            normalized_label,
            source_label,
        )

    for brand in NORMALIZED_BRANDS:
        brand_index = normalized_label.find(brand)
        if brand_index == -1:
            continue

        before_brand = normalized_label[:brand_index]
        after_brand = normalized_label[brand_index + len(brand) :]
        has_extra_digits = bool(before_brand or after_brand)
        before_is_digits = not before_brand or before_brand.isdigit()
        after_is_digits = not after_brand or after_brand.isdigit()

        if has_extra_digits and before_is_digits and after_is_digits:
            add_candidate(
                candidates,
                seen_candidates,
                brand,
                "addition-stripped",
                location,
                normalized_label,
                source_label,
            )

    for candidate in list(candidates):
        for variant in create_character_variants(candidate.value):
            if variant != candidate.value:
                add_candidate(
                    candidates,
                    seen_candidates,
                    variant,
                    "leet",
                    location,
                    normalized_label,
                    source_label,
                )

    return candidates


def get_domain_candidates(parsed_hostname: ParsedHostname) -> list[DomainCandidate]:
    candidates = get_label_candidates(
        parsed_hostname.domain_without_suffix,
        "registrable",
    )

    for label in filter(None, parsed_hostname.subdomain.split(".")):
        candidates.extend(get_label_candidates(label, "subdomain"))

    return candidates


def get_allowed_distance(brand: str) -> int:
    if len(brand) <= 4:
        return 0
    if len(brand) <= 7:
        return 1
    return 2


# dict preserves the source order while removing the duplicate primevideo entry.
NORMALIZED_BRANDS = list(
    dict.fromkeys(normalize_token(brand) for brand in KNOWN_BRANDS)
)


def get_additions_beside_brand(normalized_label: str, brand: str) -> list[str]:
    brand_index = normalized_label.find(brand)
    if brand_index == -1:
        return []

    # Remove the brand first, otherwise a legitimate brand such as
    # bankmillennium would match the addition "bank" inside its own name.
    text_beside_brand = (
        normalized_label[:brand_index]
        + normalized_label[brand_index + len(brand) :]
    )
    return [
        addition
        for addition in SUSPICIOUS_ADDITIONS
        if normalize_token(addition) in text_beside_brand
    ]


def get_text_beside_brand(normalized_label: str, brand: str) -> str:
    brand_index = normalized_label.find(brand)
    if brand_index == -1:
        return ""

    return (
        normalized_label[:brand_index]
        + normalized_label[brand_index + len(brand) :]
    )


def add_reason(
    evidence: MatchEvidence,
    reason: SuspiciousDomainReason,
    score: int,
) -> None:
    if reason in evidence.reasons:
        return

    evidence.reasons.append(reason)
    evidence.score += score


def create_evidence(
    candidate: DomainCandidate,
    brand: str,
    parsed_hostname: ParsedHostname,
    hostname: str,
    fuzzy_match: bool,
) -> MatchEvidence:
    provenance: DomainMatchProvenance = (
        "fuzzy" if fuzzy_match else candidate.provenance
    )
    evidence = MatchEvidence(
        score=0,
        reasons=[],
        matched_brand=brand,
        provenance=provenance,
    )
    registrable_brand = normalize_token(parsed_hostname.domain_without_suffix)
    brand_is_in_foreign_subdomain = (
        candidate.location == "subdomain" and registrable_brand != brand
    )

    if fuzzy_match:
        add_reason(evidence, "lookalike-spelling", 3)
    elif candidate.provenance == "leet":
        add_reason(evidence, "character-substitution", 3)
    elif brand_is_in_foreign_subdomain:
        add_reason(evidence, "brand-in-foreign-subdomain", 3)
    elif brand in REGIONAL_BRAND_LABELS:
        add_reason(evidence, "unverified-regional-brand", 1)
    else:
        add_reason(evidence, "non-regional-brand-domain", 3)

    if (
        candidate.location == "registrable"
        and get_additions_beside_brand(candidate.normalized_label, brand)
    ):
        add_reason(evidence, "suspicious-addition", 2)

    if candidate.location == "registrable" and any(
        character.isdigit()
        for character in get_text_beside_brand(candidate.normalized_label, brand)
    ):
        add_reason(evidence, "numeric-affix", 2)

    if (
        candidate.location == "registrable"
        and normalize_token(candidate.source_label) == brand
        and not is_known_brand_label_form(candidate.source_label, brand)
    ):
        add_reason(evidence, "brand-label-obfuscation", 2)

    if parsed_hostname.public_suffix in RISKY_PUBLIC_SUFFIXES:
        add_reason(evidence, "risky-public-suffix", 2)

    if parsed_hostname.is_private or is_shared_hosting_hostname(hostname):
        add_reason(evidence, "private-or-shared-hosting", 2)

    return evidence


def is_better_evidence(
    candidate: MatchEvidence,
    current: MatchEvidence | None,
) -> bool:
    if current is None or candidate.score != current.score:
        return current is None or candidate.score > current.score

    candidate_priority = PROVENANCE_PRIORITY[candidate.provenance]
    current_priority = PROVENANCE_PRIORITY[current.provenance]
    if candidate_priority != current_priority:
        return candidate_priority > current_priority

    return len(candidate.matched_brand) > len(current.matched_brand)


def empty_analysis(hostname: str) -> DomainAnalysis:
    return DomainAnalysis(
        hostname=hostname,
        is_suspicious=False,
        score=0,
        reasons=(),
        matched_brand=None,
        provenance=None,
    )


def analyze_domain(domain: str) -> DomainAnalysis:
    """Return the decision together with its score, reasons and match source."""

    hostname = normalize_hostname(domain)
    if not hostname:
        return empty_analysis(hostname)

    parsed_hostname = parse_hostname(hostname)
    if parsed_hostname is None:
        return empty_analysis(hostname)

    if is_official_domain(hostname, parsed_hostname):
        return empty_analysis(hostname)

    # A plain company label on an ordinary ICANN suffix is the deliberate
    # regional-domain policy. Once accepted, its subdomains inherit the result.
    # Risky and shared/private suffixes are excluded from this shortcut.
    plain_regional_brand = get_plain_regional_brand(hostname, parsed_hostname)
    if plain_regional_brand:
        return DomainAnalysis(
            hostname=hostname,
            is_suspicious=False,
            score=1,
            reasons=("unverified-regional-brand",),
            matched_brand=plain_regional_brand,
            provenance="raw",
        )

    best_evidence: MatchEvidence | None = None

    for candidate in get_domain_candidates(parsed_hostname):
        for brand in NORMALIZED_BRANDS:
            if candidate.value == brand:
                evidence = create_evidence(
                    candidate,
                    brand,
                    parsed_hostname,
                    hostname,
                    fuzzy_match=False,
                )
                if is_better_evidence(evidence, best_evidence):
                    best_evidence = evidence
                continue

            allowed_distance = get_allowed_distance(brand)
            if (
                allowed_distance == 0
                or abs(len(candidate.value) - len(brand)) > allowed_distance
            ):
                continue

            edit_distance = levenshtein(candidate.value, brand)
            if edit_distance == 0 or edit_distance > allowed_distance:
                continue

            evidence = create_evidence(
                candidate,
                brand,
                parsed_hostname,
                hostname,
                fuzzy_match=True,
            )
            if is_better_evidence(evidence, best_evidence):
                best_evidence = evidence

    if best_evidence is None:
        return empty_analysis(hostname)

    return DomainAnalysis(
        hostname=hostname,
        is_suspicious=best_evidence.score >= SUSPICIOUS_SCORE_THRESHOLD,
        score=best_evidence.score,
        reasons=tuple(best_evidence.reasons),
        matched_brand=best_evidence.matched_brand,
        provenance=best_evidence.provenance,
    )


def is_suspicious_domain(domain: str) -> bool:
    """Compatibility wrapper used by SuspiciousDomainTool."""

    return analyze_domain(domain).is_suspicious
