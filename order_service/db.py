import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "orders.db"


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
        CREATE TABLE IF NOT EXISTS orders (
            order_id         TEXT PRIMARY KEY,
            store_id         TEXT NOT NULL,
            customer_name    TEXT NOT NULL,
            status           TEXT NOT NULL,
            created_at       TEXT NOT NULL,
            rejection_reason TEXT
        );

        CREATE TABLE IF NOT EXISTS order_components (
            order_id       TEXT NOT NULL,
            component_id   TEXT NOT NULL,
            quantity_needed INTEGER NOT NULL,
            PRIMARY KEY (order_id, component_id),
            FOREIGN KEY (order_id) REFERENCES orders(order_id)
        );

        CREATE TABLE IF NOT EXISTS preparation_queue (
            position  INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id  TEXT NOT NULL UNIQUE,
            store_id  TEXT NOT NULL,
            added_at  TEXT NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(order_id)
        );
    """)
    conn.commit()
