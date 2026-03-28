#!/usr/bin/env python3
"""
Daily Stock Briefing Email
Sends a morning market briefing: overnight summary, futures, portfolio recap,
and a news summary of events that moved the markets.
Skips Sundays and US federal holidays.
On Saturdays, sends a weekly recap instead of a daily briefing.
"""

import os
import sys
import smtplib
import json
import urllib.request
import urllib.parse
import ssl
import re
from datetime import datetime, date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import unescape

# ─── Load .env ────────────────────────────────────────────────────────────────
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

# ─── CONFIG ───────────────────────────────────────────────────────────────────
RECIPIENTS    = os.environ.get("MAIL_RECIPIENT", "").split(",")
SENDER_EMAIL  = os.environ.get("SMTP_USER", "")
SENDER_NAME   = "Daily Stock Briefing"
SMTP_HOST     = os.environ.get("SMTP_HOST", "smtp.mail.me.com")
SMTP_PORT     = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER     = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")

PORTFOLIO = ["XLI", "AEXA", "GOOGL", "QBTS", "PLTR", "TSLA", "NVDA", "UNH", "CRWD", "AMZN", "MSFT", "ZS", "DELL"]

FUTURES_TICKERS = {
    "S&P 500 Futures":  "ES=F",
    "Nasdaq Futures":   "NQ=F",
    "Dow Futures":      "YM=F",
    "Russell 2000":     "RTY=F",
    "Crude Oil (WTI)":  "CL=F",
    "Gold":             "GC=F",
    "10-Yr Treasury":   "ZN=F",
    "VIX":              "^VIX",
}

INDEX_TICKERS = {
    "S&P 500":  "^GSPC",
    "Nasdaq":   "^IXIC",
    "Dow":      "^DJI",
    "Russell":  "^RUT",
}

# ─── HOLIDAYS ─────────────────────────────────────────────────────────────────
def get_us_holidays(year):
    holidays = set()
    holidays.add(date(year, 1, 1))
    holidays.add(_nth_weekday(year, 1, 0, 3))
    holidays.add(_nth_weekday(year, 2, 0, 3))
    holidays.add(_last_weekday(year, 5, 0))
    holidays.add(date(year, 6, 19))
    holidays.add(date(year, 7, 4))
    holidays.add(_nth_weekday(year, 9, 0, 1))
    holidays.add(_nth_weekday(year, 11, 3, 4))
    holidays.add(date(year, 12, 25))
    return holidays

def _nth_weekday(year, month, weekday, n):
    d = date(year, month, 1)
    count = 0
    while True:
        if d.weekday() == weekday:
            count += 1
            if count == n:
                return d
        d += timedelta(days=1)

def _last_weekday(year, month, weekday):
    if month == 12:
        d = date(year + 1, 1, 1)
    else:
        d = date(year, month + 1, 1)
    d -= timedelta(days=1)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d

# ─── DATA FETCHING ────────────────────────────────────────────────────────────
def get_quote(ticker):
    """Return (price, change_pct, prev_close, name) for a ticker."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}"
        f"?interval=1d&range=2d"
    )
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
            data = json.loads(r.read().decode())
        result = data["chart"]["result"][0]
        meta   = result["meta"]
        price  = meta.get("regularMarketPrice") or meta.get("previousClose")
        prev   = meta.get("chartPreviousClose") or meta.get("previousClose")
        name   = meta.get("shortName") or meta.get("symbol") or ticker
        change_pct = ((price - prev) / prev * 100) if prev else 0
        return price, change_pct, prev, name
    except Exception as e:
        print(f"  Warning: could not fetch {ticker}: {e}")
        return None, None, None, ticker

def get_weekly_data(ticker):
    """Return (week_start_price, current_price, week_pct) for weekly recap."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}"
        f"?interval=1d&range=5d"
    )
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
            data = json.loads(r.read().decode())
        result = data["chart"]["result"][0]
        closes = result["indicators"]["quote"][0]["close"]
        closes = [c for c in closes if c is not None]
        if len(closes) < 2:
            return None, None, None
        week_start = closes[0]
        current    = closes[-1]
        pct = (current - week_start) / week_start * 100
        return week_start, current, pct
    except Exception as e:
        print(f"  Warning: could not fetch weekly {ticker}: {e}")
        return None, None, None

