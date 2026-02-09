import yfinance as yf
import pandas as pd
import os
import json
import smtplib
import google.generativeai as genai
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
from datetime import datetime

# --- 1. 数据计算逻辑 ---
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

# --- 2. 【核心新增】AI 大模型分析模块 ---
def get_ai_strategic_advice(vix, total_amt, results):
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key: return None
    
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-pro')
        
        # 构造发给 AI 的数据报表
        data_summary = f"当前 VIX: {vix}, 总建议投入: {total_amt} RMB。\n详情：\n"
        for r in results:
            data_summary += f"- {r['name']}: 现价{r['p']}, RSI{r['rsi']}, 定投倍数{r['m']}x\n"
            
        prompt = f"""
        你是一位全球顶级对冲基金的首席策略师。
        请根据以下量化数据，为一位高级行政官员提供简明、高端的投资决策建议。
        
        {data_summary}
        
        要求：
        1. 语气稳重、专业。
        2. 分为“当前局势研判”和“核心操作建议”两个模块。
        3. 总字数控制在 200 字以内，使用 HTML 的 <li> 标签输出。
        """
        
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"AI 分析调用失败: {e}")
        return None

# --- 3. Google Finance 风格邮件模板 ---
def send_ai_report(title, total_rmb, results, vix, ai_advice, fallback_alerts):
    mail_user = os.getenv('EMAIL_USER')
    mail_pass = os.getenv('EMAIL_PASS')
    receiver = os.getenv('EMAIL_RECEIVER')
    if not all([mail_user, mail_pass, receiver]): return

    rows_html = ""
    for r in results:
        m_color = "#137333" if r['m'] >= 1.3 else ("#c5221f" if r['m'] <= 0.6 else "#3c4043")
        m_bg = "#e6f4ea" if r['m'] >= 1.3 else ("#fce8e6" if r['m'] <= 0.6 else "transparent")
        rows_html += f"""
        <tr style="border-bottom: 1px solid #dadce0;">
            <td style="padding: 16px 8px; color: #1a73e8; font-size: 14px; font-weight: 500;">{r['name']}</td>
            <td style="padding: 16px 8px; text-align: right; color: #202124;">{r['p']}</td>
            <td style="padding: 16px 8px; text-align: right; color: #70757a;">{r['rsi']}</td>
            <td style="padding: 16px 8px; text-align: right;">
                <span style="padding: 4px 8px; border-radius: 4px; background-color: {m_bg}; color: {m_color}; font-weight: 500;">{r['m']}x</span>
            </td>
            <td style="padding: 16px 8px; text-align: right; font-weight: 500;">¥{r['rmb']:,}</td>
        </tr>
        """

    # 优先展示 AI 建议
    advice_content = ai_advice if ai_advice else "".join([f"<li>{a}</li>" for a in fallback_alerts])
    ai_badge = '<span style="background:#e8f0fe; color:#1a73e8; padding:2px 6px; border-radius:4px; font-size:10px; margin-left:8px;">AI 驱动</span>' if ai_advice else ''

    html_body = f"""
    <div style="font-family: 'Roboto', Arial, sans-serif; max-width: 650px; margin: auto; color: #3c4043;">
        <div style="padding: 24px 16px; border-bottom: 1px solid #dadce0; font-size: 20px; color: #5f6368;">
            Google Finance <span style="font-weight: 400;">Sentinel</span> {ai_badge}
        </div>
        
        <div style="padding: 24px 16px;">
            <table width="100%">
                <tr>
                    <td style="border: 1px solid #dadce0; border-radius: 8px; padding: 16px; width: 48%;">
                        <div style="color: #70757a; font-size: 12px;">VIX 恐慌指数</div>
                        <div style="font-size: 24px; color: #202124;">{vix}</div>
                    </td>
                    <td width="4%"></td>
                    <td style="border: 1px solid #dadce0; border-radius: 8px; padding: 16px; width: 48%;">
                        <div style="color: #70757a; font-size: 12px;">今日建议总投入</div>
                        <div style="font-size: 24px; color: #1a73e8; font-weight: 500;">¥ {total_rmb:,.2f}</div>
                    </td>
                </tr>
            </table>
        </div>

        <div style="padding: 0 16px;">
            <table width="100%" style="border-collapse: collapse; font-size: 13px;">
                <thead>
                    <tr style="border-bottom: 1px solid #dadce0; color: #70757a;">
                        <th align="left" style="padding-bottom: 8px;">资产</th>
                        <th align="right">现价</th><th align="right">RSI</th>
                        <th align="right">倍数</th><th align="right">金额</th>
                    </tr>
                </thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>

        <div style="padding: 32px 16px;">
            <div style="background-color: #f8f9fa; border-radius: 8px; padding: 20px;">
                <div style="font-size: 15px; color: #1a73e8; font-weight: 500; margin-bottom: 12px;">智能智策摘要</div>
                <ul style="margin: 0; padding-left: 20px; font-size: 14px; line-height: 1.8; color: #202124;">
                    {advice_content}
                </ul>
            </div>
        </div>

        <div style="text-align: center; color: #9aa0a6; font-size: 11px; padding: 20px;">
            此报告由量化哨兵联合 Gemini Pro AI 自动生成 · {datetime.now().strftime('%Y-%m-%d %H:%M')}
        </div>
    </div>
    """
    
    msg = MIMEMultipart()
    msg['Subject'] = Header(title, 'utf-8')
    msg['From'] = formataddr((str(Header('Sentinel AI', 'utf-8')), mail_user))
    msg['To'] = receiver
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))
    
    try:
        with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=15) as smtp:
            smtp.login(mail_user, mail_pass)
            smtp.sendmail(mail_user, [receiver], msg.as_string())
        print("✉️ AI 增强版简报发送成功。")
    except Exception as e: print(f"发送异常: {e}")

# --- 4. 运行逻辑 ---
def main():
    if not os.path.exists("assets.json"): return
    with open("assets.json", 'r', encoding='utf-8') as f:
        assets = json.load(f)
    
    ctx = get_market_context()
    results, total_rmb, fallback_alerts = [], 0, []
    
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
            
            rsi_val = round(calculate_rsi(close), 1)
            if rsi_val < 35: m += 0.3
            if rsi_val > 65: m -= 0.3
            if ctx['VIX'] > 25: m += 0.2
            
            m = round(max(0.4, min(m, 3.5)), 2)
            rmb_amt = round(info['base_amount'] * m, 2)
            results.append({"name": name, "p": round(curr_p, 2), "rsi": rsi_val, "m": m, "rmb": rmb_amt})
            total_rmb += rmb_amt
            
            if m >= 1.3: fallback_alerts.append(f"{name} 触发超跌补仓信号")
        except: continue

    if results:
        # 获取 AI 分析
        ai_advice = get_ai_strategic_advice(round(ctx['VIX'], 1), round(total_rmb, 2), results)
        # 发送报告
        send_ai_report(f"Sentinel AI 战略内参 - {datetime.now().strftime('%m/%d')}", total_rmb, results, round(ctx['VIX'], 1), ai_advice, fallback_alerts)

if __name__ == "__main__":
    main()