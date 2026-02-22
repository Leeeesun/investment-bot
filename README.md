# Investment Bot (Sentinel Pro) 🚀

![Sentinel Pro](https://img.shields.io/badge/Sentinel-Pro%205.6-blue?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Active-success?style=for-the-badge)

一个专业的全球资产量化定投工具，结合了经典量化算法与大模型策略建议，为您提供金融级的投资决策支持。

## ✨ 核心特性

- **🌍 全球资产覆盖**：支持美股（S&P 500, Nasdaq）、日经、欧股、港股及黄金等多种资产的实时追踪。
- **📊 混合量化算法**：深度集成移动平均线（MA）、相对强弱指数（RSI）及恐慌指数（VIX）的动态加权模型。
- **🤖 AI 战略内参**：连接智谱 AI (GLM-4) 决策引擎，为每一份报告提供专业级的人工智能执行策略。
- **📧 高级视觉报告**：提供类 Google Finance 风格的 HTML 邮件报告，包含清晰的层级设计与执行指标。
- **📝 本地审计日志**：自动记录所有决策数据至 `global_investment_log.csv`，方便复盘与分析。

## 🧠 核心算法（Sentinel 量效模型）

量化乘数 `m`（Multiplier）决定了每日定投的最终金额。其计算逻辑如下：

1. **基础分**：初始权重为 `0.6x`。
2. **趋势博弈 (Trend-Following)**：
    - 价格低于 MA20: `+0.2`
    - 价格低于 MA60: `+0.3`
    - 价格低于 MA120: `+0.4`
    - 价格低于 MA250: `+0.5`
3. **情绪指标 (Vibrancy & Fear)**：
    - **RSI < 35**: 超卖区间，`+0.3`（增加投入）
    - **RSI > 65**: 超买区间，`-0.3`（减少投入）
    - **VIX > 25**: 市场波动放大，`+0.2`（抗波动加码）
4. **约束机制**：最终乘数严格约束在 `[0.4, 3.5]` 之间，确保极端行情下的稳健性。

## 🛠️ 环境部署

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

项目需要以下环境变量来启动 AI 引擎和邮件系统：

| 变量名 | 说明 |
| :--- | :--- |
| `ZHIPU_API_KEY` | 智谱 AI API Key (用于 GLM-4 战略决策) |
| `EMAIL_USER` | 发信邮箱账号 (支持 QQ 邮箱/SMTP) |
| `EMAIL_PASS` | 发信邮箱授权码 |
| `EMAIL_RECEIVER` | 报告接收地址 |

### 3. 配置资产列表 (`assets.json`)

在 `assets.json` 中定义您关注的资产及其基础定投金额：

```json
{
    "标普500": { "ticker": "^GSPC", "base_amount": 200, "currency": "USD" },
    "黄金": { "ticker": "GC=F", "base_amount": 100, "currency": "USD" }
}
```

## 🚀 启动运行

执行主引擎即可获取今日决策报告：

```bash
python main.py
```

## 📁 文件结构

- `main.py`: 核心量化引擎与执行逻辑。
- `assets.json`: 资产库配置文件。
- `requirements.txt`: Python 依赖清单。
- `global_investment_log.csv`: 决策执行的历史日志。

---
> [!NOTE]
> 投资有风险，决策需谨慎。本项目仅作为量化技术研究与自动化工具，不构成任何投资建议。