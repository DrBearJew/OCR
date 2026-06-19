import html
import json
import logging
import os
import re
import requests
import threading
import time
from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

LLAMA_URL = os.getenv("LLAMA_URL", "http://172.18.0.1:1234/v1")
LLAMA_ADMIN = os.getenv("LLAMA_ADMIN", "http://172.18.0.1:1234")

IDLE_UNLOAD_SECONDS = int(os.getenv("IDLE_UNLOAD_SECONDS", "180"))
UNLOAD_AFTER_REQUEST = os.getenv("UNLOAD_AFTER_REQUEST", "1").strip().lower() not in {"0", "false", "no"}

last_request_time = time.time()
last_models_used = set()
active_requests = 0
state_lock = threading.Lock()

TITLE_RULES_PATH = os.getenv("TITLE_RULES_PATH", "/app/title_rules.json")
_title_rules_cache = {
    "mtime": None,
    "data": {},
}


def is_ocr_model(model_name: str) -> bool:
    return (model_name or "").lower().strip() in {"glm-ocr", "zai-org/glm-ocr", "paddleocr-vl", "paddleocr-vl-1.6"}


def strip_wrappers_keep_structure(text: str) -> str:
    if not text:
        return ""

    text = str(text).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"<(think|thinking|content|reasoning)>\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*</(think|thinking|content|reasoning)>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```[a-zA-Z0-9_-]*\s*\n", "", text)
    text = re.sub(r"\n```$", "", text)
    text = text.replace("`", "")

    lines = [re.sub(r"[ \t]+$", "", line) for line in text.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    return "\n".join(lines).strip()


def clean_cell_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def html_table_to_markdown(table_html: str) -> str:
    """Convert simple HTML tables to Markdown without flattening columns."""
    if not table_html:
        return ""

    rows = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", table_html, flags=re.IGNORECASE | re.DOTALL):
        cells = re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row, flags=re.IGNORECASE | re.DOTALL)
        if cells:
            rows.append([clean_cell_text(cell).replace("|", "\\|") for cell in cells])

    if not rows:
        fallback = table_html
        fallback = re.sub(r"</tr\s*>", "\n", fallback, flags=re.IGNORECASE)
        fallback = re.sub(r"</t[dh]\s*>", " | ", fallback, flags=re.IGNORECASE)
        fallback = re.sub(r"<[^>]+>", " ", fallback)
        fallback = html.unescape(fallback)
        fallback = re.sub(r"[ \t]+", " ", fallback)
        fallback = re.sub(r"\n{2,}", "\n", fallback)
        return fallback.strip(" \n")

    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    header = padded[0]
    body = padded[1:]
    rendered = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * width) + " |"]
    rendered.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(rendered)


