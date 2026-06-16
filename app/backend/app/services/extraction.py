from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
import unicodedata

from app.services.rules import get_ocr_rules, validate_title_for_collection


@dataclass(slots=True)
class ExtractionInput:
    collection_name: str
    ocr_text: str
    original_filename: str = ""
    created_at: datetime | None = None
    existing_title: str | None = None


@dataclass(slots=True)
class ExtractionResult:
    title: str
    sender: str | None = None
    recipient: str | None = None
    invoice_number: str | None = None
    date: str | None = None
    amount: str | None = None
    payment_method: str | None = None
    metadata: dict = field(default_factory=dict)


BAD_BELEGE_SUBSTRINGS = (
    "worldhealthorganization",
    "sauglinge",
    "impf",
    "masern",
    "rki",
    "who",
    "leaflet",
    "beipack",
    "kleinkinder",
    "erwachsene",
    "jugendliche",
    "therapie",
    "zuzahlung",
    "behandl",
    "ersatzkassen",
    "primarkassen",
    "pertussis",
    "poliomyelitis",
    "hepatitis",
    "mumps",
    "roteln",
    "varizellen",
    "windpocken",
    "tetanus",
    "diphtherie",
    "hilfs",
    "pneumokokken",
    "meningokokken",
    "standardimpfungen",
    "hausbesuch",
    "schlingentisch",
    "bandagierung",
    "bobath",
    "kgbobath",
    "microsoft",
    "fango",
    "shiptobill",
    "namevornameved",
    "fehlendegrundimmunisierungennach",
)

BAD_EXACT = {
    "dok",
    "document",
    "dokument",
    "scan",
    "scanner",
    "receipt",
    "beleg",
    "invoice",
    "rechnung",
    "page",
    "seiten",
    "unknown",
    "unbekannt",
    "untitled",
    "file",
    "img",
    "image",
    "pdf",
    "jpg",
    "jpeg",
    "png",
    "webp",
    "na",
    "none",
    "null",
    "sauglingeund",
    "worldhealthorganization",
    "microsoft",
    "bgm",
    "fango",
    "shiptobill",
    "namevornameved",
    "fehlendegrundimmunisierungennach",
    "kmt",
    "kg",
    "mt",
    "et",
    "est",
    "us",
    "rl",
    "hr",
    "kt",
    "mld",
}


def configured_bad_belege_substrings() -> tuple[str, ...]:
    configured = get_ocr_rules().get("belege_bad_sender_substrings", [])
    if not isinstance(configured, list):
        configured = []
    return tuple(dict.fromkeys([*BAD_BELEGE_SUBSTRINGS, *(str(item).lower() for item in configured)]))

NEUTRAL_INVOICE_COLLECTIONS = {"eingangsrechnung", "ausgangsrechnung"}

FINANCIAL_SIGNAL_RE = re.compile(
    r"\b("
    r"rechnung|rechnungs|invoice|beleg|quittung|receipt|"
    r"betrag|summe|total|steuer|ust|mwst|vat|tax|"
    r"iban|bic|konto|zahlung|payment|due|balance|"
    r"bestell|order|lieferung|delivery|kundennummer|customer"
    r")\b|€|eur\b|usd\b",
    re.IGNORECASE,
)


ORG_HINTS = (
    "bank",
    "gmbh",
    "mbh",
    "ag",
    "kg",
    "ug",
    "ev",
    "llc",
    "ltd",
    "inc",
    "corp",
    "apotheke",
    "praxis",
    "klinik",
    "hospital",
    "zentrum",
    "versicherung",
    "market",
    "shop",
    "store",
    "lidl",
    "aldi",
    "rewe",
    "edeka",
    "dm",
    "rossmann",
    "distributors",
)


