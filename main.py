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

# --- 1. 定投模型引擎 (保持人民币基准) ---
def calculate_rsi(prices, period=14):
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def get_market_context():
    context = {"VIX": 18, "rates": {"USD": 7.25}}
    try:
        vix_data = yf.download("^VIX", period="5d", progress=False)
        if not vix_data.empty:
            v_close = vix_data['Close'].iloc[:, 0] if isinstance(vix_data['Close'], pd.DataFrame) else vix_data['Close']
            context["VIX"] = float(v_close.dropna().iloc[-1])
        rate_data = yf.download("USDCNY=X", period="5d", progress=False)
        if not rate_data.empty:
            r_close = rate_data['Close'].iloc[:, 0] if isinstance(rate_data['Close'], pd.DataFrame) else rate_data['Close']
            context["rates"]["USD"] = float(r_close.dropna().iloc[-1])
    except: pass
    return context

# --- 2. 奢华视觉报告系统 (Black Gold Edition) ---
def send_luxury_report(title, total_rmb, results, vix, alert_list):
    mail_user = os.getenv('EMAIL_USER')
    mail_pass = os.getenv('EMAIL_PASS')
    receiver = os.getenv('EMAIL_RECEIVER')
    if not all([mail_user, mail_pass, receiver]): return

    # 构造表格行 - 奢华质感
    rows_html = ""
    for r in results:
        # 倍数颜色：高加仓用玫瑰金感，减仓用高级灰
        m_style = "color: #C5A059; font-weight: bold;" if r['m'] >= 1.3 else ("color: #8E8E93;" if r['m'] <= 0.6 else "color: #333;")
        rows_html += f"""
        <tr style="border-bottom: 1px solid #F0F0F0;">
            <td style="padding: 18px 10px; color: #1C1C1E; font-family: 'PingFang SC', sans-serif;">{r['name']}</td>
            <td style="padding: 18px 10px; text-align: center; color: #636366;">{r['p']}</td>
            <td style="padding: 18px 10px; text-align: center; color: #636366;">{r['rsi']}</td>
            <td style="padding: 18px 10px; text-align: center; {m_style}">{r['m']}x</td>
            <td style="padding: 18px 10px; text-align: right; color: #000000; font-weight: 600; font-size: 15px;">¥{r['rmb']:,}</td>
        </tr>
        """
    
    alert_html = "".join([f"<li style='margin-bottom:12px; border-left: 2px solid #C5A059; padding-left: 15px;'>{a}</li>" for a in alert_list])

    html_content = f"""
    <html>
    <body style="margin: 0; padding: 0; background-color: #F4F4F4; font-family: 'Times New Roman', 'PingFang SC', serif;">
        <table width="100%" border="0" cellspacing="0" cellpadding="0">
            <tr>
                <td align="center" style="padding: 50px 0;">
                    <table width="640" border="0" cellspacing="0" cellpadding="0" style="background-color: #FFFFFF; box-shadow: 0 20px 40px rgba(0,0,0,0.08);">
                        <tr>
                            <td style="background-color: #0F172A; padding: 45px 50px; border-bottom: 4px solid #C5A059;">
                                <table width="100%" border="0" cellspacing="0" cellpadding="0">
                                    <tr>
                                        <td>
                                            <h2 style="color: #C5A059; margin: 0; font-size: 12px; text-transform: uppercase; letter-spacing: 4px; font-weight: 400;">Private Intelligence</h2>
                                            <h1 style="color: #FFFFFF; margin: 5px 0 0 0; font-size: 26px; font-weight: 500; letter-spacing: 1px;">全球资产策略简报</h1>
                                        </td>
                                        <td align="right" style="color: #C5A059; font-size: 14px; letter-spacing: 1px;">
                                            {datetime.now().strftime('%Y / %m / %d')}
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>
                        
                        <tr>
                            <td style="padding: 40px 50px 20px 50px;">
                                <table width="100%" border="0" cellspacing="0" cellpadding="0">
                                    <tr>
                                        <td width="50%" style="border-right: 1px solid #EEEEEE;">
                                            <p style="color: #8E8E93; font-size: 11px; margin: 0; text-transform: uppercase;">市场恐慌指数 / VIX</p>
                                            <p style="color: #1C1C1E; font-size: 24px; margin: 5px 0 0 0; font-weight: 300;">{vix}</p>
                                        </td>
                                        <td width="50%" style="padding-left: 30px;">
                                            <p style="color: #8E8E93; font-size: 11px; margin: 0; text-transform: uppercase;">今日执行预算 / Total</p>
                                            <p style="color: #C5A059; font-size: 24px; margin: 5px 0 0 0; font-weight: 500;">¥ {total_rmb:,.2f}</p>
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>

                        <tr>
                            <td style="padding: 20px 50px 40px 50px;">
                                <table width="100%" border="0" cellspacing="0" cellpadding="0" style="font-size: 14px; border-collapse: collapse;">
                                    <thead>
                                        <tr style="border-bottom: 1px solid #000000;">
                                            <th align="left" style="padding: 15px 10px; color: #1C1C1E; font-weight: 600; text-transform: uppercase; font-size: 11px; letter-spacing: 1px;">Assets</th>
                                            <th align="center" style="padding: 15px 10px; color: #1C1C1E; font-weight: 600; text-transform: uppercase; font-size: 11px;">Price</th>
                                            <th align="center" style="padding: 15px 10px; color: #1C1C1E; font-weight: 600; text-transform: uppercase; font-size: 11px;">RSI</th>
                                            <th align="center" style="padding: 15px 10px; color: #1C1C1E; font-weight: 600; text-transform: uppercase; font-size: 11px;">Mult.</th>
                                            <th align="right" style="padding: 15px 10px; color: #1C1C1E; font-weight: 600; text-transform: uppercase; font-size: 11px;">Amount</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {rows_html}
                                    </tbody>
                                </table>
                            </td>
                        </tr>

                        <tr>
                            <td style="padding: 0 50px 50px 50px;">
                                <div style="background-color: #FBFBFB; padding: 30px; border-radius: 2px;">
                                    <h3 style="margin: 0 0 20px 0; color: #1C1C1E; font-size: 16px; font-weight: 500; border-bottom: 1px solid #C5A059; display: inline-block; padding-bottom: 5px;">战略执行建议</h3>
                                    <ul style="margin: 0; padding: 0; list-style: none; color: #3A3A3C; font-size: 14px; line-height: 2;">
                                        {alert_html}
                                    </ul>
                                </div>
                            </td>
                        </tr>

                        <tr>
                            <td style="background-color: #FFFFFF; padding: 30px 50px; text-align: center; border-top: 1px solid #F4F4F4;">
                                <p style="color: #AEAEB2; font-size: 10px; margin: 0; letter-spacing: 2px; text-transform: uppercase;">
                                    Confidential Strategic Intelligence · Automated Generation
                                </p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """
    
    msg = MIMEMultipart()
    msg['Subject'] = Header(title, 'utf-8')
    msg['From'] = formataddr((str(Header('Sentinel Intelligence Pro', 'utf-8')), mail_user))
    msg['To'] = receiver
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))
    
    try:
        with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=15) as smtp:
            smtp.login(mail_user, mail_pass)
            smtp.sendmail(mail_user, [receiver], msg.as_string())
        print("✉️ 尊享版策略简报已送达。")
    except Exception as e: print(f"发送异常: {e}")

