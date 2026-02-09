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

# --- 1. 量化工具函数 ---
def calculate_rsi(prices, period=14):
    """计算 RSI 热度指数"""
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def get_market_context():
    """获取全局市场背景：VIX 与 汇率参考"""
    context = {"VIX": 18, "rates": {"USD": 7.25, "CNY": 1.0}}
    try:
        # 抓取 VIX 恐慌指数
        vix_data = yf.download("^VIX", period="5d", progress=False)
        if not vix_data.empty:
            v_close = vix_data['Close'].iloc[:, 0] if isinstance(vix_data['Close'], pd.DataFrame) else vix_data['Close']
            context["VIX"] = float(v_close.dropna().iloc[-1])
        
        # 抓取汇率（仅作参考显示用）
        rate_data = yf.download("USDCNY=X", period="5d", progress=False)
        if not rate_data.empty:
            r_close = rate_data['Close'].iloc[:, 0] if isinstance(rate_data['Close'], pd.DataFrame) else rate_data['Close']
            context["rates"]["USD"] = float(r_close.dropna().iloc[-1])
    except: pass
    return context

# --- 2. 视觉报告系统 (结构优化版) ---
def send_report(title, total_rmb, results, vix, alert_list):
    mail_user = os.getenv('EMAIL_USER')
    mail_pass = os.getenv('EMAIL_PASS')
    receiver = os.getenv('EMAIL_RECEIVER')
    if not all([mail_user, mail_pass, receiver]): return

    vix_color = "#e74c3c" if vix > 25 else "#27ae60"
    vix_desc = "市场较恐慌" if vix > 25 else "情绪较平稳"
    
    # 构造表格行
    rows_html = ""
    for r in results:
        m_color = "#e74c3c" if r['m'] >= 1.3 else ("#3498db" if r['m'] <= 0.6 else "#2c3e50")
        rows_html += f"""
        <tr style="border-bottom: 1px solid #eee; font-size: 14px;">
            <td style="padding:12px;"><b>{r['name']}</b></td>
            <td style="padding:12px; text-align:center;">{r['p']}</td>
            <td style="padding:12px; text-align:center;">{r['rsi']}</td>
            <td style="padding:12px; text-align:center; color:{m_color}; font-weight:bold;">{r['m']}x</td>
            <td style="padding:12px; text-align:right; font-weight:bold;">¥{r['rmb']:,}</td>
        </tr>
        """
    
    alert_items = "".join([f"<li style='margin-bottom:8px;'>{a}</li>" for a in alert_list])

    html_body = f"""
    <div style="font-family:'Microsoft YaHei',sans-serif; max-width:600px; margin:auto; border:1px solid #ddd; border-radius:12px; overflow:hidden; box-shadow:0 4px 15px rgba(0,0,0,0.1);">
        <div style="background:#2c3e50; color:white; padding:25px;">
            <h2 style="margin:0; font-size:20px; letter-spacing:1px;">全球资产监测分析报告</h2>
            <p style="margin:8px 0 0; opacity:0.8; font-size:13px;">
                恐慌指数 VIX: <b style="color:{vix_color};">{vix} ({vix_desc})</b> | 美元汇率参考: {os.getenv('USD_REF','7.25')}
            </p>
        </div>
        
        <div style="padding:25px; background:#fff;">
            <table width="100%" style="border-collapse:collapse; margin-bottom:25px;">
                <tr style="background:#f8f9fa; color:#7f8c8d; font-size:12px;">
                    <th style="padding:10px; text-align:left;">资产名称</th>
                    <th style="padding:10px;">最新价格</th>
                    <th style="padding:10px;">热度(RSI)</th>
                    <th style="padding:10px;">建议倍数</th>
                    <th style="padding:10px; text-align:right;">建议金额</th>
                </tr>
                {rows_html}
            </table>

            <div style="background:#fdf2f2; border-radius:8px; padding:20px; margin-bottom:25px; text-align:center; border: 1px solid #f5c6cb;">
                <span style="font-size:14px; color:#666;">今日建议出资总额 (RMB)</span><br>
                <span style="font-size:32px; color:#e74c3c; font-weight:bold;">¥ {total_rmb:,.2f}</span>
            </div>

            <div style="border-top:2px dashed #eee; padding-top:20px;">
                <h4 style="margin:0 0 12px 0; color:#2c3e50; font-size:16px;">💡 哨兵决策建议：</h4>
                <ul style="margin:0; padding-left:20px; color:#2c3e50; font-size:15px; line-height:1.6;">
                    {alert_items}
                    <li style="margin-top:15px; color:#7f8c8d; list-style:none; font-size:13px; border-top:1px solid #f5f5f5; padding-top:10px;">
                        <b>⚠️ 场内特别提醒：</b><br>
                        1. 买入前请看一眼 <b>溢价率</b>，若 >1.5% 建议分批或暂缓。<br>
                        2. 建议金额已根据您设定的 <b>人民币基数</b> 动态计算。
                    </li>
                </ul>
            </div>
        </div>
        <div style="background:#f9f9f9; padding:15px; text-align:center; font-size:11px; color:#bdc3c7;">
            策略：MA趋势+VIX情绪+RSI强弱 | 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}
        </div>
    </div>
    """
    
    msg = MIMEMultipart()
    msg['Subject'] = Header(title, 'utf-8')
    msg['From'] = formataddr((str(Header('资产管理哨兵', 'utf-8')), mail_user))
    msg['To'] = receiver
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))
    
    try:
        with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=15) as smtp:
            smtp.login(mail_user, mail_pass)
            smtp.sendmail(mail_user, [receiver], msg.as_string())
        print("✉️ 报告已成功投递。")
    except Exception as e:
        print(f"发送异常: {e}")

