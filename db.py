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
# db.py 하단에 추가할 초기화 함수들

def reset_game(reset_password: bool = False):
    """
    게임 전체 초기화 함수
    - 학생 잔액, 보유 주식, 거래 내역, 뉴스, 주가, 거래일 초기화
    - reset_password=True 이면 비밀번호도 '0000'으로 초기화
    """
    conn = get_connection()
    try:
        conn.execute("BEGIN")

        # 1. 보유 주식 전체 삭제
        conn.execute("DELETE FROM holdings")

        # 2. 거래 내역 전체 삭제
        conn.execute("DELETE FROM transactions")

        # 3. 뉴스 전체 삭제
        conn.execute("DELETE FROM news")

        # 4. 모든 학생 잔액 초기화
        if reset_password:
            # 비밀번호도 함께 초기화
            conn.execute(
                "UPDATE students SET cash=?, password=?",
                (INITIAL_CASH, DEFAULT_PASSWORD)
            )
        else:
            # 비밀번호는 유지
            conn.execute(
                "UPDATE students SET cash=?",
                (INITIAL_CASH,)
            )

        # 5. 기업 주가 초기값으로 복구
        for name, sector, price in INITIAL_COMPANIES:
            conn.execute(
                """
                UPDATE companies
                SET current_price=?, prev_price=?
                WHERE name=? AND sector=?
                """,
                (price, price, name, sector)
            )

        # 6. 거래일 1일차로 복구
        conn.execute(
            "UPDATE game_state SET value='1' WHERE key='day'"
        )

        conn.commit()
        conn.close()
        return True, "게임이 성공적으로 초기화되었습니다!"

    except Exception as e:
        conn.rollback()
        conn.close()
        return False, f"초기화 중 오류 발생: {e}"


def get_game_summary() -> dict:
    """
    초기화 전 현재 게임 현황을 요약해서 반환합니다.
    (초기화 전 확인용)
    """
    conn = get_connection()

    day = int(conn.execute(
        "SELECT value FROM game_state WHERE key='day'"
    ).fetchone()["value"])

    tx_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM transactions"
    ).fetchone()["cnt"]

    news_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM news"
    ).fetchone()["cnt"]

    active_students = conn.execute(
        """
        SELECT COUNT(DISTINCT student_id) as cnt
        FROM transactions
        """
    ).fetchone()["cnt"]

    conn.close()

    return {
        "current_day":      day,
        "tx_count":         tx_count,
        "news_count":       news_count,
        "active_students":  active_students,
    }
