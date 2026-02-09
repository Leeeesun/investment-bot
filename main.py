import yfinance as yf
import pandas as pd
import os
import json
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
from datetime import datetime

# --- 1. 基础工具函数 ---
def calculate_rsi(prices, period=14):
    """计算 RSI 相对强弱指数"""
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def get_market_context():
    """获取 VIX 恐慌指数与实时汇率"""
    context = {"VIX": 18, "rates": {"USD": 7.25, "JPY": 0.048, "EUR": 7.8, "HKD": 0.93, "CNY": 1.0}}
    try:
        # 抓取 VIX
        vix_data = yf.download("^VIX", period="5d", progress=False)
        if not vix_data.empty:
            v_val = vix_data['Close'].iloc[:, 0] if isinstance(vix_data['Close'], pd.DataFrame) else vix_data['Close']
            context["VIX"] = float(v_val.dropna().iloc[-1])
        
        # 抓取汇率
        tickers = {"USD": "USDCNY=X", "JPY": "JPYCNY=X", "EUR": "EURCNY=X", "HKD": "HKDCNY=X"}
        for curr, t in tickers.items():
            rate_data = yf.download(t, period="5d", progress=False)
            if not rate_data.empty:
                r_val = rate_data['Close'].iloc[:, 0] if isinstance(rate_data['Close'], pd.DataFrame) else rate_data['Close']
                context["rates"][curr] = float(r_val.dropna().iloc[-1])
    except: pass
    return context

# --- 2. 核心计算引擎 (3.0 终极版) ---
def calculate_ultimate_score(name, info, context):
    try:
        data = yf.download(info['ticker'], period="2y", progress=False)
        if data.empty: return None
        
        close = data['Close'].iloc[:, 0] if isinstance(data['Close'], pd.DataFrame) else data['Close']
        curr_p = float(close.iloc[-1])
        
        # A. 均线维度 (MA) - 基础仓位
        ma = [close.rolling(w).mean().iloc[-1] for w in [20, 60, 120, 250]]
        score_ma = 0.6
        if curr_p < ma[0]: score_ma += 0.2
        if curr_p < ma[1]: score_ma += 0.3
        if curr_p < ma[2]: score_ma += 0.4
        if curr_p < ma[3]: score_ma += 0.5
        
        # B. 动能维度 (Streak)
        diff = close.diff()
        streak = 0
        for i in range(len(diff)-1, 0, -1):
            if diff.iloc[i] < 0: streak -= 1
            else: break
        score_streak = 0.3 if streak <= -5 else (0.1 if streak <= -3 else (-0.1 if streak >= 3 else 0))
        
        # C. 力量维度 (RSI)
        rsi_val = calculate_rsi(close)
        score_rsi = 0
        if rsi_val < 30: score_rsi = 0.3
        elif rsi_val < 40: score_rsi = 0.1
        elif rsi_val > 70: score_rsi = -0.3
        elif rsi_val > 60: score_rsi = -0.1
        
        # D. 情绪维度 (VIX)
        vix = context["VIX"]
        score_vix = 0.5 if vix > 35 else (0.2 if vix > 25 else (-0.1 if vix < 15 else 0))
        
        # 综合计算倍数
        final_multiplier = round(max(0.4, min(score_ma + score_streak + score_rsi + score_vix, 3.5)), 2)
        rmb_amt = info['base_amount'] * final_multiplier * context['rates'].get(info['currency'], 1.0)
        
        return {
            "name": name, "p": round(curr_p, 2), "m": final_multiplier, 
            "rmb": round(rmb_amt, 2), "rsi": round(rsi_val, 1), "streak": streak
        }
    except: return None

