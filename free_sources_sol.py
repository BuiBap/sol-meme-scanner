#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
free_sources_sol.py — Nguồn dữ liệu MIỄN PHÍ bổ sung cho sol_meme_bot.py (Solana).

NGUỒN CHÍNH: Jupiter Token API V2 — mạnh hơn hẳn mọi thứ có trên Base.
Nó trả sẵn những chỉ báo mà bot đang phải tự chế bằng proxy:

  organicScore (0-100)     : điểm chất lượng ĐÃ LỌC BOT của Jupiter
  buyOrganicVolume         : volume mua THẬT (đã trừ wash trading) <- quan trọng nhất
  numOrganicBuyers         : số người mua thật, không phải bot
  holderCount              : số holder thật
  audit.topHoldersPercentage : % top holder (LẤP chỗ GoPlus Solana chỉ cho top-10)
  audit.mintAuthorityDisabled / freezeAuthorityDisabled : đối chiếu chéo với GoPlus
  audit.devMints           : dev đã mint bao nhiêu lần (mint nhiều lần = cờ đỏ)
  isVerified, tags, cexes  : token đã được xác minh / niêm yết CEX chưa
  dev                      : địa chỉ ví dev
  twitter, website         : social có sẵn, khỏi gọi API khác

SỰ THẬT VỀ TỪNG NGUỒN (kiểm chứng 7/2026, không bịa):
  - Jupiter lite-api.jup.ag : MIỄN PHÍ, KHÔNG cần key. Bản api.jup.ag cần x-api-key.
    CẢNH BÁO: Jupiter đã đổi nền tảng billing, người dùng portal cũ được giữ
    rate limit miễn phí ĐẾN 30/06/2026 (đã qua). Nếu lite-api bắt đầu chặn,
    lấy key tại portal.jup.ag và set JUPITER_API_KEY.
  - Helius : MIỄN PHÍ 1M credit/tháng, 10 RPS. CẦN key (helius.dev, free tier).
    Chỉ dùng cho fresh-wallet ratio. Không có key -> bot tự bỏ qua.
  - GeckoTerminal /tokens/{addr}/info : MIỄN PHÍ, không key. Cho gt_score.
  - RugCheck : đã tích hợp sẵn trong sol_meme_bot.py, miễn phí.

KHÔNG dùng được (đã kiểm chứng, đừng mất công):
  - Kaito Yaps : ĐÃ KHAI TỬ 15/01/2026, trang docs trả 404.
  - Smart money chất lượng cao : không có nguồn free. Rẻ nhất Cielo Whale $199/thg.