# --- 3. 运行逻辑 ---
def main():
    if not os.path.exists("assets.json"): return
    with open("assets.json", 'r', encoding='utf-8') as f:
        assets = json.load(f)
    
    ctx = get_market_context()
    results, total_rmb, alert_list = [], 0, []
    
    for name, info in assets.items():
        try:
            data = yf.download(info['ticker'], period="2y", progress=False)
            if data.empty: continue
            close = data['Close'].iloc[:, 0] if isinstance(data['Close'], pd.DataFrame) else data['Close']
            curr_p = float(close.iloc[-1])
            ma = [close.rolling(w).mean().iloc[-1] for w in [20, 60, 120, 250]]
            m = 0.6
            if curr_p < ma[0]: m += 0.2
            if curr_p < ma[1]: m += 0.3
            if curr_p < ma[2]: m += 0.4
            if curr_p < ma[3]: m += 0.5
            
            rsi_val = round(calculate_rsi(close), 1)
            if rsi_val < 35: m += 0.3
            if rsi_val > 65: m -= 0.3
            if ctx['VIX'] > 25: m += 0.2
            
            m = round(max(0.4, min(m, 3.5)), 2)
            rmb_amt = round(info['base_amount'] * m, 2)
            results.append({"name": name, "p": round(curr_p, 2), "rsi": rsi_val, "m": m, "rmb": rmb_amt})
            total_rmb += rmb_amt
            
            if m >= 1.3 or rsi_val <= 35:
                alert_list.append(f"<b>{name}</b> 现处于战略级低估区间，建议启动强化配置计划。")
            elif m <= 0.6 or rsi_val >= 65:
                alert_list.append(f"<b>{name}</b> 市场热度已达峰值，建议执行风险规避，暂缓投入。")
        except: continue

    if results:
        # 记录数据
        df = pd.DataFrame(results); df['日期'] = datetime.now().strftime("%Y-%m-%d")
        df.to_csv("global_investment_log.csv", mode='a', index=False, header=not os.path.exists("global_investment_log.csv"), encoding='utf-8-sig')
        
        # 触发预警
        if alert_list:
            send_luxury_report(f"Strategic Intelligence: {datetime.now().strftime('%m / %d')} 资产研判", total_rmb, results, round(ctx['VIX'], 1), alert_list)

if __name__ == "__main__":
    main()