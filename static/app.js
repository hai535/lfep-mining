// LFep Q&A Mining — vanilla ethers v6, light-mode only.

const $ = (id) => document.getElementById(id);
const fmtAddr = (a) => a ? a.slice(0, 6) + ".." + a.slice(-4) : "—";
const fmtLfep = (wei) => {
  if (!wei || wei === "0") return "0 LFEP";
  const big = BigInt(wei);
  const whole = big / 10n ** 18n;
  return whole.toLocaleString() + " LFEP";
};
const timeAgo = (sec) => {
  const d = Math.max(0, Math.floor(Date.now() / 1000) - sec);
  if (d < 60) return d + "s ago";
  if (d < 3600) return Math.floor(d / 60) + "m ago";
  if (d < 86400) return Math.floor(d / 3600) + "h ago";
  return Math.floor(d / 86400) + "d ago";
};

let provider = null;
let signer = null;
let userAddr = null;
let chainConfig = null;
let mining = null;
let usdc = null;
let pendingTicket = null;
let activeQuestion = null;

// ---------- toast ----------
function toast(msg, isError) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast" + (isError ? " error" : "");
  t.style.display = "block";
  clearTimeout(toast._h);
  toast._h = setTimeout(() => { t.style.display = "none"; }, 4500);
}

// ---------- API ----------
async function apiGet(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json();
}
async function apiPost(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json();
}

// ---------- streak bar ----------
function renderStreakBar(n) {
  const el = $("streak-bar");
  el.innerHTML = "";
  for (let i = 0; i < 10; i++) {
    const d = document.createElement("span");
    d.className = "streak-cell" + (i < n ? (i === 9 ? " bonus" : " filled") : "");
    el.appendChild(d);
  }
}

// ---------- copy helper for addresses ----------
function copyAddrSpan(addr) {
  if (!addr) return '<span style="color:var(--gray);font-size:11px;font-family:var(--f-mono)">not deployed</span>';
  return `<a class="copy-addr" data-copy="${addr}" title="Click to copy ${addr}" target="_blank" href="https://basescan.org/address/${addr}">${fmtAddr(addr)}<svg viewBox="0 0 24 24" fill="currentColor"><path d="M16 1H4a2 2 0 0 0-2 2v14h2V3h12V1zm3 4H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2zm0 16H8V7h11v14z"/></svg></a>`;
}

document.addEventListener("click", (e) => {
  const el = e.target.closest(".copy-addr");
  if (!el) return;
  const addr = el.dataset.copy;
  if (!addr) return;
  // Don't preventDefault on the basescan link by default — but do copy too
  navigator.clipboard.writeText(addr).then(() => toast("address copied"));
});

// ---------- config (contract addresses from /api/contracts) ----------
async function loadConfig() {
  try {
    const c = await apiGet("/api/contracts");
    chainConfig = c;
    window.LFEP_CONFIG.lfepToken = c.lfepToken;
    window.LFEP_CONFIG.lfepMining = c.lfepMining;
    $("stat-token").innerHTML = copyAddrSpan(c.lfepToken);
    $("stat-mining").innerHTML = copyAddrSpan(c.lfepMining);
    $("stat-usdc").innerHTML = copyAddrSpan(c.usdc);
    $("stat-signer").innerHTML = copyAddrSpan(c.signerAddr);
  } catch (e) { console.error("loadConfig", e); }
}

// ---------- chain stats ----------
async function refreshHealth() {
  try {
    const h = await apiGet("/api/health");
    const setText = (id, v) => { const el = $(id); if (el) el.textContent = v; };
    setText("stat-attempts",    (h.totalAttempts ?? 0).toLocaleString());
    setText("stat-miners",      (h.uniqueMiners ?? 0).toLocaleString());
    setText("stat-distributed", fmtLfep(h.totalDistributedWei));
    setText("stat-remaining",   fmtLfep(h.miningPoolRemainingWei));
    const total = BigInt(h.miningPoolTotalWei || "0");
    const used  = BigInt(h.totalDistributedWei || "0");
    const pct   = total > 0n ? Number((used * 1000000n) / total) / 10000 : 0;
    const pf = $("pool-fill"); if (pf) pf.style.width = Math.min(100, pct).toFixed(2) + "%";
    setText("pool-pct", pct.toFixed(4) + "% used");
  } catch (e) { console.error("refreshHealth", e); }
}