def strip_accents(value: str) -> str:
    value = value or ""
    value = value.replace("ß", "ss")
    value = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def compact_party(value: str, max_len: int = 40) -> str:
    value = strip_accents(value)
    value = re.sub(r"\b(ges\.?\s*mbh|gesmbh|gmbh|mbh|ag|kg|ug|inc|ltd|llc|sarl|e\.?k\.?)\b", " ", value, flags=re.I)
    value = re.sub(r"[^A-Za-z0-9 ]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    parts = [part for part in value.split() if part]
    return "".join(parts[:3])[:max_len] or "Dok"


def compact_sender_token(value: str) -> str:
    value = strip_accents(value).replace("&", " And ")
    value = re.sub(r"[_/\\|]+", " ", value)
    value = re.sub(r"[^A-Za-z0-9 .,-]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    words = [word for word in value.split() if word]
    if not words:
        return ""

    def norm_word(word: str) -> str:
        if word.isupper() and len(word) <= 8:
            return word
        return word[:1].upper() + word[1:]

    token = "".join(norm_word(word) for word in words[:3])
    token = re.sub(r"[^A-Za-z0-9]+", "", token)
    return token[:32]


def looks_technical(value: str) -> bool:
    return bool(re.match(r"^(scan|img|image|photo|document|file|bankcheckocrinput\d*|ocrinput\d*)", value or "", re.I))


def has_financial_signal(text: str) -> bool:
    return bool(FINANCIAL_SIGNAL_RE.search(text or ""))


def neutral_title_base(text: str, original_filename: str = "") -> str:
    candidates: list[str] = []
    for raw in (text or "").splitlines()[:12]:
        line = re.sub(r"\s+", " ", raw.strip())
        if not line or len(line) < 4 or len(line) > 80:
            continue
        if has_financial_signal(line):
            continue
        if re.fullmatch(r"[0-9 ./:-]+", line):
            continue
        candidates.append(line)
    if original_filename:
        stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", original_filename).strip()
        stem = re.sub(r"[_-]+", " ", stem)
        if stem and not looks_technical(stem) and not has_financial_signal(stem):
            candidates.append(stem)
    for candidate in candidates:
        token = compact_sender_token(candidate)
        if token and token.lower() != "dok" and len(token) >= 4:
            return token
    return "Dok"


def is_neutral_invoice_file(text: str, *, invoice_number: str, amount: str) -> bool:
    if has_financial_signal(text):
        return False
    if invoice_number and invoice_number != "NA":
        return False
    if amount and amount != "NA":
        return False
    return neutral_title_base(text) != "Dok"


def neutral_invoice_result(payload: ExtractionInput, collection_name: str) -> ExtractionResult:
    title = neutral_title_base(payload.ocr_text, payload.original_filename)
    return ExtractionResult(
        title=title,
        metadata={
            "collection": collection_name,
            "title_schema_valid": True,
            "neutral_file": True,
            "document_kind": "neutral",
            "neutral_reason": "no_invoice_financial_signals",
        },
    )


def is_bad_belege_candidate(value: str) -> bool:
    token = compact_sender_token(value)
    low = token.lower()
    if not token or low in BAD_EXACT:
        return True
    if any(fragment in low for fragment in configured_bad_belege_substrings()):
        return True
    if len(token) <= 2:
        return True
    if len(token) <= 4 and token.isupper() and low not in {"acme"}:
        return True
    return bool(re.fullmatch(r"[0-9]+", token))


def looks_like_sender(value: str, *, strong: bool = False) -> bool:
    token = compact_sender_token(value)
    low = token.lower()
    if is_bad_belege_candidate(token):
        return False
    if not re.match(r"^[A-Za-z]", token):
        return False
    if low in {"acme"}:
        return True
    if len(token) > 20 and not any(hint in low for hint in ORG_HINTS) and not token.isupper():
        return False
    if any(hint in low for hint in ORG_HINTS):
        return True
    if re.search(r"[A-Z][a-z]+[A-Z][A-Za-z]+", token):
        return True
    if token.isupper() and 3 <= len(token) <= 8:
        return strong
    if re.fullmatch(r"[A-Z][A-Za-z0-9]{2,20}", token):
        return strong
    return strong and len(token) >= 5


def normalize_date(raw: str) -> str:
    iso_match = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", raw or "")
    if iso_match:
        year, month, day = iso_match.groups()
        return f"{int(day):02d}/{int(month):02d}/{int(year):04d}"
    match = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", raw or "")
    if not match:
        return ""
    day, month, year_raw = match.groups()
    year = int(year_raw)
    if year < 100:
        year = 2000 + year if year < 70 else 1900 + year
    return f"{int(day):02d}/{int(month):02d}/{year:04d}"


def normalize_month_year(raw: str, created_at: datetime | None = None) -> str:
    date = normalize_date(raw)
    if date:
        _, month, year = date.split("/")
        return f"{month}/{year[-2:]}"
    if created_at is not None:
        return f"{created_at.month:02d}/{created_at.year % 100:02d}"
    return "00/00"


def normalize_amount(raw: str) -> str:
    original = (raw or "").strip()
    value = re.sub(r"[^0-9,.\-]", "", original)
    if not value:
        return "NA"

    normalized: str | None = None
    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            normalized = value.replace(".", "").replace(",", ".")
        else:
            normalized = value.replace(",", "")
    elif "," in value:
        parts = value.split(",")
        if len(parts[-1]) == 2:
            normalized = value.replace(".", "").replace(",", ".")
        elif len(parts[-1]) == 3 and len(parts) == 2:
            normalized = value.replace(",", "")
        else:
            normalized = None
    elif "." in value:
        parts = value.split(".")
        if len(parts[-1]) == 3 and len(parts) == 2:
            normalized = value.replace(".", "")
        else:
            normalized = value
    else:
        normalized = value

    candidates = [normalized] if normalized else []
    last_sep = re.search(r"([.,])(\d{2})$", value)
    if last_sep:
        integer_part = re.sub(r"[^0-9]", "", value[: last_sep.start(1)])
        if integer_part:
            candidates.append(f"{integer_part}.{last_sep.group(2)}")

    for candidate in candidates:
        try:
            return f"{float(candidate):.2f}".replace(".", ",")
        except (TypeError, ValueError):
            continue
    return "NA"


def extract_invoice_number(text: str) -> str:
    patterns = [
        r"(?i)\bEingangsrechnung\s+([A-Z0-9][A-Z0-9./-]{2,})\b",
        r"(?i)\bRechnungs\s*nummer\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b",
        r"(?i)\bRechnungs\s*nr\.?\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b",
        r"(?i)\bRechnungs\s*-\s*Nr\.?\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b",
        r"(?i)\bRechnung\s*-\s*Nr\.?\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b",
        r"(?i)\bRechnung\s*Nr\.?\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b",
        r"(?i)\bInvoice\s*No\.?\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b",
        r"(?i)\bInvoice\s*Number\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b",
        r"(?i)\bBeleg(?:nr|nummer)\.?\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b",
    ]
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw.strip())
        low = line.lower()
        if any(
            bad in low
            for bad in (
                "kundennummer",
                "kunden-nr",
                "kunden nr",
                "customer",
                "auftrags",
                "bestell",
                "lieferant nr",
                "lieferant-nr",
                "vat id",
                "ust-id",
                "ustid",
                "iban",
                "telefon",
                "phone",
            )
        ):
            continue
        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                value = re.sub(r"[^A-Za-z0-9./-]+", "", match.group(1))
                if value and not _is_rejected_identifier(value):
                    return value[:40]
    return "NA"


def _is_rejected_identifier(value: str) -> bool:
    compact = re.sub(r"[^A-Za-z0-9]", "", value or "")
    if re.fullmatch(r"(?:DE)?\d{10,}", compact, flags=re.I):
        return True
    if re.fullmatch(r"[A-Z]{2}\d{12,}", compact, flags=re.I):
        return True
    digits = re.sub(r"\D", "", value or "")
    if len(digits) >= 10 and not re.search(r"[A-Za-z]", value or ""):
        return True
    return False


def extract_invoice_date(text: str, created_at: datetime | None = None) -> str:
    lines = [re.sub(r"\s+", " ", raw.strip()) for raw in text.splitlines() if raw.strip()]
    for line in lines:
        low = line.lower()
        if "rechnungsdatum" in low or "invoice date" in low:
            date = normalize_date(line)
            if date:
                return date
    for line in lines:
        low = line.lower()
        if "lieferdatum" in low or "leistungsdatum" in low or "valutadatum" in low:
            continue
        if re.search(r"\bdatum\b|\bdate\b", low):
            date = normalize_date(line)
            if date:
                return date
    if created_at is not None:
        return f"{created_at.day:02d}/{created_at.month:02d}/{created_at.year:04d}"
    return "00/00/0000"


def extract_invoice_amount(text: str) -> str:
    num_re = re.compile(r"(?<!\d)(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})|\d+[.,]\d{2}|\d+)(?!\d)")
    strong = ("endsumme", "gesamtsumme", "gesamtbetrag", "zu zahlen", "balance due", "invoice total", "grand total", "brutto")
    medium = ("summe", "gesamt", "total", "rechnungsbetrag")
    bad = ("netto", "mwst", "ust", "steuer", "skonto", "rabatt")
    candidates: list[tuple[int, float, str]] = []

    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw.strip())
        if not line:
            continue
        low = line.lower()
        numbers = num_re.findall(line)
        if not numbers:
            continue
        score = 0
        if any(cue in low for cue in strong):
            score += 4
        elif any(cue in low for cue in medium):
            score += 2
        if any(cue in low for cue in bad) and not any(cue in low for cue in strong):
            score -= 3
        amount = normalize_amount(numbers[-1])
        if amount == "NA":
            continue
        try:
            numeric = float(amount.replace(",", "."))
        except ValueError:
            numeric = 0.0
        if _looks_like_garbage_amount(numeric, amount):
            continue
        candidates.append((score, numeric, amount))

    if not candidates:
        return "NA"
    reliable = [candidate for candidate in candidates if candidate[0] >= 0]
    ranked = reliable or candidates
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return ranked[0][2]


