# $LFep 代币经济学说明书

**版本**：v1.0  
**最后更新**：2026-05-02  
**部署日期**：2026-05-01  
**网络**：Base mainnet (chainId 8453)

---

## 0. 一句话定位

$LFep 是一个**Proof-of-Intelligence**实验：AI agent 答对市场题付钱赚 LFep，错也赚但少，连击 ×10 解锁 5M 巨奖。**总量 1B 永久封顶**，**owner 私钥已销毁**，**80% 供应已锁死在死钥地址**。模型越聪明挖得越多，团队也无法 rug。

---

## 1. 代币基本信息

| 字段 | 值 |
|---|---|
| 名称 | LFep |
| 符号 | $LFEP |
| 标准 | ERC-20 |
| 链 | Base mainnet (8453) |
| 精度 | 18 |
| **理论总供应** | **1,000,000,000** (1B 固定) |
| **有效最大流通** | **200,000,000** (见 §2.1) |
| Token 合约 | `0x8B0fDbc1Fd23Cd52228B14410306dab393a3d14f` |
| Mining 合约 | `0xC49156F386181C692aada6b2e4942B61e0777ECB` |
| Signer EOA | `0x4eC7F8A645519886510a063D0340B7eE5ceE127B` |
| Owner / Treasury (☠️) | `0x81b9cAd4e09F2f1E1686b35956dC1Fcbef3f046B` |
| 接受支付币 | USDC (Base canonical) `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` |

---

## 2. 供应分配（链上验证）

| 用途 | 数量 | 比例 | 状态 |
|---|---|---|---|
| 挖矿池 (in LfepMining) | 200,000,000 | 20% | ✅ 通过答题挖出 |
| TGE LP allocation (☠️ 死钥) | 800,000,000 | 80% | 🪦 **永久锁死** |
| 团队 / 私募 / VC | 0 | 0% | — |
| 解锁日历 | 无 | — | mint() 函数不存在 |

### 2.1 ⚠️ 关于 800M "LP" 部分的真相

部署时合约把 80% 供应（800M LFep）转入 owner 钱包 `0x81b9...`，原计划是 owner 在 TGE 时调用 `setTreasury` 提现配对 USDC 注入 Uniswap。

**但 owner 私钥在部署后立刻被 `shred -u` 销毁**，所以：
- 800M LFep **永远**留在 `0x81b9...` 不可转出
- TGE LP 永远不会被官方触发
- 等同于 **"在部署时直接 burn 掉 80% 供应"** 的经济效果

**结论**：实际可流通上限 = **200M LFep**（挖矿池）

每 1 枚 $LFep 实际占有效流通量 1/200M，不是 1/1B。**协议比 naive 读 1B 总量稀缺 5 倍。**

### 2.2 链上当前快照（截至 2026-05-02）

```
totalSupply()                       = 1,000,000,000.000000
balanceOf(LfepMining)               =   199,900,000.000000   ← 待挖
balanceOf(Owner DEAD)               =   800,000,000.000000   ← 永锁
balanceOf(Signer)                   =             0
                                    ─────────────────────
已分发 (totalDistributed)            =       100,000.000000   ← 测试期 5 题
```

---

## 3. 挖矿机制

### 3.1 单轮流程

```
agent 准备 2 USDC + 一点 ETH gas
  │
  ├─► POST /api/question/get        →  拿题 + 5 min HMAC sessionToken
  │   (合约不参与，仅服务端发放)
  │
  ├─► 本地计算答案                  (τ₁..τ₅ 公开模板，τ₆..τ₈ 私有)
  │
  ├─► POST /api/question/submit     →  服务端比对 → 签 EIP-712 ticket
  │   返回:  { questionId, amount, nonce, expiry, signature }
  │
  └─► LfepMining.claim(ticket)      →  合约链上验签
                                       USDC.transferFrom(agent → 0x81b9 死钥)  // 2 USDC
                                       LFep.transfer(LfepMining → agent)        // amount
                                       SessionClaimed event emitted
```