# --- 3. 视觉报告系统 ---
def send_ultimate_report(total_rmb, results, context):
    mail_user = os.getenv('EMAIL_USER')
    mail_pass = os.getenv('EMAIL_PASS')
    receiver = os.getenv('EMAIL_RECEIVER')
    if not all([mail_user, mail_pass, receiver]): return

    vix = context["VIX"]
    vix_color = "#e74c3c" if vix > 25 else "#27ae60"
    
    rows = ""
    for r in results:
        # RSI 状态提示
        rsi_tag = "<span style='color:#e74c3c;'>超卖</span>" if r['rsi'] < 35 else ("<span style='color:#3498db;'>超买</span>" if r['rsi'] > 65 else "适中")
        rows += f"""
        <tr style="border-bottom: 1px solid #eee; font-size: 14px;">
            <td style="padding: 12px;"><b>{r['name']}</b></td>
            <td style="padding: 12px; text-align:center;">{r['p']}</td>
            <td style="padding: 12px; text-align:center;">{r['rsi']} ({rsi_tag})</td>
            <td style="padding: 12px; text-align:center; color:#e74c3c; font-weight:bold;">{r['m']}x</td>
            <td style="padding: 12px; text-align:right; font-weight:bold;">¥{r['rmb']:,}</td>
        </tr>
        """

    html = f"""
    <div style="font-family:sans-serif; max-width:600px; margin:auto; border:1px solid #ddd; border-radius:12px; overflow:hidden; box-shadow:0 4px 15px rgba(0,0,0,0.1);">
        <div style="background:#2c3e50; color:white; padding:25px;">
            <h2 style="margin:0; font-size:22px; letter-spacing:1px;">全球资产量化定投报告 3.0</h2>
            <div style="margin-top:10px; font-size:14px; opacity:0.9;">
                市场恐慌指数 VIX: <b style="color:{vix_color};">{vix}</b> | 汇率 USD/CNY: {context['rates']['USD']:.2f}
            </div>
        </div>
        <div style="padding:25px; background:#fff;">
            <div style="background:#fff5f5; border-left:5px solid #e74c3c; padding:20px; margin-bottom:25px; border-radius:4px;">
                <span style="font-size:14px; color:#95a5a6; text-transform:uppercase;">本期合计出资额 (RMB)</span><br>
                <span style="font-size:32px; color:#e74c3c; font-weight:bold;">¥ {total_rmb:,.2f}</span>
            </div>
            <table width="100%" style="border-collapse:collapse;">
                <tr style="background:#f8f9fa; color:#7f8c8d; font-size:12px;">
                    <th style="padding:10px; text-align:left;">资产名称</th>
                    <th style="padding:10px;">最新价格</th>
                    <th style="padding:10px;">RSI力度</th>
                    <th style="padding:10px;">综合倍数</th>
                    <th style="padding:10px; text-align:right;">建议金额</th>
                </tr>
                {rows}
            </table>
        </div>
        <div style="background:#f9f9f9; padding:15px; text-align:center; font-size:12px; color:#bdc3c7;">
            策略逻辑：MA趋势 + VIX情绪 + Streak动能 + RSI强弱 | {datetime.now().strftime('%Y-%m-%d %H:%M')}
        </div>
    </div>
    """
    
    msg = MIMEMultipart()
    title = f"量化定投决策日报 - {datetime.now().strftime('%m/%d')}"
    msg['Subject'] = Header(title, 'utf-8')
    msg['From'] = formataddr((str(Header('全球资产终端', 'utf-8')), mail_user))
    msg['To'] = receiver
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    
    try:
        with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=15) as smtp:
            smtp.login(mail_user, mail_pass)
            smtp.sendmail(mail_user, [receiver], msg.as_string())
        print("✉️ 终极版报告已送达。")
    except Exception as e: print(f"❌ 邮件发送异常: {e}")

# --- 4. 运行入口 ---
def main():
    if not os.path.exists("assets.json"): return
    with open("assets.json", 'r', encoding='utf-8') as f:
        assets = json.load(f)
    
    context = get_market_context()
    final_results, total_all = [], 0
    
    for name, info in assets.items():
        res = calculate_ultimate_score(name, info, context)
        if res:
            final_results.append(res)
            total_all += res['rmb']
            
    if final_results:
        send_ultimate_report(total_all, final_results, context)
        # 存档 CSV
        df = pd.DataFrame(final_results)
        df['日期'] = datetime.now().strftime("%Y-%m-%d")
        log = "global_investment_log.csv"
        df.to_csv(log, mode='a', index=False, header=not os.path.exists(log), encoding='utf-8-sig')

if __name__ == "__main__":
    main()