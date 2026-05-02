# $LFep 部署 / 基础设施配置

完整记录从域名注册到生产可访问的所有步骤。包含我们踩过的所有坑。

| 项 | 值 |
|---|---|
| 域名 | `lfep.us` |
| 注册商 | [Spaceship](https://www.spaceship.com/) |
| DNS / CDN | Cloudflare Free |
| Origin 服务器 | `46.224.8.188` (Hetzner) |
| Origin 端口 | `:8078` (FastAPI uvicorn) |
| Origin 反代 | nginx 1.18 :80 |
| SSL 模式 | Cloudflare Flexible (CF→browser HTTPS, CF→origin HTTP) |
| GitHub | `hai535/lfep-mining` |

---

## 1. 系统架构

```
浏览器 ──HTTPS──► Cloudflare Edge ──HTTP──► 46.224.8.188 nginx :80 ──proxy_pass──► 127.0.0.1:8078 FastAPI
        (Universal SSL)      (Flexible)      (lfep vhost)              (uvicorn / lfep-mining systemd)
```

为什么走 CF Flexible 而不是 Full：
- 服务器 `:443` 被 xray VLESS-REALITY 占用
- xray REALITY 不支持 SNI fallback，无法和 nginx 共存
- 所以 origin 只跑 HTTP `:80`，SSL 由 Cloudflare 终止

---

## 2. Spaceship 域名配置

### 2.1 注册参数
- 注册时长：1 年（默认）
- DNSSEC：**关闭**（CF Free 不签名，开了会破坏 DNSSEC 链）

### 2.2 NS 切换到 Cloudflare

`Manage → Domains → lfep.us → Nameservers → Change → Custom Nameservers`：

```
art.ns.cloudflare.com
shaz.ns.cloudflare.com
```

切换后 5-30 分钟生效到 .us 注册局，验证：

```bash
dig +trace lfep.us NS | tail -5
# 应该看到：lfep.us NS art.ns.cloudflare.com / shaz.ns.cloudflare.com
```

### 2.3 Spaceship 那些**不需要**配的

| 设置 | 状态 | 说明 |
|---|---|---|
| Inactive records | 空 | NS 切到 Custom 后老记录自动 inactive |
| Personal nameservers | 0 | 只有想做 ns.lfep.us 这种品牌 NS 才用 |
| URL Redirect | unavailable | 用 Custom NS 时这个功能不可用 |
| Web Forwarding | unavailable | 同上 |
| DNSSEC | 0 records | **不要启用**（除非 CF 也启用并填 DS） |

---

## 3. Cloudflare 配置

### 3.1 添加站点

`https://dash.cloudflare.com → Add a Site → 输入 lfep.us → 选 Free`

CF 自动扫描 Spaceship 的现有 DNS 记录并 import。

### 3.2 ⚠️ 关键：**清理 import 进来的 parking A 记录**（我们踩过的最大坑）

CF 添加站点时会扫描 Spaceship 当时的 A 记录。如果 Spaceship 当时还在 parking 状态，import 进来的会包括：

```
A   lfep.us   54.149.79.189   ← Spaceship parking AWS IP
A   lfep.us   34.216.117.25   ← Spaceship parking AWS IP
```

**必须手动删除这两条**，否则 CF 会在 origin 层 round-robin 到 parking 服务器，**约 2/3 用户会看到 "registered at spaceship" parking 页**。

正确的最终 DNS 表应该只有 2 条：

| Type | Name | Content | Proxy | TTL |
|---|---|---|---|---|
| A | `lfep.us` | `46.224.8.188` | 🟠 Proxied | Auto |
| A | `www` | `46.224.8.188` | 🟠 Proxied | Auto |

> **诊断命令**（在 CF DNS 修改后跑）：
> ```bash
> dig @art.ns.cloudflare.com lfep.us A +noall +answer
> ```
> 应该只看到 CF anycast IP（104.21.x / 172.67.x），其他出现都是异常。

### 3.3 SSL/TLS

`SSL/TLS → Overview → Encryption mode = Flexible`

为什么 Flexible：origin nginx 只跑 :80。如果开 Full，CF 会期待 origin :443 有有效证书，但那个端口被 xray 占了。

### 3.4 Edge Certificates 推荐设置

`SSL/TLS → Edge Certificates`：

| 选项 | 推荐 | 原因 |
|---|---|---|
| Always Use HTTPS | ON | 强制 HTTP→HTTPS 308 |
| Automatic HTTPS Rewrites | ON | 页面里 http:// 自动改 https:// |
| HSTS | 启用，max-age = 6 months, includeSubDomains | 浏览器 6 个月内强制 HTTPS（防 stale-DNS 命中老 IP 的 HTTP 流量） |
| Minimum TLS | TLS 1.2 | 1.0/1.1 已淘汰 |

### 3.5 Caching

| 选项 | 推荐 |
|---|---|
| Browser Cache TTL | Respect Existing Headers（让 origin 的 Cache-Control 生效） |
| Cache Level | Standard |

**注意**：CF Free 默认对 .js / .css / .html 等静态资源会缓存 4 小时（即使 origin 没设 max-age）。所以最好让 origin 显式设置（见 §4.2）。

---

## 4. nginx 配置

### 4.1 文件位置

```
/etc/nginx/sites-available/lfep        ← vhost 配置
/etc/nginx/sites-enabled/lfep          ← symlink
```

### 4.2 vhost 完整内容

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name lfep.us www.lfep.us;

    # Cloudflare 真实客户端 IP（Flexible 模式）
    set_real_ip_from 0.0.0.0/0;
    real_ip_header CF-Connecting-IP;

    client_max_body_size 1M;

    access_log /var/log/nginx/lfep.access.log;
    error_log  /var/log/nginx/lfep.error.log warn;

    # Active-dev assets — 短缓存让 CF 边缘 60 秒内同步 origin 改动
    location ~* \.(html|js|css|map)$ {
        proxy_pass http://127.0.0.1:8078;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        add_header Cache-Control "public, max-age=60, must-revalidate" always;
    }

    location / {
        proxy_pass http://127.0.0.1:8078;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_connect_timeout 30s;
        proxy_send_timeout    60s;
        proxy_read_timeout    60s;
    }
}
```

### 4.3 reload

```bash
nginx -t && systemctl reload nginx
```

---

## 5. 后端服务（lfep-mining systemd）

### 5.1 服务管理

```bash
systemctl status lfep-mining        # 状态
systemctl restart lfep-mining        # 重启（改了 server.py 后必须）
journalctl -u lfep-mining -f        # 实时日志
```

### 5.2 配置

```
/etc/systemd/system/lfep-mining.service        ← 主 unit
/etc/systemd/system/lfep-mining.service.d/override.conf   ← 环境变量
```

`override.conf` 里包含合约地址等（见 `project_lfep_mining.md`）：

```ini
[Service]
Environment="LFEP_TOKEN_CONTRACT=0x8B0fDbc1Fd23Cd52228B14410306dab393a3d14f"
Environment="LFEP_MINING_CONTRACT=0xC49156F386181C692aada6b2e4942B61e0777ECB"
```

### 5.3 端口与对外

- 后端只监听 `127.0.0.1:8078`，**不要绑 `0.0.0.0`**（防直接访问绕过 CF）
- nginx `:80` 是唯一入口
- `:443` 被 xray 占用（VLESS-REALITY VPN，独立服务）
- `:22` SSH 限 root key auth

---

## 6. 资源缓存策略

CF 会自动给静态资源加 `cache-control: max-age=14400`（4 小时）。

为了让前端改动**60 秒内**全网同步：

### 6.1 origin 设短缓存（已在 nginx 里）

```nginx
location ~* \.(html|js|css|map)$ {
    add_header Cache-Control "public, max-age=60, must-revalidate" always;
}
```

### 6.2 但 CF Free 默认会**覆写**这个

要让 CF 尊重 origin Cache-Control，需要：

`Cloudflare → Caching → Configuration → Browser Cache TTL → Respect Existing Headers`

### 6.3 兜底：cache-bust 版本号

每次改 `app.js` / `abi.js` 等文件，把 `index.html` 里的 `?v=2` 改成 `?v=3`：

```html
<script src="/static/app.js?v=3"></script>
```

CF 把 query string 视为新 cache key → 立即拿新版。

---

## 7. 部署流水线（手动）

```bash
# 1. 改代码
vim /root/lfep_mining/static/index.html
# 必要时 bump 版本号 ?v=N

