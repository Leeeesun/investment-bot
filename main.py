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

# --- 1. 获取汇率逻辑 ---
def get_exchange_rates():
    rates = {"CNY": 1.0, "USD": 7.25, "JPY": 0.048, "EUR": 7.8, "HKD": 0.93}
    tickers = {"USD": "USDCNY=X", "JPY": "JPYCNY=X", "EUR": "EURCNY=X", "HKD": "HKDCNY=X"}
    for curr, ticker in tickers.items():
        try:
            data = yf.download(ticker, period="5d", progress=False)
            if not data.empty:
                val = data['Close'].iloc[:, 0] if isinstance(data['Close'], pd.DataFrame) else data['Close']
                rates[curr] = float(val.dropna().iloc[-1])
        except: pass
    return rates

# --- 2. 消息发送逻辑 (UI 升级版) ---
def send_notifications(title, total_rmb, results_list):
    mail_user = os.getenv('EMAIL_USER')
    mail_pass = os.getenv('EMAIL_PASS')
    receiver = os.getenv('EMAIL_RECEIVER')
    
    if all([mail_user, mail_pass, receiver]):
        msg = MIMEMultipart()
        msg['Subject'] = Header(title, 'utf-8')
        msg['From'] = formataddr((str(Header('全球资产管理终端', 'utf-8')), mail_user))
        msg['To'] = receiver
        
        # 构造表格行
        rows_html = ""
        for r in results_list:
            # 根据倍数决定颜色：加仓红色，减仓灰色
            color = "#e74c3c" if r['倍数'] > 1 else "#2c3e50"
            rows_html += f"""
            <tr style="border-bottom: 1px solid #eee;">
                <td style="padding: 12px; text-align: left;">{r['资产']}</td>
                <td style="padding: 12px; text-align: center;">{r['价格']}</td>
                <td style="padding: 12px; text-align: center; color: {color}; font-weight: bold;">{r['倍数']}x</td>
                <td style="padding: 12px; text-align: right; font-weight: bold; color: #2c3e50;">¥{r['金额']:,}</td>
            </tr>
            """

        # 构造精美的 HTML 模板
        html_body = f"""
        <html>
        <body style="margin: 0; padding: 0; background-color: #f4f7f9; font-family: 'Microsoft YaHei', Helvetica, Arial, sans-serif;">
            <table width="100%" border="0" cellspacing="0" cellpadding="0">
                <tr>
                    <td align="center" style="padding: 20px 0;">
                        <table width="600" border="0" cellspacing="0" cellpadding="0" style="background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 10px rgba(0,0,0,0.1);">
                            <tr>
                                <td style="background-color: #2c3e50; padding: 30px 40px; text-align: left;">
                                    <h1 style="color: #ffffff; margin: 0; font-size: 24px; letter-spacing: 1px;">{title}</h1>
                                    <p style="color: #bdc3c7; margin: 10px 0 0 0; font-size: 14px;">量化定投系统 · 自动化分析决策</p>
                                </td>
                            </tr>
                            <tr>
                                <td style="padding: 30px 40px;">
                                    <div style="background-color: #f8f9fa; border-left: 4px solid #e74c3c; padding: 20px; margin-bottom: 30px;">
                                        <p style="margin: 0; color: #7f8c8d; font-size: 14px;">本期建议总投入 (RMB)</p>
                                        <h2 style="margin: 5px 0 0 0; color: #e74c3c; font-size: 32px;">¥ {total_rmb:,.2f}</h2>
                                    </div>
                                    <table width="100%" border="0" cellspacing="0" cellpadding="0" style="font-size: 15px; color: #34495e;">
                                        <thead>
                                            <tr style="background-color: #fdfdfd; border-bottom: 2px solid #eee;">
                                                <th style="padding: 12px; text-align: left;">资产名称</th>
                                                <th style="padding: 12px; text-align: center;">最新价格</th>
                                                <th style="padding: 12px; text-align: center;">定投倍数</th>
                                                <th style="padding: 12px; text-align: right;">建议金额</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {rows_html}
                                        </tbody>
                                    </table>
                                </td>
                            </tr>
                            <tr>
                                <td style="background-color: #fafafa; padding: 20px 40px; text-align: center; border-top: 1px solid #eee;">
                                    <p style="color: #95a5a6; font-size: 12px; margin: 0;">
                                        * 本报告由云端自动化系统基于四维均线算法生成，仅供决策参考。<br>
                                        结算时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
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
        
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))
        
        try:
            with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=15) as smtp:
                smtp.login(mail_user, mail_pass)
                smtp.sendmail(mail_user, [receiver], msg.as_string())
            print("✉️ 视觉增强版邮件发送成功！")
        except Exception as e:
            print(f"❌ 邮件发送失败: {e}")

# --- 3. 核心计算逻辑 ---
def run_automation():
    if not os.path.exists("assets.json"): return

    with open("assets.json", 'r', encoding='utf-8') as f:
        my_assets = json.load(f)
    
    rates = get_exchange_rates()
    results, total_rmb_val = [], 0
    now = datetime.now()
    report_title = f"全球资产定投决策日报 ({now.strftime('%m月%d日')})"

    for name, info in my_assets.items():
        try:
            data = yf.download(info['ticker'], period="2y", progress=False)
            if data.empty: continue
            
            close = data['Close'].iloc[:, 0] if isinstance(data['Close'], pd.DataFrame) else data['Close']
            curr_p = float(close.iloc[-1])
            ma = [close.rolling(w).mean().iloc[-1] for w in [20, 60, 120, 250]]
            
            multiplier = 0.6
            if curr_p < ma[0]: multiplier += 0.2
            if curr_p < ma[1]: multiplier += 0.3
            if curr_p < ma[2]: multiplier += 0.4
            if curr_p < ma[3]: multiplier += 0.5
            if curr_p > ma[0] * 1.1: multiplier -= 0.2
            
            multiplier = round(max(0.4, min(multiplier, 2.5)), 2)
            rmb_amt = info['base_amount'] * multiplier * rates.get(info['currency'], 1.0)
            total_rmb_val += rmb_amt
            
            results.append({
                "资产": name, 
                "价格": round(curr_p, 2), 
                "倍数": multiplier, 
                "金额": round(rmb_amt, 2)
            })
        except: continue

    if results:
        # 传入计算好的总金额和结果列表
        send_notifications(report_title, total_rmb_val, results)
        
        # 存档 CSV
        df = pd.DataFrame(results); df['日期'] = now.strftime("%Y-%m-%d")
        log = "global_investment_log.csv"
        if os.path.exists(log):
            df.to_csv(log, mode='a', index=False, header=False, encoding='utf-8-sig')
        else:
            df.to_csv(log, index=False, encoding='utf-8-sig')

if __name__ == "__main__":
    run_automation()