// ---------- recent activity ----------
async function refreshRecent() {
  try {
    const r = await apiGet("/api/recent?limit=8");
    const el = $("recent-feed");
    if (!r.entries.length) {
      el.innerHTML = '<div style="color:var(--gray);font-size:11px;font-family:var(--f-mono)">no activity yet</div>';
      return;
    }
    el.innerHTML = r.entries.map(e => {
      const tag = e.bonusTriggered
        ? '<span class="feed-tag bonus">★ bonus</span>'
        : e.isCorrect
          ? '<span class="feed-tag ok">✓ correct</span>'
          : '<span class="feed-tag no">✗ wrong</span>';
      return `<div class="feed-item">
        ${tag}
        <span style="color:var(--text)">${fmtAddr(e.address)}</span>
        <span style="color:var(--green)"> +${fmtLfep(e.amountWei)}</span>
        <span class="feed-meta"> · Q-${String(e.questionId).padStart(3,'0')} · ${timeAgo(e.createdAt)}</span>
      </div>`;
    }).join("");
  } catch (e) { console.error(e); }
}

// ---------- leaderboard ----------
async function refreshLeaderboard() {
  try {
    const url = userAddr ? `/api/leaderboard?address=${userAddr}` : "/api/leaderboard";
    const lb = await apiGet(url);
    $("lb-total").textContent = lb.totalMiners.toLocaleString();
    $("lb-myrank").textContent = lb.myRank ? "#" + lb.myRank : "—";
    const list = $("lb-list");
    if (!lb.entries.length) {
      list.innerHTML = '<div style="color:var(--gray);font-size:12px;font-family:var(--f-mono);text-align:center;padding:24px 0">no miners yet — be #1 ✨</div>';
      return;
    }
    list.innerHTML = lb.entries.map((e, i) => {
      const isMe = userAddr && e.address.toLowerCase() === userAddr;
      const rankCls = i < 3 ? " gold" : "";
      const streak = e.currentStreak > 0
        ? `<span class="lb-streak">🔥${e.currentStreak}</span>`
        : "";
      return `<div class="lb-row${isMe ? " lb-row-mine" : ""}">
        <span class="lb-rank${rankCls}">#${i + 1}</span>
        <span class="lb-addr">${fmtAddr(e.address)}${isMe ? ' (you)' : ''}</span>
        ${streak}
        <span class="lb-amount">${fmtLfep(e.totalEarnedWei)}</span>
       </div>`;
    }).join("");
  } catch (e) { console.error(e); }
}

// ---------- my stats ----------
async function refreshMyStats() {
  if (!userAddr) return;
  try {
    const s = await apiGet("/api/stats?address=" + userAddr);
    $("my-streak").textContent = s.currentStreak;
    renderStreakBar(s.currentStreak);
    $("my-earned").textContent = fmtLfep(s.totalEarnedWei);
    $("my-correct").textContent = `${s.totalCorrect} / ${s.totalAttempts}`;
  } catch (e) { console.error(e); }
}

