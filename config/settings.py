"""
Configuration settings for the AlgoTrading application.
This module contains API keys, credentials, and other configuration settings.
"""
import os
from pathlib import Path


API_KEY = ''
USERNAME = ''
PASSWORD = ''
TOTP_KEY = ''


SPOT_TOKEN = "99926000"


BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = os.path.join(BASE_DIR, 'data')
ORDER_HISTORY_DIR = os.path.join(DATA_DIR, 'order_history')
OPTIONS_DATA_DIR = os.path.join(DATA_DIR, 'options_data')
RAW_TICKS_DIR = os.path.join(DATA_DIR, 'raw_ticks')


os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(ORDER_HISTORY_DIR, exist_ok=True)
os.makedirs(OPTIONS_DATA_DIR, exist_ok=True)
os.makedirs(RAW_TICKS_DIR, exist_ok=True)


DEFAULT_LOT_SIZE = 75
TARGET_RISK_MIN = 800
TARGET_RISK_MAX = 900
TARGET_RISK_MID = 850
MAX_SIGNAL_ATTEMPTS = 1  


MAX_REQUESTS_PER_MINUTE = 500
MAX_REQUESTS_PER_SECOND = 20
MIN_REQUEST_INTERVAL_MS = 50  


GREEKS_REFRESH_INTERVAL = 10  
DAILY_GREEKS_LIMIT = 3000
MINUTE_GREEKS_LIMIT = 180
EXPIRY_GREEKS_LIMIT = 90  

LOG_LEVEL = "INFO" 
LOG_FILE = os.path.join(BASE_DIR, 'trading.log')