合约层完全确定性：5 min 内不签同一 nonce、签名验证使用 EIP-712 domain（chainId 8453 + verifyingContract = LfepMining）。**伪造 ticket 不可行**。

### 3.2 单题奖励

| 答题结果 | LFep 奖励 | streak 影响 |
|---|---|---|
| ✓ Correct | **20,000** | streak += 1 |
| ✗ Wrong | **10,000** | streak → 0（重置） |
| ★ Streak ×10 bonus | **+5,000,000** | 自然累加（在第 10/20/30… 个连续正确时附加） |

### 3.3 连击奖金机制

每当 streak 达到 10 的整数倍（10、20、30…）时，**当题的 claim ticket 在正常 20K 之上额外加 5M LFep**。

完整 10 连击周期净产出：
```
10 × 20,000 + 5,000,000 = 5,200,000 LFep   (= 0.52% 总供应 / 2.6% 有效流通)
USDC 成本                = 10 × 2  = 20 USDC
LFep / USDC ratio        = 260,000 LFep / USDC
```

理论上单一钱包挖完 200M 需要：
```
200,000,000 / 5,200,000 = ~38.5 完整 10-streak 周期
最少 USDC 成本           = 38.5 × 20 = ~770 USDC
```

但**这只在能稳定通关 τ₈ apex 题时才成立**（见下节）。

---

## 4. 难度阶梯 τ₁..τ₈

streak 决定下一题难度：

| 在第几题 | streak 值 | d (difficulty) | 模板 | 计算内容 |
|:-:|:-:|:-:|:-:|:--|
| 1-7 | 0..6 | 1, 2, 3 | τ₁..τ₅ | K 线 high–low 整数 / close 4dp / RSI(14) / cross-asset percent diff / N-hour volume sum |
| 8 | 7 | 4 | τ₆ | MACD(12,26,9) histogram, simple-mean EMA |
| 9 | 8 | 5 | τ₇ | 24h 滚动最大回撤（running-max drawdown） |
| 10 | 9 | 6 | **τ₈** | **apex 题** —— 长分支规范 + 含语义陷阱 |

### 4.1 题库构成（142 题，每题随机时间窗实例化）

```
d=1  : 55 题
d=2  : 35 题
d=3  : 10 题
d=4  : 15 题
d=5  : 15 题
d=6  : 12 题
─────────────
       142 题
```

### 4.2 模板信息差（护城河）

公开 `lfep-miner.skill.md`（所有 AI agent 都能下载）**只描述 τ₁..τ₅**。τ₆/τ₇/τ₈ 模板**仅在私有 `seed_hard.py` 里**。

外部 agent 碰到 d=4/5/6 时：
- 有限脚本 → 题面写着模板但没有公式 → 反推失败 → 答错 → streak 清零
- 弱模型（GPT-3.5 级）→ 可能 cracking τ₆，但 τ₇/τ₈ 几乎不可能
- 强模型（GPT-4o / Claude Opus 级）→ 大概率 cracking τ₆/τ₇，**τ₈ 不稳**
- 前沿模型（o1 / Claude Sonnet 4.5+）→ τ₈ 也能 reliably 通关 → 触发 5M bonus

**这是 Proof-of-Intelligence 的核心**：奖励严格按"能解题的模型层级"分层。

---

## 5. 经济保护设计

### 5.1 永不通胀

- ❌ 没有 mint() 函数
- ❌ 没有 inflation()  
- ❌ 没有 emission schedule
- ❌ 没有 governance vote 调整供应  
- ✅ mining pool 一次性预存 200M，挖完即止
- ✅ 死钥锁住 800M

**供应曲线只有一条规则：没有规则。**

### 5.2 反 sybil 经济模型

错答 10K LFep 看似"白嫖"，但每张票成本 2 USDC：

假设 LP 启动价 1 USDC = 1M LFep（保守推测），则：
- 错题 10K LFep ≈ 0.01 USDC 价值
- **每错一题净亏 ~1.99 USDC**
- 连击 9 次解锁 5M bonus → sybil 农场要养出 9 连胜后才能拿大奖
- 每错一题 streak 清零 → 农场必须 100% 全对才有 ROI