// ---------- wallet ----------
async function connect() {
  if (!window.ethereum) { toast("No injected wallet found.", true); return; }
  try {
    provider = new ethers.BrowserProvider(window.ethereum);
    await provider.send("eth_requestAccounts", []);
    signer = await provider.getSigner();
    userAddr = (await signer.getAddress()).toLowerCase();

    const net = await provider.getNetwork();
    if (Number(net.chainId) !== 8453) {
      try {
        await window.ethereum.request({
          method: "wallet_switchEthereumChain",
          params: [{ chainId: "0x2105" }],
        });
        provider = new ethers.BrowserProvider(window.ethereum);
        signer = await provider.getSigner();
      } catch {
        toast("Please switch to Base mainnet (chainId 8453).", true);
        return;
      }
    }
    if (chainConfig.lfepMining) {
      mining = new ethers.Contract(chainConfig.lfepMining, window.MINING_ABI, signer);
    }
    if (chainConfig.usdc) {
      usdc = new ethers.Contract(chainConfig.usdc, window.ERC20_ABI, signer);
    }
    $("my-addr").textContent = fmtAddr(userAddr);
    $("connect-btn").textContent = fmtAddr(userAddr);
    await refreshMyStats();
    await refreshLeaderboard();
    toast("Connected. Approve USDC, then $ get-question.");
  } catch (e) {
    console.error(e);
    toast(e.message || "connect failed", true);
  }
}

async function approveUsdc() {
  if (!signer || !mining || !usdc) {
    toast("Connect wallet first (and ensure mining contract is deployed).", true);
    return;
  }
  try {
    const cur = await usdc.allowance(userAddr, chainConfig.lfepMining);
    if (cur > 10n * 10n ** 6n) {
      toast(`Already approved (allowance: ${cur} micro-USDC).`);
      return;
    }
    toast("Sending USDC approve tx…");
    const tx = await usdc.approve(chainConfig.lfepMining, ethers.MaxUint256);
    await tx.wait();
    toast("USDC approved. You can now claim rewards.");
  } catch (e) {
    console.error(e);
    toast(e.shortMessage || e.message, true);
  }
}

async function getQuestion() {
  if (!userAddr) { toast("Connect wallet first.", true); return; }
  try {
    const q = await apiPost("/api/question/get", { address: userAddr });
    activeQuestion = q;
    $("q-id").textContent = "Q-" + String(q.questionId).padStart(3, "0") + (q.difficulty ? `   (difficulty ${q.difficulty})` : "");
    $("q-content").textContent = q.content;
    $("q-answer").value = "";
    $("q-area").style.display = "block";
    $("result-area").style.display = "none";
    $("claim-btn").style.display = "none";
    setTimeout(() => $("q-answer").focus(), 50);
  } catch (e) {
    console.error(e);
    toast("get-question failed: " + (e.message || ""), true);
  }
}

async function submitAnswer() {
  if (!activeQuestion) return;
  const answer = $("q-answer").value.trim();
  if (!answer) { toast("Enter an answer first.", true); return; }
  try {
    const r = await apiPost("/api/question/submit", {
      address: userAddr,
      questionId: activeQuestion.questionId,
      sessionToken: activeQuestion.sessionToken,
      sessionNonce: activeQuestion.sessionNonce,
      sessionExpiry: activeQuestion.sessionExpiry,
      answer,
    });
    pendingTicket = r.ticket;
    activeQuestion = null;
    $("q-area").style.display = "none";
    const ra = $("result-area");
    let msg;
    if (r.result === "correct" && r.bonusTriggered) {
      msg = `<div class="result-bonus">✓ CORRECT — 10-STREAK BONUS! amount: ${fmtLfep(r.amount)}</div>`;
    } else if (r.result === "correct") {
      msg = `<div class="result-correct">✓ correct — amount: ${fmtLfep(r.amount)} · streak: ${r.streak}/10</div>`;
    } else {
      // Server runs closed-box: r.correctAnswer is null in production. We show
      // it only if explicitly disclosed (LFEP_REVEAL_CORRECT_ANSWER=1 on backend).
      const reveal = r.correctAnswer ? ` — canonical: <code>${r.correctAnswer}</code>` : "";
      msg = `<div class="result-wrong">✗ wrong${reveal} · consolation: ${fmtLfep(r.amount)} · streak reset</div>`;
    }
    msg += `<div style="margin-top:6px;color:var(--gray);font-size:11px;font-family:var(--f-mono)">claim ticket signed (5min ttl) — click $ claim-reward to receive on chain.</div>`;
    ra.innerHTML = msg;
    ra.style.display = "block";
    $("claim-btn").style.display = "inline-block";
    refreshMyStats();
    refreshHealth();
    refreshRecent();
  } catch (e) {
    console.error(e);
    toast("submit failed: " + (e.message || ""), true);
  }
}

