"""Tests for the order service (validate → reserve → queue)."""


OPEN_STORE = "10482"    # First Hill - Madison & Boylston (store_open=true)
CLOSED_STORE = "09815"  # South Lake Union (store_open=false)


def _latte_order(store_id: str = OPEN_STORE, customer: str = "Alice"):
    return {
        "store_id": store_id,
        "customer_name": customer,
        "items": [
            {
                "drink_name": "Oat Milk Latte",
                "components": [
                    {"component_id": "espresso_signature", "quantity_needed": 2},
                    {"component_id": "two_pct_milk", "quantity_needed": 1},
                ],
            }
        ],
    }


# ---------------------------------------------------------------------------
# Order creation
# ---------------------------------------------------------------------------

def test_create_order_accepted(order_client_with_stock):
    resp = order_client_with_stock.post("/orders", json=_latte_order())
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["customer_name"] == "Alice"
    assert body["rejection_reason"] is None


def test_accepted_order_appears_in_queue(order_client_with_stock):
    resp = order_client_with_stock.post("/orders", json=_latte_order())
    order_id = resp.json()["order_id"]

    queue = order_client_with_stock.get(f"/stores/{OPEN_STORE}/queue").json()
    ids = [e["order_id"] for e in queue]
    assert order_id in ids


def test_queue_preserves_fifo_order(order_client_with_stock):
    id1 = order_client_with_stock.post("/orders", json=_latte_order(customer="Alice")).json()["order_id"]
    id2 = order_client_with_stock.post("/orders", json=_latte_order(customer="Bob")).json()["order_id"]

    queue = order_client_with_stock.get(f"/stores/{OPEN_STORE}/queue").json()
    ids = [e["order_id"] for e in queue]
    assert ids.index(id1) < ids.index(id2)


def test_create_order_rejected_out_of_stock(order_client_with_stock):
    # oat_milk in store 10482 has 0 available
    order = {
        "store_id": OPEN_STORE,
        "customer_name": "Bob",
        "items": [
            {
                "drink_name": "Oat Milk Latte",
                "components": [{"component_id": "oat_milk", "quantity_needed": 1}],
            }
        ],
    }
    resp = order_client_with_stock.post("/orders", json=order)
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "rejected"
    assert body["rejection_reason"] is not None


def test_rejected_order_not_in_queue(order_client_with_stock):
    order = {
        "store_id": OPEN_STORE,
        "customer_name": "Eve",
        "items": [
            {
                "drink_name": "Oat Milk Latte",
                "components": [{"component_id": "oat_milk", "quantity_needed": 1}],
            }
        ],
    }
    order_id = order_client_with_stock.post("/orders", json=order).json()["order_id"]
    queue = order_client_with_stock.get(f"/stores/{OPEN_STORE}/queue").json()
    ids = [e["order_id"] for e in queue]
    assert order_id not in ids


def test_create_order_closed_store(order_client_with_stock):
    order = {
        "store_id": CLOSED_STORE,
        "customer_name": "Carol",
        "items": [
            {
                "drink_name": "Espresso",
                "components": [{"component_id": "espresso_signature", "quantity_needed": 1}],
            }
        ],
    }
    resp = order_client_with_stock.post("/orders", json=order)
    assert resp.status_code == 201
    assert resp.json()["status"] == "rejected"


def test_reservation_reduces_available_stock(order_client_with_stock):
    from fastapi.testclient import TestClient
    from stock_service.app import app as stock_app

    # Grab available before the order
    stock_before = {
        item["component_id"]: item
        for item in TestClient(stock_app).get(f"/stores/{OPEN_STORE}/stock").json()
    }
    espresso_before = stock_before["espresso_signature"]["available_quantity"]

    order_client_with_stock.post("/orders", json=_latte_order())

    stock_after = {
        item["component_id"]: item
        for item in TestClient(stock_app).get(f"/stores/{OPEN_STORE}/stock").json()
    }
    espresso_after = stock_after["espresso_signature"]["available_quantity"]
    assert espresso_after == espresso_before - 2


# ---------------------------------------------------------------------------
# Get order
# ---------------------------------------------------------------------------

def test_get_order(order_client_with_stock):
    order_id = order_client_with_stock.post("/orders", json=_latte_order()).json()["order_id"]
    resp = order_client_with_stock.get(f"/orders/{order_id}")
    assert resp.status_code == 200
    assert resp.json()["order_id"] == order_id


def test_get_order_not_found(order_client_with_stock):
    resp = order_client_with_stock.get("/orders/nonexistent-id")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Complete order
# ---------------------------------------------------------------------------

def test_complete_order_marks_ready_and_leaves_queue(order_client_with_stock):
    order_id = order_client_with_stock.post("/orders", json=_latte_order()).json()["order_id"]

    resp = order_client_with_stock.patch(f"/orders/{order_id}/complete")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"

    queue = order_client_with_stock.get(f"/stores/{OPEN_STORE}/queue").json()
    assert order_id not in [e["order_id"] for e in queue]


def test_complete_already_ready_order_fails(order_client_with_stock):
    order_id = order_client_with_stock.post("/orders", json=_latte_order()).json()["order_id"]
    order_client_with_stock.patch(f"/orders/{order_id}/complete")

    resp = order_client_with_stock.patch(f"/orders/{order_id}/complete")
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Cancel order
# ---------------------------------------------------------------------------

def test_cancel_order_releases_reservation(order_client_with_stock):
    from fastapi.testclient import TestClient
    from stock_service.app import app as stock_app

    stock_before = {
        item["component_id"]: item
        for item in TestClient(stock_app).get(f"/stores/{OPEN_STORE}/stock").json()
    }

    order_id = order_client_with_stock.post("/orders", json=_latte_order()).json()["order_id"]
    order_client_with_stock.delete(f"/orders/{order_id}")

    stock_after = {
        item["component_id"]: item
        for item in TestClient(stock_app).get(f"/stores/{OPEN_STORE}/stock").json()
    }

    # reservation should be fully released — available quantity matches what it was before
    assert (
        stock_after["espresso_signature"]["available_quantity"]
        == stock_before["espresso_signature"]["available_quantity"]
    )
