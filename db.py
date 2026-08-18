# db.py
# SQLite3 DB를 초기화하는 모듈
# 최초 실행 시 테이블 생성 및 초기 데이터 삽입

import sqlite3
import os

DB_PATH = "stock_game.db"

# 초기 기업 정보 (회사명, 업종, 초기 주가)
INITIAL_COMPANIES = [
    ("미래IT", "IT",   10000),
    ("글로벌무역", "무역", 8000),
    ("행복식품", "식품", 5000),
    ("클린에너지", "에너지", 12000),
]

# 학생 수
NUM_STUDENTS = 23
INITIAL_CASH = 1_000_000  # 초기 자금 100만 원


def get_connection():
    """DB 연결 객체를 반환합니다."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # 결과를 딕셔너리처럼 접근 가능하게 설정
    return conn


def init_db():
    """DB 초기화: 테이블 생성 및 초기 데이터 삽입"""
    conn = get_connection()
    c = conn.cursor()

    # ── 기업 테이블 ──────────────────────────────────────────────
    # company_id, 회사명, 업종, 현재 주가, 전일 주가
    c.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            company_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT    NOT NULL,
            sector       TEXT    NOT NULL,
            current_price INTEGER NOT NULL,
            prev_price    INTEGER NOT NULL
        )
    """)

    # ── 뉴스 테이블 ───────────────────────────────────────────────
    # 날짜(거래일), 회사별 뉴스 텍스트
    c.execute("""
        CREATE TABLE IF NOT EXISTS news (
            news_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            day          INTEGER NOT NULL,
            company_id   INTEGER NOT NULL,
            content      TEXT    NOT NULL,
            FOREIGN KEY (company_id) REFERENCES companies(company_id)
        )
    """)

    # ── 학생 테이블 ───────────────────────────────────────────────
    # 학생 번호, 잔액
    c.execute("""
        CREATE TABLE IF NOT EXISTS students (
            student_id  INTEGER PRIMARY KEY,   -- 1 ~ 23
            cash        INTEGER NOT NULL
        )
    """)

    # ── 보유 주식 테이블 ──────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS holdings (
            holding_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id  INTEGER NOT NULL,
            company_id  INTEGER NOT NULL,
            quantity    INTEGER NOT NULL DEFAULT 0,
            UNIQUE (student_id, company_id),
            FOREIGN KEY (student_id)  REFERENCES students(student_id),
            FOREIGN KEY (company_id)  REFERENCES companies(company_id)
        )
    """)

    # ── 거래 내역 테이블 ──────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            tx_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id  INTEGER NOT NULL,
            company_id  INTEGER NOT NULL,
            tx_type     TEXT    NOT NULL,   -- 'buy' or 'sell'
            quantity    INTEGER NOT NULL,
            price       INTEGER NOT NULL,
            reason      TEXT    NOT NULL,   -- 투자 이유
            day         INTEGER NOT NULL,
            FOREIGN KEY (student_id)  REFERENCES students(student_id),
            FOREIGN KEY (company_id)  REFERENCES companies(company_id)
        )
    """)

    # ── 게임 상태 테이블 ─────────────────────────────────────────
    # 현재 거래일(day) 저장
    c.execute("""
        CREATE TABLE IF NOT EXISTS game_state (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    # ── 초기 데이터 삽입 (기업이 없을 때만) ──────────────────────
    c.execute("SELECT COUNT(*) as cnt FROM companies")
    if c.fetchone()["cnt"] == 0:
        for name, sector, price in INITIAL_COMPANIES:
            c.execute(
                "INSERT INTO companies (name, sector, current_price, prev_price) VALUES (?,?,?,?)",
                (name, sector, price, price)
            )

    # 학생 초기화 (없을 때만)
    c.execute("SELECT COUNT(*) as cnt FROM students")
    if c.fetchone()["cnt"] == 0:
        for i in range(1, NUM_STUDENTS + 1):
            c.execute(
                "INSERT INTO students (student_id, cash) VALUES (?,?)",
                (i, INITIAL_CASH)
            )

    # 거래일 초기화
    c.execute("SELECT value FROM game_state WHERE key='day'")
    if c.fetchone() is None:
        c.execute("INSERT INTO game_state (key, value) VALUES ('day', '1')")

    conn.commit()
    conn.close()