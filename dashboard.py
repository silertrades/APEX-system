# =============================================================================
# APEX SYSTEM — dashboard.py
# =============================================================================
# Flask web dashboard showing live scores and signal history.
# Runs alongside the main bot on Railway.
# Access via your Railway public URL.
# Password protected via HTTP Basic Auth.
# =============================================================================

import os
import csv
import json
import threading
import time
import logging
from datetime import datetime
from flask import Flask, render_template_string, jsonify, request, Response
from functools import wraps

log = logging.getLogger("dashboard")

app = Flask(__name__)

# =============================================================================
# PASSWORD PROTECTION
# =============================================================================

DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "apex2024")
DASHBOARD_USER     = "apex"

def check_auth(username, password):
    return username == DASHBOARD_USER and password == DASHBOARD_PASSWORD

def authenticate():
    return Response(
        "Authentication required.",
        401,
        {"WWW-Authenticate": 'Basic realm="APEX Dashboard"'}
    )

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated


# =============================================================================
# SCORE CACHE
# =============================================================================
# Stores the latest scores from the bot's scan loop.
# Updated by update_scores() called from main.py every scan.

_score_cache = {}
_score_lock  = threading.Lock()
_last_update = None


def update_scores(scores: dict):
    """
    Called by main.py after every scan with the latest scores.
    scores = {
        "BTCUSDT": {
            "score": 31.0,
            "direction": "long",
            "regime": "mean_reversion",
            "tier": "none",
            "layers": {
                "L1_structure":  {"score": 2,  "max": 20, "direction": "neutral"},
                "L2_order_flow": {"score": 7,  "max": 20, "direction": "long"},
                "L3_zones":      {"score": 2,  "max": 15, "direction": "long"},
                "L4_macro":      {"score": 9,  "max": 15, "direction": "long"},
                "L5_momentum":   {"score": 4,  "max": 15, "direction": "long"},
                "L6_sentiment":  {"score": 7,  "max": 15, "direction": "long"},
            }
        },
        ...
    }
    """
    global _last_update
    with _score_lock:
        _score_cache.update(scores)
        _last_update = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")


def get_scores() -> dict:
    with _score_lock:
        return dict(_score_cache)


# =============================================================================
# SIGNAL HISTORY
# =============================================================================

CSV_PATH = "/app/signals.csv"

def get_signal_history(limit: int = 50) -> list:
    """Returns the most recent signals from the CSV."""
    if not os.path.exists(CSV_PATH):
        return []
    try:
        with open(CSV_PATH, "r") as f:
            reader  = csv.DictReader(f)
            signals = list(reader)
        # Most recent first
        signals.reverse()
        return signals[:limit]
    except Exception as e:
        log.error(f"Failed to read signals CSV: {e}")
        return []


def get_performance_stats() -> dict:
    """Returns win rate and R stats from signal history."""
    if not os.path.exists(CSV_PATH):
        return {}
    try:
        with open(CSV_PATH, "r") as f:
            reader  = csv.DictReader(f)
            signals = list(reader)

        if not signals:
            return {}

        closed  = [s for s in signals
                   if s.get("outcome") not in ["OPEN", ""]]
        open_   = [s for s in signals if s.get("outcome") == "OPEN"]
        wins    = [s for s in closed  if "TP" in s.get("outcome", "")]
        losses  = [s for s in closed  if s.get("outcome") == "SL_HIT"]
        partial = [s for s in closed  if "THEN_SL" in s.get("outcome", "")]

        win_rate = round(len(wins) / len(closed) * 100, 1) if closed else 0

        avg_r = 0.0
        if closed:
            r_vals = []
            for s in closed:
                try:
                    r_vals.append(float(s.get("final_r", 0)))
                except (ValueError, TypeError):
                    pass
            avg_r = round(sum(r_vals) / len(r_vals), 2) if r_vals else 0.0

        # By symbol
        symbols    = list(set(s["symbol"] for s in signals if s.get("symbol")))
        by_symbol  = {}
        for sym in sorted(symbols):
            sc = [s for s in closed if s["symbol"] == sym]
            sw = [s for s in sc    if "TP" in s.get("outcome", "")]
            by_symbol[sym] = {
                "total":    len([s for s in signals if s["symbol"] == sym]),
                "closed":   len(sc),
                "wins":     len(sw),
                "win_rate": round(len(sw) / len(sc) * 100, 1) if sc else 0,
            }

        return {
            "total":      len(signals),
            "closed":     len(closed),
            "open":       len(open_),
            "wins":       len(wins),
            "losses":     len(losses),
            "partial":    len(partial),
            "win_rate":   win_rate,
            "avg_r":      avg_r,
            "by_symbol":  by_symbol,
        }

    except Exception as e:
        log.error(f"Stats calculation failed: {e}")
        return {}


