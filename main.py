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

# --- 1. 获取恐慌指数 VIX 与 汇率 ---
def get_market_context():
    context = {"VIX": 18, "rates": {"USD": 7.25, "JPY": 0.048, "EUR": 7.8, "HKD": 0.93, "CNY": 1.0}}
    try:
        # 抓取 VIX
        vix_data = yf.download("^VIX", period="5d", progress=False)
        if not vix_data.empty:
            context["VIX"] = float(vix_data['Close'].iloc[-1])
        
        # 抓取汇率
        tickers = {"USD": "USDCNY=X", "JPY": "JPYCNY=X", "EUR": "EURCNY=X", "HKD": "HKDCNY=X"}
        for curr, t in tickers.items():
            rate_data = yf.download(t, period="5d", progress=False)
            if not rate_data.empty:
                val = rate_data['Close'].iloc[:, 0] if isinstance(rate_data['Close'], pd.DataFrame) else rate_data['Close']
                context["rates"][curr] = float(val.dropna().iloc[-1])
    except: pass
    return context

# --- 2. 核心计算引擎 (2.0 Pro) ---
def calculate_score(ticker, base_amount, context):
    try:
        data = yf.download(ticker, period="2y", progress=False)
        if data.empty: return None
        
        close = data['Close'].iloc[:, 0] if isinstance(data['Close'], pd.DataFrame) else data['Close']
        curr_p = float(close.iloc[-1])
        
        # (1) 均线维度
        ma = [close.rolling(w).mean().iloc[-1] for w in [20, 60, 120, 250]]
        ma_score = 0.6
        if curr_p < ma[0]: ma_score += 0.2
        if curr_p < ma[1]: ma_score += 0.3
        if curr_p < ma[2]: ma_score += 0.4
        if curr_p < ma[3]: ma_score += 0.5
        
        # (2) 连涨连跌维度 (Streak)
        diff = close.diff()
        streak = 0
        for i in range(len(diff)-1, 0, -1):
            if diff.iloc[i] < 0: streak -= 1
            else: break
        
        streak_score = 0
        if streak <= -3: streak_score = 0.1
        if streak <= -5: streak_score = 0.3
        if streak >= 3: streak_score = -0.1
        
        # (3) 恐慌维度 (VIX)
        vix = context["VIX"]
        vix_score = 0
        if vix > 25: vix_score = 0.2
        if vix > 35: vix_score = 0.5
        if vix < 15: vix_score = -0.1
        
        final_multiplier = round(max(0.4, min(ma_score + streak_score + vix_score, 3.0)), 2)
        
        return {
            "p": curr_p,
            "m": final_multiplier,
            "streak": streak,
            "vix": round(vix, 2)
        }
    except: return None

# --- 3. 视觉增强版邮件 (HTML) ---
def send_pro_report(title, total_rmb, results, vix):
    mail_user = os.getenv('EMAIL_USER')
    mail_pass = os.getenv('EMAIL_PASS')
    receiver = os.getenv('EMAIL_RECEIVER')
    if not all([mail_user, mail_pass, receiver]): return

    # 情绪标签
    vix_status = "市场恐慌" if vix > 25 else "情绪平稳"
    vix_color = "#e74c3c" if vix > 25 else "#27ae60"

    rows = ""
    for r in results:
        streak_desc = f"连跌{abs(r['streak'])}天" if r['streak'] < 0 else f"连涨{r['streak']}天"
        rows += f"""
        <tr style="border-bottom: 1px solid #eee;">
            <td style="padding:12px;">{r['name']}</td>
            <td style="padding:12px; text-align:center;">{r['p']}</td>
            <td style="padding:12px; text-align:center;">{streak_desc}</td>
            <td style="padding:12px; text-align:center; color:#e74c3c; font-weight:bold;">{r['m']}x</td>
            <td style="padding:12px; text-align:right; font-weight:bold;">¥{r['rmb']:,}</td>
        </tr>
        """

    html = f"""
    <div style="font-family:sans-serif; max-width:600px; margin:auto; border:1px solid #ddd; border-radius:10px; overflow:hidden;">
        <div style="background:#2c3e50; color:white; padding:20px;">
            <h2 style="margin:0;">{title}</h2>
            <p style="margin:5px 0 0; opacity:0.8;">恐慌指数 VIX: <span style="color:{vix_color}; font-weight:bold;">{vix} ({vix_status})</span></p>
        </div>
        <div style="padding:20px;">
            <div style="background:#fdf2f2; border-left:5px solid #e74c3c; padding:15px; margin-bottom:20px;">
                <span style="font-size:14px; color:#666;">建议总投入 (RMB)</span><br>
                <span style="font-size:28px; color:#e74c3c; font-weight:bold;">¥ {total_rmb:,.2f}</span>
            </div>
            <table width="100%" style="border-collapse:collapse; font-size:14px;">
                <tr style="background:#f8f9fa;">
                    <th style="padding:10px; text-align:left;">资产</th>
                    <th style="padding:10px;">现价</th>
                    <th style="padding:10px;">动能</th>
                    <th style="padding:10px;">倍数</th>
                    <th style="padding:10px; text-align:right;">金额</th>
                </tr>
                {rows}
            </table>
        </div>
        <div style="background:#f9f9f9; padding:15px; text-align:center; font-size:12px; color:#999;">
            模型指令：三维量化策略 (均线+动能+情绪)
        </div>
    </div>
    """
    
    msg = MIMEMultipart()
    msg['Subject'] = Header(title, 'utf-8')
    msg['From'] = formataddr((str(Header('量化交易终端 Pro', 'utf-8')), mail_user))
    msg['To'] = receiver
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    
    try:
        with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=15) as smtp:
            smtp.login(mail_user, mail_pass)
            smtp.sendmail(mail_user, [receiver], msg.as_string())
        print("✉️ Pro版报告发送成功！")
    except Exception as e: print(f"邮件失败: {e}")

def run():
    with open("assets.json", 'r', encoding='utf-8') as f:
        assets = json.load(f)
    context = get_market_context()
    final_results, total_all = [], 0
    
    for name, info in assets.items():
        res = calculate_score(info['ticker'], info['base_amount'], context)
        if res:
            rmb = round(info['base_amount'] * res['m'] * context['rates'].get(info['currency'], 1.0), 2)
            final_results.append({"name": name, "p": res['p'], "streak": res['streak'], "m": res['m'], "rmb": rmb})
            total_all += rmb
            
    if final_results:
        send_pro_report(f"全球量化定投决策 - Pro版 ({datetime.now().strftime('%m/%d')})", total_all, final_results, context['VIX'])

if __name__ == "__main__":
    run()