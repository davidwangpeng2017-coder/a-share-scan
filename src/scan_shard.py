import argparse
import os
import time
from pathlib import Path

import akshare as ak
import baostock as bs
import pandas as pd

from common import START_DATE, END_DATE, baostock_code, calc_metrics


def fetch_baostock_history(code: str):
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(lg.error_msg)

    rs = bs.query_history_k_data_plus(
        baostock_code(code),
        "date,open,high,low,close,volume,amount",
        start_date=f"{START_DATE[:4]}-{START_DATE[4:6]}-{START_DATE[6:]}",
        end_date=f"{END_DATE[:4]}-{END_DATE[4:6]}-{END_DATE[6:]}",
        frequency="d",
        adjustflag="2",
    )

    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())

    bs.logout()

    if not rows:
        raise RuntimeError("BaoStock history empty")

    df = pd.DataFrame(rows, columns=rs.fields)
    df = df.rename(columns={
        "date": "日期",
        "open": "开盘",
        "high": "最高",
        "low": "最低",
        "close": "收盘",
        "volume": "成交量",
        "amount": "成交额",
    })
    return df, "BaoStock"


def fetch_akshare_history(code: str):
    df = ak.stock_zh_a_hist(
        symbol=code,
        period="daily",
        start_date=START_DATE,
        end_date=END_DATE,
        adjust="qfq",
    )
    if df is None or df.empty:
        raise RuntimeError("AKShare history empty")
    return df, "AKShare"


def combined_fetcher(code: str):
    errors = []

    if not code.startswith(("43", "83", "87", "88", "92")):
        try:
            return fetch_baostock_history(code)
        except Exception as exc:
            errors.append(f"BaoStock: {exc}")

    for attempt in range(1, 3):
        try:
            return fetch_akshare_history(code)
        except Exception as exc:
            errors.append(f"AKShare-{attempt}: {exc}")
            time.sleep(attempt * 2)

    raise RuntimeError(" | ".join(errors))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard", type=int, required=True)
    parser.add_argument("--shards", type=int, default=20)
    parser.add_argument("--universe", default="input/universe.csv")
    parser.add_argument("--out-dir", default="output")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    universe = pd.read_csv(args.universe, dtype={"代码": str})
    universe["代码"] = universe["代码"].str.zfill(6)

    shard_df = universe.iloc[args.shard::args.shards].copy()
    print(f"Shard {args.shard}: {len(shard_df)} stocks")

    results = []
    for idx, row in shard_df.iterrows():
        result = calc_metrics(
            code=row["代码"],
            name=str(row.get("名称", "")),
            market=str(row.get("市场", "")),
            fetcher=combined_fetcher,
        )
        results.append(result)

        if len(results) % 25 == 0:
            pd.DataFrame(results).to_csv(
                out_dir / f"shard_{args.shard:02d}_checkpoint.csv",
                index=False,
                encoding="utf-8-sig",
            )
            print(f"Shard {args.shard}: completed {len(results)}/{len(shard_df)}")

    result_df = pd.DataFrame(results)
    result_df.to_csv(
        out_dir / f"shard_{args.shard:02d}.csv",
        index=False,
        encoding="utf-8-sig",
    )

    print(result_df["遍历状态"].value_counts(dropna=False))


if __name__ == "__main__":
    main()
