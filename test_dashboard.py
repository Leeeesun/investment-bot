import sys
import os
# Add current dir to path
sys.path.append(os.getcwd())

from main import generate_dashboard
from datetime import datetime

# 模拟数据：测试纯文本标签和颜色
results = [
    {
        "name": "标普 500 (空头衰竭)",
        "p": 5088.3,
        "m": 1.5,
        "rsi": 32.5,
        "macd_hist": -0.5,
        "hist_shrinking": True,
        "backtest": {"win_rate": 65, "annualized_ret": 12.5, "max_drawdown_pct": -8.2},
        "signals": ["空头动能衰竭 (看多)", "RSI 超卖"]
    },
    {
        "name": "纳斯达克 (多头加速)",
        "p": 18235.1,
        "m": 1.8,
        "rsi": 55.2,
        "macd_hist": 1.2,
        "hist_shrinking": False,
        "backtest": {"win_rate": 72, "annualized_ret": 18.4, "max_drawdown_pct": -12.5},
        "signals": ["多头动能加速 (看多)"]
    },
    {
        "name": "黄金 (多头衰竭)",
        "p": 2050.5,
        "m": 0.8,
        "rsi": 68.0,
        "macd_hist": 0.4,
        "hist_shrinking": True,
        "backtest": {"win_rate": 60, "annualized_ret": 5.2, "max_drawdown_pct": -5.1},
        "signals": ["多头动能衰竭 (看空)", "RSI 偏高"]
    }
]

macro_ctx = {
    "vix": 22.5,
    "us10y": 4.25,
    "us10y_chg_pct": 1.2,
    "dxy": 104.2,
    "dxy_trending_up": True
}

ai_advice = """
<li>根据量化信号，标普 500 出现空头动能衰竭 (看多)，建议维持加仓。</li>
<li>纳斯达克多头动能仍在加速 (看多)，择机买入。</li>
"""

path = generate_dashboard(results, macro_ctx, ai_advice)
print(f"Test dashboard generated at: {path}")