# 2. 改后端代码？需要重启
systemctl restart lfep-mining

# 3. 改 nginx 配置？
nginx -t && systemctl reload nginx

# 4. 验证后端
curl -s http://127.0.0.1:8078/api/health | head -1

# 5. 验证 nginx vhost（用 Host 头模拟 lfep.us）
curl -sI -H "Host: lfep.us" http://127.0.0.1/ | head -3

# 6. 验证 CF 边缘（cache-bust query）
curl -sI "https://lfep.us/?_=$(date +%s)" | head -3

# 7. git 提交
cd /root/lfep_mining
git add -A
git commit -m "..."
git push origin master
```

---

## 8. 故障排查矩阵

### 用户看到 Spaceship parking 页

**原因**：CF DNS 表有指向 Spaceship 老 IP（54.149.79.189 或 34.216.117.25）的 A 记录残留。

**修复**：CF DNS 表只保留 2 条 `lfep.us` 和 `www` 都指向 `46.224.8.188`。**所有其他 A 记录全删**。

**验证**：
```bash
# 100 次循环测试，统计正常率
for i in $(seq 1 50); do
  curl -s --max-time 5 "https://lfep.us/?_=$RANDOM" | \
    grep -q "LFep" && echo "$i ✓" || echo "$i ✗"