CÁCH DÙNG: xem hướng dẫn cuối file.
"""

import os
import time
from typing import Optional

import requests

# --------------------------------------------------------------------------- #
#  Cấu hình
# --------------------------------------------------------------------------- #

JUP_LITE = "https://lite-api.jup.ag"                    # miễn phí, không key
JUP_PRO = "https://api.jup.ag"                          # cần x-api-key
JUPITER_API_KEY = os.getenv("JUPITER_API_KEY", "")
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")
GT_API = "https://api.geckoterminal.com/api/v2"

FRESH_WALLET_MAX_AGE_H = 24.0
FRESH_WALLET_TOP_N = 15
FRESH_WALLET_MIN_CHECKED = 5

_session = requests.Session()
_session.headers.update({"Accept": "application/json",
                         "User-Agent": "sol-meme-bot-free-sources/1.0"})
_last_call = {}


def _throttle(host: str, min_interval: float):
    last = _last_call.get(host, 0)
    wait = min_interval - (time.time() - last)
    if wait > 0:
        time.sleep(wait)
    _last_call[host] = time.time()


def _get(url: str, headers: Optional[dict] = None,
         min_interval: float = 0.3, timeout: int = 15):
    host = url.split("/")[2]
    _throttle(host, min_interval)
    delay = 1.0
    for attempt in range(1, 4):
        try:
            r = _session.get(url, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                time.sleep(delay * (2 ** (attempt - 1)))
                continue
            if r.status_code in (401, 403):
                if "jup.ag" in host and not JUPITER_API_KEY:
                    print("    [jupiter] lite-api bị chặn -> lấy key free tại portal.jup.ag "
                          "rồi set JUPITER_API_KEY")
                return None
            if 500 <= r.status_code < 600:
                time.sleep(delay * (2 ** (attempt - 1)))
                continue
            return None
        except (requests.RequestException, ValueError):
            time.sleep(delay * (2 ** (attempt - 1)))
    return None


def _rpc(method: str, params: list, min_interval: float = 0.15):
    """JSON-RPC tới Helius (free tier 10 RPS)."""
    if not HELIUS_API_KEY:
        return None
    url = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
    _throttle("mainnet.helius-rpc.com", min_interval)
    payload = {"jsonrpc": "2.0", "id": "1", "method": method, "params": params}
    for attempt in range(1, 4):
        try:
            r = _session.post(url, json=payload, timeout=20)
            if r.status_code == 200:
                return (r.json() or {}).get("result")
            if r.status_code == 429:
                time.sleep(1.0 * (2 ** (attempt - 1)))
                continue
            return None
        except (requests.RequestException, ValueError):
            time.sleep(1.0 * (2 ** (attempt - 1)))
    return None


def _f(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
#  1) JUPITER TOKEN API V2 — nguồn giá trị nhất, miễn phí
# --------------------------------------------------------------------------- #

def jupiter_token(mint: str) -> Optional[dict]:
    """Lấy toàn bộ thông tin token từ Jupiter. None nếu không có."""
    base = JUP_PRO if JUPITER_API_KEY else JUP_LITE
    headers = {"x-api-key": JUPITER_API_KEY} if JUPITER_API_KEY else None
    d = _get(f"{base}/tokens/v2/search?query={mint}", headers, min_interval=0.4)
    if not isinstance(d, list) or not d:
        return None
    # search có thể trả nhiều kết quả -> lấy đúng mint
    for item in d:
        if isinstance(item, dict) and item.get("id") == mint:
            return item
    return d[0] if isinstance(d[0], dict) else None


def jupiter_signals(mint: str) -> Optional[dict]:
    """Rút các chỉ báo dùng được từ Jupiter. Trả dict hoặc None."""
    t = jupiter_token(mint)
    if not t:
        return None

    audit = t.get("audit") or {}
    out = {
        "organic_score": _f(t.get("organicScore"), -1.0),
        "organic_label": t.get("organicScoreLabel"),
        "holder_count": t.get("holderCount"),
        "top_holders_pct": _f(audit.get("topHoldersPercentage"), -1.0),
        "mint_disabled": audit.get("mintAuthorityDisabled"),
        "freeze_disabled": audit.get("freezeAuthorityDisabled"),
        "dev_mints": audit.get("devMints"),
        "is_verified": bool(t.get("isVerified")),
        "tags": t.get("tags") or [],
        "cexes": t.get("cexes") or [],
        "dev_wallet": t.get("dev"),
        "twitter": t.get("twitter"),
        "website": t.get("website"),
        "liquidity": _f(t.get("liquidity")),
        "mcap": _f(t.get("mcap")),
    }

    # --- Tỷ lệ volume THẬT: đây là chỉ báo wash-trading tốt nhất có được miễn phí ---
    for win in ("stats5m", "stats1h", "stats24h"):
        s = t.get(win) or {}
        buy_v = _f(s.get("buyVolume"))
        buy_org = _f(s.get("buyOrganicVolume"))
        sell_v = _f(s.get("sellVolume"))
        sell_org = _f(s.get("sellOrganicVolume"))
        key = win.replace("stats", "")
        # % volume mua là thật (0-100). None nếu chưa có volume để kết luận.
        out[f"organic_buy_pct_{key}"] = round(buy_org / buy_v * 100, 1) if buy_v > 0 else None
        # net organic: mua thật vs bán thật
        out[f"organic_net_{key}"] = round(buy_org - sell_org, 2) if (buy_org or sell_org) else None
        out[f"organic_buyers_{key}"] = s.get("numOrganicBuyers")
        out[f"traders_{key}"] = s.get("numTraders")
        out[f"holder_change_{key}"] = s.get("holderChange")
    return out


# --------------------------------------------------------------------------- #
#  2) HELIUS — fresh wallet ratio (cần key free)
# --------------------------------------------------------------------------- #

def _top_holder_owners(mint: str, top_n: int) -> list:
    """Trả [(owner_address, ui_amount)] của top holder. Dùng 2 call RPC."""
    res = _rpc("getTokenLargestAccounts", [mint])
    if not isinstance(res, dict):
        return []
    accounts = res.get("value") or []
    if not accounts:
        return []
    token_accounts = [a.get("address") for a in accounts[:top_n * 2] if a.get("address")]
    amounts = {a.get("address"): _f((a.get("uiAmount") if a.get("uiAmount") is not None
                                     else a.get("uiAmountString"))) for a in accounts}
    if not token_accounts:
        return []

    parsed = _rpc("getMultipleAccounts", [token_accounts, {"encoding": "jsonParsed"}])
    if not isinstance(parsed, dict):
        return []
    owners = []
    for ta, acc in zip(token_accounts, parsed.get("value") or []):
        if not isinstance(acc, dict):
            continue
        try:
            info = acc["data"]["parsed"]["info"]
            owner = info.get("owner")
        except (KeyError, TypeError):
            continue
        if owner:
            owners.append((owner, amounts.get(ta, 0.0)))
    return owners[:top_n]


def _wallet_age_hours(owner: str) -> Optional[float]:
    """Tuổi ví Solana. Lấy 1000 chữ ký gần nhất trong 1 call:
    - nếu trả < 1000 -> đã thấy hết lịch sử, cái cuối là giao dịch đầu tiên (chính xác)
    - nếu trả = 1000 -> ví hoạt động nhiều, chắc chắn không phải ví mới 24h
    """
    res = _rpc("getSignaturesForAddress", [owner, {"limit": 1000}])
    if not isinstance(res, list):
        return None
    if not res:
        return None
    if len(res) >= 1000:
        return 9999.0  # rất hoạt động -> không phải fresh
    oldest = res[-1]
    bt = oldest.get("blockTime")
    if not bt:
        return None
    return max(0.0, (time.time() - float(bt)) / 3600.0)


def fresh_wallet_ratio(mint: str,
                       top_n: int = FRESH_WALLET_TOP_N,
                       max_age_h: float = FRESH_WALLET_MAX_AGE_H) -> Optional[float]:
    """% supply nằm ở ví mới tạo (<24h), tính trên top N holder.

    PROXY, KHÔNG PHẢI SỐ TUYỆT ĐỐI — chỉ soi top N ví. Cần HELIUS_API_KEY (free).
    Trả None nếu thiếu key / không đủ mẫu (thà không biết còn hơn báo số sai).
    """
    if not HELIUS_API_KEY:
        return None
    owners = _top_holder_owners(mint, top_n)
    if len(owners) < FRESH_WALLET_MIN_CHECKED:
        return None

    total = sum(a for _, a in owners)
    if total <= 0:
        return None

    fresh_amount = 0.0
    checked = 0
    for owner, amount in owners:
        age = _wallet_age_hours(owner)
        checked += 1
        if age is not None and age < max_age_h:
            fresh_amount += amount
    if checked < FRESH_WALLET_MIN_CHECKED:
        return None
    # % trên tổng của nhóm top N (không phải trên toàn supply)
    return round(fresh_amount / total * 100, 2)


# --------------------------------------------------------------------------- #
#  3) GeckoTerminal token info — gt_score, miễn phí
# --------------------------------------------------------------------------- #

def gt_token_info(mint: str, network: str = "solana") -> Optional[dict]:
    d = _get(f"{GT_API}/networks/{network}/tokens/{mint}/info", min_interval=2.1)
    if not isinstance(d, dict):
        return None
    attr = ((d.get("data") or {}).get("attributes")) or {}
    return {
        "gt_score": _f(attr.get("gt_score"), 0.0),
        "twitter_handle": attr.get("twitter_handle"),
        "telegram_handle": attr.get("telegram_handle"),
        "websites": attr.get("websites") or [],
        "description": attr.get("description") or "",
    }


# --------------------------------------------------------------------------- #
#  4) Social score 0-100 (Jupiter + GeckoTerminal)
# --------------------------------------------------------------------------- #

def social_presence_score(mint: str, symbol: str = "",
                          jup: Optional[dict] = None) -> Optional[float]:
    """Điểm hiện diện xã hội 0-100 từ nguồn miễn phí.

    KHÔNG phải TweetScout X-Score hay Kaito mindshare (cả hai đều không dùng được).
    Nó đo token CÓ hạ tầng + được Jupiter/GeckoTerminal đánh giá ra sao,
    không đo chất lượng follower hay % tương tác KOL tích xanh. Bộ lọc thô.

    Truyền sẵn `jup` (kết quả jupiter_signals) để khỏi gọi API 2 lần.
    """
    if jup is None:
        jup = jupiter_signals(mint)
    info = gt_token_info(mint)
    if jup is None and info is None:
        return None

    score = 0.0
    jup = jup or {}

    # organicScore của Jupiter là tín hiệu tốt nhất -> trọng số lớn nhất
    org = jup.get("organic_score", -1.0)
    if org is not None and org >= 0:
        score += min(45.0, org * 0.45)

    if jup.get("is_verified"):
        score += 15
    if jup.get("cexes"):
        score += 5
    if jup.get("twitter"):
        score += 12
    if jup.get("website"):
        score += 6

    if info:
        score += min(12.0, _f(info.get("gt_score")) * 0.12)
        if info.get("telegram_handle"):
            score += 5

    return round(min(100.0, score), 1)


# --------------------------------------------------------------------------- #
#  5) K.O bổ sung dựa trên Jupiter (dùng trong tầng K.O 2)
# --------------------------------------------------------------------------- #

def jupiter_ko(jup: Optional[dict],
               min_organic_score: float = 30.0,
               min_organic_buy_pct: float = 40.0,
               max_top_holders_pct: float = 25.0,
               max_dev_mints: int = 1) -> Optional[str]:
    """K.O dựa trên dữ liệu Jupiter. Trả lý do loại, hoặc None nếu qua.

    Không có dữ liệu Jupiter -> trả None (KHÔNG loại), vì token quá mới
    thường chưa được Jupiter index. Đừng để thiếu dữ liệu thành án tử.
    """
    if not jup:
        return None

    # mint/freeze: đối chiếu chéo với GoPlus. False = quyền CHƯA bị thu hồi.
    if jup.get("mint_disabled") is False:
        return "Jupiter: mint authority CHƯA thu hồi"
    if jup.get("freeze_disabled") is False:
        return "Jupiter: freeze authority CHƯA thu hồi"

    dm = jup.get("dev_mints")
    if isinstance(dm, (int, float)) and dm > max_dev_mints:
        return f"Jupiter: dev đã mint {int(dm)} lần (>{max_dev_mints})"

    org = jup.get("organic_score", -1.0)
    if org is not None and 0 <= org < min_organic_score:
        return f"organicScore {org:.0f} < {min_organic_score:.0f} (Jupiter đánh giá kém)"

    thp = jup.get("top_holders_pct", -1.0)
    if thp is not None and thp >= 0 and thp > max_top_holders_pct:
        return f"top holders {thp:.1f}% > {max_top_holders_pct}% (Jupiter)"

    # wash trading: % volume mua là THẬT
    pct1h = jup.get("organic_buy_pct_1h")
    if pct1h is not None and pct1h < min_organic_buy_pct:
        return f"chỉ {pct1h:.0f}% volume mua 1h là thật (<{min_organic_buy_pct:.0f}% -> wash trading)"
    return None


# --------------------------------------------------------------------------- #
#  HƯỚNG DẪN CẮM VÀO sol_meme_bot.py
# --------------------------------------------------------------------------- #
"""
BƯỚC 1 — Upload file này vào repo sol-meme-scanner, cùng cấp sol_meme_bot.py

