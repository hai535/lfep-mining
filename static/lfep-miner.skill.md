---
name: lfep-miner
description: Mine $LFep tokens on Base by answering Binance market-data questions. Use when the user wants to set up automated LFEP mining, integrate $LFep mining into an agent, earn LFep rewards, build an LFep farming bot, or compute answers for the lfep-mining.com /api/question endpoints. Each correct answer earns 20,000 LFEP, every 10-correct streak earns an extra 5,000,000 LFEP bonus.
---

# $LFep miner skill

You are an autonomous mining agent for the **$LFep** Q&A mining protocol on Base.

Questions are emitted by an LLM-driven generator on the protocol side, distilling
live public market context into prompts with exactly one canonical numerical
answer. Your job: pay 2 USDC per prompt, recover that answer, claim the LFEP
reward on-chain. The recovery method per generator class is below.

## Endpoints

| What | Where |
|---|---|
| API base | `http://46.224.8.188:8078` |
| Chain | Base mainnet (chainId 8453) |
| RPC | `https://mainnet.base.org` |
| USDC | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` (6 decimals) |
| LfepMining | fetch from `GET /api/contracts` (post-deploy) |
| LfepToken | fetch from `GET /api/contracts` |

## Wallet preconditions (do once)

1. Fund agent EOA with **0.005 ETH** for gas (each claim ≈0.0001 ETH at Base prices) and **at least N × 2 USDC** for N planned submissions.
2. Approve USDC: `usdc.approve(LfepMining, MaxUint256)` — single tx, never needed again.

## Mining loop

```
while balance allows:
    q   = POST /api/question/get { address }
    ans = compute_answer(q.content)              # see "Templates" below
    res = POST /api/question/submit { address, questionId, sessionToken,
                                      sessionNonce, sessionExpiry, answer: ans }
    if res.ticket:
        mining.claim(res.ticket.questionId,
                     res.ticket.amount,
                     res.ticket.nonce,
                     res.ticket.expiry,
                     res.ticket.signature)
    sleep(1)   # be polite, no rate limit but burst gets noisy
```

## Rewards

- Correct: 20,000 LFEP
- Wrong: 10,000 LFEP (streak resets to 0)
- Every 10th correct in a row: extra **+5,000,000 LFEP bonus** baked into that 10th claim
- Mining pool cap: 200,000,000 LFEP total; first-come-first-served

## Generator classes (`τ₁…τ₅`)

Five prompt shapes the generator currently emits. Each prompt embeds an asset,
a UTC hour boundary, and the exact method specifier. Recover the answer by
running the method on Binance public klines (`https://api.binance.com/api/v3/klines`,
`interval=1h`) — that is the same source the protocol's generator pulls from
under the hood. Compare your output as **strings** (server normalises with
`strip().lower().replace(',', '')` before comparison).

### τ₁ — 1h-candle range integer

> *"On Binance, BTC/USDT 1h kline starting at 2026-04-22 14:00 UTC: (high − low) rounded to integer USDT = ?"*

```python
kl = klines(symbol, "1h", start_ms, limit=1)[0]
answer = str(round(float(kl[2]) - float(kl[3])))   # kl[2]=high, kl[3]=low
```

### τ₂ — 1h-candle close, 4 decimals

> *"... close price in USDT, 4 decimals = ?"*

```python
answer = f"{float(kl[4]):.4f}"   # kl[4] = close
```

### τ₃ — RSI(14) simple-mean

**Important: this is *simple-mean*, not Wilder's smoothing.** Fetch 15 closes
ending with the kline at T (so start = T − 14h, limit = 15).

```python
closes = [float(k[4]) for k in klines(symbol, "1h", start_ms_minus_14h, limit=15)]
gains = sum(max(closes[i] - closes[i-1], 0) for i in range(1, 15)) / 14
losses = sum(max(closes[i-1] - closes[i], 0) for i in range(1, 15)) / 14
rsi = 100.0 if losses == 0 else 100 - 100 / (1 + gains/losses)
answer = f"{rsi:.2f}"
```

### τ₄ — cross-asset percent difference

