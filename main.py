import yfinance as yf
import pandas as pd
import numpy as np
import os
import json
import smtplib
import time
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
from datetime import datetime

# ============================================================================
#  Sentinel Pro 6.0 — 多因子智能定投决策引擎
#  架构：5 层流水线
#    Layer 1: 宏观上下文采集 (VIX / US10Y / DXY)
#    Layer 2: 技术指标引擎   (RSI / ADX / MACD / ATR)
#    Layer 3: 风控 & 资金管理 (动态倍率 / 相关性熔断)
#    Layer 4: AI 决策审核     (智谱 GLM-4 首席风控官)
#    Layer 5: 报告 & 日志     (HTML 邮件 / CSV 日志)
# ============================================================================


# ---------------------------------------------------------------------------
#  Layer 1: 数据采集 & 宏观上下文
# ---------------------------------------------------------------------------

def fetch_macro_context() -> dict:
    """
    获取三维宏观市场上下文：VIX、10Y美债收益率、美元指数。

    返回字典包含:
      vix            - CBOE 恐慌指数 (默认 18)
      us10y          - 10 年期美债收益率 (默认 4.0)
      us10y_chg_pct  - 周涨幅百分比 (默认 0)
      us10y_at_1y_hi - 是否处于 1 年高位 (默认 False)
      dxy            - 美元指数 (默认 100)
      dxy_above_ma20 - 美元是否站上 20 日均线 (默认 False)
      dxy_trending_up- 美元是否处于上升通道 (默认 False)

    金融逻辑:
      - 美债利率飙升 → 资金从权益类流出，压制股票估值
      - 美元走强 → 非美资产计价缩水，新兴市场资金外流
    """
    ctx = {
        "vix": 18.0,
        "us10y": 4.0, "us10y_chg_pct": 0.0, "us10y_at_1y_hi": False,
        "dxy": 100.0, "dxy_above_ma20": False, "dxy_trending_up": False,
    }

    # --- VIX ---
    try:
        vix_data = yf.download("^VIX", period="5d", progress=False)
        if not vix_data.empty:
            p = vix_data['Close']
            ctx["vix"] = float(p.iloc[-1, 0] if isinstance(p, pd.DataFrame) else p.iloc[-1])
    except Exception:
        print("⚠️ VIX 数据获取失败，使用默认值")

    # --- 10Y 美债收益率 (^TNX) ---
    try:
        tnx_data = yf.download("^TNX", period="1y", progress=False)
        if not tnx_data.empty:
            p = tnx_data['Close']
            closes = p.iloc[:, 0] if isinstance(p, pd.DataFrame) else p
            ctx["us10y"] = float(closes.iloc[-1])

            # 周涨幅 (与 5 个交易日前比较)
            if len(closes) >= 6:
                prev = float(closes.iloc[-6])
                if prev > 0:
                    ctx["us10y_chg_pct"] = round((float(closes.iloc[-1]) - prev) / prev * 100, 2)

            # 是否处于 1 年高位 (最近 250 个交易日)
            one_year = closes.tail(250)
            ctx["us10y_at_1y_hi"] = float(closes.iloc[-1]) >= float(one_year.max()) * 0.98
    except Exception:
        print("⚠️ US10Y 数据获取失败，使用默认值")

    # --- 美元指数 (DX-Y.NYB) ---
    try:
        dxy_data = yf.download("DX-Y.NYB", period="3mo", progress=False)
        if not dxy_data.empty:
            p = dxy_data['Close']
            closes = p.iloc[:, 0] if isinstance(p, pd.DataFrame) else p
            ctx["dxy"] = float(closes.iloc[-1])

            # 是否站上 20 日均线
            ma20 = closes.rolling(20).mean()
            if not ma20.empty and not pd.isna(ma20.iloc[-1]):
                ctx["dxy_above_ma20"] = float(closes.iloc[-1]) > float(ma20.iloc[-1])

            # 上升通道：20 日均线 > 60 日均线
            ma60 = closes.rolling(60).mean()
            if not ma60.empty and not pd.isna(ma60.iloc[-1]) and not pd.isna(ma20.iloc[-1]):
                ctx["dxy_trending_up"] = float(ma20.iloc[-1]) > float(ma60.iloc[-1])
    except Exception:
        print("⚠️ DXY 数据获取失败，使用默认值")

    return ctx


# ---------------------------------------------------------------------------
#  Layer 2: 技术指标引擎 (全部使用 pandas 原生计算，零外部依赖)
# ---------------------------------------------------------------------------

def calculate_rsi(prices: pd.Series, period: int = 14) -> float:
    """
    计算 RSI (Relative Strength Index)。
    RSI < 30 → 超卖；RSI > 70 → 超买。
    """
    try:
        delta = prices.diff()
        gain = delta.where(delta > 0, 0).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return round(float(rsi.iloc[-1]), 1)
    except Exception:
        return 50.0


