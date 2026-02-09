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

def send_notifications(title, md_content):
    mail_user = os.getenv('EMAIL_USER')
    mail_pass = os.getenv('EMAIL_PASS')
    receiver = os.getenv('EMAIL_RECEIVER')
    
    if all([mail_user, mail_pass, receiver]):
        msg = MIMEMultipart()
        msg['Subject'] = Header(title, 'utf-8')
        # 核心修复：必须严格符合发件人格式
        msg['From'] = formataddr((str(Header('全球定投管家', 'utf-8')), mail_user))
        msg['To'] = receiver
        
        html_body = f"""<div style="font-family:sans-serif;padding:20px;"><h2>{title}</h2>{md_content.replace('\n', '<br>')}</div>"""
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))
        
        try:
            with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=15) as smtp:
                smtp.login(mail_user, mail_pass)
                smtp.sendmail(mail_user, [receiver], msg.as_string())
            print("✉️ 邮件提醒发送成功！")
        except Exception as e:
            print(f"❌ 邮件发送失败: {e}")

    webhook_url = os.getenv('WEBHOOK_URL')
    if webhook_url:
        try:
            requests.post(webhook_url, json={"msgtype": "markdown", "markdown": {"title": title, "text": f"### {title}\n\n{md_content}"}}, timeout=10)
        except: pass

def run_automation():
    with open("assets.json", 'r', encoding='utf-8') as f:
        my_assets = json.load(f)
    rates = get_exchange_rates()
    results, total_rmb = [], 0
    now = datetime.now()
    report_type = "【周一版】" if now.weekday() == 0 else "【周五版】"

    for name, info in my_assets.items():
        try:
            data = yf.download(info['ticker'], period="2y", progress=False)
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
            total_rmb += rmb_amt
            results.append({"资产": name, "价格": round(curr_p, 2), "倍数": multiplier, "金额": round(rmb_amt, 2)})
        except: continue

    if results:
        md = f"**本周预计总投入：{total_rmb:.2f} CNY**\n\n| 资产 | 现价 | 倍数 | **建议金额** |\n| :--- | :--- | :--- | :--- |\n"
        for r in results:
            md += f"| {r['资产']} | {r['价格']} | {r['倍数']}x | **{r['金额']}** |\n"
        
        send_notifications(f"{report_type} 定投建议", md)
        df = pd.DataFrame(results); df['日期'] = now.strftime("%Y-%m-%d")
        log = "global_investment_log.csv"
        df.to_csv(log, mode='a', index=False, header=not os.path.exists(log), encoding='utf-8-sig')
        summary = os.getenv('GITHUB_STEP_SUMMARY')
        if summary:
            with open(summary, 'a', encoding='utf-8') as f: f.write(f"## {report_type} 看板\n{md}")

if __name__ == "__main__":
    run_automation()