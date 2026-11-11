import hashlib
import hmac
import json
import threading

import pytest

from app.phone import is_moroccan_mobile_or_landline, normalize_phone
from app.pricing import order_total
from app.store import Store
from app.texts import detect_lang, normalize_name
from app.whatsapp import extract_messages, verify_signature


@pytest.mark.parametrize(
    "raw",
    ["0612345678", "06 12 34 56 78", "06.12.34.56.78", "+212612345678", "+212 6 12 34 56 78",
     "00212612345678", "212612345678", "+212 0612345678", "(+212) 612-345-678"],
)
def test_phone_normalization_same_format(raw):
    assert normalize_phone(raw) == "212612345678"


@pytest.mark.parametrize("raw", ["", None, "abc", "12", "06123"])
def test_phone_normalization_rejects(raw):
    assert normalize_phone(raw) is None


def test_foreign_numbers_kept_and_moroccan_check():
    assert normalize_phone("+33 6 12 34 56 78") == "33612345678"
    assert not is_moroccan_mobile_or_landline("33612345678")
    assert is_moroccan_mobile_or_landline("212512345678")
    assert not is_moroccan_mobile_or_landline("212812345678")


@pytest.mark.parametrize("q,total", [(1, 209), (2, 398), (3, 587), (10, 1910)])
def test_totals(q, total):
    assert order_total(q) == total


@pytest.mark.parametrize("q", [0, 11, -1, True, 2.0, "2"])
def test_totals_reject(q):
    with pytest.raises(ValueError):
        order_total(q)


def test_signature():
    body = b'{"a":1}'
    sig = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert verify_signature(body, sig, "secret")
    assert not verify_signature(body + b" ", sig, "secret")
    assert not verify_signature(body, sig, "other")
    assert not verify_signature(body, None, "secret")
    assert not verify_signature(body, sig.removeprefix("sha256="), "secret")
    assert not verify_signature(body, sig, "")


def test_extract_messages_ignores_statuses():
    payload = {"entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": "212612345678", "profile": {"name": "Yassine"}}],
        "messages": [{"id": "wamid.1", "from": "212612345678", "type": "text", "text": {"body": "salam"}},
                     {"id": "wamid.2", "from": "212612345678", "type": "audio", "audio": {}}],
        "statuses": [{"id": "wamid.x", "status": "read"}],
    }}]}]}
    msgs = extract_messages(payload)
    assert [(m.id, m.type, m.text, m.profile_name) for m in msgs] == [
        ("wamid.1", "text", "salam", "Yassine"), ("wamid.2", "audio", "", "Yassine")]


def test_language_detection():
    assert detect_lang("لا بغيتش") == "ar"
    assert detect_lang("je veux annuler") == "fr"
    assert detect_lang("wakha confirmi") == "darija"
    assert detect_lang("ana f Agadir hay salam rue 12") == "darija"
    assert detect_lang("ok", previous="darija") == "darija"
    assert detect_lang("Bonjour NAYO, je confirme ma commande NAYO-1043 – 209 MAD – Salma") == "fr"


def test_name_normalization():
    assert normalize_name("  Imane  ÉL-Rhazi ") == normalize_name("imane el rhazi")
    assert normalize_name("Salma K.") == "salma k"


def test_order_counter_is_atomic_under_concurrency(tmp_path):
    store = Store("sqlite", sqlite_path=str(tmp_path / "c.db"))
    got: list[int] = []
    lock = threading.Lock()

    def worker():
        for _ in range(10):
            n = store.next_order_number()
            with lock:
                got.append(n)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(got) == 80 and len(set(got)) == 80
    assert min(got) == 1001 and max(got) == 1080


def test_processed_ids_and_history(store):
    assert store.mark_processed("a") is True
    assert store.mark_processed("a") is False
    for i in range(30):
        store.add_message("p", "client", f"m{i}", keep=20, now=1000 + i)
    msgs = store.recent_messages("p", 50)
    assert len(msgs) == 20 and msgs[0][1] == "m10" and msgs[-1][1] == "m29"


def test_webhook_verification(client):
    ok = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "1234"})
    assert ok.status_code == 200 and ok.text == "1234"
    bad = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "1234"})
    assert bad.status_code == 403