def _looks_like_garbage_amount(numeric: float, amount: str) -> bool:
    rules = get_ocr_rules().get("amount_garbage", {})
    if not isinstance(rules, dict):
        rules = {}
    max_abs = float(rules.get("max_abs", 10_000_000))
    repeated_digit_min_length = int(rules.get("repeated_digit_min_length", 8))
    digits = re.sub(r"\D", "", amount)
    if numeric >= max_abs:
        return True
    return len(digits) >= repeated_digit_min_length and len(set(digits)) <= 2


def extract_payment_method(text: str) -> str:
    low = text.lower()
    if re.search(r"\b(bar|cash|barzahlung)\b", low):
        return "Bar"
    if re.search(r"\b(karte|ec|girocard|visa|mastercard|master card|amex|electronic cash|debit)\b", low):
        return "Karte"
    return "NA"


def extract_belege_sender(text: str, original_filename: str = "", existing_title: str | None = None) -> str:
    if existing_title:
        match = re.match(r"^([^_]+)_B_\d{2}/\d{2}_[^_]+_[^_]+$", existing_title.strip())
        candidate = match.group(1) if match else existing_title.strip()
        token = compact_sender_token(candidate)
        if token and looks_like_sender(candidate, strong=True):
            return token

    lines: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw.strip())
        if line:
            lines.append(line)
        if len(lines) >= 20:
            break

    if len(lines) >= 2:
        first, second = lines[0], lines[1]
        if re.fullmatch(r"[A-Z]{3,8}", first) and first.lower() not in BAD_EXACT:
            if re.fullmatch(r"[A-Z][A-Z ]{3,24}", second):
                return compact_sender_token(first)

    label_re = re.compile(
        r"(ship to|bill to|pay to|order of|name|vorname|surname|given name|"
        r"personalnummer|dienstbezeichnung|ausgestellt|issued to|wohnort|geburtsdatum|"
        r"passport|identity card|therapie|zuzahlung|behandl|standardimpfungen)",
        re.I,
    )
    info_re = re.compile(r"(rechnung|invoice|betrag|summe|gesamt|steuer|ust|iban|bic|konto|page|seite|date|datum)", re.I)

    for line in lines[:12]:
        if len(line) < 3 or len(line) > 60:
            continue
        if ":" in line or re.search(r"\d{2,}", line):
            continue
        if label_re.search(line) or info_re.search(line):
            continue
        words = re.findall(r"[A-Za-zÄÖÜäöüß]+", line)
        if not words or len(words) > 2:
            continue
        if len(words) == 2 and not all(word[:1].isupper() for word in words):
            continue
        token = compact_sender_token(line)
        if token and looks_like_sender(line, strong=False):
            return token

    if original_filename:
        stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", original_filename).strip()
        if not re.search(r"^(scan\d*|scan20\d\d|img\d*|image\d*|document\d*|untitled)", stem, re.I):
            if not re.search(r"(invoice|rechnung|receipt|beleg|masern|impf|therapie|zuzahl|name|vorname)", stem, re.I):
                words = re.findall(r"[A-Za-zÄÖÜäöüß]+", stem.replace("_", " ").replace("-", " "))
                if 0 < len(words) <= 2 and looks_like_sender(stem, strong=False):
                    return compact_sender_token(stem)
    return "Dok"


