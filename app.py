# app.py

import streamlit as st
import pandas as pd
from db import (
    init_db,
    get_connection,
    get_setting,
    set_setting,
    verify_student_password,
    update_student_password,
    reset_all_passwords,
    get_all_passwords,
    reset_game,
    get_game_summary,
    NUM_STUDENTS,
    INITIAL_CASH,
    INITIAL_GOLD_PRICE,
    INITIAL_BTC_PRICE,
)

st.set_page_config(
    page_title="💰 어린이 경제 교실",
    page_icon="💰",
    layout="wide",
)
init_db()

TEACHER_PASSWORD = "1234"


# ══════════════════════════════════════════════════════════════
# ■ 헬퍼 함수
# ══════════════════════════════════════════════════════════════

def get_current_day() -> int:
    return int(get_setting("day") or 1)

def get_bond_rate() -> float:
    return float(get_setting("bond_rate") or 0.5)

def get_saving_rate() -> float:
    return float(get_setting("saving_rate") or 3.0)

def get_saving_period() -> int:
    return int(get_setting("saving_period") or 5)

def get_inflation_rate() -> float:
    return float(get_setting("inflation_rate") or 0.3)

def get_companies() -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql("SELECT * FROM companies ORDER BY company_id", conn)
    conn.close()
    return df

def get_alt_assets() -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql("SELECT * FROM alt_assets ORDER BY asset_id", conn)
    conn.close()
    return df

def get_news(day: int) -> pd.DataFrame:
    conn = get_connection()
    # ✅ params 대신 f-string 방식으로 변경 (pandas 최신 버전 호환)
    df = pd.read_sql(
        f"""
        SELECT n.content, n.news_type,
               COALESCE(c.name,'전체 경제') AS company_name,
               COALESCE(c.sector,'경제')    AS sector
        FROM news n
        LEFT JOIN companies c ON n.company_id = c.company_id
        WHERE n.day = {day}
        ORDER BY n.news_type, c.company_id
        """,
        conn
    )
    conn.close()
    return df

def get_student_cash(student_id: int) -> float:
    conn = get_connection()
    row = conn.execute(
        "SELECT cash FROM students WHERE student_id=?", (student_id,)
    ).fetchone()
    conn.close()
    return float(row[0]) if row else 0.0

def get_stock_holdings(student_id: int) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql(
        f"""
        SELECT h.company_id, c.name, c.sector,
               h.quantity, c.current_price,
               (h.quantity * c.current_price) AS eval_amount
        FROM holdings h
        JOIN companies c ON h.company_id = c.company_id
        WHERE h.student_id = {student_id} AND h.quantity > 0
        """,
        conn
    )
    conn.close()
    return df

def get_alt_holdings(student_id: int) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql(
        f"""
        SELECT ah.asset_type, a.name, a.unit,
               ah.quantity, a.current_price,
               (ah.quantity * a.current_price) AS eval_amount
        FROM alt_holdings ah
        JOIN alt_assets a ON ah.asset_type = a.asset_type
        WHERE ah.student_id = {student_id} AND ah.quantity > 0
        """,
        conn
    )
    conn.close()
    return df

def get_bond_holding(student_id: int) -> float:
    conn = get_connection()
    row = conn.execute(
        "SELECT amount FROM bond_holdings WHERE student_id=?", (student_id,)
    ).fetchone()
    conn.close()
    return float(row["amount"]) if row else 0.0

def get_savings(student_id: int) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql(
        f"""
        SELECT saving_id, amount, rate, start_day, end_day, is_matured,
               ROUND(amount * rate / 100, 0)       AS interest,
               ROUND(amount * (1 + rate/100), 0)   AS maturity_amount
        FROM savings
        WHERE student_id = {student_id}
        ORDER BY saving_id DESC
        """,
        conn
    )
    conn.close()
    return df

def calc_total_assets(student_id: int) -> dict:
    cash = get_student_cash(student_id)
    conn = get_connection()

    r1 = conn.execute(
        """
        SELECT COALESCE(SUM(h.quantity * c.current_price),0) AS v
        FROM holdings h JOIN companies c ON h.company_id=c.company_id
        WHERE h.student_id=?
        """, (student_id,)
    ).fetchone()
    stock_val = float(r1["v"])

    r2 = conn.execute(
        """
        SELECT COALESCE(SUM(ah.quantity * a.current_price),0) AS v
        FROM alt_holdings ah JOIN alt_assets a ON ah.asset_type=a.asset_type
        WHERE ah.student_id=?
        """, (student_id,)
    ).fetchone()
    alt_val = float(r2["v"])

    bond_val = get_bond_holding(student_id)

    r3 = conn.execute(
        "SELECT COALESCE(SUM(amount),0) AS v FROM savings WHERE student_id=? AND is_matured=0",
        (student_id,)
    ).fetchone()
    saving_val = float(r3["v"])

    r4 = conn.execute(
        "SELECT COALESCE(cumulative_loss,0) AS v FROM students WHERE student_id=?",
        (student_id,)
    ).fetchone()
    cumulative_loss = float(r4["v"])

    conn.close()

    total       = cash + stock_val + alt_val + bond_val + saving_val
    profit_rate = (total / INITIAL_CASH - 1) * 100

    return {
        "cash":            cash,
        "stock_val":       stock_val,
        "alt_val":         alt_val,
        "bond_val":        bond_val,
        "saving_val":      saving_val,
        "total":           total,
        "profit_rate":     profit_rate,
        "cumulative_loss": cumulative_loss,
    }


# ── 거래 함수 ─────────────────────────────────────────────────

def buy_stock(student_id, company_id, quantity, price, reason, day):
    total = quantity * price
    conn  = get_connection()
    try:
        conn.execute("BEGIN")
        cash = float(conn.execute(
            "SELECT cash FROM students WHERE student_id=?", (student_id,)
        ).fetchone()["cash"])
        if cash < total:
            conn.close()
            return False, "잔액이 부족합니다."
        conn.execute(
            "UPDATE students SET cash=cash-? WHERE student_id=?",
            (total, student_id)
        )
        conn.execute(
            """
            INSERT INTO holdings (student_id,company_id,quantity) VALUES (?,?,?)
            ON CONFLICT(student_id,company_id) DO UPDATE SET quantity=quantity+?
            """,
            (student_id, company_id, quantity, quantity)
        )
        conn.execute(
            "INSERT INTO transactions (student_id,asset_type,company_id,tx_type,quantity,price,reason,day) VALUES (?,?,?,?,?,?,?,?)",
            (student_id, "stock", company_id, "buy", quantity, price, reason, day)
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
    conn  = get_connection()
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
            "UPDATE holdings SET quantity=quantity-? WHERE student_id=? AND company_id=?",
            (quantity, student_id, company_id)
        )
        conn.execute(
            "UPDATE students SET cash=cash+? WHERE student_id=?",
            (total, student_id)
        )
        conn.execute(
            "INSERT INTO transactions (student_id,asset_type,company_id,tx_type,quantity,price,reason,day) VALUES (?,?,?,?,?,?,?,?)",
            (student_id, "stock", company_id, "sell", quantity, price, reason, day)
        )
        conn.commit()
        conn.close()
        return True, "매도 완료!"
    except Exception as e:
        conn.rollback()
        conn.close()
        return False, str(e)


