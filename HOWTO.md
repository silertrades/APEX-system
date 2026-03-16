# APEX Bot — How To Guide
**SilerTrades · A Division of 96 Bulls Financial Group**

Quick reference for everything you need to do to maintain and use the bot.
---

## How to View Your Signal Log (signals.csv)

Every time a signal fires it gets logged automatically to a CSV file
on Railway. Here's how to access it:

1. Go to railway.app and log in
2. Click on your apex-bot project
3. Click on your service (the apex-bot box)
4. Click the **"Files"** tab in the top navigation
5. Navigate to the `/app` folder
6. Find `signals.csv` and click it to download
7. Open in Excel or Google Sheets

### What the columns mean

| Column | What it is |
|--------|-----------|
| timestamp | When the signal fired |
| symbol | Which coin (BTCUSDT, ETHUSDT etc) |
| direction | long or short |
| score | Total confluence score (0-100) |
| tier | standard / high_conviction / max_size |
| regime | trend / mean_reversion / breakout |
| entry | Suggested entry price |
| stop | Stop loss price |
| tp1 / tp2 / tp3 | Three take profit targets |
| r_pct | Stop distance as % of price |
| l1_score through l6_score | Individual layer scores |
| l1_direction through l6_direction | Each layer's direction vote |
| l1_reason through l6_reason | Top reason from each layer |
| outcome | You fill this in manually (see below) |
| outcome_price | Price when outcome was reached |
| outcome_notes | Any notes you want to add |

### How to update outcomes

After a trade resolves, open the CSV, find the row, and update
the outcome column with one of these values:

- **TP1_HIT** — price reached first target
- **TP2_HIT** — price reached second target
- **TP3_HIT** — price reached third target
- **SL_HIT** — stop loss was hit
- **MISSED** — signal fired but you didn't take the trade
- **OPEN** — trade still active (default)

---

## How to Add or Remove Symbols

1. Go to your GitHub repo
2. Click config.py
3. Click the pencil icon to edit
4. Find this line:
   `CRYPTO_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT", "XRPUSDT"]`
5. Add or remove symbols — must be Binance perpetual futures format (e.g. SOLUSDT)
6. Commit changes — Railway redeploys automatically

---

## How to Change the Score Threshold

If you're getting too many signals (lower the bar) or too few (raise it):

1. Go to config.py in GitHub
2. Find this section:
```
   SCORE_THRESHOLD_STANDARD        = 65
   SCORE_THRESHOLD_HIGH_CONVICTION = 80
   SCORE_THRESHOLD_MAX_SIZE        = 90
```
3. Adjust the numbers and commit

---

## How to Pause the Bot

1. Go to Railway dashboard
2. Click your service
3. Click **"Settings"**
4. Click **"Suspend service"**
5. To resume — same steps, click **"Resume service"**

---

## How to Put Bot in Test Mode (No Live Alerts)

1. Go to Railway dashboard
2. Click your service
3. Click **"Variables"**
4. Find DRY_RUN — if it's not there, add it
5. Set value to `True`
6. Railway redeploys — bot runs but sends no Telegram alerts
7. Set back to `False` to go live again

---

## How to Check if the Bot is Running

1. Go to Railway dashboard
2. Click your service
3. Click **"Logs"**
4. You should see a new scan line every 60 seconds:
   `--- Scan #X | 6 symbols ---`
5. If logs are frozen for more than 5 minutes something is wrong

---

## How to Read the Railway Logs

Key lines to look for:

| Log line | What it means |
|----------|--------------|
| `APEX BOT STARTING` | Bot just deployed or restarted |
| `Websocket connected` | Live order flow connected |
| `--- Scan #X ---` | New scan cycle starting |
| `Score XX below threshold` | No signal — normal |
| `SIGNAL FIRED` | Signal found — alert sending |
| `Signal logged to CSV` | Signal saved to tracking file |
| `ERROR` | Something went wrong — read the full line |

---

## How to Update the Bot Code

1. Go to your GitHub repo
2. Find the file you want to change
3. Click the pencil icon
4. Make your changes
5. Click **"Commit changes"**
6. Railway detects the change and redeploys automatically
7. You'll get a Telegram message when it's back online

---

## How to Access This Bot From Another Computer

The bot lives entirely on Railway and GitHub — nothing is on your
personal computer. From any computer or phone:

- **View logs:** railway.app → your project → Logs tab
- **Edit code:** github.com → your apex-bot repo
- **Get alerts:** Telegram (already set up on your phone)

---

## Known Issues & Roadmap

See ROADMAP.md in this repo for all known limitations
and planned upgrades.

---

## Emergency Contacts

- **Railway status:** status.railway.app
- **Binance API status:** binance.com/en/support
- **Telegram Bot issues:** t.me/BotFather → /mybots

---

*Last updated: March 15, 2026*
*SilerTrades · A Division of 96 Bulls Financial Group*
