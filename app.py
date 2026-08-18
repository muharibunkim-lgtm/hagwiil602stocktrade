# app.py
# 초등학생 모의 주식 거래 웹 앱 (Streamlit + SQLite3)
# 실행 방법: streamlit run app.py

import streamlit as st
import sqlite3
import pandas as pd
from db import init_db, get_connection, NUM_STUDENTS, INITIAL_CASH

# ─────────────────────────────────────────────────────────────
# 페이지 기본 설정
# ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="📈 어린이 주식 교실",
    page_icon="📈",
    layout="wide",
)

# ─────────────────────────────────────────────────────────────
# DB 초기화 (최초 1회)
# ─────────────────────────────────────────────────────────────
init_db()

TEACHER_PASSWORD = "1234"  # 교사 관리자 암호


# ══════════════════════════════════════════════════════════════
# ■ 헬퍼 함수 모음
# ══════════════════════════════════════════════════════════════

def get_current_day() -> int:
    """현재 거래일을 반환합니다."""
    conn = get_connection()
    row = conn.execute("SELECT value FROM game_state WHERE key='day'").fetchone()
    conn.close()
    return int(row["value"])


def get_companies() -> pd.DataFrame:
    """모든 기업 정보를 DataFrame으로 반환합니다."""
    conn = get_connection()
    df = pd.read_sql("SELECT * FROM companies ORDER BY company_id", conn)
    conn.close()
    return df


