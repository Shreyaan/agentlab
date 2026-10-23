"""Best-effort scrubbing of secrets from anything persisted or sent to a judge model.

A backstop, not the primary control: keep credentials out of recorded data in the first place.
"""

import re

from pydantic import JsonValue

SECRET_KEY = re.compile(r"secret|token|password|authorization|api[_-]?key|cookie", re.IGNORECASE)
SECRET_PARAM = re.compile(r"token|key|secret|sig|password", re.IGNORECASE)
QUERY_PARAM = re.compile(r"[?&]([^=&\s?#]{1,256})=")  # bounded, delimiter-free name: linear on hostile text
VALUE_END = re.compile(r"[&\s\"']")
AUTHORITY_END = re.compile(r"[/\s]")
SECRET_VALUE = [  # (pattern, replacement) for secrets embedded in free text: errors, outputs, URLs
    (re.compile(r"(bearer\s+)[\w.~+/=-]+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"\b(?:sk|pk|rk)[-_][\w-]{16,}|\bgh[pousr]_\w{20,}|\bAKIA[0-9A-Z]{16}\b"), "[REDACTED]"),
]


def redact_query_params(text: str) -> str:
    """Secret-named params are redacted up to the next & / whitespace / quote (values may contain ? or #).
    Benign params are skipped without consuming their value, so a param embedded in it is still found."""
    out, pos = [], 0
    for m in QUERY_PARAM.finditer(text):
        if m.start() < pos or not SECRET_PARAM.search(m[1]):
            continue
        end = VALUE_END.search(text, m.end())
        out += [text[pos : m.end()], "[REDACTED]"]
        pos = end.start() if end else len(text)
    return "".join(out) + text[pos:]


def _is_number_or_null(value: JsonValue) -> bool:
    return value is None or (isinstance(value, int | float) and not isinstance(value, bool))


def redact_userinfo(text: str) -> str:
    """Redact URL credentials up to the LAST '@' before the next '/' or whitespace (passwords may contain '@', '?',
    '#'). No length bound, so nothing fails open; each authority span is scanned once, so it is linear."""
    out, pos = [], 0
    while (scheme := text.find("://", pos)) != -1:
        start = scheme + 3
        end = m.start() if (m := AUTHORITY_END.search(text, start)) else len(text)
        at = text.rfind("@", start, end)
        out.append(text[pos:start] + ("[REDACTED]" if at != -1 else ""))
        pos = at if at != -1 else start
    return "".join(out) + text[pos:]


def redact(value: JsonValue) -> JsonValue:
    """Key-based for structured data, pattern-based for free text. Under a secret-looking key everything is redacted
    except numbers and nulls, so numeric telemetry such as input_tokens survives."""
    if isinstance(value, dict):
        return {
            k: redact(v) if not SECRET_KEY.search(k) or _is_number_or_null(v) else "[REDACTED]"
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = redact_query_params(redact_userinfo(value))
        for pattern, repl in SECRET_VALUE:
            value = pattern.sub(repl, value)
    return value
