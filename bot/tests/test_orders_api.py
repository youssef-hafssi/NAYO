import uuid

H = {"X-API-Key": "k3y", "Origin": "https://nayo.ma"}


def order(**kw):
    base = {
        "clientId": str(uuid.uuid4()),
        "name": "Salma Kettani",
        "phone": "06 12 34 56 78",
        "quantity": 2,
        "product": "NAYO® Déodorant",
        "unitPrice": 189,
        "subtotal": 378,
        "shipping": 20,
        "total": 398,
        "currency": "MAD",
        "payment": "cash_on_delivery",
        "status": "new",
        "createdAt": "2026-11-08T10:00:00.000Z",
    }
    base.update(kw)
    return base


def test_creates_sequential_numbers_and_rows(client, orders):
    a = client.post("/orders", json=order(), headers=H).json()
    b = client.post("/orders", json=order(), headers=H).json()
    assert (a["orderNumber"], b["orderNumber"]) == ("NAYO-1001", "NAYO-1002")
    assert a["total"] == 398
    row = orders.get("NAYO-1001")
    assert row["phone"] == "212612345678" and row["status"] == "new" and row["quantity"] == "2" and row["total"] == "398"


def test_total_is_recomputed_never_trusted(client, orders):
    r = client.post("/orders", json=order(quantity=3, total=1), headers=H).json()
    assert r["total"] == 587 and orders.get(r["orderNumber"])["total"] == "587"


def test_same_client_id_is_idempotent(client, orders):
    body = order()
    a = client.post("/orders", json=body, headers=H).json()
    b = client.post("/orders", json=body, headers=H).json()
    assert a == b and len(orders.rows) == 1


def test_fallback_number_kept_when_new(client, orders):
    r = client.post("/orders", json=order(orderNumber="NAYO-W123456"), headers=H).json()
    assert r["orderNumber"] == "NAYO-W123456" and orders.get("NAYO-W123456")


def test_fallback_after_timeout_becomes_alias(client, orders, store):
    body = order()
    first = client.post("/orders", json=body, headers=H).json()  # browser timed out on this one
    retry = client.post("/orders", json={**body, "orderNumber": "NAYO-W654321"}, headers=H).json()
    assert retry["orderNumber"] == first["orderNumber"] and len(orders.rows) == 1
    assert store.resolve_alias("NAYO-W654321") == first["orderNumber"]


def test_api_key_and_validation(client):
    assert client.post("/orders", json=order(), headers={"X-API-Key": "wrong"}).status_code == 401
    for bad in (
        order(phone="12345"),
        order(phone="+33612345678"),
        order(name="ab"),
        order(name="=HYPERLINK(\"x\")"),
        order(quantity=0),
        order(quantity=11),
        order(currency="EUR"),
        order(orderNumber="NAYO-1"),
        {**order(), "admin": True},
    ):
        r = client.post("/orders", json=bad, headers=H)
        assert r.status_code == 422, bad


def test_rate_limit_per_ip(client):
    codes = [client.post("/orders", json=order(), headers=H).status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and codes[5:] == [429, 429]


def test_cors_only_for_site(client):
    ok = client.options("/orders", headers={"Origin": "https://nayo.ma", "Access-Control-Request-Method": "POST",
                                            "Access-Control-Request-Headers": "content-type,x-api-key"})
    assert ok.headers.get("access-control-allow-origin") == "https://nayo.ma"
    bad = client.options("/orders", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers


# ---------------------------------------------------------------- express checkout (landing page)
def test_express_order_stores_city_and_address(client, orders):
    r = client.post("/orders", json=order(city="  Agadir ", address="Hay Salam,\n rue 12  "), headers=H)
    assert r.status_code == 200, r.text
    row = orders.get(r.json()["orderNumber"])
    assert (row["city"], row["address"]) == ("Agadir", "Hay Salam, rue 12")
    # /commande sends neither: unchanged
    row = orders.get(client.post("/orders", json=order(), headers=H).json()["orderNumber"])
    assert (row["city"], row["address"]) == ("", "")
    # empty fields count as "not given"
    row = orders.get(client.post("/orders", json=order(city=" ", address=""), headers=H).json()["orderNumber"])
    assert (row["city"], row["address"]) == ("", "")


def test_express_order_city_and_address_are_validated(client):
    for bad in ({"city": "A"}, {"city": "x" * 61}, {"address": "rue"}, {"address": "x" * 201},
                {"city": "=HYPERLINK(1)"}, {"address": "+212 hack"}):
        r = client.post("/orders", json=order(**bad), headers=H)
        assert r.status_code == 422, bad
        assert set(r.json()["fields"]) <= {"city", "address"}, r.json()


def test_express_order_address_only_fills_the_city_and_only_asks_yes(client, orders, say, wa, ai):
    """The landing form sends the address only ("Quartier, rue, ville"): no city question, recap, then "oui"."""
    from .conftest import CLIENT

    n = client.post("/orders", json=order(quantity=1, total=209, subtotal=189, address="Hay Salam, rue 12, Agadir"),
                    headers=H).json()["orderNumber"]
    assert orders.get(n)["city"] == "Agadir"  # filled from the address (reports, delivery)
    ai.push("confirm", "Merci !")
    say(f"Bonjour NAYO, je confirme ma commande {n} – 209 MAD – Salma Kettani")
    recap = wa.to(CLIENT)[-1]
    assert recap == "Salma Kettani, Hay Salam, rue 12, Agadir, 209 MAD à la livraison — c'est bon ?"  # city not repeated
    assert orders.get(n)["status"] == "awaiting_details"
    ai.push("confirm", "Super")
    say("oui")
    assert orders.get(n)["status"] == "confirmed"


def test_express_order_unknown_city_is_left_empty_and_never_asked(client, orders, say, wa, ai):
    from .conftest import CLIENT

    n = client.post("/orders", json=order(quantity=1, total=209, subtotal=189, address="Douar Ait Ali, près de la mosquée"),
                    headers=H).json()["orderNumber"]
    assert orders.get(n)["city"] == ""
    ai.push("confirm", "Merci !")
    say(f"je confirme ma commande {n}")
    recap = wa.to(CLIENT)[-1]
    assert recap.startswith("Salma Kettani, Douar Ait Ali, près de la mosquée, 209 MAD") and "ville" not in recap.lower()
    ai.push("confirm", "Super")
    say("oui")
    assert orders.get(n)["status"] == "confirmed" and orders.get(n)["city"] == ""