done | tail -20
```

100% 应该返回 ✓。

### 用户报 "网站打不开" / "DNS 查不到"

依次检查：
```bash
dig +trace lfep.us NS                        # 注册局 NS 是 CF？
dig @art.ns.cloudflare.com lfep.us A         # CF 权威返回 CF anycast?
curl -sI https://lfep.us/                    # CF 边缘正常?
curl -sI -H "Host: lfep.us" http://127.0.0.1/  # nginx 正常?
curl -s http://127.0.0.1:8078/api/health     # 后端正常?
```

任何一步失败定位到那一层。

### 改了前端代码但用户看到老版本

```
原因：CF 边缘缓存或浏览器缓存
快速修：cache-bust 版本号 (index.html 里 ?v=N → N+1)
长期修：CF Caching → Browser Cache TTL → Respect Existing Headers
```

### nginx reload 后访问 502

```bash
journalctl -u lfep-mining -n 50    # 看后端是否挂了
nginx -t                            # 配置语法
systemctl status nginx              # nginx 进程
```

---

## 9. 健康检查清单（每次部署后跑）

```bash
#!/bin/bash
# /root/lfep_mining/scripts/healthcheck.sh

echo "=== DNS ==="
dig +short @1.1.1.1 lfep.us A
dig +short @8.8.8.8 lfep.us A

echo "=== CF 边缘 ==="
curl -sI --max-time 5 "https://lfep.us/?_=$(date +%s%N)" | grep -iE "server|cf-ray"

echo "=== 后端 API ==="
curl -s --max-time 5 https://lfep.us/api/health | python3 -m json.tool

echo "=== 一致性测试 (CF round-robin 健康) ==="
ok=0; bad=0
for i in $(seq 1 20); do
  if curl -s --max-time 5 "https://lfep.us/?_=$RANDOM" | grep -q "LFep"; then
    ok=$((ok+1))
  else
    bad=$((bad+1))
  fi
done
echo "  正常 / parking 比例: $ok / $bad   (期望 20/0)"
```

---

## 10. 复盘 — 我们踩过的坑

### 坑 1：CF auto-import parking A 记录
- **症状**：~67% 用户看到 Spaceship parking
- **根因**：CF 添加站点时 import 了 Spaceship 当时的 3 条 A 记录（含 2 条指向 parking）
- **教训**：添加 CF 站点后，**必须手动审核 DNS 记录表**，删除所有不属于自己的 A 记录

### 坑 2：xray 占用 :443 阻断 nginx SSL
- **症状**：装 Let's Encrypt 失败
- **根因**：服务器 :443 被 VLESS-REALITY 独占
- **解决**：走 CF Flexible 模式（CF→origin 用 :80 HTTP）

### 坑 3：CF 默认 Browser Cache TTL = 4h
- **症状**：改 app.js 后用户看不到新版
- **解决**：cache-bust query (`?v=N`) + 让 origin 显式设短 max-age

### 坑 4：app.js 引用不存在的 DOM
- **症状**：stats 区段所有数字都是 `—`
- **根因**：`$("stat-qs")` 引用不存在的元素 → TypeError → 整个 refreshHealth() 崩溃
- **教训**：DOM 操作前用 null-safe 写法 `if (el) el.textContent = ...`

### 坑 5：CF DNS 切换后 24-72h 长尾
- **症状**：部分用户本机 DNS 缓存还停在老 IP
- **根因**：操作系统 / 浏览器 DNS 缓存可达 24-72h
- **缓解**：开启 HSTS 让浏览器强制 HTTPS（命中老 IP 时 cert 错误而非假 parking 页）

---

## 11. 灾难恢复

### 服务器宕机
- nginx 死了：`systemctl restart nginx`
- 后端死了：`systemctl restart lfep-mining`
- 整机死了：到 Hetzner 控制台 reboot

### Cloudflare 出事
- CF 全局故障：直接走 origin IP `46.224.8.188:80`（短期对内可用，对外用户看不到）
- CF 把账号封了：到 Spaceship 把 NS 改回 `launch1/launch2.spaceship.net` + 在 Spaceship DNS 加 A 记录指向 `46.224.8.188`

### 域名出事
- Spaceship 不续费：1 年内迁出到 Cloudflare Registrar / Namecheap
- 当前域名被 ban：用备用域名（建议提前注册一个 `.xyz` 备份）

### Signer 私钥泄漏（H1 风险）
- 详见 `TOKENOMICS.md` §6 H1
- 因 owner 已死，无法 rotate signer
- 唯一应对：fork 合约重部署 v2

---

## 12. 联系 / 资源

- 网站：https://lfep.us
- X：https://x.com/LFEP_
- GitHub：https://github.com/hai535/lfep-mining
- Cloudflare 控制台：https://dash.cloudflare.com
- Spaceship 控制台：https://www.spaceship.com/
- 服务器：46.224.8.188 (Hetzner, root SSH)
