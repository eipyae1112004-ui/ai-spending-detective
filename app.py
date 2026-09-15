"""AI Spending Detective — Streamlit dashboard."""

import tempfile
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from src.agent import _next_month_str, recommend_budgets, run_agent
from src.db import get_session, init_db
from src.ingest import import_csv, import_pdf
from src.models import AgentAction, Budget, Category, Transaction
from src.synthetic_data import generate_month

st.set_page_config(page_title="AI Spending Detective", page_icon="🕵️", layout="wide")
init_db()


def md_safe(text: str | None) -> str:
    """Escape $ so Streamlit's markdown renderer doesn't mistake dollar amounts for LaTeX math."""
    return text.replace("$", "\\$") if text else ""

# ---------------------------------------------------------------- sidebar: data controls
st.sidebar.title("🕵️ AI Spending Detective")
st.sidebar.caption("Upload a statement, or generate demo data, then let the AI agent categorize it.")

uploaded = st.sidebar.file_uploader("Upload bank statement", type=["csv", "pdf"])
if uploaded is not None:
    suffix = Path(uploaded.name).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded.getbuffer())
        tmp_path = tmp.name
    session = get_session()
    try:
        n = import_csv(tmp_path, session) if suffix.lower() == ".csv" else import_pdf(tmp_path, session)
        st.sidebar.success(f"Imported {n} transactions.")
    except Exception as e:
        st.sidebar.error(f"Import failed: {e}")
    finally:
        session.close()

if st.sidebar.button("Generate demo month (synthetic)"):
    session = get_session()
    n = generate_month(session, 2026, 9)
    st.sidebar.success(f"Generated {n} synthetic transactions.")
    session.close()

session = get_session()
uncategorized_count = session.query(Transaction).filter(Transaction.category_id.is_(None)).count()
session.close()

if uncategorized_count > 0:
    st.sidebar.warning(f"{uncategorized_count} uncategorized transactions.")
    if st.sidebar.button("🤖 Run AI agent"):
        with st.spinner("Agent categorizing and auditing transactions..."):
            n = run_agent()
        st.sidebar.success(f"Agent processed {n} transactions.")
        st.rerun()
else:
    st.sidebar.success("All transactions categorized.")

st.sidebar.divider()
if st.sidebar.button("🔄 Refresh dashboard"):
    st.rerun()

# ---------------------------------------------------------------- load data
session = get_session()
transactions = session.query(Transaction).all()
actions = session.query(AgentAction).order_by(AgentAction.timestamp.desc()).limit(30).all()

if not transactions:
    session.close()
    st.title("AI Spending Detective")
    st.info("No data yet — use the sidebar to upload a statement or generate demo data.")
    st.stop()

df = pd.DataFrame(
    [
        {
            "date": t.date,
            "merchant": t.merchant,
            "amount": t.amount,
            "category": t.category.name if t.category else "Uncategorized",
            "is_anomaly": t.is_anomaly,
            "anomaly_reason": t.anomaly_reason,
            "lat": t.lat,
            "lng": t.lng,
            "location_name": t.location_name,
        }
        for t in transactions
    ]
)
session.close()

# ---------------------------------------------------------------- KPI row
st.title("🕵️ AI Spending Detective")

income = df[df.amount > 0].amount.sum()
expenses = -df[df.amount < 0].amount.sum()
net = income - expenses
anomaly_count = int(df.is_anomaly.sum())

c1, c2, c3, c4 = st.columns(4)
c1.metric("Income", f"${income:,.2f}")
c2.metric("Expenses", f"${expenses:,.2f}")
c3.metric("Net cash flow", f"${net:,.2f}")
c4.metric("Anomalies flagged", anomaly_count)

st.divider()

# ---------------------------------------------------------------- charts
daily = df.groupby("date").amount.sum().reset_index()
daily["cumulative"] = daily.amount.cumsum()
daily["day_type"] = daily.amount.apply(lambda x: "Net inflow" if x >= 0 else "Net outflow")

st.subheader("Daily net cash flow")
st.caption(
    "Each bar = total income minus total spending for that single day. "
    "Green = you took in more than you spent that day; red = you spent more than you took in."
)
fig_bar = px.bar(
    daily,
    x="date",
    y="amount",
    color="day_type",
    color_discrete_map={"Net inflow": "#2ca02c", "Net outflow": "#d62728"},
)
fig_bar.update_layout(margin=dict(l=0, r=0, t=10, b=0), showlegend=False)
st.plotly_chart(fig_bar, use_container_width=True)

col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Running balance")
    st.caption("The daily bars above, added up over time — shows whether your balance is trending up or down overall.")
    fig = px.line(daily, x="date", y="cumulative", markers=True)
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("Spending by category")
    st.caption("Where the expense side of the money went this month, as a share of total spending.")
    cat_spend = df[df.amount < 0].groupby("category").amount.sum().abs().reset_index()
    fig2 = px.pie(cat_spend, names="category", values="amount", hole=0.5)
    fig2.update_layout(margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig2, use_container_width=True)

st.divider()

# ---------------------------------------------------------------- map
st.subheader("📍 Spending map")

map_df = df.dropna(subset=["lat", "lng"]).copy()
map_df = map_df[map_df.amount < 0]  # expenses only

if map_df.empty:
    st.caption("No located transactions to show.")
