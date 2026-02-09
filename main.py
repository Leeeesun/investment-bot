import yfinance as yf
import pandas as pd
import os
import json
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# --- 1. 获取汇率逻辑 ---
def get_exchange_rates():
    tickers = {"USD": "USDCNY=X", "JPY": "JPYCNY=X", "EUR": "EURCNY=X", "HKD": "HKDCNY=X"}
    rates = {"CNY": 1.0}
    try:
        data = yf.download(list(tickers.values()), period="5d", progress=False)['Close']
        for curr, ticker in tickers.items():
            rates[curr] = float(data[ticker].dropna().iloc[-1])
    except:
        rates.update({"USD": 7.25, "JPY": 0.048, "EUR": 7.8, "HKD": 0.93})
    return rates

# --- 2. 消息发送逻辑 ---
def send_notifications(title, md_content):
    # A. 发送邮件
    mail_user = os.getenv('EMAIL_USER')
    mail_pass = os.getenv('EMAIL_PASS')
    receiver = os.getenv('EMAIL_RECEIVER')
    if all([mail_user, mail_pass, receiver]):
        msg = MIMEMultipart()
        msg['Subject'] = title
        msg['From'] = f"定投管家 <{mail_user}>"
        msg['To'] = receiver
        # 邮件使用简单的 HTML 格式
        html_body = md_content.replace("\n", "<br>").replace("|", " ")
        msg.attach(MIMEText(f"<html><body>{html_body}</body></html>", 'html', 'utf-8'))
        try:
            with smtplib.SMTP_SSL("smtp.qq.com", 465) as smtp:
                smtp.login(mail_user, mail_pass)
                smtp.sendmail(mail_user, [receiver], msg.as_string())
        except Exception as e: print(f"邮件失败: {e}")

    # B. 发送 Webhook (钉钉/企微)
    webhook_url = os.getenv('WEBHOOK_URL')
    if webhook_url:
        payload = {"msgtype": "markdown", "markdown": {"title": title, "text": f"### {title}\n\n{md_content}"}}
        try: requests.post(webhook_url, json=payload, timeout=10)
        except: pass

# --- 3. 核心计算逻辑 ---
def run_automation():
    with open("assets.json", 'r', encoding='utf-8') as f:
        my_assets = json.load(f)
    
    rates = get_exchange_rates()
    results = []; total_rmb_budget = 0
    now = datetime.now(); today_str = now.strftime("%Y-%m-%d")
    report_type = "【周一·上周结算】" if now.weekday() == 0 else "【周五·本周盘点】"

    for name, info in my_assets.items():
        try:
            data = yf.download(info['ticker'], period="2y", progress=False, timeout=20)
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
            total_rmb_budget += rmb_amt

            results.append({"资产": name, "现价": round(curr_p, 2), "倍数": multiplier, "RMB金额": round(rmb_amt, 2)})
        except: continue

    if results:
        md = f"**总预算：{total_rmb_budget:.2f} CNY**\n\n| 资产 | 现价 | 倍数 | **RMB金额** |\n| :--- | :--- | :--- | :--- |\n"
        for r in results:
            md += f"| {r['资产']} | {r['现价']} | {r['倍数']}x | **{r['RMB金额']}** |\n"
        
        send_notifications(f"{report_type} 定投建议", md)
        
        # 存档与 Summary
        df = pd.DataFrame(results); df['日期'] = today_str
        log = "global_investment_log.csv"
        df.to_csv(log, mode='a', index=False, header=not os.path.exists(log), encoding='utf-8-sig')
        summary = os.getenv('GITHUB_STEP_SUMMARY')
        if summary:
            with open(summary, 'a') as f: f.write(f"## {report_type} 看板\n{md}")

if __name__ == "__main__":
    run_automation()