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

# --- 1. 数据计算逻辑 (RSI & 市场背景) ---
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
        # 抓取 VIX 恐慌指数
        vix_data = yf.download("^VIX", period="5d", progress=False)
        if not vix_data.empty:
            v_close = vix_data['Close'].iloc[:, 0] if isinstance(vix_data['Close'], pd.DataFrame) else vix_data['Close']
            context["VIX"] = float(v_close.dropna().iloc[-1])
        
        # 抓取美元汇率参考
        rate_data = yf.download("USDCNY=X", period="5d", progress=False)
        if not rate_data.empty:
            r_close = rate_data['Close'].iloc[:, 0] if isinstance(rate_data['Close'], pd.DataFrame) else rate_data['Close']
            context["rates"]["USD"] = float(r_close.dropna().iloc[-1])
    except Exception as e:
        print(f"背景数据抓取微调: {e}")
    return context

# --- 2. AI 战略分析模块 (修复模型 404 问题) ---
def get_ai_strategic_advice(vix, total_amt, results):
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key: return None
    
    try:
        genai.configure(api_key=api_key)
        # 修正：使用 gemini-1.5-flash 代替已失效的 gemini-pro
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        data_summary = f"当前 VIX: {vix}, 今日建议总投入: {total_amt} RMB。\n明细数据：\n"
        for r in results:
            data_summary += f"- {r['name']}: 现价{r['p']}, 热度RSI {r['rsi']}, 定投权重{r['m']}x\n"
            
        prompt = f"""
        你是一位服务于高级行政官员的私人财富管理专家。
        基于以下量化数据，请提供一份具有深度和前瞻性的战略研判：
        
        {data_summary}
        
        要求：
        1. 语气必须稳重、简练，具有“行政内参”的风格。
        2. 分析 VIX 揭示的市场情绪与 RSI 揭示的品种热度。
        3. 直接指出当前最具性价比的布局点和需警惕的风险点。
        4. 使用 HTML 的 <li> 标签输出 3-4 条核心建议。
        """
        
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"AI 调用失败（通常为 API Key 或模型权限问题）: {e}")
        return None