else:
    st.caption("Bubble size = amount spent. Color = category. Hover a bubble for details.")

    map_df["abs_amount"] = map_df.amount.abs()
    map_df["amount_label"] = map_df.abs_amount.map(lambda x: f"${x:,.2f}")

    fig_map = px.scatter_mapbox(
        map_df,
        lat="lat",
        lon="lng",
        color="category",
        size="abs_amount",
        size_max=28,
        hover_name="merchant",
        custom_data=["amount_label", "category", "location_name"],
        color_discrete_sequence=px.colors.qualitative.Set2,
        zoom=10.5,
        height=500,
    )
    fig_map.update_traces(
        hovertemplate="<b>%{hovertext}</b><br>%{customdata[0]} — %{customdata[1]}<br>📍 %{customdata[2]}<extra></extra>"
    )
    fig_map.update_layout(mapbox_style="open-street-map", margin=dict(l=0, r=0, t=0, b=0))
    st.plotly_chart(fig_map, use_container_width=True)

st.divider()

# ---------------------------------------------------------------- budgets
st.subheader("Budget health")

current_month = df.date.max().strftime("%Y-%m") if len(df) else None
session = get_session()
budgets = (
    {b.category.name: b.allocated_amount for b in session.query(Budget).filter_by(month=current_month).all()}
    if current_month
    else {}
)
session.close()

expense_categories = sorted(df[df.amount < 0].category.unique())

if not budgets:
    st.caption("No budgets set for this month yet — set some below to see health gauges.")
else:
    bcols = st.columns(min(len(budgets), 4) or 1)
    for i, (cat_name, allocated) in enumerate(budgets.items()):
        spent = -df[(df.category == cat_name) & (df.amount < 0)].amount.sum()
        pct = spent / allocated if allocated else 0
        with bcols[i % len(bcols)]:
            st.metric(cat_name, f"${spent:,.0f} / ${allocated:,.0f}", delta=f"{pct:.0%} used", delta_color="inverse")
            st.progress(min(pct, 1.0))

with st.expander("Set monthly budgets"):
    with st.form("budget_form"):
        new_budgets = {
            cat: st.number_input(f"{cat} budget ($)", min_value=0.0, value=float(budgets.get(cat, 0)), step=10.0)
            for cat in expense_categories
        }
        submitted = st.form_submit_button("Save budgets")
        if submitted and current_month:
            session = get_session()
            for cat_name, amount in new_budgets.items():
                if amount <= 0:
                    continue
                category = session.query(Category).filter_by(name=cat_name).one()
                existing = session.query(Budget).filter_by(category_id=category.id, month=current_month).one_or_none()
                if existing:
                    existing.allocated_amount = amount
                else:
                    session.add(Budget(category_id=category.id, month=current_month, allocated_amount=amount))
            session.commit()
            session.close()
            st.success("Budgets saved.")
            st.rerun()

st.divider()

# ---------------------------------------------------------------- AI budget recommendation
target_month = _next_month_str(current_month) if current_month else None

if target_month:
    st.subheader("🎯 AI budget recommendation")
    st.caption(
        f"Have the AI analyze {current_month}'s actual income and spending, then recommend a budget "
        f"for {target_month} — like a financial advisor reviewing last month's statement."
    )

    if st.button("🤖 Generate AI budget recommendation"):
        with st.spinner("Analyzing spending and drafting a budget..."):
            try:
                recommend_budgets(month=current_month)
                st.success(f"Recommended {target_month} budget saved.")
                st.rerun()
            except Exception as e:
                st.error(f"Could not generate recommendation: {e}")

    session = get_session()
    recommended = {
        b.category.name: b.allocated_amount for b in session.query(Budget).filter_by(month=target_month).all()
    }
    last_recommendation = (
        session.query(AgentAction)
        .filter_by(action_type="budget_recommendation")
        .order_by(AgentAction.timestamp.desc())
        .first()
    )
    reasoning_text = last_recommendation.reasoning if last_recommendation else None
    session.close()

    if recommended:
        if reasoning_text:
            st.info(md_safe(reasoning_text))

        actual_spend = df[df.amount < 0].groupby("category").amount.sum().abs().to_dict()
        comparison = pd.DataFrame(
            [
                {
                    "category": cat,
                    f"{current_month} actual": actual_spend.get(cat, 0.0),
                    f"{target_month} recommended": amount,
                }
                for cat, amount in recommended.items()
            ]
        )
        st.dataframe(comparison, use_container_width=True, hide_index=True)

        fig_cmp = px.bar(
            comparison.melt(id_vars="category", var_name="type", value_name="amount"),
            x="category",
            y="amount",
            color="type",
            barmode="group",
        )
        fig_cmp.update_layout(margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig_cmp, use_container_width=True)
    else:
        st.caption("No recommendation generated yet.")

st.divider()

# ---------------------------------------------------------------- anomalies
st.subheader("🚩 Flagged anomalies")
anomalies_df = df[df.is_anomaly]
if anomalies_df.empty:
    st.caption("No anomalies flagged.")
else:
    st.dataframe(
        anomalies_df[["date", "merchant", "amount", "category", "anomaly_reason"]],
        use_container_width=True,
        hide_index=True,
    )

st.divider()

# ---------------------------------------------------------------- agent activity feed
st.subheader("🤖 Agent activity feed")
ACTION_ICONS = {
    "flag_anomaly": "🚩",
    "import": "📥",
    "budget_recommendation": "🎯",
    "categorize": "🏷️",
}
for action in actions:
    icon = ACTION_ICONS.get(action.action_type, "🏷️")
    st.markdown(f"{icon} **{md_safe(action.summary)}**")
    if action.reasoning:
        st.caption(md_safe(action.reasoning))
