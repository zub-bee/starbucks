import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException

from .db import get_db, init_schema
from .models import (
    ComponentRequirement,
    CreateOrderRequest,
    Order,
    OrderStatus,
    QueueEntry,
)
from .stock_client import StockClient


def get_stock_client() -> StockClient:
    return StockClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .db import connect

    conn = connect()
    init_schema(conn)
    conn.close()
    yield


app = FastAPI(title="Order Service", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/orders", response_model=Order, status_code=201)
def create_order(
    req: CreateOrderRequest,
    conn: sqlite3.Connection = Depends(get_db),
    stock: StockClient = Depends(get_stock_client),
):
    # Aggregate components across all items in the order
    totals: dict[str, int] = {}
    for item in req.items:
        for comp in item.components:
            totals[comp.component_id] = totals.get(comp.component_id, 0) + comp.quantity_needed

    components = [
        ComponentRequirement(component_id=k, quantity_needed=v) for k, v in totals.items()
    ]

    validation = stock.validate(req.store_id, components)

    order_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    if not validation["valid"]:
        conn.execute(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)",
            (
                order_id,
                req.store_id,
                req.customer_name,
                OrderStatus.REJECTED,
                now,
                validation.get("rejection_reason"),
            ),
        )
        conn.commit()
        return Order(
            order_id=order_id,
            store_id=req.store_id,
            customer_name=req.customer_name,
            status=OrderStatus.REJECTED,
            created_at=now,
            rejection_reason=validation.get("rejection_reason"),
        )

    # Stock is available — reserve it
    stock.reserve(order_id, req.store_id, components)

    conn.execute(
        "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)",
        (order_id, req.store_id, req.customer_name, OrderStatus.ACCEPTED, now, None),
    )
    for comp in components:
        conn.execute(
            "INSERT INTO order_components VALUES (?, ?, ?)",
            (order_id, comp.component_id, comp.quantity_needed),
        )
    conn.execute(
        "INSERT INTO preparation_queue (order_id, store_id, added_at) VALUES (?, ?, ?)",
        (order_id, req.store_id, now),
    )
    conn.commit()

    return Order(
        order_id=order_id,
        store_id=req.store_id,
        customer_name=req.customer_name,
        status=OrderStatus.ACCEPTED,
        created_at=now,
    )


@app.get("/orders/{order_id}", response_model=Order)
def get_order(order_id: str, conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
    return Order(**dict(row))


@app.get("/stores/{store_id}/queue", response_model=list[QueueEntry])
def get_queue(store_id: str, conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        """
        SELECT q.position, q.order_id, q.store_id, o.customer_name, q.added_at
        FROM preparation_queue q
        JOIN orders o ON o.order_id = q.order_id
        WHERE q.store_id = ?
        ORDER BY q.position
        """,
        (store_id,),
    ).fetchall()
    return [QueueEntry(**dict(r)) for r in rows]


@app.patch("/orders/{order_id}/complete", response_model=Order)
def complete_order(
    order_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    stock: StockClient = Depends(get_stock_client),
):
    row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")

    if row["status"] != OrderStatus.ACCEPTED:
        raise HTTPException(
            status_code=409,
            detail=f"Order is not in accepted state (current: {row['status']})",
        )

    conn.execute(
        "UPDATE orders SET status = ? WHERE order_id = ?",
        (OrderStatus.READY, order_id),
    )
    conn.execute("DELETE FROM preparation_queue WHERE order_id = ?", (order_id,))
    conn.commit()

    return Order(
        order_id=order_id,
        store_id=row["store_id"],
        customer_name=row["customer_name"],
        status=OrderStatus.READY,
        created_at=row["created_at"],
    )


@app.delete("/orders/{order_id}", status_code=204)
def cancel_order(
    order_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    stock: StockClient = Depends(get_stock_client),
):
    row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")

    if row["status"] not in (OrderStatus.ACCEPTED, OrderStatus.IN_PREPARATION):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel order in status '{row['status']}'",
        )

    stock.release(order_id)

    conn.execute(
        "UPDATE orders SET status = 'cancelled' WHERE order_id = ?", (order_id,)
    )
    conn.execute("DELETE FROM preparation_queue WHERE order_id = ?", (order_id,))
    conn.commit()