def extract_belege_amount(text: str) -> str:
    cues = ("summe", "gesamt", "total", "betrag", "balance due", "zu zahlen", "endbetrag", "invoice total", "rechnungsbetrag")
    num_re = re.compile(r"(?<!\d)(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})|\d+[.,]\d{2}|\d+)(?!\d)")
    candidates: list[tuple[int, str]] = []
    for line in text.splitlines():
        low = line.lower()
        score = 0
        if any(cue in low for cue in cues):
            score += 2
        if "eur" in low or "€" in line or "$" in line:
            score += 1
        for number in num_re.findall(line):
            candidates.append((score, number))
    if not candidates:
        return "NA"
    candidates.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
    if candidates[0][0] < 2:
        return "NA"
    return normalize_amount(candidates[0][1])


def extract_eingangsrechnung_sender(text: str, original_filename: str = "", existing_title: str | None = None) -> str:
    if existing_title:
        match = re.match(r"^([^_]+)_[^_]+_\d{2}/\d{2}/\d{4}_[^_]+$", existing_title.strip())
        if match and match.group(1).lower() != "dok":
            return match.group(1)

    bad_fragments = (
        "firma",
        "kunde",
        "kundennummer",
        "lieferant",
        "sachbearbeiter",
        "bitte",
        "rechnung",
        "eingangsrechnung",
        "invoice",
        "seite",
        "datum",
        "auftrag",
        "artikel",
        "menge",
        "summe",
        "telefon",
        "phone",
        "fax",
        "mail",
        "www",
        "bearbeiter",
        "kommission",
        "bestell",
        "lieferdatum",
    )
    street_re = re.compile(r"\b(strasse|straße|str\.?|weg|gasse|allee|platz|ufer|ring)\b", re.I)
    lines = [re.sub(r"\s+", " ", raw.strip()) for raw in text.splitlines() if raw.strip()][:18]
    for line in lines:
        low = line.lower()
        if any(fragment in low for fragment in bad_fragments):
            continue
        candidate = re.split(r"\b(phone|telefon|fax|mail|www)\b", line, maxsplit=1, flags=re.I)[0].strip()
        street = street_re.search(candidate)
        if street:
            candidate = candidate[: street.start()].strip()
        postal = re.search(r"\b\d{4,5}\b", candidate)
        if postal:
            candidate = candidate[: postal.start()].strip()
        words = re.findall(r"[A-Za-zÄÖÜäöüß.\-]+", candidate)
        if not words:
            continue
        sender = compact_party(" ".join(words))
        if sender.lower() != "dok" and len(sender) >= 3 and not looks_technical(sender):
            return sender

    if original_filename:
        stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", original_filename)
        if not looks_technical(stem) and not re.search(r"(invoice|rechnung|eingangsrechnung|scan|img|image|document|file)", stem, re.I):
            sender = compact_party(stem)
            if sender.lower() != "dok":
                return sender
    return "Dok"


