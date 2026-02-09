import yfinance as yf
import pandas as pd
import os
import json
import smtplib
import time
from google import genai
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
from datetime import datetime

# --- 1. 定投量化引擎 ---
def calculate_rsi(prices, period=14):
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1] if not rsi.empty else 50

def get_market_context():
    ctx = {"VIX": 18}
    try:
        vix_data = yf.download("^VIX", period="5d", progress=False)
        if not vix_data.empty:
            ctx["VIX"] = float(vix_data['Close'].iloc[-1])
    except: pass
    return ctx

# --- 2. AI 战略研判 (带自动重试与降级逻辑) ---
def get_ai_advice(vix, total_amt, results):
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key: return None
    
    # 采用 1.5-flash，因为它有最慷慨的免费配额，基本不会触发 429
    model_name = 'gemini-1.5-flash'
    client = genai.Client(api_key=api_key)
    
    summary = f"VIX: {vix}, 今日建议总出资: {total_amt} RMB。\n详情：\n"
    for r in results:
        summary += f"- {r['name']}: RSI {r['rsi']}, 定投权重 {r['m']}x\n"
    
    prompt = f"你是一位全球资管专家。请为高级行政官员分析以下量化数据，提供3条简明、稳重的战略执行建议，使用HTML的<li>标签输出：\n{summary}"

    # 自动重试逻辑 (应对 429 错误)
    for attempt in range(3):
        try:
            response = client.models.generate_content(model=model_name, contents=prompt)
            return response.text
        except Exception as e:
            if "429" in str(e):
                print(f"⚠️ 服务器繁忙 (429)，第 {attempt+1} 次尝试等待中...")
                time.sleep(20) # 等待 20 秒再重试
            else:
                print(f"❌ AI 引擎异常: {e}")
                break
    return None

# --- 3. Google Finance 视觉模板 ---
def send_google_report(title, total_rmb, results, vix, ai_advice):
    mail_user = os.getenv('EMAIL_USER')
    mail_pass = os.getenv('EMAIL_PASS')
    receiver = os.getenv('EMAIL_RECEIVER')
    if not all([mail_user, mail_pass, receiver]): return

    rows_html = "".join([f"""
        <tr style="border-bottom: 1px solid #dadce0;">
            <td style="padding:16px 8px; color:#1a73e8; font-weight:500;">{r['name']}</td>
            <td style="padding:16px 8px; text-align:right; color:#202124;">{r['p']}</td>
            <td style="padding:16px 8px; text-align:right; color:#70757a;">{r['rsi']}</td>
            <td style="padding:16px 8px; text-align:right;">
                <span style="padding:4px 10px; border-radius:4px; background:{'#e6f4ea' if r['m']>=1.3 else '#fce8e6' if r['m']<=0.6 else '#f8f9fa'}; color:{'#137333' if r['m']>=1.3 else '#c5221f' if r['m']<=0.6 else '#3c4043'}; font-weight:600; font-size:12px;">{r['m']}x</span>
            </td>
            <td style="padding:16px 8px; text-align:right; color:#202124; font-weight:500;">¥{r['rmb']:,}</td>
        </tr>""" for r in results])

    advice_body = ai_advice if ai_advice else "<li>AI 幕僚目前由于流量管控无法连接，请参考上方量化数据自行决策。</li>"

    html = f"""
    <div style="font-family:'Roboto',Arial,sans-serif; max-width:650px; margin:auto; border:1px solid #dadce0; border-radius:8px; overflow:hidden;">
        <div style="padding:20px 24px; border-bottom:1px solid #dadce0; background:#fff;">
            <span style="font-size:22px; color:#5f6368;">Google</span><span style="font-size:22px; color:#5f6368; font-weight:400;"> Finance</span>
            <span style="background:#e8f0fe; color:#1a73e8; padding:2px 8px; border-radius:12px; font-size:10px; margin-left:10px; font-weight:600;">STABLE SENTINEL</span>
        </div>
        <div style="padding:24px;">
            <table width="100%" style="margin-bottom:24px;">
                <tr>
                    <td style="border:1px solid #dadce0; border-radius:8px; padding:16px; width:48%;">
                        <div style="color:#70757a; font-size:11px; margin-bottom:4px; text-transform:uppercase;">Volatility Index (VIX)</div>
                        <div style="font-size:28px; color:#202124;">{vix}</div>
                    </td>
                    <td width="4%"></td>
                    <td style="border:1px solid #dadce0; border-radius:8px; padding:16px; width:48%;">
                        <div style="color:#70757a; font-size:11px; margin-bottom:4px; text-transform:uppercase;">Daily Budget (RMB)</div>
                        <div style="font-size:28px; color:#1a73e8; font-weight:500;">¥ {total_rmb:,.2f}</div>
                    </td>
                </tr>
            </table>
            <table width="100%" style="border-collapse:collapse; margin-bottom:30px;">
                <thead>
                    <tr style="border-bottom:1px solid #dadce0; color:#70757a; font-size:11px; text-transform:uppercase;">
                        <th align="left">Asset</th><th align="right">Price</th><th align="right">RSI</th><th align="right">Mult.</th><th align="right">Amount</th>
                    </tr>
                </thead>
                <tbody>{rows_html}</tbody>
            </table>
            <div style="background:#f8f9fa; border-radius:8px; padding:24px; border:1px solid #eee;">
                <div style="font-size:15px; color:#202124; font-weight:500; margin-bottom:12px;">战略研判与执行建议</div>
                <ul style="margin:0; padding-left:20px; font-size:14px; color:#3c4043; line-height:1.8;">{advice_body}</ul>
            </div>
        </div>
        <div style="background:#f1f3f4; padding:16px 24px; text-align:center; color:#70757a; font-size:11px;">
            Sentinel Intelligence v4.9 · {datetime.now().strftime('%Y-%m-%d %H:%M')}
        </div>
    </div>"""
    
    msg = MIMEMultipart()
    msg['Subject'] = Header(title, 'utf-8')
    msg['From'] = formataddr((str(Header('Sentinel Intelligence', 'utf-8')), mail_user))
    msg['To'] = receiver
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    
    with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=15) as smtp:
        smtp.login(mail_user, mail_pass)
        smtp.sendmail(mail_user, [receiver], msg.as_string())

