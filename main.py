import yfinance as yf
import pandas as pd
import os
import json
import smtplib
from google import genai
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
from datetime import datetime

# --- 1. 定投量化算法 ---
def calculate_rsi(prices, period=14):
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def get_market_context():
    ctx = {"VIX": 18, "USD_RATE": 7.25}
    try:
        vix_data = yf.download("^VIX", period="5d", progress=False)
        if not vix_data.empty:
            v_close = vix_data['Close'].iloc[:, 0] if isinstance(vix_data['Close'], pd.DataFrame) else vix_data['Close']
            ctx["VIX"] = float(v_close.dropna().iloc[-1])
        rate_data = yf.download("USDCNY=X", period="5d", progress=False)
        if not rate_data.empty:
            r_close = rate_data['Close'].iloc[:, 0] if isinstance(rate_data['Close'], pd.DataFrame) else rate_data['Close']
            ctx["USD_RATE"] = float(r_close.dropna().iloc[-1])
    except: pass
    return ctx

# --- 2. AI 战略研判 (Google Gemini 1.5 Flash) ---
def get_ai_advice(vix, total_amt, results):
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key: return None
    try:
        client = genai.Client(api_key=api_key)
        summary = f"VIX: {vix}, 总预算: {total_amt} RMB。\n"
        for r in results:
            summary += f"- {r['name']}: RSI {r['rsi']}, 倍数 {r['m']}x\n"
        
        prompt = f"""
        你是全球首席策略师。请为高级行政官员分析以下量化数据，提供战略内参：
        {summary}
        要求：语气专业、稳重。分析风险与确定性。
        格式：仅输出 HTML 的 <li> 标签列表。
        """
        response = client.models.generate_content(model='gemini-1.5-flash', contents=prompt)
        return response.text
    except Exception as e:
        print(f"AI 模块连接受阻: {e}")
        return None

# --- 3. Google Finance 视觉模板 ---
def send_report(title, total_rmb, results, vix, ai_advice, fallbacks):
    mail_user = os.getenv('EMAIL_USER')
    mail_pass = os.getenv('EMAIL_PASS')
    receiver = os.getenv('EMAIL_RECEIVER')
    if not all([mail_user, mail_pass, receiver]): return

    rows_html = ""
    for r in results:
        m_color = "#137333" if r['m'] >= 1.3 else ("#c5221f" if r['m'] <= 0.6 else "#3c4043")
        m_bg = "#e6f4ea" if r['m'] >= 1.3 else ("#fce8e6" if r['m'] <= 0.6 else "#f8f9fa")
        rows_html += f"""
        <tr style="border-bottom: 1px solid #dadce0;">
            <td style="padding:16px 8px; color:#1a73e8; font-weight:500;">{r['name']}</td>
            <td style="padding:16px 8px; text-align:right; color:#202124;">{r['p']}</td>
            <td style="padding:16px 8px; text-align:right; color:#70757a;">{r['rsi']}</td>
            <td style="padding:16px 8px; text-align:right;">
                <span style="padding:4px 10px; border-radius:4px; background:{m_bg}; color:{m_color}; font-weight:500; font-size:12px;">{r['m']}x</span>
            </td>
            <td style="padding:16px 8px; text-align:right; color:#202124; font-weight:500;">¥{r['rmb']:,}</td>
        </tr>"""

    advice_body = ai_advice if ai_advice else "".join([f"<li>{f}</li>" for f in fallbacks])
    badge = '<span style="background:#e8f0fe; color:#1a73e8; padding:2px 8px; border-radius:12px; font-size:10px; margin-left:10px; font-weight:600;">AI INSIGHT</span>' if ai_advice else ''

    html = f"""
    <div style="font-family:'Roboto',Arial,sans-serif; max-width:650px; margin:auto; border:1px solid #dadce0; border-radius:8px; overflow:hidden;">
        <div style="padding:20px 24px; border-bottom:1px solid #dadce0; background:#fff;">
            <span style="font-size:22px; color:#5f6368;">Google</span><span style="font-size:22px; color:#5f6368; font-weight:400;"> Finance</span>{badge}
        </div>
        <div style="padding:24px;">
            <table width="100%" style="margin-bottom:24px;">
                <tr>
                    <td style="border:1px solid #dadce0; border-radius:8px; padding:16px; width:48%;">
                        <div style="color:#70757a; font-size:11px; margin-bottom:4px; text-transform:uppercase;">Volatility (VIX)</div>
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
                        <th align="left" style="padding-bottom:8px;">Security</th><th align="right">Price</th>
                        <th align="right">RSI</th><th align="right">Mult.</th><th align="right">Amount</th>
                    </tr>
                </thead>
                <tbody>{rows_html}</tbody>
            </table>
            <div style="background:#f8f9fa; border-radius:8px; padding:24px; border:1px solid #eee;">
                <div style="font-size:15px; color:#202124; font-weight:500; margin-bottom:12px; display:flex; align-items:center;">
                    <span style="color:#1a73e8; margin-right:8px;">✦</span> 战略分析与执行建议
                </div>
                <ul style="margin:0; padding-left:20px; font-size:14px; color:#3c4043; line-height:1.8;">{advice_body}</ul>
            </div>
        </div>
        <div style="background:#f1f3f4; padding:16px 24px; text-align:center; color:#70757a; font-size:11px;">
            哨兵系统 v4.0 (Gemini Powered) · {datetime.now().strftime('%Y-%m-%d %H:%M')}
        </div>
    </div>"""
    
    msg = MIMEMultipart()
    msg['Subject'] = Header(title, 'utf-8')
    msg['From'] = formataddr((str(Header('Sentinel Intelligence', 'utf-8')), mail_user))
    msg['To'] = receiver
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    
    try:
        with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=15) as smtp:
            smtp.login(mail_user, mail_pass)
            smtp.sendmail(mail_user, [receiver], msg.as_string())
    except Exception as e: print(f"邮件错误: {e}")