def extract_ausgangsrechnung_recipient(text: str) -> str:
    lines = [re.sub(r"\s+", " ", raw.strip()) for raw in text.splitlines() if raw.strip()]
    if not lines:
        return "Dok"
    meta_re = re.compile(
        r"\b(rechnung|rechnungs|invoice|datum|date|kunden-?nr|kundennummer|bestell-?nr|"
        r"auftrags-?nr|telefon|phone|fax|mail|www|bearbeiter|komission|kommission|"
        r"lieferdatum|lieferbedingung|summe|ust|mwst|endsumme|iban|bic|konto|pos\.)",
        re.I,
    )
    street_re = re.compile(r"\b(strasse|straße|str\.?|weg|gasse|allee|platz|ufer|ring)\b", re.I)
    city_re = re.compile(r"^\d{4,5}\s+[A-Za-zÄÖÜäöüß]", re.I)
    phone_mail_re = re.compile(r"(@|www\.|\+\d|\btelefon\b|\bphone\b|\bfax\b|\bmail\b)", re.I)

    def is_name_line(line: str) -> bool:
        if meta_re.search(line) or phone_mail_re.search(line) or city_re.search(line):
            return False
        if street_re.search(line):
            return False
        if re.search(r"\d", line):
            return False
        if re.search(r"\d{4,}", line):
            return False
        words = re.findall(r"[A-Za-zÄÖÜäöüß.\-&]+", line)
        if not words or len(words) > 6:
            return False
        candidate = compact_party(line)
        return candidate != "Dok" and len(candidate) >= 3

    top: list[str] = []
    for line in lines[:25]:
        if meta_re.search(line) and not re.search(r"\b(gmbh|ag|kg|ug|co\.?)\b", line, re.I):
            break
        top.append(line)
    parties: list[str] = []
    seen: set[str] = set()
    for idx, line in enumerate(top):
        if not is_name_line(line):
            continue
        has_address = False
        for next_line in top[idx + 1 : idx + 4]:
            if phone_mail_re.search(next_line):
                continue
            if street_re.search(next_line) or city_re.search(next_line) or re.search(r"\b\d{4,5}\b", next_line):
                has_address = True
                break
        if has_address:
            candidate = compact_party(line)
            if candidate not in seen:
                seen.add(candidate)
                parties.append(candidate)
    if len(parties) >= 2:
        return parties[1]
    if len(parties) == 1:
        return parties[0]

    clean: list[str] = []
    seen.clear()
    for line in top:
        if is_name_line(line):
            candidate = compact_party(line)
            if candidate not in seen:
                seen.add(candidate)
                clean.append(candidate)
    if len(clean) >= 2:
        return clean[1]
    if len(clean) == 1:
        return clean[0]
    return "Dok"


