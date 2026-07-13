import json
import os
import time
from pathlib import Path

import akshare as ak
import baostock as bs
import pandas as pd

from common import normalize_code, market_of


OUT = Path(os.getenv("OUT_DIR", "output"))
OUT.mkdir(parents=True, exist_ok=True)


def fetch_baostock_universe() -> pd.DataFrame:
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"BaoStock login failed: {lg.error_msg}")

    rs = bs.query_stock_basic()
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    bs.logout()

    df = pd.DataFrame(rows, columns=rs.fields)
    if df.empty:
        raise RuntimeError("BaoStock universe empty")

    df = df[df["type"] == "1"].copy()
    df["代码"] = df["code"].str.split(".").str[-1].map(normalize_code)
    df["名称"] = df["code_name"].astype(str)
    df["市场"] = df["代码"].map(market_of)
    return df[["代码", "名称", "市场"]]


def fetch_bse_universe() -> pd.DataFrame:
    errors = []
    candidates = [
        "stock_info_bj_name_code",
        "stock_bj_a_spot_em",
        "stock_zh_a_spot_em",
    ]

    for func_name in candidates:
        if not hasattr(ak, func_name):
            continue
        fn = getattr(ak, func_name)

        for attempt in range(1, 4):
            try:
                df = fn()
                if df is None or df.empty:
                    continue

                code_col = next((c for c in df.columns if "代码" in str(c)), None)
                name_col = next((c for c in df.columns if "名称" in str(c) or "简称" in str(c)), None)
                if code_col is None:
                    continue

                out = pd.DataFrame()
                out["代码"] = df[code_col].map(normalize_code)
                out["名称"] = df[name_col].astype(str) if name_col else ""
                out = out[out["代码"].str.startswith(("43", "83", "87", "88", "92"))]
                out["市场"] = "北交所"

                if len(out) >= 100:
                    return out[["代码", "名称", "市场"]].drop_duplicates("代码")
            except Exception as exc:
                errors.append(f"{func_name}-{attempt}: {exc}")
                time.sleep(attempt * 2)

    print("BSE universe warning:", errors)
    return pd.DataFrame(columns=["代码", "名称", "市场"])


def main():
    frames = []

    try:
        frames.append(fetch_baostock_universe())
    except Exception as exc:
        print("BaoStock universe failed:", exc)

    bse = fetch_bse_universe()
    if not bse.empty:
        frames.append(bse)

    if not frames:
        raise RuntimeError("All universe sources failed")

    universe = pd.concat(frames, ignore_index=True)
    universe["代码"] = universe["代码"].map(normalize_code)
    universe = universe.drop_duplicates("代码").sort_values("代码").reset_index(drop=True)

    universe.to_csv(OUT / "universe.csv", index=False, encoding="utf-8-sig")

    report = {
        "total": int(len(universe)),
        "markets": universe["市场"].value_counts().to_dict(),
    }
    (OUT / "universe_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if len(universe) < 4500:
        raise RuntimeError(f"Universe too small: {len(universe)}")


if __name__ == "__main__":
    main()
