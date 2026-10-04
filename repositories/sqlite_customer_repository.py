from __future__ import annotations

from pathlib import Path
from typing import Optional
from uuid import uuid4

from models import CustomerRecord
from repositories.sqlite import connect_sqlite, default_sqlite_path, now_iso


def customer_key(name: Optional[str], contact: Optional[str] = None) -> str:
    return f"{(name or '').strip().casefold()}|{(contact or '').strip().casefold()}"


class SqliteCustomerRepository:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else default_sqlite_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = connect_sqlite(self.path)
        self._initialize()

    def close(self) -> None:
        self._connection.close()

    def _initialize(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY,
                customer_id TEXT NOT NULL UNIQUE,
                customer_name TEXT NOT NULL,
                department TEXT,
                contact_name TEXT,
                email TEXT,
                phone TEXT,
                address TEXT,
                end_user TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def save(self, record: CustomerRecord) -> CustomerRecord:
        now = now_iso()
        existing = None
        if record.customer_id:
            existing = self.get(record.customer_id)
        if existing is None:
            existing = self.find(record.customer_name, record.contact_name)
        customer_id = existing.customer_id if existing else (record.customer_id or f"CUS-{uuid4().hex[:10].upper()}")
        created = existing.created_at if existing else (record.created_at or now)
        stored = record.model_copy(update={"customer_id": customer_id, "created_at": created, "updated_at": now})
        self._connection.execute(
            """
            INSERT INTO customers (
                customer_id, customer_name, department, contact_name, email, phone,
                address, end_user, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(customer_id) DO UPDATE SET
                customer_name = excluded.customer_name,
                department = excluded.department,
                contact_name = excluded.contact_name,
                email = excluded.email,
                phone = excluded.phone,
                address = excluded.address,
                end_user = excluded.end_user,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            (
                stored.customer_id,
                stored.customer_name,
                stored.department,
                stored.contact_name,
                stored.email,
                stored.phone,
                stored.address,
                stored.end_user,
                stored.notes,
                stored.created_at,
                stored.updated_at,
            ),
        )
        self._connection.commit()
        return stored

    def get(self, customer_id: str) -> Optional[CustomerRecord]:
        row = self._connection.execute(
            "SELECT * FROM customers WHERE customer_id = ?",
            (customer_id,),
        ).fetchone()
        return self._from_row(row) if row else None

    def find(self, customer_name: Optional[str], contact_name: Optional[str] = None) -> Optional[CustomerRecord]:
        if not (customer_name or "").strip():
            return None
        row = self._connection.execute(
            """
            SELECT * FROM customers
            WHERE lower(trim(customer_name)) = lower(trim(?))
              AND lower(trim(COALESCE(contact_name, ''))) = lower(trim(?))
            """,
            (customer_name, contact_name or ""),
        ).fetchone()
        return self._from_row(row) if row else None

    def list_customers(self) -> list[CustomerRecord]:
        rows = self._connection.execute(
            "SELECT * FROM customers ORDER BY customer_name COLLATE NOCASE, contact_name COLLATE NOCASE"
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def _from_row(self, row) -> CustomerRecord:
        return CustomerRecord(
            customer_id=row["customer_id"],
            customer_name=row["customer_name"],
            department=row["department"],
            contact_name=row["contact_name"],
            email=row["email"],
            phone=row["phone"],
            address=row["address"],
            end_user=row["end_user"],
            notes=row["notes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
