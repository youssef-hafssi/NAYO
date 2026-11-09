"""Messages that carry a decision or a number are written here (not by the AI), in the client's language.

Languages: 'fr' (French), 'darija' (Moroccan Darija in Latin letters / Arabizi), 'ar' (Darija in Arabic script).
"""

import re
import unicodedata

ESCALATE = "Un membre de notre équipe vous répond très vite 🙏"

T: dict[str, dict[str, str]] = {
    "ask_order_number": {
        "fr": "Bonjour 😊 Pour retrouver votre commande, envoyez-nous son numéro (ex. NAYO-1043). Il est affiché sur la page de confirmation.",
        "darija": "Salam 😊 3afak sift lina numéro dyal la commande (bhal NAYO-1043), kayn f la page dyal la confirmation.",
        "ar": "السلام 😊 عافاك صيفط لينا رقم الطلب (بحال NAYO-1043)، كاين فصفحة التأكيد.",
    },
    "ask_name": {
        "fr": "Merci ! Pour la sécurité de la commande, pouvez-vous écrire le nom complet utilisé lors de la commande ?",
        "darija": "Choukran! Bach nt2akdo, 3afak kteb lina smiya kamla li dkhlti f la commande.",
        "ar": "شكرا! باش نتأكدو، عافاك كتب لينا السمية كاملة اللي دخلتي فالطلب.",
    },
    "greet_ask_details": {
        "fr": "Merci {first} pour votre commande NAYO ! 😊 Pour la livraison, envoyez-nous votre ville et votre adresse complète.",
        "darija": "Choukran {first} 3la la commande dyal NAYO! 😊 3afak sift lina lmdina w l'adresse kamla bach nwslouha lik.",
        "ar": "شكرا {first} على الطلب ديال NAYO! 😊 عافاك صيفط لينا المدينة والعنوان كامل باش نوصلوه ليك.",
    },
    "ask_details": {
        "fr": "Pour la livraison, envoyez-nous votre ville et votre adresse complète, s'il vous plaît.",
        "darija": "3afak sift lina lmdina w l'adresse kamla dyal la livraison.",
        "ar": "عافاك صيفط لينا المدينة والعنوان كامل ديال التوصيل.",
    },
    "ask_city": {
        "fr": "Merci ! Dans quelle ville doit-on livrer ?",
        "darija": "Choukran! F ina mdina nwslouha lik?",
        "ar": "شكرا! فأي مدينة نوصلوه ليك؟",
    },
    "ask_address": {
        "fr": "Merci ! Quelle est votre adresse complète à {city} (quartier, rue, numéro) ?",
        "darija": "Choukran! Chno l'adresse kamla f {city} (l7ay, zan9a, raqm)?",
        "ar": "شكرا! شنو العنوان كامل ف{city} (الحي، الزنقة، الرقم)؟",
    },
    "recap": {
        "fr": "{name}, {city}, {address}, {qty_part}{total} MAD à la livraison — c'est bon ?",
        "darija": "{name}, {city}, {address}, {qty_part}{total} MAD f la livraison — mzyan haka?",
        "ar": "{name}، {city}، {address}، {qty_part}{total} درهم عند التوصيل — واش هكا مزيان؟",
    },
    "qty_part": {
        "fr": "{qty} × NAYO, ",
        "darija": "{qty} × NAYO, ",
        "ar": "{qty} × NAYO، ",
    },
    "confirmed": {
        "fr": "C'est confirmé ✅ Merci {first} ! Vous paierez {total} MAD au livreur à la réception.",
        "darija": "Safi tconfirmat ✅ Choukran {first}! Ghadi tkhlless {total} MAD l livreur mlli twslek.",
        "ar": "صافي تأكدات ✅ شكرا {first}! غادي تخلص {total} درهم للموزع ملي توصلك.",
    },
    "cancelled": {
        "fr": "C'est noté, votre commande {number} est annulée. Vous pouvez revenir quand vous voulez 🙂",
        "darija": "Safi, la commande {number} tlghat. Mrehba bik f ay wqt 🙂",
        "ar": "صافي، الطلب {number} تلغى. مرحبا بيك فأي وقت 🙂",
    },
    "quantity_updated": {
        "fr": "C'est noté : {qty} × NAYO, total {total} MAD (livraison 20 MAD incluse).",
        "darija": "Safi: {qty} × NAYO, total {total} MAD (m3a livraison 20 MAD).",
        "ar": "صافي: {qty} × NAYO، المجموع {total} درهم (مع التوصيل 20 درهم).",
    },
    "non_text": {
        "fr": "Merci ! Pouvez-vous nous écrire votre message en texte, s'il vous plaît ? 🙏",
        "darija": "Choukran! 3afak kteb lina l message b l'ktaba 🙏",
        "ar": "شكرا! عافاك كتب لينا الرسالة بالكتابة 🙏",
    },
}


