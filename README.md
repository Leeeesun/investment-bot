# Sentinel Pro 6.0

![Version](https://img.shields.io/badge/Sentinel_Pro-6.0-7c3aed?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.12+-3776ab?style=for-the-badge&logo=python&logoColor=white)
![Status](https://img.shields.io/badge/Status-Active-10b981?style=for-the-badge)

多因子智能定投决策系统 — 融合量化分析、宏观研判与 AI 风控于一体的全球资产配置引擎。

## 架构概览

```
┌─────────────────────────────────────────────────────┐
│  Layer 1   宏观上下文采集 (VIX / US10Y / DXY)        │
├─────────────────────────────────────────────────────┤
│  Layer 2   多因子技术指标 (RSI / ADX / MACD / ATR)   │
├─────────────────────────────────────────────────────┤
│  Layer 3   风控 & 资金管理                            │
│            ├─ 相关性矩阵 (Pearson)                    │
│            ├─ 相关性熔断 (corr > 0.85)                │
│            └─ ATR 动态头寸控制                        │
├─────────────────────────────────────────────────────┤
│  Layer 4   AI 决策审核 (智谱 GLM-4 · CRO 角色)       │
├─────────────────────────────────────────────────────┤
│  Layer 5   报告 & 日志                               │
│            ├─ HTML 邮件 (响应式 / 中文表头)            │
│            ├─ 180 天内联回测 (胜率 / 年化 / 最大回撤)   │
│            └─ 资金曲线图表附件 (matplotlib)            │
├─────────────────────────────────────────────────────┤
│  Layer 6   GitHub Pages 看板                         │
│            └─ Tailwind CSS 暗色主题 Dashboard         │
└─────────────────────────────────────────────────────┘
```

## 核心特性

### 📊 多因子量化引擎

倍率 `m` 由百分比权重系统动态计算，而非简单加减分：

| 因子 | 权重占比 | 逻辑 |
|:---|:---|:---|
| MA 偏离度 | 10%–25% | MA20 / MA60 / MA120 / MA250 四级偏离比例 |
| RSI | 15%–20% | 超卖 (<30) 加仓，超买 (>65) 减仓 |
| ADX 趋势过滤 | 门控 | ADX>25 且下行趋势 → 禁止加仓 |
| MACD 门控 | 衰减 50% | 价格低于 MA20 但动量未衰减 → 信号减半 |
| ATR 动态头寸 | 自适应 | ATR ratio>1.5 → 按波动比例调整仓位 |
| 宏观因子 | 修正 | 美债飙升/美元走强 → 下调非美资产倍率 |

最终倍率约束在 `[0.3, 3.5]` 之间。

### 🌍 宏观三维度

- **VIX** — 恐慌指数，>25 触发加仓信号
- **US 10Y** — 美债收益率，周涨幅急升 → 宏观"否决"
- **DXY** — 美元指数，上升通道 → 非美资产下调

### 🛡️ AI 风控官 (CRO)

接入智谱 GLM-4-Flash，角色设定为首席风控官：

- 分析 RSI/MACD 指标背离，判断"多头陷阱 (Bull Trap)"风险
- 审核量化倍率合理性，给出具体调整建议
- 检查跨资产联动风险和仓位集中度
- **CRO vs 量化偏差 >0.5 → 邮件中红色警报标注**

### 📈 内联历史回测

每次运行自动对所有资产进行 **180 天策略回测**：

- 策略胜率 (Win Rate) — 买入后至今盈利的交易占比
- 年化收益率 — 按 252 个交易日年化
- 最大回撤 — **DD > 15% → 倍率自动 ×0.8 + 黄色警告**
- 资金曲线 PNG 附件随邮件发送

### 🌐 GitHub Pages 看板

每次 CI 运行后自动部署到 `gh-pages` 分支：

- Tailwind CSS 暗色主题 + 磨砂玻璃效果
- 响应式卡片布局（手机/平板/桌面自适应）
- `noindex, nofollow` 防搜索引擎索引
- 不泄露 API Key / 邮箱 / 具体金额

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

| 变量名 | 说明 |
|:---|:---|
| `ZHIPU_API_KEY` | 智谱 AI API Key |
| `EMAIL_USER` | 发信邮箱 (QQ 邮箱 SMTP) |
| `EMAIL_PASS` | 邮箱授权码 |
| `EMAIL_RECEIVER` | 报告接收邮箱 |

### 3. 配置资产 (`assets.json`)

```json
{
    "标普500": { "ticker": "^GSPC", "base_amount": 100, "currency": "USD" },
    "纳斯达克": { "ticker": "^IXIC", "base_amount": 50, "currency": "USD" },
    "黄金":    { "ticker": "GC=F",  "base_amount": 10,  "currency": "USD" }
}
```

### 4. 运行

```bash
# 日常决策
python main.py

# 独立回测 (2年 QQQ/SPY)
python backtest.py
```

## 文件结构

```
investment-bot/
├── main.py                     # 核心引擎 (6 层架构)
├── backtest.py                 # 独立回测模块
├── assets.json                 # 资产配置
├── requirements.txt            # Python 依赖
├── global_investment_log.csv   # 决策历史日志
├── output/
│   └── index.html              # GitHub Pages 看板
├── backtest_equity_chart.png   # 回测资金曲线图
└── .github/workflows/
    └── auto_invest.yml         # CI: 定时运行 + gh-pages 部署
```

## CI/CD

GitHub Actions 每日北京时间 **09:45** 自动运行：

1. 拉取全球市场数据
2. 多因子分析 + 回测
3. AI 风控审核
4. 发送邮件报告（含图表附件）
5. 部署 Dashboard 到 gh-pages
6. 提交日志到仓库

支持 `workflow_dispatch` 手动触发。

---

> [!NOTE]
> 投资有风险，决策需谨慎。本项目仅作为量化技术研究与自动化工具，不构成任何投资建议。