import os
import re
import time
import signal
from datetime import datetime, timedelta

import numpy as np
import pandas as pd


START_DATE = (datetime.utcnow() - timedelta(days=365 * 5 + 30)).strftime("%Y%m%d")
END_DATE = datetime.utcnow().strftime("%Y%m%d")
PER_STOCK_TIMEOUT = int(os.getenv("PER_STOCK_TIMEOUT", "25"))


class StockTimeoutError(Exception):
    pass


def timeout_handler(signum, frame):
    raise StockTimeoutError("single stock timeout")


def normalize_code(value: object) -> str:
    s = str(value).strip()
    s = re.sub(r"\.0$", "", s)
    return s.zfill(6)


def market_of(code: str) -> str:
    if code.startswith(("43", "83", "87", "88", "92")):
        return "北交所"
    if code.startswith(("60", "68", "90")):
        return "沪市"
    return "深市"


def baostock_code(code: str) -> str:
    if code.startswith(("60", "68", "90")):
        return f"sh.{code}"
    if code.startswith(("00", "30", "20")):
        return f"sz.{code}"
    return code


def calc_metrics(code: str, name: str, market: str, fetcher) -> dict:
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(PER_STOCK_TIMEOUT)
    try:
        df, source = fetcher(code)
        signal.alarm(0)

        if df is None or len(df) < 60:
            return {
                "代码": code,
                "名称": name,
                "市场": market,
                "遍历状态": "数据不足",
                "错误信息": f"仅{0 if df is None else len(df)}个交易日",
            }

        df = df.copy()
        df["日期"] = pd.to_datetime(df["日期"])
        for c in ["开盘", "收盘", "最高", "最低", "成交量", "成交额"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        df = df.dropna(subset=["收盘"]).sort_values("日期")
        close = df["收盘"]
        high = df["最高"] if "最高" in df.columns else close
        amount = df["成交额"] if "成交额" in df.columns else pd.Series(np.nan, index=df.index)

        last = float(close.iloc[-1])
        running_max = close.cummax()
        drawdown = close / running_max - 1

        def ret(n):
            return float(last / close.iloc[-n] - 1) if len(close) >= n else np.nan

        ma20 = close.tail(20).mean()
        ma60 = close.tail(60).mean()
        ma120 = close.tail(120).mean() if len(close) >= 120 else np.nan
        ma250 = close.tail(250).mean() if len(close) >= 250 else np.nan

        mas = [x for x in [ma20, ma60, ma120] if pd.notna(x)]
        ma_spread = max(mas) / min(mas) - 1 if len(mas) >= 2 and min(mas) > 0 else np.nan

        avg20 = amount.tail(20).mean() if amount.notna().sum() >= 20 else np.nan
        avg60 = amount.tail(60).mean() if amount.notna().sum() >= 60 else np.nan
        vol_ratio = avg20 / avg60 if pd.notna(avg20) and pd.notna(avg60) and avg60 > 0 else np.nan

        low250 = close.tail(250).min() if len(close) >= 250 else close.min()
        high250 = close.tail(250).max() if len(close) >= 250 else close.max()
        pos250 = (last - low250) / (high250 - low250) if high250 > low250 else np.nan
        range120 = close.tail(120).max() / close.tail(120).min() - 1 if len(close) >= 120 else np.nan
        annual_vol = close.pct_change().dropna().tail(250).std() * np.sqrt(250)

        return {
            "代码": code,
            "名称": name,
            "市场": market,
            "遍历状态": "成功",
            "历史数据源": source,
            "交易日数": len(df),
            "历史末日": str(df["日期"].iloc[-1].date()),
            "历史末价": last,
            "距5年最高价回撤": last / float(high.max()) - 1,
            "5年最大回撤": float(drawdown.min()),
            "近20日收益": ret(20),
            "近60日收益": ret(60),
            "近120日收益": ret(120),
            "近250日收益": ret(250),
            "MA20": ma20,
            "MA60": ma60,
            "MA120": ma120,
            "MA250": ma250,
            "MA20偏离": last / ma20 - 1 if ma20 else np.nan,
            "MA60偏离": last / ma60 - 1 if ma60 else np.nan,
            "均线粘合度": ma_spread,
            "20日平均成交额": avg20,
            "60日平均成交额": avg60,
            "量能20比60": vol_ratio,
            "年化波动率": annual_vol,
            "近250日位置": pos250,
            "近120日区间": range120,
            "错误信息": "",
        }

    except StockTimeoutError:
        signal.alarm(0)
        return {
            "代码": code,
            "名称": name,
            "市场": market,
            "遍历状态": "超时",
            "错误信息": f"超过{PER_STOCK_TIMEOUT}秒",
        }
    except Exception as exc:
        signal.alarm(0)
        return {
            "代码": code,
            "名称": name,
            "市场": market,
            "遍历状态": "失败",
            "错误信息": f"{type(exc).__name__}: {str(exc)[:240]}",
        }