def extract_belege_title(payload: ExtractionInput) -> ExtractionResult:
    sender = extract_belege_sender(payload.ocr_text, payload.original_filename, payload.existing_title)
    date = normalize_month_year(payload.ocr_text, payload.created_at)
    amount = extract_belege_amount(payload.ocr_text)
    payment = extract_payment_method(payload.ocr_text)
    title = f"{sender}_B_{date}_{amount}_{payment}"
    valid = validate_title_for_collection("Belege", title)
    return ExtractionResult(
        title=title,
        sender=sender,
        date=date,
        amount=amount,
        payment_method=payment,
        metadata={"collection": "Belege", "title_schema_valid": valid},
    )


def extract_eingangsrechnung_title(payload: ExtractionInput) -> ExtractionResult:
    sender = extract_eingangsrechnung_sender(payload.ocr_text, payload.original_filename, payload.existing_title)
    invoice_number = extract_invoice_number(payload.ocr_text)
    amount = extract_invoice_amount(payload.ocr_text)
    if is_neutral_invoice_file(payload.ocr_text, invoice_number=invoice_number, amount=amount):
        return neutral_invoice_result(payload, "Eingangsrechnung")
    date = extract_invoice_date(payload.ocr_text, payload.created_at)
    title = f"{sender}_{invoice_number}_{date}_{amount}"
    valid = validate_title_for_collection("Eingangsrechnung", title)
    return ExtractionResult(
        title=title,
        sender=sender,
        invoice_number=invoice_number,
        date=date,
        amount=amount,
        metadata={"collection": "Eingangsrechnung", "title_schema_valid": valid},
    )


