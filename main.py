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

# --- 1. 计算核心 (保持人民币基准) ---
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
    except: pass
    return context

# --- 2. 视觉进化版：高端行政简报 (High-End Minimalism) ---
def send_executive_report(title, total_rmb, results, vix, alert_list):
    mail_user = os.getenv('EMAIL_USER')
    mail_pass = os.getenv('EMAIL_PASS')
    receiver = os.getenv('EMAIL_RECEIVER')
    if not all([mail_user, mail_pass, receiver]): return

    # 构造表格行 - 极致简洁
    rows_html = ""
    for r in results:
        # 仅通过字体加粗和微小的颜色变化体现重点
        m_style = "color: #AF2D2D; font-weight: 600;" if r['m'] >= 1.3 else ("color: #2D5FAF;" if r['m'] <= 0.6 else "color: #1C1C1E;")
        rows_html += f"""
        <tr style="border-bottom: 0.5px solid #E5E5EA;">
            <td style="padding: 20px 0; color: #1C1C1E; font-size: 15px; font-weight: 500;">{r['name']}</td>
            <td style="padding: 20px 0; text-align: center; color: #8E8E93; font-size: 14px;">{r['p']}</td>
            <td style="padding: 20px 0; text-align: center; color: #8E8E93; font-size: 14px;">{r['rsi']}</td>
            <td style="padding: 20px 0; text-align: center; {m_style}">{r['m']}x</td>
            <td style="padding: 20px 0; text-align: right; color: #1C1C1E; font-weight: 600; font-size: 16px;">¥{r['rmb']:,}</td>
        </tr>
        """
    
    # 构造决策建议：采用“批注”风格
    alert_html = "".join([f"<div style='margin-bottom:12px; border-left: 3px solid #1C1C1E; padding-left: 15px; color: #3A3A3C;'>{a}</div>" for a in alert_list])

    html_content = f"""
    <html>
    <body style="margin: 0; padding: 0; background-color: #FBFBFB; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
        <table width="100%" border="0" cellspacing="0" cellpadding="0">
            <tr>
                <td align="center" style="padding: 60px 0;">
                    <table width="600" border="0" cellspacing="0" cellpadding="0" style="background-color: #FFFFFF; border-radius: 2px; box-shadow: 0 4px 24px rgba(0,0,0,0.04);">
                        
                        <tr>
                            <td style="padding: 40px 50px 30px 50px; border-bottom: 2px solid #1C1C1E;">
                                <table width="100%" border="0" cellspacing="0" cellpadding="0">
                                    <tr>
                                        <td>
                                            <h1 style="margin: 0; color: #1C1C1E; font-size: 24px; font-weight: 600; letter-spacing: -0.5px;">策略投资组合日报</h1>
                                            <p style="margin: 5px 0 0 0; color: #8E8E93; font-size: 12px; text-transform: uppercase; letter-spacing: 2px;">Quantitative Strategy Report</p>
                                        </td>
                                        <td align="right" valign="bottom">
                                            <p style="margin: 0; color: #1C1C1E; font-size: 14px; font-weight: 500;">{datetime.now().strftime('%Y.%m.%d')}</p>
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>
                        
                        <tr>
                            <td style="padding: 40px 50px 10px 50px;">
                                <table width="100%" border="0" cellspacing="0" cellpadding="0">
                                    <tr>
                                        <td>
                                            <p style="color: #8E8E93; font-size: 11px; margin: 0; text-transform: uppercase; letter-spacing: 1px;">Market Volatility (VIX)</p>
                                            <p style="color: #1C1C1E; font-size: 22px; margin: 4px 0 0 0; font-weight: 400;">{vix}</p>
                                        </td>
                                        <td align="right">
                                            <p style="color: #8E8E93; font-size: 11px; margin: 0; text-transform: uppercase; letter-spacing: 1px;">Total Allocation (RMB)</p>
                                            <p style="color: #1C1C1E; font-size: 22px; margin: 4px 0 0 0; font-weight: 600;">¥ {total_rmb:,.2f}</p>
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>

                        <tr>
                            <td style="padding: 20px 50px 40px 50px;">
                                <table width="100%" border="0" cellspacing="0" cellpadding="0" style="border-collapse: collapse;">
                                    <thead>
                                        <tr style="border-bottom: 1px solid #1C1C1E;">
                                            <th align="left" style="padding: 12px 0; color: #1C1C1E; font-size: 11px; text-transform: uppercase; letter-spacing: 1px;">Asset Name</th>
                                            <th align="center" style="padding: 12px 0; color: #1C1C1E; font-size: 11px; text-transform: uppercase;">Price</th>
                                            <th align="center" style="padding: 12px 0; color: #1C1C1E; font-size: 11px; text-transform: uppercase;">RSI</th>
                                            <th align="center" style="padding: 12px 0; color: #1C1C1E; font-size: 11px; text-transform: uppercase;">Mult.</th>
                                            <th align="right" style="padding: 12px 0; color: #1C1C1E; font-size: 11px; text-transform: uppercase;">Subtotal</th>
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
                                <div style="background-color: #F2F2F7; padding: 30px; border-radius: 4px;">
                                    <h3 style="margin: 0 0 20px 0; color: #1C1C1E; font-size: 15px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;">Executive Summary</h3>
                                    <div style="font-size: 14px; line-height: 1.6; color: #3A3A3C;">
                                        {alert_html}
                                    </div>
                                    <div style="margin-top: 25px; font-size: 11px; color: #8E8E93; border-top: 1px solid #D1D1D6; padding-top: 15px;">
                                        * 此建议基于多维量化模型生成，场内执行请关注 IOPV 溢价。
                                    </div>
                                </div>
                            </td>
                        </tr>

                        <tr>
                            <td style="padding: 0 50px 40px 50px; text-align: center;">
                                <p style="color: #C7C7CC; font-size: 10px; margin: 0; letter-spacing: 2px; text-transform: uppercase;">
                                    Confidential Portfolio Sentinel · Automated System
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
    msg['From'] = formataddr((str(Header('Sentinel Intelligence', 'utf-8')), mail_user))
    msg['To'] = receiver
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))
    
    try:
        with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=15) as smtp:
            smtp.login(mail_user, mail_pass)
            smtp.sendmail(mail_user, [receiver], msg.as_string())
        print("✉️ 行政精简版简报发送成功。")
    except Exception as e: print(f"发送失败: {e}")

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
                alert_list.append(f"资产 <b>{name}</b> 处于价值洼地，建议增加配置头寸。")
            elif m <= 0.6 or rsi_val >= 65:
                alert_list.append(f"资产 <b>{name}</b> 动能趋于枯竭，建议收缩投资规模。")
        except: continue

    if results:
        df = pd.DataFrame(results); df['日期'] = datetime.now().strftime("%Y-%m-%d")
        df.to_csv("global_investment_log.csv", mode='a', index=False, header=not os.path.exists("global_investment_log.csv"), encoding='utf-8-sig')
        
        if alert_list:
            send_executive_report(f"Strategic Intelligence Report - {datetime.now().strftime('%m.%d')}", total_rmb, results, round(ctx['VIX'], 1), alert_list)

if __name__ == "__main__":
    main()