def calculate_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> dict:
    """
    计算 ADX (Average Directional Index) — 衡量趋势强弱。

    返回:
      adx      - ADX 值 (>25 = 强趋势, <20 = 无趋势/震荡)
      plus_di  - +DI (多头方向指标)
      minus_di - -DI (空头方向指标)

    金融逻辑:
      ADX > 25 且 -DI > +DI → 强下行趋势，严禁"接飞刀"
    """
    try:
        # True Range
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # +DM / -DM (Directional Movement)
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low
        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0)

        # 平滑 (Wilder's smoothing ≈ EMA with alpha=1/period)
        atr = tr.ewm(alpha=1/period, min_periods=period).mean()
        plus_di = 100 * (plus_dm.ewm(alpha=1/period, min_periods=period).mean() / atr)
        minus_di = 100 * (minus_dm.ewm(alpha=1/period, min_periods=period).mean() / atr)

        # DX 和 ADX
        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di))
        adx = dx.ewm(alpha=1/period, min_periods=period).mean()

        return {
            "adx": round(float(adx.iloc[-1]), 1),
            "plus_di": round(float(plus_di.iloc[-1]), 1),
            "minus_di": round(float(minus_di.iloc[-1]), 1),
        }
    except Exception:
        return {"adx": 20.0, "plus_di": 25.0, "minus_di": 25.0}