def extract_ausgangsrechnung_title(payload: ExtractionInput) -> ExtractionResult:
    recipient = extract_ausgangsrechnung_recipient(payload.ocr_text)
    invoice_number = extract_invoice_number(payload.ocr_text)
    amount = extract_invoice_amount(payload.ocr_text)
    if is_neutral_invoice_file(payload.ocr_text, invoice_number=invoice_number, amount=amount):
        return neutral_invoice_result(payload, "Ausgangsrechnung")
    date = extract_invoice_date(payload.ocr_text, payload.created_at)
    title = f"{recipient}_{invoice_number}_{date}_{amount}"
    valid = validate_title_for_collection("Ausgangsrechnung", title)
    return ExtractionResult(
        title=title,
        recipient=recipient,
        invoice_number=invoice_number,
        date=date,
        amount=amount,
        metadata={"collection": "Ausgangsrechnung", "title_schema_valid": valid},
    )


def extract_metadata(payload: ExtractionInput) -> ExtractionResult:
    collection = payload.collection_name.strip().lower()
    if collection == "belege":
        return extract_belege_title(payload)
    if collection == "eingangsrechnung":
        return extract_eingangsrechnung_title(payload)
    if collection == "ausgangsrechnung":
        return extract_ausgangsrechnung_title(payload)
    return ExtractionResult(title=payload.original_filename or "Dok", metadata={"collection": payload.collection_name})


def sanitize_shared_title_base(value: str | None) -> str:
    if not value:
        return ""
    raw = value.strip()
    if not re.search(r"[A-Za-z0-9]", raw):
        return ""
    return compact_party(raw)


def replace_title_base(collection_name: str, title: str | None, shared_base: str | None) -> str:
    base = sanitize_shared_title_base(shared_base)
    if not base:
        return title or ""
    current = title or ""
    collection = collection_name.strip().lower()
    if collection == "belege":
        match = re.match(r"^[^_]+(_B_.+)$", current)
        suffix = match.group(1) if match else "_B_00/00_NA_NA"
        return f"{base}{suffix}"
    if collection in {"eingangsrechnung", "ausgangsrechnung"}:
        parts = current.split("_")
        if len(parts) >= 4:
            parts[0] = base
            return "_".join(parts)
        return f"{base}_NA_00/00/0000_NA"
    return current


def apply_shared_title_to_result(
    collection_name: str,
    result: ExtractionResult,
    shared_base: str | None,
) -> ExtractionResult:
    title = replace_title_base(collection_name, result.title, shared_base)
    if title == result.title:
        return result
    metadata = {
        **(result.metadata or {}),
        "shared_title_base": sanitize_shared_title_base(shared_base),
        "shared_title_applied": True,
    }
    return ExtractionResult(
        title=title,
        sender=result.sender,
        recipient=result.recipient,
        invoice_number=result.invoice_number,
        date=result.date,
        amount=result.amount,
        payment_method=result.payment_method,
        metadata=metadata,
    )


def generate_title_for_collection(payload: ExtractionInput) -> ExtractionResult:
    return extract_metadata(payload)
