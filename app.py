# app.py
# 초등학생 모의 주식 거래 웹 앱
# 수정 내용:
#   1. applymap → map 으로 변경 (pandas 최신 버전 호환)
#   2. 학생 개인 비밀번호 로그인 기능 추가
#   3. 교사 관리자 → 비밀번호 관리 기능 추가

import streamlit as st
import sqlite3
import pandas as pd
from db import (
    init_db, get_connection,
    NUM_STUDENTS, INITIAL_CASH,
    reset_game, get_game_summary      # ← 이 두 줄 추가
)

# ─────────────────────────────────────────────────────────────
# 페이지 기본 설정
# ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="📈 어린이 주식 교실",
    page_icon="📈",
    layout="wide",
)

init_db()

TEACHER_PASSWORD = "1234"


# ══════════════════════════════════════════════════════════════
# ■ 헬퍼 함수 모음
# ══════════════════════════════════════════════════════════════

def get_current_day() -> int:
    conn = get_connection()
    row = conn.execute("SELECT value FROM game_state WHERE key='day'").fetchone()
    conn.close()
    return int(row["value"])


def get_companies() -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql("SELECT * FROM companies ORDER BY company_id", conn)
    conn.close()
    return df


def get_news(day: int) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql(
        """
        SELECT n.content, c.name AS company_name, c.sector
        FROM news n
        JOIN companies c ON n.company_id = c.company_id
        WHERE n.day = ?
        ORDER BY c.company_id
        """,
        conn, params=(day,)
    )
    conn.close()
    return df


def get_student(student_id: int) -> sqlite3.Row:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM students WHERE student_id=?", (student_id,)
    ).fetchone()
    conn.close()
    return row


def verify_student_password(student_id: int, password: str) -> bool:
    """학생 비밀번호를 검증합니다."""
    conn = get_connection()
    row = conn.execute(
        "SELECT password FROM students WHERE student_id=?", (student_id,)
    ).fetchone()
    conn.close()
    if row is None:
        return False
    return row["password"] == password


def update_student_password(student_id: int, new_password: str):
    """학생 비밀번호를 변경합니다."""
    conn = get_connection()
    conn.execute(
        "UPDATE students SET password=? WHERE student_id=?",
        (new_password, student_id)
    )
    conn.commit()
    conn.close()


def reset_all_passwords(new_password: str):
    """전체 학생 비밀번호를 일괄 초기화합니다."""
    conn = get_connection()
    conn.execute("UPDATE students SET password=?", (new_password,))
    conn.commit()
    conn.close()


def get_all_passwords() -> pd.DataFrame:
    """전체 학생 비밀번호 목록을 반환합니다."""
    conn = get_connection()
    df = pd.read_sql(
        "SELECT student_id, password FROM students ORDER BY student_id", conn
    )
    conn.close()
    return df


def get_holdings(student_id: int) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql(
        """
        SELECT h.company_id, c.name, c.sector,
               h.quantity, c.current_price,
               (h.quantity * c.current_price) AS eval_amount
        FROM holdings h
        JOIN companies c ON h.company_id = c.company_id
        WHERE h.student_id = ? AND h.quantity > 0
        ORDER BY c.company_id
        """,
        conn, params=(student_id,)
    )
    conn.close()
    return df


def get_transactions(student_id: int) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql(
        """
        SELECT t.day, c.name AS company_name, t.tx_type,
               t.quantity, t.price, t.reason,
               (t.quantity * t.price) AS total_amount
        FROM transactions t
        JOIN companies c ON t.company_id = c.company_id
        WHERE t.student_id = ?
        ORDER BY t.tx_id DESC
        """,
        conn, params=(student_id,)
    )
    conn.close()
    return df