BƯỚC 2 — Trong sol_meme_bot.py, THAY 3 hàm hook cũ (từ "def hook_fresh_wallet_ratio"
         đến hết "def hook_social_score") bằng:

# --- nguồn miễn phí (module free_sources_sol.py) ---
try:
    import free_sources_sol as fsol
except ImportError:
    fsol = None

def hook_fresh_wallet_ratio(mint: str, cfg: Config) -> Optional[float]:
    if fsol is None:
        return None
    return fsol.fresh_wallet_ratio(mint)

def hook_smart_money(mint: str, cfg: Config) -> Optional[dict]:
    # Không có nguồn miễn phí. Rẻ nhất Cielo Whale $199/thang.
    if not cfg.smart_money_api_key:
        return None
    return None

def hook_social_score(mint: str, symbol: str, cfg: Config) -> Optional[float]:
    if fsol is None:
        return None
    return fsol.social_presence_score(mint, symbol)


BƯỚC 3 (QUAN TRỌNG NHẤT) — thêm K.O Jupiter vào tầng 2.
         Trong hàm ko_stage2_goplus_sol, ngay TRƯỚC dòng "return None" cuối cùng,
         chèn:

    # --- K.O bổ sung từ Jupiter (organic score, wash trading, top holders) ---
    if fsol is not None:
        jup = fsol.jupiter_signals(c.token_address)
        if jup:
            c.jupiter = jup                      # lưu lại để chấm điểm/hiển thị
            ko_jup = fsol.jupiter_ko(jup)
            if ko_jup:
                return ko_jup

         Và thêm 1 dòng vào dataclass Candidate (ngay trên "score: float = 0.0"):

    jupiter: Optional[dict] = None

BƯỚC 4 — Lấy key Helius MIỄN PHÍ tại https://helius.dev (1M credit/tháng),
         thêm vào GitHub Secrets tên HELIUS_API_KEY. Workflow scanner-sol.yml
         đã có sẵn dòng env HELIUS_API_KEY nên không cần sửa gì thêm.
         (Không có key thì fresh-wallet trả None, mọi thứ khác vẫn chạy.)

BƯỚC 5 — Nếu lite-api.jup.ag bị chặn (log hiện "[jupiter] lite-api bị chặn"),
         lấy key tại portal.jup.ag, thêm Secret JUPITER_API_KEY và thêm dòng
         JUPITER_API_KEY: ${{ secrets.JUPITER_API_KEY }} vào env: của workflow.
"""
