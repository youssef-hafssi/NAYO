"""Phone numbers: every format (+212 6…, 00212 6…, 06…, 2126…) becomes the WhatsApp format 2126XXXXXXXX."""

import re

_SEPARATORS = re.compile(r"[\s().\-/]")


def normalize_phone(raw: str | None) -> str | None:
    """Digits-only international format, as WhatsApp sends it in `from`. None if it isn't a phone number."""
    if not raw:
        return None
    s = _SEPARATORS.sub("", str(raw))
    if s.startswith("+"):
        s = s[1:]
    elif s.startswith("00"):
        s = s[2:]
    if not s.isdigit():
        return None
    if s.startswith("0") and len(s) == 10:  # Moroccan national format 06XXXXXXXX
        s = "212" + s[1:]
    if s.startswith("2120") and len(s) == 13:  # +212 0612… (extra 0 typed after the country code)
        s = "212" + s[4:]
    if not 8 <= len(s) <= 15:
        return None
    return s


def is_moroccan_mobile_or_landline(normalized: str | None) -> bool:
    return bool(normalized) and re.fullmatch(r"212[5-7]\d{8}", normalized) is not None