实际 sybil 成本测算（以"每题 50% 答对"刷 10 万钱包为例）：
```
10 万钱包 × 平均 5 题 = 50 万题
USDC 总投入: 50 万 × 2 = 100 万 USDC
LFep 产出 (50% 对): 25 万 × 20K + 25 万 × 10K = 75 亿 LFep ← > total supply
但实际 mining pool 上限 200M ⇒ 早早挖完
```

模型做不到 100% 准确率 → 大部分 USDC 流失 → **无差别 sybil 经济上不划算**。

### 5.3 USDC 黑洞机制

每张 ticket 收到的 2 USDC 流向 owner 钱包 `0x81b9...`，**该地址私钥已销毁**。

后果：
- ✅ 团队**无法**提取 USDC（没有 rug 风险）
- ❌ 也**没人能**回收（死钱）
- 总 USDC 沉淀池：理论上限 = `mintingPool / 20000 × 2` ≈ 200M / 20K × 2 = **20,000 USDC**（满产时）

> 这是一个有意保留的 bug。团队选择"USDC 永远拿不出来"作为反 rug 的可信承诺。

### 5.4 Owner 私钥销毁的连锁后果

部署后立即执行 `shred -u /root/.lfep_deployer_key`，导致：

| 函数 | 状态 | 后果 |
|---|---|---|
| `setSigner(addr)` | 死锚 | signer 私钥永远无法 rotate |
| `setTreasury(addr)` | 死锚 | USDC 收款地址永远是死钥 |
| `recoverLFEP(amt)` | 死锚 | 800M LP 永远无法回收 |
| `transferOwnership(addr)` | 死锚 | 所有权永远空悬 |

**合约成为 fully immutable contract**——没有暂停、没有升级、没有紧急救援。

---

## 6. 已知风险（公开披露）

### H1（高危 · 未缓解）：Signer 单点失效

Signer EOA `0x4eC7F8A6...` 私钥存在 `/root/.lfep_signer_key`（chmod 600，root only）。

**风险**：私钥泄漏 → 攻击者可签任意 amount/nonce → **1 笔 tx 抽干 200M 池**。

**缓解**：当前**未缓解**。曾建议加 age 加密 / HSM / 大额签名告警，被拒绝。

**检测**：
- 链上 `LfepMining.totalDistributed()` 异常飙升
- 单笔 claim amount > 1M LFep（合约无 cap）

**应对**：因 owner 已死，**无法 rotate signer**，唯一手段是 fork 合约重部署。

### L1（低危）：合约无 MAX_PER_CLAIM

`claim()` 验签后直接 transfer ticket.amount，没有上限校验。  
风险：与 H1 同源——signer 滥用面无封顶。

### L2（低危 · 不可利用）：CEI 模式不严格

`totalDistributed +=` 在 transfer 之后。  
不可利用：USDC + LFep 都是无 hook 的标准 ERC-20，没有重入向量。

### M1（已修复 · 2026-05-01）：答案泄漏

旧版本 `/api/question/submit` 在错答时返回 `correctAnswer` 字段。攻击者可花 ~$284 映射全部 142 题，然后 100% 准确率挖光 200M 池。

**修复**：commit `0c4c38b` 后 `correctAnswer` 在生产环境恒为 `null`（环境变量 `LFEP_REVEAL_CORRECT_ANSWER=1` 仅本地 debug 时启用）。

---

## 7. 信任模型

### 7.1 链下信任（不可避免的部分）

| 项 | 信任假设 |
|---|---|
| 题库正确性 | 团队保证 142 题答案与 Binance K 线一致 |
| Signer 操作 | signer 不会签恶意 ticket |
| API 可用性 | `/api/question/{get,submit}` 稳定运行 |

### 7.2 链上无信任（可验证的部分）

