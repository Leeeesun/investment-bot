"""
Sentinel Pro 6.0 — 定投策略回测模块
=====================================

功能:
  - 利用过去 2 年历史数据，在每个交易日模拟 main.py 的多因子定投策略
  - 对 QQQ 和 SPY 分别跑回测
  - 输出: 资金曲线、最大回撤 (Max Drawdown)、夏普比率 (Sharpe Ratio)

运行方式:
  python backtest.py

设计说明:
  本策略是"定投型"（DCA），不是传统的买/卖信号型。
  因此不使用 Backtesting.py 框架，而是自建模拟器:
    - 每个交易日根据指标计算 multiplier m
    - 投入 base_amount * m 的资金买入对应份额
    - 跟踪累计持仓市值 + 剩余现金 = 总资产
    - 基于总资产序列计算回撤和夏普比率
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime

# ---------------------------------------------------------------------------
#  从 main.py 导入指标函数和工具函数
# ---------------------------------------------------------------------------
from main import (
    _to_series,
    _safe_scalar,
    calculate_rsi,
    calculate_adx,
    calculate_macd,
    calculate_atr,
)


# ---------------------------------------------------------------------------
#  回测版 compute_multiplier (简化: 不含宏观因子，因历史宏观数据拉取成本高)
#  核心逻辑与 main.py 一致: MA偏离 + RSI + ADX过滤 + MACD门控 + ATR动态头寸
# ---------------------------------------------------------------------------

def bt_compute_multiplier(idx: int, close: pd.Series, high: pd.Series,
                          low: pd.Series, lookback: int = 250) -> dict:
    """
    给定当前位置 idx，用截至该日的历史数据计算 multiplier。

    参数:
      idx      - 当前日期在 Series 中的位置索引
      close    - 完整收盘价 Series
      high     - 完整最高价 Series
      low      - 完整最低价 Series
      lookback - 需要的最小历史长度 (默认 250 交易日)

    返回: {"m": float, "signals": list[str]}
    """
    # 截取到当日的历史窗口
    start = max(0, idx - lookback - 50)  # 多取 50 行给 rolling 预热
    c = close.iloc[start:idx + 1]
    h = high.iloc[start:idx + 1]
    l = low.iloc[start:idx + 1]

    curr_price = _safe_scalar(c.iloc[-1])
    signals = []

    # --- 技术指标 ---
    rsi = calculate_rsi(c)
    adx_data = calculate_adx(h, l, c)
    macd_data = calculate_macd(c)
    atr_data = calculate_atr(h, l, c)

    adx = adx_data.get("adx", 20)
    plus_di = adx_data.get("plus_di", 25)
    minus_di = adx_data.get("minus_di", 25)
    hist_shrinking = macd_data.get("hist_shrinking", False)
    atr_ratio = atr_data.get("atr_ratio", 1.0)
    atr_val = atr_data.get("atr", 0)
    atr_avg = atr_data.get("atr_avg", 0)

    base_m = 1.0
    weight = 0.0

    # (1) 均线偏离度 — 百分比制
    for w, mw in [(20, 0.10), (60, 0.15), (120, 0.20), (250, 0.25)]:
        if len(c) > w:
            ma_val = _safe_scalar(c.rolling(w).mean().iloc[-1])
            if not pd.isna(ma_val) and curr_price < ma_val:
                deviation = (ma_val - curr_price) / ma_val
                weight += mw * (1 + deviation)
            elif not pd.isna(ma_val) and curr_price > ma_val * 1.05:
                weight -= mw * 0.3

    # (2) RSI 信号
    if rsi < 30:
        weight += 0.20
    elif rsi < 35:
        weight += 0.15
    elif rsi > 70:
        weight -= 0.25
    elif rsi > 65:
        weight -= 0.15

    # (3) ADX 趋势过滤 — 强下行禁止加仓
    if adx > 25 and minus_di > plus_di:
        weight = min(weight, 0.0)

    # (4) MACD 门控
    if len(c) > 20:
        ma20_val = _safe_scalar(c.rolling(20).mean().iloc[-1])
        if not pd.isna(ma20_val) and curr_price < ma20_val and not hist_shrinking:
            if weight > 0:
                weight *= 0.5  # 动量未衰减，减半

    # (5) ATR 动态头寸
    if atr_ratio > 1.5 and atr_val > 0:
        m_adj = atr_avg / atr_val
        weight = weight * m_adj + (m_adj - 1)
    elif atr_ratio > 1.2:
        weight = weight * 0.9 - 0.1

    m = base_m + weight
    m = round(max(0.3, min(m, 3.5)), 2)

    return {"m": m, "signals": signals}


# ---------------------------------------------------------------------------
#  回测引擎
# ---------------------------------------------------------------------------

def run_backtest(ticker: str, base_amount: float = 100.0,
                 period: str = "2y", invest_freq: int = 5) -> dict:
    """
    对单个资产执行定投策略回测。

    参数:
      ticker      - Yahoo Finance 代码 (如 "QQQ", "SPY")
      base_amount - 每次定投基础金额 (美元)
      period      - 回测数据周期
      invest_freq - 每隔多少个交易日定投一次 (5 = 周定投)

    返回:
      {
        "ticker": str,
        "total_invested": float,    # 累计投入
        "final_value": float,       # 最终总资产
        "total_return_pct": float,  # 总回报率
        "max_drawdown_pct": float,  # 最大回撤 (%)
        "sharpe_ratio": float,      # 年化夏普比率
        "equity_curve": pd.Series,  # 日度资产曲线
        "trades": int,              # 交易次数
        "avg_multiplier": float,    # 平均倍率
      }
    """
    print(f"\n{'='*60}")
    print(f"  回测: {ticker} | 基础定投: ${base_amount} | 频率: 每 {invest_freq} 交易日")
    print(f"{'='*60}")

    # --- 拉取数据 ---
    data = yf.download(ticker, period=period, progress=False)
    if data.empty:
        print(f"[ERR] 无法获取 {ticker} 数据")
        return None

    close = _to_series(data['Close'])
    high = _to_series(data['High'])
    low = _to_series(data['Low'])

    # 需要至少 300 天数据 (250天均线 + 50天预热)
    warmup = 300
    if len(close) < warmup + 20:
        print(f"[ERR] {ticker} 数据不足 ({len(close)} 天)，需要至少 {warmup + 20} 天")
        return None

    # --- 模拟回测 ---
    total_shares = 0.0      # 累计持有份额
    total_invested = 0.0    # 累计投入资金
    trade_count = 0
    multipliers = []

    # 记录每日资产曲线
    dates = []
    equity_values = []

    start_idx = warmup  # 从第 warmup 天开始回测
    day_counter = 0

    for i in range(start_idx, len(close)):
        curr_price = _safe_scalar(close.iloc[i])
        date = close.index[i]

        # 每 invest_freq 天执行一次定投
        if day_counter % invest_freq == 0:
            result = bt_compute_multiplier(i, close, high, low)
            m = result["m"]
            invest_amount = base_amount * m

            shares_bought = invest_amount / curr_price
            total_shares += shares_bought
            total_invested += invest_amount
            trade_count += 1
            multipliers.append(m)

        day_counter += 1

        # 记录当日总资产 (持仓市值)
        portfolio_value = total_shares * curr_price
        dates.append(date)
        equity_values.append(portfolio_value)

    # --- 构建资金曲线 ---
    equity_curve = pd.Series(equity_values, index=dates, name=f"{ticker}_equity")

    # --- 计算绩效指标 ---
    final_value = equity_values[-1] if equity_values else 0
    total_return_pct = ((final_value - total_invested) / total_invested * 100
                        if total_invested > 0 else 0)

    # 最大回撤: 从峰值到谷底的最大跌幅
    running_max = equity_curve.expanding().max()
    drawdown = (equity_curve - running_max) / running_max
    max_drawdown_pct = round(drawdown.min() * 100, 2)

    # 夏普比率: (年化收益 - 无风险利率) / 年化波动率
    # 使用日收益率计算
    daily_returns = equity_curve.pct_change().dropna()
    if len(daily_returns) > 1 and daily_returns.std() > 0:
        annualized_return = daily_returns.mean() * 252
        annualized_vol = daily_returns.std() * np.sqrt(252)
        risk_free_rate = 0.04  # 假设无风险利率 4% (参考当前美债)
        sharpe_ratio = round((annualized_return - risk_free_rate) / annualized_vol, 2)
    else:
        sharpe_ratio = 0.0

    avg_m = round(np.mean(multipliers), 2) if multipliers else 1.0

    # --- 输出结果 ---
    print(f"\n[RESULT] 回测结果: {ticker}")
    print(f"   回测区间: {dates[0].strftime('%Y-%m-%d')} -> {dates[-1].strftime('%Y-%m-%d')}"
          f" ({len(dates)} 交易日)")
    print(f"   交易次数: {trade_count} 次")
    print(f"   平均倍率: {avg_m}x")
    print(f"   累计投入: ${total_invested:,.2f}")
    print(f"   最终市值: ${final_value:,.2f}")
    print(f"   总回报率: {total_return_pct:+.2f}%")
    print(f"   最大回撤: {max_drawdown_pct:.2f}%")
    print(f"   夏普比率: {sharpe_ratio}")

    return {
        "ticker": ticker,
        "total_invested": round(total_invested, 2),
        "final_value": round(final_value, 2),
        "total_return_pct": round(total_return_pct, 2),
        "max_drawdown_pct": max_drawdown_pct,
        "sharpe_ratio": sharpe_ratio,
        "equity_curve": equity_curve,
        "trades": trade_count,
        "avg_multiplier": avg_m,
    }


# ---------------------------------------------------------------------------
#  对比基准: 等额定投 (m=1.0 固定)
# ---------------------------------------------------------------------------

def run_benchmark(ticker: str, base_amount: float = 100.0,
                  period: str = "2y", invest_freq: int = 5) -> dict:
    """
    等额定投基准: 每次投入固定 base_amount，不做任何倍率调整。
    用于和策略回测对比，衡量多因子策略是否创造了超额收益。
    """
    data = yf.download(ticker, period=period, progress=False)
    if data.empty:
        return None

    close = _to_series(data['Close'])
    warmup = 300

    if len(close) < warmup + 20:
        return None

    total_shares = 0.0
    total_invested = 0.0
    dates = []
    equity_values = []
    day_counter = 0

    for i in range(warmup, len(close)):
        curr_price = _safe_scalar(close.iloc[i])
        date = close.index[i]

        if day_counter % invest_freq == 0:
            shares_bought = base_amount / curr_price
            total_shares += shares_bought
            total_invested += base_amount

        day_counter += 1
        dates.append(date)
        equity_values.append(total_shares * curr_price)

    equity_curve = pd.Series(equity_values, index=dates, name=f"{ticker}_benchmark")

    final_value = equity_values[-1] if equity_values else 0
    total_return_pct = ((final_value - total_invested) / total_invested * 100
                        if total_invested > 0 else 0)

    running_max = equity_curve.expanding().max()
    drawdown = (equity_curve - running_max) / running_max
    max_drawdown_pct = round(drawdown.min() * 100, 2)

    daily_returns = equity_curve.pct_change().dropna()
    if len(daily_returns) > 1 and daily_returns.std() > 0:
        annualized_return = daily_returns.mean() * 252
        annualized_vol = daily_returns.std() * np.sqrt(252)
        sharpe_ratio = round((annualized_return - 0.04) / annualized_vol, 2)
    else:
        sharpe_ratio = 0.0

    return {
        "ticker": ticker,
        "total_invested": round(total_invested, 2),
        "final_value": round(final_value, 2),
        "total_return_pct": round(total_return_pct, 2),
        "max_drawdown_pct": max_drawdown_pct,
        "sharpe_ratio": sharpe_ratio,
        "equity_curve": equity_curve,
    }


# ---------------------------------------------------------------------------
#  主函数
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  Sentinel Pro 6.0 - DCA Strategy Backtest")
    print(f"  运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    tickers = ["QQQ", "SPY"]
    base_amount = 100.0   # 每次基础定投 $100
    invest_freq = 5       # 每 5 个交易日投一次 (≈周定投)

    all_results = []

    for ticker in tickers:
        print(f"\n\n{'#'*60}")
        print(f"  正在回测: {ticker}")
        print(f"{'#'*60}")

        # 运行策略回测
        strategy = run_backtest(ticker, base_amount, period="2y",
                                invest_freq=invest_freq)
        # 运行等额定投基准
        benchmark = run_benchmark(ticker, base_amount, period="2y",
                                  invest_freq=invest_freq)

        if strategy and benchmark:
            all_results.append({
                "ticker": ticker,
                "strategy": strategy,
                "benchmark": benchmark,
            })

    # --- 汇总对比表 ---
    if all_results:
        print(f"\n\n{'='*72}")
        print("  [SUMMARY] 策略 vs 等额定投 -- 对比汇总")
        print(f"{'='*72}")
        print(f"{'资产':<8} | {'指标':<10} | {'策略':>12} | {'等额定投':>12} | {'超额':>10}")
        print("-" * 72)

        for r in all_results:
            s = r["strategy"]
            b = r["benchmark"]
            ticker = r["ticker"]

            # 总回报对比
            print(f"{ticker:<8} | {'总回报%':<10} | {s['total_return_pct']:>+11.2f}% "
                  f"| {b['total_return_pct']:>+11.2f}% "
                  f"| {s['total_return_pct'] - b['total_return_pct']:>+9.2f}%")

            # 最大回撤对比
            print(f"{'':8} | {'最大回撤%':<10} | {s['max_drawdown_pct']:>11.2f}% "
                  f"| {b['max_drawdown_pct']:>11.2f}% "
                  f"| {s['max_drawdown_pct'] - b['max_drawdown_pct']:>+9.2f}%")

            # 夏普比率对比
            print(f"{'':8} | {'夏普比率':<10} | {s['sharpe_ratio']:>12} "
                  f"| {b['sharpe_ratio']:>12} "
                  f"| {s['sharpe_ratio'] - b['sharpe_ratio']:>+10.2f}")

            # 累计投入对比
            print(f"{'':8} | {'累计投入':<10} | ${s['total_invested']:>10,.0f} "
                  f"| ${b['total_invested']:>10,.0f} "
                  f"| ${s['total_invested'] - b['total_invested']:>+9,.0f}")

            print("-" * 72)

        # --- 保存资金曲线到 CSV ---
        curves = {}
        for r in all_results:
            curves[f"{r['ticker']}_策略"] = r["strategy"]["equity_curve"]
            curves[f"{r['ticker']}_等额定投"] = r["benchmark"]["equity_curve"]

        curves_df = pd.DataFrame(curves)
        output_file = "backtest_equity_curves.csv"
        curves_df.to_csv(output_file, encoding="utf-8-sig")
        print(f"\n[SAVE] 资金曲线已保存至: {output_file}")

    print(f"\n{'='*60}")
    print("  [DONE] 回测完成")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