async function claimReward() {
  if (!pendingTicket) { toast("No pending ticket.", true); return; }
  if (!mining) { toast("Mining contract not deployed yet.", true); return; }
  try {
    const allow = await usdc.allowance(userAddr, chainConfig.lfepMining);
    if (allow < 2n * 10n ** 6n) {
      toast("USDC allowance too low. Click $ approve-usdc first.", true);
      return;
    }
    toast("Submitting claim() — confirm in wallet…");
    const tx = await mining.claim(
      pendingTicket.questionId, pendingTicket.amount,
      pendingTicket.nonce, pendingTicket.expiry, pendingTicket.signature,
    );
    const rcpt = await tx.wait();
    toast(`✓ claim mined in block ${rcpt.blockNumber} — ${fmtLfep(pendingTicket.amount)} received`);
    pendingTicket = null;
    $("claim-btn").style.display = "none";
    $("result-area").style.display = "none";
    refreshLeaderboard();
  } catch (e) {
    console.error(e);
    toast("claim failed: " + (e.shortMessage || e.message || ""), true);
  }
}

// ---------- tabs (scoped per-section so docs and skills tabs are independent) ----------
document.querySelectorAll(".tab").forEach(t => {
  t.addEventListener("click", () => {
    const target = t.dataset.tab;
    const scope = t.closest(".page-section") || document;
    scope.querySelectorAll(".tab").forEach(x => x.classList.toggle("active", x.dataset.tab === target));
    scope.querySelectorAll(".tab-content").forEach(x => x.classList.toggle("active", x.dataset.tab === target));
  });
});

// ---------- hash-based single-page routing ----------
// Each section is its own "page" addressed by /#<id>. Default → hero.
const ROUTES = ["hero", "mine", "skills", "stats", "leaderboard", "docs"];

function applyRoute() {
  const raw = (location.hash || "").replace(/^#/, "");
  const route = ROUTES.includes(raw) ? raw : "hero";
  document.body.classList.add("single-route");
  document.querySelectorAll(".page-section").forEach(s => {
    s.classList.toggle("is-active", s.id === route);
  });
  // navbar active state — only overview/docs/skills are in the bar
  document.querySelectorAll(".navbar-link").forEach(l => {
    const href = (l.getAttribute("href") || "").replace(/^#/, "");
    let active = false;
    if (href === "hero" && route === "hero") active = true;
    else if (href === route) active = true;
    l.classList.toggle("navbar-link-active", active);
  });
  window.scrollTo({ top: 0, behavior: "instant" });
}

window.addEventListener("hashchange", applyRoute);

// ---------- FAQ accordion ----------
document.querySelectorAll(".faq-q").forEach(q => {
  q.addEventListener("click", () => q.parentElement.classList.toggle("open"));
});

// ---------- wire up ----------
$("connect-btn").addEventListener("click", connect);
$("approve-btn").addEventListener("click", approveUsdc);
$("get-q-btn").addEventListener("click", getQuestion);
$("submit-btn").addEventListener("click", submitAnswer);
$("cancel-btn").addEventListener("click", () => {
  activeQuestion = null;
  $("q-area").style.display = "none";
});
$("claim-btn").addEventListener("click", claimReward);
$("q-answer").addEventListener("keydown", (e) => {
  if (e.key === "Enter") submitAnswer();
});

(async () => {
  applyRoute();   // resolve initial hash before first paint
  await loadConfig();
  await refreshHealth();
  await refreshRecent();
  await refreshLeaderboard();
  setInterval(refreshHealth, 15000);
  setInterval(refreshRecent, 12000);
  setInterval(refreshLeaderboard, 30000);
  renderStreakBar(0);
})();
