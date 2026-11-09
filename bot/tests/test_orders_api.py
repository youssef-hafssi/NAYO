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