def fetch_market_news(weekly=False):
    """
    Fetch top market-moving headlines from Yahoo Finance RSS.
    Returns a list of dicts: {title, link, summary, source, pubdate}
    """
    feeds = [
        "https://finance.yahoo.com/rss/topstories",
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EGSPC&region=US&lang=en-US",
    ]
    # For weekly, also pull broader market news
    if weekly:
        feeds.append("https://finance.yahoo.com/rss/industry?ind=finance")

    items = []
    ctx = ssl.create_default_context()

    for feed_url in feeds:
        try:
            req = urllib.request.Request(feed_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
                xml = r.read().decode("utf-8", errors="replace")

            # Parse <item> blocks
            for item_match in re.finditer(r"<item>(.*?)</item>", xml, re.DOTALL):
                item_xml = item_match.group(1)

                def tag(t):
                    m = re.search(rf"<{t}[^>]*><!\[CDATA\[(.*?)\]\]></{t}>", item_xml, re.DOTALL)
                    if m:
                        return m.group(1).strip()
                    m = re.search(rf"<{t}[^>]*>(.*?)</{t}>", item_xml, re.DOTALL)
                    return unescape(m.group(1).strip()) if m else ""

                title   = tag("title")
                link    = tag("link")
                summary = tag("description")
                source  = tag("source") or "Yahoo Finance"
                pubdate = tag("pubDate")

                # Clean summary — strip HTML tags
                summary = re.sub(r"<[^>]+>", "", summary)
                summary = re.sub(r"\s+", " ", summary).strip()
                # Truncate summary
                if len(summary) > 220:
                    summary = summary[:220].rsplit(" ", 1)[0] + "…"

                # Skip any article mentioning Jim Cramer
                if re.search(r"jim cramer", title + summary, re.IGNORECASE):
                    continue

                if title and title not in [i["title"] for i in items]:
                    items.append({
                        "title":   title,
                        "link":    link,
                        "summary": summary,
                        "source":  source,
                        "pubdate": pubdate,
                    })

        except Exception as e:
            print(f"  Warning: could not fetch news feed {feed_url}: {e}")

    # Return up to 10 items for weekly, 7 for daily
    limit = 10 if weekly else 7
    return items[:limit]

# ─── FORMATTING HELPERS ───────────────────────────────────────────────────────
def arrow(pct):
    if pct is None: return "–"
    return "▲" if pct >= 0 else "▼"

def fmt_pct(pct):
    if pct is None: return "N/A"
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.2f}%"

def color(pct):
    if pct is None: return "#888"
    return "#1a7a1a" if pct >= 0 else "#b22222"

def pct_cell(pct):
    c = color(pct)
    return f"<span style='color:{c};font-weight:bold'>{arrow(pct)} {fmt_pct(pct)}</span>"

