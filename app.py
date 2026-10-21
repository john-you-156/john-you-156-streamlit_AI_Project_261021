
import pandas as pd
import streamlit as st
import plotly.express as px

# 페이지 설정: 화면을 넓게 사용
st.set_page_config(
    page_title="철도 설비 분석",
    page_icon="🚆",
    layout="wide",
)

# 데이터 읽기: 화면 조작 때마다 파일을 다시 읽지 않도록 캐시
@st.cache_data
def load_data(path):
    data = pd.read_csv(path)
    data["측정시각"] = pd.to_datetime(data["측정시각"])
    data["목표시각"] = pd.to_datetime(data["목표시각"])
    return data.sort_values("측정시각")


df = load_data("analysis_result.csv")

if df.empty:
    st.warning("조회할 데이터가 없습니다.")
    st.stop()

equipment_list = df["설비ID"].dropna().unique().tolist()

if not equipment_list or df["측정시각"].dropna().empty:
    st.warning("설비ID 또는 측정시각을 확인하세요.")
    st.stop()

first_date = df["측정시각"].min().date()
last_date = df["측정시각"].max().date()

# 처음 접속했을 때의 조회 조건
if "applied_filters" not in st.session_state:
    st.session_state.applied_filters = (
        equipment_list[0], first_date, last_date
    )

# 사이드바: 조건을 한 번에 적용
with st.sidebar:
    st.header("조회 조건")
    st.caption(f"자료 기간: {first_date} ~ {last_date}")

    with st.form("filter_form"):
        selected_equipment = st.selectbox(
            "설비선택", equipment_list
        )
        selected_start = st.date_input(
            "시작일",
            value=first_date,
            min_value=first_date,
            max_value=last_date,
        )
        selected_end = st.date_input(
            "종료일",
            value=last_date,
            min_value=first_date,
            max_value=last_date,
        )
        submitted = st.form_submit_button(
            "조회 적용", use_container_width=True
        )

    if submitted:
        if selected_start > selected_end:
            st.error("시작일은 종료일보다 늦을 수 없습니다.")
        else:
            st.session_state.applied_filters = (
                selected_equipment,
                selected_start,
                selected_end,
            )

    st.caption("조건을 변경한 뒤 ‘조회 적용’을 누르세요.")

equipment, start, end = st.session_state.applied_filters

# 조회 조건 적용
view = df[
    (df["설비ID"] == equipment)
    & (df["측정시각"].dt.date >= start)
    & (df["측정시각"].dt.date <= end)
].copy()

# 제목과 현재 적용된 조건
st.title("🚆 철도 설비 분석 대시보드")
st.caption(
    "by POWER629 · 교육용 가상 자료이며, AI 확인후보는 고장 확정이 아닙니다."
)
st.info(f"현재 조회: {equipment}  |  {start} ~ {end}")

if view.empty:
    st.warning("조회 결과가 없습니다. 사이드바에서 조건을 변경하세요.")
    st.stop()

# 공통 계산
candidates = view[view["AI결과"] == "확인후보"]
pred = view.dropna(
    subset=["다음온도_C", "AI예측온도_C"]
).sort_values("목표시각")

mae = (pred["다음온도_C"] - pred["AI예측온도_C"]).abs().mean()
mae_text = f"{mae:.2f} ℃" if not pred.empty else "비교 자료 없음"
candidate_rate = len(candidates) / len(view) * 100

# 핵심 수치를 화면 상단에 배치
col1, col2, col3, col4 = st.columns(4)

col1.metric("조회 자료", f"{len(view):,}건")
col2.metric("AI 확인후보", f"{len(candidates):,}건")
col3.metric("확인후보 비율", f"{candidate_rate:.1f}%")
col4.metric("온도 예측 오차(MAE)", mae_text)

# 세 가지 작업 탭
tab1, tab2, tab3 = st.tabs([
    "🔎 AI 점검 후보",
    "🌡️ 다음 1시간 온도 예측",
    "📝 업무 검토 및 저장",
])

