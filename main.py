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

# --- 1. 基础工具逻辑 ---
def calculate_rsi(prices, period=14):
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def get_market_context():
    context = {"VIX": 18, "rates": {"USD": 7.25, "JPY": 0.048, "EUR": 7.8, "HKD": 0.93, "CNY": 1.0}}
    try:
        vix_data = yf.download("^VIX", period="5d", progress=False)
        if not vix_data.empty:
            v_close = vix_data['Close'].iloc[:, 0] if isinstance(vix_data['Close'], pd.DataFrame) else vix_data['Close']
            context["VIX"] = float(v_close.dropna().iloc[-1])
        
        tickers = {"USD": "USDCNY=X", "JPY": "JPYCNY=X", "EUR": "EURCNY=X", "HKD": "HKDCNY=X"}
        for curr, t in tickers.items():
            rate_data = yf.download(t, period="5d", progress=False)
            if not rate_data.empty:
                r_close = rate_data['Close'].iloc[:, 0] if isinstance(rate_data['Close'], pd.DataFrame) else rate_data['Close']
                context["rates"][curr] = float(r_close.dropna().iloc[-1])
    except: pass
    return context

# --- 2. 邮件发送逻辑 (专业投研风格) ---
def send_alert_email(title, total_rmb, results, vix, alert_msg):
    mail_user = os.getenv('EMAIL_USER')
    mail_pass = os.getenv('EMAIL_PASS')
    receiver = os.getenv('EMAIL_RECEIVER')
    if not all([mail_user, mail_pass, receiver]): return

    vix_color = "#e74c3c" if vix > 25 else "#27ae60"
    rows = ""
    for r in results:
        m_color = "#e74c3c" if r['m'] >= 1.3 else ("#3498db" if r['m'] <= 0.6 else "#2c3e50")
        rows += f"""
        <tr style="border-bottom: 1px solid #eee; font-size: 14px;">
            <td style="padding:12px;"><b>{r['name']}</b></td>
            <td style="padding:12px; text-align:center;">{r['p']}</td>
            <td style="padding:12px; text-align:center;">{r['rsi']}</td>
            <td style="padding:12px; text-align:center; color:{m_color}; font-weight:bold;">{r['m']}x</td>
            <td style="padding:12px; text-align:right; font-weight:bold;">¥{r['rmb']:,}</td>
        </tr>
        """

    html = f"""
    <div style="font-family:sans-serif; max-width:600px; margin:auto; border:1px solid #ddd; border-radius:12px; overflow:hidden;">
        <div style="background:#2c3e50; color:white; padding:20px;">
            <h2 style="margin:0; font-size:20px;">{title}</h2>
            <p style="margin:5px 0 0; opacity:0.8;">关键预警：{alert_msg} | VIX: <b style="color:{vix_color};">{vix}</b></p>
        </div>
        <div style="padding:20px;">
            <div style="background:#fff5f5; border-left:5px solid #e74c3c; padding:15px; margin-bottom:20px;">
                <span style="font-size:13px; color:#7f8c8d;">当日建议投入总额 (RMB)</span><br>
                <span style="font-size:28px; color:#e74c3c; font-weight:bold;">¥ {total_rmb:,.2f}</span>
            </div>
            <table width="100%" style="border-collapse:collapse;">
                <tr style="background:#f8f9fa; color:#7f8c8d; font-size:12px;">
                    <th style="padding:10px; text-align:left;">资产</th><th style="padding:10px;">现价</th>
                    <th style="padding:10px;">RSI</th><th style="padding:10px;">倍数</th><th style="padding:10px; text-align:right;">金额</th>
                </tr>
                {rows}
            </table>
        </div>
        <div style="background:#f9f9f9; padding:12px; text-align:center; font-size:11px; color:#bdc3c7;">
            哨兵系统已根据今日行情（{datetime.now().strftime('%Y-%m-%d %H:%M')}）自动触发
        </div>
    </div>
    """
    
    msg = MIMEMultipart()
    msg['Subject'] = Header(title, 'utf-8')
    msg['From'] = formataddr((str(Header('全球资产哨兵', 'utf-8')), mail_user))
    msg['To'] = receiver
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    
    try:
        with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=15) as smtp:
            smtp.login(mail_user, mail_pass)
            smtp.sendmail(mail_user, [receiver], msg.as_string())
        print("✉️ 预警邮件已发送")
    except Exception as e: print(f"邮件失败: {e}")

# --- 3. 哨兵核心逻辑 ---
def main():
    with open("assets.json", 'r', encoding='utf-8') as f:
        assets = json.load(f)
    
    ctx = get_market_context()
    results, total_rmb, alert_assets = [], 0, []
    
    for name, info in assets.items():
        try:
            data = yf.download(info['ticker'], period="2y", progress=False)
            close = data['Close'].iloc[:, 0] if isinstance(data['Close'], pd.DataFrame) else data['Close']
            curr_p = float(close.iloc[-1])
            
            # 模型评分
            ma = [close.rolling(w).mean().iloc[-1] for w in [20, 60, 120, 250]]
            m = 0.6
            if curr_p < ma[0]: m += 0.2
            if curr_p < ma[1]: m += 0.3
            if curr_p < ma[2]: m += 0.4
            if curr_p < ma[3]: m += 0.5
            
            rsi = calculate_rsi(close)
            if rsi < 35: m += 0.3
            if rsi > 65: m -= 0.3
            if ctx['VIX'] > 25: m += 0.2
            
            m = round(max(0.4, min(m, 3.5)), 2)
            rmb = round(info['base_amount'] * m * ctx['rates'].get(info['currency'], 1.0), 2)
            
            item = {"name": name, "p": round(curr_p, 2), "rsi": round(rsi, 1), "m": m, "rmb": rmb}
            results.append(item)
            total_rmb += rmb
            
            # 【哨兵触发阈值】
            if m >= 1.3 or rsi <= 35: alert_assets.append(f"{name}(买入信号)")
            if m <= 0.6 or rsi >= 65: alert_assets.append(f"{name}(高位避险)")
        except: continue

    if results:
        # 1. 记录数据 (无论是否有信号)
        df = pd.DataFrame(results); df['日期'] = datetime.now().strftime("%Y-%m-%d")
        log = "global_investment_log.csv"
        df.to_csv(log, mode='a', index=False, header=not os.path.exists(log), encoding='utf-8-sig')
        
        # 2. 信号过滤：只有触发特定信号才发邮件
        if alert_assets:
            msg = "、".join(alert_assets)
            send_alert_email(f"交易信号预警：{msg}", total_rmb, results, round(ctx['VIX'], 1), msg)
        else:
            print("😴 今日行情平稳，哨兵继续值守，未发送邮件。")

if __name__ == "__main__":
    main()