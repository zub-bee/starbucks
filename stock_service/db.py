import csv
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "stock.db"
CSV_PATH = Path(__file__).parent.parent / "Store Stock Snapshot, 7 March 2025 06:45.csv"


def connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def get_db():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS stock (
            store_id          TEXT NOT NULL,
            store_name        TEXT NOT NULL,
            store_open        INTEGER NOT NULL,
            component_id      TEXT NOT NULL,
            component_name    TEXT NOT NULL,
            component_type    TEXT NOT NULL,
            quantity_on_hand  INTEGER NOT NULL,
            reserved_quantity INTEGER NOT NULL DEFAULT 0,
            last_updated_at   TEXT NOT NULL,
            PRIMARY KEY (store_id, component_id)
        );

        CREATE TABLE IF NOT EXISTS reservations (
            order_id     TEXT NOT NULL,
            store_id     TEXT NOT NULL,
            component_id TEXT NOT NULL,
            quantity     INTEGER NOT NULL,
            PRIMARY KEY (order_id, component_id)
        );
    """)
    conn.commit()


def seed_from_csv(conn: sqlite3.Connection, csv_path: Path = CSV_PATH) -> None:
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            conn.execute(
                """
                INSERT OR REPLACE INTO stock
                    (store_id, store_name, store_open, component_id, component_name,
                     component_type, quantity_on_hand, reserved_quantity, last_updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["store_id"],
                    row["store_name"],
                    1 if row["store_open"].lower() == "true" else 0,
                    row["component_id"],
                    row["component_name"],
                    row["component_type"],
                    int(row["quantity_on_hand"]),
                    int(row["reserved_quantity"]),
                    row["last_updated_at"],
                ),
            )
    conn.commit()