def buy_stock(student_id, company_id, quantity, price, reason, day):
    total = quantity * price
    conn = get_connection()
    try:
        conn.execute("BEGIN")
        cash = conn.execute(
            "SELECT cash FROM students WHERE student_id=?", (student_id,)
        ).fetchone()["cash"]
        if cash < total:
            conn.close()
            return False, "잔액이 부족합니다."
        conn.execute(
            "UPDATE students SET cash = cash - ? WHERE student_id=?",
            (total, student_id)
        )
        conn.execute(
            """
            INSERT INTO holdings (student_id, company_id, quantity)
            VALUES (?, ?, ?)
            ON CONFLICT(student_id, company_id)
            DO UPDATE SET quantity = quantity + ?
            """,
            (student_id, company_id, quantity, quantity)
        )
        conn.execute(
            """
            INSERT INTO transactions
            (student_id, company_id, tx_type, quantity, price, reason, day)
            VALUES (?,?,?,?,?,?,?)
            """,
            (student_id, company_id, "buy", quantity, price, reason, day)
        )
        conn.commit()
        conn.close()
        return True, "매수 완료!"
    except Exception as e:
        conn.rollback()
        conn.close()
        return False, str(e)


def sell_stock(student_id, company_id, quantity, price, reason, day):
    total = quantity * price
    conn = get_connection()
    try:
        conn.execute("BEGIN")
        row = conn.execute(
            "SELECT quantity FROM holdings WHERE student_id=? AND company_id=?",
            (student_id, company_id)
        ).fetchone()
        if row is None or row["quantity"] < quantity:
            conn.close()
            return False, "보유 주식이 부족합니다."
        conn.execute(
            "UPDATE holdings SET quantity = quantity - ? WHERE student_id=? AND company_id=?",
            (quantity, student_id, company_id)
        )
        conn.execute(
            "UPDATE students SET cash = cash + ? WHERE student_id=?",
            (total, student_id)
        )
        conn.execute(
            """
            INSERT INTO transactions
            (student_id, company_id, tx_type, quantity, price, reason, day)
            VALUES (?,?,?,?,?,?,?)
            """,
            (student_id, company_id, "sell", quantity, price, reason, day)
        )
        conn.commit()
        conn.close()
        return True, "매도 완료!"
    except Exception as e:
        conn.rollback()
        conn.close()
        return False, str(e)


def calc_total_assets(student_id: int) -> dict:
    conn = get_connection()
    student = conn.execute(
        "SELECT cash FROM students WHERE student_id=?", (student_id,)
    ).fetchone()
    cash = student["cash"] if student else 0
    row = conn.execute(
        """
        SELECT COALESCE(SUM(h.quantity * c.current_price), 0) AS stock_value
        FROM holdings h
        JOIN companies c ON h.company_id = c.company_id
        WHERE h.student_id = ?
        """,
        (student_id,)
    ).fetchone()
    conn.close()
    stock_value = row["stock_value"] if row else 0
    total = cash + stock_value
    profit_rate = (total / INITIAL_CASH - 1) * 100
    return {
        "cash": cash,
        "stock_value": stock_value,
        "total": total,
        "profit_rate": profit_rate,
    }


# ══════════════════════════════════════════════════════════════
# ■ Session State 초기화
# ══════════════════════════════════════════════════════════════

# 학생 로그인 상태 관리
if "student_logged_in" not in st.session_state:
    st.session_state["student_logged_in"] = False   # 로그인 여부
if "logged_student_id" not in st.session_state:
    st.session_state["logged_student_id"] = None    # 로그인된 학생 번호
if "teacher_auth" not in st.session_state:
    st.session_state["teacher_auth"] = False        # 교사 인증 여부


# ══════════════════════════════════════════════════════════════
# ■ 사이드바: 계정 선택
# ══════════════════════════════════════════════════════════════

st.sidebar.title("📈 어린이 주식 교실")
st.sidebar.markdown("---")

user_options = [f"학생 {i}번" for i in range(1, NUM_STUDENTS + 1)]
user_options.append("교사 관리자")

selected_user = st.sidebar.selectbox(
    "👤 접속할 계정을 선택하세요",
    user_options,
    # 로그인된 학생이 있으면 해당 번호를 기본으로 표시
    index=(st.session_state["logged_student_id"] - 1)
    if st.session_state["logged_student_id"] else 0
)