# --- 3. 哨兵运行引擎 ---
def main():
    if not os.path.exists("assets.json"): return
    with open("assets.json", 'r', encoding='utf-8') as f:
        assets = json.load(f)
    
    ctx = get_market_context()
    os.environ['USD_REF'] = str(round(ctx['rates']['USD'], 2))
    results, total_rmb, alert_list = [], 0, []
    
    for name, info in assets.items():
        try:
            data = yf.download(info['ticker'], period="2y", progress=False)
            if data.empty: continue
            
            close = data['Close'].iloc[:, 0] if isinstance(data['Close'], pd.DataFrame) else data['Close']
            curr_p = float(close.iloc[-1])
            
            # A. 均线维度评分
            ma = [close.rolling(w).mean().iloc[-1] for w in [20, 60, 120, 250]]
            m = 0.6
            if curr_p < ma[0]: m += 0.2
            if curr_p < ma[1]: m += 0.3
            if curr_p < ma[2]: m += 0.4
            if curr_p < ma[3]: m += 0.5
            
            # B. RSI 维度评分
            rsi_val = round(calculate_rsi(close), 1)
            if rsi_val < 35: m += 0.3
            if rsi_val > 65: m -= 0.3
            
            # C. VIX 维度评分
            if ctx['VIX'] > 25: m += 0.2
            
            # 最终倍数锁定
            m = round(max(0.4, min(m, 3.5)), 2)
            
            # --- 核心逻辑改动：直接认为 base_amount 是人民币 ---
            rmb_amt = round(info['base_amount'] * m, 2)
            
            item = {"name": name, "p": round(curr_p, 2), "rsi": rsi_val, "m": m, "rmb": rmb_amt}
            results.append(item)
            total_rmb += rmb_amt
            
            # 决策语言翻译
            if m >= 1.3 or rsi_val <= 35:
                alert_list.append(f"<b style='color:#e74c3c;'>🔥 {name}：</b>目前处于“低位捡便宜”区间，建议增加出资。")
            elif m <= 0.6 or rsi_val >= 65:
                alert_list.append(f"<b style='color:#3498db;'>⚠️ {name}：</b>目前涨势过猛，建议“歇一歇”减少出资。")
        except: continue

    if results:
        # 存档数据
        df = pd.DataFrame(results); df['日期'] = datetime.now().strftime("%Y-%m-%d")
        log_file = "global_investment_log.csv"
        df.to_csv(log_file, mode='a', index=False, header=not os.path.exists(log_file), encoding='utf-8-sig')
        
        # 哨兵触发：仅在有显著信号时发邮件
        if alert_list:
            send_report(f"交易信号预警：今日发现 {len(alert_list)} 个重要信号", total_rmb, results, round(ctx['VIX'], 1), alert_list)
        else:
            print("行情平稳，哨兵静默中。")

if __name__ == "__main__":
    main()