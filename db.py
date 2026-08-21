import os
import sqlite3
import pandas as pd

DB_PATH = "stock_game.db"

INITIAL_COMPANIES = [
    ("미래IT",    "IT",     10000),
    ("글로벌무역", "무역",    8000),
    ("행복식품",  "식품",    5000),
    ("클린에너지", "에너지", 12000),
]

INITIAL_GOLD_PRICE     = 100000
INITIAL_BTC_PRICE      = 5000000
INITIAL_BOND_RATE      = 0.5
INITIAL_SAVING_RATE    = 3.0
INITIAL_SAVING_PERIOD  = 5
INITIAL_INFLATION_RATE = 0.3

NUM_STUDENTS     = 23
INITIAL_CASH     = 1_000_000
DEFAULT_PASSWORD = "0000"


def get_connection():
    """
    Streamlit Secrets 또는 환경 변수에 Turso 접속 정보(TURSO_DATABASE_URL, TURSO_AUTH_TOKEN)가 있으면
    Turso 클라우드 DB에 연결하고, 없으면 로컬 SQLite(stock_game.db)에 연결합니다.
    """
    turso_url = None
    turso_token = None

    try:
        import streamlit as st
        turso_url = st.secrets.get("TURSO_DATABASE_URL")
        turso_token = st.secrets.get("TURSO_AUTH_TOKEN")
    except Exception:
        pass

    if not turso_url:
        turso_url = os.environ.get("TURSO_DATABASE_URL")
        turso_token = os.environ.get("TURSO_AUTH_TOKEN")

    if turso_url and turso_token:
        import libsql
        conn = libsql.connect(database=turso_url, auth_token=turso_token)
    else:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)

    try:
        conn.row_factory = sqlite3.Row
    except Exception:
        pass

    return conn