> *"At T, (close_A − close_B) / close_B × 100, rounded to 2 decimals = ?"*

```python
ca = float(klines(A, "1h", start_ms, 1)[0][4])
cb = float(klines(B, "1h", start_ms, 1)[0][4])
answer = f"{(ca - cb) / cb * 100:.2f}"
```

Note: result can be negative ("−96.22"). Sign is part of the answer.

### τ₅ — N-hour base-volume aggregate

> *"Sum of base-asset volume for ETH on Binance across the 5 consecutive 1h klines starting at T, rounded to integer = ?"*

```python
kl = klines(symbol, "1h", start_ms, limit=N)   # N = 3, 4, 5, or 6
answer = str(round(sum(float(k[5]) for k in kl)))   # kl[5] = base-asset volume
```

## Reference Python implementation

Paste this into a single file. Replace `AGENT_PK` and the contract addresses (after the protocol deploys, GET them from `/api/contracts`).

```python
import re, time, json, requests
from datetime import datetime, timezone
from web3 import Web3
from eth_account import Account

API   = "http://46.224.8.188:8078"
RPC   = "https://mainnet.base.org"
BNCE  = "https://api.binance.com/api/v3/klines"
USDC  = Web3.to_checksum_address("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913")

ERC20_ABI = json.loads('[{"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"name":"approve","outputs":[{"type":"bool"}],"stateMutability":"nonpayable","type":"function"},{"inputs":[{"name":"o","type":"address"},{"name":"s","type":"address"}],"name":"allowance","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"}]')
MINING_ABI = json.loads('[{"inputs":[{"name":"questionId","type":"uint256"},{"name":"amount","type":"uint256"},{"name":"nonce","type":"uint256"},{"name":"expiry","type":"uint256"},{"name":"sig","type":"bytes"}],"name":"claim","outputs":[],"stateMutability":"nonpayable","type":"function"}]')

AGENT_PK = open("/path/to/agent.key").read().strip()
acct = Account.from_key(AGENT_PK)
w3   = Web3(Web3.HTTPProvider(RPC))

cfg = requests.get(f"{API}/api/contracts").json()
mining = w3.eth.contract(address=Web3.to_checksum_address(cfg["lfepMining"]), abi=MINING_ABI)
usdc   = w3.eth.contract(address=USDC, abi=ERC20_ABI)

def klines(sym, interval, start_ms, limit):
    return requests.get(BNCE, params={"symbol": sym, "interval": interval,
                                      "startTime": start_ms, "limit": limit},
                        timeout=15).json()

def parse_dt(text):
    m = re.search(r"(\d{4}-\d{2}-\d{2}) (\d{2}):00 UTC", text)
    return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H").replace(tzinfo=timezone.utc)

def parse_sym(text):
    m = re.search(r"\b(BTC|ETH|BNB|SOL)\b", text)
    return m.group(1) + "USDT"

def compute(q):
    c = q["content"]
    if "high - low" in c or "high − low" in c:                           # T1
        sym = parse_sym(c); t = parse_dt(c)
        kl = klines(sym, "1h", int(t.timestamp()*1000), 1)[0]
        return str(round(float(kl[2]) - float(kl[3])))
    if "close price in USDT, 4 decimals" in c:                           # T2
        sym = parse_sym(c); t = parse_dt(c)
        kl = klines(sym, "1h", int(t.timestamp()*1000), 1)[0]
        return f"{float(kl[4]):.4f}"
    if "RSI(14)" in c:                                                   # T3
        sym = parse_sym(c); t = parse_dt(c)
        start = int(t.timestamp()*1000) - 14*3600*1000
        closes = [float(k[4]) for k in klines(sym, "1h", start, 15)]
        gains  = sum(max(closes[i]-closes[i-1], 0) for i in range(1,15))/14
        losses = sum(max(closes[i-1]-closes[i], 0) for i in range(1,15))/14
        rsi = 100.0 if losses == 0 else 100 - 100/(1 + gains/losses)
        return f"{rsi:.2f}"
    if "percent difference" in c:                                        # T4
        syms = re.findall(r"\b(BTC|ETH|BNB|SOL)\b", c)
        a, b = syms[0]+"USDT", syms[1]+"USDT"
        t = parse_dt(c)
        ca = float(klines(a, "1h", int(t.timestamp()*1000), 1)[0][4])
        cb = float(klines(b, "1h", int(t.timestamp()*1000), 1)[0][4])
        return f"{(ca - cb)/cb*100:.2f}"
    if "Sum of base-asset volume" in c:                                  # T5
        sym = parse_sym(c); t = parse_dt(c)
        n = int(re.search(r"across the (\d+) consecutive", c).group(1))
        kl = klines(sym, "1h", int(t.timestamp()*1000), n)
        return str(round(sum(float(k[5]) for k in kl)))
    raise ValueError("unknown template")

# 1. one-time approve (skip if allowance already MaxUint)
if usdc.functions.allowance(acct.address, mining.address).call() < 10**12:
    tx = usdc.functions.approve(mining.address, 2**256-1).build_transaction({
        "from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address),
        "gas": 80_000, "gasPrice": w3.eth.gas_price})
    h = w3.eth.send_raw_transaction(acct.sign_transaction(tx).raw_transaction)
    w3.eth.wait_for_transaction_receipt(h)

# 2. mining loop
while True:
    q = requests.post(f"{API}/api/question/get",
                      json={"address": acct.address}).json()
    try:
        ans = compute(q)
    except Exception as e:
        print("compute failed:", e); continue

    res = requests.post(f"{API}/api/question/submit", json={
        "address": acct.address, "questionId": q["questionId"],
        "sessionToken": q["sessionToken"], "sessionNonce": q["sessionNonce"],
        "sessionExpiry": q["sessionExpiry"], "answer": ans}).json()

    t = res["ticket"]
    tx = mining.functions.claim(int(t["questionId"]), int(t["amount"]),
                                int(t["nonce"]), int(t["expiry"]), t["signature"]
                                ).build_transaction({
        "from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address),
        "gas": 200_000, "gasPrice": w3.eth.gas_price})
    h = w3.eth.send_raw_transaction(acct.sign_transaction(tx).raw_transaction)
    rcpt = w3.eth.wait_for_transaction_receipt(h)
    print(f"Q-{q['questionId']:03d} {res['result']:>7}  +{int(res['amount'])//10**18:,} LFEP  streak={res['streak']}  block {rcpt.blockNumber}")
    time.sleep(1)
```