def calculate_macd(prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """
    计算 MACD (Moving Average Convergence Divergence)。

    返回:
      macd_line      - MACD 线 (快线 - 慢线)
      signal_line    - 信号线 (MACD 的 9 日 EMA)
      histogram      - 柱状图 (MACD - Signal)
      hist_shrinking - 柱状图是否缩短 (动量衰减信号)

    金融逻辑:
      价格 < MA 且 hist_shrinking=True → 下跌动量衰竭，是潜在加仓时机
      价格 < MA 且 hist_shrinking=False → 动量仍在加速下跌，不宜加仓
    """
    try:
        ema_fast = prices.ewm(span=fast, adjust=False).mean()
        ema_slow = prices.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line

        # 柱状图是否在缩短：比较最近 3 根柱状图的绝对值变化方向
        hist_vals = histogram.dropna().tail(3)
        hist_shrinking = False
        if len(hist_vals) >= 3:
            abs_vals = hist_vals.abs()
            # 连续两期绝对值缩小 → 动量衰减
            hist_shrinking = bool(abs_vals.iloc[-1] < abs_vals.iloc[-2] and
                                  abs_vals.iloc[-2] < abs_vals.iloc[-3])

        return {
            "macd_line": round(float(macd_line.iloc[-1]), 4),
            "signal_line": round(float(signal_line.iloc[-1]), 4),
            "histogram": round(float(histogram.iloc[-1]), 4),
            "hist_shrinking": hist_shrinking,
        }
    except Exception:
        return {"macd_line": 0, "signal_line": 0, "histogram": 0, "hist_shrinking": False}


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> dict:
    """
    计算 ATR (Average True Range) — 衡量市场波动率。

    返回:
      atr          - 当前 14 日 ATR
      atr_avg      - 历史平均 ATR (250 日均值)
      atr_ratio    - atr / atr_avg，>1.5 说明处于极端波动
      stop_loss    - 动态止损位 = 当前价 - 2 * ATR

    金融逻辑:
      ATR 高 → 市场恐慌/不确定 → 缩小单次头寸
      动态止损用 ATR 而非固定百分比，自适应市场节奏
    """
    try:
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr_series = tr.rolling(window=period).mean()
        current_atr = float(atr_series.iloc[-1])
        # 历史平均 ATR：取最近 250 个 ATR 值的均值
        atr_avg = float(atr_series.tail(250).mean())

        atr_ratio = current_atr / atr_avg if atr_avg > 0 else 1.0
        stop_loss = float(close.iloc[-1]) - 2 * current_atr

        return {
            "atr": round(current_atr, 4),
            "atr_avg": round(atr_avg, 4),
            "atr_ratio": round(atr_ratio, 2),
            "stop_loss": round(stop_loss, 2),
        }
    except Exception:
        return {"atr": 0, "atr_avg": 0, "atr_ratio": 1.0, "stop_loss": 0}


# ---------------------------------------------------------------------------
#  Layer 3: 风控 & 资金管理
# ---------------------------------------------------------------------------

def calculate_correlation_matrix(assets: dict, period: str = "1y") -> pd.DataFrame:
    """
    计算 assets.json 中所有资产的相关性矩阵。

    逻辑:
      - 批量拉取所有 ticker 的日收盘价
      - 计算日收益率的皮尔逊相关系数
      - corr > 0.85 的资产对视为"高度相关"，后续在 apply_risk_caps 中处理
    """
    tickers = {name: info['ticker'] for name, info in assets.items()}
    names = list(tickers.keys())

    try:
        # 批量下载
        ticker_list = list(tickers.values())
        data = yf.download(ticker_list, period=period, progress=False)

        if data.empty:
            return pd.DataFrame(1.0, index=names, columns=names)

        # 提取收盘价并按资产名重命名列
        close = data['Close']
        if isinstance(close, pd.Series):
            # 只有一个 ticker 时
            close = close.to_frame(columns=[names[0]])
        else:
            # 多个 ticker，列名是 ticker 符号，需要映射回资产名
            ticker_to_name = {v: k for k, v in tickers.items()}
            close = close.rename(columns=ticker_to_name)

        # 日收益率相关性
        returns = close.pct_change().dropna()
        corr = returns.corr()
        return corr

    except Exception as e:
        print(f"⚠️ 相关性矩阵计算失败: {e}")
        return pd.DataFrame(1.0, index=names, columns=names)


def compute_multiplier(curr_price: float, close_prices: pd.Series,
                       macro_ctx: dict, indicators: dict,
                       asset_currency: str = "USD") -> dict:
    """
    核心：基于多维信号计算动态加仓倍率 m。

    采用百分比权重系统替代固定加减法:
      base_m = 1.0，在此基础上按百分比累加/扣除权重。

    参数:
      curr_price    - 当前价格
      close_prices  - 历史收盘价 Series
      macro_ctx     - fetch_macro_context() 返回值
      indicators    - 包含 rsi, adx, macd, atr 的 dict
      asset_currency- 资产计价货币 (判断是否受美元影响)

    返回:
      m         - 最终倍率
      signals   - 触发的信号说明列表
      stop_loss - ATR 动态止损位
      factors   - 因子权重分布 (供报告展示)
    """
    base_m = 1.0
    signals = []
    # 因子权重分布记录，用于报告中展示"师出有名"
    factors = {"macro": 0.0, "ma": 0.0, "rsi": 0.0, "adx": 0.0,
               "macd": 0.0, "atr": 0.0, "vix": 0.0}

    rsi = indicators.get("rsi", 50)
    adx_data = indicators.get("adx", {})
    macd_data = indicators.get("macd", {})
    atr_data = indicators.get("atr", {})

    adx = adx_data.get("adx", 20)
    plus_di = adx_data.get("plus_di", 25)
    minus_di = adx_data.get("minus_di", 25)
    hist_shrinking = macd_data.get("hist_shrinking", False)
    histogram = macd_data.get("histogram", 0)
    atr_ratio = atr_data.get("atr_ratio", 1.0)
    atr_val = atr_data.get("atr", 0)
    atr_avg = atr_data.get("atr_avg", 0)
    stop_loss = atr_data.get("stop_loss", 0)

    vix = macro_ctx.get("vix", 18)
    us10y_chg_pct = macro_ctx.get("us10y_chg_pct", 0)
    us10y_at_1y_hi = macro_ctx.get("us10y_at_1y_hi", False)
    dxy_above_ma20 = macro_ctx.get("dxy_above_ma20", False)
    dxy_trending_up = macro_ctx.get("dxy_trending_up", False)

    weight = 0.0  # 累计百分比偏移

    # ---------------------------------------------------------------
    # 1) 均线偏离度 — 价格低于均线越深，权重越大 (百分比制)
    # ---------------------------------------------------------------
    ma_windows = [20, 60, 120, 250]
    ma_weights = [0.10, 0.15, 0.20, 0.25]
    ma_contribution = 0.0
    for w, mw in zip(ma_windows, ma_weights):
        ma_val = float(close_prices.rolling(w).mean().iloc[-1])
        if not pd.isna(ma_val) and curr_price < ma_val:
            deviation = (ma_val - curr_price) / ma_val  # 偏离比例
            contribution = mw * (1 + deviation)
            ma_contribution += contribution
            signals.append(f"📉 价格低于 MA{w} ({deviation:.1%})")
        elif not pd.isna(ma_val) and curr_price > ma_val * 1.05:
            # 价格显著高于均线，适当减权
            ma_contribution -= mw * 0.3

    weight += ma_contribution
    factors["ma"] = round(ma_contribution, 3)

    # ---------------------------------------------------------------
    # 2) RSI 信号 (百分比)
    # ---------------------------------------------------------------
    rsi_contribution = 0.0
    if rsi < 30:
        rsi_contribution = 0.20
        signals.append(f"🔵 RSI={rsi} 严重超卖")
    elif rsi < 35:
        rsi_contribution = 0.15
        signals.append(f"🔵 RSI={rsi} 超卖")
    elif rsi > 70:
        rsi_contribution = -0.25
        signals.append(f"🔴 RSI={rsi} 超买")
    elif rsi > 65:
        rsi_contribution = -0.15
        signals.append(f"🟡 RSI={rsi} 偏高")
    weight += rsi_contribution
    factors["rsi"] = round(rsi_contribution, 3)

    # ---------------------------------------------------------------
    # 3) VIX 恐慌溢价 — 非线性放大
    # ---------------------------------------------------------------
    vix_contribution = 0.0
    if vix > 30:
        vix_contribution = 0.15
        signals.append(f"😱 VIX={vix:.1f} 极度恐慌")
    elif vix > 25:
        vix_contribution = 0.10 * (vix - 25) / 25  # 随 VIX 非线性放大
        signals.append(f"😰 VIX={vix:.1f} 高恐慌")
    weight += vix_contribution
    factors["vix"] = round(vix_contribution, 3)

    # ---------------------------------------------------------------
    # 4) ADX 趋势过滤 (硬约束 — 强下行时一票否决加仓)
    # ---------------------------------------------------------------
    adx_contribution = 0.0
    if adx > 25 and minus_di > plus_di:
        # 强下行趋势：无论 RSI 多超卖，都不加仓
        weight = min(weight, 0.0)
        adx_contribution = -abs(weight) if weight > 0 else 0
        signals.append(f"⛔ ADX={adx} +DI={plus_di} -DI={minus_di} 强下行趋势，禁止加仓")
    elif adx > 25 and plus_di > minus_di:
        adx_contribution = 0.05
        signals.append(f"✅ ADX={adx} 强上行趋势")
    weight += adx_contribution
    factors["adx"] = round(adx_contribution, 3)

    # ---------------------------------------------------------------
    # 5) MACD 动量确认 (门控逻辑)
    #    价格 < MA20 时，只有 MACD 柱状图缩短(动量衰减)才允许满额加仓
    # ---------------------------------------------------------------
    macd_contribution = 0.0
    ma20_val = float(close_prices.rolling(20).mean().iloc[-1])
    if not pd.isna(ma20_val) and curr_price < ma20_val:
        if not hist_shrinking:
            # 动量仍在加速下跌，减半加仓力度
            penalty = weight * 0.5 if weight > 0 else 0
            macd_contribution = -penalty
            weight -= penalty
            signals.append(f"🔸 MACD 动量未衰减 (hist={histogram:.4f})，加仓力度减半")
        else:
            signals.append(f"🟢 MACD 柱状图缩短，动量衰减确认")

    factors["macd"] = round(macd_contribution, 3)

    # ---------------------------------------------------------------
    # 6) ATR 动态头寸控制
    #    当前波动率 > 历史均值 1.5 倍 → 乘以 ATR_avg/ATR_current 系数
    # ---------------------------------------------------------------
    atr_contribution = 0.0
    if atr_ratio > 1.5 and atr_val > 0:
        # 极端波动：m_adj = ATR_avg / ATR_current (< 1，起到缩仓作用)
        m_adj = atr_avg / atr_val if atr_val > 0 else 1.0
        atr_contribution = (m_adj - 1) * (base_m + weight)  # 负值，缩减总倍率
        signals.append(f"📊 ATR 波动比={atr_ratio:.2f}x (极端)，头寸缩减系数={m_adj:.2f}")
    elif atr_ratio > 1.2:
        m_adj = 0.9  # 轻度高波动，打9折
        atr_contribution = -0.1 * (base_m + weight)
        signals.append(f"📊 ATR 波动比={atr_ratio:.2f}x (偏高)，头寸轻度缩减")

    weight += atr_contribution
    factors["atr"] = round(atr_contribution, 3)

    # ---------------------------------------------------------------
    # 7) 宏观因子 — "一票否决"与"系数修正"
    # ---------------------------------------------------------------
    macro_contribution = 0.0
    macro_cap = 3.5  # 默认倍率上限

    # (a) 美债收益率飙升 → 一票否决: 倍率上限锁定 1.0
    if us10y_chg_pct > 5.0 or us10y_at_1y_hi:
        macro_cap = 1.0
        if us10y_chg_pct > 5.0:
            signals.append(f"🚨 美债收益率周涨 {us10y_chg_pct:.1f}%，触发一票否决 (m ≤ 1.0)")
        if us10y_at_1y_hi:
            signals.append(f"🚨 美债收益率处于 1 年高位，触发一票否决 (m ≤ 1.0)")

    # (b) 美元强势 → 非美资产减权 20%
    is_non_usd = asset_currency.upper() != "USD"
    if dxy_trending_up and is_non_usd:
        # 美元上升通道 + 非美资产 → 打 80% 系数
        penalty = (base_m + weight) * 0.2
        macro_contribution -= penalty
        signals.append(f"💵 美元上升通道，非美资产({asset_currency})减权 w_macro=0.8")
    elif dxy_above_ma20 and is_non_usd:
        # 美元偏强（但非趋势性上升）→ 打 90%
        penalty = (base_m + weight) * 0.1
        macro_contribution -= penalty
        signals.append(f"💵 美元偏强，非美资产({asset_currency})减权 w_macro=0.9")

    weight += macro_contribution
    factors["macro"] = round(macro_contribution, 3)

    # ---------------------------------------------------------------
    # 最终倍率计算
    # ---------------------------------------------------------------
    m = base_m + weight
    m = round(max(0.3, min(m, macro_cap)), 2)  # 限制在 [0.3, macro_cap]

    return {
        "m": m,
        "signals": signals,
        "stop_loss": stop_loss,
        "factors": factors,
    }


def apply_risk_caps(results: list, corr_matrix: pd.DataFrame, assets: dict) -> list:
    """
    资产相关性熔断机制 — 避免在高度相关的资产上重复下注。

    规则:
      如果两个资产的相关性 > 0.85，且同时触发买入信号 (m > 1.0)：
        - 总买入额度不超过两者中信号最强(m最大)的那一个
        - 即：保留 m 较大的那个不变，较小的那个 m 降至使总额不超限

    实现方式:
      遍历所有资产对，检查相关性。如有冲突，按比例缩减。
    """
    if corr_matrix.empty or len(results) < 2:
        return results

    # 建立 name → index 映射
    name_to_idx = {r["name"]: i for i, r in enumerate(results)}
    processed_pairs = set()

    for i, r1 in enumerate(results):
        for j, r2 in enumerate(results):
            if i >= j:
                continue
            pair_key = (r1["name"], r2["name"])
            if pair_key in processed_pairs:
                continue
            processed_pairs.add(pair_key)

            # 查相关系数
            try:
                corr_val = float(corr_matrix.loc[r1["name"], r2["name"]])
            except (KeyError, ValueError):
                continue

            if corr_val > 0.85 and r1["m"] > 1.0 and r2["m"] > 1.0:
                # 两者高度相关且都触发买入 → 熔断
                base1 = assets.get(r1["name"], {}).get("base_amount", 100)
                base2 = assets.get(r2["name"], {}).get("base_amount", 100)

                # 总额度上限 = max(r1.rmb, r2.rmb)
                max_single = max(r1["rmb"], r2["rmb"])

                if r1["rmb"] + r2["rmb"] > max_single * 1.5:
                    # 需要缩减: 按 m 值比例分配总额度
                    total_m = r1["m"] + r2["m"]
                    budget = max_single * 1.5  # 允许 1.5 倍而非 1 倍，给一些弹性

                    new_rmb1 = budget * (r1["m"] / total_m)
                    new_rmb2 = budget * (r2["m"] / total_m)

                    new_m1 = round(new_rmb1 / base1, 2) if base1 > 0 else r1["m"]
                    new_m2 = round(new_rmb2 / base2, 2) if base2 > 0 else r2["m"]

                    old_m1, old_m2 = r1["m"], r2["m"]
                    results[i]["m"] = max(0.3, new_m1)
                    results[i]["rmb"] = round(base1 * results[i]["m"], 2)
                    results[j]["m"] = max(0.3, new_m2)
                    results[j]["rmb"] = round(base2 * results[j]["m"], 2)

                    msg = (f"🔗 相关性熔断: {r1['name']}↔{r2['name']} "
                           f"(corr={corr_val:.2f}) — "
                           f"m: {old_m1}→{results[i]['m']}, {old_m2}→{results[j]['m']}")
                    results[i]["signals"].append(msg)
                    results[j]["signals"].append(msg)
                    print(msg)

    return results


# ---------------------------------------------------------------------------
#  Layer 4: AI 决策审核 (智谱 GLM-4)
# ---------------------------------------------------------------------------

def get_ai_advice(macro_ctx: dict, total_amt: float, results: list) -> str | None:
    """
    调用智谱 AI (GLM-4-Flash) 获取首席风控官视角的执行建议。

    升级点:
      - 角色从"策略师"升级为"首席风控官 (CRO)"
      - 数据包中标注指标背离情况
      - 要求 AI 分析"多头陷阱 (Bull Trap)"风险
    保留:
      - 5 次异步重试机制 + 指数退避
    """
    api_key = os.getenv('ZHIPU_API_KEY')
    if not api_key:
        print("❌ 错误：未设置 ZHIPU_API_KEY")
        return None

    url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # --- 构建数据包 ---
    vix = macro_ctx.get("vix", 18)
    us10y = macro_ctx.get("us10y", 4.0)
    us10y_chg = macro_ctx.get("us10y_chg_pct", 0)
    dxy = macro_ctx.get("dxy", 100)

    data_summary = (
        f"=== 宏观环境 ===\n"
        f"VIX: {vix:.1f} | US10Y: {us10y:.2f}% (周变化: {us10y_chg:+.1f}%) | "
        f"DXY: {dxy:.1f} {'↑上升通道' if macro_ctx.get('dxy_trending_up') else '→中性'}\n"
        f"总预算: {total_amt:.0f} RMB\n\n"
        f"=== 各资产信号详情 ===\n"
    )

    divergences = []  # 收集背离情况

    for r in results:
        rsi = r.get("rsi", 50)
        macd_hist = r.get("macd_hist", 0)
        hist_shrinking = r.get("hist_shrinking", False)
        adx = r.get("adx", 20)
        plus_di = r.get("plus_di", 25)
        minus_di = r.get("minus_di", 25)

        data_summary += (
            f"  {r['name']}: 价格={r['p']} | RSI={rsi} | ADX={adx} "
            f"(+DI={plus_di}, -DI={minus_di}) | "
            f"MACD柱状={'缩短↑' if hist_shrinking else '扩大↓'} | "
            f"倍率={r['m']}x | 金额=¥{r['rmb']}\n"
            f"    触发信号: {'; '.join(r.get('signals', ['无']))}\n"
            f"    因子权重: {r.get('factors', {})}\n"
        )

        # --- 标注背离情况 ---
        # 背离1: RSI 超卖但 MACD 动量仍在加速下跌
        if rsi < 35 and not hist_shrinking:
            divergences.append(
                f"⚠️ {r['name']}: RSI={rsi} 超卖，但 MACD 动能继续向下 → 存在多头陷阱风险"
            )
        # 背离2: VIX 高但 ADX 显示无趋势
        if vix > 25 and adx < 20:
            divergences.append(
                f"⚠️ {r['name']}: VIX={vix:.0f} 高恐慌，但 ADX={adx} 显示无明确趋势 → 可能是假恐慌"
            )
        # 背离3: RSI 超买但趋势强劲向上
        if rsi > 65 and adx > 25 and plus_di > minus_di:
            divergences.append(
                f"⚠️ {r['name']}: RSI={rsi} 偏高，但 ADX={adx} 强上行 → 可能是合理趋势延续"
            )

    if divergences:
        data_summary += f"\n=== 🔍 检测到的指标背离 ===\n"
        for d in divergences:
            data_summary += f"  {d}\n"

    # --- 系统提示词：首席风控官 ---
    system_prompt = (
        "你是一位拥有 CFA 资格的首席风控官 (CRO)，负责审核量化系统的执行建议。\n\n"
        "### 你将收到的数据：\n"
        "1. **宏观因子**: VIX、10Y美债收益率及周变化、美元指数走势\n"
        "2. **各资产详情**: 价格、RSI、ADX(含+DI/-DI)、MACD柱状图状态、触发信号列表、因子权重\n"
        "3. **背离标注**: 系统已标注的指标间矛盾/背离情况\n\n"
        "### 你的分析框架：\n"
        "1. **背离分析**: 重点分析系统标注的每一个背离。对于'RSI超卖+MACD动能下行'的组合，"
        "明确判断：该信号是否为'多头陷阱 (Bull Trap)'？给出概率评估和依据。\n"
        "2. **倍率合理性**: 审核量化系统给出的倍率是否合理。如有不妥，给出具体调整建议和理由。\n"
        "3. **跨资产风险**: 检查是否有被忽略的联动风险或集中度风险。\n"
        "4. **宏观一致性**: 判断宏观环境是否支持当前的整体仓位方向。\n\n"
        "### 输出格式：\n"
        "请给出 3-5 条简练的执行建议，使用 <li> 标签。\n"
        "每条建议必须包含：\n"
        "- 具体的逻辑推导依据\n"
        "- 如涉及背离，明确注明'Bull Trap 风险: 高/中/低'\n"
        "- 建议的具体行动（持有/加仓/减仓/观望）"
    )

    payload = {
        "model": "glm-4-flash",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请分析以下量化数据并给出风控建议：\n\n{data_summary}"}
        ],
        "temperature": 0.2
    }

    # --- 5 次重试 + 指数退避 ---
    for attempt in range(5):
        try:
            print(f"📡 正在呼叫 AI 决策引擎 (第 {attempt+1}/5 次)...")
            response = requests.post(url, headers=headers, json=payload, timeout=(15, 100))
            response.raise_for_status()
            res_data = response.json()
            return res_data['choices'][0]['message']['content']
        except Exception as e:
            print(f"⚠️ 连接 AI 接口失败 (Attempt {attempt+1}): {e}")
            if attempt < 4:
                time.sleep((attempt + 1) * 10)
            else:
                print("❌ 跨海链路严重受阻，已达重试上限。")
    return None


