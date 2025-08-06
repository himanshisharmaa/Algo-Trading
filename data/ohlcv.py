"""
OHLCV (Open, High, Low, Close, Volume) data module.
Provides classes and functions for working with time series price data.
"""
import os
import pandas as pd
from datetime import datetime
from ..utils.logger import logger
from ..config import settings

class LiveOHLCVData:
    """
    Class for managing real-time OHLCV data with multiple timeframes.
    Processes tick data into candles of various timeframes.
    """
    
    def __init__(self, timeframe_minutes=1, name="default"):
        """
        Initialize LiveOHLCVData instance.
        
        Args:
            timeframe_minutes (int): Timeframe in minutes (1, 5, 15, etc.)
            name (str): Identifier for this data series
        """
        self.timeframe_minutes = timeframe_minutes
        self.name = name
        self.current_candle = None
        self.completed_candles = []
        
    def update_from_tick(self, tick):
        """
        Update candle data from a tick.
        
        Args:
            tick (dict): Tick data with timestamp and ltp (last traded price)
        """
        try:
            tick_time = tick['timestamp']
            price = tick['ltp']
            
           
            candle_start = tick_time.replace(
                minute=(tick_time.minute // self.timeframe_minutes) * self.timeframe_minutes,
                second=0,
                microsecond=0
            )
            
          
            if not self.current_candle or candle_start > self.current_candle['time']:
                if self.current_candle:
                    self.completed_candles.append(self.current_candle)
                self.current_candle = {
                    'time': candle_start,
                    'open': price,
                    'high': price,
                    'low': price,
                    'close': price,
                    'volume': 0
                }
            else:
               
                self.current_candle['high'] = max(self.current_candle['high'], price)
                self.current_candle['low'] = min(self.current_candle['low'], price)
                self.current_candle['close'] = price
                
        except Exception as e:
            logger.error(f"Error updating candle from tick: {e}")
    
    def get_latest_candles(self, count=100):
        """
        Get the latest candles, including the current one.
        
        Args:
            count (int): Maximum number of candles to return
            
        Returns:
            list: List of candle dictionaries
        """
        all_candles = self.completed_candles + [self.current_candle] if self.current_candle else self.completed_candles
        return all_candles[-count:]
    
    def get_dataframe(self):
        """
        Convert candle data to pandas DataFrame.
        
        Returns:
            pd.DataFrame: DataFrame with OHLCV data
        """
        candles = self.get_latest_candles()
        if not candles:
            return pd.DataFrame()
        
        df = pd.DataFrame(candles)
        if 'time' in df.columns:
            df = df.rename(columns={'time': 'timestamp'})
            df.set_index('timestamp', inplace=True)
        
        return df
    
    def initialize_from_historical(self, historical_df):
        """
        Initialize candle data from historical DataFrame.
        
        Args:
            historical_df (pd.DataFrame): Historical data with OHLCV columns
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if historical_df.empty:
                logger.warning(f"Empty historical data provided, not initializing {self.timeframe_minutes}min candles")
                return False
                
            # Make sure we have a copy to avoid modifying the original
            sorted_df = historical_df.sort_values('timestamp')
            
            # Convert each row to a candle dictionary
            for _, row in sorted_df.iterrows():
                candle = {
                    'time': row['timestamp'],
                    'open': row['open'],
                    'high': row['high'],
                    'low': row['low'],
                    'close': row['close'],
                    'volume': row['volume'] if 'volume' in row else 0
                }
                self.completed_candles.append(candle)
                
            logger.info(f"Initialized {len(self.completed_candles)} historical {self.timeframe_minutes}min candles for {self.name}")
            return True
        except Exception as e:
            logger.error(f"Error initializing from historical data: {e}")
            return False
    
    def export_to_csv(self, filename_prefix=None):
        """
        Export candle data to CSV file.
        
        Args:
            filename_prefix (str, optional): Prefix for the filename
            
        Returns:
            str: Path to the saved file or None if failed
        """
        try:
            df = self.get_dataframe()
            if df.empty:
                logger.warning(f"No data to export for {self.name} {self.timeframe_minutes}min")
                return None
                
            os.makedirs(settings.DATA_DIR, exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            prefix = filename_prefix or f"{self.name}_{self.timeframe_minutes}min"
            filename = os.path.join(settings.DATA_DIR, f"{prefix}_{timestamp}.csv")
            
            df_to_save = df.reset_index()
            df_to_save.to_csv(filename, index=False)
            
            logger.info(f"Successfully exported {len(df_to_save)} candles to {filename}")
            return filename
        except Exception as e:
            logger.error(f"Error exporting data to CSV: {e}")
            return None

def resample_ohlcv(df, timeframe, on='timestamp'):
    """
    Resample OHLCV data to a different timeframe.
    
    Args:
        df (pd.DataFrame): DataFrame containing OHLCV data
        timeframe (str): Pandas-compatible timeframe string (e.g., '5min', '1H')
        on (str): Column to use as timestamp
        
    Returns:
        pd.DataFrame: Resampled DataFrame
    """
    try:
        if df.empty:
            return df
            
        temp_df = df.copy()
        if on in temp_df.columns and not pd.api.types.is_datetime64_any_dtype(temp_df[on]):
            temp_df[on] = pd.to_datetime(temp_df[on])
            
        if temp_df.index.name != on and on in temp_df.columns:
            temp_df = temp_df.set_index(on)
            
        resampled = temp_df.resample(timeframe).agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()
        
        return resampled
    except Exception as e:
        logger.error(f"Error resampling OHLCV data: {e}")
        return pd.DataFrame()

def fetch_historical_data(broker, token, exchange, from_date, to_date, interval="ONE_MINUTE"):
    """
    Fetch historical OHLCV data from the broker.
    
    Args:
        broker: Broker instance
        token (str): Symbol token
        exchange (str): Exchange identifier
        from_date (str): Start date in format "YYYY-MM-DD HH:MM"
        to_date (str): End date in format "YYYY-MM-DD HH:MM"
        interval (str): Candle interval
        
    Returns:
        pd.DataFrame: DataFrame with historical data
    """
    try:
        logger.info(f"Fetching {interval} historical data for {exchange}:{token} from {from_date} to {to_date}")
        
        if not broker or not hasattr(broker, 'api'):
            logger.error("Broker not connected or invalid")
            return pd.DataFrame()
            
        params = {
            "exchange": exchange,
            "symboltoken": token,
            "interval": interval,
            "fromdate": from_date,
            "todate": to_date
        }
        
        hist_data = broker.api.getCandleData(params)
        
        if isinstance(hist_data, dict):
            if not hist_data.get('status'):
                error_msg = hist_data.get('message', 'Unknown error')
                logger.error(f"API error: {error_msg}")
                return pd.DataFrame()
                
            data = hist_data.get('data', [])
            if not isinstance(data, list):
                logger.error("Invalid data format in response")
                return pd.DataFrame()
                
            if data:
                df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                try:
                    df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
                    df = df.dropna(subset=['timestamp'])
                    df = df.sort_values('timestamp')
                    
                    numeric_cols = ['open', 'high', 'low', 'close', 'volume']
                    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors='coerce')
                    
                    logger.info(f"Successfully fetched {len(df)} records")
                    return df
                except Exception as e:
                    logger.error(f"Error processing historical data: {e}")
                    return pd.DataFrame()
            else:
                logger.warning(f"No {interval} historical data returned for {exchange}:{token}")
                return pd.DataFrame()
        else:
            logger.error(f"Invalid response format: {type(hist_data)}")
            return pd.DataFrame()
    except Exception as e:
        logger.error(f"Exception fetching {interval} historical data: {e}")
        return pd.DataFrame()