def buy_alt_asset(student_id, asset_type, quantity, price, reason, day):
    total = quantity * price
    conn  = get_connection()
    try:
        conn.execute("BEGIN")
        cash = float(conn.execute(
            "SELECT cash FROM students WHERE student_id=?", (student_id,)
        ).fetchone()["cash"])
        if cash < total:
            conn.close()
            return False, "잔액이 부족합니다."
        conn.execute(
            "UPDATE students SET cash=cash-? WHERE student_id=?",
            (total, student_id)
        )
        conn.execute(
            """
            INSERT INTO alt_holdings (student_id,asset_type,quantity) VALUES (?,?,?)
            ON CONFLICT(student_id,asset_type) DO UPDATE SET quantity=quantity+?
            """,
            (student_id, asset_type, quantity, quantity)
        )
        conn.execute(
            "INSERT INTO transactions (student_id,asset_type,tx_type,quantity,price,reason,day) VALUES (?,?,?,?,?,?,?)",
            (student_id, asset_type, "buy", quantity, price, reason, day)
        )
        conn.commit()
        conn.close()
        return True, "매수 완료!"
    except Exception as e:
        conn.rollback()
        conn.close()
        return False, str(e)


def sell_alt_asset(student_id, asset_type, quantity, price, reason, day):
    total = quantity * price
    conn  = get_connection()
    try:
        conn.execute("BEGIN")
        row = conn.execute(
            "SELECT quantity FROM alt_holdings WHERE student_id=? AND asset_type=?",
            (student_id, asset_type)
        ).fetchone()
        if row is None or float(row["quantity"]) < quantity:
            conn.close()
            return False, "보유량이 부족합니다."
        conn.execute(
            "UPDATE alt_holdings SET quantity=quantity-? WHERE student_id=? AND asset_type=?",
            (quantity, student_id, asset_type)
        )
        conn.execute(
            "UPDATE students SET cash=cash+? WHERE student_id=?",
            (total, student_id)
        )
        conn.execute(
            "INSERT INTO transactions (student_id,asset_type,tx_type,quantity,price,reason,day) VALUES (?,?,?,?,?,?,?)",
            (student_id, asset_type, "sell", quantity, price, reason, day)
        )
        conn.commit()
        conn.close()
        return True, "매도 완료!"
    except Exception as e:
        conn.rollback()
        conn.close()
        return False, str(e)


def buy_bond(student_id, amount, reason, day):
    conn = get_connection()
    try:
        conn.execute("BEGIN")
        cash = float(conn.execute(
            "SELECT cash FROM students WHERE student_id=?", (student_id,)
        ).fetchone()["cash"])
        if cash < amount:
            conn.close()
            return False, "잔액이 부족합니다."
        conn.execute(
            "UPDATE students SET cash=cash-? WHERE student_id=?",
            (amount, student_id)
        )
        conn.execute(
            """
            INSERT INTO bond_holdings (student_id,amount) VALUES (?,?)
            ON CONFLICT(student_id) DO UPDATE SET amount=amount+?
            """,
            (student_id, amount, amount)
        )
        conn.execute(
            "INSERT INTO transactions (student_id,asset_type,tx_type,quantity,price,reason,day) VALUES (?,?,?,?,?,?,?)",
            (student_id, "bond", "buy", amount, 1, reason, day)
        )
        conn.commit()
        conn.close()
        return True, "국채 매수 완료!"
    except Exception as e:
        conn.rollback()
        conn.close()
        return False, str(e)


def sell_bond(student_id, amount, reason, day):
    conn = get_connection()
    try:
        conn.execute("BEGIN")
        row = conn.execute(
            "SELECT amount FROM bond_holdings WHERE student_id=?", (student_id,)
        ).fetchone()
        if row is None or float(row["amount"]) < amount:
            conn.close()
            return False, "보유 국채 금액이 부족합니다."
        conn.execute(
            "UPDATE bond_holdings SET amount=amount-? WHERE student_id=?",
            (amount, student_id)
        )
        conn.execute(
            "UPDATE students SET cash=cash+? WHERE student_id=?",
            (amount, student_id)
        )
        conn.execute(
            "INSERT INTO transactions (student_id,asset_type,tx_type,quantity,price,reason,day) VALUES (?,?,?,?,?,?,?)",
            (student_id, "bond", "sell", amount, 1, reason, day)
        )
        conn.commit()
        conn.close()
        return True, "국채 환매 완료!"
    except Exception as e:
        conn.rollback()
        conn.close()
        return False, str(e)


def deposit_saving(student_id, amount, rate, start_day, end_day, reason, day):
    conn = get_connection()
    try:
        conn.execute("BEGIN")
        cash = float(conn.execute(
            "SELECT cash FROM students WHERE student_id=?", (student_id,)
        ).fetchone()["cash"])
        if cash < amount:
            conn.close()
            return False, "잔액이 부족합니다."
        conn.execute(
            "UPDATE students SET cash=cash-? WHERE student_id=?",
            (amount, student_id)
        )
        conn.execute(
            "INSERT INTO savings (student_id,amount,rate,start_day,end_day,is_matured) VALUES (?,?,?,?,?,0)",
            (student_id, amount, rate, start_day, end_day)
        )
        conn.execute(
            "INSERT INTO transactions (student_id,asset_type,tx_type,quantity,price,reason,day) VALUES (?,?,?,?,?,?,?)",
            (student_id, "saving", "buy", amount, 1, reason, day)
        )
        conn.commit()
        conn.close()
        return True, "적금 납입 완료!"
    except Exception as e:
        conn.rollback()
        conn.close()
        return False, str(e)


