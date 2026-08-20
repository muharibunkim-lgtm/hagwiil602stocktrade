# db.py
# 자산 확장 버전: 국채, 금, 비트코인, 적금, 인플레이션 추가

import sqlite3

DB_PATH = "stock_game.db"

# ── 초기 기업 정보 ────────────────────────────────────────────
INITIAL_COMPANIES = [
    ("미래IT",    "IT",     10000),
    ("글로벌무역", "무역",    8000),
    ("행복식품",  "식품",    5000),
    ("클린에너지", "에너지", 12000),
]

# ── 초기 대체 자산 가격 ───────────────────────────────────────
INITIAL_GOLD_PRICE    = 100000   # 금 1g 가격 (원)
INITIAL_BTC_PRICE     = 5000000  # 비트코인 1BTC 가격 (원)
INITIAL_BOND_RATE     = 0.5      # 국채 일일 이자율 (%)
INITIAL_SAVING_RATE   = 3.0      # 적금 만기 이자율 (%)
INITIAL_INFLATION_RATE = 0.3     # 일일 물가 상승률 (%) → 현금 가치 하락

NUM_STUDENTS     = 23
INITIAL_CASH     = 1_000_000
DEFAULT_PASSWORD = "0000"


def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    c = conn.cursor()

    # ── 기업(주식) 테이블 ────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            company_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            sector        TEXT    NOT NULL,
            current_price INTEGER NOT NULL,
            prev_price    INTEGER NOT NULL
        )
    """)

    # ── 대체 자산 시세 테이블 (금, 비트코인) ─────────────────
    # asset_type: 'gold' | 'bitcoin'
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

    # ── 게임 설정 테이블 (국채이율, 적금이율, 물가상승률) ─────
    c.execute("""
        CREATE TABLE IF NOT EXISTS game_settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    # ── 뉴스 테이블 ──────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS news (
            news_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            day        INTEGER NOT NULL,
            company_id INTEGER,           -- NULL이면 전체 경제 뉴스
            content    TEXT    NOT NULL,
            news_type  TEXT    NOT NULL DEFAULT 'stock',
            FOREIGN KEY (company_id) REFERENCES companies(company_id)
        )
    """)

    # ── 학생 테이블 ──────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS students (
            student_id       INTEGER PRIMARY KEY,
            cash             REAL    NOT NULL,
            cumulative_loss  REAL    NOT NULL DEFAULT 0,
            password         TEXT    NOT NULL DEFAULT '0000'
        )
    """)

    # 마이그레이션: 기존 테이블에 컬럼 없으면 추가
    for col, definition in [
        ("password",        "TEXT NOT NULL DEFAULT '0000'"),
        ("cumulative_loss", "REAL NOT NULL DEFAULT 0"),
    ]:
        try:
            c.execute(f"ALTER TABLE students ADD COLUMN {col} {definition}")
        except sqlite3.OperationalError:
            pass

    # ── 보유 주식 테이블 ─────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS holdings (
            holding_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            company_id INTEGER NOT NULL,
            quantity   INTEGER NOT NULL DEFAULT 0,
            UNIQUE (student_id, company_id),
            FOREIGN KEY (student_id)  REFERENCES students(student_id),
            FOREIGN KEY (company_id)  REFERENCES companies(company_id)
        )
    """)

    # ── 대체 자산 보유 테이블 (금, 비트코인) ─────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS alt_holdings (
            alt_holding_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id     INTEGER NOT NULL,
            asset_type     TEXT    NOT NULL,
            quantity       REAL    NOT NULL DEFAULT 0,
            UNIQUE (student_id, asset_type),
            FOREIGN KEY (student_id) REFERENCES students(student_id)
        )
    """)

    # ── 국채 보유 테이블 ─────────────────────────────────────
    # 국채: 구매 금액만큼 보유, 매일 이자 자동 지급
    c.execute("""
        CREATE TABLE IF NOT EXISTS bond_holdings (
            bond_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL UNIQUE,
            amount     REAL    NOT NULL DEFAULT 0,
            FOREIGN KEY (student_id) REFERENCES students(student_id)
        )
    """)

    # ── 적금 테이블 ──────────────────────────────────────────
    # 적금: 납입 시점(day), 만기(day), 납입 금액, 이자율 저장
    c.execute("""
        CREATE TABLE IF NOT EXISTS savings (
            saving_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            amount     REAL    NOT NULL,
            rate       REAL    NOT NULL,
            start_day  INTEGER NOT NULL,
            end_day    INTEGER NOT NULL,
            is_matured INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (student_id) REFERENCES students(student_id)
        )
    """)

    # ── 거래 내역 테이블 ─────────────────────────────────────
    # asset_type: 'stock' | 'gold' | 'bitcoin' | 'bond' | 'saving'
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
            day        INTEGER NOT NULL,
            FOREIGN KEY (student_id)  REFERENCES students(student_id),
            FOREIGN KEY (company_id)  REFERENCES companies(company_id)
        )
    """)

    # ── 인플레이션 로그 테이블 ───────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS inflation_log (
            log_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            day        INTEGER NOT NULL,
            rate       REAL    NOT NULL,
            student_id INTEGER NOT NULL,
            loss_amount REAL   NOT NULL
        )
    """)

    # ── 게임 상태 테이블 ─────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS game_state (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    # ── 초기 데이터 삽입 ─────────────────────────────────────

    # 기업
    c.execute("SELECT COUNT(*) as cnt FROM companies")
    if c.fetchone()["cnt"] == 0:
        for name, sector, price in INITIAL_COMPANIES:
            c.execute(
                "INSERT INTO companies (name,sector,current_price,prev_price) VALUES (?,?,?,?)",
                (name, sector, price, price)
            )

    # 대체 자산 (금, 비트코인)
    c.execute("SELECT COUNT(*) as cnt FROM alt_assets")
    if c.fetchone()["cnt"] == 0:
        c.execute("""
            INSERT INTO alt_assets (asset_type,name,unit,current_price,prev_price)
            VALUES ('gold','금','g',?,?)
        """, (INITIAL_GOLD_PRICE, INITIAL_GOLD_PRICE))
        c.execute("""
            INSERT INTO alt_assets (asset_type,name,unit,current_price,prev_price)
            VALUES ('bitcoin','비트코인','BTC',?,?)
        """, (INITIAL_BTC_PRICE, INITIAL_BTC_PRICE))

    # 게임 설정 기본값
    defaults = {
        "day":            "1",
        "bond_rate":      str(INITIAL_BOND_RATE),
        "saving_rate":    str(INITIAL_SAVING_RATE),
        "inflation_rate": str(INITIAL_INFLATION_RATE),
        "saving_period":  "5",   # 적금 만기 기간(일)
    }
    for key, value in defaults.items():
        c.execute(
            "INSERT OR IGNORE INTO game_settings (key,value) VALUES (?,?)",
            (key, value)
        )

    # 학생
    c.execute("SELECT COUNT(*) as cnt FROM students")
    if c.fetchone()["cnt"] == 0:
        for i in range(1, NUM_STUDENTS + 1):
            c.execute(
                "INSERT INTO students (student_id,cash,password) VALUES (?,?,?)",
                (i, INITIAL_CASH, DEFAULT_PASSWORD)
            )

    # 거래일 (game_state → game_settings로 이전)
    c.execute("SELECT value FROM game_state WHERE key='day'")
    if c.fetchone() is None:
        c.execute("INSERT INTO game_state (key,value) VALUES ('day','1')")

    conn.commit()
    conn.close()


