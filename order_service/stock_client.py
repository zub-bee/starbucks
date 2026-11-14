import httpx

from .models import ComponentRequirement

STOCK_SERVICE_URL = "http://localhost:8001"


class StockServiceError(Exception):
    pass


class StockClient:
    def __init__(self, base_url: str = STOCK_SERVICE_URL):
        self.base_url = base_url

    def validate(self, store_id: str, components: list[ComponentRequirement]) -> dict:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(
                f"{self.base_url}/validate",
                json={
                    "store_id": store_id,
                    "components": [c.model_dump() for c in components],
                },
            )
            resp.raise_for_status()
            return resp.json()

    def reserve(self, order_id: str, store_id: str, components: list[ComponentRequirement]) -> dict:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(
                f"{self.base_url}/reserve",
                json={
                    "order_id": order_id,
                    "store_id": store_id,
                    "components": [c.model_dump() for c in components],
                },
            )
            resp.raise_for_status()
            return resp.json()

    def release(self, order_id: str) -> None:
        with httpx.Client(timeout=5.0) as client:
            resp = client.delete(f"{self.base_url}/reservations/{order_id}")
            resp.raise_for_status()