# --- 3. Google Finance 风格视觉模板 ---
def send_google_style_report(title, total_rmb, results, vix, ai_advice, fallback_alerts):
    mail_user = os.getenv('EMAIL_USER')
    mail_pass = os.getenv('EMAIL_PASS')
    receiver = os.getenv('EMAIL_RECEIVER')
    if not all([mail_user, mail_pass, receiver]): return

    rows_html = ""
    for r in results:
        # 绿增红减逻辑 (Google Finance 特色)
        m_color = "#137333" if r['m'] >= 1.3 else ("#c5221f" if r['m'] <= 0.6 else "#3c4043")
        m_bg = "#e6f4ea" if r['m'] >= 1.3 else ("#fce8e6" if r['m'] <= 0.6 else "transparent")
        
        rows_html += f"""
        <tr style="border-bottom: 1px solid #dadce0;">
            <td style="padding: 16px 8px; color: #1a73e8; font-size: 14px; font-weight: 500;">{r['name']}</td>
            <td style="padding: 16px 8px; text-align: right; color: #202124;">{r['p']}</td>
            <td style="padding: 16px 8px; text-align: right; color: #70757a; font-size: 13px;">{r['rsi']}</td>
            <td style="padding: 16px 8px; text-align: right;">
                <span style="padding: 4px 8px; border-radius: 4px; background-color: {m_bg}; color: {m_color}; font-weight: 500; font-size: 13px;">
                    {r['m']}x
                </span>
            </td>
            <td style="padding: 16px 8px; text-align: right; color: #202124; font-weight: 500;">¥{r['rmb']:,}</td>
        </tr>
        """

    advice_content = ai_advice if ai_advice else "".join([f"<li>{a}</li>" for a in fallback_alerts])
    ai_tag = '<span style="background:#e8f0fe; color:#1a73e8; padding:2px 6px; border-radius:4px; font-size:10px; margin-left:8px; font-weight:bold;">AI STRATEGY</span>' if ai_advice else ''

    html_body = f"""
    <html>
    <body style="margin:0; padding:0; background-color:#ffffff; font-family:'Roboto',Arial,sans-serif;">
        <table width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width:650px; margin:auto;">
            <tr>
                <td style="padding:24px 16px; border-bottom:1px solid #dadce0;">
                    <span style="font-size:20px; color:#5f6368;">Google Finance</span>
                    <span style="font-size:20px; color:#5f6368; font-weight:400;"> Sentinel</span>
                    {ai_tag}
                </td>
            </tr>
            <tr>
                <td style="padding:24px 16px;">
                    <table width="100%">
                        <tr>
                            <td style="border:1px solid #dadce0; border-radius:8px; padding:16px; width:48%;">
                                <div style="color:#70757a; font-size:12px; margin-bottom:4px;">恐慌指数 VIX</div>
                                <div style="font-size:24px; color:#202124;">{vix}</div>
                            </td>
                            <td width="4%"></td>
                            <td style="border:1px solid #dadce0; border-radius:8px; padding:16px; width:48%;">
                                <div style="color:#70757a; font-size:12px; margin-bottom:4px;">今日预估总出资</div>
                                <div style="font-size:24px; color:#1a73e8; font-weight:500;">¥ {total_rmb:,.2f}</div>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
            <tr>
                <td style="padding:0 16px;">
                    <table width="100%" style="border-collapse:collapse;">
                        <thead>
                            <tr style="border-bottom:1px solid #dadce0; color:#70757a; font-size:12px;">
                                <th align="left" style="padding-bottom:8px;">资产名称</th>
                                <th align="right">最新价</th><th align="right">热度</th>
                                <th align="right">权重</th><th align="right">建议金额</th>
                            </tr>
                        </thead>
                        <tbody>{rows_html}</tbody>
                    </table>
                </td>
            </tr>
            <tr>
                <td style="padding:32px 16px;">
                    <div style="background-color:#f8f9fa; border-radius:8px; padding:20px;">
                        <div style="font-size:14px; color:#1a73e8; font-weight:500; margin-bottom:12px; text-transform:uppercase; letter-spacing:1px;">核心研判建议</div>
                        <ul style="margin:0; padding-left:20px; font-size:14px; color:#3c4043; line-height:1.8;">
                            {advice_content}
                        </ul>
                    </div>
                </td>
            </tr>
            <tr>
                <td style="padding:24px 16px; text-align:center; color:#9aa0a6; font-size:11px; border-top:1px solid #dadce0;">
                    AI 驱动量化哨兵系统 · {datetime.now().strftime('%Y-%m-%d %H:%M')}<br>
                    建议仅供参考，请重点关注场内 IOPV 溢价。
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
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))
    
    try:
        with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=15) as smtp:
            smtp.login(mail_user, mail_pass)
            smtp.sendmail(mail_user, [receiver], msg.as_string())
        print("✉️ AI 增强报告已投递。")
    except Exception as e: print(f"邮件失败: {e}")

# --- 4. 自动化逻辑入口 ---
def main():
    if not os.path.exists("assets.json"): return
    with open("assets.json", 'r', encoding='utf-8') as f:
        assets = json.load(f)
    
    ctx = get_market_context()
    results, total_all, fallbacks = [], 0, []
    
    for name, info in assets.items():
        try:
            data = yf.download(info['ticker'], period="2y", progress=False)
            close = data['Close'].iloc[:, 0] if isinstance(data['Close'], pd.DataFrame) else data['Close']
            curr_p = float(close.iloc[-1])
            
            # 定投倍数算法
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
            rmb = round(info['base_amount'] * m, 2)
            
            results.append({"name": name, "p": round(curr_p, 2), "rsi": rsi_val, "m": m, "rmb": rmb})
            total_all += rmb
            if m >= 1.3: fallbacks.append(f"{name} 处于显著低估区")
        except: continue

    if results:
        # 存档数据
        df = pd.DataFrame(results); df['日期'] = datetime.now().strftime("%Y-%m-%d")
        df.to_csv("global_investment_log.csv", mode='a', index=False, header=not os.path.exists("global_investment_log.csv"), encoding='utf-8-sig')
        
        # 尝试 AI 分析
        ai_res = get_ai_strategic_advice(round(ctx['VIX'], 1), round(total_all, 2), results)
        
        # 发送 Google Finance 风格邮件
        send_google_style_report(
            f"Sentinel 战略决策日报 - {datetime.now().strftime('%m/%d')}",
            total_all, results, round(ctx['VIX'], 1), ai_res, fallbacks
        )

if __name__ == "__main__":
    main()