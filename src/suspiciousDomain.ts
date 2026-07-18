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

  try {
    const hasProtocol = /^[a-z][a-z\d+\-.]*:\/\//i.test(trimmedValue);

    const url = new URL(hasProtocol ? trimmedValue : `https://${trimmedValue}`);

    return url.hostname
      .toLowerCase()
      .replace(/^www\./, "")
      .replace(/\.$/, "");
  } catch {
    return trimmedValue
      .toLowerCase()
      .replace(/^https?:\/\//, "")
      .replace(/^www\./, "")
      .split(/[/?#]/)[0]
      .split(":")[0]
      .replace(/\.$/, "");
  }
}

function isOfficialDomain(hostname: string): boolean {
  return officialDomains.some((officialDomain) => {
    return (
      hostname === officialDomain || hostname.endsWith(`.${officialDomain}`)
    );
  });
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

function getDomainCandidates(hostname: string): string[] {
  const candidates = new Set<string>();
  const labels = hostname.split(".").filter(Boolean);

  /*
   * Pomijamy ostatni element domeny, ponieważ zazwyczaj jest to:
   * com, pl, net, org itd.
   */
  const labelsWithoutTld = labels.slice(0, -1);

  for (const label of labelsWithoutTld) {
    const normalizedLabel = normalizeToken(label);

    if (normalizedLabel.length >= 3) {
      candidates.add(normalizedLabel);
    }

    /*
     * Przykład:
     * paypal-login -> paypal oraz login
     */
    const labelParts = label.split(/[-_]/);

    for (const part of labelParts) {
      const normalizedPart = normalizeToken(part);

      if (normalizedPart.length >= 3) {
        candidates.add(normalizedPart);
      }
    }

    /*
     * Przykład:
     * paypallogin -> paypal
     */
    const withoutSuspiciousWords = removeSuspiciousAdditions(normalizedLabel);

    if (withoutSuspiciousWords.length >= 3) {
      candidates.add(withoutSuspiciousWords);
    }
  }

  const candidatesWithVariants = new Set<string>();

  for (const candidate of candidates) {
    const variants = createCharacterVariants(candidate);

    for (const variant of variants) {
      if (variant.length >= 3) {
        candidatesWithVariants.add(variant);
      }
    }
  }

  return Array.from(candidatesWithVariants);
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

export function isSuspiciousDomain(domain: string): boolean {
  const hostname = normalizeHostname(domain);

  if (!hostname || !hostname.includes(".")) {
    return false;
  }

  if (isOfficialDomain(hostname)) {
    return false;
  }

  const candidates = getDomainCandidates(hostname);

  return candidates.some((candidate) => {
    return normalizedBrands.some((brand) => {
      const allowedDistance = getAllowedDistance(brand);

      /*
       * Dokładna nazwa marki na nieoficjalnej domenie:
       *
       * paypal-login.com
       * allegro-pomoc.net
       * pkobp-logowanie.com
       */
      if (candidate === brand) {
        return true;
      }

      if (allowedDistance === 0) {
        return false;
      }

      /*
       * Jeżeli różnica długości jest większa niż dopuszczalny
       * dystans, nie ma potrzeby liczenia Levenshteina.
       */
      if (Math.abs(candidate.length - brand.length) > allowedDistance) {
        return false;
      }

      const distance = levenshtein(candidate, brand);

      return distance > 0 && distance <= allowedDistance;
    });
  });
}
