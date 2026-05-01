"""Seed difficulty-4 and difficulty-5 questions used at streak positions 7→8
and 8→9 respectively. These templates require multi-step state-tracking
computation that ordinary LLMs (without code execution) cannot get right
even when given the exact formula — they accumulate floating-point drift
and miscount indices.

Templates added:
  τ₆ (d=4): MACD(12,26,9) histogram on 1h closes — simple-mean EMA
            initialisation, 35 candles back, signal line is EMA(9) over
            MACD values, output rounded to 6 decimals.
  τ₇ (d=5): 24-hour maximum drawdown on 1h closes — running-max state,
            output as percentage with 4 decimals.

Idempotent: skips if 30+ d=4/5 questions already exist.
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
BNCE = "https://api.binance.com/api/v3/klines"

D4_PER_RUN = 15
D5_PER_RUN = 15


def fetch(symbol: str, start_ms: int, limit: int) -> list[list]:
    qs = urllib.parse.urlencode({"symbol": symbol, "interval": "1h",
                                 "startTime": start_ms, "limit": limit})
    req = urllib.request.Request(f"{BNCE}?{qs}",
                                 headers={"User-Agent": "lfep-seed-hard/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def random_past_hour(min_days: int = 7, max_days: int = 30) -> dt.datetime:
    days_ago = random.uniform(min_days, max_days)
    target = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)
    return target.replace(minute=0, second=0, microsecond=0)


def fmt_ts(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%d %H:00 UTC")


def asset_name(symbol: str) -> str:
    return symbol.replace("USDT", "")


# ── τ₆: MACD(12,26,9) histogram, simple-mean EMA init ──

def macd_histogram(closes: list[float]) -> float:
    """Returns the histogram value at the last index. Requires len(closes) >= 35."""
    if len(closes) < 35:
        raise ValueError("need 35 closes")
    a12 = 2 / (12 + 1)
    a26 = 2 / (26 + 1)
    a9 = 2 / (9 + 1)

    # Simple-mean initialisation
    ema12 = sum(closes[:12]) / 12   # at index 11
    ema26 = sum(closes[:26]) / 26   # at index 25

    # Walk EMA12 from index 12 to end
    for c in closes[12:]:
        ema12 = a12 * c + (1 - a12) * ema12
    # ema12 is now value at index len-1

    # We need the EMA12 at every index from 25 onward (to compute MACD)
    # so redo more carefully:
    e12 = [None] * len(closes)
    e12[11] = sum(closes[:12]) / 12
    for i in range(12, len(closes)):
        e12[i] = a12 * closes[i] + (1 - a12) * e12[i-1]

    e26 = [None] * len(closes)
    e26[25] = sum(closes[:26]) / 26
    for i in range(26, len(closes)):
        e26[i] = a26 * closes[i] + (1 - a26) * e26[i-1]

    # MACD values from index 25 to end
    macd = [e12[i] - e26[i] for i in range(25, len(closes))]
    if len(macd) < 9:
        raise ValueError("not enough MACD values for signal")

    # Signal: EMA(9) over MACD with simple-mean init at MACD[8]
    sig = [None] * len(macd)
    sig[8] = sum(macd[:9]) / 9
    for i in range(9, len(macd)):
        sig[i] = a9 * macd[i] + (1 - a9) * sig[i-1]

    return macd[-1] - sig[-1]


def gen_tau6() -> tuple[str, str]:
    sym = random.choice(ASSETS)
    t = random_past_hour()
    # Need 35 closes ending at T (i.e. closes at T-34h .. T)
    start_ms = int((t - dt.timedelta(hours=34)).timestamp() * 1000)
    kls = fetch(sym, start_ms, 35)
    if len(kls) < 35:
        raise RuntimeError(f"only got {len(kls)} klines")
    closes = [float(k[4]) for k in kls]
    hist = macd_histogram(closes)
    answer = f"{hist:.6f}"

    content = (
        f"At Binance {asset_name(sym)}/USDT 1h timeframe, compute the MACD(12,26,9) "
        f"histogram value at the kline starting at {fmt_ts(t)}. Use closing prices only. "
        f"EMA(N) is initialised with simple-mean of the first N closes (no smoothing prefix), "
        f"then EMA_t = α·close_t + (1−α)·EMA_{{t-1}} with α = 2/(N+1). The MACD line is "
        f"EMA(12) − EMA(26), defined from index 25 onward. The signal line is EMA(9) over "
        f"the MACD values, simple-mean-initialised at MACD index 8. Histogram = MACD − Signal. "
        f"Use exactly 35 hourly closes ending at the named kline. Answer in USDT, signed, "
        f"rounded to 6 decimals = ?"
    )
    return content, answer


# ── τ₇: 24-hour max drawdown on 1h closes ──

def max_drawdown_pct(closes: list[float]) -> float:
    """Maximum drawdown as positive percentage (e.g. 5.1234 for 5.1234%)."""
    running_max = closes[0]
    worst_dd = 0.0
    for c in closes:
        if c > running_max:
            running_max = c
        dd = (running_max - c) / running_max if running_max > 0 else 0.0
        if dd > worst_dd:
            worst_dd = dd
    return worst_dd * 100


def gen_tau7() -> tuple[str, str]:
    sym = random.choice(ASSETS)
    t = random_past_hour()
    start_ms = int((t - dt.timedelta(hours=23)).timestamp() * 1000)
    kls = fetch(sym, start_ms, 24)
    if len(kls) < 24:
        raise RuntimeError(f"only got {len(kls)} klines")
    closes = [float(k[4]) for k in kls]
    dd = max_drawdown_pct(closes)
    answer = f"{dd:.4f}"

    content = (
        f"For Binance {asset_name(sym)}/USDT 1h closes, compute the maximum drawdown across "
        f"the 24 consecutive closes from {fmt_ts(t - dt.timedelta(hours=23))} to {fmt_ts(t)} "
        f"inclusive. Drawdown at index i = (running_max[0..i] − close[i]) / running_max[0..i], "
        f"where running_max[0..i] is the maximum close from index 0 to i (inclusive). The answer "
        f"is the maximum drawdown over all 24 indices, expressed as a percentage with 4 decimals "
        f"(e.g. 5.1234 for 5.1234%, NOT 0.0512) = ?"
    )
    return content, answer


def main() -> int:
    db.init_db()
    with db.cursor() as c:
        c.execute("SELECT difficulty, COUNT(*) FROM questions GROUP BY difficulty")
        existing = dict(c.fetchall())
    if existing.get(4, 0) >= 10 and existing.get(5, 0) >= 10:
        print(f"already seeded (d=4: {existing.get(4,0)}, d=5: {existing.get(5,0)}); skip")
        return 0

    random.seed(int(time.time()))

    # Get the next available qid
    with db.cursor() as c:
        c.execute("SELECT COALESCE(MAX(id), 0) FROM questions")
        next_qid = c.fetchone()[0] + 1

    inserted = {4: 0, 5: 0}
    failed = 0
    for diff, gen, count in [(4, gen_tau6, D4_PER_RUN), (5, gen_tau7, D5_PER_RUN)]:
        for _ in range(count):
            try:
                content, answer = gen()
                db.insert_question(next_qid, content, answer, diff)
                print(f"  Q-{next_qid:03d} [d={diff}] {content[:80]}…  → {answer}")
                inserted[diff] += 1
                next_qid += 1
                time.sleep(0.2)
            except Exception as e:
                failed += 1
                print(f"  d={diff} FAILED: {e}", file=sys.stderr)

    print(f"\ninserted d=4: {inserted[4]}  d=5: {inserted[5]}  failed: {failed}")
    print(f"total questions in bank: {db.question_count()}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
