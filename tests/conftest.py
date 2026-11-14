import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stock_service.app import app as stock_app
from stock_service.db import get_db as stock_get_db, init_schema as stock_init_schema, seed_from_csv
from order_service.app import app as order_app, get_stock_client
from order_service.db import get_db as order_get_db, init_schema as order_init_schema


CSV_PATH = Path(__file__).parent.parent / "Store Stock Snapshot, 7 March 2025 06:45.csv"


@pytest.fixture
def stock_client(tmp_path):
    db_path = tmp_path / "test_stock.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    stock_init_schema(conn)
    seed_from_csv(conn, CSV_PATH)
    conn.close()

    def override():
        c = sqlite3.connect(str(db_path))
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()

    stock_app.dependency_overrides[stock_get_db] = override
    yield TestClient(stock_app)
    stock_app.dependency_overrides.clear()


@pytest.fixture
def order_client(tmp_path):
    db_path = tmp_path / "test_orders.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    order_init_schema(conn)
    conn.close()

    def override_db():
        c = sqlite3.connect(str(db_path))
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()

    order_app.dependency_overrides[order_get_db] = override_db
    yield TestClient(order_app)
    order_app.dependency_overrides.clear()


class MockStockClient:
    """Thin stub that delegates to a real stock service TestClient."""

    def __init__(self, client: TestClient):
        self._client = client

    def validate(self, store_id: str, components) -> dict:
        resp = self._client.post(
            "/validate",
            json={
                "store_id": store_id,
                "components": [c.model_dump() for c in components],
            },
        )
        resp.raise_for_status()
        return resp.json()

    def reserve(self, order_id: str, store_id: str, components) -> dict:
        resp = self._client.post(
            "/reserve",
            json={
                "order_id": order_id,
                "store_id": store_id,
                "components": [c.model_dump() for c in components],
            },
        )
        resp.raise_for_status()
        return resp.json()

    def release(self, order_id: str) -> None:
        resp = self._client.delete(f"/reservations/{order_id}")
        resp.raise_for_status()


@pytest.fixture
def order_client_with_stock(tmp_path):
    """Order service wired to a real (in-memory) stock service."""
    # --- stock DB ---
    stock_db_path = tmp_path / "test_stock.db"
    sc = sqlite3.connect(str(stock_db_path))
    sc.row_factory = sqlite3.Row
    stock_init_schema(sc)
    seed_from_csv(sc, CSV_PATH)
    sc.close()

    def override_stock_db():
        c = sqlite3.connect(str(stock_db_path))
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()

    stock_app.dependency_overrides[stock_get_db] = override_stock_db
    stock_test_client = TestClient(stock_app)

    # --- order DB ---
    order_db_path = tmp_path / "test_orders.db"
    oc = sqlite3.connect(str(order_db_path))
    oc.row_factory = sqlite3.Row
    order_init_schema(oc)
    oc.close()

    def override_order_db():
        c = sqlite3.connect(str(order_db_path))
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()

    mock = MockStockClient(stock_test_client)
    order_app.dependency_overrides[order_get_db] = override_order_db
    order_app.dependency_overrides[get_stock_client] = lambda: mock

    yield TestClient(order_app)

    stock_app.dependency_overrides.clear()
    order_app.dependency_overrides.clear()
