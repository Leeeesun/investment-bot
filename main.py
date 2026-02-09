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

# --- 2. 视觉报告系统 (排版优化版) ---
def send_alert_email(title, total_rmb, results, vix, alert_list):
    mail_user = os.getenv('EMAIL_USER')
    mail_pass = os.getenv('EMAIL_PASS')
    receiver = os.getenv('EMAIL_RECEIVER')
    if not all([mail_user, mail_pass, receiver]): return

    vix_color = "#e74c3c" if vix > 25 else "#27ae60"
    vix_desc = "市场恐慌" if vix > 25 else "情绪平稳"
    
    # 构造表格行
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
    
    # 构造预警建议（放到底部）
    alert_html = "".join([f"<li style='margin-bottom:5px;'>{a}</li>" for a in alert_list])

    html = f"""
    <div style="font-family:sans-serif; max-width:600px; margin:auto; border:1px solid #ddd; border-radius:12px; overflow:hidden; box-shadow:0 4px 12px rgba(0,0,0,0.1);">
        <div style="background:#2c3e50; color:white; padding:25px;">
            <h2 style="margin:0; font-size:22px; letter-spacing:1px;">全球资产量化监测日报</h2>
            <p style="margin:8px 0 0; opacity:0.8; font-size:14px;">
                恐慌指数 VIX: <b style="color:{vix_color};">{vix} ({vix_desc})</b> | 汇率 USD/CNY: {os.getenv('USD_RATE','7.25')}
            </p>
        </div>
        
        <div style="padding:25px; background:#fff;">
            <table width="100%" style="border-collapse:collapse; margin-bottom:25px;">
                <tr style="background:#f8f9fa; color:#7f8c8d; font-size:12px;">
                    <th style="padding:10px; text-align:left;">资产名称</th>
                    <th style="padding:10px;">最新价格</th>
                    <th style="padding:10px;">热度(RSI)</th>
                    <th style="padding:10px;">建议倍数</th>
                    <th style="padding:10px; text-align:right;">建议金额</th>
                </tr>
                {rows}
            </table>

            <div style="background:#fdf2f2; border-radius:8px; padding:20px; margin-bottom:25px; text-align:center;">
                <span style="font-size:14px; color:#666;">今日预计总投入 (RMB)</span><br>
                <span style="font-size:32px; color:#e74c3c; font-weight:bold;">¥ {total_rmb:,.2f}</span>
            </div>

            <div style="border-top:2px dashed #eee; padding-top:20px;">
                <h4 style="margin:0 0 10px 0; color:#2c3e50;">💡 哨兵决策建议：</h4>
                <ul style="margin:0; padding-left:20px; color:#e74c3c; font-size:15px; line-height:1.6; font-weight:bold;">
                    {alert_html}
                </ul>
            </div>
        </div>

        <div style="background:#f9f9f9; padding:15px; text-align:center; font-size:12px; color:#bdc3c7;">
            策略：均线趋势 + 情绪监控 | 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}
        </div>
    </div>
    """
    
    msg = MIMEMultipart()
    msg['Subject'] = Header(title, 'utf-8')
    msg['From'] = formataddr((str(Header('资产哨兵系统', 'utf-8')), mail_user))
    msg['To'] = receiver
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    
    try:
        with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=15) as smtp:
            smtp.login(mail_user, mail_pass)
            smtp.sendmail(mail_user, [receiver], msg.as_string())
        print("✉️ 优化版报告已送达")
    except Exception as e: print(f"发送失败: {e}")

# --- 3. 运行逻辑 ---
def main():
    if not os.path.exists("assets.json"): return
    with open("assets.json", 'r', encoding='utf-8') as f:
        assets = json.load(f)
    
    ctx = get_market_context()
    os.environ['USD_RATE'] = str(round(ctx['rates']['USD'], 2))
    results, total_rmb, alert_list = [], 0, []
    
    for name, info in assets.items():
        try:
            data = yf.download(info['ticker'], period="2y", progress=False)
            close = data['Close'].iloc[:, 0] if isinstance(data['Close'], pd.DataFrame) else data['Close']
            curr_p = float(close.iloc[-1])
            
            # 计算评分
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
            
            results.append({"name": name, "p": round(curr_p, 2), "rsi": round(rsi, 1), "m": m, "rmb": rmb})
            total_rmb += rmb
            
            # 信号翻译：改写为更直白的语言
            if m >= 1.3 or rsi <= 35:
                alert_list.append(f"🔥 {name}：目前处于‘超跌’区间，建议加大定投力度。")
            if m <= 0.6 or rsi >= 65:
                alert_list.append(f"⚠️ {name}：目前热度过高，建议缩减资金或观望。")
        except: continue

    if results:
        df = pd.DataFrame(results); df['日期'] = datetime.now().strftime("%Y-%m-%d")
        df.to_csv("global_investment_log.csv", mode='a', index=False, header=not os.path.exists("global_investment_log.csv"), encoding='utf-8-sig')
        
        # 只要有信号，就发送优化排版后的邮件
        if alert_list:
            send_alert_email(f"定投预警：发现 {len(alert_list)} 个重要信号", total_rmb, results, round(ctx['VIX'], 1), alert_list)
        else:
            print("行情平稳，无须报警。")

if __name__ == "__main__":
    main()