day = get_current_day()
st.sidebar.markdown(f"---\n📅 **현재 거래일: {day}일차**")

# 다른 계정 선택 시 로그인 상태 초기화
if selected_user != "교사 관리자":
    sel_id = int(selected_user.replace("학생 ", "").replace("번", ""))
    if st.session_state["logged_student_id"] != sel_id:
        # 다른 번호 선택 시 로그인 초기화
        st.session_state["student_logged_in"] = False
        st.session_state["logged_student_id"] = None


# ══════════════════════════════════════════════════════════════
# ■ 교사 관리자 로그인 처리
# ══════════════════════════════════════════════════════════════

if selected_user == "교사 관리자":
    # 학생 로그인 상태 초기화
    st.session_state["student_logged_in"] = False
    st.session_state["logged_student_id"] = None

    if not st.session_state["teacher_auth"]:
        st.title("🔐 교사 관리자 로그인")
        pw = st.text_input("관리자 암호를 입력하세요", type="password")
        if st.button("로그인"):
            if pw == TEACHER_PASSWORD:
                st.session_state["teacher_auth"] = True
                st.rerun()
            else:
                st.error("암호가 틀렸습니다.")
        st.stop()


# ══════════════════════════════════════════════════════════════
# ■ 교사 관리자 화면
# ══════════════════════════════════════════════════════════════