def apply_daily_events(day: int):
    bond_rate      = get_bond_rate()
    inflation_rate = get_inflation_rate()
    conn           = get_connection()
    try:
        conn.execute("BEGIN")

        # 국채 이자 지급
        for bh in conn.execute(
            "SELECT student_id, amount FROM bond_holdings WHERE amount > 0"
        ).fetchall():
            interest = float(bh["amount"]) * bond_rate / 100
            conn.execute(
                "UPDATE students SET cash=cash+? WHERE student_id=?",
                (interest, bh["student_id"])
            )

        # 적금 만기 처리
        for sv in conn.execute(
            "SELECT * FROM savings WHERE end_day<=? AND is_matured=0", (day,)
        ).fetchall():
            maturity_amount = float(sv["amount"]) * (1 + float(sv["rate"]) / 100)
            conn.execute(
                "UPDATE students SET cash=cash+? WHERE student_id=?",
                (maturity_amount, sv["student_id"])
            )
            conn.execute(
                "UPDATE savings SET is_matured=1 WHERE saving_id=?",
                (sv["saving_id"],)
            )

        # 인플레이션: 현금 가치 하락
        for s in conn.execute(
            "SELECT student_id, cash FROM students"
        ).fetchall():
            loss = float(s["cash"]) * inflation_rate / 100
            conn.execute(
                "UPDATE students SET cash=cash-?, cumulative_loss=cumulative_loss+? WHERE student_id=?",
                (loss, loss, s["student_id"])
            )
            conn.execute(
                "INSERT INTO inflation_log (day,rate,student_id,loss_amount) VALUES (?,?,?,?)",
                (day, inflation_rate, s["student_id"], loss)
            )

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        conn.rollback()
        conn.close()
        return False


# ══════════════════════════════════════════════════════════════
# ■ Session State 초기화
# ══════════════════════════════════════════════════════════════

for key, val in [
    ("student_logged_in", False),
    ("logged_student_id", None),
    ("teacher_auth",      False),
    ("reset_requested",   False),
]:
    if key not in st.session_state:
        st.session_state[key] = val


# ══════════════════════════════════════════════════════════════
# ■ 사이드바
# ══════════════════════════════════════════════════════════════

st.sidebar.title("💰 어린이 경제 교실")
st.sidebar.markdown("---")

user_options = [f"학생 {i}번" for i in range(1, NUM_STUDENTS + 1)]
user_options.append("교사 관리자")

selected_user = st.sidebar.selectbox("👤 접속할 계정을 선택하세요", user_options)
day = get_current_day()
st.sidebar.markdown(f"---\n📅 **현재 거래일: {day}일차**")

if selected_user != "교사 관리자":
    sel_id = int(selected_user.replace("학생 ", "").replace("번", ""))
    if st.session_state["logged_student_id"] != sel_id:
        st.session_state["student_logged_in"] = False
        st.session_state["logged_student_id"] = None


# ══════════════════════════════════════════════════════════════
# ■ 교사 관리자 로그인
# ══════════════════════════════════════════════════════════════

if selected_user == "교사 관리자":
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

