import re
import unicodedata
from urllib.parse import urlparse
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

# --- FUNKCJE POMOCNICZE ---
def normalize_token(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = re.sub(r"[\u0300-\u036f]", "", value)
    return re.sub(r"[^a-z0-9]", "", value.lower())


def normalize_hostname(value: str) -> str:
    trimmed = value.strip()
    has_protocol = re.match(r"^[a-z][a-z\d+\-.]*://", trimmed, re.IGNORECASE)
    try:
        parsed = urlparse(trimmed if has_protocol else f"https://{trimmed}")
        hostname = parsed.hostname or ""
        return hostname.lower().removeprefix("www.").rstrip(".")
    except Exception:
        cleaned = re.sub(r"^https?://", "", trimmed.lower())
        cleaned = cleaned.removeprefix("www.")
        cleaned = re.split(r"[/?#]", cleaned)[0].split(":")[0]
        return cleaned.rstrip(".")


def is_official_domain(hostname: str) -> bool:
    return any(
        hostname == official or hostname.endswith(f".{official}")
        for official in OFFICIAL_DOMAINS
    )


def create_character_variants(value: str) -> list[str]:
    return [
        value,
        value.replace("0", "o").replace("1", "l").replace("3", "e").replace("5", "s").replace("7", "t"),
        value.replace("0", "o").replace("1", "i").replace("3", "e").replace("5", "s").replace("7", "t"),
    ]


def remove_suspicious_additions(value: str) -> str:
    result = value
    for addition in SUSPICIOUS_ADDITIONS:
        result = result.replace(normalize_token(addition), "")
    return re.sub(r"^\d+|\d+$", "", result)


def get_domain_candidates(hostname: str) -> list[str]:
    candidates: set[str] = set()
    labels = [label for label in hostname.split(".") if label]
    labels_without_tld = labels[:-1]

    for label in labels_without_tld:
        normalized_label = normalize_token(label)
        if len(normalized_label) >= 3:
            candidates.add(normalized_label)

        for part in re.split(r"[-_]", label):
            normalized_part = normalize_token(part)
            if len(normalized_part) >= 3:
                candidates.add(normalized_part)

        without_additions = remove_suspicious_additions(normalized_label)
        if len(without_additions) >= 3:
            candidates.add(without_additions)

    with_variants: set[str] = set()
    for candidate in candidates:
        for variant in create_character_variants(candidate):
            if len(variant) >= 3:
                with_variants.add(variant)

    return list(with_variants)


def get_allowed_distance(brand: str) -> int:
    if len(brand) <= 4:
        return 0
    if len(brand) <= 7:
        return 1
    return 2

# --- STAŁA POCHODNA ---
NORMALIZED_BRANDS = list({normalize_token(b) for b in KNOWN_BRANDS})

# --- GŁÓWNA FUNKCJA ---
def _matches_brand(candidate: str, brand: str) -> bool:
    allowed = get_allowed_distance(brand)

    # dokładna nazwa marki na nieoficjalnej domenie
    if candidate == brand:
        return True

    if allowed == 0:
        return False

    # optymalizacja: różnica długości większa niż próg
    if abs(len(candidate) - len(brand)) > allowed:
        return False

    dist = levenshtein(candidate, brand)
    return 0 < dist <= allowed


def is_suspicious_domain(domain: str) -> bool:
    hostname = normalize_hostname(domain)

    if not hostname or "." not in hostname:
        return False

    if is_official_domain(hostname):
        return False

    candidates = get_domain_candidates(hostname)

    return any(
        _matches_brand(candidate, brand)
        for candidate in candidates
        for brand in NORMALIZED_BRANDS
    )