# ─── DAILY BRIEFING ───────────────────────────────────────────────────────────
def build_daily_briefing(today):
    print("Fetching futures...")
    futures_rows = []
    for name, ticker in FUTURES_TICKERS.items():
        price, pct, prev, _ = get_quote(ticker)
        futures_rows.append((name, ticker, price, pct))

    print("Fetching index data...")
    index_rows = []
    for name, ticker in INDEX_TICKERS.items():
        price, pct, prev, _ = get_quote(ticker)
        index_rows.append((name, ticker, price, pct))

    print("Fetching portfolio...")
    portfolio_rows = []
    for ticker in PORTFOLIO:
        price, pct, prev, name = get_quote(ticker)
        portfolio_rows.append((ticker, name, price, pct))

    print("Fetching market news...")
    news_items = fetch_market_news(weekly=False)

    # Market open direction from S&P futures
    sp_pct = futures_rows[0][3] if futures_rows else None
    if sp_pct is not None:
        if sp_pct > 0.5:
            market_open = f"pointing HIGHER — S&P 500 futures up {fmt_pct(sp_pct)}"
            open_color  = "#1a7a1a"
        elif sp_pct < -0.5:
            market_open = f"pointing LOWER — S&P 500 futures down {fmt_pct(sp_pct)}"
            open_color  = "#b22222"
        else:
            market_open = f"relatively FLAT — S&P 500 futures {fmt_pct(sp_pct)}"
            open_color  = "#888"
    else:
        market_open = "data unavailable"
        open_color  = "#888"

    day_str = today.strftime("%A, %B %-d, %Y")
    subject = f"📈 Daily Stock Briefing — {day_str}"

    # ── PLAIN TEXT ────────────────────────────────────────────────────────────
    lines = []
    lines.append("=" * 65)
    lines.append("DAILY STOCK BRIEFING")
    lines.append(day_str)
    lines.append("=" * 65)
    lines.append("")
    lines.append(f"MARKET OPEN: {market_open.upper()}")
    lines.append("")

    lines.append("── WHAT'S MOVING THE MARKET ──")
    if news_items:
        for i, item in enumerate(news_items, 1):
            lines.append(f"  {i}. {item['title']}")
            if item["summary"]:
                lines.append(f"     {item['summary']}")
            lines.append("")
    else:
        lines.append("  No headlines available at this time.")
        lines.append("")

    lines.append("── FUTURES & KEY INDICATORS ──")
    for name, ticker, price, pct in futures_rows:
        p_str = f"${price:,.2f}" if price else "N/A"
        lines.append(f"  {name:<22} {p_str:>10}   {arrow(pct)} {fmt_pct(pct)}")
    lines.append("")

    lines.append("── MAJOR INDEXES (PRIOR CLOSE) ──")
    for name, ticker, price, pct in index_rows:
        p_str = f"{price:,.2f}" if price else "N/A"
        lines.append(f"  {name:<22} {p_str:>10}   {arrow(pct)} {fmt_pct(pct)}")
    lines.append("")

    lines.append("── YOUR PORTFOLIO ──")
    for ticker, name, price, pct in portfolio_rows:
        p_str = f"${price:,.2f}" if price else "N/A"
        lines.append(f"  {ticker:<6} {name:<28} {p_str:>9}   {arrow(pct)} {fmt_pct(pct)}")
    lines.append("")
    lines.append("─" * 65)
    lines.append("Data via Yahoo Finance. Not financial advice.")
    plain_text = "\n".join(lines)

    # ── HTML ──────────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  body{{font-family:Arial,sans-serif;max-width:700px;margin:0 auto;padding:20px;color:#222;background:#fff;}}
  h1{{font-size:22px;color:#1a3a6b;border-bottom:3px solid #1a3a6b;padding-bottom:8px;margin-bottom:4px;}}
  h2{{font-size:13px;color:#666;font-weight:normal;margin-top:0;margin-bottom:20px;}}
  h3{{font-size:15px;color:#1a3a6b;margin-top:28px;margin-bottom:6px;text-transform:uppercase;letter-spacing:.05em;}}
  table{{width:100%;border-collapse:collapse;font-size:14px;margin-bottom:10px;}}
  tr:nth-child(even){{background:#f7f7f7;}}
  th{{background:#1a3a6b;color:#fff;padding:7px 12px;text-align:left;}}
  td{{border-bottom:1px solid #eee;padding:5px 12px;}}
  .open-banner{{padding:14px 18px;border-radius:6px;font-size:16px;font-weight:bold;margin-bottom:24px;}}
  .news-item{{padding:10px 0;border-bottom:1px solid #eee;}}
  .news-title{{font-size:14px;font-weight:bold;color:#1a3a6b;text-decoration:none;}}
  .news-title:hover{{text-decoration:underline;}}
  .news-summary{{font-size:13px;color:#555;margin-top:3px;line-height:1.5;}}
  .news-source{{font-size:11px;color:#999;margin-top:2px;}}
  .footer{{font-size:11px;color:#aaa;border-top:1px solid #eee;margin-top:30px;padding-top:10px;}}
</style>
</head><body>
<h1>📈 Daily Stock Briefing</h1>
<h2>{day_str}</h2>
<div class="open-banner" style="background:{open_color}22;border-left:5px solid {open_color};color:{open_color}">
  Market open is {market_open}
</div>

<h3>What's Moving the Market</h3>
"""
    if news_items:
        for item in news_items:
            link_open  = f'<a class="news-title" href="{item["link"]}">' if item["link"] else '<span class="news-title">'
            link_close = "</a>" if item["link"] else "</span>"
            html += f"""<div class="news-item">
  {link_open}{item['title']}{link_close}
  {'<div class="news-summary">' + item['summary'] + '</div>' if item['summary'] else ''}
  <div class="news-source">{item['source']}{' &mdash; ' + item['pubdate'] if item['pubdate'] else ''}</div>
</div>
"""
    else:
        html += "<p>No headlines available at this time.</p>\n"

    html += """
<h3>Futures &amp; Key Indicators</h3>
<table>
  <tr><th>Contract</th><th style="text-align:right">Price</th><th style="text-align:right">Change</th></tr>
"""
    for name, ticker, price, pct in futures_rows:
        p_str = f"${price:,.2f}" if price else "N/A"
        html += f"  <tr><td>{name}</td><td style='text-align:right'>{p_str}</td><td style='text-align:right'>{pct_cell(pct)}</td></tr>\n"

    html += """</table>
<h3>Major Indexes (Prior Close)</h3>
<table>
  <tr><th>Index</th><th style="text-align:right">Price</th><th style="text-align:right">Change</th></tr>
"""
    for name, ticker, price, pct in index_rows:
        p_str = f"{price:,.2f}" if price else "N/A"
        html += f"  <tr><td>{name}</td><td style='text-align:right'>{p_str}</td><td style='text-align:right'>{pct_cell(pct)}</td></tr>\n"

    html += """</table>
<h3>Your Portfolio</h3>
<table>
  <tr><th>Ticker</th><th>Name</th><th style="text-align:right">Price</th><th style="text-align:right">Change</th></tr>
"""
    for ticker, name, price, pct in portfolio_rows:
        p_str = f"${price:,.2f}" if price else "N/A"
        html += f"  <tr><td><strong>{ticker}</strong></td><td>{name}</td><td style='text-align:right'>{p_str}</td><td style='text-align:right'>{pct_cell(pct)}</td></tr>\n"

    html += """</table>
<div class="footer">Data via Yahoo Finance. For informational purposes only — not financial advice.</div>
</body></html>"""

    return subject, plain_text, html

# ─── WEEKLY BRIEFING ──────────────────────────────────────────────────────────
def build_weekly_briefing(today):
    print("Fetching weekly index data...")
    index_rows = []
    for name, ticker in INDEX_TICKERS.items():
        start, current, pct = get_weekly_data(ticker)
        index_rows.append((name, ticker, current, pct))

    print("Fetching weekly portfolio data...")
    portfolio_rows = []
    for ticker in PORTFOLIO:
        start, current, pct = get_weekly_data(ticker)
        _, _, _, name = get_quote(ticker)
        portfolio_rows.append((ticker, name, current, pct))

    print("Fetching weekly market news...")
    news_items = fetch_market_news(weekly=True)

    week_end   = today
    week_start = today - timedelta(days=4)
    week_str   = f"{week_start.strftime('%B %-d')} – {week_end.strftime('%B %-d, %Y')}"
    subject    = f"📊 Weekly Stock Recap — Week of {week_str}"
    day_str    = today.strftime("%A, %B %-d, %Y")

    scored = [(t, n, p, c) for t, n, p, c in portfolio_rows if c is not None]
    best   = max(scored, key=lambda x: x[3]) if scored else None
    worst  = min(scored, key=lambda x: x[3]) if scored else None

    # ── PLAIN TEXT ────────────────────────────────────────────────────────────
    lines = []
    lines.append("=" * 65)
    lines.append("WEEKLY STOCK RECAP")
    lines.append(week_str)
    lines.append("=" * 65)
    lines.append("")
    if best:
        lines.append(f"  🏆 Best performer:  {best[0]} {fmt_pct(best[3])}")
    if worst:
        lines.append(f"  📉 Worst performer: {worst[0]} {fmt_pct(worst[3])}")
    lines.append("")

    lines.append("── WHAT MOVED THE MARKETS THIS WEEK ──")
    if news_items:
        for i, item in enumerate(news_items, 1):
            lines.append(f"  {i}. {item['title']}")
            if item["summary"]:
                lines.append(f"     {item['summary']}")
            lines.append("")
    else:
        lines.append("  No headlines available at this time.")
        lines.append("")

    lines.append("── MAJOR INDEXES (WEEK) ──")
    for name, ticker, price, pct in index_rows:
        p_str = f"{price:,.2f}" if price else "N/A"
        lines.append(f"  {name:<22} {p_str:>10}   {arrow(pct)} {fmt_pct(pct)}")
    lines.append("")

    lines.append("── YOUR PORTFOLIO (WEEK) ──")
    for ticker, name, price, pct in portfolio_rows:
        p_str = f"${price:,.2f}" if price else "N/A"
        lines.append(f"  {ticker:<6} {name:<28} {p_str:>9}   {arrow(pct)} {fmt_pct(pct)}")
    lines.append("")
    lines.append("─" * 65)
    lines.append("Data via Yahoo Finance. Not financial advice.")
    plain_text = "\n".join(lines)

    # ── HTML ──────────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
  body{{font-family:Arial,sans-serif;max-width:700px;margin:0 auto;padding:20px;color:#222;background:#fff;}}
  h1{{font-size:22px;color:#1a3a6b;border-bottom:3px solid #1a3a6b;padding-bottom:8px;margin-bottom:4px;}}
  h2{{font-size:13px;color:#666;font-weight:normal;margin-top:0;margin-bottom:20px;}}
  h3{{font-size:15px;color:#1a3a6b;margin-top:28px;margin-bottom:6px;text-transform:uppercase;letter-spacing:.05em;}}
  table{{width:100%;border-collapse:collapse;font-size:14px;margin-bottom:10px;}}
  tr:nth-child(even){{background:#f7f7f7;}}
  th{{background:#1a3a6b;color:#fff;padding:7px 12px;text-align:left;}}
  td{{border-bottom:1px solid #eee;padding:5px 12px;}}
  .highlight{{padding:14px 18px;border-radius:6px;background:#f0f4ff;border-left:5px solid #1a3a6b;margin-bottom:24px;font-size:15px;}}
  .news-item{{padding:10px 0;border-bottom:1px solid #eee;}}
  .news-title{{font-size:14px;font-weight:bold;color:#1a3a6b;text-decoration:none;}}
  .news-title:hover{{text-decoration:underline;}}
  .news-summary{{font-size:13px;color:#555;margin-top:3px;line-height:1.5;}}
  .news-source{{font-size:11px;color:#999;margin-top:2px;}}
  .footer{{font-size:11px;color:#aaa;border-top:1px solid #eee;margin-top:30px;padding-top:10px;}}
</style>
</head><body>
<h1>📊 Weekly Stock Recap</h1>
<h2>Week of {week_str}</h2>
<div class="highlight">
"""
    if best:
        html += f"  🏆 <strong>Best:</strong> {best[0]} <span style='color:{color(best[3])}'>{fmt_pct(best[3])}</span>&nbsp;&nbsp;&nbsp;"
    if worst:
        html += f"  📉 <strong>Worst:</strong> {worst[0]} <span style='color:{color(worst[3])}'>{fmt_pct(worst[3])}</span>"
    html += """
</div>

<h3>What Moved the Markets This Week</h3>
"""
    if news_items:
        for item in news_items:
            link_open  = f'<a class="news-title" href="{item["link"]}">' if item["link"] else '<span class="news-title">'
            link_close = "</a>" if item["link"] else "</span>"
            html += f"""<div class="news-item">
  {link_open}{item['title']}{link_close}
  {'<div class="news-summary">' + item['summary'] + '</div>' if item['summary'] else ''}
  <div class="news-source">{item['source']}{' &mdash; ' + item['pubdate'] if item['pubdate'] else ''}</div>
</div>
"""
    else:
        html += "<p>No headlines available at this time.</p>\n"

    html += """
<h3>Major Indexes — Weekly Performance</h3>
<table>
  <tr><th>Index</th><th style="text-align:right">Price</th><th style="text-align:right">Week Change</th></tr>
"""
    for name, ticker, price, pct in index_rows:
        p_str = f"{price:,.2f}" if price else "N/A"
        html += f"  <tr><td>{name}</td><td style='text-align:right'>{p_str}</td><td style='text-align:right'>{pct_cell(pct)}</td></tr>\n"

    html += """</table>
<h3>Your Portfolio — Weekly Performance</h3>
<table>
  <tr><th>Ticker</th><th>Name</th><th style="text-align:right">Price</th><th style="text-align:right">Week Change</th></tr>
"""
    for ticker, name, price, pct in portfolio_rows:
        p_str = f"${price:,.2f}" if price else "N/A"
        html += f"  <tr><td><strong>{ticker}</strong></td><td>{name}</td><td style='text-align:right'>{p_str}</td><td style='text-align:right'>{pct_cell(pct)}</td></tr>\n"

    html += """</table>
<div class="footer">Data via Yahoo Finance. For informational purposes only — not financial advice.</div>
</body></html>"""

    return subject, plain_text, html

# ─── EMAIL ────────────────────────────────────────────────────────────────────
def send_email(subject, plain_text, html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{SENDER_NAME} <{SENDER_EMAIL}>"
    msg["To"]      = ", ".join(RECIPIENTS)

    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_body,  "html",  "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECIPIENTS, msg.as_string())

    print(f"✅ Email sent to {RECIPIENTS}")

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    today = date.today()
    dow   = today.weekday()  # 0=Mon, 6=Sun

    if dow == 6:
        print("Sunday — skipping.")
        sys.exit(0)

    holidays = get_us_holidays(today.year)
    if today in holidays:
        print(f"Holiday ({today}) — skipping.")
        sys.exit(0)

    if dow == 5:
        print("Saturday — sending weekly recap...")
        subject, plain_text, html_body = build_weekly_briefing(today)
    else:
        print(f"Weekday — sending daily briefing for {today}...")
        subject, plain_text, html_body = build_daily_briefing(today)

    print("\n" + "=" * 65)
    print(plain_text[:2000])
    print("=" * 65 + "\n")

    send_email(subject, plain_text, html_body)

if __name__ == "__main__":
    main()