# --- 4. 运行引擎 ---
def main():
    if not os.path.exists("assets.json"): return
    with open("assets.json", 'r', encoding='utf-8') as f:
        assets = json.load(f)
    
    ctx = get_market_context()
    results, total_all, fallbacks, alerts_triggered = [], 0, [], False
    
    for name, info in assets.items():
        try:
            data = yf.download(info['ticker'], period="2y", progress=False)
            close = data['Close'].iloc[:, 0] if isinstance(data['Close'], pd.DataFrame) else data['Close']
            curr_p = float(close.iloc[-1])
            ma = [close.rolling(w).mean().iloc[-1] for w in [20, 60, 120, 250]]
            m = 0.6
            if curr_p < ma[0]: m += 0.2
            if curr_p < ma[1]: m += 0.3
            if curr_p < ma[2]: m += 0.4
            if curr_p < ma[3]: m += 0.5
            rsi = round(calculate_rsi(close), 1)
            if rsi < 35: m += 0.3
            if rsi > 65: m -= 0.3
            if ctx['VIX'] > 25: m += 0.2
            m = round(max(0.4, min(m, 3.5)), 2)
            rmb = round(info['base_amount'] * m, 2)
            results.append({"name": name, "p": round(curr_p, 2), "rsi": rsi, "m": m, "rmb": rmb})
            total_all += rmb
            if m >= 1.3 or m <= 0.6 or rsi <= 35 or rsi >= 65: alerts_triggered = True
        except: continue

    if results:
        df = pd.DataFrame(results); df['日期'] = datetime.now().strftime("%Y-%m-%d")
        df.to_csv("global_investment_log.csv", mode='a', index=False, header=not os.path.exists("global_investment_log.csv"), encoding='utf-8-sig')
        if alerts_triggered:
            ai_advice = get_ai_advice(round(ctx['VIX'], 1), round(total_all, 2), results)
            send_report(f"Strategic Report: {datetime.now().strftime('%m/%d')}", total_all, results, round(ctx['VIX'], 1), ai_advice, ["发现调仓信号，建议执行。"])

if __name__ == "__main__":
    main()