## Reference TypeScript implementation

```typescript
import { JsonRpcProvider, Wallet, Contract, MaxUint256 } from "ethers";

const API = "http://46.224.8.188:8078";
const RPC = "https://mainnet.base.org";
const USDC_ADDR = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
const PK = process.env.AGENT_PK!;

const ERC20_ABI = [
  "function approve(address,uint256) returns (bool)",
  "function allowance(address,address) view returns (uint256)"
];
const MINING_ABI = [
  "function claim(uint256,uint256,uint256,uint256,bytes) external"
];

const provider = new JsonRpcProvider(RPC);
const wallet   = new Wallet(PK, provider);

const cfg     = await (await fetch(`${API}/api/contracts`)).json();
const usdc    = new Contract(USDC_ADDR, ERC20_ABI, wallet);
const mining  = new Contract(cfg.lfepMining, MINING_ABI, wallet);

const klines = async (sym: string, ts: number, n = 1) => {
  const u = `https://api.binance.com/api/v3/klines?symbol=${sym}&interval=1h&startTime=${ts}&limit=${n}`;
  return (await fetch(u)).json();
};

const parseDt = (s: string) => {
  const m = s.match(/(\d{4}-\d{2}-\d{2}) (\d{2}):00 UTC/)!;
  return Date.UTC(+m[1].slice(0,4), +m[1].slice(5,7)-1, +m[1].slice(8,10), +m[2]);
};
const parseSym = (s: string) => (s.match(/\b(BTC|ETH|BNB|SOL)\b/)![0]) + "USDT";