def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            company_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            sector        TEXT    NOT NULL,
            current_price INTEGER NOT NULL,
            prev_price    INTEGER NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS alt_assets (
            asset_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_type    TEXT    NOT NULL UNIQUE,
            name          TEXT    NOT NULL,
            unit          TEXT    NOT NULL,
            current_price REAL    NOT NULL,
            prev_price    REAL    NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS game_settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS news (
            news_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            day        INTEGER NOT NULL,
            company_id INTEGER,
            content    TEXT    NOT NULL,
            news_type  TEXT    NOT NULL DEFAULT 'stock'
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS students (
            student_id      INTEGER PRIMARY KEY,
            cash            REAL    NOT NULL,
            cumulative_loss REAL    NOT NULL DEFAULT 0,
            password        TEXT    NOT NULL DEFAULT '0000'
        )
    """)

    for col, definition in [
        ("password",        "TEXT NOT NULL DEFAULT '0000'"),
        ("cumulative_loss", "REAL NOT NULL DEFAULT 0"),
    ]:
        try:
            c.execute(f"ALTER TABLE students ADD COLUMN {col} {definition}")
        except Exception:
            pass

    c.execute("""
        CREATE TABLE IF NOT EXISTS holdings (
            holding_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            company_id INTEGER NOT NULL,
            quantity   INTEGER NOT NULL DEFAULT 0,
            UNIQUE (student_id, company_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS alt_holdings (
            alt_holding_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id     INTEGER NOT NULL,
            asset_type     TEXT    NOT NULL,
            quantity       REAL    NOT NULL DEFAULT 0,
            UNIQUE (student_id, asset_type)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS bond_holdings (
            bond_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL UNIQUE,
            amount     REAL    NOT NULL DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS savings (
            saving_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            amount     REAL    NOT NULL,
            rate       REAL    NOT NULL,
            start_day  INTEGER NOT NULL,
            end_day    INTEGER NOT NULL,
            is_matured INTEGER NOT NULL DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            tx_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            asset_type TEXT    NOT NULL DEFAULT 'stock',
            company_id INTEGER,
            tx_type    TEXT    NOT NULL,
            quantity   REAL    NOT NULL,
            price      REAL    NOT NULL,
            reason     TEXT    NOT NULL,
            day        INTEGER NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS inflation_log (
            log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            day         INTEGER NOT NULL,
            rate        REAL    NOT NULL,
            student_id  INTEGER NOT NULL,
            loss_amount REAL    NOT NULL
        )
    """)

    # 초기 데이터 삽입
    c.execute("SELECT COUNT(*) as cnt FROM companies")
    if c.fetchone()[0] == 0:
        for name, sector, price in INITIAL_COMPANIES:
            c.execute(
                "INSERT INTO companies (name,sector,current_price,prev_price) VALUES (?,?,?,?)",
                (name, sector, price, price)
            )

    c.execute("SELECT COUNT(*) as cnt FROM alt_assets")
    if c.fetchone()[0] == 0:
        c.execute(
            "INSERT INTO alt_assets (asset_type,name,unit,current_price,prev_price) VALUES (?,?,?,?,?)",
            ("gold", "금", "g", INITIAL_GOLD_PRICE, INITIAL_GOLD_PRICE)
        )
        c.execute(
            "INSERT INTO alt_assets (asset_type,name,unit,current_price,prev_price) VALUES (?,?,?,?,?)",
            ("bitcoin", "비트코인", "BTC", INITIAL_BTC_PRICE, INITIAL_BTC_PRICE)
        )

    defaults = {
        "day":            "1",
        "bond_rate":      str(INITIAL_BOND_RATE),
        "saving_rate":    str(INITIAL_SAVING_RATE),
        "saving_period":  str(INITIAL_SAVING_PERIOD),
        "inflation_rate": str(INITIAL_INFLATION_RATE),
    }
    for key, value in defaults.items():
        c.execute(
            "INSERT OR IGNORE INTO game_settings (key,value) VALUES (?,?)",
            (key, value)
        )

    c.execute("SELECT COUNT(*) as cnt FROM students")
    if c.fetchone()[0] == 0:
        for i in range(1, NUM_STUDENTS + 1):
            c.execute(
                "INSERT INTO students (student_id,cash,password) VALUES (?,?,?)",
                (i, INITIAL_CASH, DEFAULT_PASSWORD)
            )

    conn.commit()
    conn.close()


def get_setting(key: str) -> str:
    conn = get_connection()
    row = conn.execute(
        "SELECT value FROM game_settings WHERE key=?", (key,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def set_setting(key: str, value: str):
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO game_settings (key,value) VALUES (?,?)",
        (key, value)
    )
    conn.commit()
    conn.close()


def verify_student_password(student_id: int, password: str) -> bool:
    conn = get_connection()
    row = conn.execute(
        "SELECT password FROM students WHERE student_id=?", (student_id,)
    ).fetchone()
    conn.close()
    return row["password"] == password if row else False


def update_student_password(student_id: int, new_password: str):
    conn = get_connection()
    conn.execute(
        "UPDATE students SET password=? WHERE student_id=?",
        (new_password, student_id)
    )
    conn.commit()
    conn.close()


def reset_all_passwords(new_password: str):
    conn = get_connection()
    conn.execute("UPDATE students SET password=?", (new_password,))
    conn.commit()
    conn.close()


def get_all_passwords() -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql(
        "SELECT student_id, password FROM students ORDER BY student_id", conn
    )
    conn.close()
    return df


def reset_game(reset_password: bool = False):
    conn = get_connection()
    try:
        try:
            conn.execute("BEGIN")
        except Exception:
            pass

        conn.execute("DELETE FROM holdings")
        conn.execute("DELETE FROM alt_holdings")
        conn.execute("DELETE FROM bond_holdings")
        conn.execute("DELETE FROM savings")
        conn.execute("DELETE FROM transactions")
        conn.execute("DELETE FROM news")
        conn.execute("DELETE FROM inflation_log")

        if reset_password:
            conn.execute(
                "UPDATE students SET cash=?, cumulative_loss=0, password=?",
                (INITIAL_CASH, DEFAULT_PASSWORD)
            )
        else:
            conn.execute(
                "UPDATE students SET cash=?, cumulative_loss=0",
                (INITIAL_CASH,)
            )

        for name, sector, price in INITIAL_COMPANIES:
            conn.execute(
                "UPDATE companies SET current_price=?, prev_price=? WHERE name=? AND sector=?",
                (price, price, name, sector)
            )
        conn.execute(
            "UPDATE alt_assets SET current_price=?, prev_price=? WHERE asset_type='gold'",
            (INITIAL_GOLD_PRICE, INITIAL_GOLD_PRICE)
        )
        conn.execute(
            "UPDATE alt_assets SET current_price=?, prev_price=? WHERE asset_type='bitcoin'",
            (INITIAL_BTC_PRICE, INITIAL_BTC_PRICE)
        )

        for key, val in [
            ("day",            "1"),
            ("bond_rate",      str(INITIAL_BOND_RATE)),
            ("saving_rate",    str(INITIAL_SAVING_RATE)),
            ("saving_period",  str(INITIAL_SAVING_PERIOD)),
            ("inflation_rate", str(INITIAL_INFLATION_RATE)),
        ]:
            conn.execute(
                "INSERT OR REPLACE INTO game_settings (key,value) VALUES (?,?)",
                (key, val)
            )

        conn.commit()
        conn.close()
        return True, "게임이 성공적으로 초기화되었습니다!"
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        conn.close()
        return False, f"오류 발생: {e}"


def get_game_summary() -> dict:
    conn = get_connection()
    day      = int(get_setting("day") or 1)
    tx_count = conn.execute("SELECT COUNT(*) as c FROM transactions").fetchone()["c"]
    news_cnt = conn.execute("SELECT COUNT(*) as c FROM news").fetchone()["c"]
    active   = conn.execute(
        "SELECT COUNT(DISTINCT student_id) as c FROM transactions"
    ).fetchone()["c"]
    conn.close()
    return {
        "current_day":      day,
        "tx_count":        tx_count,
        "news_count":      news_cnt,
        "active_students": active,
    }
