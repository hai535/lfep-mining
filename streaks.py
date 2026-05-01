"""Streak + reward computation.

Constants are in wei (10^18 base units). All percentages are of total supply
(1,000,000,000 LFEP):

  CORRECT:    0.002% × 1B = 20,000 LFEP
  WRONG:      0.001% × 1B = 10,000 LFEP
  STREAK_10:  0.5%   × 1B = 5,000,000 LFEP (added on top of CORRECT every 10th)

Streak resets on any wrong answer. Bonus triggers deterministically every time
current_streak hits a multiple of 10 (10, 20, 30, ...).
"""
from __future__ import annotations

import db

REWARD_CORRECT_WEI = 20_000 * 10**18
REWARD_WRONG_WEI = 10_000 * 10**18
BONUS_WEI = 5_000_000 * 10**18


def compute_reward(address: str, is_correct: bool) -> tuple[int, int, bool]:
    """Update streak, persist, return (amount_wei, new_streak, bonus_triggered)."""
    row = db.get_streak_row(address)
    streak = row["current_streak"] if row else 0

    if is_correct:
        streak += 1
        bonus = (streak % 10 == 0)
        amount = REWARD_CORRECT_WEI + (BONUS_WEI if bonus else 0)
    else:
        streak = 0
        bonus = False
        amount = REWARD_WRONG_WEI

    db.upsert_streak(address, streak, is_correct, amount)
    return amount, streak, bonus
