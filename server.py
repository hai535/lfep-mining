"""LFep Q&A Mining backend (FastAPI).

Routes:
  GET  /                      → static/index.html
  GET  /static/*              → StaticFiles
  GET  /api/health            → totals + mining pool status
  GET  /api/stats?address=    → per-agent streak + earnings
  POST /api/question/get      → returns a random question + sessionToken
  POST /api/question/submit   → verifies answer, returns signed claim ticket
  GET  /api/leaderboard       → top earners

Configuration via env vars:
  LFEP_PORT              default 8078
  LFEP_MINING_CONTRACT   required for ticket signing (post-deploy)
  LFEP_DB                default /root/lfep_mining/lfep.db
  LFEP_SIGNER_KEY_FILE   default /root/.lfep_signer_key
  LFEP_SESSION_SECRET_FILE default /root/.lfep_session_secret
  LFEP_TICKET_TTL        default 300 seconds
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
import streaks
from signer import TicketSigner

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s  %(message)s")
log = logging.getLogger("lfep")

STATIC = Path(__file__).parent / "static"
PORT = int(os.environ.get("LFEP_PORT", 8078))
MINING_POOL_TOTAL_WEI = 200_000_000 * 10**18  # 20% of 1B
SESSION_TTL = 300  # seconds — must be >= ticket TTL

# ---------- session token (HMAC) ----------

_SESSION_SECRET_FILE = os.environ.get(
    "LFEP_SESSION_SECRET_FILE", "/root/.lfep_session_secret"
)


def _load_or_create_session_secret() -> bytes:
    p = Path(_SESSION_SECRET_FILE)
    if not p.exists():
        secret = secrets.token_bytes(32)
        p.write_bytes(secret)
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
        log.info("created new session secret at %s", p)
        return secret
    return p.read_bytes()


SESSION_SECRET = _load_or_create_session_secret()


def make_session_token(address: str, qid: int, nonce: str, expiry: int) -> str:
    msg = f"{address.lower()}:{qid}:{nonce}:{expiry}".encode()
    mac = hmac.new(SESSION_SECRET, msg, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode()


def verify_session_token(address: str, qid: int, nonce: str, expiry: int, token: str) -> bool:
    expected = make_session_token(address, qid, nonce, expiry)
    return hmac.compare_digest(expected, token)


# ---------- ticket signer ----------

SIGNER: TicketSigner | None = None


def _load_signer() -> TicketSigner | None:
    contract = os.environ.get("LFEP_MINING_CONTRACT", "").strip()
    key_file = os.environ.get("LFEP_SIGNER_KEY_FILE", "/root/.lfep_signer_key")
    if not contract or contract == "0x0000000000000000000000000000000000000000":
        log.warning(
            "LFEP_MINING_CONTRACT not set — server will run but /api/question/submit "
            "will return 503 until contract is deployed and address is configured"
        )
        return None
    if not os.path.exists(key_file):
        log.warning("signer key file %s missing — submits will 503", key_file)
        return None
    s = TicketSigner.from_file(path=key_file, verifying_contract=contract)
    log.info("signer loaded: %s (contract=%s)", s.signer_addr, contract)
    return s


# ---------- app lifecycle ----------

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    global SIGNER
    SIGNER = _load_signer()
    log.info("DB ready: %d questions seeded", db.question_count())

    # background nonce cleanup
    async def _cleanup():
        while True:
            await asyncio.sleep(600)
            try:
                n = db.cleanup_old_nonces()
                if n:
                    log.info("cleaned %d old session nonces", n)
            except Exception as e:
                log.warning("nonce cleanup failed: %s", e)

    task = asyncio.create_task(_cleanup())
    yield
    task.cancel()


app = FastAPI(title="LFep Q&A Mining", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- HTML + static ----------

if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/")
async def root():
    idx = STATIC / "index.html"
    if not idx.exists():
        return JSONResponse({"error": "frontend not built"}, status_code=503)
    return FileResponse(idx)


# ---------- API models ----------

class GetQuestionReq(BaseModel):
    address: str


class SubmitAnswerReq(BaseModel):
    address: str
    questionId: int
    sessionToken: str
    sessionNonce: str
    sessionExpiry: int
    answer: str


# ---------- API routes ----------

def _normalize_addr(addr: str) -> str:
    a = addr.strip().lower()
    if not (a.startswith("0x") and len(a) == 42 and all(c in "0123456789abcdef" for c in a[2:])):
        raise HTTPException(400, "invalid address")
    return a


def _normalize_answer(s: str) -> str:
    return s.strip().lower().replace(",", "")


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "questions": db.question_count(),
        "totalAttempts": db.total_attempts(),
        "totalDistributedWei": str(db.total_distributed_wei()),
        "miningPoolTotalWei": str(MINING_POOL_TOTAL_WEI),
        "miningPoolRemainingWei": str(max(0, MINING_POOL_TOTAL_WEI - db.total_distributed_wei())),
        "signerReady": SIGNER is not None,
        "miningContract": os.environ.get("LFEP_MINING_CONTRACT", ""),
    }


@app.get("/api/stats")
async def stats(address: str):
    addr = _normalize_addr(address)
    row = db.get_streak_row(addr)
    if row is None:
        return {
            "address": addr,
            "currentStreak": 0,
            "totalCorrect": 0,
            "totalAttempts": 0,
            "totalEarnedWei": "0",
        }
    return {
        "address": addr,
        "currentStreak": row["current_streak"],
        "totalCorrect": row["total_correct"],
        "totalAttempts": row["total_attempts"],
        "totalEarnedWei": row["total_earned_wei"],
    }


@app.post("/api/question/get")
async def get_question(req: GetQuestionReq):
    addr = _normalize_addr(req.address)
    if db.question_count() == 0:
        raise HTTPException(503, "question bank not seeded")

    # Difficulty-by-streak: ramp up across the last three positions of the
    # streak. Each tier is a separate moat — τ₆ (state-tracking EMA), τ₇
    # (running-max DD), τ₈ (apex tier — long branched specification).
    row = db.get_streak_row(addr)
    streak = row["current_streak"] if row else 0
    if streak == 7:
        diffs = [4]                # 8th in streak — τ₆ MACD
    elif streak == 8:
        diffs = [5]                # 9th — τ₇ max drawdown
    elif streak == 9:
        diffs = [6]                # 10th — τ₈ apex (the bonus claim itself)
    else:
        diffs = [1, 2, 3]
    q = db.random_question_by_difficulty(diffs)
    if q is None:
        raise HTTPException(500, "no questions")

    nonce = secrets.token_hex(16)
    expiry = int(time.time()) + SESSION_TTL
    token = make_session_token(addr, q["id"], nonce, expiry)
    return {
        "questionId": q["id"],
        "content": q["content"],
        "difficulty": q["difficulty"],
        "sessionNonce": nonce,
        "sessionExpiry": expiry,
        "sessionToken": token,
    }


@app.post("/api/question/submit")
async def submit_answer(req: SubmitAnswerReq):
    if SIGNER is None:
        raise HTTPException(
            503,
            "signer not configured — set LFEP_MINING_CONTRACT and LFEP_SIGNER_KEY_FILE",
        )

    addr = _normalize_addr(req.address)

    # 1. verify session token integrity
    if not verify_session_token(addr, req.questionId, req.sessionNonce, req.sessionExpiry, req.sessionToken):
        raise HTTPException(400, "invalid session token")

    # 2. expiry check
    if int(time.time()) > req.sessionExpiry:
        raise HTTPException(400, "session expired")

    # 3. replay check (nonce must be fresh)
    if not db.consume_session_nonce(req.sessionNonce):
        raise HTTPException(400, "session already used")

    # 4. lookup correct answer
    q = db.get_question(req.questionId)
    if q is None:
        raise HTTPException(400, "unknown question")
    correct = _normalize_answer(q["answer"]) == _normalize_answer(req.answer)

    # 5. compute reward + update streak
    amount, new_streak, bonus = streaks.compute_reward(addr, correct)
    db.insert_submission(addr, req.questionId, correct, bonus, amount, new_streak)

    # 6. sign EIP-712 ticket
    ticket = SIGNER.sign_ticket(addr, req.questionId, amount)

    # Closed-box response: never leak the canonical answer on wrong submissions.
    # A finite Q&A bank + answer-on-wrong reveal would let an attacker map the
    # whole bank for ~2 USDC × N questions, then mine with 100% accuracy.
    # Operators can re-enable disclosure for local debugging only by setting
    # LFEP_REVEAL_CORRECT_ANSWER=1 in the env (off by default in production).
    reveal = os.environ.get("LFEP_REVEAL_CORRECT_ANSWER", "0") == "1"
    return {
        "result": "correct" if correct else "wrong",
        "amount": str(amount),
        "streak": new_streak,
        "bonusTriggered": bonus,
        "correctAnswer": (q["answer"] if (reveal and not correct) else None),
        "ticket": ticket,
    }


@app.get("/api/leaderboard")
async def leaderboard(address: str | None = None):
    rows = db.leaderboard(limit=20)
    out = {
        "entries": [
            {
                "address": r["address"],
                "currentStreak": r["current_streak"],
                "totalCorrect": r["total_correct"],
                "totalAttempts": r["total_attempts"],
                "totalEarnedWei": r["total_earned_wei"],
            }
            for r in rows
        ],
        "totalMiners": db.total_miners(),
    }
    if address:
        try:
            addr = _normalize_addr(address)
            out["myRank"] = db.address_rank(addr)
        except HTTPException:
            pass
    return out


@app.get("/api/recent")
async def recent(limit: int = 20):
    """Recent submissions feed for the stats card."""
    limit = max(1, min(50, limit))
    rows = db.recent_submissions(limit=limit)
    return {
        "entries": [
            {
                "address": r["address"],
                "questionId": r["question_id"],
                "isCorrect": bool(r["is_correct"]),
                "bonusTriggered": bool(r["bonus_triggered"]),
                "amountWei": r["amount_wei"],
                "streakAfter": r["streak_after"],
                "createdAt": r["created_at"],
            }
            for r in rows
        ]
    }


@app.get("/api/contracts")
async def contracts():
    """Expose contract addresses + chain config to the frontend."""
    return {
        "chainId": 8453,
        "rpc": "https://mainnet.base.org",
        "lfepToken": os.environ.get("LFEP_TOKEN_CONTRACT", ""),
        "lfepMining": os.environ.get("LFEP_MINING_CONTRACT", ""),
        "usdc": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "signerAddr": SIGNER.signer_addr if SIGNER else "",
    }


if __name__ == "__main__":
    import uvicorn
    log.info("starting lfep mining server on :%d", PORT)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