# ── 설정값 조회/저장 헬퍼 ────────────────────────────────────

def get_setting(key: str) -> str:
    conn = get_connection()
    row = conn.execute(
        "SELECT value FROM game_settings WHERE key=?", (key,)
    ).fetchone()
    conn.close()
    return row["value"] if row else None


def set_setting(key: str, value: str):
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO game_settings (key,value) VALUES (?,?)",
        (key, value)
    )
    conn.commit()
    conn.close()


# ── 비밀번호 관련 ────────────────────────────────────────────

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


def get_all_passwords():
    import pandas as pd
    conn = get_connection()
    df = pd.read_sql(
        "SELECT student_id, password FROM students ORDER BY student_id", conn
    )
    conn.close()
    return df


# ── 게임 초기화 ──────────────────────────────────────────────

def reset_game(reset_password: bool = False):
    conn = get_connection()
    try:
        conn.execute("BEGIN")
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
                (INITIAL_CASH, "0000")
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

        # 설정값 초기화
        for key, val in [
            ("day",            "1"),
            ("bond_rate",      str(INITIAL_BOND_RATE)),
            ("saving_rate",    str(INITIAL_SAVING_RATE)),
            ("inflation_rate", str(INITIAL_INFLATION_RATE)),
            ("saving_period",  "5"),
        ]:
            conn.execute(
                "INSERT OR REPLACE INTO game_settings (key,value) VALUES (?,?)",
                (key, val)
            )

        conn.commit()
        conn.close()
        return True, "게임이 성공적으로 초기화되었습니다!"
    except Exception as e:
        conn.rollback()
        conn.close()
        return False, f"오류 발생: {e}"


def get_game_summary() -> dict:
    import pandas as pd
    conn = get_connection()
    day      = int(get_setting("day") or 1)
    tx_count = conn.execute("SELECT COUNT(*) as c FROM transactions").fetchone()["c"]
    news_cnt = conn.execute("SELECT COUNT(*) as c FROM news").fetchone()["c"]
    active   = conn.execute(
        "SELECT COUNT(DISTINCT student_id) as c FROM transactions"
    ).fetchone()["c"]
    conn.close()
    return {
        "current_day":     day,
        "tx_count":        tx_count,
        "news_count":      news_cnt,
        "active_students": active,
    }