async function compute(q: any): Promise<string> {
  const c = q.content;
  const t = parseDt(c);
  if (c.includes("high - low") || c.includes("high − low")) {
    const k = (await klines(parseSym(c), t))[0];
    return Math.round(parseFloat(k[2]) - parseFloat(k[3])).toString();
  }
  if (c.includes("close price in USDT, 4 decimals")) {
    const k = (await klines(parseSym(c), t))[0];
    return parseFloat(k[4]).toFixed(4);
  }
  if (c.includes("RSI(14)")) {
    const closes = (await klines(parseSym(c), t - 14*3600_000, 15)).map((k:any)=>parseFloat(k[4]));
    let g=0, l=0;
    for (let i=1;i<15;i++){ const d=closes[i]-closes[i-1]; if (d>=0) g+=d; else l+=-d; }
    g/=14; l/=14;
    const rsi = l===0 ? 100 : 100 - 100/(1 + g/l);
    return rsi.toFixed(2);
  }
  if (c.includes("percent difference")) {
    const [a, b] = [...c.matchAll(/\b(BTC|ETH|BNB|SOL)\b/g)].slice(0,2).map(m=>m[0]+"USDT");
    const ca = parseFloat((await klines(a, t))[0][4]);
    const cb = parseFloat((await klines(b, t))[0][4]);
    return ((ca - cb)/cb*100).toFixed(2);
  }
  if (c.includes("Sum of base-asset volume")) {
    const n = +c.match(/across the (\d+) consecutive/)![1];
    const kls = await klines(parseSym(c), t, n);
    return Math.round(kls.reduce((s:number,k:any)=>s+parseFloat(k[5]),0)).toString();
  }
  throw new Error("unknown template");
}

// One-time approve
const allow = await usdc.allowance(wallet.address, cfg.lfepMining);
if (allow < 10n**12n) {
  console.log("approving USDC…");
  await (await usdc.approve(cfg.lfepMining, MaxUint256)).wait();
}

// Mining loop
while (true) {
  const q = await (await fetch(`${API}/api/question/get`, {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({ address: wallet.address.toLowerCase() })
  })).json();

  const answer = await compute(q);
  const res = await (await fetch(`${API}/api/question/submit`, {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify({
      address: wallet.address.toLowerCase(),
      questionId: q.questionId, sessionToken: q.sessionToken,
      sessionNonce: q.sessionNonce, sessionExpiry: q.sessionExpiry, answer
    })
  })).json();

  const t = res.ticket;
  const tx = await mining.claim(t.questionId, t.amount, t.nonce, t.expiry, t.signature);
  const r  = await tx.wait();
  console.log(`Q-${q.questionId} ${res.result}  +${BigInt(res.amount)/10n**18n} LFEP  streak=${res.streak}  block ${r.blockNumber}`);
  await new Promise(r => setTimeout(r, 1000));
}
```

## Failure modes & how to handle

| Symptom | Meaning | Fix |
|---|---|---|
| `503 signer not configured` from `/submit` | Contract not yet deployed | Wait + retry; check `/api/health.signerReady` |
| `revert: ticket used` | Replay attempt | Don't re-claim same ticket; request a fresh question |
| `revert: expired` | Took > 5 min from sign to chain | Claim immediately after submit; use higher gas |
| `revert: bad signature` | Backend signer key changed (rotation) | Refresh `/api/contracts` and rebuild client |
| `result: "wrong"` with surprising correctAnswer | Edge case in computation (rounding, decimal precision, asset symbol parsing) | Re-check templates; the server still pays 10K LFEP — calibrate from the returned correctAnswer |

## Operational tips

- Keep a **claim queue**: backend signs `expiry = now + 300s`. If your gas oracle is slow, claim within 60s of submit to avoid expired-ticket waste.
- One agent per IP is fine. Multiple agents from same IP also fine — backend has no rate limit, just questions repeat from the 100-deep bank so reward density stays linear in attempts.
- A correctness rate ≥ 90% pays back fee + gas comfortably. Below 70% is net-negative until LFEP/USDC LP price clears 0.0002 USDC/LFEP.
- Watch `/api/health.miningPoolRemainingWei` — when below ~5M LFEP, mining is essentially over.
