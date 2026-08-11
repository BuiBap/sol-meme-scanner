#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
free_sources_sol.py — Nguồn dữ liệu MIỄN PHÍ bổ sung cho sol_meme_bot.py (Solana).

=============================================================================
 BẢN VÁ v2 (11/08/2026) — SỬA LỖI LÀM BOT IM LẶNG TỪ 26/07/2026
=============================================================================
Tín hiệu cuối cùng: 25/07 19:20 UTC. File này được thêm vào 26/07 15:14 UTC.
Sau đó 0 tín hiệu trong 17 ngày. Nguyên nhân nằm ở jupiter_ko() bản cũ:

 [1] min_organic_buy_pct = 40  -> LOẠI 100% TOKEN, kể cả SOL và USDC.
     Đo kiểm 11/08/2026 trên chính bảng top-organic-score của Jupiter
     (buyOrganicVolume / buyVolume, cửa sổ 1h):
         SOL   0.77%   |  USDC  3.7%
         CASH  10.2%   |  TOAD  13.8%  (organicScore 93 — token tốt nhất bảng)
     Jupiter tính mọi lệnh đi qua aggregator/router là INORGANIC, nên tỷ lệ này
     gần như không bao giờ vượt 15%. Ngưỡng mới: 5% (chỉ để bắt wash 100% bot).

 [2] max_dev_mints = 1 -> hiểu sai field. audit.devMints KHÔNG phải "dev in thêm
     supply mấy lần". Đo kiểm: SOL=1, USDC=1, nhưng CASH=11, TOAD=10 (dù
     mintAuthorityDisabled=true). Đây là số token ví dev đã từng phát hành.
     Ví dev pump.fun thường 10+. -> TẮT hẳn, thay bằng devBalancePercentage
     (dev còn ôm bao nhiêu % supply) — cái này mới thực sự là cờ đỏ.

 [3] max_top_holders_pct = 25 -> quá chặt. USDC 25.7%, USDT 34.7%, TOAD 28.0%.
     Trên Solana account LP/CEX/program cũng bị tính là holder. -> 45%.

 [4] min_organic_score = 30 -> pool 1-120h tuổi (đúng khoảng bot săn) thường
     Jupiter chưa kịp chấm và trả 0 -> "0 <= 0 < 30" -> K.O oan.
     -> hạ xuống 10 VÀ bỏ qua khi organicScore == 0 (chưa có dữ liệu).

THÊM MỚI:
  - jupiter_score_bonus()      : dữ liệu Jupiter giờ CỘNG ĐIỂM, không chỉ để loại.
  - jupiter_top_holders_pct()  : bù cho GoPlus khi mảng holders trả rỗng
                                 (đây là lý do top10_holder_pct = 0.0% trong CSV).
  - Mọi ngưỡng đọc được từ biến môi trường -> tinh chỉnh qua GitHub Secrets,
    không cần sửa code.
=============================================================================

NGUỒN CHÍNH: Jupiter Token API V2.
  organicScore (0-100)       : điểm chất lượng ĐÃ LỌC BOT của Jupiter
  buyOrganicVolume           : volume mua thật (đã trừ wash trading)
  numOrganicBuyers           : số người mua thật
  holderCount                : số holder thật
  audit.topHoldersPercentage : % top holder
  audit.devBalancePercentage : % supply ví dev còn giữ
  audit.mintAuthorityDisabled / freezeAuthorityDisabled : đối chiếu chéo GoPlus
  isVerified, tags, cexes, dev, twitter, website

SỰ THẬT VỀ TỪNG NGUỒN (kiểm chứng 11/08/2026):
  - Jupiter lite-api.jup.ag : MIỄN PHÍ, KHÔNG cần key, vẫn hoạt động tốt.
    Bản api.jup.ag cần x-api-key. Nếu lite-api bắt đầu chặn (log hiện cảnh báo),
    lấy key tại portal.jup.ag và set JUPITER_API_KEY.
  - Helius : MIỄN PHÍ 1M credit/tháng, 10 RPS. CẦN key (helius.dev).
    Chỉ dùng cho fresh-wallet ratio. Không có key -> bot tự bỏ qua.
  - GeckoTerminal /tokens/{addr}/info : MIỄN PHÍ, không key. Cho gt_score.
  - RugCheck : đã tích hợp sẵn trong sol_meme_bot.py, miễn phí.