def get_news(day: int) -> pd.DataFrame:
    """특정 거래일의 뉴스를 DataFrame으로 반환합니다."""
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
    """학생 정보를 반환합니다."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM students WHERE student_id=?", (student_id,)
    ).fetchone()
    conn.close()
    return row


def get_holdings(student_id: int) -> pd.DataFrame:
    """학생의 보유 주식 정보를 DataFrame으로 반환합니다."""
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
    """학생의 거래 내역을 반환합니다."""
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


def buy_stock(student_id: int, company_id: int, quantity: int,
              price: int, reason: str, day: int):
    """
    주식 매수 처리:
    1. 잔액에서 금액 차감
    2. 보유 주식 수 증가
    3. 거래 내역 기록
    """
    total = quantity * price
    conn = get_connection()
    try:
        conn.execute("BEGIN")

        # 잔액 확인
        cash = conn.execute(
            "SELECT cash FROM students WHERE student_id=?", (student_id,)
        ).fetchone()["cash"]
        if cash < total:
            conn.close()
            return False, "잔액이 부족합니다."

        # 잔액 차감
        conn.execute(
            "UPDATE students SET cash = cash - ? WHERE student_id=?",
            (total, student_id)
        )

        # 보유 주식 추가 (없으면 INSERT, 있으면 UPDATE)
        conn.execute(
            """
            INSERT INTO holdings (student_id, company_id, quantity)
            VALUES (?, ?, ?)
            ON CONFLICT(student_id, company_id)
            DO UPDATE SET quantity = quantity + ?
            """,
            (student_id, company_id, quantity, quantity)
        )

        # 거래 내역 기록
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


def sell_stock(student_id: int, company_id: int, quantity: int,
               price: int, reason: str, day: int):
    """
    주식 매도 처리:
    1. 보유 수량 확인 후 차감
    2. 잔액에 금액 추가
    3. 거래 내역 기록
    """
    total = quantity * price
    conn = get_connection()
    try:
        conn.execute("BEGIN")

        # 보유 수량 확인
        row = conn.execute(
            "SELECT quantity FROM holdings WHERE student_id=? AND company_id=?",
            (student_id, company_id)
        ).fetchone()
        if row is None or row["quantity"] < quantity:
            conn.close()
            return False, "보유 주식이 부족합니다."

        # 보유 수량 차감
        conn.execute(
            """
            UPDATE holdings SET quantity = quantity - ?
            WHERE student_id=? AND company_id=?
            """,
            (quantity, student_id, company_id)
        )

        # 잔액 추가
        conn.execute(
            "UPDATE students SET cash = cash + ? WHERE student_id=?",
            (total, student_id)
        )

        # 거래 내역 기록
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
    """
    학생의 전체 자산 계산:
    - 현금 + 보유 주식 평가 금액 = 총 자산
    - 수익률 = (총 자산 / 초기 자금 - 1) * 100
    """
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
# ■ 사이드바: 로그인 선택
# ══════════════════════════════════════════════════════════════

st.sidebar.title("📈 어린이 주식 교실")
st.sidebar.markdown("---")

# 접속자 선택 목록 생성
user_options = [f"학생 {i}번" for i in range(1, NUM_STUDENTS + 1)]
user_options.append("교사 관리자")

selected_user = st.sidebar.selectbox(
    "👤 접속할 계정을 선택하세요",
    user_options
)

day = get_current_day()
st.sidebar.markdown(f"---\n📅 **현재 거래일: {day}일차**")

# ──────────────────────────────────────────────────────────────
# 교사 관리자 로그인 처리
# ──────────────────────────────────────────────────────────────
if selected_user == "교사 관리자":
    # session_state로 교사 인증 상태 관리
    if "teacher_auth" not in st.session_state:
        st.session_state["teacher_auth"] = False

    if not st.session_state["teacher_auth"]:
        st.title("🔐 교사 관리자 로그인")
        pw = st.text_input("관리자 암호를 입력하세요", type="password")
        if st.button("로그인"):
            if pw == TEACHER_PASSWORD:
                st.session_state["teacher_auth"] = True
                st.rerun()  # 페이지 새로고침으로 관리자 화면 진입
            else:
                st.error("암호가 틀렸습니다.")
        st.stop()  # 암호 입력 전 이하 코드 실행 차단


# ══════════════════════════════════════════════════════════════
# ■ 교사 관리자 화면
# ══════════════════════════════════════════════════════════════

if selected_user == "교사 관리자" and st.session_state.get("teacher_auth"):

    st.title(f"🏫 교사 관리자 대시보드 — {day}일차")

    companies_df = get_companies()

    # ── 탭 구성 ──────────────────────────────────────────────
    tab_news, tab_price, tab_rank = st.tabs([
        "📰 오늘의 뉴스 작성",
        "💹 주가 변동 설정 및 하루 경과",
        "🏆 학생 순위 & 거래 내역"
    ])

    # ── [탭1] 뉴스 작성 ────────────────────────────────────
    with tab_news:
        st.subheader(f"📰 {day}일차 뉴스 작성")
        st.info("각 기업에 대한 오늘의 뉴스를 입력하세요. 학생들이 투자 판단에 활용합니다.")

        # 이미 오늘 작성된 뉴스 확인
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
                # 모든 뉴스가 입력되었는지 확인
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

    # ── [탭2] 주가 변동 설정 & 하루 경과 ──────────────────
    with tab_price:
        st.subheader("💹 주가 변동률(%) 설정 및 하루 경과")
        st.warning(
            "⚠️ '주가 반영 및 하루 경과' 버튼을 누르면 DB의 주가가 즉시 갱신되고, "
            "거래일이 하루 증가합니다. 신중하게 사용하세요."
        )

        change_rates = {}  # { company_id: change_rate(%) }

        cols = st.columns(len(companies_df))
        for i, (_, row) in enumerate(companies_df.iterrows()):
            with cols[i]:
                # 전일 대비 등락 표시
                diff = row["current_price"] - row["prev_price"]
                diff_str = f"({'+' if diff >= 0 else ''}{diff:,}원)" if diff != 0 else ""
                st.metric(
                    label=f"{row['name']} ({row['sector']})",
                    value=f"{row['current_price']:,}원",
                    delta=diff_str if diff_str else None
                )
                change_rates[row["company_id"]] = st.number_input(
                    f"변동률 (%)",
                    min_value=-30.0, max_value=30.0,
                    value=0.0, step=0.5,
                    key=f"rate_{row['company_id']}",
                    help="음수: 하락, 양수: 상승 (최대 ±30%)"
                )

        st.markdown("---")

        if st.button("🔄 주가 반영 및 하루 경과", type="primary"):
            conn = get_connection()
            try:
                conn.execute("BEGIN")

                # 각 기업 주가 갱신
                for cid, rate in change_rates.items():
                    # 현재 주가 조회
                    current = conn.execute(
                        "SELECT current_price FROM companies WHERE company_id=?",
                        (cid,)
                    ).fetchone()["current_price"]

                    # 새 주가 계산 (최소 100원 이하로 떨어지지 않도록 설정)
                    new_price = max(100, int(current * (1 + rate / 100)))

                    conn.execute(
                        """
                        UPDATE companies
                        SET prev_price = current_price,
                            current_price = ?
                        WHERE company_id = ?
                        """,
                        (new_price, cid)
                    )

                # 거래일 하루 증가
                conn.execute(
                    "UPDATE game_state SET value = CAST(value AS INTEGER) + 1 WHERE key='day'"
                )

                conn.commit()
                conn.close()
                st.success(f"✅ 주가가 갱신되고 {day + 1}일차로 넘어갔습니다!")
                st.rerun()
            except Exception as e:
                conn.rollback()
                conn.close()
                st.error(f"오류 발생: {e}")

    # ── [탭3] 학생 순위 & 거래 내역 ───────────────────────
    with tab_rank:
        st.subheader("🏆 학생 전체 순위")

        # 모든 학생 자산 계산
        rank_data = []
        for sid in range(1, NUM_STUDENTS + 1):
            assets = calc_total_assets(sid)
            rank_data.append({
                "학생": f"{sid}번",
                "현금(원)": assets["cash"],
                "주식평가액(원)": assets["stock_value"],
                "총자산(원)": assets["total"],
                "수익률(%)": round(assets["profit_rate"], 2),
            })

        rank_df = pd.DataFrame(rank_data)
        rank_df = rank_df.sort_values("총자산(원)", ascending=False).reset_index(drop=True)
        rank_df.index = rank_df.index + 1  # 순위를 1부터 시작
        rank_df.index.name = "순위"

        # 수익률에 따라 색상 표시를 위한 스타일 함수
        def highlight_profit(val):
            if isinstance(val, float):
                color = "color: green" if val > 0 else ("color: red" if val < 0 else "")
                return color
            return ""

        st.dataframe(
            rank_df.style.applymap(highlight_profit, subset=["수익률(%)"]),
            use_container_width=True
        )

        st.markdown("---")
        st.subheader("📋 전체 투자 이유 제출 내역")

        # 모든 거래 내역 조회
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
            # 학생 번호 필터 추가
            student_filter = st.multiselect(
                "학생 번호 필터 (선택하지 않으면 전체 표시)",
                options=list(range(1, NUM_STUDENTS + 1)),
                format_func=lambda x: f"{x}번"
            )
            if student_filter:
                all_tx = all_tx[all_tx["학생번호"].isin(student_filter)]

            st.dataframe(all_tx, use_container_width=True, hide_index=True)

        # 로그아웃 버튼
        if st.sidebar.button("🚪 로그아웃"):
            st.session_state["teacher_auth"] = False
            st.rerun()


# ══════════════════════════════════════════════════════════════
# ■ 학생 화면
# ══════════════════════════════════════════════════════════════

else:
    # 학생 번호 파싱 (예: "학생 3번" → 3)
    student_id = int(selected_user.replace("학생 ", "").replace("번", ""))

    st.title(f"📈 어린이 주식 교실 — 학생 {student_id}번")

    # 자산 정보 계산
    assets = calc_total_assets(student_id)
    companies_df = get_companies()
    news_df = get_news(day)

    # ── 상단 자산 요약 카드 ──────────────────────────────────
    st.subheader("💰 나의 자산 현황")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("💵 보유 현금", f"{assets['cash']:,}원")
    col2.metric("📊 주식 평가액", f"{assets['stock_value']:,}원")
    col3.metric("🏦 총 자산", f"{assets['total']:,}원")

    profit_color = "normal"
    col4.metric(
        "📈 수익률",
        f"{assets['profit_rate']:+.2f}%",
        delta=f"{assets['total'] - INITIAL_CASH:+,}원"
    )

    st.markdown("---")

    # ── 탭 구성 ──────────────────────────────────────────────
    tab_market, tab_trade, tab_portfolio, tab_history = st.tabs([
        "🏪 주식 시장",
        "💱 매수 / 매도",
        "📂 내 포트폴리오",
        "📜 거래 내역"
    ])

    # ── [탭1] 주식 시장 (시세 + 뉴스) ──────────────────────
    with tab_market:
        st.subheader(f"📊 {day}일차 현재 주가")

        market_data = []
        for _, row in companies_df.iterrows():
            diff = row["current_price"] - row["prev_price"]
            rate = (diff / row["prev_price"] * 100) if row["prev_price"] else 0
            arrow = "🔺" if diff > 0 else ("🔻" if diff < 0 else "➡️")
            market_data.append({
                "기업명": row["name"],
                "업종": row["sector"],
                "현재 주가(원)": f"{row['current_price']:,}",
                "전일 대비": f"{arrow} {diff:+,}원 ({rate:+.1f}%)",
            })

        st.table(pd.DataFrame(market_data))

        st.markdown("---")
        st.subheader(f"📰 {day}일차 오늘의 뉴스")

        if news_df.empty:
            st.info("아직 오늘의 뉴스가 등록되지 않았습니다. 선생님께 문의하세요.")
        else:
            for _, nrow in news_df.iterrows():
                with st.expander(f"📌 [{nrow['sector']}] {nrow['company_name']}"):
                    st.write(nrow["content"])

    # ── [탭2] 매수 / 매도 ───────────────────────────────────
    with tab_trade:
        st.subheader("💱 주식 거래")
        st.info(
            "💡 **투자 이유**를 반드시 입력해야 거래 버튼이 활성화됩니다. "
            "왜 이 주식을 사거나 파는지 생각해 보세요!"
        )

        col_buy, col_sell = st.columns(2)

        # ── 매수 폼 ──────────────────────────────────────────
        with col_buy:
            st.markdown("### 🟢 주식 매수")

            # 기업 선택 (매수)
            buy_company_name = st.selectbox(
                "매수할 기업 선택",
                options=companies_df["name"].tolist(),
                key="buy_company"
            )
            buy_company = companies_df[companies_df["name"] == buy_company_name].iloc[0]
            buy_price = int(buy_company["current_price"])

            st.markdown(f"**현재 주가:** {buy_price:,}원")

            buy_qty = st.number_input(
                "매수 수량 (주)",
                min_value=1, max_value=1000, value=1, step=1,
                key="buy_qty"
            )
            buy_total = buy_qty * buy_price
            st.markdown(f"**총 매수 금액:** {buy_total:,}원")

            if buy_total > assets["cash"]:
                st.error(f"잔액 부족! (보유 현금: {assets['cash']:,}원)")

            buy_reason = st.text_area(
                "✏️ 투자 이유를 입력하세요 (필수)",
                placeholder="예) 오늘 뉴스에서 새로운 제품을 출시한다고 해서 주가가 오를 것 같아요.",
                height=100,
                key="buy_reason"
            )

            # 투자 이유 입력 여부 및 잔액으로 버튼 활성화 제어
            buy_disabled = (buy_reason.strip() == "") or (buy_total > assets["cash"])
            if st.button(
                "✅ 매수 실행",
                type="primary",
                disabled=buy_disabled,
                key="btn_buy"
            ):
                ok, msg = buy_stock(
                    student_id=student_id,
                    company_id=int(buy_company["company_id"]),
                    quantity=buy_qty,
                    price=buy_price,
                    reason=buy_reason.strip(),
                    day=day
                )
                if ok:
                    st.success(f"🎉 {msg} ({buy_company_name} {buy_qty}주 매수)")
                    st.rerun()
                else:
                    st.error(msg)

            if buy_reason.strip() == "":
                st.caption("⚠️ 투자 이유를 입력하면 매수 버튼이 활성화됩니다.")

        # ── 매도 폼 ──────────────────────────────────────────
        with col_sell:
            st.markdown("### 🔴 주식 매도")

            holdings_df = get_holdings(student_id)

            if holdings_df.empty:
                st.info("보유 중인 주식이 없습니다.")
            else:
                sell_company_name = st.selectbox(
                    "매도할 기업 선택",
                    options=holdings_df["name"].tolist(),
                    key="sell_company"
                )
                sell_holding = holdings_df[
                    holdings_df["name"] == sell_company_name
                ].iloc[0]
                sell_price = int(sell_holding["current_price"])
                max_qty = int(sell_holding["quantity"])

                st.markdown(f"**현재 주가:** {sell_price:,}원")
                st.markdown(f"**보유 수량:** {max_qty:,}주")

                sell_qty = st.number_input(
                    "매도 수량 (주)",
                    min_value=1, max_value=max_qty, value=1, step=1,
                    key="sell_qty"
                )
                sell_total = sell_qty * sell_price
                st.markdown(f"**총 매도 금액:** {sell_total:,}원")

                sell_reason = st.text_area(
                    "✏️ 매도 이유를 입력하세요 (필수)",
                    placeholder="예) 주가가 많이 올라서 지금이 팔기 좋은 것 같아요.",
                    height=100,
                    key="sell_reason"
                )

                sell_disabled = sell_reason.strip() == ""
                if st.button(
                    "✅ 매도 실행",
                    type="primary",
                    disabled=sell_disabled,
                    key="btn_sell"
                ):
                    ok, msg = sell_stock(
                        student_id=student_id,
                        company_id=int(sell_holding["company_id"]),
                        quantity=sell_qty,
                        price=sell_price,
                        reason=sell_reason.strip(),
                        day=day
                    )
                    if ok:
                        st.success(f"🎉 {msg} ({sell_company_name} {sell_qty}주 매도)")
                        st.rerun()
                    else:
                        st.error(msg)

                if sell_reason.strip() == "":
                    st.caption("⚠️ 매도 이유를 입력하면 매도 버튼이 활성화됩니다.")

    # ── [탭3] 내 포트폴리오 ─────────────────────────────────
    with tab_portfolio:
        st.subheader("📂 내 포트폴리오")

        holdings_df = get_holdings(student_id)

        if holdings_df.empty:
            st.info("아직 보유 중인 주식이 없습니다. 주식을 매수해 보세요!")
        else:
            portfolio_data = []
            for _, row in holdings_df.iterrows():
                portfolio_data.append({
                    "기업명": row["name"],
                    "업종": row["sector"],
                    "보유 수량(주)": int(row["quantity"]),
                    "현재 주가(원)": f"{int(row['current_price']):,}",
                    "평가 금액(원)": f"{int(row['eval_amount']):,}",
                })
            st.dataframe(
                pd.DataFrame(portfolio_data),
                use_container_width=True,
                hide_index=True
            )

        st.markdown("---")
        st.subheader("💡 자산 구성 요약")

        summary_cols = st.columns(3)
        summary_cols[0].metric(
            "💵 현금",
            f"{assets['cash']:,}원",
            help="주식을 사지 않고 보유 중인 현금"
        )
        summary_cols[1].metric(
            "📊 주식 평가액",
            f"{assets['stock_value']:,}원",
            help="현재 주가 기준 보유 주식의 총 가치"
        )
        summary_cols[2].metric(
            "🏦 총 자산",
            f"{assets['total']:,}원",
            delta=f"수익률 {assets['profit_rate']:+.2f}%"
        )

    # ── [탭4] 거래 내역 ────────────────────────────────────
    with tab_history:
        st.subheader("📜 나의 거래 내역")

        tx_df = get_transactions(student_id)

        if tx_df.empty:
            st.info("아직 거래 내역이 없습니다.")
        else:
            # 컬럼명 한글화 및 거래 유형 변환
            tx_df["tx_type"] = tx_df["tx_type"].map({"buy": "🟢 매수", "sell": "🔴 매도"})
            tx_df = tx_df.rename(columns={
                "day": "거래일",
                "company_name": "기업명",
                "tx_type": "거래유형",
                "quantity": "수량(주)",
                "price": "단가(원)",
                "total_amount": "거래금액(원)",
                "reason": "투자이유",
            })
            st.dataframe(tx_df, use_container_width=True, hide_index=True)