# =============================================================================
# HTML TEMPLATE
# =============================================================================

TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="60">
<title>APEX Signal Dashboard — SilerTrades</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    background: #0A0E1A;
    color: #E8EAF0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 14px;
    line-height: 1.5;
  }

  /* Grid background */
  body::before {
    content: "";
    position: fixed;
    top: 0; left: 0;
    width: 100%; height: 100%;
    background-image:
      linear-gradient(#161E30 1px, transparent 1px),
      linear-gradient(90deg, #161E30 1px, transparent 1px);
    background-size: 40px 40px;
    pointer-events: none;
    z-index: 0;
  }

  .container {
    max-width: 1400px;
    margin: 0 auto;
    padding: 0 24px 40px;
    position: relative;
    z-index: 1;
  }

  /* Top gold bar */
  .top-bar {
    height: 4px;
    background: #C9A84C;
    width: 100%;
    position: fixed;
    top: 0; left: 0;
    z-index: 100;
  }

  /* Header */
  .header {
    padding: 32px 0 24px;
    border-bottom: 1px solid #2A3550;
    margin-bottom: 32px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .header-left h1 {
    font-size: 24px;
    font-weight: 600;
    color: #C9A84C;
    letter-spacing: -0.5px;
  }

  .header-left p {
    font-size: 12px;
    color: #8A93A8;
    margin-top: 4px;
  }

  .header-right {
    text-align: right;
  }

  .last-update {
    font-size: 12px;
    color: #8A93A8;
  }

  .live-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    background: #22C55E;
    border-radius: 50%;
    margin-right: 6px;
    animation: pulse 2s infinite;
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }

  /* Section headers */
  .section-label {
    font-size: 11px;
    font-weight: 600;
    color: #C9A84C;
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-bottom: 16px;
  }

  /* Stats row */
  .stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
    margin-bottom: 40px;
  }

  .stat-card {
    background: #141B2D;
    border: 1px solid #2A3550;
    border-radius: 8px;
    padding: 16px;
  }

  .stat-label {
    font-size: 11px;
    color: #8A93A8;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .stat-value {
    font-size: 28px;
    font-weight: 600;
    color: #E8EAF0;
    margin-top: 4px;
    line-height: 1;
  }

  .stat-value.gold  { color: #C9A84C; }
  .stat-value.green { color: #22C55E; }
  .stat-value.red   { color: #EF4444; }

  /* Symbol score cards */
  .symbols-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
    gap: 16px;
    margin-bottom: 40px;
  }

  .symbol-card {
    background: #141B2D;
    border: 1px solid #2A3550;
    border-radius: 10px;
    padding: 20px;
    position: relative;
    overflow: hidden;
  }

  .symbol-card::before {
    content: "";
    position: absolute;
    top: 0; left: 0;
    width: 3px; height: 100%;
    background: #2A3550;
  }

  .symbol-card.long::before   { background: #22C55E; }
  .symbol-card.short::before  { background: #EF4444; }
  .symbol-card.neutral::before { background: #8A93A8; }

  .symbol-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;
  }

  .symbol-name {
    font-size: 16px;
    font-weight: 600;
    color: #E8EAF0;
  }

  .symbol-score {
    font-size: 28px;
    font-weight: 700;
    color: #C9A84C;
    line-height: 1;
  }

  .symbol-score span {
    font-size: 13px;
    font-weight: 400;
    color: #8A93A8;
  }

  .direction-badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.5px;
    text-transform: uppercase;
  }

  .direction-badge.long    { background: #0D2818; color: #22C55E; }
  .direction-badge.short   { background: #2D0F0F; color: #EF4444; }
  .direction-badge.neutral { background: #1C2333; color: #8A93A8; }

  .regime-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 10px;
    color: #8A93A8;
    background: #1C2333;
    margin-left: 8px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  /* Layer bars */
  .layers {
    margin-top: 16px;
  }

  .layer-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
  }

  .layer-label {
    font-size: 11px;
    color: #8A93A8;
    width: 28px;
    flex-shrink: 0;
  }

  .layer-bar-track {
    flex: 1;
    height: 6px;
    background: #2A3550;
    border-radius: 3px;
    overflow: hidden;
  }

  .layer-bar-fill {
    height: 100%;
    border-radius: 3px;
    transition: width 0.3s ease;
  }

  .layer-score {
    font-size: 11px;
    color: #8A93A8;
    width: 32px;
    text-align: right;
    flex-shrink: 0;
  }

  /* Signal table */
  .table-wrapper {
    background: #141B2D;
    border: 1px solid #2A3550;
    border-radius: 10px;
    overflow: hidden;
    margin-bottom: 40px;
  }

  table {
    width: 100%;
    border-collapse: collapse;
  }

  thead tr {
    background: #1C2333;
    border-bottom: 1px solid #2A3550;
  }

  th {
    padding: 12px 16px;
    font-size: 11px;
    font-weight: 600;
    color: #8A93A8;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    text-align: left;
  }

  td {
    padding: 12px 16px;
    font-size: 13px;
    color: #E8EAF0;
    border-bottom: 1px solid #1C2333;
  }

  tr:last-child td { border-bottom: none; }

  tr:hover td { background: #1C2333; }

  .outcome-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
  }

  .outcome-tp3    { background: #0A2015; color: #22C55E; }
  .outcome-tp2    { background: #0D2818; color: #4ADE80; }
  .outcome-tp1    { background: #112210; color: #86EFAC; }
  .outcome-sl     { background: #2D0F0F; color: #EF4444; }
  .outcome-partial{ background: #1C1A08; color: #C9A84C; }
  .outcome-open   { background: #0D1829; color: #60A5FA; }

  .long-text  { color: #22C55E; font-weight: 600; }
  .short-text { color: #EF4444; font-weight: 600; }

  /* By symbol stats */
  .symbol-stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px;
    margin-bottom: 40px;
  }

  .symbol-stat-card {
    background: #141B2D;
    border: 1px solid #2A3550;
    border-radius: 8px;
    padding: 16px;
  }

  .symbol-stat-name {
    font-size: 13px;
    font-weight: 600;
    color: #C9A84C;
    margin-bottom: 8px;
  }

  .symbol-stat-row {
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    color: #8A93A8;
    margin-bottom: 4px;
  }

  .symbol-stat-row span:last-child {
    color: #E8EAF0;
  }

  /* Footer */
  .footer {
    border-top: 1px solid #2A3550;
    padding-top: 20px;
    text-align: center;
    font-size: 11px;
    color: #4A5568;
  }

  .footer strong { color: #C9A84C; }

  /* No data state */
  .no-data {
    text-align: center;
    padding: 40px;
    color: #8A93A8;
    font-size: 13px;
  }

  /* Score color helpers */
  .score-high   { color: #C9A84C; }
  .score-med    { color: #60A5FA; }
  .score-low    { color: #8A93A8; }
</style>
</head>
<body>
<div class="top-bar"></div>
<div class="container">

  <!-- Header -->
  <div class="header">
    <div class="header-left">
      <h1>APEX Signal Dashboard</h1>
      <p>SilerTrades &nbsp;·&nbsp; A Division of 96 Bulls Financial Group</p>
    </div>
    <div class="header-right">
      <div class="last-update">
        <span class="live-dot"></span>
        Live &nbsp;·&nbsp; Auto-refresh 60s
      </div>
      <div class="last-update" style="margin-top:4px;">
        Last scan: {{ last_update or "Waiting for first scan..." }}
      </div>
    </div>
  </div>

  <!-- Overall Stats -->
  <div class="section-label">Overall Performance</div>
  <div class="stats-grid">
    <div class="stat-card">
      <div class="stat-label">Total Signals</div>
      <div class="stat-value gold">{{ stats.get("total", 0) }}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Open</div>
      <div class="stat-value">{{ stats.get("open", 0) }}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Win Rate</div>
      <div class="stat-value {% if stats.get('win_rate', 0) >= 50 %}green{% else %}red{% endif %}">
        {{ stats.get("win_rate", 0) }}%
      </div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Avg R</div>
      <div class="stat-value {% if stats.get('avg_r', 0) >= 0 %}green{% else %}red{% endif %}">
        {{ stats.get("avg_r", 0) }}R
      </div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Winners</div>
      <div class="stat-value green">{{ stats.get("wins", 0) }}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Losers</div>
      <div class="stat-value red">{{ stats.get("losses", 0) }}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Partial</div>
      <div class="stat-value gold">{{ stats.get("partial", 0) }}</div>
    </div>
  </div>

  <!-- Live Scores -->
  <div class="section-label">Live Scores — Scanning Every 60s</div>
  {% if scores %}
  <div class="symbols-grid">
    {% for symbol, data in scores.items() %}
    <div class="symbol-card {{ data.get('direction', 'neutral') }}">
      <div class="symbol-header">
        <div>
          <div class="symbol-name">{{ symbol.replace("USDT", "") }}</div>
          <div style="margin-top:6px;">
            <span class="direction-badge {{ data.get('direction', 'neutral') }}">
              {{ data.get("direction", "neutral").upper() }}
            </span>
            <span class="regime-badge">
              {{ data.get("regime", "—").replace("_", " ") }}
            </span>
          </div>
        </div>
        <div style="text-align:right;">
          <div class="symbol-score">
            {{ data.get("score", 0)|round|int }}<span>/100</span>
          </div>
          {% if data.get("score", 0) >= 90 %}
            <div style="font-size:11px;color:#EF4444;margin-top:4px;">🔥 MAX SIZE</div>
          {% elif data.get("score", 0) >= 80 %}
            <div style="font-size:11px;color:#C9A84C;margin-top:4px;">⚡ HIGH CONVICTION</div>
          {% elif data.get("score", 0) >= 65 %}
            <div style="font-size:11px;color:#22C55E;margin-top:4px;">✅ SIGNAL</div>
          {% else %}
            <div style="font-size:11px;color:#8A93A8;margin-top:4px;">Watching...</div>
          {% endif %}
        </div>
      </div>

      <!-- Layer bars -->
      <div class="layers">
        {% set layer_colors = {
          "L1_structure":  "#3B82F6",
          "L2_order_flow": "#22C55E",
          "L3_zones":      "#C9A84C",
          "L4_macro":      "#A855F7",
          "L5_momentum":   "#F97316",
          "L6_sentiment":  "#EF4444"
        } %}
        {% set layer_labels = {
          "L1_structure":  "L1",
          "L2_order_flow": "L2",
          "L3_zones":      "L3",
          "L4_macro":      "L4",
          "L5_momentum":   "L5",
          "L6_sentiment":  "L6"
        } %}
        {% for layer_key, layer_data in data.get("layers", {}).items() %}
        <div class="layer-row">
          <div class="layer-label">{{ layer_labels.get(layer_key, layer_key) }}</div>
          <div class="layer-bar-track">
            <div class="layer-bar-fill" style="
              width: {{ ((layer_data.score / layer_data.max) * 100)|round|int }}%;
              background: {{ layer_colors.get(layer_key, '#8A93A8') }};
            "></div>
          </div>
          <div class="layer-score">{{ layer_data.score }}/{{ layer_data.max }}</div>
        </div>
        {% endfor %}
      </div>
    </div>
    {% endfor %}
  </div>
  {% else %}
  <div class="no-data">
    Waiting for first scan to complete...
  </div>
  {% endif %}

  <!-- By Symbol Stats -->
  {% if stats.get("by_symbol") %}
  <div class="section-label">Performance by Symbol</div>
  <div class="symbol-stats-grid">
    {% for sym, s in stats.get("by_symbol", {}).items() %}
    <div class="symbol-stat-card">
      <div class="symbol-stat-name">{{ sym.replace("USDT","") }}</div>
      <div class="symbol-stat-row">
        <span>Signals</span><span>{{ s.total }}</span>
      </div>
      <div class="symbol-stat-row">
        <span>Closed</span><span>{{ s.closed }}</span>
      </div>
      <div class="symbol-stat-row">
        <span>Win rate</span>
        <span style="color: {% if s.win_rate >= 50 %}#22C55E{% else %}#EF4444{% endif %}">
          {{ s.win_rate }}%
        </span>
      </div>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  <!-- Signal History -->
  <div class="section-label">Signal History (Last 50)</div>
  {% if signals %}
  <div class="table-wrapper">
    <table>
      <thead>
        <tr>
          <th>Time</th>
          <th>Symbol</th>
          <th>Direction</th>
          <th>Score</th>
          <th>Regime</th>
          <th>Entry</th>
          <th>Stop</th>
          <th>TP1</th>
          <th>TP2</th>
          <th>TP3</th>
          <th>Outcome</th>
        </tr>
      </thead>
      <tbody>
        {% for s in signals %}
        <tr>
          <td style="color:#8A93A8;font-size:12px;">
            {{ s.get("timestamp","")[:16] }}
          </td>
          <td style="font-weight:600;">
            {{ s.get("symbol","").replace("USDT","") }}
          </td>
          <td>
            <span class="{{ s.get('direction','') }}-text">
              {{ s.get("direction","").upper() }}
            </span>
          </td>
          <td>
            <span class="
              {% if s.get('score',0)|float >= 80 %}score-high
              {% elif s.get('score',0)|float >= 65 %}score-med
              {% else %}score-low{% endif %}
            ">{{ s.get("score","") }}</span>
          </td>
          <td style="color:#8A93A8;font-size:12px;">
            {{ s.get("regime","").replace("_"," ") }}
          </td>
          <td>{{ s.get("entry","") }}</td>
          <td style="color:#EF4444;">{{ s.get("stop","") }}</td>
          <td style="color:#22C55E;">{{ s.get("tp1","") }}</td>
          <td style="color:#22C55E;">{{ s.get("tp2","") }}</td>
          <td style="color:#C9A84C;">{{ s.get("tp3","") }}</td>
          <td>
            {% set outcome = s.get("outcome","OPEN") %}
            {% if outcome == "TP3_HIT" %}
              <span class="outcome-badge outcome-tp3">TP3 ✓✓✓</span>
            {% elif outcome == "TP2_HIT" %}
              <span class="outcome-badge outcome-tp2">TP2 ✓✓</span>
            {% elif outcome == "TP2_THEN_SL" %}
              <span class="outcome-badge outcome-partial">TP2→SL</span>
            {% elif outcome == "TP1_HIT" %}
              <span class="outcome-badge outcome-tp1">TP1 ✓</span>
            {% elif outcome == "TP1_THEN_SL" %}
              <span class="outcome-badge outcome-partial">TP1→SL</span>
            {% elif outcome == "SL_HIT" %}
              <span class="outcome-badge outcome-sl">SL ✗</span>
            {% else %}
              <span class="outcome-badge outcome-open">Open</span>
            {% endif %}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% else %}
  <div class="no-data" style="background:#141B2D;border:1px solid #2A3550;border-radius:10px;">
    No signals logged yet. The bot is scanning — first signal coming soon.
  </div>
  {% endif %}

  <!-- Footer -->
  <div class="footer">
    <strong>APEX Signal System</strong> &nbsp;·&nbsp;
    SilerTrades &nbsp;·&nbsp;
    A Division of 96 Bulls Financial Group &nbsp;·&nbsp;
    For informational use only. Not financial advice.
  </div>

</div>
</body>
</html>
"""


# =============================================================================
# ROUTES
# =============================================================================

@app.route("/")
@requires_auth
def index():
    scores  = get_scores()
    signals = get_signal_history(50)
    stats   = get_performance_stats()
    return render_template_string(
        TEMPLATE,
        scores      = scores,
        signals     = signals,
        stats       = stats,
        last_update = _last_update,
    )


@app.route("/api/scores")
@requires_auth
def api_scores():
    """JSON endpoint for scores — useful for future integrations."""
    return jsonify({
        "scores":      get_scores(),
        "last_update": _last_update,
    })


@app.route("/api/signals")
@requires_auth
def api_signals():
    """JSON endpoint for signal history."""
    return jsonify(get_signal_history(50))


@app.route("/health")
def health():
    """Health check — no auth required. Used by Railway."""
    return jsonify({"status": "ok", "timestamp": str(datetime.now())})


# =============================================================================
# START DASHBOARD
# =============================================================================

def start_dashboard():
    """
    Starts the Flask dashboard in a background thread.
    Called from main.py on startup.
    Port 8080 is what Railway expects for web services.
    """
    port = int(os.getenv("PORT", 8080))
    log.info(f"Starting APEX dashboard on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