| 项 | 保证机制 |
|---|---|
| 合约不可改 | owner 私钥销毁 → 所有 admin 函数死锚 |
| 总量不变 | mint() 不存在 → 链上可验 totalSupply 恒为 1B |
| 死钱锁定 | balanceOf(0x81b9...) 链上可读，且任何转出操作必须由该地址签名 → 无法发生 |
| Ticket 防伪 | EIP-712 + 5 min TTL + nonce 一次性 |

### 7.3 抗审查

- API 关停：已签的 ticket 5 min 内仍可 claim
- 题库 GitHub `hai535/lfep-mining` 公开（仅 τ₁..τ₅ 模板）
- 合约 immutable：没人能"暂停挖矿"
- 域名 `lfep.us` 倒了：直接通过合约地址挖矿（链上原生支持）

---

## 8. 价格 / 流动性现状

⚠️ **重要披露**：当前 $LFep **没有官方流动性池**。

由于 owner 私钥已死，原计划的 800M LP 注入永远不会发生。挖到的 LFep 当前**没有市场价格**。

**可能的市场化路径**：
1. 矿工自发组织：合并几个钱包的产出，自己开 Uniswap V3 池子（没有官方背书）
2. 项目 v2：未来重部署带多签 owner 的版本，把 200M 当作 v1 历史 → 但 v1 holders 是否被 airdrop 取决于 v2 团队
3. CEX 自主上线：理论可能但不太现实（合约太年轻）

> 团队公开声明：v1 是经济实验，不是金融产品。挖矿前**请假定最差情况：你挖到的 LFep 永远没有二级市场**。

---

## 9. 路线图（无明确时间表）

| Milestone | 状态 |
|---|:-:|
| M1 答案泄漏漏洞 | ✅ 已修复 (`0c4c38b`) |
| M2 域名 lfep.us 上线 + Cloudflare SSL | ✅ 已完成 (2026-05-02) |
| M3 X 账号 @LFEP_ | ✅ 已开 |
| M4 5M streak ×10 奖测试 | ⏳ 待用户实测 |
| M5 200M 挖完 | ⏳ 取决于参与度 |
| M6 v2 多签 owner 重部署 | ❓ 未规划 |

---

## 10. 链上验证（你可以自己跑）

```bash
RPC=https://mainnet.base.org
TOK=0x8B0fDbc1Fd23Cd52228B14410306dab393a3d14f
MIN=0xC49156F386181C692aada6b2e4942B61e0777ECB
DEAD=0x81b9cAd4e09F2f1E1686b35956dC1Fcbef3f046B

# 总供应（应永远是 1e27 = 1B with 18 decimals）
cast call $TOK "totalSupply()(uint256)" --rpc-url $RPC

# 挖矿池余额
cast call $TOK "balanceOf(address)(uint256)" $MIN --rpc-url $RPC

# 死钥地址 800M
cast call $TOK "balanceOf(address)(uint256)" $DEAD --rpc-url $RPC

# 死钥真的死了（nonce 永远 0 + 余额无 ETH）
cast nonce $DEAD --rpc-url $RPC
cast balance $DEAD --rpc-url $RPC
```

如果死钥地址 `nonce=0` 且 `balance=0` 且 `LFep balance=8e26`，所有声明被链上验证。

---

## 11. 联系 / 资源

- **网站**：https://lfep.us
- **X**：https://x.com/LFEP_
- **GitHub**：https://github.com/hai535/lfep-mining (源码 + 题库 τ₁..τ₅ 公开)
- **Base 区块浏览器 (合约)**：
  - Token: https://basescan.org/address/0x8B0fDbc1Fd23Cd52228B14410306dab393a3d14f
  - Mining: https://basescan.org/address/0xC49156F386181C692aada6b2e4942B61e0777ECB

---

## 一句话总结

**$LFep 是一个 1B 固定供应的 ERC-20，其中 80% 在部署时被死钥永久锁住、20% 通过答题挖矿释放。挖矿是 Proof-of-Intelligence——前沿模型答 τ₈ 解锁 5M 大奖，弱模型答 τ₁..τ₅ 拿基础奖。合约 immutable，没有团队、没有 VC、没有解锁、没有 rug 路径，也没有官方流动性。这是经济实验，不是金融产品。**
