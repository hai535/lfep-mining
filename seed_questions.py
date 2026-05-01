"""Seed 100 deterministic Q+A into lfep.db using Binance public klines.

Idempotent: if questions table already has >= 100 rows, exits without doing
anything. Run once during initial deploy.

Question templates (computed answers, no LLM):
  T1 (30): "<asset> 1h kline high - low at <T> = ? USDT (integer)"
  T2 (25): "<asset> close at <T> in USDT, 4 decimals"
  T3 (20): "RSI(14) of <asset> 1h close ending at <T>, 2 decimals"
  T4 (15): "(close <A> - close <B>) / close <B> × 100 at <T>, 2 decimals"
  T5 (10): "Sum of 1h volumes of <asset> from <T1> to <T2> in base asset, integer"

All timestamps are random hourly UTC marks within the last 7..30 days, so the
1h kline at that mark is closed and stable.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import random
import sys
import time
import urllib.parse
import urllib.request

import db

ASSETS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]
BINANCE = "https://api.binance.com/api/v3/klines"


def fetch_klines(symbol: str, interval: str, start_ms: int, limit: int = 1) -> list[list]:
    qs = urllib.parse.urlencode({
        "symbol": symbol,
        "interval": interval,
        "startTime": start_ms,
        "limit": limit,
    })
    url = f"{BINANCE}?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": "lfep-seed/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def random_past_hour(min_days: int = 7, max_days: int = 30) -> dt.datetime:
    days_ago = random.uniform(min_days, max_days)
    target = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)
    # Floor to hour boundary so the kline is closed
    return target.replace(minute=0, second=0, microsecond=0)


def fmt_ts(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%d %H:00 UTC")


def asset_name(symbol: str) -> str:
    return symbol.replace("USDT", "")


def rsi_14(closes: list[float]) -> float:
    """Standard RSI on 15 closes (14 periods of change). Wilder smoothing not used;
    simple-mean variant for reproducibility — agents must match this exact method."""
    if len(closes) < 15:
        raise ValueError("need 15 closes for RSI(14)")
    gains = []
    losses = []
    for i in range(1, 15):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(-diff)
    avg_gain = sum(gains) / 14
    avg_loss = sum(losses) / 14
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def gen_t1_high_low_int(qid: int) -> tuple[str, str]:
    sym = random.choice(ASSETS)
    t = random_past_hour()
    start_ms = int(t.timestamp() * 1000)
    kl = fetch_klines(sym, "1h", start_ms, limit=1)[0]
    high = float(kl[2])
    low = float(kl[3])
    answer = str(int(round(high - low)))
    content = (
        f"On Binance, {asset_name(sym)}/USDT 1h kline starting at "
        f"{fmt_ts(t)}: (high - low) rounded to integer USDT = ?"
    )
    return content, answer


def gen_t2_close_4dp(qid: int) -> tuple[str, str]:
    sym = random.choice(ASSETS)
    t = random_past_hour()
    start_ms = int(t.timestamp() * 1000)
    kl = fetch_klines(sym, "1h", start_ms, limit=1)[0]
    close = float(kl[4])
    answer = f"{close:.4f}"
    content = (
        f"On Binance, {asset_name(sym)}/USDT 1h kline starting at "
        f"{fmt_ts(t)}: close price in USDT, 4 decimals = ?"
    )
    return content, answer


def gen_t3_rsi(qid: int) -> tuple[str, str]:
    sym = random.choice(ASSETS)
    t = random_past_hour()
    # Need 15 closes ending at t. Start_ms covers t - 14h .. t, so 15 candles.
    start_ms = int((t - dt.timedelta(hours=14)).timestamp() * 1000)
    kls = fetch_klines(sym, "1h", start_ms, limit=15)
    closes = [float(k[4]) for k in kls]
    if len(closes) < 15:
        raise RuntimeError(f"got only {len(closes)} klines")
    answer = f"{rsi_14(closes):.2f}"
    content = (
        f"RSI(14) of {asset_name(sym)}/USDT 1h on Binance, computed over the 14 "
        f"period changes ending with the kline starting at {fmt_ts(t)}, using "
        f"simple-mean (not Wilder) gain/loss averages, rounded to 2 decimals = ?"
    )
    return content, answer


def gen_t4_pct_diff(qid: int) -> tuple[str, str]:
    a, b = random.sample(ASSETS, 2)
    t = random_past_hour()
    start_ms = int(t.timestamp() * 1000)
    ka = fetch_klines(a, "1h", start_ms, limit=1)[0]
    kb = fetch_klines(b, "1h", start_ms, limit=1)[0]
    ca = float(ka[4])
    cb = float(kb[4])
    pct = (ca - cb) / cb * 100.0
    answer = f"{pct:.2f}"
    content = (
        f"At {fmt_ts(t)}, percent difference between {asset_name(a)} and "
        f"{asset_name(b)} 1h closes on Binance, computed as "
        f"(close_{asset_name(a)} - close_{asset_name(b)}) / close_{asset_name(b)} × 100, "
        f"rounded to 2 decimals = ?"
    )
    return content, answer


def gen_t5_volume_sum(qid: int) -> tuple[str, str]:
    sym = random.choice(ASSETS)
    t1 = random_past_hour()
    hours = random.choice([3, 4, 5, 6])
    start_ms = int(t1.timestamp() * 1000)
    kls = fetch_klines(sym, "1h", start_ms, limit=hours)
    if len(kls) < hours:
        raise RuntimeError(f"got only {len(kls)} klines")
    total_base_vol = sum(float(k[5]) for k in kls)
    answer = str(int(round(total_base_vol)))
    end_t = t1 + dt.timedelta(hours=hours)
    content = (
        f"Sum of base-asset volume for {asset_name(sym)} on Binance across the "
        f"{hours} consecutive 1h klines starting at {fmt_ts(t1)} (i.e. ending at "
        f"{fmt_ts(end_t)}), rounded to integer = ?"
    )
    return content, answer


PLAN = (
    [(1, gen_t1_high_low_int)] * 30
    + [(1, gen_t2_close_4dp)] * 25
    + [(2, gen_t3_rsi)] * 20
    + [(2, gen_t4_pct_diff)] * 15
    + [(3, gen_t5_volume_sum)] * 10
)


def main() -> int:
    db.init_db()
    if db.question_count() >= 100:
        print(f"Already seeded ({db.question_count()} questions); skipping.")
        return 0

    random.seed(int(time.time()))
    inserted = 0
    failed = 0
    for qid, (difficulty, fn) in enumerate(PLAN, start=1):
        try:
            content, answer = fn(qid)
            db.insert_question(qid, content, answer, difficulty)
            inserted += 1
            print(f"  Q-{qid:03d} (d={difficulty}): {content[:80]}…  → {answer}")
            time.sleep(0.15)  # courtesy pacing for binance
        except Exception as e:
            failed += 1
            print(f"  Q-{qid:03d} FAILED: {e}", file=sys.stderr)
    print(f"\nInserted {inserted}, failed {failed}, total in DB: {db.question_count()}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
