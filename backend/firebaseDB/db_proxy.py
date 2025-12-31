from typing import List, Optional

import psycopg2
from psycopg2 import sql

from ..fieldDetecting.sandbox.combinedSrc.config import get_logger
from .connection_store import ConnectionRecord, create, get, remove


logger = get_logger(__name__)


def _sanitize_key(key: str, allowed: List[str]) -> Optional[str]:
    if not key:
        return None
    candidate = key.strip()
    if candidate in allowed:
        return candidate
    lower = candidate.lower()
    for column in allowed:
        if column.lower() == lower:
            return column
    return None


def _pick_identifier_key(columns: List[str]) -> Optional[str]:
    lower = {c.lower(): c for c in columns}
    for pref in ["mrn", "patient_id", "enterprise_patient_id", "external_mrn", "id"]:
        if pref in lower:
            return lower[pref]
    for col in columns:
        if "mrn" in col.lower():
            return col
    for col in columns:
        if col.lower().endswith("_id") or col.lower() == "id":
            return col
    return columns[0] if columns else None


def _connect_postgres(cfg: dict):
    sslmode = "require" if cfg.get("ssl") else "prefer"
    return psycopg2.connect(
        host=cfg["host"],
        port=int(cfg.get("port") or 5432),
        dbname=cfg["database"],
        user=cfg["user"],
        password=cfg["password"],
        sslmode=sslmode,
        connect_timeout=10,
    )


def _postgres_columns(cursor, schema: str, view: str) -> List[str]:
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, view),
    )
    return [row[0] for row in cursor.fetchall()]


def test_and_create_connection(payload: dict) -> dict:
    db_type = str(payload.get("type") or "").lower()
    if db_type != "postgres":
        raise ValueError("Only postgres is supported in the Python backend")

    cfg = {
        "host": payload.get("host"),
        "port": payload.get("port"),
        "database": payload.get("database"),
        "user": payload.get("user"),
        "password": payload.get("password"),
        "ssl": bool(payload.get("ssl")),
    }
    schema = payload.get("schema") or "public"
    view = payload.get("view")
    if not cfg["host"] or not cfg["database"] or not cfg["user"] or not cfg["password"] or not view:
        raise ValueError("Missing required fields")

    logger.debug("Testing postgres connection", {"host": cfg["host"], "database": cfg["database"], "schema": schema, "view": view})
    with _connect_postgres(cfg) as conn:
        with conn.cursor() as cursor:
            columns = _postgres_columns(cursor, schema, view)
            query = sql.SQL("SELECT * FROM {}.{} LIMIT 1").format(
                sql.Identifier(schema),
                sql.Identifier(view),
            )
            cursor.execute(query)
            cursor.fetchone()

    record = create({
        "type": db_type,
        "config": cfg,
        "schema": schema,
        "view": view,
        "ttlMs": payload.get("ttlMs"),
    })
    return {
        "connId": record.id,
        "columns": columns,
        "identifierKey": _pick_identifier_key(columns),
    }


def fetch_columns(conn_id: str) -> List[str]:
    record = get(conn_id)
    if not record:
        raise ValueError("Invalid or expired connection")
    if record.type != "postgres":
        raise ValueError("Only postgres is supported in the Python backend")
    with _connect_postgres(record.config) as conn:
        with conn.cursor() as cursor:
            return _postgres_columns(cursor, record.schema, record.view)


def disconnect(conn_id: str) -> bool:
    return remove(conn_id)


def get_row_by_identifier(conn_id: str, key: str, value: str) -> Optional[dict]:
    record = get(conn_id)
    if not record:
        raise ValueError("Invalid or expired connection")
    if record.type != "postgres":
        raise ValueError("Only postgres is supported in the Python backend")
    with _connect_postgres(record.config) as conn:
        with conn.cursor() as cursor:
            columns = _postgres_columns(cursor, record.schema, record.view)
            safe_key = _sanitize_key(key, columns)
            if not safe_key:
                raise ValueError("Invalid key")
            query = sql.SQL("SELECT * FROM {}.{} WHERE {} = %s LIMIT 1").format(
                sql.Identifier(record.schema),
                sql.Identifier(record.view),
                sql.Identifier(safe_key),
            )
            cursor.execute(query, (value,))
            row = cursor.fetchone()
            if not row:
                return None
            return dict(zip([desc[0] for desc in cursor.description], row))


def search_rows(
    conn_id: str,
    key: str,
    query: str,
    *,
    mode: str = "contains",
    limit: int = 25,
) -> List[dict]:
    record = get(conn_id)
    if not record:
        raise ValueError("Invalid or expired connection")
    if record.type != "postgres":
        raise ValueError("Only postgres is supported in the Python backend")
    if query is None:
        return []
    query_text = str(query).strip()
    if not query_text:
        return []

    try:
        limit_val = int(limit)
    except Exception:
        limit_val = 25
    limit_val = max(1, min(limit_val, 50))

    with _connect_postgres(record.config) as conn:
        with conn.cursor() as cursor:
            columns = _postgres_columns(cursor, record.schema, record.view)
            safe_key = _sanitize_key(key, columns)
            if not safe_key:
                raise ValueError("Invalid key")

            mode_norm = str(mode or "").strip().lower()
            if mode_norm == "equals":
                clause = sql.SQL("{} = %s").format(sql.Identifier(safe_key))
                params = (query_text, limit_val)
            else:
                clause = sql.SQL("CAST({} AS TEXT) ILIKE %s").format(sql.Identifier(safe_key))
                params = (f"%{query_text}%", limit_val)

            query_stmt = (
                sql.SQL("SELECT * FROM {}.{} WHERE ")
                .format(sql.Identifier(record.schema), sql.Identifier(record.view))
                + clause
                + sql.SQL(" LIMIT %s")
            )
            cursor.execute(query_stmt, params)
            matches = cursor.fetchall()
            if not matches:
                return []

            cols = [desc[0] for desc in cursor.description]
            return [dict(zip(cols, row)) for row in matches]
