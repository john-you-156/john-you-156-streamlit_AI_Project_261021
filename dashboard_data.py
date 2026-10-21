"""CSV validation and aggregations shared by the dashboard and tests."""
from io import BytesIO

import pandas as pd

SENSORS = {"온도_C": "온도 (℃)", "진동_mm_s": "진동 (mm/s)", "전류_A": "전류 (A)", "부하율_pct": "부하율 (%)"}
EQUIPMENT_REQUIRED = ["측정시각", "설비ID", "온도_C", "AI결과", "목표시각", "다음온도_C", "AI예측온도_C"]
STATION_REQUIRED = ["일자", "역명", "요일구분", "승차건수", "하차건수", "민원건수"]


def read_csv(raw):
    try:
        return pd.read_csv(BytesIO(raw), encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(BytesIO(raw), encoding="cp949")


def prepare_data(raw, kind="equipment"):
    df = read_csv(raw)
    df.columns = df.columns.str.strip()
    required = EQUIPMENT_REQUIRED if kind == "equipment" else STATION_REQUIRED
    missing = [c for c in required if c not in df]
    if missing:
        raise ValueError("필수 열 누락: " + ", ".join(missing))
    date_col, id_col = ("측정시각", "설비ID") if kind == "equipment" else ("일자", "역명")
    date_columns = ["측정시각", "목표시각"] if kind == "equipment" else ["일자"]
    for c in date_columns:
        parsed = pd.to_datetime(df[c], errors="coerce")
        if not pd.api.types.is_datetime64_any_dtype(parsed):
            raise ValueError(f"{c}: 날짜 형식 또는 시간대를 통일해 주세요.")
        if parsed.dt.tz is not None:
            parsed = parsed.dt.tz_localize(None)
        df[c] = parsed
    df[id_col] = df[id_col].astype("string").str.strip().replace("", pd.NA)
    labels = ["AI결과", "규칙결과"] if kind == "equipment" else ["요일구분"]
    for c in labels:
        if c in df:
            df[c] = df[c].astype("string").str.strip().replace("", pd.NA)
    numeric = list(SENSORS) + ["이동평균_C", "다음온도_C", "AI예측온도_C"] if kind == "equipment" else ["승차건수", "하차건수", "민원건수"]
    for c in numeric:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce").replace([float("inf"), -float("inf")], float("nan"))
            if kind == "station":
                df.loc[(df[c] < 0) | (df[c] % 1 != 0), c] = float("nan")
    valid = df.dropna(subset=[date_col, id_col]).copy()
    quality = {"original": len(df), "excluded": len(df) - len(valid), "duplicates": int(valid.duplicated([id_col, date_col]).sum())}
    if kind == "equipment":
        valid["AI확인후보"] = valid["AI결과"].eq("확인후보").fillna(False)
        valid["규칙확인후보"] = valid["규칙결과"].eq("확인후보").fillna(False) if "규칙결과" in valid else False
        valid["절대오차_C"] = (valid["다음온도_C"] - valid["AI예측온도_C"]).abs()
    else:
        valid["승하차건수"] = valid["승차건수"] + valid["하차건수"]
    return valid.sort_values([id_col, date_col]).reset_index(drop=True), quality


def filter_period(df, id_col, ids, date_col, start, end):
    return df[df[id_col].isin(ids) & df[date_col].dt.date.between(start, end)].copy()


def prediction_metrics(df):
    paired = df.dropna(subset=["다음온도_C", "AI예측온도_C"])
    error = paired["AI예측온도_C"] - paired["다음온도_C"]
    return {"count": len(paired), "mae": error.abs().mean(), "rmse": (error.pow(2).mean()) ** 0.5, "bias": error.mean()}


def equipment_summary(df):
    return df.groupby("설비ID", as_index=False).agg(
        조회건수=("측정시각", "size"), AI확인후보=("AI확인후보", "sum"),
        평균온도=("온도_C", "mean"), 최고온도=("온도_C", "max"), MAE=("절대오차_C", "mean"),
    ).assign(확인후보비율=lambda x: x["AI확인후보"] / x["조회건수"] * 100)


def station_summary(df):
    result = df.groupby("역명")[["승차건수", "하차건수", "승하차건수", "민원건수"]].sum(min_count=1)
    # Rate uses only rows with BOTH a valid passenger denominator and complaints.
    pairs = df.dropna(subset=["승하차건수", "민원건수"])
    denominators = pairs.groupby("역명")[["승하차건수", "민원건수"]].sum(min_count=1)
    rate = denominators["민원건수"].div(denominators["승하차건수"].where(denominators["승하차건수"] > 0)) * 10000
    result["1만건당민원"] = rate
    return result.reset_index()


def export_csv(df):
    # Keep spreadsheet applications from treating user-provided text as formulas.
    safe = df.copy()
    for c in safe.select_dtypes(include=["object", "string"]).columns:
        safe[c] = safe[c].map(lambda v: "'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v)
    return safe.to_csv(index=False).encode("utf-8-sig")
