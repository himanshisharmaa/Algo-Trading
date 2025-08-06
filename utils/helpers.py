"""
Helper utilities for the AlgoTrading application.
"""
import os
import json
import re
import requests
from datetime import datetime, timedelta
import pytz
from ..utils.logger import logger

def get_today_date_range():
    """
    Get today's date range for historical data fetching.
    
    Returns:
        tuple: (from_date, to_date, current_time) in format "YYYY-MM-DD HH:MM"
    """
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    today_str = now.strftime('%Y-%m-%d')  # Format: YYYY-MM-DD

    # Market open time (9:15 AM IST)
    from_time = "09:15"

    # Current time
    to_time = now.strftime('%H:%M')

    from_date = f"{today_str} {from_time}"
    to_date = f"{today_str} {to_time}"

    logger.debug(f"Date range: From {from_date} to {to_date}")
    return from_date, to_date, now

def fetch_scripmaster_data():
    """
    Fetch the JSON data from AngelOne's ScripMaster API.
    
    Returns:
        list: List of instruments or None if failed
    """
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"

    try:
        logger.info("Fetching ScripMaster data...")
        response = requests.get(url)
        response.raise_for_status()  # Raise exception for HTTP errors
        data = response.json()
        logger.info(f"Successfully fetched data with {len(data)} records.")
        return data
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching data: {e}")
        return None

def get_nearest_expiry_dates(data, num_expiries=2):
    """
    Extract all available NIFTY option expiry dates and return the nearest ones.
    
    Args:
        data (list): ScripMaster data
        num_expiries (int): Number of expiry dates to return
        
    Returns:
        list: List of expiry date dictionaries
    """
    logger.info("Finding nearest expiry dates...")
    expiry_dates = set()
    today = datetime.now().date()

    # Extract all valid expiry dates for NIFTY options
    for item in data:
        try:
            if (item.get('exch_seg') == 'NFO' and
                item.get('instrumenttype') == 'OPTIDX' and
                item.get('name') == 'NIFTY'):

                expiry_raw = item.get('expiry')
                if not expiry_raw:
                    continue

                # Parse expiry date using multiple format attempts
                try:
                    # Format like "31-Dec-26"
                    expiry_date_obj = datetime.strptime(expiry_raw, '%d-%b-%y')
                except ValueError:
                    try:
                        # Format like "31DEC2026"
                        expiry_date_obj = datetime.strptime(expiry_raw, '%d%b%Y')
                    except ValueError:
                        try:
                            # Last attempt with day-month-year
                            expiry_date_obj = datetime.strptime(expiry_raw, '%d-%m-%Y')
                        except ValueError:
                            continue

                # Only include future expiry dates
                expiry_date = expiry_date_obj.date()
                if expiry_date >= today:
                    expiry_dates.add(expiry_date)
        except Exception as e:
            continue

    # Sort expiry dates and get the nearest ones
    sorted_expiry_dates = sorted(expiry_dates)
    nearest_expiries = sorted_expiry_dates[:num_expiries] if sorted_expiry_dates else []

    # Format expiry dates for display and API
    formatted_expiries = []
    for expiry_date in nearest_expiries:
        expiry_obj = datetime.combine(expiry_date, datetime.min.time())
        formatted_expiries.append({
            'date_obj': expiry_obj,
            'date': expiry_date,
            'formatted': expiry_obj.strftime('%d%b%Y').upper(),
            'display': expiry_obj.strftime('%d-%b-%Y')
        })

    if formatted_expiries:
        logger.info(f"Found nearest {len(formatted_expiries)} expiry dates:")
        for i, exp in enumerate(formatted_expiries):
            logger.info(f"  {i+1}. {exp['display']} (API format: {exp['formatted']})")
    else:
        logger.info("No future expiry dates found")

    return formatted_expiries