# ---------------------------------------------------------------------------
#  Layer 5: 报告 & 日志
# ---------------------------------------------------------------------------

def send_report(title: str, total_rmb: float, results: list,
                macro_ctx: dict, ai_advice: str | None):
    """
    生成 HTML 邮件报告并发送。

    升级点:
      - 宏观数据卡片 (VIX / US10Y / DXY)
      - 资产表增加 ADX / MACD / Signals 列
      - 每个资产附带因子权重分布 (师出有名)
    """
    mail_user = os.getenv('EMAIL_USER')
    mail_pass = os.getenv('EMAIL_PASS')
    receiver = os.getenv('EMAIL_RECEIVER')

    if not all([mail_user, mail_pass, receiver]):
        print("⚠️ 邮件环境变量配置不全，跳过发送。")
        return

    vix = macro_ctx.get("vix", 18)
    us10y = macro_ctx.get("us10y", 4.0)
    us10y_chg = macro_ctx.get("us10y_chg_pct", 0)
    dxy = macro_ctx.get("dxy", 100)

    # --- 资产行 ---
    rows_html = ""
    for r in results:
        # 倍率着色
        m = r['m']
        if m >= 1.3:
            m_bg, m_color = '#e6f4ea', '#137333'
        elif m <= 0.6:
            m_bg, m_color = '#fce8e6', '#c5221f'
        else:
            m_bg, m_color = '#f8f9fa', '#3c4043'

        # MACD 方向
        macd_dir = "↑衰减" if r.get("hist_shrinking", False) else "↓加速"
        macd_color = "#137333" if r.get("hist_shrinking", False) else "#c5221f"

        # 信号摘要 (取前 2 条)
        sig_list = r.get("signals", [])
        sig_text = "<br>".join(sig_list[:2])
        if len(sig_list) > 2:
            sig_text += f"<br>...+{len(sig_list)-2}条"

        # 因子权重分布
        factors = r.get("factors", {})
        factor_parts = []
        for k, v in factors.items():
            if v != 0:
                prefix = "+" if v > 0 else ""
                factor_parts.append(f"{k}:{prefix}{v}")
        factor_text = " | ".join(factor_parts) if factor_parts else "—"

        rows_html += f"""
    <tr style="border-bottom: 1px solid #dadce0;">
        <td style="padding:14px 8px; color:#1a73e8; font-weight:500;">{r['name']}</td>
        <td style="padding:14px 8px; text-align:right;">{r['p']}</td>
        <td style="padding:14px 8px; text-align:right; color:#70757a;">{r.get('rsi', '-')}</td>
        <td style="padding:14px 8px; text-align:right; color:#70757a;">{r.get('adx', '-')}</td>
        <td style="padding:14px 8px; text-align:right; color:{macd_color};">{macd_dir}</td>
        <td style="padding:14px 8px; text-align:right;">
            <span style="padding:4px 10px; border-radius:4px; background:{m_bg}; color:{m_color}; font-weight:600; font-size:12px;">{m}x</span>
        </td>
        <td style="padding:14px 8px; text-align:right; color:#202124; font-weight:500;">¥{r['rmb']:,.0f}</td>
    </tr>
    <tr style="border-bottom: 1px solid #f1f3f4;">
        <td colspan="7" style="padding:4px 8px 12px 16px; font-size:11px; color:#9aa0a6;">
            因子: {factor_text}
            {f'<br>信号: {sig_text}' if sig_text else ''}
        </td>
    </tr>"""

    # --- 美债变化着色 ---
    tnx_chg_color = "#c5221f" if us10y_chg > 0 else "#137333"
    tnx_chg_sign = "+" if us10y_chg > 0 else ""

    html = f"""
    <div style="font-family:'Roboto',Arial,sans-serif; max-width:750px; margin:auto; border:1px solid #dadce0; border-radius:8px; overflow:hidden; background:#fff;">
        <div style="padding:20px 24px; border-bottom:1px solid #dadce0;">
            <span style="font-size:22px; color:#5f6368;">Google</span><span style="font-size:22px; color:#5f6368; font-weight:400;"> Finance</span>
            <span style="background:#e8f0fe; color:#1a73e8; padding:2px 8px; border-radius:12px; font-size:10px; margin-left:10px; font-weight:600;">SENTINEL PRO 6.0</span>
        </div>
        <div style="padding:24px;">
            <table width="100%" style="margin-bottom:24px;">
                <tr>
                    <td style="border:1px solid #dadce0; border-radius:8px; padding:14px; width:30%;">
                        <div style="color:#70757a; font-size:10px; margin-bottom:4px; text-transform:uppercase;">Market VIX</div>
                        <div style="font-size:24px; color:{'#c5221f' if vix > 25 else '#202124'};">{vix:.1f}</div>
                    </td>
                    <td width="3%"></td>
                    <td style="border:1px solid #dadce0; border-radius:8px; padding:14px; width:30%;">
                        <div style="color:#70757a; font-size:10px; margin-bottom:4px; text-transform:uppercase;">US 10Y Yield</div>
                        <div style="font-size:24px; color:#202124;">{us10y:.2f}%</div>
                        <div style="font-size:11px; color:{tnx_chg_color};">{tnx_chg_sign}{us10y_chg:.1f}% 周变化</div>
                    </td>
                    <td width="3%"></td>
                    <td style="border:1px solid #dadce0; border-radius:8px; padding:14px; width:30%;">
                        <div style="color:#70757a; font-size:10px; margin-bottom:4px; text-transform:uppercase;">USD Index (DXY)</div>
                        <div style="font-size:24px; color:#202124;">{dxy:.1f}</div>
                        <div style="font-size:11px; color:#70757a;">{'↑ 上升通道' if macro_ctx.get('dxy_trending_up') else '→ 中性'}</div>
                    </td>
                </tr>
            </table>
            <div style="background:#e8f0fe; border-radius:8px; padding:14px; margin-bottom:24px; text-align:center;">
                <span style="color:#70757a; font-size:11px; text-transform:uppercase;">Daily Total Budget</span>
                <div style="font-size:28px; color:#1a73e8; font-weight:500;">¥ {total_rmb:,.2f}</div>
            </div>
            <table width="100%" style="border-collapse:collapse; margin-bottom:30px; font-size:13px;">
                <thead>
                    <tr style="border-bottom: 2px solid #dadce0; color: #70757a; text-transform: uppercase; font-size:11px;">
                        <th align="left" style="padding:8px;">Asset</th>
                        <th align="right" style="padding:8px;">Price</th>
                        <th align="right" style="padding:8px;">RSI</th>
                        <th align="right" style="padding:8px;">ADX</th>
                        <th align="right" style="padding:8px;">MACD</th>
                        <th align="right" style="padding:8px;">Mult.</th>
                        <th align="right" style="padding:8px;">Amount</th>
                    </tr>
                </thead>
                <tbody>{rows_html}</tbody>
            </table>
            <div style="background:#f8f9fa; border-radius:8px; padding:24px; border:1px solid #eee;">
                <div style="font-size:15px; color:#202124; font-weight:500; margin-bottom:12px;">
                    🛡️ 首席风控官建议 (智谱 AI · CRO)
                </div>
                <ul style="margin:0; padding-left:20px; font-size:14px; color:#3c4043; line-height:1.8;">
                    {ai_advice if ai_advice else '<li>风控引擎同步中，请先参考量化权重执行。</li>'}
                </ul>
            </div>
        </div>
        <div style="background:#f1f3f4; padding:12px 24px; text-align:center; color:#9aa0a6; font-size:10px;">
            Sentinel Pro 6.0 (Multi-Factor Enhanced) · {datetime.now().strftime('%Y-%m-%d %H:%M')}
        </div>
    </div>"""

    msg = MIMEMultipart()
    msg['Subject'] = Header(title, 'utf-8')
    msg['From'] = formataddr((str(Header('Sentinel Pro', 'utf-8')), mail_user))
    msg['To'] = receiver
    msg.attach(MIMEText(html, 'html', 'utf-8'))

    try:
        with smtplib.SMTP("smtp.qq.com", 587, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(mail_user, mail_pass)
            smtp.sendmail(mail_user, [receiver], msg.as_string())
            print("✅ 投资决策报告已成功发送至邮箱")
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")


def save_log(results: list):
    """
    将本次决策结果追加保存到 CSV 日志文件。
    包含新增字段：ADX、MACD方向、因子权重。
    """
    log_file = "global_investment_log.csv"
    try:
        records = []
        for r in results:
            records.append({
                "日期": datetime.now().strftime("%Y-%m-%d"),
                "name": r["name"],
                "p": r["p"],
                "rsi": r.get("rsi", ""),
                "adx": r.get("adx", ""),
                "macd_hist": r.get("macd_hist", ""),
                "hist_shrinking": r.get("hist_shrinking", ""),
                "m": r["m"],
                "rmb": r["rmb"],
                "stop_loss": r.get("stop_loss", ""),
                "factors": json.dumps(r.get("factors", {}), ensure_ascii=False),
                "signals": "; ".join(r.get("signals", [])),
            })
        df = pd.DataFrame(records)
        df.to_csv(log_file, mode='a', index=False,
                  header=not os.path.exists(log_file),
                  encoding='utf-8-sig')
        print(f"📝 日志已保存至 {log_file}")
    except Exception as e:
        print(f"⚠️ 日志保存失败: {e}")


# ---------------------------------------------------------------------------
#  主引擎
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  Sentinel Pro 6.0 — 多因子智能定投决策引擎")
    print(f"  运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # --- 1. 加载资产配置 ---
    if not os.path.exists("assets.json"):
        print("❌ 错误：找不到 assets.json 文件")
        return

    with open("assets.json", 'r', encoding='utf-8') as f:
        assets = json.load(f)

    print(f"\n📋 已加载 {len(assets)} 个资产")

    # --- 2. 采集宏观上下文 ---
    print("\n🌍 Layer 1: 采集宏观上下文...")
    macro_ctx = fetch_macro_context()
    print(f"   VIX={macro_ctx['vix']:.1f} | US10Y={macro_ctx['us10y']:.2f}% "
          f"(周变化:{macro_ctx['us10y_chg_pct']:+.1f}%) | "
          f"DXY={macro_ctx['dxy']:.1f} "
          f"{'↑趋势' if macro_ctx['dxy_trending_up'] else '→中性'}")

    # --- 3. 计算资产相关性矩阵 ---
    print("\n📊 Layer 3a: 计算相关性矩阵...")
    corr_matrix = calculate_correlation_matrix(assets)
    # 打印高相关资产对
    names = list(assets.keys())
    for i in range(len(names)):
        for j in range(i+1, len(names)):
            try:
                cv = float(corr_matrix.loc[names[i], names[j]])
                if cv > 0.7:
                    print(f"   {names[i]} ↔ {names[j]}: corr={cv:.2f}"
                          f"{' ⚠️高相关' if cv > 0.85 else ''}")
            except (KeyError, ValueError):
                pass

    # --- 4. 逐资产分析 ---
    print("\n🔬 Layer 2+3: 逐资产技术分析 & 倍率计算...")
    results = []
    total_all = 0

    for name, info in assets.items():
        try:
            data = yf.download(info['ticker'], period="2y", progress=False)
            if data.empty:
                print(f"   ⏭️ {name}: 无数据，跳过")
                continue

            # 提取 OHLC 数据 (兼容 MultiIndex 和单层列)
            for col in ['Close', 'High', 'Low']:
                if isinstance(data[col], pd.DataFrame):
                    data[col] = data[col].iloc[:, 0]

            close = data['Close']
            high = data['High']
            low = data['Low']
            curr_p = float(close.iloc[-1])

            # 4a. 计算全部技术指标
            rsi_val = calculate_rsi(close)
            adx_data = calculate_adx(high, low, close)
            macd_data = calculate_macd(close)
            atr_data = calculate_atr(high, low, close)

            indicators = {
                "rsi": rsi_val,
                "adx": adx_data,
                "macd": macd_data,
                "atr": atr_data,
            }

            # 4b. 综合计算倍率
            result = compute_multiplier(
                curr_p, close, macro_ctx, indicators,
                asset_currency=info.get("currency", "USD")
            )

            m = result["m"]
            rmb_amt = round(info['base_amount'] * m, 2)

            entry = {
                "name": name,
                "p": round(curr_p, 2),
                "rsi": rsi_val,
                "adx": adx_data.get("adx", 20),
                "plus_di": adx_data.get("plus_di", 25),
                "minus_di": adx_data.get("minus_di", 25),
                "macd_hist": macd_data.get("histogram", 0),
                "hist_shrinking": macd_data.get("hist_shrinking", False),
                "atr": atr_data.get("atr", 0),
                "atr_ratio": atr_data.get("atr_ratio", 1.0),
                "m": m,
                "rmb": rmb_amt,
                "stop_loss": result.get("stop_loss", 0),
                "signals": result.get("signals", []),
                "factors": result.get("factors", {}),
            }

            results.append(entry)
            total_all += rmb_amt

            # 打印摘要
            print(f"   ✅ {name}: p={curr_p:.2f} RSI={rsi_val} "
                  f"ADX={adx_data['adx']} MACD={'↑' if macd_data['hist_shrinking'] else '↓'} "
                  f"ATR_ratio={atr_data['atr_ratio']:.2f} → m={m}x ¥{rmb_amt:,.0f}")
            for sig in result.get("signals", []):
                print(f"      {sig}")

        except Exception as e:
            print(f"   ❌ Skip: {name} - {e}")

    if not results:
        print("\n⚠️ 无有效数据，流程终止。")
        return

    # --- 5. 相关性熔断 ---
    print("\n🔗 Layer 3b: 相关性风控检查...")
    results = apply_risk_caps(results, corr_matrix, assets)

    # 重新计算总额
    total_all = sum(r["rmb"] for r in results)
    print(f"\n💰 日投总额: ¥{total_all:,.2f}")

    # --- 6. AI 决策审核 ---
    print("\n🤖 Layer 4: AI 风控审核...")
    ai_res = get_ai_advice(macro_ctx, round(total_all, 2), results)

    # --- 7. 报告 & 日志 ---
    print("\n📧 Layer 5: 生成报告...")
    send_report(
        f"Strategic Intelligence: {datetime.now().strftime('%m/%d')} 决策日报",
        total_all, results, macro_ctx, ai_res
    )
    save_log(results)

    print("\n" + "=" * 60)
    print("  ✅ Sentinel Pro 6.0 流程完成")
    print("=" * 60)


if __name__ == "__main__":
    main()