# --- 4. 运行引擎 ---
def main():
    if not os.path.exists("assets.json"): return
    with open("assets.json", 'r', encoding='utf-8') as f:
        assets = json.load(f)
    
    ctx = get_market_context()
    results, total_all = [], 0
    
    for name, info in assets.items():
        try:
            data = yf.download(info['ticker'], period="2y", progress=False)
            if data.empty: continue
            prices = data['Close'].iloc[:, 0] if isinstance(data['Close'], pd.DataFrame) else data['Close']
            curr_p = float(prices.iloc[-1])
            ma = [prices.rolling(w).mean().iloc[-1] for w in [20, 60, 120, 250]]
            m = 0.6
            if curr_p < ma[0]: m += 0.2
            if curr_p < ma[1]: m += 0.3
            if curr_p < ma[2]: m += 0.4
            if curr_p < ma[3]: m += 0.5
            rsi_val = round(calculate_rsi(prices), 1)
            if rsi_val < 35: m += 0.3
            if rsi_val > 65: m -= 0.3
            if ctx['VIX'] > 25: m += 0.2
            m = round(max(0.4, min(m, 3.5)), 2)
            rmb_amt = round(info['base_amount'] * m, 2)
            results.append({"name": name, "p": round(curr_p, 2), "rsi": rsi_val, "m": m, "rmb": rmb_amt})
            total_all += rmb_amt
        except: continue

    if results:
        df = pd.DataFrame(results); df['日期'] = datetime.now().strftime("%Y-%m-%d")
        df.to_csv("global_investment_log.csv", mode='a', index=False, header=not os.path.exists("global_investment_log.csv"), encoding='utf-8-sig')
        
        # 即使 AI 获取失败，邮件也会发送基础表格数据
        ai_res = get_ai_advice(round(ctx['VIX'], 1), round(total_all, 2), results)
        send_google_report(f"Strategic Report: {datetime.now().strftime('%m/%d')} 决策日报", total_all, results, round(ctx['VIX'], 1), ai_res)

if __name__ == "__main__":
    main()