import yfinance as yf
import pandas as pd
import os
import json
import smtplib
import time
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
from datetime import datetime

# --- 1. 定投量化算法 ---
def calculate_rsi(prices, period=14):
    try:
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return round(rsi.iloc[-1], 1)
    except: return 50.0

def get_market_context():
    ctx = {"VIX": 18}
    try:
        vix_data = yf.download("^VIX", period="5d", progress=False)
        if not vix_data.empty:
            p = vix_data['Close']
            ctx["VIX"] = float(p.iloc[-1, 0] if isinstance(p, pd.DataFrame) else p.iloc[-1])
    except: pass
    return ctx

# --- 2. 智谱 AI 战略模块 (修复超时与重试逻辑) ---
def get_ai_advice(vix, total_amt, results):
    api_key = os.getenv('ZHIPU_API_KEY')
    if not api_key: 
        print("❌ 错误：未发现 ZHIPU_API_KEY 环境变量")
        return None
    
    url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    
    summary = f"VIX: {vix}, 今日建议投入: {total_amt} RMB。\n资产配置："
    for r in results:
        summary += f" {r['name']}({r['m']}倍);"
    
    payload = {
        "model": "glm-4-flash",
        "messages": [
            {"role": "system", "content": "你是一位专注于全球配置的资深策略师。请为行政官员提供3条简明、稳重的执行建议，仅使用<li>标签。"},
            {"role": "user", "content": f"分析并建议：{summary}"}
        ],
        "temperature": 0.2
    }

    # 针对跨海网络波动的重试机制
    for attempt in range(5):
        try:
            print(f"📡 正在尝试连接 AI 决策引擎 (第 {attempt+1}/5 次)...")
            # 延长 timeout 以应对 Read timed out 问题 
            response = requests.post(url, headers=headers, json=payload, timeout=(15, 100))
            response.raise_for_status()
            res_data = response.json()
            print("✅ AI 建议生成成功。")
            return res_data['choices'][0]['message']['content']
        except Exception as e:
            print(f"⚠️ 信号干扰 (Attempt {attempt+1}): {e}")
            if attempt < 4:
                wait_time = (attempt + 1) * 10
                print(f"⌛ 正在原地待命，{wait_time}秒后重新呼叫...")
                time.sleep(wait_time)
            else:
                print("❌ 跨海链路严重受阻，已达到最大重试次数。")
    return None

# --- 3. Google Finance 风格模板 ---
def send_report(title, total_rmb, results, vix, ai_advice):
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

    html = f"""
    <div style="font-family:'Roboto',Arial,sans-serif; max-width:650px; margin:auto; border:1px solid #dadce0; border-radius:8px; overflow:hidden; background:#fff;">
        <div style="padding:20px 24px; border-bottom:1px solid #dadce0;">
            <span style="font-size:22px; color:#5f6368;">Google</span><span style="font-size:22px; color:#5f6368; font-weight:400;"> Finance</span>
            <span style="background:#e8f0fe; color:#1a73e8; padding:2px 8px; border-radius:12px; font-size:10px; margin-left:10px; font-weight:600;">PRO SENTINEL 5.6</span>
        </div>
        <div style="padding:24px;">
            <table width="100%" style="margin-bottom:24px;">
                <tr>
                    <td style="border:1px solid #dadce0; border-radius:8px; padding:16px; width:48%;">
                        <div style="color:#70757a; font-size:11px; margin-bottom:4px; text-transform:uppercase;">Market VIX</div>
                        <div style="font-size:28px; color:#202124;">{vix}</div>
                    </td>
                    <td width="4%"></td>
                    <td style="border:1px solid #dadce0; border-radius:8px; padding:16px; width:48%;">
                        <div style="color:#70757a; font-size:11px; margin-bottom:4px; text-transform:uppercase;">Daily Allocation (RMB)</div>
                        <div style="font-size:28px; color:#1a73e8; font-weight:500;">¥ {total_rmb:,.2f}</div>
                    </td>
                </tr>
            </table>
            <table width="100%" style="border-collapse:collapse; margin-bottom:30px; font-size:13px;">
                <thead>
                    <tr style="border-bottom: 1px solid #dadce0; color:#70757a; text-transform:uppercase;">
                        <th align="left">Asset</th><th align="right">Price</th><th align="right">RSI</th><th align="right">Mult.</th><th align="right">Amount</th>
                    </tr>
                </thead>
                <tbody>{rows_html}</tbody>
            </table>
            <div style="background:#f8f9fa; border-radius:8px; padding:24px; border:1px solid #eee;">
                <div style="font-size:15px; color:#202124; font-weight:500; margin-bottom:12px; display:flex; align-items:center;">
                    <span style="color:#1a73e8; font-weight:bold; margin-right:8px;">✦</span> 战略执行决策建议 (智谱 AI)
                </div>
                <ul style="margin:0; padding-left:20px; font-size:14px; color:#3c4043; line-height:1.8;">{ai_advice if ai_advice else '<li>内参引擎同步中，请先参考量化倍数执行。</li>'}</ul>
            </div>
        </div>
        <div style="background:#f1f3f4; padding:16px 24px; text-align:center; color:#70757a; font-size:11px;">
            Sentinel Pro 5.6 (Region: East US) · {datetime.now().strftime('%Y-%m-%d %H:%M')}
        </div>
    </div>"""
    
    msg = MIMEMultipart(); msg['Subject'] = Header(title, 'utf-8')
    msg['From'] = formataddr((str(Header('Sentinel Pro', 'utf-8')), mail_user))
    msg['To'] = receiver; msg.attach(MIMEText(html, 'html', 'utf-8'))
    
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
            p_data = data['Close']
            prices = p_data.iloc[:, 0] if isinstance(p_data, pd.DataFrame) else p_data
            curr_p = float(prices.iloc[-1])
            ma = [prices.rolling(w).mean().iloc[-1] for w in [20, 60, 120, 250]]
            m = 0.6
            if curr_p < ma[0]: m += 0.2
            if curr_p < ma[1]: m += 0.3
            if curr_p < ma[2]: m += 0.4
            if curr_p < ma[3]: m += 0.5
            rsi_val = calculate_rsi(prices)
            if rsi_val < 35: m += 0.3
            if rsi_val > 65: m -= 0.3
            if ctx['VIX'] > 25: m += 0.2
            m = round(max(0.4, min(m, 3.5)), 2)
            rmb_amt = round(info['base_amount'] * m, 2)
            results.append({"name": name, "p": round(curr_p, 2), "rsi": rsi_val, "m": m, "rmb": rmb_amt})
            total_all += rmb_amt
        except Exception as e: # 修正此处的语法错误 
            print(f"Skip: {name} - {e}")

    if results:
        # 数据归档
        df = pd.DataFrame(results); df['日期'] = datetime.now().strftime("%Y-%m-%d")
        df.to_csv("global_investment_log.csv", mode='a', index=False, header=not os.path.exists("global_investment_log.csv"), encoding='utf-8-sig')
        
        # 呼叫 AI 幕僚
        ai_res = get_ai_advice(round(ctx['VIX'], 1), round(total_all, 2), results)
        send_report(f"Strategic Portfolio: {datetime.now().strftime('%m/%d')} 决策日报", total_all, results, round(ctx['VIX'], 1), ai_res)

if __name__ == "__main__":
    main()