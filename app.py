"""Railway operations dashboard. Run: streamlit run app.py"""
from hashlib import sha256
from html import escape
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard_data import (
    SENSORS, prepare_data, filter_period, prediction_metrics,
    equipment_summary, station_summary, export_csv,
)

ROOT = Path(__file__).resolve().parent
COLORS = ["#2563EB", "#0D9488", "#F59E0B", "#8B5CF6", "#E11D48"]
st.set_page_config(page_title="RAIL INSIGHT · 철도 운영 분석", page_icon="🚆", layout="wide")
st.markdown("""
<style>
.block-container {max-width:1440px; padding-top:2rem;}
.rail-hero {background:linear-gradient(115deg,#10284b,#214d7c);color:white;
 padding:26px 32px;border-radius:18px;margin-bottom:24px;}
.rail-hero .eyebrow {font-size:12px;letter-spacing:3px;color:#a8c9f6;font-weight:700;}
.rail-hero h1 {color:white;font-size:30px;line-height:1.35;padding:8px 0;}
.rail-hero p {color:#d5e3f5;margin:0;font-size:14px;}
[data-testid="stMetric"] {background:var(--secondary-background-color);
 border:1px solid #cbd5e155;border-radius:14px;padding:16px 18px;}
[data-testid="stMetricValue"] {font-size:1.8rem;}
[data-testid="stTabs"] button {font-weight:600;}
[data-testid="stSidebarUserContent"] {padding-top:1.5rem;}
@media(max-width:640px){.rail-hero{padding:20px}.rail-hero h1{font-size:24px}}
</style>
""", unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def load(raw, kind):
    return prepare_data(raw, kind)


def chart(fig, key, height=350):
    fig.update_layout(
        height=height, margin=dict(l=12, r=12, t=35, b=12),
        font=dict(family="Malgun Gothic, Apple SD Gothic Neo, sans-serif", size=12),
        legend=dict(orientation="h", y=1.12, x=0), legend_title_text="",
        hovermode="x unified",
    )
    st.plotly_chart(fig, width="stretch", key=key,
                    config={"displaylogo": False, "toImageButtonOptions": {"format": "png", "scale": 2}})


def table(df, height=None):
    kwargs = {"height": height} if height else {}
    st.dataframe(df, hide_index=True, width="stretch", **kwargs)


def number(value, decimals=1, suffix=""):
    return "자료 없음" if pd.isna(value) else f"{value:,.{decimals}f}{suffix}"


def hero(title, subtitle):
    st.markdown(f'<div class="rail-hero"><div class="eyebrow">RAIL INSIGHT / POWER629</div>'
                f'<h1>{escape(title)}</h1><p>{escape(subtitle)}</p></div>', unsafe_allow_html=True)


def quality_panel(df, quality, prefix):
    with st.expander("데이터 품질 · 누락값과 중복 확인"):
        st.caption(f"원본 {quality['original']:,}행 · 날짜/식별자 누락 제외 {quality['excluded']:,}행 · "
                   f"동일 식별자·시각 중복 {quality['duplicates']:,}행 (자동 삭제하지 않음)")
        missing = df.isna().sum().rename_axis("항목").reset_index(name="누락 건수")
        missing["누락 비율 (%)"] = missing["누락 건수"] / len(df) * 100
        table(missing.round(1))
        st.caption("누락 표는 현재 조회 범위 기준입니다. 계산에 필요한 값이 없는 행은 해당 계산에서 제외됩니다.")
        st.download_button("품질 요약 CSV", export_csv(missing), f"{prefix}_quality.csv", "text/csv")


def source_data(kind):
    filename = "analysis_result.csv" if kind == "equipment" else "station_daily_usage.csv"
    with st.sidebar.expander("데이터 파일 변경"):
        uploaded = st.file_uploader("다른 CSV로 분석", type=["csv"], key=f"upload_{kind}")
    path = ROOT / filename
    if uploaded is None and not path.is_file():
        st.info(f"사이드바에서 {filename} 파일을 업로드하세요.")
        st.stop()
    raw = uploaded.getvalue() if uploaded is not None else path.read_bytes()
    try:
        df, quality = load(raw, kind)
    except (ValueError, UnicodeError, pd.errors.ParserError) as exc:
        st.error(f"데이터를 확인해 주세요. {exc}")
        st.stop()
    if df.empty:
        st.warning("유효한 날짜와 식별자를 가진 자료가 없습니다.")
        st.stop()
    st.sidebar.caption(f"파일: {uploaded.name if uploaded else filename}")
    return df, quality, sha256(raw).hexdigest()[:16]


def filters(df, kind, fingerprint):
    id_col, date_col = ("설비ID", "측정시각") if kind == "equipment" else ("역명", "일자")
    ids = sorted(df[id_col].unique().tolist())
    first, last = df[date_col].min().date(), df[date_col].max().date()
    key = f"{kind}_{fingerprint}"
    state_key = "applied_" + key
    st.session_state.setdefault(state_key, (ids, first, last))
    applied_ids, applied_start, applied_end = st.session_state[state_key]
    with st.sidebar:
        st.divider()
        st.subheader("조회 조건")
        st.caption(f"자료 기간: {first} ~ {last}")
        with st.form("filters_" + key):
            selected = st.multiselect("설비선택" if kind == "equipment" else "역 선택",
                                      ids, default=applied_ids)
            start = st.date_input("시작일", applied_start, min_value=first, max_value=last)
            end = st.date_input("종료일", applied_end, min_value=first, max_value=last)
            apply = st.form_submit_button("조회 적용", type="primary", width="stretch")
        if apply:
            if not selected:
                st.error("하나 이상 선택하세요. 기존 결과를 유지합니다.")
            elif start > end:
                st.error("시작일은 종료일보다 늦을 수 없습니다. 기존 결과를 유지합니다.")
            else:
                st.session_state[state_key] = (selected, start, end)
        st.caption("조건 변경 후 조회 적용을 누르세요.")
    selected, start, end = st.session_state[state_key]
    view = filter_period(df, id_col, selected, date_col, start, end)
    st.caption(f"적용 조건  ·  {', '.join(selected)}  /  {start} ~ {end}  /  {len(view):,}행")
    if view.empty:
        st.info("선택한 조건에 자료가 없습니다. 사이드바에서 조건을 변경하세요.")
        st.stop()
    return view, selected, start, end


def report_panel(view, candidates, summary, fingerprint, selected, start, end):
    st.subheader("검토 내용을 기록하고 결과를 보관하세요")
    context = fingerprint + "|" + ",".join(sorted(selected)) + f"|{start}|{end}"
    memo_key = sha256(context.encode()).hexdigest()[:16]
    saved = st.session_state.setdefault("saved_reviews", {})
    review = saved.get(memo_key, {"note": "", "status": "검토 전"})
    left, right = st.columns([1, 1])
    with left:
        with st.form("review_" + memo_key):
            status = st.selectbox("검토 상태", ["검토 전", "검토 중", "검토 완료"],
                                  index=["검토 전", "검토 중", "검토 완료"].index(review["status"]))
            note = st.text_area("확인 사항 및 조치 제안", value=review["note"], height=180,
                                placeholder="예: 진동이 증가한 시간대의 센서 상태와 운전 조건 확인")
            if st.form_submit_button("보고서에 반영", type="primary"):
                saved[memo_key] = {"note": note, "status": status}
                review = saved[memo_key]
                st.success("보고서에 반영했습니다.")
        st.caption("수정 후 반영 버튼을 누르세요. 메모는 현재 접속 세션에서만 유지됩니다.")
    stats = prediction_metrics(view)
    report = f"""철도 설비 검토 보고서
설비: {', '.join(selected)}
측정 기간: {start} ~ {end}
조회 자료: {len(view):,}건
AI 확인후보: {len(candidates):,}건 ({len(candidates) / len(view) * 100:.1f}%)
예측 MAE: {number(stats['mae'], 2, ' ℃')} / 비교 {stats['count']:,}건
검토 상태: {review['status']}

업무 메모:
{review['note'] or '작성된 메모가 없습니다.'}

교육용 가상 자료이며, 확인후보는 고장 확정이 아닙니다.
CSV에 저장된 예측을 비교한 결과이며 새 예측 모델을 실행하지 않습니다.
"""
    with right:
        st.markdown("**내려받을 보고서**")
        st.text(report)
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("조회결과.csv", export_csv(view))
        archive.writestr("확인후보.csv", export_csv(candidates))
        archive.writestr("설비요약.csv", export_csv(summary))
        archive.writestr("보고서.txt", report.encode("utf-8-sig"))
    filename = f"{start}_{end}_{memo_key[:6]}"
    a, b, c = st.columns(3)
    a.download_button("전체 결과 ZIP", buffer.getvalue(), f"rail_report_{filename}.zip", "application/zip", type="primary", width="stretch")
    b.download_button("확인후보 CSV", export_csv(candidates), f"candidates_{filename}.csv", "text/csv", width="stretch")
    c.download_button("보고서 TXT", report.encode("utf-8-sig"), f"report_{filename}.txt", "text/plain", width="stretch")
    with st.expander("조회 데이터 탐색 및 CSV 저장"):
        query = st.text_input("설비ID 검색", key="data_search")
        display = view[view["설비ID"].str.contains(query, case=False, regex=False, na=False)]
        columns = st.multiselect("표시할 열", view.columns.tolist(), default=view.columns.tolist()[:8], key="data_columns")
        if columns:
            table(display[columns], 320)
            st.download_button("현재 표 CSV", export_csv(display[columns]), f"filtered_{filename}.csv", "text/csv")
        else:
            st.info("표시할 열을 하나 이상 선택하세요.")


def equipment_page():
    hero("철도 설비 분석", "핵심 현황부터 센서 추이, AI 점검 후보와 예측 품질까지 한곳에서 확인하세요.")
    df, quality, fingerprint = source_data("equipment")
    view, selected, start, end = filters(df, "equipment", fingerprint)
    candidates = view[view["AI확인후보"]]
    metrics = prediction_metrics(view)
    summary = equipment_summary(view)
    a, b, c, d = st.columns(4)
    a.metric("조회 자료", f"{len(view):,}건", help=f"선택한 설비 {len(selected)}개")
    b.metric("AI 확인후보", f"{len(candidates):,}건", help="확인후보는 고장 확정이 아닙니다.")
    c.metric("확인후보 비율", f"{len(candidates) / len(view) * 100:.1f}%", help="현재 조회 행 전체를 분모로 계산합니다.")
    d.metric("예측 오차 MAE", number(metrics["mae"], 2, " ℃"), help=f"유효한 실제값·예측값 {metrics['count']}건 기준")
    st.write("")
    overview, sensors, inspection, forecast, reports = st.tabs(
        ["종합 현황", "센서 상세", "AI 점검 후보", "다음 1시간 온도 예측", "업무 검토 및 저장"])
    with overview:
        left, right = st.columns([2, 1])
        with left:
            st.subheader("온도 추이")
            fig = px.line(view, x="측정시각", y="온도_C", color="설비ID", color_discrete_sequence=COLORS,
                          labels={"온도_C": "온도 (℃)"})
            fig.add_scatter(x=candidates["측정시각"], y=candidates["온도_C"], mode="markers",
                            name="AI 확인후보", marker=dict(color="#E11D48", size=9, symbol="diamond"),
                            text=candidates["설비ID"], hovertemplate="%{text}<br>%{x}<br>%{y:.2f} ℃")
            chart(fig, "overview")
        with right:
            st.subheader("검토 포인트")
            with st.container(border=True):
                st.write(f"**AI 확인후보 {len(candidates):,}건**")
                if not candidates.empty:
                    recent = candidates.sort_values("측정시각").iloc[-1]
                    st.write(f"최근 후보: {recent['설비ID']}")
                    st.caption(recent["측정시각"].strftime("%Y-%m-%d %H:%M"))
                unavailable = view["AI결과"].isna() | view["AI결과"].eq("입력부족").fillna(False)
                st.write(f"**입력 부족·AI 판정 누락 {int(unavailable.sum()):,}건**")
                st.caption("후보는 센서와 운전 조건을 함께 검토하세요.")
            with st.container(border=True):
                st.write("**데이터 기준 시각**")
                st.write(view["측정시각"].max().strftime("%Y-%m-%d %H:%M"))
                st.caption("저장된 CSV 기준이며 실시간 관제 화면이 아닙니다.")
        st.subheader("설비별 비교")
        table(summary.rename(columns={"평균온도": "평균온도 (℃)", "최고온도": "최고온도 (℃)", "MAE": "MAE (℃)", "확인후보비율": "후보 비율 (%)"}).round(2))
        if len(summary) == 1:
            st.caption("현재 자료에는 선택한 설비 1개가 있습니다. 다른 설비가 포함된 CSV를 올리면 함께 비교할 수 있습니다.")
        quality_panel(view, quality, "equipment")
    with sensors:
        available = [c for c in SENSORS if c in view]
        sensor = st.selectbox("살펴볼 센서", available, format_func=lambda c: SENSORS[c])
        valid = view[sensor].dropna()
        a, b, c = st.columns(3)
        a.metric("평균", number(valid.mean(), 2))
        b.metric("최댓값", number(valid.max(), 2))
        c.metric("누락", f"{view[sensor].isna().sum():,}건")
        st.caption(f"단위: {SENSORS[sensor]} · 단위가 다른 센서는 개별 그래프로 확인합니다.")
        fig = px.line(view, x="측정시각", y=sensor, color="설비ID", color_discrete_sequence=COLORS, labels={sensor: SENSORS[sensor]})
        chart(fig, "sensor_detail")
        daily = view.assign(일자=view["측정시각"].dt.date).groupby(["일자", "설비ID"], as_index=False)[sensor].mean()
        with st.expander("일별 평균 보기"):
            table(daily.rename(columns={sensor: SENSORS[sensor]}).round(3))
    with inspection:
        st.subheader("AI와 규칙 판정을 함께 검토하세요")
        if "규칙결과" in view:
            ai_only = view["AI확인후보"] & ~view["규칙확인후보"]
            rule_only = ~view["AI확인후보"] & view["규칙확인후보"]
            both = view["AI확인후보"] & view["규칙확인후보"]
            modes = {"AI 확인후보 전체": view["AI확인후보"], "AI·규칙 모두 후보": both,
                     "AI만 후보": ai_only, "규칙만 후보": rule_only, "전체 자료": pd.Series(True, index=view.index)}
            a, b, c = st.columns(3)
            a.metric("AI·규칙 모두 후보", f"{both.sum():,}건")
            b.metric("AI만 후보", f"{ai_only.sum():,}건")
            c.metric("규칙만 후보", f"{rule_only.sum():,}건")
            st.caption("‘~만 후보’는 다른 판정이 확인후보가 아닌 행입니다. 확인불가·누락도 포함할 수 있으므로 상세 판정을 확인하세요.")
        else:
            modes = {"AI 확인후보 전체": view["AI확인후보"], "전체 자료": pd.Series(True, index=view.index)}
            st.info("규칙결과 열이 없어 AI 판정만 표시합니다.")
        mode = st.selectbox("점검 목록", list(modes))
        result = view[modes[mode]].sort_values("측정시각", ascending=False)
        st.caption(f"목록 {len(result):,}건 · 행 수는 고장 횟수가 아닙니다.")
        table(result, 360)
        st.download_button("현재 점검 목록 CSV", export_csv(result), f"inspection_{start}_{end}.csv", "text/csv")
        counts = view["AI결과"].fillna("판정 누락").value_counts().rename_axis("AI 판정").reset_index(name="건수")
        chart(px.bar(counts, x="AI 판정", y="건수", text="건수", color_discrete_sequence=COLORS), "ai_counts", 260)
    with forecast:
        st.subheader("예측 품질과 오차 분석")
        st.caption("조회는 측정시각 기준입니다. 목표시각은 선택한 종료일 이후일 수 있습니다. CSV에 저장된 예측값을 비교합니다.")
        a, b, c = st.columns(3)
        a.metric("RMSE", number(metrics["rmse"], 2, " ℃"), help="큰 오차에 더 민감한 지표입니다.")
        b.metric("평균 편향", number(metrics["bias"], 2, " ℃"), help="예측−실제의 평균. 양수는 높게, 음수는 낮게 예측한 경향입니다.")
        c.metric("비교 가능 자료", f"{metrics['count']:,} / {len(view):,}건")
        paired = view.dropna(subset=["다음온도_C", "AI예측온도_C"])
        if paired.empty:
            st.info("실제값과 예측값이 모두 있는 자료가 없습니다.")
        else:
            focus = st.selectbox("예측 그래프 설비", sorted(paired["설비ID"].unique()))
            focused = paired[paired["설비ID"] == focus]
            timed = focused.dropna(subset=["목표시각"]).sort_values("목표시각")
            if len(timed) < len(focused):
                st.warning(f"목표시각 누락 {len(focused) - len(timed)}건은 그래프에서 제외했습니다. 오차 지표에는 포함됩니다.")
            if not timed.empty:
                plot = timed.rename(columns={"다음온도_C": "실제 온도", "AI예측온도_C": "AI 예측"})
                chart(px.line(plot, x="목표시각", y=["실제 온도", "AI 예측"], color_discrete_sequence=COLORS,
                              labels={"value": "온도 (℃)", "variable": "구분"}), "prediction")
            with st.expander("오차가 큰 자료부터 확인", expanded=True):
                cols = ["설비ID", "측정시각", "목표시각", "다음온도_C", "AI예측온도_C", "절대오차_C"]
                table(paired.sort_values("절대오차_C", ascending=False)[cols].round(3), 260)
    with reports:
        report_panel(view, candidates, summary, fingerprint, selected, start, end)


def station_page():
    hero("역 이용 현황", "역별 승하차 추이와 민원을 비교하고, 평일·주말의 차이를 확인하세요.")
    df, quality, fingerprint = source_data("station")
    view, selected, start, end = filters(df, "station", fingerprint)
    day_type = st.radio("요일 구분", ["전체", "평일", "주말"], horizontal=True)
    if day_type != "전체":
        view = view[view["요일구분"] == day_type]
    if view.empty:
        st.info("선택한 요일 구분에 자료가 없습니다.")
        st.stop()
    summary = station_summary(view)
    a, b, c, d = st.columns(4)
    a.metric("승차", number(view["승차건수"].sum(min_count=1), 0, "건"))
    b.metric("하차", number(view["하차건수"].sum(min_count=1), 0, "건"))
    c.metric("민원", number(view["민원건수"].sum(min_count=1), 0, "건"))
    d.metric("조회 역", f"{view['역명'].nunique()}개")
    st.caption("승하차는 이용 건수이며 고유 이용자 수가 아닙니다. 설비 분석과 기간을 독립적으로 선택합니다.")
    trends, comparison, details = st.tabs(["이용 추이", "역별 비교", "데이터 및 저장"])
    with trends:
        measure = st.selectbox("표시 지표", ["승하차건수", "승차건수", "하차건수", "민원건수"])
        daily = view.groupby(["일자", "역명"], as_index=False)[measure].sum(min_count=1)
        chart(px.line(daily, x="일자", y=measure, color="역명", markers=True, color_discrete_sequence=COLORS), "station_trend", 400)
        st.subheader("평일·주말 일평균 비교")
        daily_type = view.groupby(["역명", "일자", "요일구분"], as_index=False)[measure].sum(min_count=1)
        average = daily_type.groupby(["역명", "요일구분"], as_index=False)[measure].mean()
        chart(px.bar(average, x="역명", y=measure, color="요일구분", barmode="group",
                     color_discrete_sequence=COLORS, labels={measure: "일평균 건수"}), "weekday", 300)
        st.caption(f"현재 조회 범위·요일 필터 기준입니다. 자료가 있는 날짜만 평균에 포함합니다. 평일·주말을 비교하려면 ‘전체’를 선택하세요.")
    with comparison:
        left, right = st.columns(2)
        with left:
            st.subheader("역별 승하차")
            chart(px.bar(summary.sort_values("승하차건수"), x="승하차건수", y="역명", orientation="h",
                         color_discrete_sequence=COLORS), "station_ranking", 320)
        with right:
            st.subheader("승하차 1만 건당 민원")
            chart(px.bar(summary.sort_values("1만건당민원"), x="1만건당민원", y="역명", orientation="h",
                         color_discrete_sequence=["#F59E0B"]), "complaints", 320)
        st.caption("민원율 = 민원 ÷ (승차+하차) × 10,000. 두 값이 모두 있는 행으로 계산하며, 승하차 합계가 0이면 비율을 표시하지 않습니다.")
        table(summary.round(2))
    with details:
        table(view, 350)
        left, right = st.columns(2)
        left.download_button("조회 자료 CSV", export_csv(view), f"station_{start}_{end}_{day_type}.csv", "text/csv", width="stretch")
        right.download_button("역별 요약 CSV", export_csv(summary), f"station_summary_{start}_{end}_{day_type}.csv", "text/csv", width="stretch")
        quality_panel(view, quality, "station")


with st.sidebar:
    st.markdown("### 🚆 RAIL INSIGHT")
    st.caption("철도 운영 데이터 워크스페이스")
    page = st.radio("분석 메뉴", ["설비 분석", "역 이용 현황"])
    st.divider()

if page == "설비 분석":
    equipment_page()
else:
    station_page()

st.divider()
st.caption("POWER629 · 교육용 가상 데이터 | AI 확인후보는 고장 확정이 아닙니다.")