KHÔNG dùng được (đừng mất công):
  - Kaito Yaps : ĐÃ KHAI TỬ 15/01/2026.
  - Smart money chất lượng cao : không có nguồn free. Rẻ nhất Cielo Whale $199/thg.

CÁCH VÁ VÀO sol_meme_bot.py: xem hướng dẫn cuối file.
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


def _env_f(name: str, default: float) -> float:
    """Đọc ngưỡng từ biến môi trường, sai kiểu thì dùng mặc định."""
    try:
        return float(os.getenv(name, ""))
    except (TypeError, ValueError):
        return default


# ---- NGƯỠNG K.O JUPITER (đã hiệu chỉnh bằng số đo thật 11/08/2026) ---------- #
# Muốn tinh chỉnh: thêm Secret/env cùng tên, KHÔNG cần sửa code.
JUP_MIN_ORGANIC_SCORE   = _env_f("JUP_MIN_ORGANIC_SCORE",   10.0)   # cũ: 30
JUP_MIN_ORGANIC_BUY_PCT = _env_f("JUP_MIN_ORGANIC_BUY_PCT",  1.0)   # cũ: 40 (chí mạng)
JUP_MAX_TOP_HOLDERS_PCT = _env_f("JUP_MAX_TOP_HOLDERS_PCT", 45.0)   # cũ: 25
JUP_MAX_DEV_BALANCE_PCT = _env_f("JUP_MAX_DEV_BALANCE_PCT",  5.0)   # MỚI (thay devMints)
JUP_MAX_DEV_MINTS       = _env_f("JUP_MAX_DEV_MINTS",      9999.0)  # cũ: 1 -> tắt

_session = requests.Session()
_session.headers.update({"Accept": "application/json",
                         "User-Agent": "sol-meme-bot-free-sources/2.0"})
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
        # MỚI: dev còn ôm bao nhiêu % supply — cờ đỏ THẬT, khác hẳn devMints
        "dev_balance_pct": (_f(audit.get("devBalancePercentage"), -1.0)
                            if audit.get("devBalancePercentage") is not None else None),
        "mint_disabled": audit.get("mintAuthorityDisabled"),
        "freeze_disabled": audit.get("freezeAuthorityDisabled"),
        "dev_mints": audit.get("devMints"),
        "dev_migrations": audit.get("devMigrations"),
        "is_verified": bool(t.get("isVerified")),
        "tags": t.get("tags") or [],
        "cexes": t.get("cexes") or [],
        "launchpad": t.get("launchpad"),
        "dev_wallet": t.get("dev"),
        "twitter": t.get("twitter"),
        "website": t.get("website"),
        "liquidity": _f(t.get("liquidity")),
        "mcap": _f(t.get("mcap")),
    }

    # --- Tỷ lệ volume THẬT: chỉ báo wash-trading tốt nhất có được miễn phí ---
    # LƯU Ý QUAN TRỌNG: giá trị điển hình là 1-15%, KHÔNG PHẢI 40-100%.
    # Jupiter coi lệnh qua aggregator/router là inorganic. Đừng đặt ngưỡng cao.
    for win in ("stats5m", "stats1h", "stats24h"):
        s = t.get(win) or {}
        buy_v = _f(s.get("buyVolume"))
        buy_org = _f(s.get("buyOrganicVolume"))
        sell_v = _f(s.get("sellVolume"))
        sell_org = _f(s.get("sellOrganicVolume"))
        key = win.replace("stats", "")
        out[f"organic_buy_pct_{key}"] = round(buy_org / buy_v * 100, 2) if buy_v > 0 else None
        out[f"buy_volume_{key}"] = buy_v
        out[f"organic_net_{key}"] = round(buy_org - sell_org, 2) if (buy_org or sell_org) else None
        out[f"organic_buyers_{key}"] = s.get("numOrganicBuyers")
        out[f"traders_{key}"] = s.get("numTraders")
        out[f"holder_change_{key}"] = s.get("holderChange")
        out[f"price_change_{key}"] = s.get("priceChange")
    return out


