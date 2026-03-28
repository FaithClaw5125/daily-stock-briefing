# Daily Stock Briefing

Sends a daily pre-market stock briefing email each weekday at 5 AM, and a weekly recap every Saturday.

## Features

- **Mon–Fri:** Futures (S&P, Nasdaq, Dow, Russell, Oil, Gold, VIX, Treasuries), major index prior closes, portfolio summary, and top market-moving headlines
- **Saturday:** Weekly recap — index and portfolio performance for the week, best/worst performers, key news
- **Sunday & US holidays:** Nothing sent

## Setup

1. Install dependencies (none required beyond Python 3 stdlib + `yfinance` optional):
   ```bash
   pip3 install requests
   ```

2. Copy `.env.example` to `.env` and fill in your credentials:
   ```bash
   cp .env.example .env
   ```

3. Edit `.env`:
   ```
   MAIL_RECIPIENT=youraddress@example.com
   SMTP_USER=youraddress@icloud.com
   SMTP_PASSWORD=your-app-specific-password
   SMTP_HOST=smtp.mail.me.com
   SMTP_PORT=587
   ```

   - **iCloud:** Generate an App-Specific Password at [appleid.apple.com](https://appleid.apple.com)
   - **Gmail:** Use `smtp.gmail.com`, port `587`, and a [Gmail App Password](https://myaccount.google.com/apppasswords)
   - **Outlook:** Use `smtp-mail.outlook.com`, port `587`

4. Test it:
   ```bash
   python3 daily_stock_briefing.py
   ```

## Portfolio

Edit the `PORTFOLIO` list in `daily_stock_briefing.py` to use your own stock tickers.

## Scheduling

Run automatically each day at 5 AM using cron:
```bash
crontab -e
# Add:
0 5 * * * /usr/bin/python3 /path/to/daily_stock_briefing.py
```

## Data Source

Market data via [Yahoo Finance](https://finance.yahoo.com). For informational purposes only — not financial advice.
