import yfinance as yf
import pandas as pd
import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
from datetime import datetime

# --- 1. 计算核心（人民币口径） ---
def calculate_rsi(prices, period=14):
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def get_market_context():
    context = {"VIX": 18}
    try:
        vix_data = yf.download("^VIX", period="5d", progress=False)
        if not vix_data.empty:
            v_close = vix_data['Close'].iloc[:, 0] if isinstance(vix_data['Close'], pd.DataFrame) else vix_data['Close']
            context["VIX"] = float(v_close.dropna().iloc[-1])
    except: pass
    return context

# --- 2. 视觉报告：Google Finance 风格 ---
def send_google_style_report(title, total_rmb, results, vix, alert_list):
    mail_user = os.getenv('EMAIL_USER')
    mail_pass = os.getenv('EMAIL_PASS')
    receiver = os.getenv('EMAIL_RECEIVER')
    if not all([mail_user, mail_pass, receiver]): return

    # 构造数据行
    rows_html = ""
    for r in results:
        # 机会绿色 (#137333)，风险红色 (#c5221f)
        m_color = "#137333" if r['m'] >= 1.3 else ("#c5221f" if r['m'] <= 0.6 else "#3c4043")
        m_bg = "#e6f4ea" if r['m'] >= 1.3 else ("#fce8e6" if r['m'] <= 0.6 else "transparent")
        
        rows_html += f"""
        <tr style="border-bottom: 1px solid #dadce0;">
            <td style="padding: 16px 8px; color: #1a73e8; font-size: 14px; font-weight: 500;">{r['name']}</td>
            <td style="padding: 16px 8px; text-align: right; color: #202124; font-size: 14px;">{r['p']}</td>
            <td style="padding: 16px 8px; text-align: right; color: #70757a; font-size: 13px;">{r['rsi']}</td>
            <td style="padding: 16px 8px; text-align: right;">
                <span style="padding: 4px 8px; border-radius: 4px; background-color: {m_bg}; color: {m_color}; font-weight: 500; font-size: 13px;">
                    {r['m']}x
                </span>
            </td>
            <td style="padding: 16px 8px; text-align: right; color: #202124; font-size: 14px; font-weight: 500;">¥{r['rmb']:,}</td>
        </tr>
        """

    html_body = f"""
    <html>
    <body style="margin: 0; padding: 0; background-color: #ffffff; font-family: 'Roboto', 'Arial', sans-serif; color: #3c4043;">
        <table width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width: 650px; margin: auto;">
            <tr>
                <td style="padding: 24px 16px; border-bottom: 1px solid #dadce0;">
                    <span style="font-size: 22px; color: #5f6368;">投资</span>
                    <span style="font-size: 22px; color: #5f6368; font-weight: 400;"> 简报</span>
                    <span style="margin-left: 8px; padding: 2px 6px; background: #1a73e8; color: white; border-radius: 3px; font-size: 12px; vertical-align: middle;">PRO</span>
                </td>
            </tr>
            
            <tr>
                <td style="padding: 24px 16px;">
                    <table width="100%" border="0" cellspacing="0" cellpadding="0">
                        <tr>
                            <td style="border: 1px solid #dadce0; border-radius: 8px; padding: 16px; width: 48%;">
                                <div style="color: #70757a; font-size: 12px; margin-bottom: 4px;">市场恐慌指数 (VIX)</div>
                                <div style="font-size: 24px; color: #202124;">{vix}</div>
                            </td>
                            <td width="4%"></td>
                            <td style="border: 1px solid #dadce0; border-radius: 8px; padding: 16px; width: 48%;">
                                <div style="color: #70757a; font-size: 12px; margin-bottom: 4px;">今日建议总投入 (RMB)</div>
                                <div style="font-size: 24px; color: #1a73e8; font-weight: 500;">¥ {total_rmb:,.2f}</div>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>

            <tr>
                <td style="padding: 0 16px;">
                    <div style="font-size: 18px; color: #202124; margin-bottom: 16px;">您的观察清单</div>
                    <table width="100%" border="0" cellspacing="0" cellpadding="0" style="border-collapse: collapse;">
                        <thead>
                            <tr style="border-bottom: 1px solid #dadce0; color: #70757a; font-size: 12px;">
                                <th align="left" style="padding-bottom: 8px;">资产名称</th>
                                <th align="right" style="padding-bottom: 8px;">最新价格</th>
                                <th align="right" style="padding-bottom: 8px;">热度(RSI)</th>
                                <th align="right" style="padding-bottom: 8px;">定投倍数</th>
                                <th align="right" style="padding-bottom: 8px;">建议金额</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rows_html}
                        </tbody>
                    </table>
                </td>
            </tr>

            <tr>
                <td style="padding: 32px 16px;">
                    <div style="background-color: #f8f9fa; border-radius: 8px; padding: 20px;">
                        <div style="font-size: 14px; color: #202124; font-weight: 500; margin-bottom: 12px;">智能决策摘要</div>
                        <ul style="margin: 0; padding-left: 20px; font-size: 13px; color: #3c4043; line-height: 1.8;">
                            {"".join([f"<li>{a}</li>" for a in alert_list])}
                        </ul>
                    </div>
                </td>
            </tr>

            <tr>
                <td style="padding: 24px 16px; text-align: center; color: #70757a; font-size: 11px; border-top: 1px solid #dadce0;">
                    数据由量化哨兵系统实时抓取 · {datetime.now().strftime('%Y-%m-%d %H:%M')}<br>
                    建议仅供参考，请结合场内溢价情况审慎操作。
                </td>
            </tr>
        </table>
    </body>
    </html>
    """
    
    msg = MIMEMultipart()
    msg['Subject'] = Header(title, 'utf-8')
    msg['From'] = formataddr((str(Header('投资简报', 'utf-8')), mail_user))
    msg['To'] = receiver
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))
    
    try:
        with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=15) as smtp:
            smtp.login(mail_user, mail_pass)
            smtp.sendmail(mail_user, [receiver], msg.as_string())
        print("✉️ 简报已发送。")
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
                alert_list.append(f"<b>{name}</b>：价格低于均线且热度偏低，触发买入信号。")
            elif m <= 0.6 or rsi_val >= 65:
                alert_list.append(f"<b>{name}</b>：市场情绪亢奋，建议规避追高风险。")
        except: continue

    if results:
        df = pd.DataFrame(results); df['日期'] = datetime.now().strftime("%Y-%m-%d")
        df.to_csv("global_investment_log.csv", mode='a', index=False, header=not os.path.exists("global_investment_log.csv"), encoding='utf-8-sig')
        if alert_list:
            send_google_style_report(f"投资简报: {datetime.now().strftime('%m月%d日')} 投资组合动态", total_rmb, results, round(ctx['VIX'], 1), alert_list)

if __name__ == "__main__":
    main()