if selected_user == "교사 관리자" and st.session_state.get("teacher_auth"):

    st.title(f"🏫 교사 관리자 대시보드 — {day}일차")
    companies_df = get_companies()

    # 탭 구성 (비밀번호 관리 탭 추가)
    tab_news, tab_price, tab_rank, tab_pw, tab_reset = st.tabs([
    "📰 오늘의 뉴스 작성",
    "💹 주가 변동 설정 및 하루 경과",
    "🏆 학생 순위 & 거래 내역",
    "🔑 비밀번호 관리",
    "🔄 게임 초기화",              # ← 새로 추가된 탭
])

    # ── [탭1] 뉴스 작성 ─────────────────────────────────────
    with tab_news:
        st.subheader(f"📰 {day}일차 뉴스 작성")
        st.info("각 기업에 대한 오늘의 뉴스를 입력하세요.")

        existing_news = get_news(day)
        if not existing_news.empty:
            st.success("✅ 오늘의 뉴스가 이미 등록되어 있습니다.")
            st.dataframe(
                existing_news.rename(columns={
                    "company_name": "기업명",
                    "sector": "업종",
                    "content": "뉴스 내용"
                }),
                use_container_width=True, hide_index=True
            )
        else:
            news_inputs = {}
            for _, row in companies_df.iterrows():
                news_inputs[row["company_id"]] = st.text_area(
                    f"📌 [{row['sector']}] {row['name']}",
                    placeholder=f"예) {row['name']} 관련 최신 뉴스를 입력하세요...",
                    height=80,
                    key=f"news_{row['company_id']}"
                )
            if st.button("📨 뉴스 등록", type="primary"):
                if any(v.strip() == "" for v in news_inputs.values()):
                    st.warning("모든 기업의 뉴스를 입력해 주세요.")
                else:
                    conn = get_connection()
                    for cid, content in news_inputs.items():
                        conn.execute(
                            "INSERT INTO news (day, company_id, content) VALUES (?,?,?)",
                            (day, cid, content.strip())
                        )
                    conn.commit()
                    conn.close()
                    st.success("뉴스가 등록되었습니다!")
                    st.rerun()

    # ── [탭2] 주가 변동 설정 ────────────────────────────────
    with tab_price:
        st.subheader("💹 주가 변동률(%) 설정 및 하루 경과")
        st.warning("⚠️ '주가 반영 및 하루 경과' 버튼은 한 번 누르면 되돌릴 수 없습니다.")

        change_rates = {}
        cols = st.columns(len(companies_df))
        for i, (_, row) in enumerate(companies_df.iterrows()):
            with cols[i]:
                diff = row["current_price"] - row["prev_price"]
                diff_str = f"({'+' if diff >= 0 else ''}{diff:,}원)"
                st.metric(
                    label=f"{row['name']} ({row['sector']})",
                    value=f"{row['current_price']:,}원",
                    delta=diff_str if diff != 0 else None
                )
                change_rates[row["company_id"]] = st.number_input(
                    "변동률 (%)",
                    min_value=-30.0, max_value=30.0,
                    value=0.0, step=0.5,
                    key=f"rate_{row['company_id']}"
                )

        st.markdown("---")
        if st.button("🔄 주가 반영 및 하루 경과", type="primary"):
            conn = get_connection()
            try:
                conn.execute("BEGIN")
                for cid, rate in change_rates.items():
                    current = conn.execute(
                        "SELECT current_price FROM companies WHERE company_id=?", (cid,)
                    ).fetchone()["current_price"]
                    new_price = max(100, int(current * (1 + rate / 100)))
                    conn.execute(
                        "UPDATE companies SET prev_price=current_price, current_price=? WHERE company_id=?",
                        (new_price, cid)
                    )
                conn.execute(
                    "UPDATE game_state SET value=CAST(value AS INTEGER)+1 WHERE key='day'"
                )
                conn.commit()
                conn.close()
                st.success(f"✅ {day + 1}일차로 넘어갔습니다!")
                st.rerun()
            except Exception as e:
                conn.rollback()
                conn.close()
                st.error(f"오류 발생: {e}")

    # ── [탭3] 학생 순위 & 거래 내역 ─────────────────────────
    with tab_rank:
        st.subheader("🏆 학생 전체 순위")

        rank_data = []
        for sid in range(1, NUM_STUDENTS + 1):
            assets = calc_total_assets(sid)
            rank_data.append({
                "학생":       f"{sid}번",
                "현금(원)":   assets["cash"],
                "주식평가액(원)": assets["stock_value"],
                "총자산(원)": assets["total"],
                "수익률(%)":  round(assets["profit_rate"], 2),
            })

        rank_df = pd.DataFrame(rank_data)
        rank_df = rank_df.sort_values("총자산(원)", ascending=False).reset_index(drop=True)
        rank_df.index = rank_df.index + 1
        rank_df.index.name = "순위"

        # ✅ 수정: applymap → map (pandas 최신 버전 호환)
        def highlight_profit(val):
            """수익률 값에 따라 색상을 반환합니다."""
            if isinstance(val, (int, float)):
                if val > 0:
                    return "color: green; font-weight: bold"
                elif val < 0:
                    return "color: red; font-weight: bold"
            return ""

        styled_df = rank_df.style.map(
            highlight_profit, subset=["수익률(%)"]
        )
        st.dataframe(styled_df, use_container_width=True)

        st.markdown("---")
        st.subheader("📋 전체 투자 이유 제출 내역")

        conn = get_connection()
        all_tx = pd.read_sql(
            """
            SELECT t.day AS 거래일,
                   t.student_id AS 학생번호,
                   c.name AS 기업명,
                   CASE t.tx_type WHEN 'buy' THEN '매수' ELSE '매도' END AS 거래유형,
                   t.quantity AS 수량,
                   t.price AS 단가,
                   (t.quantity * t.price) AS 거래금액,
                   t.reason AS 투자이유
            FROM transactions t
            JOIN companies c ON t.company_id = c.company_id
            ORDER BY t.tx_id DESC
            """,
            conn
        )
        conn.close()

        if all_tx.empty:
            st.info("아직 거래 내역이 없습니다.")
        else:
            student_filter = st.multiselect(
                "학생 번호 필터",
                options=list(range(1, NUM_STUDENTS + 1)),
                format_func=lambda x: f"{x}번"
            )
            if student_filter:
                all_tx = all_tx[all_tx["학생번호"].isin(student_filter)]
            st.dataframe(all_tx, use_container_width=True, hide_index=True)

    # ── [탭4] 비밀번호 관리 ─────────────────────────────────
    with tab_pw:
        st.subheader("🔑 학생 비밀번호 관리")
        st.info(
            "초기 비밀번호는 **0000** 입니다.  \n"
            "학생 개인 비밀번호를 설정하거나 일괄 초기화할 수 있습니다."
        )

        # ── 전체 비밀번호 현황 ────────────────────────────────
        pw_df = get_all_passwords()
        pw_df.columns = ["학생번호", "현재 비밀번호"]
        pw_df["학생번호"] = pw_df["학생번호"].apply(lambda x: f"{x}번")
        st.dataframe(pw_df, use_container_width=True, hide_index=True)

        st.markdown("---")

        col_single, col_bulk = st.columns(2)
            # ── [탭5] 게임 전체 초기화 ──────────────────────────────
    with tab_reset:
        st.subheader("🔄 게임 전체 초기화")

        # ── 현재 게임 현황 표시 ───────────────────────────────
        st.markdown("### 📊 현재 게임 현황")
        st.info("초기화 전 현재 진행 상황을 확인하세요.")

        summary = get_game_summary()

        s_col1, s_col2, s_col3, s_col4 = st.columns(4)
        s_col1.metric("📅 현재 거래일",   f"{summary['current_day']}일차")
        s_col2.metric("💱 총 거래 횟수",  f"{summary['tx_count']}건")
        s_col3.metric("📰 등록된 뉴스",   f"{summary['news_count']}건")
        s_col4.metric("👥 거래 참여 학생", f"{summary['active_students']}명")

        st.markdown("---")

        # ── 초기화 옵션 선택 ──────────────────────────────────
        st.markdown("### ⚙️ 초기화 옵션")

        reset_pw_also = st.checkbox(
            "🔑 비밀번호도 함께 초기화 (전체 학생 비밀번호를 '0000'으로 변경)",
            value=False
        )

        st.markdown("---")

        # ── 초기화 후 상태 미리보기 ───────────────────────────
        st.markdown("### 🔍 초기화 후 상태 미리보기")

        preview_data = {
            "항목":       ["거래일", "학생 잔액", "보유 주식",
                          "거래 내역", "뉴스", "주가", "비밀번호"],
            "현재 상태":  [
                f"{summary['current_day']}일차",
                "각자 다름",
                "각자 보유 중",
                f"{summary['tx_count']}건",
                f"{summary['news_count']}건",
                "각자 다름",
                "각자 다름"
            ],
            "초기화 후":  [
                "1일차",
                "1,000,000원",
                "전량 삭제",
                "전체 삭제",
                "전체 삭제",
                "초기 주가로 복구",
                "0000으로 초기화" if reset_pw_also else "유지 (변경 없음)"
            ],
        }

        st.table(pd.DataFrame(preview_data))

        st.markdown("---")

        # ── 초기화 실행 (2단계 확인) ──────────────────────────
        st.markdown("### ⚠️ 초기화 실행")
        st.error(
            "🚨 **주의:** 초기화는 되돌릴 수 없습니다!  \n"
            "모든 학생의 거래 내역, 보유 주식, 잔액이 초기화됩니다.  \n"
            "반드시 데이터를 먼저 저장(캡처/엑셀 다운로드) 후 진행하세요."
        )

        # 2단계 확인: 체크박스 + 버튼
        confirm_check = st.checkbox(
            "✅ 위 내용을 확인했으며, 게임을 초기화하겠습니다.",
            value=False,
            key="confirm_reset"
        )

        # 확인 체크박스가 체크되어야만 버튼 활성화
        if st.button(
            "🔄 게임 전체 초기화 실행",
            type="primary",
            disabled=not confirm_check,
            key="btn_reset"
        ):
            # 3단계: 최종 재확인 (session_state 활용)
            st.session_state["reset_requested"] = True

        # 최종 재확인 단계
        if st.session_state.get("reset_requested", False):
            st.warning("⚠️ 정말로 초기화하시겠습니까? 아래 버튼을 눌러 최종 확인하세요.")

            final_col1, final_col2 = st.columns(2)

            with final_col1:
                if st.button(
                    "✅ 네, 초기화합니다",
                    type="primary",
                    key="btn_final_yes"
                ):
                    # 초기화 실행
                    ok, msg = reset_game(reset_password=reset_pw_also)
                    if ok:
                        st.session_state["reset_requested"] = False
                        st.success(f"🎉 {msg}")
                        st.balloons()   # 초기화 완료 축하 애니메이션
                        st.rerun()
                    else:
                        st.error(msg)

            with final_col2:
                if st.button(
                    "❌ 아니요, 취소합니다",
                    key="btn_final_no"
                ):
                    st.session_state["reset_requested"] = False
                    st.info("초기화가 취소되었습니다.")
                    st.rerun()

        # ── 개별 비밀번호 변경 ────────────────────────────────
        with col_single:
            st.markdown("### 👤 개별 비밀번호 변경")
            target_student = st.selectbox(
                "학생 선택",
                options=list(range(1, NUM_STUDENTS + 1)),
                format_func=lambda x: f"{x}번",
                key="pw_target"
            )
            new_pw_single = st.text_input(
                "새 비밀번호 입력",
                max_chars=20,
                key="new_pw_single",
                placeholder="새 비밀번호 입력"
            )
            if st.button("✅ 비밀번호 변경", key="btn_pw_single"):
                if new_pw_single.strip() == "":
                    st.warning("비밀번호를 입력해 주세요.")
                else:
                    update_student_password(target_student, new_pw_single.strip())
                    st.success(f"✅ {target_student}번 학생 비밀번호가 변경되었습니다!")
                    st.rerun()

        # ── 전체 일괄 초기화 ──────────────────────────────────
        with col_bulk:
            st.markdown("### 🔄 전체 일괄 초기화")
            new_pw_bulk = st.text_input(
                "일괄 초기화할 비밀번호",
                value="0000",
                max_chars=20,
                key="new_pw_bulk"
            )
            st.warning("⚠️ 전체 학생의 비밀번호가 동일하게 변경됩니다.")
            if st.button("🔄 전체 초기화", type="primary", key="btn_pw_bulk"):
                if new_pw_bulk.strip() == "":
                    st.warning("초기화할 비밀번호를 입력해 주세요.")
                else:
                    reset_all_passwords(new_pw_bulk.strip())
                    st.success(f"✅ 전체 비밀번호가 '{new_pw_bulk}'(으)로 초기화되었습니다!")
                    st.rerun()

    # 로그아웃 버튼
    if st.sidebar.button("🚪 로그아웃"):
        st.session_state["teacher_auth"] = False
        st.rerun()