def t(key: str, lang: str, **kw) -> str:
    variants = T[key]
    return variants.get(lang, variants["fr"]).format(**kw)


_ARABIC = re.compile(r"[؀-ۿ]")
_FR = {
    "je", "bonjour", "bonsoir", "merci", "commande", "oui", "non", "vous", "est", "pas", "pour", "avec",
    "annuler", "confirme", "livraison", "combien", "quand", "les", "une", "des", "mon", "svp", "adresse",
    "ville", "veux", "voudrais", "suis", "et", "c'est", "s'il", "plait", "plaît",
}
_DARIJA = {
    "wakha", "waxa", "safi", "bghit", "bghina", "chhal", "ch7al", "ana", "fin", "ach", "wach", "kif",
    "dyal", "lla", "mzyan", "3afak", "smiti", "nta", "nti", "taman", "katwslo", "katwsl", "hna",
    "zid", "bghitch", "iyeh", "wa7d", "jouj", "ghadi", "daba", "3la", "l9it",
    # spelling variants seen in real chats (Moroccan Arabizi has no fixed spelling)
    "wakhha", "wkha", "safy", "sfe", "sfi", "mzn", "mzna", "mzian", "mezyan", "mzyana", "choukran", "chokran",
    "chokrane", "choukrane", "shukran", "chkran", "nswlek", "nswlk", "nsowlek", "kifach", "kifash", "kifch",
    "chno", "ash", "wash", "ila", "bzaf", "3endi", "3andi", "fiha", "fih", "hadchi", "hada", "had", "dial",
    "ghir", "khoya", "khti", "sahbi", "labas", "bikhir", "nchallah", "inchallah", "baraka", "lah", "y3tik",
    "ma3rftch", "fhmtch", "ana", "rah", "raha", "kayn", "kayna", "makaynch", "imta", "fo9ach", "f",
}
# Address words ("rue", "hay", "salam" as in Hay Salam…) appear in every language, so they are not markers.


_EN = {
    "i", "want", "please", "the", "order", "my", "you", "when", "how", "much", "yes", "hello", "hi", "thanks",
    "thank", "is", "it", "to", "do", "can", "will", "what", "where", "deliver", "delivery", "price", "cancel",
    "confirm", "and", "address", "city", "would", "like", "am", "in", "of",
}


def detect_lang(text: str, previous: str | None = None) -> str:
    if _ARABIC.search(text or ""):
        return "ar"
    words = set(re.findall(r"[\w'’]+", (text or "").lower().replace("’", "'")))
    fr, da, en = len(words & _FR), len(words & _DARIJA), len(words & _EN)
    if en > max(fr, da):
        return "en"
    if fr > da:
        return "fr"
    if da > fr:
        return "darija"
    return previous or "fr"


def normalize_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s]", " ", s.casefold())
    return " ".join(s.split())


def first_name(name: str) -> str:
    return (name or "").strip().split(" ")[0]