with tab1:
    st.subheader("온도 추이와 점검 후보")

    fig = px.line(
        view,
        x="측정시각",
        y="온도_C",
        labels={"측정시각": "측정 시각", "온도_C": "온도(℃)"},
    )
    fig.add_scatter(
        x=candidates["측정시각"],
        y=candidates["온도_C"],
        mode="markers",
        name="AI 확인후보",
        marker=dict(color="red", size=9),
    )
    fig.update_layout(
        height=380,
        margin=dict(l=20, r=20, t=30, b=20),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)

    if candidates.empty:
        st.success("선택한 기간에 AI 확인후보가 없습니다.")
    else:
        st.write(f"**검토할 후보: {len(candidates):,}건**")
        st.dataframe(
            candidates.sort_values("측정시각", ascending=False),
            use_container_width=True,
            hide_index=True,
        )

    with st.expander("AI 판정별 건수 보기"):
        counts = (
            view["AI결과"]
            .value_counts()
            .rename_axis("AI 판정")
            .reset_index(name="건수")
        )
        st.dataframe(
            counts, use_container_width=True, hide_index=True
        )

with tab2:
    st.subheader("실제 온도와 AI 예측 온도")
    st.caption(
        f"비교 자료 {len(pred):,}건 · "
        "MAE는 실제 온도와 예측 온도의 차이를 절댓값으로 평균한 값입니다."
    )

    if pred.empty:
        st.info("선택한 기간에 실제 온도와 예측 온도를 비교할 자료가 없습니다.")
    else:
        fig2 = px.line(
            pred,
            x="목표시각",
            y=["다음온도_C", "AI예측온도_C"],
            labels={
                "목표시각": "예측 대상 시각",
                "value": "온도(℃)",
                "variable": "구분",
            },
        )
        fig2.update_layout(
            height=380,
            margin=dict(l=20, r=20, t=30, b=20),
            hovermode="x unified",
            legend_title_text="",
        )
        st.plotly_chart(fig2, use_container_width=True)

        with st.expander("예측 비교 자료 보기"):
            st.dataframe(
                pred[[
                    "목표시각", "다음온도_C", "AI예측온도_C"
                ]],
                use_container_width=True,
                hide_index=True,
            )

with tab3:
    st.subheader("업무 검토 및 저장")

    note = st.text_area(
        "확인할 사항 및 조치 제안",
        value="센서 상태와 운전 조건을 확인한 후 담당자 검토가 필요합니다.",
        height=130,
        key=f"work_note_{equipment}",
    )

    report = f"""설비: {equipment}
조회 기간: {start} ~ {end}
조회 건수: {len(view)}건
AI 확인후보: {len(candidates)}건
확인후보 비율: {candidate_rate:.1f}%
온도 예측 MAE: {mae_text} ({len(pred)}건 비교)
업무 메모: {note}
교육용 가상 자료이며, 확인후보는 고장 확정이 아닙니다."""

    with st.expander("보고서 미리보기", expanded=True):
        st.text(report)

    download1, download2, download3 = st.columns(3)

    with download1:
        st.download_button(
            "📥 조회 결과 CSV",
            data=view.to_csv(index=False).encode("utf-8-sig"),
            file_name="dashboard_result.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with download2:
        st.download_button(
            "📥 점검 후보 CSV",
            data=candidates.to_csv(index=False).encode("utf-8-sig"),
            file_name="inspection_candidates.csv",
            mime="text/csv",
            use_container_width=True,
        )

    with download3:
        st.download_button(
            "📥 보고서 TXT",
            data=report.encode("utf-8-sig"),
            file_name="dashboard_report.txt",
            mime="text/plain",
            use_container_width=True,
        )

# 긴 표는 필요할 때만 펼쳐서 확인
with st.expander(f"현재 조회 데이터 전체 보기 · {len(view):,}건"):
    st.dataframe(
        view, use_container_width=True, hide_index=True
    )

with st.expander("원본 데이터 미리보기"):
    st.caption(f"원본 전체 {len(df):,}건 중 첫 10건")
    st.dataframe(
        df.head(10), use_container_width=True, hide_index=True
    )
