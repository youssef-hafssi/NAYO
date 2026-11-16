"""Meta Conversions API: hashed user data, one Purchase per new order (deduplicated with the browser Pixel by
event_id), test event code, token never in the URL, and an order never depends on Meta."""

import hashlib
import uuid

from app.meta import MetaCapi, purchase_event, user_data

from .test_orders_api import H, order


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


class FakePost:
    def __init__(self, status=200, fail=False):
        self.calls, self.status, self.fail = [], status, fail

    def __call__(self, url, json):
        self.calls.append((url, json))
        if self.fail:
            raise ConnectionError("down")
        return type("R", (), {"status_code": self.status, "text": '{"events_received":1}'})()


def use_meta(client, post, test_code=""):
    client.app.state.meta_box["m"] = MetaCapi("1490585709624189", "TOKEN-xyz", "v26.0", test_code, post=post)


def test_user_data_is_normalized_and_hashed():
    ud = user_data(phone="212612345678", name="  Salma  Kettani ", city="Agadir", ip="1.2.3.4", user_agent="UA",
                   fbp="fb.1.1700000000000.123", fbc="fb.1.1700000000000.AbC", external_id="212612345678")
    assert ud["ph"] == [sha("212612345678")] and ud["fn"] == [sha("salma")] and ud["ln"] == [sha("kettani")]
    assert ud["ct"] == [sha("agadir")] and ud["country"] == [sha("ma")]
    assert (ud["client_ip_address"], ud["client_user_agent"], ud["fbp"], ud["fbc"]) == ("1.2.3.4", "UA", "fb.1.1700000000000.123", "fb.1.1700000000000.AbC")
    assert "212612345678" not in str({k: v for k, v in ud.items() if k not in ("client_ip_address",)})  # never in clear
    assert user_data(name="Fès Rabat", city="Fès")["ct"] == [sha("fes")]  # accents removed before hashing


def test_new_order_sends_one_purchase_deduplicated_with_the_browser(client, orders):
    post = FakePost()
    use_meta(client, post, test_code="TEST123")
    cid = str(uuid.uuid4())
    body = order(clientId=cid, quantity=2, address="Hay Salam, rue 12, Agadir", fbp="fb.1.1700000000000.123456789",
                 fbc="fb.1.1700000000000.IwAR0abc", pageUrl="https://nayo.ma/?utm_source=fb")
    r = client.post("/orders", json=body, headers={**H, "User-Agent": "Mozilla/5.0 test", "X-Forwarded-For": "41.250.1.2"})
    assert r.status_code == 200, r.text
    assert len(post.calls) == 1
    url, sent = post.calls[0]
    assert url == "https://graph.facebook.com/v26.0/1490585709624189/events" and "TOKEN" not in url  # token in the body
    assert sent["access_token"] == "TOKEN-xyz" and sent["test_event_code"] == "TEST123"
    e = sent["data"][0]
    assert (e["event_name"], e["event_id"], e["action_source"]) == ("Purchase", f"purchase-{cid}", "website")
    assert e["event_source_url"] == "https://nayo.ma/?utm_source=fb"
    assert e["custom_data"]["value"] == 398 and e["custom_data"]["currency"] == "MAD" and e["custom_data"]["num_items"] == 2
    assert e["custom_data"]["order_id"] == r.json()["orderNumber"]
    ud = e["user_data"]
    assert ud["ph"] == [sha("212612345678")] and ud["ct"] == [sha("agadir")]  # city found in the address
    assert ud["client_ip_address"] == "41.250.1.2" and ud["client_user_agent"] == "Mozilla/5.0 test"
    assert ud["fbp"] == "fb.1.1700000000000.123456789" and ud["fbc"] == "fb.1.1700000000000.IwAR0abc"
    # the browser retries the same order (same clientId): stored once, sent once
    assert client.post("/orders", json=body, headers=H).json()["orderNumber"] == r.json()["orderNumber"]
    assert len(post.calls) == 1


def test_tracking_never_blocks_an_order(client, orders):
    # malformed / oversized tracking values are dropped, the order goes through
    post = FakePost()
    use_meta(client, post)
    r = client.post("/orders", json=order(fbp="<script>", fbc="fb.1.1700000000000." + "x" * 900, pageUrl="javascript:alert(1)"), headers=H)
    assert r.status_code == 200, r.text
    ud = post.calls[0][1]["data"][0]["user_data"]
    assert "fbp" not in ud and "fbc" not in ud and "event_source_url" not in post.calls[0][1]["data"][0]
    assert "test_event_code" not in post.calls[0][1]
    # Meta down or refusing: the order is saved anyway
    for bad in (FakePost(fail=True), FakePost(status=400)):
        use_meta(client, bad)
        r = client.post("/orders", json=order(), headers=H)
        assert r.status_code == 200 and orders.get(r.json()["orderNumber"]) is not None


def test_disabled_without_token_or_pixel(client):
    post = FakePost()
    client.app.state.meta_box["m"] = MetaCapi("1490585709624189", "", "v26.0", post=post)
    assert client.post("/orders", json=order(), headers=H).status_code == 200
    client.app.state.meta_box["m"] = MetaCapi("", "TOKEN", "v26.0", post=post)
    assert client.post("/orders", json=order(), headers=H).status_code == 200
    assert post.calls == []


def test_invalid_order_sends_nothing(client):
    post = FakePost()
    use_meta(client, post)
    assert client.post("/orders", json=order(phone="123"), headers=H).status_code == 422
    assert post.calls == []


def test_purchase_event_shape():
    e = purchase_event(event_id="purchase-x", value=209, quantity=1, order_number="NAYO-1001", source_url="", ud={}, at=1800000000)
    assert e["event_time"] == 1800000000 and e["event_source_url"] is None
    assert e["custom_data"]["contents"] == [{"id": "nayo-deodorant", "quantity": 1}]