def jupiter_top_holders_pct(jup: Optional[dict]) -> Optional[float]:
    """% top holder theo Jupiter — dùng BÙ khi GoPlus trả mảng holders rỗng.

    Đây là lý do CSV cũ ghi top10_holder_pct = 0.0% cho cả 2 tín hiệu:
    GoPlus không index holder cho token mới -> bot cộng 9 điểm 'phân phối tốt'
    trong khi thực tế nó KHÔNG BIẾT GÌ. Số 0 giả đó nguy hiểm hơn là None.
    """
    if not jup:
        return None
    v = jup.get("top_holders_pct")
    if v is None or v < 0:
        return None
    return round(float(v), 2)


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
    - nếu trả < 1000 -> đã thấy hết lịch sử, cái cuối là giao dịch đầu tiên
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

    LUÔN truyền sẵn `jup` (kết quả jupiter_signals) để khỏi gọi Jupiter 2 lần
    cho cùng một token — bản cũ gọi lặp, tốn rate limit vô ích.
    """
    if jup is None:
        jup = jupiter_signals(mint)
    info = gt_token_info(mint)
    if jup is None and info is None:
        return None

    score = 0.0
    jup = jup or {}

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
#  5) K.O bổ sung dựa trên Jupiter — ĐÃ HIỆU CHỈNH
# --------------------------------------------------------------------------- #

def jupiter_ko(jup: Optional[dict],
               min_organic_score: float = None,
               min_organic_buy_pct: float = None,
               max_top_holders_pct: float = None,
               max_dev_balance_pct: float = None,
               max_dev_mints: float = None) -> Optional[str]:
    """K.O dựa trên dữ liệu Jupiter. Trả lý do loại, hoặc None nếu qua.

    Không có dữ liệu Jupiter -> trả None (KHÔNG loại), vì token quá mới
    thường chưa được Jupiter index. Đừng để thiếu dữ liệu thành án tử.

    NGUYÊN TẮC SAU BẢN VÁ: chỉ loại khi có BẰNG CHỨNG XẤU RÕ RÀNG.
    Thiếu dữ liệu / dữ liệu bằng 0 vì chưa index -> bỏ qua, để tầng khác quyết.
    """
    if not jup:
        return None

    min_organic_score   = JUP_MIN_ORGANIC_SCORE   if min_organic_score   is None else min_organic_score
    min_organic_buy_pct = JUP_MIN_ORGANIC_BUY_PCT if min_organic_buy_pct is None else min_organic_buy_pct
    max_top_holders_pct = JUP_MAX_TOP_HOLDERS_PCT if max_top_holders_pct is None else max_top_holders_pct
    max_dev_balance_pct = JUP_MAX_DEV_BALANCE_PCT if max_dev_balance_pct is None else max_dev_balance_pct
    max_dev_mints       = JUP_MAX_DEV_MINTS       if max_dev_mints       is None else max_dev_mints

    # --- 1. mint/freeze: đối chiếu chéo với GoPlus ---
    # Chỉ K.O khi Jupiter nói RÕ là False. Field vắng mặt (None) -> không kết luận.
    if jup.get("mint_disabled") is False:
        return "Jupiter: mint authority CHƯA thu hồi"
    if jup.get("freeze_disabled") is False:
        return "Jupiter: freeze authority CHƯA thu hồi"

    # --- 2. Dev còn ôm bao nhiêu % supply (thay cho devMints sai lệch) ---
    dbp = jup.get("dev_balance_pct")
    if dbp is not None and dbp >= 0 and dbp > max_dev_balance_pct:
        return f"dev còn giữ {dbp:.1f}% supply (>{max_dev_balance_pct:.0f}%)"

    # --- 3. devMints: MẶC ĐỊNH TẮT ---
    # audit.devMints = số token ví dev đã từng phát hành, KHÔNG phải số lần in
    # thêm supply của token này. TOAD=10, CASH=11 vẫn là token tốt.
    # Chỉ bật lại nếu anh chủ ý set JUP_MAX_DEV_MINTS.
    dm = jup.get("dev_mints")
    if isinstance(dm, (int, float)) and dm > max_dev_mints:
        return f"Jupiter: ví dev đã phát hành {int(dm)} token (>{int(max_dev_mints)})"

    # --- 4. organicScore ---
    # Bỏ qua khi = 0 hoặc âm: token quá mới, Jupiter chưa chấm điểm.
    org = jup.get("organic_score", -1.0)
    if org is not None and org > 0 and org < min_organic_score:
        return f"organicScore {org:.0f} < {min_organic_score:.0f} (Jupiter đánh giá kém)"

    # --- 5. Top holder concentration ---
    thp = jup.get("top_holders_pct", -1.0)
    if thp is not None and thp >= 0 and thp > max_top_holders_pct:
        return f"top holders {thp:.1f}% > {max_top_holders_pct:.0f}% (Jupiter)"

    # --- 6. Wash trading ---
    # THANG ĐO THỰC TẾ của organic_buy_pct là 1-15%, KHÔNG phải 40-100%.
    # Đo 11/08/2026: SOL 0.77% | USDT 2.9% | USDC 3.7% | CASH 10.2% | TOAD 13.8%.
    # Token volume càng lớn, tỷ lệ càng THẤP (nhiều lệnh đi qua router).
    # Vì vậy dùng 2 tín hiệu, cả hai đều chỉ bắt trường hợp wash gần như tuyệt đối:
    buyv1h = jup.get("buy_volume_1h") or 0
    if buyv1h >= 10_000:
        # (a) có volume mua nhưng KHÔNG một người mua thật nào -> bot 100%
        ob = jup.get("organic_buyers_1h")
        if isinstance(ob, (int, float)) and ob == 0:
            return f"0 người mua thật trong 1h dù volume mua ${buyv1h:,.0f} (bot 100%)"
        # (b) sàn tuyệt đối
        pct1h = jup.get("organic_buy_pct_1h")
        if pct1h is not None and pct1h < min_organic_buy_pct:
            return (f"chỉ {pct1h:.1f}% volume mua 1h là thật "
                    f"(<{min_organic_buy_pct:.1f}% -> wash trading)")
    return None


# --------------------------------------------------------------------------- #
#  6) MỚI — Jupiter CỘNG ĐIỂM (bản cũ chỉ dùng Jupiter để loại, không để thưởng)
# --------------------------------------------------------------------------- #

def jupiter_score_bonus(jup: Optional[dict]) -> tuple:
    """Trả (điểm_cộng, [lý_do]). Tối đa +15 để không phá cân bằng thang 100.

    Cố tình chồng lấn ÍT với social_presence_score (vốn cũng dùng organicScore),
    nên trọng số ở đây đặt nhẹ.
    """
    if not jup:
        return 0.0, []

    pts, why = 0.0, []

    org = jup.get("organic_score", -1.0)
    if org is not None and org >= 70:
        pts += 8; why.append(f"organicScore {org:.0f} (cao)")
    elif org is not None and org >= 40:
        pts += 5; why.append(f"organicScore {org:.0f}")
    elif org is not None and org >= 20:
        pts += 2

    pct1h = jup.get("organic_buy_pct_1h")
    if pct1h is not None:
        if pct1h >= 15:
            pts += 4; why.append(f"volume mua thật 1h {pct1h:.0f}%")
        elif pct1h >= 8:
            pts += 2

    hc = jup.get("holder_change_1h")
    if isinstance(hc, (int, float)) and hc > 0:
        pts += 2; why.append(f"holder tăng 1h +{hc:.1f}%")

    if jup.get("is_verified"):
        pts += 1; why.append("Jupiter verified")

    return round(min(15.0, pts), 1), why


# --------------------------------------------------------------------------- #
#  7) Tự kiểm tra nhanh:  python free_sources_sol.py <mint>
# --------------------------------------------------------------------------- #

def _selftest(mint: str):
    print(f"=== Jupiter signals cho {mint} ===")
    jup = jupiter_signals(mint)
    if not jup:
        print("  KHÔNG có dữ liệu Jupiter (token quá mới hoặc lite-api bị chặn).")
        print("  -> jupiter_ko() sẽ trả None, KHÔNG loại token. Đúng thiết kế.")
        return
    for k in ("organic_score", "organic_label", "top_holders_pct", "dev_balance_pct",
              "dev_mints", "mint_disabled", "freeze_disabled", "holder_count",
              "organic_buy_pct_5m", "organic_buy_pct_1h", "organic_buy_pct_24h",
              "buy_volume_1h", "holder_change_1h", "is_verified", "launchpad"):
        print(f"  {k:22} = {jup.get(k)}")
    ko = jupiter_ko(jup)
    print(f"\n  --> jupiter_ko: {ko if ko else 'QUA ✅'}")
    bonus, why = jupiter_score_bonus(jup)
    print(f"  --> điểm cộng : +{bonus}  {why}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        _selftest(sys.argv[1])
    else:
        print("Dùng: python free_sources_sol.py <mint_address>")
        print("Ví dụ (token thật, organicScore cao):")
        print("  python free_sources_sol.py A13oRB9FFaiUjfi6LdCg6p9ka1u8SfGkUFs4SKvPpump")


# --------------------------------------------------------------------------- #
#  HƯỚNG DẪN VÁ sol_meme_bot.py — xem file HUONG_DAN_VA.md
# --------------------------------------------------------------------------- #
