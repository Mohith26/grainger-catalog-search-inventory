"""Reserve / release stock with zero oversell.

Correctness under concurrency comes from ``SELECT ... FOR UPDATE``: the row for a
(product, warehouse) is locked for the duration of the transaction, so two buyers
racing for the last unit are serialized — one wins, the other gets an
``InsufficientStockError``. The DB ``no_oversell`` CHECK is the belt-and-suspenders
backstop behind the lock.
"""

from __future__ import annotations

from typing import Any

from stockfind import db
from stockfind.errors import InsufficientStockError, NotFoundError


def _product_id(conn: Any, sku: str) -> int:
    row = conn.execute(
        "SELECT id FROM products WHERE part_no = %s", (sku,)
    ).fetchone()
    if row is None:
        raise NotFoundError(f"Unknown SKU: {sku}")
    return row["id"]


def reserve(sku: str, warehouse_code: str, quantity: int, buyer: str) -> dict[str, Any]:
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    pool = db.get_pool()
    with pool.connection() as conn, conn.transaction():
        product_id = _product_id(conn, sku)
        row = conn.execute(
            """
                SELECT on_hand, reserved
                FROM inventory
                WHERE product_id = %s AND warehouse_code = %s
                FOR UPDATE
                """,
            (product_id, warehouse_code),
        ).fetchone()
        if row is None:
            raise NotFoundError(
                f"No stock record for {sku} at warehouse {warehouse_code}"
            )

        atp = row["on_hand"] - row["reserved"]
        if quantity > atp:
            raise InsufficientStockError(
                f"Requested {quantity} but only {atp} available-to-promise "
                f"for {sku} at {warehouse_code}"
            )

        conn.execute(
            """
                UPDATE inventory SET reserved = reserved + %s
                WHERE product_id = %s AND warehouse_code = %s
                """,
            (quantity, product_id, warehouse_code),
        )
        reservation_id = conn.execute(
            """
                INSERT INTO reservations (product_id, warehouse_code, quantity, buyer)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
            (product_id, warehouse_code, quantity, buyer),
        ).fetchone()["id"]

    return {
        "reservation_id": reservation_id,
        "sku": sku,
        "warehouse_code": warehouse_code,
        "quantity": quantity,
        "remaining_atp": atp - quantity,
    }


def release(reservation_id: int) -> dict[str, Any]:
    pool = db.get_pool()
    with pool.connection() as conn, conn.transaction():
        res = conn.execute(
            """
                SELECT product_id, warehouse_code, quantity, status
                FROM reservations
                WHERE id = %s
                FOR UPDATE
                """,
            (reservation_id,),
        ).fetchone()
        if res is None:
            raise NotFoundError(f"Unknown reservation: {reservation_id}")

        if res["status"] != "released":
            conn.execute(
                "UPDATE reservations SET status = 'released' WHERE id = %s",
                (reservation_id,),
            )
            conn.execute(
                """
                    UPDATE inventory SET reserved = reserved - %s
                    WHERE product_id = %s AND warehouse_code = %s
                    """,
                (res["quantity"], res["product_id"], res["warehouse_code"]),
            )

        atp_row = conn.execute(
            """
                SELECT (on_hand - reserved) AS atp
                FROM inventory
                WHERE product_id = %s AND warehouse_code = %s
                """,
            (res["product_id"], res["warehouse_code"]),
        ).fetchone()

    return {
        "reservation_id": reservation_id,
        "status": "released",
        "restored_atp": atp_row["atp"],
    }
