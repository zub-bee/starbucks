import sqlite3
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException

from .db import DB_PATH, connect, get_db, init_schema, seed_from_csv
from .models import (
    ComponentResult,
    ReserveRequest,
    ReserveResponse,
    StockItem,
    ValidateRequest,
    ValidateResponse,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = connect()
    init_schema(conn)
    seed_from_csv(conn)
    conn.close()
    yield


app = FastAPI(title="Stock Service", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/stores/{store_id}/stock", response_model=list[StockItem])
def get_store_stock(store_id: str, conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        "SELECT * FROM stock WHERE store_id = ?", (store_id,)
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail=f"Store {store_id} not found")
    return [
        StockItem(
            component_id=r["component_id"],
            component_name=r["component_name"],
            component_type=r["component_type"],
            quantity_on_hand=r["quantity_on_hand"],
            reserved_quantity=r["reserved_quantity"],
            available_quantity=r["quantity_on_hand"] - r["reserved_quantity"],
            last_updated_at=r["last_updated_at"],
        )
        for r in rows
    ]


@app.post("/validate", response_model=ValidateResponse)
def validate_order(req: ValidateRequest, conn: sqlite3.Connection = Depends(get_db)):
    store_row = conn.execute(
        "SELECT store_open FROM stock WHERE store_id = ? LIMIT 1", (req.store_id,)
    ).fetchone()

    if not store_row:
        raise HTTPException(status_code=404, detail=f"Store {req.store_id} not found")

    if not store_row["store_open"]:
        return ValidateResponse(
            store_id=req.store_id,
            store_open=False,
            valid=False,
            components=[],
            rejection_reason="Store is currently closed",
        )

    results: list[ComponentResult] = []
    all_sufficient = True

    for item in req.components:
        row = conn.execute(
            """
            SELECT component_name, quantity_on_hand, reserved_quantity
            FROM stock
            WHERE store_id = ? AND component_id = ?
            """,
            (req.store_id, item.component_id),
        ).fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Component '{item.component_id}' not found in store {req.store_id}",
            )

        available = row["quantity_on_hand"] - row["reserved_quantity"]
        sufficient = available >= item.quantity_needed
        if not sufficient:
            all_sufficient = False

        results.append(
            ComponentResult(
                component_id=item.component_id,
                component_name=row["component_name"],
                required=item.quantity_needed,
                available=available,
                sufficient=sufficient,
            )
        )

    rejection_reason = None
    if not all_sufficient:
        short = [r.component_id for r in results if not r.sufficient]
        rejection_reason = f"Insufficient stock for: {', '.join(short)}"

    return ValidateResponse(
        store_id=req.store_id,
        store_open=True,
        valid=all_sufficient,
        components=results,
        rejection_reason=rejection_reason,
    )


@app.post("/reserve", response_model=ReserveResponse)
def reserve_stock(req: ReserveRequest, conn: sqlite3.Connection = Depends(get_db)):
    # Re-check availability atomically before updating
    for item in req.components:
        row = conn.execute(
            "SELECT quantity_on_hand, reserved_quantity FROM stock WHERE store_id = ? AND component_id = ?",
            (req.store_id, item.component_id),
        ).fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Component '{item.component_id}' not found",
            )

        available = row["quantity_on_hand"] - row["reserved_quantity"]
        if available < item.quantity_needed:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Insufficient stock for '{item.component_id}': "
                    f"need {item.quantity_needed}, have {available}"
                ),
            )

    for item in req.components:
        conn.execute(
            "UPDATE stock SET reserved_quantity = reserved_quantity + ? WHERE store_id = ? AND component_id = ?",
            (item.quantity_needed, req.store_id, item.component_id),
        )
        conn.execute(
            "INSERT INTO reservations (order_id, store_id, component_id, quantity) VALUES (?, ?, ?, ?)",
            (req.order_id, req.store_id, item.component_id, item.quantity_needed),
        )

    conn.commit()
    return ReserveResponse(order_id=req.order_id, success=True)


@app.delete("/reservations/{order_id}", status_code=204)
def release_reservation(order_id: str, conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        "SELECT store_id, component_id, quantity FROM reservations WHERE order_id = ?",
        (order_id,),
    ).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail=f"No reservation found for order {order_id}")

    for row in rows:
        conn.execute(
            "UPDATE stock SET reserved_quantity = reserved_quantity - ? WHERE store_id = ? AND component_id = ?",
            (row["quantity"], row["store_id"], row["component_id"]),
        )

    conn.execute("DELETE FROM reservations WHERE order_id = ?", (order_id,))
    conn.commit()
