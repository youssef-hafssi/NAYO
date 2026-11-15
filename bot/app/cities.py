"""Moroccan city from a free-text address ("Hay Salam, rue 12, Agadir" → "Agadir").

Used to fill the orders' city column (reports, delivery) when the client only gave an address. Whole words only,
accents / case / punctuation ignored, longest name first. No match → "" (the client is never asked for the city).
"""

from __future__ import annotations

import re
import unicodedata

# Canonical name → spellings people type (Latin, common variants, Arabic). Keep the canonical first.
CITIES: dict[str, tuple[str, ...]] = {
    "Casablanca": ("casablanca", "casa", "dar el beida", "dar al baida", "الدار البيضاء", "كازا", "كازابلانكا"),
    "Rabat": ("rabat", "الرباط"),
    "Salé": ("sale", "sla", "سلا"),
    "Témara": ("temara", "تمارة"),
    "Tamesna": ("tamesna", "تامسنا"),
    "Skhirat": ("skhirat", "الصخيرات"),
    "Kénitra": ("kenitra", "القنيطرة"),
    "Mohammedia": ("mohammedia", "mohamedia", "المحمدية"),
    "Bouskoura": ("bouskoura", "بوسكورة"),
    "Berrechid": ("berrechid", "برشيد"),
    "Settat": ("settat", "سطات"),
    "El Jadida": ("el jadida", "eljadida", "jadida", "الجديدة"),
    "Azemmour": ("azemmour", "أزمور"),
    "Safi": ("safi", "آسفي"),
    "Essaouira": ("essaouira", "الصويرة"),
    "Marrakech": ("marrakech", "marrakesh", "marrakch", "مراكش"),
    "Agadir": ("agadir", "أكادير", "اكادير"),
    "Inezgane": ("inezgane", "انزكان", "إنزكان"),
    "Aït Melloul": ("ait melloul", "ait mellloul", "ايت ملول", "أيت ملول"),
    "Dcheira": ("dcheira", "الدشيرة"),
    "Tiznit": ("tiznit", "تيزنيت"),
    "Taroudant": ("taroudant", "تارودانت"),
    "Guelmim": ("guelmim", "كلميم"),
    "Laâyoune": ("laayoune", "layoune", "العيون"),
    "Dakhla": ("dakhla", "الداخلة"),
    "Ouarzazate": ("ouarzazate", "ورزازات"),
    "Errachidia": ("errachidia", "الرشيدية"),
    "Béni Mellal": ("beni mellal", "بني ملال"),
    "Khouribga": ("khouribga", "خريبكة"),
    "Fquih Ben Salah": ("fquih ben salah", "fkih ben salah", "الفقيه بن صالح"),
    "Khénifra": ("khenifra", "خنيفرة"),
    "Fès": ("fes", "fez", "فاس"),
    "Meknès": ("meknes", "مكناس"),
    "Ifrane": ("ifrane", "إفران"),
    "Azrou": ("azrou", "أزرو"),
    "Taza": ("taza", "تازة"),
    "Oujda": ("oujda", "وجدة"),
    "Nador": ("nador", "الناظور"),
    "Berkane": ("berkane", "بركان"),
    "Al Hoceïma": ("al hoceima", "alhoceima", "hoceima", "الحسيمة"),
    "Tanger": ("tanger", "tangier", "tanja", "طنجة"),
    "Tétouan": ("tetouan", "تطوان"),
    "M'diq": ("mdiq", "m diq", "المضيق"),
    "Fnideq": ("fnideq", "الفنيدق"),
    "Martil": ("martil", "مرتيل"),
    "Larache": ("larache", "العرائش"),
    "Ksar El Kébir": ("ksar el kebir", "ksar kebir", "القصر الكبير"),
    "Asilah": ("asilah", "أصيلة"),
    "Chefchaouen": ("chefchaouen", "chaouen", "شفشاون"),
    "Ouezzane": ("ouezzane", "ouazzane", "وزان"),
    "Sidi Kacem": ("sidi kacem", "سيدي قاسم"),
    "Sidi Slimane": ("sidi slimane", "سيدي سليمان"),
    "Khémisset": ("khemisset", "الخميسات"),
    "Benslimane": ("benslimane", "ben slimane", "بنسليمان"),
    "Bouznika": ("bouznika", "بوزنيقة"),
    "Benguerir": ("benguerir", "ben guerir", "ابن جرير"),
    "El Kelâa des Sraghna": ("kelaa des sraghna", "kelaat sraghna", "قلعة السراغنة"),
    "Youssoufia": ("youssoufia", "اليوسفية"),
    "Sidi Bennour": ("sidi bennour", "سيدي بنور"),
    "Guercif": ("guercif", "جرسيف"),
    "Taourirt": ("taourirt", "تاوريرت"),
    "Midelt": ("midelt", "ميدلت"),
    "Tinghir": ("tinghir", "تنغير"),
    "Zagora": ("zagora", "زاكورة"),
    "Tan-Tan": ("tan tan", "tantan", "طانطان"),
    "Oulad Teima": ("oulad teima", "اولاد تايمة", "أولاد تايمة"),
    "Biougra": ("biougra", "بيوكرى"),
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s]", " ", s.casefold())
    return " ".join(s.split())


# (normalized spelling, canonical), longest spelling first: "ksar el kebir" wins over shorter names.
_INDEX = sorted(((_norm(v), name) for name, variants in CITIES.items() for v in variants), key=lambda x: -len(x[0]))


def detect_city(address: str | None) -> str:
    """The Moroccan city named in an address, or "" (never guessed)."""
    text = f" {_norm(address or '')} "
    if not text.strip():
        return ""
    for spelling, name in _INDEX:
        if f" {spelling} " in text:
            return name
    return ""


def city_in_address(city: str, address: str) -> bool:
    """True when the address already names that city (the recap then shows the address alone)."""
    c = _norm(city)
    return bool(c) and (f" {c} " in f" {_norm(address)} " or detect_city(address) == city)
