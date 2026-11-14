"""Tests for the stock validation service (read-only gate)."""


def test_health(stock_client):
    resp = stock_client.get("/health")
    assert resp.status_code == 200


def test_get_store_stock(stock_client):
    resp = stock_client.get("/stores/10482/stock")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) > 0
    # available_quantity is derived correctly
    for item in items:
        assert item["available_quantity"] == item["quantity_on_hand"] - item["reserved_quantity"]


def test_get_store_stock_not_found(stock_client):
    resp = stock_client.get("/stores/99999/stock")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Validate endpoint
# ---------------------------------------------------------------------------

def test_validate_happy_path(stock_client):
    # Store 10482 has espresso_signature: quantity_on_hand=142, reserved=4 → available=138
    resp = stock_client.post("/validate", json={
        "store_id": "10482",
        "components": [{"component_id": "espresso_signature", "quantity_needed": 1}],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["store_open"] is True
    assert body["rejection_reason"] is None
    comp = body["components"][0]
    assert comp["available"] == 138
    assert comp["sufficient"] is True


def test_validate_out_of_stock(stock_client):
    # Store 10482 has oat_milk: quantity_on_hand=0, reserved=0 → available=0
    resp = stock_client.post("/validate", json={
        "store_id": "10482",
        "components": [{"component_id": "oat_milk", "quantity_needed": 1}],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert "oat_milk" in body["rejection_reason"]
    assert body["components"][0]["sufficient"] is False


def test_validate_exactly_available(stock_client):
    # almond_milk in store 10482: on_hand=38, reserved=1 → available=37
    resp = stock_client.post("/validate", json={
        "store_id": "10482",
        "components": [{"component_id": "almond_milk", "quantity_needed": 37}],
    })
    assert resp.status_code == 200
    assert resp.json()["valid"] is True


def test_validate_two_pct_milk_available(stock_client):
    # two_pct_milk in store 10482: on_hand=96, reserved=3 → available=93
    resp = stock_client.post("/validate", json={
        "store_id": "10482",
        "components": [{"component_id": "two_pct_milk", "quantity_needed": 93}],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["components"][0]["available"] == 93
    assert body["components"][0]["sufficient"] is True


def test_validate_exceeds_available(stock_client):
    resp = stock_client.post("/validate", json={
        "store_id": "10482",
        "components": [{"component_id": "almond_milk", "quantity_needed": 38}],
    })
    assert resp.status_code == 200
    assert resp.json()["valid"] is False


def test_validate_multiple_components_one_short(stock_client):
    resp = stock_client.post("/validate", json={
        "store_id": "10482",
        "components": [
            {"component_id": "espresso_signature", "quantity_needed": 1},
            {"component_id": "oat_milk", "quantity_needed": 1},  # out of stock
        ],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    results = {c["component_id"]: c for c in body["components"]}
    assert results["espresso_signature"]["sufficient"] is True
    assert results["oat_milk"]["sufficient"] is False


def test_validate_closed_store(stock_client):
    # Store 09815 has store_open=false
    resp = stock_client.post("/validate", json={
        "store_id": "09815",
        "components": [{"component_id": "espresso_signature", "quantity_needed": 1}],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert body["store_open"] is False
    assert "closed" in body["rejection_reason"].lower()


def test_validate_store_not_found(stock_client):
    resp = stock_client.post("/validate", json={
        "store_id": "99999",
        "components": [{"component_id": "espresso_signature", "quantity_needed": 1}],
    })
    assert resp.status_code == 404


def test_validate_component_not_found(stock_client):
    resp = stock_client.post("/validate", json={
        "store_id": "10482",
        "components": [{"component_id": "dragon_syrup", "quantity_needed": 1}],
    })
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Reserve + release endpoints
# ---------------------------------------------------------------------------

def test_reserve_updates_reserved_quantity(stock_client):
    resp = stock_client.post("/reserve", json={
        "order_id": "order-001",
        "store_id": "10482",
        "components": [{"component_id": "espresso_signature", "quantity_needed": 5}],
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # Available should have decreased by 5
    stock = stock_client.get("/stores/10482/stock").json()
    espresso = next(s for s in stock if s["component_id"] == "espresso_signature")
    # original reserved was 4, now should be 9
    assert espresso["reserved_quantity"] == 9
    assert espresso["available_quantity"] == espresso["quantity_on_hand"] - 9


def test_reserve_conflict_when_insufficient(stock_client):
    resp = stock_client.post("/reserve", json={
        "order_id": "order-002",
        "store_id": "10482",
        "components": [{"component_id": "oat_milk", "quantity_needed": 1}],
    })
    assert resp.status_code == 409


def test_release_reservation(stock_client):
    stock_client.post("/reserve", json={
        "order_id": "order-003",
        "store_id": "10482",
        "components": [{"component_id": "vanilla_syrup", "quantity_needed": 3}],
    })

    # Confirm reservation is reflected
    stock = stock_client.get("/stores/10482/stock").json()
    vanilla = next(s for s in stock if s["component_id"] == "vanilla_syrup")
    reserved_after = vanilla["reserved_quantity"]

    # Release it
    resp = stock_client.delete("/reservations/order-003")
    assert resp.status_code == 204

    stock = stock_client.get("/stores/10482/stock").json()
    vanilla = next(s for s in stock if s["component_id"] == "vanilla_syrup")
    assert vanilla["reserved_quantity"] == reserved_after - 3


def test_release_nonexistent_reservation(stock_client):
    resp = stock_client.delete("/reservations/does-not-exist")
    assert resp.status_code == 404