def test_webhook_signature_enforced(client, orders, wa):
    orders.add("NAYO-1001", "Salma K", "212612345678")
    body = json.dumps({"entry": [{"changes": [{"value": {"messages": [
        {"id": "wamid.sig", "from": "212612345678", "type": "text", "text": {"body": "salam"}}]}}]}]}).encode()
    r = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": "sha256=deadbeef"})
    assert r.status_code == 401 and wa.sent == []
    sig = "sha256=" + hmac.new(b"app-secret", body, hashlib.sha256).hexdigest()
    r = client.post("/webhook", content=body, headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"})
    assert r.status_code == 200
    assert wa.to("212612345678")  # processed in the background task, reply sent


def test_health(client):
    assert client.get("/health").json() == {"ok": True, "db": True}


def test_csv_orders_backend(tmp_path):
    from app.sheets import CsvOrders

    o = CsvOrders(str(tmp_path / "orders.csv"))
    o.append({"order_number": "NAYO-1001", "name": "Imane Él", "phone": "212612345678", "quantity": 1, "total": 209, "status": "new"})
    o.append({"order_number": "NAYO-1002", "name": "Salma", "phone": "212612345678", "quantity": 2, "total": 398, "status": "new"})
    assert o.find_open_by_phone("212612345678")["order_number"] == "NAYO-1002"
    o.update("NAYO-1002", status="confirmed", city="Agadir")
    assert o.get("nayo-1002")["status"] == "confirmed" and o.get("NAYO-1002")["updated_at"]
    assert o.find_open_by_phone("212612345678")["order_number"] == "NAYO-1001"
    assert o.get("NAYO-1001")["name"] == "Imane Él"
    assert CsvOrders(str(tmp_path / "orders.csv")).get("NAYO-1001")  # survives reopening


def test_inline_mode_replies_before_answering_meta(settings, orders, store, bot, wa):
    from fastapi.testclient import TestClient

    from app.main import Services, create_app

    settings.process_inline = True
    orders.add("NAYO-1001", "Salma K", "212612345678")
    body = json.dumps({"entry": [{"changes": [{"value": {"messages": [
        {"id": "wamid.inline", "from": "212612345678", "type": "text", "text": {"body": "salam"}}]}}]}]}).encode()
    sig = "sha256=" + hmac.new(b"app-secret", body, hashlib.sha256).hexdigest()
    with TestClient(create_app(Services(settings, store, orders, bot))) as c:
        r = c.post("/webhook", content=body, headers={"X-Hub-Signature-256": sig})
    assert r.status_code == 200 and wa.to("212612345678")


def test_db_orders_backend(store):
    from app.sheets import DbOrders

    o = DbOrders(store)
    o.append({"order_number": "NAYO-1001", "created_at": "2026-11-09 10:00:00", "name": "Imane Él", "phone": "212612345678",
              "quantity": 1, "total": 209, "status": "new"})
    o.append({"order_number": "NAYO-1002", "created_at": "2026-11-09 11:00:00", "name": "Salma", "phone": "212612345678",
              "quantity": 2, "total": 398, "status": "new"})
    assert o.find_open_by_phone("212612345678")["order_number"] == "NAYO-1002"
    o.update("nayo-1002", status="confirmed", city="Agadir")
    assert o.get("NAYO-1002")["status"] == "confirmed" and o.get("NAYO-1002")["updated_at"]
    assert o.find_open_by_phone("212612345678")["order_number"] == "NAYO-1001"
    assert o.find_open_by_phone("212612345678", ("confirmed",))["city"] == "Agadir"
    assert o.get("NAYO-1001")["name"] == "Imane Él" and o.get("NAYO-9999") is None
    with pytest.raises(ValueError):
        o.update("NAYO-1001", hacked="1")


def test_sheet_mirror_copies_new_and_changed_orders(store):
    from app.sheets import DbOrders, MirroredOrders

    posted = []

    class Resp:
        status_code, text = 200, '{"ok":true}'

    def fake_post(url, json):
        posted.append((url, json))
        return Resp()

    o = MirroredOrders(DbOrders(store), "https://script.example/exec", "s3cret", post=fake_post)
    o.append({"order_number": "NAYO-1001", "name": "Salma", "phone": "212612345678", "quantity": 1, "total": 209, "status": "new"})
    o.update("NAYO-1001", status="confirmed", city="Agadir")
    assert [p[1]["order"]["status"] for p in posted] == ["new", "confirmed"]
    assert posted[-1][1]["secret"] == "s3cret" and posted[-1][1]["order"]["city"] == "Agadir"
    assert set(posted[-1][1]["order"]) >= {"order_number", "phone", "total", "address", "updated_at"}


def test_sheet_mirror_failure_never_breaks_orders(store):
    from app.sheets import DbOrders, MirroredOrders

    def boom(url, json):
        raise RuntimeError("google down")

    o = MirroredOrders(DbOrders(store), "https://script.example/exec", "s", post=boom)
    o.append({"order_number": "NAYO-1001", "name": "Salma", "phone": "212612345678", "status": "new"})
    o.update("NAYO-1001", status="confirmed")
    assert o.get("NAYO-1001")["status"] == "confirmed"