if selected_user == "교사 관리자" and st.session_state["teacher_auth"]:

    st.title(f"🏫 교사 관리자 대시보드 — {day}일차")
    companies_df  = get_companies()
    alt_assets_df = get_alt_assets()

    tab_news, tab_price, tab_rank, tab_pw, tab_reset = st.tabs([
        "📰 뉴스 작성",
        "💹 시세 & 하루 경과",
        "🏆 순위 & 거래 내역",
        "🔑 비밀번호 관리",
        "🔄 게임 초기화",
    ])

    # ── [탭1] 뉴스 작성 ─────────────────────────────────────
    with tab_news:
        st.subheader(f"📰 {day}일차 뉴스 작성")
        existing = get_news(day)
        if not existing.empty:
            st.success("✅ 오늘의 뉴스가 이미 등록되어 있습니다.")
            st.dataframe(
                existing.rename(columns={
                    "company_name": "대상",
                    "sector":       "분류",
                    "content":      "내용",
                    "news_type":    "유형",
                }),
                use_container_width=True, hide_index=True
            )
        else:
            st.markdown("#### 📌 주식 관련 뉴스")
            stock_news = {}
            for _, row in companies_df.iterrows():
                stock_news[row["company_id"]] = st.text_area(
                    f"[{row['sector']}] {row['name']}",
                    height=70, key=f"snews_{row['company_id']}"
                )
            st.markdown("#### 🌐 경제 전체 뉴스")
            eco_news = st.text_area(
                "전체 경제 뉴스 (선택 입력)",
                placeholder="예) 전 세계 물가가 오르고 있어요. 금 수요가 늘고 있답니다.",
                height=80, key="eco_news"
            )
            if st.button("📨 뉴스 등록", type="primary"):
                if any(v.strip() == "" for v in stock_news.values()):
                    st.warning("주식 기업 뉴스를 모두 입력해 주세요.")
                else:
                    conn = get_connection()
                    for cid, content in stock_news.items():
                        conn.execute(
                            "INSERT INTO news (day,company_id,content,news_type) VALUES (?,?,?,?)",
                            (day, cid, content.strip(), "stock")
                        )
                    if eco_news.strip():
                        conn.execute(
                            "INSERT INTO news (day,company_id,content,news_type) VALUES (?,NULL,?,?)",
                            (day, eco_news.strip(), "economy")
                        )
                    conn.commit()
                    conn.close()
                    st.success("뉴스 등록 완료!")
                    st.rerun()

    # ── [탭2] 시세 & 하루 경과 ──────────────────────────────
    with tab_price:
        st.subheader("💹 시세 변동 설정 및 하루 경과")

        st.markdown("#### 📈 주식 변동률 설정")
        change_rates = {}
        cols = st.columns(len(companies_df))
        for i, (_, row) in enumerate(companies_df.iterrows()):
            with cols[i]:
                diff = row["current_price"] - row["prev_price"]
                st.metric(
                    row["name"],
                    f"{row['current_price']:,}원",
                    delta=f"{diff:+,}원" if diff != 0 else None
                )
                change_rates[row["company_id"]] = st.number_input(
                    "변동률(%)", -30.0, 30.0, 0.0, 0.5,
                    key=f"sr_{row['company_id']}"
                )

        st.markdown("---")
        st.markdown("#### 🥇 금 / ₿ 비트코인 시세 변동률 설정")
        alt_rates = {}
        acols = st.columns(len(alt_assets_df))
        for i, (_, row) in enumerate(alt_assets_df.iterrows()):
            with acols[i]:
                emoji    = "🥇" if row["asset_type"] == "gold" else "₿"
                diff     = float(row["current_price"]) - float(row["prev_price"])
                max_chg  = 50.0 if row["asset_type"] == "bitcoin" else 20.0
                st.metric(
                    f"{emoji} {row['name']}",
                    f"{row['current_price']:,.0f}원/{row['unit']}",
                    delta=f"{diff:+,.0f}원" if diff != 0 else None
                )
                alt_rates[row["asset_type"]] = st.number_input(
                    f"변동률(%) 최대±{max_chg}%",
                    -max_chg, max_chg, 0.0, 0.5,
                    key=f"ar_{row['asset_type']}"
                )

        st.markdown("---")
        st.markdown("#### ⚙️ 경제 지표 설정")

        ec1, ec2, ec3, ec4 = st.columns(4)
        with ec1:
            new_bond_rate = st.number_input(
                "🏛️ 국채 일일 이자율(%)",
                min_value=0.0,
                max_value=5.0,
                value=get_bond_rate(),
                step=0.1,
                help="하루 경과 시 국채 보유액에 이자 지급"
            )
        with ec2:
            new_saving_rate = st.number_input(
                "🏦 적금 만기 이자율(%)",
                min_value=0.0,
                max_value=20.0,
                value=get_saving_rate(),
                step=0.5,
                help="적금 만기 시 지급되는 총 이자율"
            )
        with ec3:
            new_saving_period = st.number_input(
                "🏦 적금 만기 기간(일)",
                min_value=1,
                max_value=30,
                value=get_saving_period(),
                step=1,
                help="적금 납입 후 만기까지 걸리는 거래일 수"
            )
        with ec4:
            new_inflation_rate = st.number_input(
                "📉 일일 물가 상승률(%)",
                min_value=0.0,
                max_value=5.0,
                value=get_inflation_rate(),
                step=0.1,
                help="하루 경과 시 현금 보유액에서 차감되는 비율"
            )

        st.markdown("---")
        st.warning("⚠️ '하루 경과' 버튼은 한 번 누르면 되돌릴 수 없습니다.")

        if st.button("🔄 시세 반영 및 하루 경과", type="primary"):
            conn = get_connection()
            try:
                conn.execute("BEGIN")

                for cid, rate in change_rates.items():
                    cur = conn.execute(
                        "SELECT current_price FROM companies WHERE company_id=?", (cid,)
                    ).fetchone()["current_price"]
                    new_price = max(100, int(cur * (1 + rate / 100)))
                    conn.execute(
                        "UPDATE companies SET prev_price=current_price, current_price=? WHERE company_id=?",
                        (new_price, cid)
                    )

                for atype, rate in alt_rates.items():
                    cur = float(conn.execute(
                        "SELECT current_price FROM alt_assets WHERE asset_type=?", (atype,)
                    ).fetchone()["current_price"])
                    new_price = max(100, cur * (1 + rate / 100))
                    conn.execute(
                        "UPDATE alt_assets SET prev_price=current_price, current_price=? WHERE asset_type=?",
                        (new_price, atype)
                    )

                conn.commit()
                conn.close()

                set_setting("bond_rate",      str(new_bond_rate))
                set_setting("saving_rate",    str(new_saving_rate))
                set_setting("saving_period",  str(new_saving_period))
                set_setting("inflation_rate", str(new_inflation_rate))

                apply_daily_events(day)
                set_setting("day", str(day + 1))

                st.success(f"✅ {day + 1}일차로 넘어갔습니다!")
                st.rerun()

            except Exception as e:
                conn.rollback()
                conn.close()
                st.error(f"오류 발생: {e}")

    # ── [탭3] 순위 & 거래 내역 ──────────────────────────────
    with tab_rank:
        st.subheader("🏆 학생 전체 순위")

        rank_data = []
        for sid in range(1, NUM_STUDENTS + 1):
            a = calc_total_assets(sid)
            rank_data.append({
                "학생":        f"{sid}번",
                "현금(원)":    int(a["cash"]),
                "주식(원)":    int(a["stock_val"]),
                "금·코인(원)": int(a["alt_val"]),
                "국채(원)":    int(a["bond_val"]),
                "적금(원)":    int(a["saving_val"]),
                "총자산(원)":  int(a["total"]),
                "수익률(%)":   round(a["profit_rate"], 2),
                "인플손실(원)": int(a["cumulative_loss"]),
            })

        rank_df = (
            pd.DataFrame(rank_data)
            .sort_values("총자산(원)", ascending=False)
            .reset_index(drop=True)
        )
        rank_df.index      = rank_df.index + 1
        rank_df.index.name = "순위"

        def highlight_profit(val):
            if isinstance(val, (int, float)):
                if val > 0:
                    return "color: green; font-weight: bold"
                elif val < 0:
                    return "color: red; font-weight: bold"
            return ""

        st.dataframe(
            rank_df.style.map(highlight_profit, subset=["수익률(%)"]),
            use_container_width=True
        )

        st.markdown("---")
        st.subheader("📋 전체 거래 내역 및 투자 이유")

        conn = get_connection()
        all_tx = pd.read_sql(
            """
            SELECT t.day AS 거래일,
                   t.student_id AS 학생번호,
                   t.asset_type AS 자산유형,
                   COALESCE(c.name, t.asset_type) AS 자산명,
                   CASE t.tx_type
                       WHEN 'buy' THEN '매수/납입'
                       ELSE '매도/환매'
                   END AS 거래유형,
                   t.quantity AS 수량,
                   t.price AS 단가,
                   (t.quantity * t.price) AS 거래금액,
                   t.reason AS 투자이유
            FROM transactions t
            LEFT JOIN companies c ON t.company_id = c.company_id
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
        st.info("초기 비밀번호는 **0000** 입니다.")

        pw_df = get_all_passwords()
        pw_df.columns = ["학생번호", "현재 비밀번호"]
        pw_df["학생번호"] = pw_df["학생번호"].apply(lambda x: f"{x}번")
        st.dataframe(pw_df, use_container_width=True, hide_index=True)

        st.markdown("---")
        col_single, col_bulk = st.columns(2)

        with col_single:
            st.markdown("### 👤 개별 비밀번호 변경")
            target_student = st.selectbox(
                "학생 선택",
                options=list(range(1, NUM_STUDENTS + 1)),
                format_func=lambda x: f"{x}번",
                            key="pw_target"
            )
            new_pw_single = st.text_input(
                "새 비밀번호 입력", max_chars=20, key="new_pw_single"
            )
            if st.button("✅ 비밀번호 변경", key="btn_pw_single"):
                if new_pw_single.strip() == "":
                    st.warning("비밀번호를 입력해 주세요.")
                else:
                    update_student_password(target_student, new_pw_single.strip())
                    st.success(f"✅ {target_student}번 학생 비밀번호 변경 완료!")
                    st.rerun()

        with col_bulk:
            st.markdown("### 🔄 전체 일괄 초기화")
            new_pw_bulk = st.text_input(
                "일괄 초기화할 비밀번호", value="0000",
                max_chars=20, key="new_pw_bulk"
            )
            st.warning("⚠️ 전체 학생 비밀번호가 동일하게 변경됩니다.")
            if st.button("🔄 전체 초기화", type="primary", key="btn_pw_bulk"):
                if new_pw_bulk.strip() == "":
                    st.warning("초기화할 비밀번호를 입력해 주세요.")
                else:
                    reset_all_passwords(new_pw_bulk.strip())
                    st.success(f"✅ 전체 비밀번호가 '{new_pw_bulk}'(으)로 초기화되었습니다!")
                    st.rerun()

    # ── [탭5] 게임 초기화 ────────────────────────────────────
    with tab_reset:
        st.subheader("🔄 게임 전체 초기화")
        summary = get_game_summary()

        s1, s2, s3, s4 = st.columns(4)
        s1.metric("📅 현재 거래일",    f"{summary['current_day']}일차")
        s2.metric("💱 총 거래 횟수",   f"{summary['tx_count']}건")
        s3.metric("📰 등록된 뉴스",    f"{summary['news_count']}건")
        s4.metric("👥 거래 참여 학생", f"{summary['active_students']}명")

        st.markdown("---")
        reset_pw_also = st.checkbox(
            "🔑 비밀번호도 함께 초기화 (전체 '0000'으로 변경)",
            value=False
        )

        preview_data = {
            "항목":      ["거래일","현금","주식","금·비트코인",
                          "국채","적금","뉴스","인플레이션 손실","비밀번호"],
            "현재 상태": [f"{summary['current_day']}일차",
                          "각자 다름","각자 보유","각자 보유",
                          "각자 보유","각자 납입","등록됨",
                          "누적됨","각자 다름"],
            "초기화 후": ["1일차","1,000,000원","전량 삭제","전량 삭제",
                          "전액 삭제","전체 삭제","전체 삭제",
                          "초기화",
                          "0000으로 초기화" if reset_pw_also else "유지"],
        }
        st.table(pd.DataFrame(preview_data))

        st.error(
            "🚨 **주의:** 초기화는 되돌릴 수 없습니다!\n\n"
            "반드시 데이터를 먼저 캡처/저장 후 진행하세요."
        )

        confirm_check = st.checkbox(
            "✅ 위 내용을 확인했으며, 게임을 초기화하겠습니다.",
            value=False, key="confirm_reset"
        )

        if st.button(
            "🔄 게임 전체 초기화 실행",
            type="primary",
            disabled=not confirm_check,
            key="btn_reset"
        ):
            st.session_state["reset_requested"] = True

        if st.session_state.get("reset_requested", False):
            st.warning("⚠️ 정말로 초기화하시겠습니까?")
            fc1, fc2 = st.columns(2)
            with fc1:
                if st.button("✅ 네, 초기화합니다", type="primary", key="btn_final_yes"):
                    ok, msg = reset_game(reset_password=reset_pw_also)
                    if ok:
                        st.session_state["reset_requested"] = False
                        st.success(f"🎉 {msg}")
                        st.balloons()
                        st.rerun()
                    else:
                        st.error(msg)
            with fc2:
                if st.button("❌ 아니요, 취소합니다", key="btn_final_no"):
                    st.session_state["reset_requested"] = False
                    st.info("초기화가 취소되었습니다.")
                    st.rerun()

    # 교사 로그아웃
    if st.sidebar.button("🚪 로그아웃"):
        st.session_state["teacher_auth"] = False
        st.rerun()


# ══════════════════════════════════════════════════════════════
# ■ 학생 로그인 화면
# ══════════════════════════════════════════════════════════════

elif selected_user != "교사 관리자":
    student_id = int(selected_user.replace("학생 ", "").replace("번", ""))

    if not st.session_state["student_logged_in"]:
        st.title(f"🔐 학생 {student_id}번 로그인")
        st.markdown("비밀번호를 입력하세요. 초기 비밀번호는 선생님께 문의하세요.")
        input_pw = st.text_input("🔑 비밀번호", type="password")
        if st.button("✅ 로그인", type="primary"):
            if verify_student_password(student_id, input_pw):
                st.session_state["student_logged_in"] = True
                st.session_state["logged_student_id"] = student_id
                st.rerun()
            else:
                st.error("❌ 비밀번호가 틀렸습니다. 선생님께 문의하세요.")
        st.stop()

    # ══════════════════════════════════════════════════════════
    # ■ 학생 메인 화면
    # ══════════════════════════════════════════════════════════

    assets         = calc_total_assets(student_id)
    companies_df   = get_companies()
    alt_assets_df  = get_alt_assets()
    news_df        = get_news(day)
    bond_rate      = get_bond_rate()
    saving_rate    = get_saving_rate()
    saving_period  = get_saving_period()
    inflation_rate = get_inflation_rate()

    st.title(f"💰 어린이 경제 교실 — 학생 {student_id}번")

    # 자산 현황 카드
    st.subheader("💼 나의 자산 현황")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("💵 현금",      f"{int(assets['cash']):,}원")
    c2.metric("📈 주식",      f"{int(assets['stock_val']):,}원")
    c3.metric("🥇 금·코인",   f"{int(assets['alt_val']):,}원")
    c4.metric("🏛️ 국채",      f"{int(assets['bond_val']):,}원")
    c5.metric("🏦 적금",      f"{int(assets['saving_val']):,}원")
    c6.metric("🏦 총 자산",   f"{int(assets['total']):,}원",
              delta=f"{assets['profit_rate']:+.2f}%")

    # 인플레이션 경고 메시지
    if assets["cumulative_loss"] > 0:
        st.warning(
            f"📉 지금까지 물가 상승으로 현금 가치가 총 "
            f"**{int(assets['cumulative_loss']):,}원** 줄었어요! "
            f"현금만 보유하면 손해가 될 수 있답니다."
        )

    if st.sidebar.button("🚪 로그아웃"):
        st.session_state["student_logged_in"] = False
        st.session_state["logged_student_id"] = None
        st.rerun()

    st.markdown("---")

    tab_market, tab_stock, tab_alt, tab_bond, tab_saving, tab_portfolio, tab_history = st.tabs([
        "🏪 시장 & 뉴스",
        "📈 주식 거래",
        "🥇 금·비트코인",
        "🏛️ 국채",
        "🏦 적금",
        "📂 내 포트폴리오",
        "📜 거래 내역",
    ])

    # ── [탭1] 시장 & 뉴스 ────────────────────────────────────
    with tab_market:
        st.subheader(f"📊 {day}일차 전체 시세")

        st.markdown("#### 📈 주식")
        stock_rows = []
        for _, row in companies_df.iterrows():
            diff  = row["current_price"] - row["prev_price"]
            rate  = (diff / row["prev_price"] * 100) if row["prev_price"] else 0
            arrow = "🔺" if diff > 0 else ("🔻" if diff < 0 else "➡️")
            stock_rows.append({
                "기업명":     row["name"],
                "업종":       row["sector"],
                "현재가(원)": f"{row['current_price']:,}",
                "전일 대비":  f"{arrow} {diff:+,}원 ({rate:+.1f}%)",
            })
        st.table(pd.DataFrame(stock_rows))

        st.markdown("#### 🥇 금 / ₿ 비트코인")
        alt_rows = []
        for _, row in alt_assets_df.iterrows():
            diff  = float(row["current_price"]) - float(row["prev_price"])
            rate  = (diff / float(row["prev_price"]) * 100) if row["prev_price"] else 0
            arrow = "🔺" if diff > 0 else ("🔻" if diff < 0 else "➡️")
            emoji = "🥇" if row["asset_type"] == "gold" else "₿"
            alt_rows.append({
                "자산":      f"{emoji} {row['name']}",
                "현재가":    f"{row['current_price']:,.0f}원/{row['unit']}",
                "전일 대비": f"{arrow} {diff:+,.0f}원 ({rate:+.1f}%)",
            })
        st.table(pd.DataFrame(alt_rows))

        st.markdown("#### ⚙️ 오늘의 경제 지표")
        ei1, ei2, ei3 = st.columns(3)
        ei1.info(f"🏛️ 국채 일일 이자율: **{bond_rate}%**")
        ei2.info(f"🏦 적금 만기 이자율: **{saving_rate}%** (만기: {saving_period}일)")
        ei3.warning(f"📉 일일 물가 상승률: **{inflation_rate}%** (현금 가치 하락!)")

        st.markdown("---")
        st.subheader(f"📰 {day}일차 오늘의 뉴스")
        if news_df.empty:
            st.info("아직 오늘의 뉴스가 등록되지 않았습니다.")
        else:
            for _, nrow in news_df.iterrows():
                icon = "🌐" if nrow["news_type"] == "economy" else "📌"
                with st.expander(f"{icon} [{nrow['sector']}] {nrow['company_name']}"):
                    st.write(nrow["content"])

    # ── [탭2] 주식 거래 ──────────────────────────────────────
    with tab_stock:
        st.subheader("📈 주식 매수 / 매도")
        st.info("💡 투자 이유를 입력해야 거래 버튼이 활성화됩니다!")

        col_buy, col_sell = st.columns(2)

        with col_buy:
            st.markdown("### 🟢 매수")
            buy_cn    = st.selectbox("기업 선택", companies_df["name"].tolist(), key="buy_company")
            buy_co    = companies_df[companies_df["name"] == buy_cn].iloc[0]
            buy_price = int(buy_co["current_price"])
            st.markdown(f"**현재가:** {buy_price:,}원")

            buy_qty   = st.number_input("수량(주)", 1, 1000, 1, 1, key="buy_qty")
            buy_total = buy_qty * buy_price
            st.markdown(f"**총 금액:** {buy_total:,}원")

            if buy_total > assets["cash"]:
                st.error(f"잔액 부족! (보유 현금: {int(assets['cash']):,}원)")

            buy_reason = st.text_area(
                "✏️ 투자 이유 (필수)",
                placeholder="예) 오늘 뉴스에서 신제품 출시 소식이 있어 주가가 오를 것 같아요.",
                height=90, key="buy_reason"
            )
            buy_disabled = (buy_reason.strip() == "") or (buy_total > assets["cash"])
            if st.button("✅ 매수", type="primary", disabled=buy_disabled, key="btn_buy"):
                ok, msg = buy_stock(
                    student_id, int(buy_co["company_id"]),
                    buy_qty, buy_price, buy_reason.strip(), day
                )
                st.success(f"🎉 {buy_cn} {buy_qty}주 매수 완료!") if ok else st.error(msg)
                if ok: st.rerun()

        with col_sell:
            st.markdown("### 🔴 매도")
            sh_df = get_stock_holdings(student_id)
            if sh_df.empty:
                st.info("보유 중인 주식이 없습니다.")
            else:
                sell_cn = st.selectbox("기업 선택", sh_df["name"].tolist(), key="sell_company")
                sell_h  = sh_df[sh_df["name"] == sell_cn].iloc[0]
                sell_price = int(sell_h["current_price"])
                max_qty    = int(sell_h["quantity"])
                st.markdown(f"**현재가:** {sell_price:,}원 | **보유:** {max_qty}주")

                sell_qty = st.number_input("수량(주)", 1, max_qty, 1, 1, key="sell_qty")
                st.markdown(f"**총 금액:** {sell_qty * sell_price:,}원")

                sell_reason = st.text_area(
                    "✏️ 매도 이유 (필수)",
                    placeholder="예) 주가가 충분히 올라서 지금 파는 게 좋을 것 같아요.",
                    height=90, key="sell_reason"
                )
                sell_disabled = sell_reason.strip() == ""
                if st.button("✅ 매도", type="primary", disabled=sell_disabled, key="btn_sell"):
                    ok, msg = sell_stock(
                        student_id, int(sell_h["company_id"]),
                        sell_qty, sell_price, sell_reason.strip(), day
                    )
                    st.success(f"🎉 {sell_cn} {sell_qty}주 매도 완료!") if ok else st.error(msg)
                    if ok: st.rerun()

    # ── [탭3] 금·비트코인 거래 ───────────────────────────────
    with tab_alt:
        st.subheader("🥇 금 / ₿ 비트코인 거래")
        st.info("💡 금은 비교적 안전한 자산이에요. 비트코인은 가격 변동이 매우 크답니다!")

        asset_labels = {
            "gold":    "🥇 금 (단위: g)",
            "bitcoin": "₿ 비트코인 (단위: BTC)",
        }
        alt_col_buy, alt_col_sell = st.columns(2)

        with alt_col_buy:
            st.markdown("### 🟢 매수")
            alt_buy_type = st.selectbox(
                "자산 선택",
                options=list(asset_labels.keys()),
                format_func=lambda x: asset_labels[x],
                key="alt_buy_type"
            )
            alt_info      = alt_assets_df[alt_assets_df["asset_type"] == alt_buy_type].iloc[0]
            alt_buy_price = float(alt_info["current_price"])
            st.markdown(f"**현재가:** {alt_buy_price:,.0f}원/{alt_info['unit']}")

            if alt_buy_type == "bitcoin":
                alt_buy_qty = st.number_input(
                    "수량(BTC, 0.0001개부터 구매 가능)", 0.0001, 10.0, 0.0001, 0.0001,
                    format="%.4f", key="alt_buy_qty"
                )
            else:
                alt_buy_qty = st.number_input(
                    "수량(g)", 1.0, 1000.0, 1.0, 1.0,
                    format="%.1f", key="alt_buy_qty"
                )

            alt_buy_total = alt_buy_qty * alt_buy_price
            st.markdown(f"**총 금액:** {alt_buy_total:,.0f}원")

            if alt_buy_total > assets["cash"]:
                st.error(f"잔액 부족! (보유 현금: {int(assets['cash']):,}원)")

            alt_buy_reason = st.text_area(
                "✏️ 투자 이유 (필수)",
                placeholder="예) 경제 불안 시 금 가격은 오르는 경향이 있어서요.",
                height=90, key="alt_buy_reason"
            )
            alt_buy_disabled = (
                alt_buy_reason.strip() == "" or alt_buy_total > assets["cash"]
            )
            if st.button("✅ 매수", type="primary", disabled=alt_buy_disabled, key="btn_alt_buy"):
                ok, msg = buy_alt_asset(
                    student_id, alt_buy_type,
                    alt_buy_qty, alt_buy_price,
                    alt_buy_reason.strip(), day
                )
                st.success(f"🎉 {asset_labels[alt_buy_type]} {alt_buy_qty} 매수 완료!") if ok else st.error(msg)
                if ok: st.rerun()

        with alt_col_sell:
            st.markdown("### 🔴 매도")
            alt_h_df = get_alt_holdings(student_id)
            if alt_h_df.empty:
                st.info("보유 중인 금·비트코인이 없습니다.")
            else:
                alt_sell_type = st.selectbox(
                    "자산 선택",
                    options=alt_h_df["asset_type"].tolist(),
                    format_func=lambda x: asset_labels.get(x, x),
                    key="alt_sell_type"
                )
                alt_sell_h     = alt_h_df[alt_h_df["asset_type"] == alt_sell_type].iloc[0]
                alt_sell_price = float(alt_sell_h["current_price"])
                alt_max_qty    = float(alt_sell_h["quantity"])
                st.markdown(
                    f"**현재가:** {alt_sell_price:,.0f}원/{alt_sell_h['unit']} "
                    f"| **보유:** {alt_max_qty}"
                )

                if alt_sell_type == "bitcoin":
                    alt_sell_qty = st.number_input(
                        "수량(BTC)", 0.0001, float(alt_max_qty), 0.0001, 0.0001,
                        format="%.4f", key="alt_sell_qty"
                    )
                else:
                    alt_sell_qty = st.number_input(
                        "수량(g)", 1.0, float(alt_max_qty), 1.0, 1.0,
                        format="%.1f", key="alt_sell_qty"
                    )

                st.markdown(f"**총 금액:** {alt_sell_qty * alt_sell_price:,.0f}원")
                alt_sell_reason = st.text_area(
                    "✏️ 매도 이유 (필수)",
                    placeholder="예) 금 가격이 많이 올라서 지금 팔면 좋을 것 같아요.",
                    height=90, key="alt_sell_reason"
                )
                alt_sell_disabled = alt_sell_reason.strip() == ""
                if st.button("✅ 매도", type="primary", disabled=alt_sell_disabled, key="btn_alt_sell"):
                    ok, msg = sell_alt_asset(
                        student_id, alt_sell_type,
                        alt_sell_qty, alt_sell_price,
                        alt_sell_reason.strip(), day
                    )
                    st.success("🎉 매도 완료!") if ok else st.error(msg)
                    if ok: st.rerun()

    # ── [탭4] 국채 ───────────────────────────────────────────
    with tab_bond:
        st.subheader("🏛️ 국채 투자")
        bond_amount = get_bond_holding(student_id)

        st.info(
            f"🏛️ 국채는 **매일 {bond_rate}%** 이자를 현금으로 받는 안전한 투자예요!\n\n"
            f"주식처럼 시세 차익은 없지만 원금이 보장된답니다."
        )

        bc1, bc2 = st.columns(2)
        bc1.metric("🏛️ 현재 국채 보유액",  f"{int(bond_amount):,}원")
        bc2.metric("💰 일일 예상 이자",    f"{int(bond_amount * bond_rate / 100):,}원")

        st.markdown("---")
        bond_col_buy, bond_col_sell = st.columns(2)

        with bond_col_buy:
            st.markdown("### 🟢 국채 매수")
            bond_buy_amount = st.number_input(
                "매수 금액(원)", 10000, 1000000, 10000, 10000, key="bond_buy_amount"
            )
            if bond_buy_amount > assets["cash"]:
                st.error(f"잔액 부족! (보유 현금: {int(assets['cash']):,}원)")
            bond_buy_reason = st.text_area(
                "✏️ 투자 이유 (필수)",
                placeholder="예) 안정적인 이자를 매일 받고 싶어서요.",
                height=90, key="bond_buy_reason"
            )
            bond_buy_disabled = (
                bond_buy_reason.strip() == "" or bond_buy_amount > assets["cash"]
            )
            if st.button("✅ 국채 매수", type="primary", disabled=bond_buy_disabled, key="btn_bond_buy"):
                ok, msg = buy_bond(
                    student_id, bond_buy_amount, bond_buy_reason.strip(), day
                )
                st.success(f"🎉 국채 {bond_buy_amount:,}원 매수 완료!") if ok else st.error(msg)
                if ok: st.rerun()

        with bond_col_sell:
            st.markdown("### 🔴 국채 환매")
            if bond_amount <= 0:
                st.info("보유 중인 국채가 없습니다.")
            else:
                bond_sell_amount = st.number_input(
                    "환매 금액(원)", 10000, int(bond_amount), 10000, 10000, key="bond_sell_amount"
                )
                bond_sell_reason = st.text_area(
                    "✏️ 환매 이유 (필수)",
                    placeholder="예) 현금이 필요해서 국채를 팔아야 해요.",
                    height=90, key="bond_sell_reason"
                )
                bond_sell_disabled = bond_sell_reason.strip() == ""
                if st.button("✅ 국채 환매", type="primary", disabled=bond_sell_disabled, key="btn_bond_sell"):
                    ok, msg = sell_bond(
                        student_id, bond_sell_amount, bond_sell_reason.strip(), day
                    )
                    st.success(f"🎉 국채 {bond_sell_amount:,}원 환매 완료!") if ok else st.error(msg)
                    if ok: st.rerun()

    # ── [탭5] 적금 ───────────────────────────────────────────
    with tab_saving:
        st.subheader("🏦 적금")
        st.info(
            f"🏦 적금은 돈을 넣어두면 **{saving_period}일 후 만기**에 "
            f"**{saving_rate}% 이자**를 붙여서 돌려받아요!\n\n"
            f"만기 전에는 꺼낼 수 없지만 원금이 보장된답니다."
        )

        savings_df = get_savings(student_id)
        if not savings_df.empty:
            st.markdown("#### 📋 내 적금 현황")
            disp = savings_df.copy()
            disp["상태"]      = disp["is_matured"].apply(
                lambda x: "✅ 만기 지급 완료" if x else "⏳ 진행 중"
            )
            disp["만기일"]    = disp["end_day"].apply(lambda x: f"{x}일차")
            disp["납입금"]    = disp["amount"].apply(lambda x: f"{int(x):,}원")
            disp["이자"]      = disp["interest"].apply(lambda x: f"{int(x):,}원")
            disp["만기 수령액"] = disp["maturity_amount"].apply(lambda x: f"{int(x):,}원")
            st.dataframe(
                disp[["납입금","이자","만기 수령액","만기일","상태"]],
                use_container_width=True, hide_index=True
            )
        else:
            st.info("아직 납입한 적금이 없습니다.")

        st.markdown("---")
        st.markdown("### 🟢 적금 납입")
        saving_amount = st.number_input(
            "납입 금액(원)", 10000, 1000000, 10000, 10000, key="saving_amount"
        )
        st.markdown(
            f"📌 만기일: **{day + saving_period}일차** | "
            f"예상 이자: **{int(saving_amount * saving_rate / 100):,}원** | "
            f"만기 수령액: **{int(saving_amount * (1 + saving_rate / 100)):,}원**"
        )
        if saving_amount > assets["cash"]:
            st.error(f"잔액 부족! (보유 현금: {int(assets['cash']):,}원)")

        saving_reason = st.text_area(
            "✏️ 납입 이유 (필수)",
            placeholder="예) 안전하게 돈을 모으고 싶어서 적금을 들었어요.",
            height=90, key="saving_reason"
        )
        saving_disabled = (
            saving_reason.strip() == "" or saving_amount > assets["cash"]
        )
        if st.button("✅ 적금 납입", type="primary", disabled=saving_disabled, key="btn_saving"):
            ok, msg = deposit_saving(
                student_id, saving_amount, saving_rate,
                day, day + saving_period,
                saving_reason.strip(), day
            )
            st.success(
                f"🎉 {saving_amount:,}원 납입 완료! "
                f"({day + saving_period}일차에 {int(saving_amount * (1 + saving_rate/100)):,}원 수령)"
            ) 

    # ── [탭6] 내 포트폴리오 ──────────────────────────────────
    with tab_portfolio:
        st.subheader("📂 내 전체 포트폴리오")

        total_safe = assets["total"] if assets["total"] > 0 else 1
        portfolio_summary = [
            {"자산 종류": "💵 현금",
             "평가액(원)": int(assets["cash"]),
             "비중(%)": round(assets["cash"] / total_safe * 100, 1)},
            {"자산 종류": "📈 주식",
             "평가액(원)": int(assets["stock_val"]),
             "비중(%)": round(assets["stock_val"] / total_safe * 100, 1)},
            {"자산 종류": "🥇 금·비트코인",
             "평가액(원)": int(assets["alt_val"]),
             "비중(%)": round(assets["alt_val"] / total_safe * 100, 1)},
            {"자산 종류": "🏛️ 국채",
             "평가액(원)": int(assets["bond_val"]),
             "비중(%)": round(assets["bond_val"] / total_safe * 100, 1)},
            {"자산 종류": "🏦 적금",
             "평가액(원)": int(assets["saving_val"]),
             "비중(%)": round(assets["saving_val"] / total_safe * 100, 1)},
        ]
        st.dataframe(
            pd.DataFrame(portfolio_summary),
            use_container_width=True, hide_index=True
        )

        sh_df = get_stock_holdings(student_id)
        if not sh_df.empty:
            st.markdown("#### 📈 보유 주식 상세")
            st.dataframe(
                sh_df.rename(columns={
                    "name": "기업명", "sector": "업종",
                    "quantity": "보유(주)", "current_price": "현재가(원)",
                    "eval_amount": "평가액(원)"
                })[["기업명","업종","보유(주)","현재가(원)","평가액(원)"]],
                use_container_width=True, hide_index=True
            )

        ah_df = get_alt_holdings(student_id)
        if not ah_df.empty:
            st.markdown("#### 🥇 보유 금·비트코인 상세")
            st.dataframe(
                ah_df.rename(columns={
                    "name": "자산명", "unit": "단위",
                    "quantity": "보유량", "current_price": "현재가(원)",
                    "eval_amount": "평가액(원)"
                })[["자산명","단위","보유량","현재가(원)","평가액(원)"]],
                use_container_width=True, hide_index=True
            )

        st.markdown("---")
        p1, p2, p3 = st.columns(3)
        p1.metric("🏦 총 자산",           f"{int(assets['total']):,}원")
        p2.metric("📈 수익률",             f"{assets['profit_rate']:+.2f}%")
        p3.metric("📉 인플레이션 누적 손실", f"{int(assets['cumulative_loss']):,}원")

    # ── [탭7] 거래 내역 ──────────────────────────────────────
    with tab_history:
        st.subheader("📜 나의 전체 거래 내역")
        conn = get_connection()
        my_tx = pd.read_sql(
            f"""
            SELECT
                t.day        AS 거래일,
                t.asset_type AS 자산유형,
                COALESCE(c.name, t.asset_type) AS 자산명,
                CASE t.tx_type
                    WHEN 'buy' THEN '🟢 매수/납입'
                    ELSE            '🔴 매도/환매'
                END          AS 거래유형,
                t.quantity   AS 수량,
                t.price      AS 단가,
                (t.quantity * t.price) AS 거래금액,
                t.reason     AS 투자이유
            FROM transactions t
            LEFT JOIN companies c ON t.company_id = c.company_id
            WHERE t.student_id = {student_id}
            ORDER BY t.tx_id DESC
            """,
            conn
        )
        conn.close()

        if my_tx.empty:
            st.info("아직 거래 내역이 없습니다.")
        else:
            st.dataframe(my_tx, use_container_width=True, hide_index=True)
