# Algo-Trading
Fully automated intraday bullish swing option buying strategy for NIFTY using SmartAPI (Angel One) with Greeks-based stop loss, CE strike selection, and live order execution.

#  Algo Trading – Bullish Swing Option Buying Strategy

This project implements a **fully automated intraday bullish swing trading strategy** using live market data from **Angel One SmartAPI**. It detects swing patterns and places **Call Option (CE)** orders automatically when a breakout is confirmed.

---

## Strategy Overview

The strategy identifies a bullish price structure using swing highs/lows:
- Detects key points: `L1`, `H1`, `A`, `B`, `C`, and `D`
- Executes a **CE Buy** at breakout above `D`
- Sets stop loss below `C`, with a **1:2 risk-reward ratio**
- Selects the most optimal CE option using **Greeks** (Δ, Γ, Θ, Vega, IV)

---

## ⚙ Features

-  Real-time structure detection and entry signal
-  Option chain filtering with Greeks (Delta, Theta, IV, etc.)
-  Auto stop-loss calculation using Greeks + price risk
-  Automatic order placement via SmartAPI
-  Saves all order & options data in CSV logs
-  Rate-limit-safe, retries, and background threads for status checks
-  Local storage of:
  - `order_history/`
  - `options_data/`

---

## 🛠️ Tech Stack

| Component        | Tech/Library             |
|------------------|--------------------------|
| Broker API       | Angel One `SmartAPI`     |
| Auth             | `pyotp` for TOTP         |
| Data Processing  | `pandas`, `numpy`        |
| Visualization    | `matplotlib`, `mplfinance` |
| Logging          | `logzero`                |
| Timezone / Time  | `pytz`, `datetime`       |

---

## 🖥️ Project Structure

```bash
algotradingabhishek/
│
├── brokers/             # Broker connection modules
├── config/              # Config & secrets
├── data/                # Market data handling
├── models/              # ML models or indicators (optional)
├── strategies/          # Trading strategies like bullish3t.py
├── utils/               # Helper functions
├── main.py              # Entry point (can be auto-run on boot)
└── README.md            # You're reading it!
