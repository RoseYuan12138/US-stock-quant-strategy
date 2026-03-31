"""
下载宏观数据
- FMP：国债收益率曲线（Premium 可用）
- FRED（免费）：GDP、CPI、联邦基金利率、失业率、非农就业

输出文件：
  cache/macro/treasury_rates.parquet
  cache/macro/fred_{series}.parquet
  cache/macro/macro_merged.parquet   ← 月度宏观特征表（供 regime_filter 使用）
"""
import os
import time
import pandas as pd
import requests
from fmp_client import get, ensure_cache_dir

MACRO_DIR = "macro"

FRED_SERIES = {
    "GDP":          ("GDP",       "quarterly"),   # 季度
    "CPI":          ("CPIAUCSL",  "monthly"),     # 月度
    "FEDFUNDS":     ("FEDFUNDS",  "monthly"),     # 月度
    "UNRATE":       ("UNRATE",    "monthly"),     # 月度
    "PAYEMS":       ("PAYEMS",    "monthly"),     # 月度非农
    "UMCSENT":      ("UMCSENT",   "monthly"),     # 密歇根消费者信心
    "INDPRO":       ("INDPRO",    "monthly"),     # 工业生产指数
}


# ─── FMP 国债收益率 ────────────────────────────────────────────────

def download_treasury_rates(start: str = "2010-01-01", force: bool = False) -> pd.DataFrame:
    out = os.path.join(ensure_cache_dir(MACRO_DIR), "treasury_rates.parquet")
    if not force and os.path.exists(out):
        print("  ✅ treasury_rates.parquet 已缓存，跳过")
        return pd.read_parquet(out)
    print("下载国债收益率曲线（FMP）...")
    end = pd.Timestamp.today().strftime("%Y-%m-%d")

    # FMP 限制单次时间范围，分年下载
    all_frames = []
    for year in range(int(start[:4]), int(end[:4]) + 1):
        y_start = f"{year}-01-01"
        y_end   = f"{year}-12-31"
        try:
            data = get("treasury-rates", **{"from": y_start, "to": y_end})
            if data:
                all_frames.append(pd.DataFrame(data))
            time.sleep(0.1)
        except Exception as e:
            print(f"  ⚠️ {year}: {e}")

    if not all_frames:
        print("  ❌ 无数据")
        return pd.DataFrame()

    df = pd.concat(all_frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    df = df.drop_duplicates("date").sort_values("date")

    # 计算关键利差
    if "year10" in df.columns and "year2" in df.columns:
        df["spread_10y2y"] = df["year10"] - df["year2"]
        df["yield_curve_inverted"] = (df["spread_10y2y"] < 0).astype(int)
    if "year10" in df.columns and "month3" in df.columns:
        df["spread_10y3m"] = df["year10"] - df["month3"]

    cache_dir = ensure_cache_dir(MACRO_DIR)
    out = os.path.join(cache_dir, "treasury_rates.parquet")
    df.to_parquet(out, index=False)
    print(f"  ✅ {len(df)} 条 ({df['date'].min().date()} ~ {df['date'].max().date()}) → {out}")
    return df


# ─── FRED 宏观指标 ─────────────────────────────────────────────────

def download_fred(series_id: str, name: str) -> pd.DataFrame:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    try:
        df = pd.read_csv(url)
        # FRED 列名可能是 DATE 或 observation_date
        date_col = [c for c in df.columns if c.lower() in ("date", "observation_date")][0]
        df = df.rename(columns={date_col: "date", series_id: name})
        df["date"] = pd.to_datetime(df["date"])
        df = df[df[name] != "."].copy()
        df[name] = pd.to_numeric(df[name], errors="coerce")
        df = df.dropna().sort_values("date")
        return df
    except Exception as e:
        print(f"  ❌ FRED {series_id}: {e}")
        return pd.DataFrame()


def download_all_fred() -> dict:
    print("下载宏观指标（FRED 免费）...")
    cache_dir = ensure_cache_dir(MACRO_DIR)
    dfs = {}
    for name, (series_id, freq) in FRED_SERIES.items():
        print(f"  {name} ({series_id})...", end=" ")
        df = download_fred(series_id, name)
        if not df.empty:
            out = os.path.join(cache_dir, f"fred_{name}.parquet")
            df.to_parquet(out, index=False)
            print(f"✅ {len(df)} 条")
            dfs[name] = df
        else:
            print("❌")
    return dfs


# ─── 合并为月度宏观特征表 ──────────────────────────────────────────

def build_macro_features(start: str = "2010-01-01") -> pd.DataFrame:
    """
    合并所有宏观数据为月末特征表，供 regime_filter.py 使用
    每行：一个月末日期，各宏观指标的最新值
    """
    print("构建月度宏观特征表...")
    cache_dir = ensure_cache_dir(MACRO_DIR)

    month_ends = pd.date_range(start, pd.Timestamp.today(), freq="ME")

    # 加载国债数据
    treasury_path = os.path.join(cache_dir, "treasury_rates.parquet")
    treasury = pd.read_parquet(treasury_path) if os.path.exists(treasury_path) else pd.DataFrame()

    # 加载 FRED 数据
    fred_dfs = {}
    for name in FRED_SERIES:
        p = os.path.join(cache_dir, f"fred_{name}.parquet")
        if os.path.exists(p):
            fred_dfs[name] = pd.read_parquet(p).set_index("date")

    rows = []
    for me in month_ends:
        me_str = me.strftime("%Y-%m-%d")
        row = {"date": me_str}

        # 国债：取月末最近一个交易日
        if not treasury.empty:
            past = treasury[treasury["date"] <= me]
            if not past.empty:
                latest = past.iloc[-1]
                for col in ["year2", "year10", "year30", "spread_10y2y",
                            "spread_10y3m", "yield_curve_inverted"]:
                    if col in latest:
                        row[f"treasury_{col}"] = latest[col]

        # FRED 指标：取月末最新值
        for name, df in fred_dfs.items():
            past = df[df.index <= me]
            if not past.empty:
                row[f"macro_{name}"] = past.iloc[-1][name]

        # 派生特征
        if "macro_CPI" in row and "macro_GDP" in row:
            row["macro_real_growth_proxy"] = row.get("macro_GDP", 0)

        rows.append(row)

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])

    # 计算同比变化
    for col in [c for c in df.columns if c.startswith("macro_")]:
        df[f"{col}_yoy"] = df[col].pct_change(12)

    out = os.path.join(ensure_cache_dir(), "macro_merged.parquet")
    df.to_parquet(out, index=False)
    print(f"✅ 月度宏观特征表：{len(df)} 行 × {len(df.columns)} 列 → {out}")
    return df


if __name__ == "__main__":
    download_treasury_rates()
    download_all_fred()
    build_macro_features()