# ══════════════════════════════════════════════════════════════
# ■ 학생 로그인 화면
# ══════════════════════════════════════════════════════════════

elif selected_user != "교사 관리자":
    student_id = int(selected_user.replace("학생 ", "").replace("번", ""))

    # ── 비밀번호 입력 (로그인 전) ────────────────────────────
    if not st.session_state["student_logged_in"]:
        st.title(f"🔐 학생 {student_id}번 로그인")
        st.markdown(
            f"**{student_id}번** 학생의 비밀번호를 입력하세요.  \n"
            "초기 비밀번호는 선생님께 문의하세요."
        )

        input_pw = st.text_input(
            "🔑 비밀번호",
            type="password",
            placeholder="비밀번호를 입력하세요"
        )

        if st.button("✅ 로그인", type="primary"):
            if verify_student_password(student_id, input_pw):
                st.session_state["student_logged_in"] = True
                st.session_state["logged_student_id"] = student_id
                st.rerun()
            else:
                st.error("❌ 비밀번호가 틀렸습니다. 선생님께 문의하세요.")
        st.stop()

    # ── 로그인 완료 후 학생 화면 ─────────────────────────────
    assets = calc_total_assets(student_id)
    companies_df = get_companies()
    news_df = get_news(day)

    st.title(f"📈 어린이 주식 교실 — 학생 {student_id}번")

    # 상단 자산 카드
    st.subheader("💰 나의 자산 현황")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("💵 보유 현금",   f"{assets['cash']:,}원")
    col2.metric("📊 주식 평가액", f"{assets['stock_value']:,}원")
    col3.metric("🏦 총 자산",    f"{assets['total']:,}원")
    col4.metric(
        "📈 수익률",
        f"{assets['profit_rate']:+.2f}%",
        delta=f"{assets['total'] - INITIAL_CASH:+,}원"
    )

    # 사이드바 로그아웃 버튼
    if st.sidebar.button("🚪 로그아웃"):
        st.session_state["student_logged_in"] = False
        st.session_state["logged_student_id"] = None
        st.rerun()

    st.markdown("---")

    tab_market, tab_trade, tab_portfolio, tab_history = st.tabs([
        "🏪 주식 시장",
        "💱 매수 / 매도",
        "📂 내 포트폴리오",
        "📜 거래 내역"
    ])

    # ── [탭1] 주식 시장 ──────────────────────────────────────
    with tab_market:
        st.subheader(f"📊 {day}일차 현재 주가")
        market_data = []
        for _, row in companies_df.iterrows():
            diff = row["current_price"] - row["prev_price"]
            rate = (diff / row["prev_price"] * 100) if row["prev_price"] else 0
            arrow = "🔺" if diff > 0 else ("🔻" if diff < 0 else "➡️")
            market_data.append({
                "기업명":    row["name"],
                "업종":      row["sector"],
                "현재 주가(원)": f"{row['current_price']:,}",
                "전일 대비": f"{arrow} {diff:+,}원 ({rate:+.1f}%)",
            })
        st.table(pd.DataFrame(market_data))

        st.markdown("---")
        st.subheader(f"📰 {day}일차 오늘의 뉴스")
        if news_df.empty:
            st.info("아직 오늘의 뉴스가 등록되지 않았습니다.")
        else:
            for _, nrow in news_df.iterrows():
                with st.expander(f"📌 [{nrow['sector']}] {nrow['company_name']}"):
                    st.write(nrow["content"])

    # ── [탭2] 매수 / 매도 ────────────────────────────────────
    with tab_trade:
        st.subheader("💱 주식 거래")
        st.info("💡 투자 이유를 반드시 입력해야 거래 버튼이 활성화됩니다!")

        col_buy, col_sell = st.columns(2)

        with col_buy:
            st.markdown("### 🟢 주식 매수")
            buy_company_name = st.selectbox(
                "매수할 기업 선택", companies_df["name"].tolist(), key="buy_company"
            )
            buy_company = companies_df[companies_df["name"] == buy_company_name].iloc[0]
            buy_price = int(buy_company["current_price"])
            st.markdown(f"**현재 주가:** {buy_price:,}원")

            buy_qty = st.number_input(
                "매수 수량 (주)", min_value=1, max_value=1000, value=1, step=1, key="buy_qty"
            )
            buy_total = buy_qty * buy_price
            st.markdown(f"**총 매수 금액:** {buy_total:,}원")

            if buy_total > assets["cash"]:
                st.error(f"잔액 부족! (보유 현금: {assets['cash']:,}원)")

            buy_reason = st.text_area(
                "✏️ 투자 이유 (필수)",
                placeholder="예) 오늘 뉴스에서 신제품 출시 소식이 있어서 주가가 오를 것 같아요.",
                height=100, key="buy_reason"
            )
            buy_disabled = (buy_reason.strip() == "") or (buy_total > assets["cash"])
            if st.button("✅ 매수 실행", type="primary", disabled=buy_disabled, key="btn_buy"):
                ok, msg = buy_stock(
                    student_id, int(buy_company["company_id"]),
                    buy_qty, buy_price, buy_reason.strip(), day
                )
                if ok:
                    st.success(f"🎉 {buy_company_name} {buy_qty}주 매수 완료!")
                    st.rerun()
                else:
                    st.error(msg)
            if buy_reason.strip() == "":
                st.caption("⚠️ 투자 이유를 입력하면 버튼이 활성화됩니다.")

        with col_sell:
            st.markdown("### 🔴 주식 매도")
            holdings_df = get_holdings(student_id)
            if holdings_df.empty:
                st.info("보유 중인 주식이 없습니다.")
            else:
                sell_company_name = st.selectbox(
                    "매도할 기업 선택", holdings_df["name"].tolist(), key="sell_company"
                )
                sell_holding = holdings_df[holdings_df["name"] == sell_company_name].iloc[0]
                sell_price = int(sell_holding["current_price"])
                max_qty = int(sell_holding["quantity"])

                st.markdown(f"**현재 주가:** {sell_price:,}원")
                st.markdown(f"**보유 수량:** {max_qty:,}주")

                sell_qty = st.number_input(
                    "매도 수량 (주)", min_value=1, max_value=max_qty, value=1, step=1, key="sell_qty"
                )
                sell_total = sell_qty * sell_price
                st.markdown(f"**총 매도 금액:** {sell_total:,}원")

                sell_reason = st.text_area(
                    "✏️ 매도 이유 (필수)",
                    placeholder="예) 주가가 많이 올라서 지금이 팔기 좋은 타이밍 같아요.",
                    height=100, key="sell_reason"
                )
                sell_disabled = sell_reason.strip() == ""
                if st.button("✅ 매도 실행", type="primary", disabled=sell_disabled, key="btn_sell"):
                    ok, msg = sell_stock(
                        student_id, int(sell_holding["company_id"]),
                        sell_qty, sell_price, sell_reason.strip(), day
                    )
                    if ok:
                        st.success(f"🎉 {sell_company_name} {sell_qty}주 매도 완료!")
                        st.rerun()
                    else:
                        st.error(msg)
                if sell_reason.strip() == "":
                    st.caption("⚠️ 매도 이유를 입력하면 버튼이 활성화됩니다.")

    # ── [탭3] 내 포트폴리오 ──────────────────────────────────
    with tab_portfolio:
        st.subheader("📂 내 포트폴리오")
        holdings_df = get_holdings(student_id)
        if holdings_df.empty:
            st.info("아직 보유 중인 주식이 없습니다.")
        else:
            portfolio_data = [{
                "기업명":        row["name"],
                "업종":          row["sector"],
                "보유 수량(주)": int(row["quantity"]),
                "현재 주가(원)": f"{int(row['current_price']):,}",
                "평가 금액(원)": f"{int(row['eval_amount']):,}",
            } for _, row in holdings_df.iterrows()]
            st.dataframe(pd.DataFrame(portfolio_data), use_container_width=True, hide_index=True)

        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        c1.metric("💵 현금",      f"{assets['cash']:,}원")
        c2.metric("📊 주식 평가액", f"{assets['stock_value']:,}원")
        c3.metric("🏦 총 자산",   f"{assets['total']:,}원",
                  delta=f"수익률 {assets['profit_rate']:+.2f}%")

    # ── [탭4] 거래 내역 ──────────────────────────────────────
    with tab_history:
        st.subheader("📜 나의 거래 내역")
        tx_df = get_transactions(student_id)
        if tx_df.empty:
            st.info("아직 거래 내역이 없습니다.")
        else:
            tx_df["tx_type"] = tx_df["tx_type"].map({"buy": "🟢 매수", "sell": "🔴 매도"})
            tx_df = tx_df.rename(columns={
                "day":          "거래일",
                "company_name": "기업명",
                "tx_type":      "거래유형",
                "quantity":     "수량(주)",
                "price":        "단가(원)",
                "total_amount": "거래금액(원)",
                "reason":       "투자이유",
            })
            st.dataframe(tx_df, use_container_width=True, hide_index=True)