def normalize_markdown_line(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    if stripped.startswith("|") and stripped.endswith("|"):
        return re.sub(r"[ \t]+", " ", stripped)
    if re.match(r"^#{1,6}\s", stripped):
        return re.sub(r"[ \t]+", " ", stripped)
    if re.match(r"^([-*+] |\d+[.)] )", stripped):
        return re.sub(r"[ \t]+", " ", stripped)
    return re.sub(r"[ \t]+", " ", stripped)


def normalize_ocr_output_for_paperless(text: str) -> str:
    """Preserve Markdown OCR structure while removing wrappers/HTML noise.

    The OCR text is stored and displayed by the app, so flattening all structure
    makes document pages unreadable. Keep Markdown headings, bullets, blank lines,
    and table pipes; only normalize HTML and excessive whitespace.
    """
    if not text:
        return ""

    text = strip_wrappers_keep_structure(text)
    text = html.unescape(text)

    def replace_table(match):
        table_text = html_table_to_markdown(match.group(0))
        return f"\n\n{table_text}\n\n" if table_text else "\n\n"

    text = re.sub(
        r"<table\b[^>]*>.*?</table>",
        replace_table,
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    for level in range(6, 0, -1):
        text = re.sub(
            rf"<h{level}\b[^>]*>(.*?)</h{level}>",
            lambda match, level=level: "\n\n" + ("#" * level) + " " + clean_cell_text(match.group(1)) + "\n\n",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )

    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(p|div|section|article|header|footer|ul|ol)>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li\b[^>]*>", "\n- ", text, flags=re.IGNORECASE)
    text = re.sub(r"</li\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)

    lines = [normalize_markdown_line(line) for line in text.split("\n")]
    result_lines = []
    blank = False
    for line in lines:
        if not line:
            if result_lines and not blank:
                result_lines.append("")
            blank = True
            continue
        result_lines.append(line)
        blank = False

    result = "\n".join(result_lines).strip()
    max_ocr = int(os.getenv("MAX_OCR_CHARS", "24000"))
    if len(result) > max_ocr:
        result = result[:max_ocr].rstrip()
    return result


def sanitize_for_paperless_field(text: str) -> str:
    if not text:
        return ""

    text = strip_wrappers_keep_structure(text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
    lines = [line for line in lines if line]

    if not lines:
        return ""

    clean = lines[0]
    clean = re.sub(
        r"^(correspondent|title|tags?|date|created[_ ]date|document type|document_type)\s*[:\-]\s*",
        "",
        clean,
        flags=re.IGNORECASE,
    )
    clean = re.sub(r"<[^>]+>", "", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:128].strip()


def is_structured_metadata_request(messages) -> bool:
    if not isinstance(messages, list):
        return False
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str) and (
            "You are Qwen Metadata" in content
            or "secondbrain" in content.lower()
            or "Deterministic metadata" in content
            or "Return valid JSON" in content
        ):
            return True
    return False


def looks_like_structured_output(text: str) -> bool:
    stripped = strip_wrappers_keep_structure(text).lstrip()
    return stripped.startswith("{") or stripped.startswith("[")


def extract_text_from_choice(choice: dict) -> str:
    if not isinstance(choice, dict):
        return ""

    msg = choice.get("message", {})
    if not isinstance(msg, dict):
        msg = {}

    content = msg.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()

    if isinstance(content, list):
        parts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif item.get("type") == "output_text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
        joined = "\n".join(p.strip() for p in parts if p and p.strip()).strip()
        if joined:
            return joined

    for key in (
        "thinking_content",
        "reasoning_content",
        "thinking",
        "reasoning",
        "output_text",
        "text",
    ):
        value = msg.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    for key in (
        "thinking_content",
        "reasoning_content",
        "thinking",
        "reasoning",
        "output_text",
        "text",
    ):
        value = choice.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return ""


def extract_tagged_block(text: str, tag: str) -> str:
    if not text:
        return ""

    m = re.search(
        rf"<{re.escape(tag)}>\s*(.*?)\s*</{re.escape(tag)}>",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return m.group(1).strip() if m else ""



def load_title_rules() -> dict:
    global _title_rules_cache

    try:
        st = os.stat(TITLE_RULES_PATH)
        mtime = st.st_mtime
    except FileNotFoundError:
        return {}
    except Exception as e:
        logging.warning(f"title rules stat failed: {e}")
        return {}

    if _title_rules_cache["mtime"] == mtime:
        return _title_rules_cache["data"]

    try:
        with open(TITLE_RULES_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            logging.warning("title rules file is not a JSON object; ignoring")
            data = {}
        _title_rules_cache = {
            "mtime": mtime,
            "data": data,
        }
        logging.info(f"Loaded title rules from {TITLE_RULES_PATH}")
        return data
    except Exception as e:
        logging.warning(f"Failed to load title rules: {e}")
        return {}


def extract_title_prompt_context(prompt_text: str) -> dict:
    return {
        "schema_key": extract_tagged_block(prompt_text, "schema_key"),
        "collection": extract_tagged_block(prompt_text, "collection"),
        "document_type": extract_tagged_block(prompt_text, "document_type"),
        "correspondent": extract_tagged_block(prompt_text, "correspondent"),
        "original_title": extract_tagged_block(prompt_text, "original_title"),
        "document_text": extract_tagged_block(prompt_text, "content"),
    }


def _lookup_rule_case_insensitive(rules: dict, key: str):
    if not key or not isinstance(rules, dict):
        return None

    if key in rules and isinstance(rules[key], dict):
        return rules[key]

    key_lower = key.lower().strip()
    for k, v in rules.items():
        if isinstance(k, str) and isinstance(v, dict) and k.lower().strip() == key_lower:
            return v

    return None


def resolve_title_rule(ctx: dict) -> dict:
    cfg = load_title_rules()
    rules = cfg.get("rules", {})
    if not isinstance(rules, dict):
        rules = {}

    for field in ("schema_key", "collection", "document_type"):
        value = (ctx.get(field) or "").strip()
        rule = _lookup_rule_case_insensitive(rules, value)
        if rule:
            out = dict(rule)
            out["_matched_on"] = field
            out["_matched_value"] = value
            return out

    default_rule = cfg.get("default", {})
    if isinstance(default_rule, dict):
        out = dict(default_rule)
        out["_matched_on"] = "default"
        out["_matched_value"] = "default"
        return out

    return {
        "_matched_on": "default",
        "_matched_value": "default",
    }


def build_title_prompt_from_rule(ctx: dict, rule: dict) -> str:
    max_length = 90
    try:
        max_length = int(rule.get("max_length", 90))
    except Exception:
        max_length = 90

    instructions = rule.get("instructions", [])
    if not isinstance(instructions, list):
        instructions = []

    examples = rule.get("examples", [])
    if not isinstance(examples, list):
        examples = []

    fmt = str(rule.get("format", "") or "").strip()

    lines = [
        "Create a short Paperless-ngx title for this document.",
        "Output title only.",
        "No explanation.",
        f"Keep under {max_length} characters."
    ]

    if fmt:
        lines.append(f"Target schema: {fmt}")

    if instructions:
        lines.append("Rules:")
        for item in instructions:
            item = str(item or "").strip()
            if item:
                lines.append(f"- {item}")

    if examples:
        lines.append("Examples:")
        for item in examples:
            item = str(item or "").strip()
            if item:
                lines.append(f"- {item}")

    context_lines = []
    for label, key in (
        ("Schema key", "schema_key"),
        ("Collection", "collection"),
        ("Document type", "document_type"),
        ("Correspondent", "correspondent"),
        ("Original title", "original_title"),
    ):
        value = str(ctx.get(key, "") or "").strip()
        if value:
            context_lines.append(f"{label}: {value}")

    if context_lines:
        lines.append("")
        lines.append("Context:")
        lines.extend(context_lines)

    lines.append("")
    lines.append("Document text:")
    lines.append(str(ctx.get("document_text", "") or "").strip())

    return "\n".join(lines)


def is_title_prompt(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    return (
        "find a suitable document title" in t
        and "respond only with the title" in t
        and "<content>" in t
    )


def build_strict_title_prompt(document_text: str, original_title: str = "") -> str:
    return (
        "Create a short Paperless-ngx title for this document.\n"
        "Rules:\n"
        "- Output title only.\n"
        "- No explanation.\n"
        "- Prefer format: <sender> <document type> <document number>.\n"
        "- For invoices and bills, include the document number if present.\n"
        "- Do not include full addresses unless absolutely necessary.\n"
        "- Keep under 90 characters.\n"
        "- If sender is present, use it.\n"
        "- If document number is present, use it.\n\n"
        f"Original title:\n{original_title}\n\n"
        f"Document text:\n{document_text}"
    )


def normalize_invoice_title(title: str, source_text: str) -> str:
    title = sanitize_for_paperless_field(title)
    source = source_text or ""

    sender = ""
    doc_no = ""
    doc_date = ""

    m_sender = re.search(
        r"^\s*([A-ZÄÖÜ][A-ZÄÖÜ0-9&.,' \-]{2,})\s*$",
        source,
        flags=re.MULTILINE,
    )
    if m_sender:
        candidate = re.sub(r"\s+", " ", m_sender.group(1)).strip()
        if any(ch.isalpha() for ch in candidate):
            sender = candidate

    if not sender:
        m_sender2 = re.search(r"\b([A-ZÄÖÜ][A-ZÄÖÜ0-9&.,' \-]{2,})\b", source)
        if m_sender2:
            sender = re.sub(r"\s+", " ", m_sender2.group(1)).strip()

    m_no = re.search(
        r"\b(?:INVOICE|RECHNUNG)\s*(?:NO\.?|NR\.?|NUMMER)?\s*[:#]?\s*([A-Z0-9\-]+)",
        source,
        flags=re.IGNORECASE,
    )
    if m_no:
        doc_no = m_no.group(1).strip()

    m_date = re.search(
        r"\b(?:INVOICE DATE|RECHNUNGSDATUM)\b[^0-9]*([0-9]{2}-[0-9]{2}-[0-9]{2})",
        source,
        flags=re.IGNORECASE,
    )
    if m_date:
        yy, mm, dd = m_date.group(1).split("-")
        try:
            doc_date = f"20{yy}-{mm}-{dd}"
        except Exception:
            doc_date = ""

    if sender and doc_no:
        out = f"{sender} Rechnung {doc_no}"
        if doc_date:
            out = f"{out} {doc_date}"
        return out[:128]

    if doc_no:
        return f"Rechnung {doc_no}"[:128]

    return title[:128]


def maybe_rewrite_qwen_messages(data: dict):
    ctx = {
        "rewritten_title_prompt": False,
        "title_rule_match": "",
    }

    messages = data.get("messages", [])
    if not isinstance(messages, list) or not messages:
        return data, ctx

    first = messages[0]
    if not isinstance(first, dict):
        return data, ctx

    content = first.get("content")
    if not isinstance(content, str):
        return data, ctx

    if is_title_prompt(content):
        title_ctx = extract_title_prompt_context(content)
        title_rule = resolve_title_rule(title_ctx)

        data["messages"] = [
            {
                "role": "user",
                "content": build_title_prompt_from_rule(title_ctx, title_rule),
            }
        ]
        data["temperature"] = 0.0
        data["top_p"] = 0.9
        data["max_tokens"] = 64

        ctx["rewritten_title_prompt"] = True
        ctx["title_rule_match"] = str(title_rule.get("_matched_value", "default"))

        logging.info(
            "Title prompt rewritten using rule matched on %s=%s",
            title_rule.get("_matched_on", "default"),
            title_rule.get("_matched_value", "default"),
        )

    return data, ctx



def safeStr(value):
    if value is None:
        return ""
    return str(value)


def normalize_title_token(value: str) -> str:
    value = safeStr(value)
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = value.replace("/", "-")
    value = re.sub(r"[^0-9A-Za-zÄÖÜäöüß&+.,\- ]+", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def extract_sender_name(text: str, fallback: str = "") -> str:
    candidates = []

    if fallback:
        candidates.append(fallback)

    lines = [re.sub(r"\s+", " ", line).strip() for line in safeStr(text).splitlines()]
    for line in lines[:20]:
        if not line:
            continue
        if len(line) > 60:
            continue
        low = line.lower()
        if low.startswith(("datum", "date", "summe", "betrag", "total", "bar", "karte", "ec", "visa", "mastercard")):
            continue
        if re.search(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", line):
            continue
        if re.search(r"\d+,\d{2}", line):
            continue
        if any(ch.isalpha() for ch in line):
            candidates.append(line)

    for candidate in candidates:
        candidate = normalize_title_token(candidate)
        if candidate:
            return candidate[:32]

    return ""


def extract_mm_yy(text: str) -> str:
    text = safeStr(text)

    m = re.search(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\b", text)
    if m:
        day, month, year = m.groups()
        day = int(day)
        month = int(month)
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{month:02d}/{year[-2:]}"

    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if m:
        year, month, _day = m.groups()
        return f"{month}/{year[-2:]}"

    m = re.search(r"\b(\d{1,2})[./-](\d{2,4})\b", text)
    if m:
        month, year = m.groups()
        month_i = int(month)
        if 1 <= month_i <= 12:
            return f"{month_i:02d}/{year[-2:]}"

    return ""


def extract_amount_de(text: str) -> str:
    text = safeStr(text)

    patterns = [
        r"\b(?:summe|betrag|gesamt|total)\b[^0-9\-]*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})",
        r"([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})\s*(?:EUR|€)\b",
        r"\b([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+,[0-9]{2})\b",
    ]

    for pattern in patterns:
        hits = re.findall(pattern, text, flags=re.IGNORECASE)
        if hits:
            value = hits[-1]
            value = value.replace(".", "")
            return value

    return ""


def extract_payment_method(text: str) -> str:
    low = safeStr(text).lower()

    if re.search(r"\b(bar|barzahlung|cash)\b", low):
        return "Bar"

    if re.search(r"\b(karte|kartenzahlung|ec|girocard|mastercard|visa|maestro|debit|credit)\b", low):
        return "Karte"

    return ""


def format_belege_title(model_title: str, ctx: dict) -> str:
    source_text = safeStr(ctx.get("document_text", ""))
    original_title = safeStr(ctx.get("original_title", ""))
    correspondent = safeStr(ctx.get("correspondent", ""))

    combined = "\n".join([source_text, original_title, model_title]).strip()

    sender = extract_sender_name(source_text, fallback=correspondent)
    mm_yy = extract_mm_yy(combined)
    amount = extract_amount_de(combined)
    payment = extract_payment_method(combined)

    if not sender:
        sender = extract_sender_name(model_title)

    if not (sender and mm_yy and amount and payment):
        return sanitize_for_paperless_field(model_title)[:90]

    return f"{sender}_B_{mm_yy}_{amount}_{payment}"[:90]


def apply_title_rule_postprocessing(raw_title: str, original_prompt: str) -> str:
    final_title = sanitize_for_paperless_field(raw_title)

    if not original_prompt or not is_title_prompt(original_prompt):
        return final_title

    ctx = extract_title_prompt_context(original_prompt)
    rule = resolve_title_rule(ctx)
    matched = safeStr(rule.get("_matched_value", ""))

    if matched.lower() == "belege":
        return format_belege_title(final_title, ctx)

    max_length = 90
    try:
        max_length = int(rule.get("max_length", 90))
    except Exception:
        max_length = 90

    return final_title[:max_length]



def model_status(model_name: str) -> str | None:
    try:
        resp = requests.get(f"{LLAMA_ADMIN}/models", timeout=5)
        if resp.status_code >= 300:
            return None
        for item in (resp.json().get("data") or []):
            if item.get("id") == model_name or model_name in (item.get("aliases") or []):
                status = item.get("status") or {}
                return status.get("value")
    except Exception as e:
        logging.warning(f"Model status check failed for '{model_name}': {e}")
    return None


def wait_model_unloaded(model_name: str, timeout_seconds: float = 20.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        status = model_status(model_name)
        if status == "unloaded":
            logging.info(f"Model '{model_name}' confirmed unloaded")
            return True
        time.sleep(0.5)
    logging.warning(f"Timed out waiting for model '{model_name}' to unload; last_status={model_status(model_name)}")
    return False


def unload_model(model_name: str, *, wait: bool = True) -> bool:
    model_name = (model_name or "").strip()
    if not model_name or model_name == "unknown":
        return False

    try:
        resp = requests.post(
            f"{LLAMA_ADMIN}/models/unload",
            json={"model": model_name},
            timeout=10,
        )

        if 200 <= resp.status_code < 300:
            logging.info(f"Unload requested for model '{model_name}' via /models/unload")
            return wait_model_unloaded(model_name) if wait else True

        if resp.status_code == 400 and "not running" in resp.text.lower():
            logging.info(f"Model '{model_name}' was already not running")
            return wait_model_unloaded(model_name) if wait else True

        logging.info(f"Unload attempt for '{model_name}' returned {resp.status_code}: {resp.text[:300]}")
    except Exception as e:
        logging.warning(f"Unload attempt failed for '{model_name}': {e}")

    return False


def idle_unload_worker():
    global last_request_time, last_models_used, active_requests

    while True:
        time.sleep(15)

        with state_lock:
            idle_for = time.time() - last_request_time
            in_flight = active_requests
            models_to_unload = list(last_models_used) if in_flight == 0 and idle_for >= IDLE_UNLOAD_SECONDS else []

        if in_flight:
            logging.info(f"Idle unload skipped; {in_flight} request(s) still active")
            continue

        if not models_to_unload:
            continue

        logging.info(f"Idle timeout reached ({idle_for:.0f}s). Attempting unload of: {models_to_unload}")

        unloaded_any = False
        for model in models_to_unload:
            if unload_model(model):
                unloaded_any = True

        if unloaded_any:
            with state_lock:
                last_models_used.clear()


@app.route("/v1/models", methods=["GET"])
def proxy_models():
    try:
        resp = requests.get(f"{LLAMA_ADMIN}/models", timeout=30)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        logging.error(f"/v1/models proxy error: {e}")
        return jsonify({"error": str(e)}), 503


@app.route("/models/unload", methods=["POST"])
@app.route("/v1/unload", methods=["POST"])
@app.route("/unload", methods=["POST"])
def proxy_unload_model():
    payload = request.get_json(silent=True) or {}
    model_name = str(payload.get("model") or payload.get("model_id") or "").strip()
    if not model_name:
        return jsonify({"success": False, "error": "model is required"}), 400
    ok = unload_model(model_name)
    return jsonify({"success": ok, "model": model_name}), 200 if ok else 502


@app.route("/v1/chat/completions", methods=["POST"])
def smart_router():
    global last_request_time, last_models_used, active_requests

    requested_model = "unknown"
    with state_lock:
        active_requests += 1
        last_request_time = time.time()

    try:
        data = request.get_json(force=True) or {}
        requested_model = str(data.get("model", "qwen3.5-2b")).lower()

        with state_lock:
            last_request_time = time.time()
            last_models_used.add(requested_model)

        logging.info(f"Incoming requested model: {requested_model}")

        messages = data.get("messages", [])
        if isinstance(messages, list):
            for i, msg in enumerate(messages):
                role = msg.get("role")
                content = msg.get("content")
                logging.info(f"message[{i}] role={role} content_type={type(content).__name__}")
                logging.info(f"message[{i}] preview={repr(content)[:500]}")

        rewrite_ctx = {
            "rewritten_title_prompt": False,
            "original_source_text": "",
        }

        data["chat_template_kwargs"] = {"enable_thinking": False}

        if is_ocr_model(requested_model):
            logging.info(f"GLM OCR routing to server: {requested_model}")
            # OCR should be deterministic. Non-zero temperature caused PaddleOCR-VL
            # to drift into repeated diagram/chart labels on dense screenshots.
            data["temperature"] = 0.0
            data["max_tokens"] = max(int(data.get("max_tokens", 4000)), 1000)
            data["repeat_penalty"] = max(float(data.get("repeat_penalty", 1.0)), 1.18)
            data["repeat_last_n"] = max(int(data.get("repeat_last_n", 0)), 512)
            data.pop("stop", None)
            data.pop("reasoning_budget", None)
        else:
            logging.info(f"Qwen metadata routing to server: {requested_model}")
            data["temperature"] = 0.1
            data["top_p"] = 0.8
            # Qwen metadata responses are compact JSON. Keep CPU-only inference
            # bounded; large output limits caused long-running requests to outlive
            # the caller and accumulate in llama.cpp.
            data["max_tokens"] = min(int(data.get("max_tokens", 1024)), 1024)
            data["stop"] = ["```"]

            data, rewrite_ctx = maybe_rewrite_qwen_messages(data)

        upstream_timeout = min(float(data.get("timeout", 300) or 300), float(os.getenv("LLAMA_UPSTREAM_TIMEOUT_SECONDS", "300")))
        resp = requests.post(
            f"{LLAMA_URL}/chat/completions",
            json=data,
            timeout=upstream_timeout,
        )

        logging.info(f"Upstream status: {resp.status_code}")

        try:
            result = resp.json()
        except Exception:
            logging.error("Upstream returned non-JSON response")
            return resp.text, resp.status_code

        if "choices" in result and result["choices"]:
            choice = result["choices"][0]
            msg = choice.get("message", {})

            if not isinstance(msg, dict):
                msg = {}
                result["choices"][0]["message"] = msg

            raw_text = extract_text_from_choice(choice)
            logging.info(f"RAW MODEL OUTPUT (first 800 chars): {repr(str(raw_text)[:800])}")

            if is_ocr_model(requested_model):
                normalized_ocr = normalize_ocr_output_for_paperless(raw_text)
                logging.info(f"OCR OUTPUT LENGTH: {len(normalized_ocr)}")
                logging.info(f"OCR extracted preview: {repr(normalized_ocr[:300])}")
                result["choices"][0]["message"]["content"] = normalized_ocr
            else:
                if is_structured_metadata_request(messages) or looks_like_structured_output(raw_text):
                    final_content = strip_wrappers_keep_structure(raw_text).strip()
                else:
                    final_content = sanitize_for_paperless_field(raw_text)

                original_title_prompt = ""
                try:
                    if isinstance(messages, list) and messages and isinstance(messages[0], dict):
                        first_content = messages[0].get("content")
                        if isinstance(first_content, str) and is_title_prompt(first_content):
                            original_title_prompt = first_content
                except Exception:
                    original_title_prompt = ""

                if original_title_prompt:
                    final_content = apply_title_rule_postprocessing(final_content, original_title_prompt)
                elif rewrite_ctx.get("rewritten_title_prompt"):
                    final_content = normalize_invoice_title(
                        final_content,
                        rewrite_ctx.get("original_source_text", ""),
                    )

                logging.info(f"Metadata cleaned output: {final_content!r}")
                result["choices"][0]["message"]["content"] = final_content

        return jsonify(result), resp.status_code

    except Exception as e:
        logging.error(f"Proxy Error: {e}")
        return jsonify({"error": f"Proxy failure: {str(e)}"}), 503
    finally:
        with state_lock:
            active_requests = max(0, active_requests - 1)
            last_request_time = time.time()
            remaining = active_requests
        logging.info(f"Request finished for model: {requested_model}; active_requests={remaining}")
        # Metadata/Qwen requests can be unloaded as soon as the response is done.
        # OCR models are unloaded by the backend after the full document/page job,
        # not by the proxy after an individual page or batch chunk.
        if UNLOAD_AFTER_REQUEST and remaining == 0 and not is_ocr_model(requested_model):
            logging.info(f"Attempting unload of model '{requested_model}' (metadata request complete)")
            unload_model(requested_model, wait=True)


if __name__ == "__main__":
    t = threading.Thread(target=idle_unload_worker, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=8081, debug=False, threaded=True)
