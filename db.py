# db.py
# SQLite3 DB를 초기화하는 모듈
# 학생 비밀번호 컬럼 추가 버전

import sqlite3

DB_PATH = "stock_game.db"

# 초기 기업 정보
INITIAL_COMPANIES = [
    ("미래IT",    "IT",     10000),
    ("글로벌무역", "무역",   8000),
    ("행복식품",  "식품",    5000),
    ("클린에너지", "에너지", 12000),
]

NUM_STUDENTS  = 23
INITIAL_CASH  = 1_000_000  # 초기 자금 100만 원
DEFAULT_PASSWORD = "0000"  # 학생 초기 비밀번호


def get_connection():
    """DB 연결 객체를 반환합니다."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """DB 초기화: 테이블 생성 및 초기 데이터 삽입"""
    conn = get_connection()
    c = conn.cursor()

    # ── 기업 테이블 ──────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            company_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            sector        TEXT    NOT NULL,
            current_price INTEGER NOT NULL,
            prev_price    INTEGER NOT NULL
        )
    """)

    # ── 뉴스 테이블 ──────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS news (
            news_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            day        INTEGER NOT NULL,
            company_id INTEGER NOT NULL,
            content    TEXT    NOT NULL,
            FOREIGN KEY (company_id) REFERENCES companies(company_id)
        )
    """)

    # ── 학생 테이블 (password 컬럼 포함) ─────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS students (
            student_id INTEGER PRIMARY KEY,
            cash       INTEGER NOT NULL,
            password   TEXT    NOT NULL DEFAULT '0000'
        )
    """)

    # 기존 students 테이블에 password 컬럼이 없으면 추가 (마이그레이션)
    try:
        c.execute("ALTER TABLE students ADD COLUMN password TEXT NOT NULL DEFAULT '0000'")
    except sqlite3.OperationalError:
        pass  # 이미 컬럼이 존재하면 무시

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

    # ── 거래 내역 테이블 ─────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            tx_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            company_id INTEGER NOT NULL,
            tx_type    TEXT    NOT NULL,
            quantity   INTEGER NOT NULL,
            price      INTEGER NOT NULL,
            reason     TEXT    NOT NULL,
            day        INTEGER NOT NULL,
            FOREIGN KEY (student_id)  REFERENCES students(student_id),
            FOREIGN KEY (company_id)  REFERENCES companies(company_id)
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
    c.execute("SELECT COUNT(*) as cnt FROM companies")
    if c.fetchone()["cnt"] == 0:
        for name, sector, price in INITIAL_COMPANIES:
            c.execute(
                "INSERT INTO companies (name,sector,current_price,prev_price) VALUES (?,?,?,?)",
                (name, sector, price, price)
            )

    c.execute("SELECT COUNT(*) as cnt FROM students")
    if c.fetchone()["cnt"] == 0:
        for i in range(1, NUM_STUDENTS + 1):
            c.execute(
                "INSERT INTO students (student_id, cash, password) VALUES (?,?,?)",
                (i, INITIAL_CASH, DEFAULT_PASSWORD)
            )

    c.execute("SELECT value FROM game_state WHERE key='day'")
    if c.fetchone() is None:
        c.execute("INSERT INTO game_state (key,value) VALUES ('day','1')")

    conn.commit()
    conn.close()