def extract_nifty_options_data(data, expiry_dates):
    """
    Extract Nifty options data for specified expiry dates.
    
    Args:
        data (list): ScripMaster data
        expiry_dates (list): List of expiry date dictionaries
        
    Returns:
        list: List of option data dictionaries
    """
    logger.info(f"Extracting Nifty options data for {len(expiry_dates)} expiry dates...")
    nifty_options = []
    target_dates = [exp['date'] for exp in expiry_dates]

    if not data:
        return nifty_options

    required_columns = ['token', 'symbol', 'name', 'expiry', 'strike',
                        'lotsize', 'instrumenttype', 'exch_seg', 'tick_size']

    for item in data:
        try:
            # Apply filters
            if (item.get('exch_seg') == 'NFO' and
                item.get('instrumenttype') == 'OPTIDX' and
                item.get('name') == 'NIFTY'):

                # Extract only required columns
                filtered_item = {col: item.get(col) for col in required_columns if col in item}

                # Extract option type (CE/PE) from symbol
                if 'symbol' in filtered_item:
                    match = re.search(r'(CE|PE)$', filtered_item['symbol'])
                    filtered_item['option_type'] = match.group(1) if match else None

                # Format expiry date - handle different possible formats
                if 'expiry' in filtered_item:
                    expiry_raw = filtered_item['expiry']
                    try:
                        # Try different date formats (for ScripMaster data)
                        try:
                            # Format like "31-Dec-26"
                            expiry_date_obj = datetime.strptime(expiry_raw, '%d-%b-%y')
                        except ValueError:
                            try:
                                # Format like "31DEC2026"
                                expiry_date_obj = datetime.strptime(expiry_raw, '%d%b%Y')
                            except ValueError:
                                # Last attempt with day-month-year
                                expiry_date_obj = datetime.strptime(expiry_raw, '%d-%m-%Y')

                        # Add formatted versions - all formats needed
                        expiry_date = expiry_date_obj.date()
                        filtered_item['expiry_date'] = expiry_date
                        filtered_item['expiry_formatted'] = expiry_date_obj.strftime('%d%b%Y').upper()
                        filtered_item['expiry_smartapi'] = expiry_date_obj.strftime('%d%b%Y').upper()

                        # Filter by target dates
                        if expiry_date not in target_dates:
                            continue

                    except Exception as e:
                        filtered_item['expiry_date'] = None
                        filtered_item['expiry_formatted'] = None
                        filtered_item['expiry_smartapi'] = None
                        logger.error(f"Error formatting expiry date '{expiry_raw}': {e}")
                        continue  # Skip if we can't parse the date correctly

                # Process strike price
                if 'strike' in filtered_item and filtered_item.get('option_type'):
                    try:
                        # Format strike price consistently - handle paise conversion
                        strike_val = float(filtered_item['strike'])

                        # Check if strike needs conversion from paise to rupees
                        # Typical NIFTY strikes are 4-5 digits (e.g. 20000, 25000)
                        # If it's much larger, it's likely in paise
                        if strike_val > 100000:  # Threshold to detect paise format
                            # Convert from paise to rupees
                            strike_val_rupees = strike_val / 100
                            filtered_item['strike_float'] = strike_val_rupees
                            filtered_item['original_strike'] = strike_val  # Keep original for reference
                        else:
                            filtered_item['strike_float'] = strike_val

                        # Format match key with corrected strike
                        filtered_item['match_key'] = f"NIFTY_{filtered_item['expiry_smartapi']}_{filtered_item['strike_float']:.2f}_{filtered_item['option_type']}"

                    except (ValueError, TypeError) as e:
                        logger.error(f"Error formatting strike value: {e}")
                        continue

                nifty_options.append(filtered_item)
        except Exception as e:
            logger.error(f"Error processing item: {e}")

    # Count options per expiry for reporting
    expiry_counts = {}
    for option in nifty_options:
        exp_date = option.get('expiry_date')
        if exp_date:
            expiry_counts[exp_date] = expiry_counts.get(exp_date, 0) + 1

    logger.info(f"Found total of {len(nifty_options)} Nifty options records matching criteria.")
    for exp_date, count in sorted(expiry_counts.items()):
        logger.info(f"  - {exp_date}: {count} options")

    return nifty_options
