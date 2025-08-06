"""
Main entry point for the AlgoTrading application.
"""
import os
import time
import pandas as pd
from datetime import datetime, timedelta

from .brokers.angelone import broker
from .strategies.bullish_swing import BullishSwingStrategy
from .data.ohlcv import LiveOHLCVData, fetch_historical_data
from .utils.helpers import get_today_date_range, fetch_scripmaster_data, get_nearest_expiry_dates
from .utils.logger import logger
from .config import settings

class AlgoTradingApp:
    """Main application class for AlgoTrading."""
    
    def __init__(self):
        """Initialize the application."""
        self.broker = broker
        self.spot_token = settings.SPOT_TOKEN
        self.fut_token = None
        
        
        self.spot_1min = LiveOHLCVData(timeframe_minutes=1, name="spot")
        self.spot_5min = LiveOHLCVData(timeframe_minutes=5, name="spot")
        self.spot_15min = LiveOHLCVData(timeframe_minutes=15, name="spot")
        
      
        self.spot_strategy = None
        
      
        self.websocket = None
        
       
        self.spot_ticks = []
        self.spot_ltp = 0
        self.tick_count = 0
        
       
        os.makedirs(settings.DATA_DIR, exist_ok=True)
        os.makedirs(settings.RAW_TICKS_DIR, exist_ok=True)
        
    def start(self):
        """Start the trading application."""
        logger.info("Starting AlgoTrading application")
        
       
        if not self.broker.connect():
            logger.error("Failed to connect to broker. Exiting.")
            return False
            
       
        scripmaster_data = fetch_scripmaster_data()
        if not scripmaster_data:
            logger.error("Failed to fetch scripmaster data. Exiting.")
            return False
            
        
        self.fut_token = self._get_futures_token(scripmaster_data)
        if not self.fut_token:
            logger.warning("Failed to get futures token. Continuing with spot only.")
            
       
        self._initialize_historical_data()
        
        
        self._start_websocket()
        
        
        try:
            while True:
                
                self._update_strategies()
                
               
                self._export_data()
                
                
                time.sleep(300)  
                
        except KeyboardInterrupt:
            logger.info("Stopping application...")
            self._shutdown()
            return True
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            self._shutdown()
            return False
            
    def _get_futures_token(self, data):
        """Get NIFTY futures token from scripmaster data."""
        logger.info("Finding current month NIFTY futures token...")
        today = datetime.now().date()
        available_expiries = []

       
        for item in data:
            try:
                if (item.get('exch_seg') == 'NFO' and
                    item.get('instrumenttype') == 'FUTIDX' and
                    item.get('name') == 'NIFTY'):

                    expiry_raw = item.get('expiry')
                    if not expiry_raw:
                        continue

                    
                    try:
                        expiry_date_obj = datetime.strptime(expiry_raw, '%d-%b-%y')
                    except ValueError:
                        try:
                            expiry_date_obj = datetime.strptime(expiry_raw, '%d%b%Y')
                        except ValueError:
                            try:
                                expiry_date_obj = datetime.strptime(expiry_raw, '%d-%m-%Y')
                            except ValueError:
                                continue

                    expiry_date = expiry_date_obj.date()
                    if expiry_date >= today:
                        available_expiries.append({
                            'expiry': expiry_date,
                            'token': item.get('token')
                        })

            except Exception as e:
                continue

        if not available_expiries:
            logger.error("No valid NIFTY futures expiries found")
            return None

        
        available_expiries.sort(key=lambda x: x['expiry'])

        
        if available_expiries[0]['expiry'] == today and len(available_expiries) > 1:
            selected_expiry = available_expiries[1]
            logger.info(f"Today is expiry day, using next available expiry: {selected_expiry['expiry']}")
        else:
            selected_expiry = available_expiries[0]
            logger.info(f"Using nearest expiry: {selected_expiry['expiry']}")

        logger.info(f"Found NIFTY futures token {selected_expiry['token']} for expiry {selected_expiry['expiry']}")
        return selected_expiry['token']
            
    def _initialize_historical_data(self):
        """Initialize data with historical OHLCV."""
        from_date, to_date, current_time = get_today_date_range()
        
        logger.info("Fetching historical data...")
        
        
        spot_historical = fetch_historical_data(
            self.broker, 
            self.spot_token, 
            "NSE", 
            from_date, 
            to_date
        )
        
        
        if not spot_historical.empty:
            logger.info(f"Retrieved {len(spot_historical)} historical spot records")
            
           
            self.spot_1min.initialize_from_historical(spot_historical)
            self.spot_5min.initialize_from_historical(spot_historical.copy())
            self.spot_15min.initialize_from_historical(spot_historical.copy())
            
           
            spot_df = self.spot_5min.get_dataframe()
            self.spot_strategy = BullishSwingStrategy(spot_df, self.broker)
            self.spot_strategy.generate_signals()
            
            logger.info("Initialized strategies with historical data")
        else:
            logger.warning("No historical data available")
    
    def _start_websocket(self):
        """Start websocket connection for real-time data."""
        logger.info("Starting websocket connection...")
        
       
        token_list = [
            {
                "exchangeType": 1,  
                "tokens": [self.spot_token]
            }
        ]
        
        if self.fut_token:
            token_list.append({
                "exchangeType": 2,  
                "tokens": [self.fut_token]
            })
        
        
        def on_tick_data(message):
            self._process_tick(message)
        
        
        self.websocket = self.broker.start_websocket(token_list, on_tick_data)
        
        if self.websocket:
            logger.info("Websocket connection established")
            return True
        else:
            logger.error("Failed to establish websocket connection")
            return False
    
    def _process_tick(self, tick_data):
        """Process incoming tick data."""
        try:
           
            if isinstance(tick_data, str):
                import json
                tick_data = json.loads(tick_data)
                
            if isinstance(tick_data, dict) and 'data' in tick_data:
                for item in tick_data['data']:
                    token = str(item.get('token', ''))
                    
                   
                    if token == self.spot_token:
                        price = float(item.get('last_traded_price', 0)) * 0.01 
                        
                        
                        current_time = datetime.now()
                        structured_tick = {
                            'timestamp': current_time,
                            'ltp': price,
                            'token': token
                        }
                        
                       
                        for field in ['last_traded_quantity', 'volume', 'open', 'high', 'low', 'close']:
                            if field in item and item[field] is not None:
                               
                                if field in ['open', 'high', 'low', 'close']:
                                    structured_tick[field] = float(item[field]) * 0.01
                                else:
                                    structured_tick[field] = item[field]
                        
                       
                        self.spot_ticks.append(structured_tick)
                        self.spot_ltp = price
                        self.tick_count += 1
                        
                      
                        self.spot_1min.update_from_tick(structured_tick)
                        self.spot_5min.update_from_tick(structured_tick)
                        self.spot_15min.update_from_tick(structured_tick)
                        
                       
                        self._check_breakout_signals('spot', price)
                        
        except Exception as e:
            logger.error(f"Error processing tick: {e}")
    
    def _check_breakout_signals(self, instrument, price):
        """Check for breakout signals in live ticks."""
        try:
            if instrument == 'spot' and self.spot_strategy:
               
                signal_data = self.spot_strategy.check_live_tick(price)
                
                if signal_data:
                    logger.info(f"SIGNAL ALERT: Breakout signal at price {price:.2f}")
                    
                   
                    order_id = self.spot_strategy.place_order(signal_data)
                    
                    if order_id:
                        logger.info(f"Order placed successfully with ID: {order_id}")
                    else:
                        logger.error("Failed to place order")
                        
        except Exception as e:
            logger.error(f"Error checking for breakout signals: {e}")
    
    def _update_strategies(self):
        """Update strategies with latest data."""
        try:
           
            spot_df = self.spot_5min.get_dataframe()
            
            if not spot_df.empty and self.spot_strategy:
              
                current_structure = {
                    'H1': self.spot_strategy.H1,
                    'H1_idx': self.spot_strategy.H1_idx,
                    'L1': self.spot_strategy.L1,
                    'L1_idx': self.spot_strategy.L1_idx,
                    'A': self.spot_strategy.A,
                    'A_idx': self.spot_strategy.A_idx,
                    'B': self.spot_strategy.B,
                    'B_idx': self.spot_strategy.B_idx,
                    'C': self.spot_strategy.C,
                    'C_idx': self.spot_strategy.C_idx,
                    'D': self.spot_strategy.D,
                    'D_idx': self.spot_strategy.D_idx,
                    'pending_setup': self.spot_strategy.pending_setup
                }
                
               
                self.spot_strategy = BullishSwingStrategy(spot_df, self.broker)
                
               
                if current_structure['pending_setup']:
                    self.spot_strategy.H1 = current_structure['H1']
                    self.spot_strategy.H1_idx = current_structure['H1_idx']
                    self.spot_strategy.L1 = current_structure['L1']
                    self.spot_strategy.L1_idx = current_structure['L1_idx']
                    self.spot_strategy.A = current_structure['A']
                    self.spot_strategy.A_idx = current_structure['A_idx']
                    self.spot_strategy.B = current_structure['B']
                    self.spot_strategy.B_idx = current_structure['B_idx']
                    self.spot_strategy.C = current_structure['C']
                    self.spot_strategy.C_idx = current_structure['C_idx']
                    self.spot_strategy.D = current_structure['D']
                    self.spot_strategy.D_idx = current_structure['D_idx']
                    self.spot_strategy.pending_setup = current_structure['pending_setup']
                
             
                self.spot_strategy.generate_signals()
                logger.info("Updated strategies with latest data")
                
              
                self.spot_strategy.print_current_structure()
                
        except Exception as e:
            logger.error(f"Error updating strategies: {e}")
    
    def _export_data(self):
        """Export data to CSV files."""
        try:
            
            current_time = datetime.now()
            if not hasattr(self, 'last_export_time'):
                self.last_export_time = current_time
                
            if (current_time - self.last_export_time).total_seconds() < 1800:  # 30 minutes
                return
                
            logger.info("Exporting data to CSV files")
            
           
            self.spot_1min.export_to_csv()
            self.spot_5min.export_to_csv()
            self.spot_15min.export_to_csv()
            
            
            self._export_ticks()
            
            self.last_export_time = current_time
            
        except Exception as e:
            logger.error(f"Error exporting data: {e}")
    
    def _export_ticks(self):
        """Export raw tick data to CSV."""
        try:
            if not self.spot_ticks:
                return
                
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = os.path.join(settings.RAW_TICKS_DIR, f"spot_ticks_{timestamp}.csv")
            
         
            df = pd.DataFrame(self.spot_ticks)
            df.to_csv(filename, index=False)
            
            logger.info(f"Exported {len(self.spot_ticks)} spot ticks to {filename}")
            
           
            if len(self.spot_ticks) > 10000:
                self.spot_ticks = self.spot_ticks[-5000:]
                
        except Exception as e:
            logger.error(f"Error exporting ticks: {e}")
    
    def _shutdown(self):
        """Clean shutdown of the application."""
        logger.info("Shutting down application...")
        
        
        try:
            self._export_data()
        except Exception as e:
            logger.error(f"Error exporting data during shutdown: {e}")
            
       
        if self.websocket:
            logger.info("Closing websocket connection")
            

def main():
    """Main entry point for the application."""
    app = AlgoTradingApp()
    app.start()

if __name__ == "__main__":
    main()
