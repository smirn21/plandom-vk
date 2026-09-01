"""SQLite-хранилище ПланДом: пользователи, wizard, проекты, платежи."""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Generator

LOGGER = logging.getLogger(__name__)

PRO_PROJECTS_PER_MONTH = 3


def create_storage(db_path: Path | str) -> "Storage":
    return Storage(Path(db_path))


class Storage:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    subscription TEXT DEFAULT 'free',
                    subscription_expires_at TEXT,
                    subscription_type TEXT,
                    free_trial_used INTEGER DEFAULT 0,
                    pro_projects_used INTEGER DEFAULT 0,
                    pro_projects_reset_at TEXT,
                    created_at TEXT
                );

                CREATE TABLE IF NOT EXISTS wizard (
                    user_id TEXT PRIMARY KEY,
                    step TEXT NOT NULL DEFAULT 'start',
                    data_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS admin_state (
                    user_id TEXT PRIMARY KEY,
                    action TEXT
                );

                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    brief_json TEXT NOT NULL,
                    layout_json TEXT,
                    tier TEXT DEFAULT 'free',
                    is_paid INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'draft',
                    output_dir TEXT,
                    created_at TEXT
                );

                CREATE TABLE IF NOT EXISTS payments (
                    payment_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    amount REAL NOT NULL,
                    payment_type TEXT NOT NULL,
                    subscription_type TEXT,
                    project_id TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT,
                    paid_at TEXT
                );
                """
            )
            self._add_column_if_missing(conn, "users", "created_at", "TEXT")
            conn.execute(
                "UPDATE users SET created_at = ? WHERE created_at IS NULL",
                (datetime.now().isoformat(),),
            )

    @staticmethod
    def _add_column_if_missing(
        conn: sqlite3.Connection, table: str, column: str, col_type: str
    ) -> None:
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")

    def ensure_user(self, user_id: str) -> None:
        uid = str(user_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id FROM users WHERE user_id = ?", (uid,)
            ).fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO users (user_id, created_at) VALUES (?, ?)",
                    (uid, datetime.now().isoformat()),
                )

    def get_user(self, user_id: str) -> dict[str, Any]:
        self.ensure_user(user_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (str(user_id),)
            ).fetchone()
            return dict(row) if row else {}

    def is_pro(self, user_id: str) -> bool:
        user = self.get_user(user_id)
        if user.get("subscription") != "pro":
            return False
        exp = user.get("subscription_expires_at")
        if not exp:
            return False
        try:
            return datetime.fromisoformat(exp) > datetime.now()
        except ValueError:
            return False

    def _reset_pro_quota_if_needed(self, conn: sqlite3.Connection, user_id: str) -> None:
        row = conn.execute(
            "SELECT pro_projects_reset_at, pro_projects_used FROM users WHERE user_id = ?",
            (str(user_id),),
        ).fetchone()
        if not row:
            return
        reset_at = row["pro_projects_reset_at"]
        now = datetime.now()
        need_reset = True
        if reset_at:
            try:
                need_reset = datetime.fromisoformat(reset_at) <= now
            except ValueError:
                need_reset = True
        if need_reset:
            conn.execute(
                """
                UPDATE users
                SET pro_projects_used = 0,
                    pro_projects_reset_at = ?
                WHERE user_id = ?
                """,
                ((now + timedelta(days=30)).isoformat(), str(user_id)),
            )

    def pro_projects_remaining(self, user_id: str) -> int:
        if not self.is_pro(user_id):
            return 0
        with self._connect() as conn:
            self._reset_pro_quota_if_needed(conn, user_id)
            row = conn.execute(
                "SELECT pro_projects_used FROM users WHERE user_id = ?",
                (str(user_id),),
            ).fetchone()
            used = int(row["pro_projects_used"] or 0) if row else 0
            return max(0, PRO_PROJECTS_PER_MONTH - used)

    def increment_pro_project(self, user_id: str) -> None:
        with self._connect() as conn:
            self._reset_pro_quota_if_needed(conn, user_id)
            conn.execute(
                """
                UPDATE users SET pro_projects_used = COALESCE(pro_projects_used, 0) + 1
                WHERE user_id = ?
                """,
                (str(user_id),),
            )

    def mark_free_trial_used(self, user_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET free_trial_used = 1 WHERE user_id = ?",
                (str(user_id),),
            )

    def set_subscription(
        self,
        user_id: str,
        tier: str,
        expires_at: str,
        subscription_type: str = "month",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET subscription = ?, subscription_expires_at = ?, subscription_type = ?,
                    pro_projects_used = 0,
                    pro_projects_reset_at = ?
                WHERE user_id = ?
                """,
                (
                    tier,
                    expires_at,
                    subscription_type,
                    (datetime.now() + timedelta(days=30)).isoformat(),
                    str(user_id),
                ),
            )

    def expire_subscriptions(self) -> list[str]:
        now = datetime.now().isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT user_id FROM users
                WHERE subscription = 'pro'
                  AND subscription_expires_at IS NOT NULL
                  AND subscription_expires_at <= ?
                """,
                (now,),
            ).fetchall()
            expired = [r["user_id"] for r in rows]
            if expired:
                conn.execute(
                    """
                    UPDATE users
                    SET subscription = 'free', subscription_expires_at = NULL
                    WHERE user_id IN ({})
                    """.format(",".join("?" * len(expired))),
                    expired,
                )
            return expired

    def get_wizard(self, user_id: str) -> tuple[str, dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT step, data_json FROM wizard WHERE user_id = ?", (str(user_id),)
            ).fetchone()
            if not row:
                return "start", {}
            try:
                data = json.loads(row["data_json"] or "{}")
            except json.JSONDecodeError:
                data = {}
            return row["step"] or "start", data

    def set_wizard(self, user_id: str, step: str, data: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO wizard (user_id, step, data_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    step = excluded.step,
                    data_json = excluded.data_json,
                    updated_at = excluded.updated_at
                """,
                (str(user_id), step, json.dumps(data, ensure_ascii=False), datetime.now().isoformat()),
            )

    def clear_subscription(self, user_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET subscription = 'free', subscription_expires_at = NULL,
                    subscription_type = NULL, pro_projects_used = 0
                WHERE user_id = ?
                """,
                (str(user_id),),
            )

    def reset_free_trial(self, user_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET free_trial_used = 0 WHERE user_id = ?",
                (str(user_id),),
            )

    def set_admin_state(self, user_id: str, action: str | None) -> None:
        with self._connect() as conn:
            if action is None:
                conn.execute("DELETE FROM admin_state WHERE user_id = ?", (str(user_id),))
            else:
                conn.execute(
                    """
                    INSERT INTO admin_state (user_id, action) VALUES (?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET action = excluded.action
                    """,
                    (str(user_id), action),
                )

    def get_admin_state(self, user_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT action FROM admin_state WHERE user_id = ?", (str(user_id),)
            ).fetchone()
            return row["action"] if row else None

    def list_recent_users(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT user_id, subscription, created_at, free_trial_used
                FROM users ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def clear_wizard(self, user_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM wizard WHERE user_id = ?", (str(user_id),))

    def create_project(
        self,
        project_id: str,
        user_id: str,
        brief: dict[str, Any],
        tier: str = "free",
        output_dir: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO projects
                (id, user_id, brief_json, tier, status, output_dir, created_at)
                VALUES (?, ?, ?, ?, 'generating', ?, ?)
                """,
                (
                    project_id,
                    str(user_id),
                    json.dumps(brief, ensure_ascii=False),
                    tier,
                    output_dir,
                    datetime.now().isoformat(),
                ),
            )

    def update_project(
        self,
        project_id: str,
        *,
        layout: dict[str, Any] | None = None,
        tier: str | None = None,
        is_paid: bool | None = None,
        status: str | None = None,
        output_dir: str | None = None,
    ) -> None:
        fields: list[str] = []
        params: list[Any] = []
        if layout is not None:
            fields.append("layout_json = ?")
            params.append(json.dumps(layout, ensure_ascii=False))
        if tier is not None:
            fields.append("tier = ?")
            params.append(tier)
        if is_paid is not None:
            fields.append("is_paid = ?")
            params.append(1 if is_paid else 0)
        if status is not None:
            fields.append("status = ?")
            params.append(status)
        if output_dir is not None:
            fields.append("output_dir = ?")
            params.append(output_dir)
        if not fields:
            return
        params.append(project_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE projects SET {', '.join(fields)} WHERE id = ?",
                params,
            )

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if not row:
                return None
            data = dict(row)
            for key in ("brief_json", "layout_json"):
                if data.get(key):
                    try:
                        data[key.replace("_json", "")] = json.loads(data[key])
                    except json.JSONDecodeError:
                        data[key.replace("_json", "")] = {}
            return data

    def get_latest_project(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM projects WHERE user_id = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (str(user_id),),
            ).fetchone()
            if not row:
                return None
            data = dict(row)
            if data.get("brief_json"):
                try:
                    data["brief"] = json.loads(data["brief_json"])
                except json.JSONDecodeError:
                    data["brief"] = {}
            return data

    def create_payment(
        self,
        payment_id: str,
        user_id: str,
        amount: float,
        payment_type: str,
        subscription_type: str | None = None,
        project_id: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO payments
                (payment_id, user_id, amount, payment_type, subscription_type, project_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payment_id,
                    str(user_id),
                    amount,
                    payment_type,
                    subscription_type,
                    project_id,
                    datetime.now().isoformat(),
                ),
            )

    def get_pending_payments(self, limit: int = 50) -> list[tuple[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payment_id, user_id FROM payments
                WHERE status = 'pending'
                ORDER BY created_at ASC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [(r["payment_id"], r["user_id"]) for r in rows]

    def get_payment_by_id(self, payment_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM payments WHERE payment_id = ?", (payment_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_unused_project_payment(self, user_id: str) -> str | None:
        """Тип оплаченного, но не применённого разового проекта."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT payment_type FROM payments
                WHERE user_id = ? AND status = 'succeeded'
                  AND payment_type IN ('project_apartment', 'project_house')
                  AND (project_id IS NULL OR project_id = '')
                ORDER BY paid_at DESC LIMIT 1
                """,
                (str(user_id),),
            ).fetchone()
            return row["payment_type"] if row else None

    def consume_project_payment(self, user_id: str, project_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE payments SET project_id = ?
                WHERE user_id = ? AND status = 'succeeded'
                  AND payment_type IN ('project_apartment', 'project_house')
                  AND (project_id IS NULL OR project_id = '')
                """,
                (project_id, str(user_id)),
            )

    def update_payment_status(
        self, payment_id: str, status: str, paid_at: str | None = None
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE payments SET status = ?, paid_at = COALESCE(?, paid_at) WHERE payment_id = ?",
                (status, paid_at, payment_id),
            )
            row = conn.execute(
                "SELECT * FROM payments WHERE payment_id = ?", (payment_id,)
            ).fetchone()
            return dict(row) if row else None
