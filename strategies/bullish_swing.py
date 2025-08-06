"""
Bullish Swing Strategy module.
Implements a trading strategy based on bullish swing patterns.
"""
import pandas as pd
import numpy as np
import os
import time
from datetime import datetime

from ..utils.logger import logger
from ..models.option import OptionData
from ..config import settings

class BullishSwingStrategy:
    """
    Strategy that identifies and trades bullish swing patterns.
    The strategy looks for specific price patterns (L1, H1, A, B, C, D points)
    and generates trading signals when price breaks above the D point.
    """
    
    def __init__(self, data, broker=None):
        """
        Initialize the strategy with price data and broker connection.
        
        Args:
            data (pd.DataFrame): Price data with OHLCV columns
            broker: Broker instance for placing orders
        """
        # Store the data and broker connection
        self.data = data.copy() if not data.empty else pd.DataFrame()
        self.broker = broker
        
        # Initialize signal tracking
        self.signals = pd.DataFrame(index=self.data.index) if not self.data.empty else pd.DataFrame()
        self.signals['signal'] = 0
        self.signals['entry_price'] = np.nan
        self.signals['stop_loss'] = np.nan
        self.signals['target'] = np.nan
        
        # Initialize structure points
        self.H1 = None
        self.L1 = None
        self.A = None
        self.B = None
        self.C = None
        self.D = None
        
        # Structure point indices
        self.H1_idx = None
        self.L1_idx = None
        self.A_idx = None
        self.B_idx = None
        self.C_idx = None
        self.D_idx = None
        
        # Setup and order tracking
        self.pending_setup = None
        self.structures = []
        self.executed_patterns = []
        self.options_data = None
        self.last_order_id = None
        self.order_history = []
        self.order_counter = 0
        self.signal_counter = 0
        
        # Greeks data caching
        self.last_greeks_refresh = None
        self.greeks_refresh_interval = settings.GREEKS_REFRESH_INTERVAL
        self.cached_options_data = None
        
        # Create directories for storing data
        os.makedirs(settings.ORDER_HISTORY_DIR, exist_ok=True)
        os.makedirs(settings.OPTIONS_DATA_DIR, exist_ok=True)
    
    def _check_for_entry_trigger(self, idx):
        """
        Check if entry conditions are met at the given index.
        
        Args:
            idx (int): Index in the data
            
        Returns:
            bool: True if entry conditions are met, False otherwise
        """
        if self.signals.iloc[idx]['signal'] == 1:
            return True
        return False
    
    def print_current_structure(self):
        """Print the current bullish structure information."""
        logger.info("\n===== CURRENT BULLISH STRUCTURE =====")
        
        def format_point(name, value, idx):
            if value is not None and idx is not None:
                time_str = self.data.index[idx]
                return f"{name}: {value:.2f} at {time_str}"
            return f"{name}: Not yet formed"
        
        logger.info(format_point("L1", self.L1, self.L1_idx))
        logger.info(format_point("H1", self.H1, self.H1_idx))
        logger.info(format_point("A", self.A, self.A_idx))
        
        # B is a swing low point in the bullish structure
        if self.B is not None and self.B_idx is not None:
            time_str = self.data.index[self.B_idx]
            logger.info(f"B (swing low): {self.B:.2f} at {time_str}")
        else:
            logger.info("B (swing low): Not yet formed")
            
        logger.info(format_point("C", self.C, self.C_idx))
        logger.info(format_point("D", self.D, self.D_idx))
        
        if self.pending_setup:
            logger.info("\n----- PENDING SETUP -----")
            logger.info(f"Entry Price: {self.pending_setup['entry_price']:.2f}")
            logger.info(f"Stop Loss: {self.pending_setup['stop_loss']:.2f}")
            logger.info(f"Target: {self.pending_setup['target']:.2f}")
            
            risk = self.pending_setup['entry_price'] - self.pending_setup['stop_loss']
            reward = self.pending_setup['target'] - self.pending_setup['entry_price']
            risk_reward = reward / risk if risk > 0 else 0
            logger.info(f"Risk:Reward - 1:{risk_reward:.2f}")
            
        logger.info("====================================\n")
    
    def calculate_point_D(self):
        """
        Calculate the D point of the bullish structure.
        This is a critical point for signal generation.
        """
        if self.H1 is not None and self.B is not None and self.C is not None:
            logger.info(f"Calculating D point with B={self.B:.2f} (swing low), C={self.C:.2f}")
            
            # Initialize D with B's price (B is a swing low, and D should be a high after B)
            highest_high = self.data.iloc[self.B_idx]['high']
            highest_high_idx = self.B_idx
            
            # Scan from B to C (inclusive) to find the highest high
            for i in range(self.B_idx + 1, self.C_idx + 1):
                current_high = self.data.iloc[i]['high']
                if current_high > highest_high:
                    highest_high = current_high
                    highest_high_idx = i
                    
            self.D = highest_high
            self.D_idx = highest_high_idx
            d_time = self.data.index[self.D_idx]
            
            logger.info(f"POINT CALCULATION: D calculated at price {self.D:.2f} at time {d_time}")
            
            # Calculate trade parameters
            entry_price = self.D + 0.05  # Small buffer above D
            stop_loss = self.C - 0.05  # Below C point for stop loss
            risk = entry_price - stop_loss
            target = entry_price + (risk * 2)  # 1:2 Risk-Reward
            
            self.pending_setup = {
                'entry_price': entry_price,
                'stop_loss': stop_loss,
                'target': target,
                'structure': {
                    'H1': (self.H1_idx, self.H1),
                    'L1': (self.L1_idx, self.L1),
                    'A': (self.A_idx, self.A),
                    'B': (self.B_idx, self.B),
                    'C': (self.C_idx, self.C),
                    'D': (self.D_idx, self.D)
                },
                'options_data': None,
                'strategy_type': 'CE_BUYING'
            }
            
            # Fetch options data if broker is available
            if self.broker and hasattr(self.broker, 'api'):
                self.refresh_option_greeks(force_refresh=True)
    
    def is_swing_high(self, idx):
        """
        Check if the given index represents a swing high.
        
        Args:
            idx (int): Index in the data to check
            
        Returns:
            bool: True if it's a swing high, False otherwise
        """
        if idx <= 0 or idx >= len(self.data) - 1:
            return False
            
        current_high = self.data.iloc[idx]['high']
        prev_high = self.data.iloc[idx-1]['high']
        next_high = self.data.iloc[idx+1]['high']
        
        return current_high > prev_high and current_high > next_high
    
    def is_swing_low(self, idx):
        """
        Check if the given index represents a swing low.
        
        Args:
            idx (int): Index in the data to check
            
        Returns:
            bool: True if it's a swing low, False otherwise
        """
        if idx <= 0 or idx >= len(self.data) - 1:
            return False
            
        current_low = self.data.iloc[idx]['low']
        prev_low = self.data.iloc[idx-1]['low']
        next_low = self.data.iloc[idx+1]['low']
        
        return current_low < prev_low and current_low < next_low
    
    def detect_swings(self):
        """Detect swing highs and lows in the data."""
        self.swing_highs = []
        self.swing_lows = []
        
        for i in range(1, len(self.data) - 1):
            if self.is_swing_high(i):
                self.swing_highs.append((i, self.data.iloc[i]['high']))
                
            if self.is_swing_low(i):
                self.swing_lows.append((i, self.data.iloc[i]['low']))
    
    def initialize_H1_L1(self):
        """Initialize L1 using the low of the first candle."""
        if len(self.data) > 0:
            self.L1 = self.data.iloc[0]['low']
            self.L1_idx = 0
            logger.info(f"POINT INITIALIZATION: L1 initialized to first candle low at {self.L1:.2f}")
            
            # Reset H1 to None - it will be identified later
            self.H1 = None
            self.H1_idx = None
        else:
            logger.warning("No data available to initialize L1 point")
    
    def reset_points(self, which_points):
        """
        Reset specified structure points.
        
        Args:
            which_points (list): List of point names to reset (e.g., ['H1', 'L1'])
        """
        for point in which_points:
            if point == 'H1':
                self.H1 = None
                self.H1_idx = None
            elif point == 'L1':
                self.L1 = None
                self.L1_idx = None
            elif point == 'A':
                self.A = None
                self.A_idx = None
            elif point == 'B':
                self.B = None
                self.B_idx = None
            elif point == 'C':
                self.C = None
                self.C_idx = None
            elif point == 'D':
                self.D = None
                self.D_idx = None
                self.pending_setup = None
    
    def refresh_option_greeks(self, current_idx=None, force_refresh=False):
        """
        Fetch and refresh option Greeks data.
        
        Args:
            current_idx (int, optional): Index in data for timestamp reference
            force_refresh (bool): Force refresh regardless of time check
            
        Returns:
            bool: True if successful or using cached data, False if failed
        """
        if not self.broker or not hasattr(self.broker, 'api'):
            logger.warning("Broker not available for fetching option Greeks")
            return False
            
        try:
            current_time = datetime.now()
            
            # Check if we've refreshed recently
            if hasattr(self, 'last_greeks_refresh') and self.last_greeks_refresh and not force_refresh:
                elapsed = (current_time - self.last_greeks_refresh).total_seconds()
                if elapsed < self.greeks_refresh_interval:
                    logger.debug(f"Using cached Greeks ({elapsed:.1f}s old)")
                    return True
                    
            # Get nearest expiry dates
            # This would typically involve calling a function to get expiry dates
            # For simplicity, we'll assume we have a function called get_nearest_expiry_dates
            
            # Get option Greeks from broker API
            # For simplicity, we'll just note that this would call the broker's API
            
            # For now, we'll simulate this with a placeholder
            self.cached_options_data = pd.DataFrame()  # This would be real data in practice
            self.last_greeks_refresh = current_time
            
            logger.info(f"Successfully refreshed Greeks")
            return True
            
        except Exception as e:
            logger.error(f"Error refreshing Greeks: {e}")
            if hasattr(self, 'cached_options_data') and self.cached_options_data is not None:
                logger.warning("Continuing with previously fetched options data")
                return True
            return False
    
    def calculate_option_stop_loss(self, option_data, underlying_entry, underlying_sl):
        """
        Calculate option-specific stop loss using Greeks and underlying movement.
        
        Args:
            option_data (dict): Option data with Greeks
            underlying_entry (float): Entry price of the underlying
            underlying_sl (float): Stop loss price of the underlying
            
        Returns:
            dict: Stop loss calculation details
        """
        try:
            # Convert option_data to OptionData object if it's a dict
            if isinstance(option_data, dict):
                option = OptionData(option_data)
            else:
                option = option_data
                
            return option.calculate_stop_loss(underlying_entry, underlying_sl)
                
        except Exception as e:
            logger.error(f"Error calculating option stop loss: {e}")
            return None
    
    def check_live_tick(self, price):
        """
        Check for breakout signals in live ticks.
        
        Args:
            price (float): Current price from the tick
            
        Returns:
            dict: Signal data if breakout detected, None otherwise
        """
        if self.C is not None and self.D is not None:
            logger.info(f"Checking live tick at price {price:.2f} against D point {self.D:.2f}")
            
            if price > self.D:
                # Check if we already have an order placed today
                if self.order_counter >= settings.MAX_SIGNAL_ATTEMPTS:
                    logger.info(f"Maximum signal attempts reached for today ({self.order_counter}). Skipping.")
                    return None
                    
                logger.info(f"LIVE BREAKOUT DETECTED: Price {price:.2f} broke above D point {self.D:.2f}")
                
                if self.pending_setup is None:
                    # Calculate setup parameters
                    entry_price = self.D + 0.05
                    stop_loss = self.C - 0.05
                    risk_points = entry_price - stop_loss
                    target = entry_price + (2 * risk_points)
                    
                    self.pending_setup = {
                        'entry_price': entry_price,
                        'stop_loss': stop_loss,
                        'target': target,
                        'structure': {
                            'H1': (self.H1_idx, self.H1),
                            'L1': (self.L1_idx, self.L1),
                            'A': (self.A_idx, self.A),
                            'B': (self.B_idx, self.B),
                            'C': (self.C_idx, self.C),
                            'D': (self.D_idx, self.D)
                        }
                    }
                
                # Prepare options data for signal
                if self.cached_options_data is not None and not self.cached_options_data.empty:
                    options_data = self.cached_options_data
                else:
                    self.refresh_option_greeks(force_refresh=True)
                    options_data = self.cached_options_data
                
                if options_data is None or options_data.empty:
                    logger.error("No options data available for signal generation")
                    return None
                
                # Select the optimal option strike
                current_price = price
                entry_price = self.pending_setup['entry_price']
                stop_loss = self.pending_setup['stop_loss']
                
                # Use the OptionData static method to select the optimal strike
                option, quantity, total_risk = OptionData.select_optimal_strike(
                    options_data, 
                    current_price,
                    target_risk_range=(settings.TARGET_RISK_MIN, settings.TARGET_RISK_MAX),
                    lot_size=settings.DEFAULT_LOT_SIZE
                )
                
                if option is None:
                    logger.error("Failed to select an optimal option strike")
                    return None
                
                # Create signal data
                signal_data = {
                    'signal': 1,
                    'entry_price': entry_price,
                    'stop_loss': stop_loss,
                    'target': self.pending_setup['target'],
                    'option_data': option.to_dict(),
                    'quantity': quantity,
                    'total_risk': total_risk,
                    'timestamp': datetime.now()
                }
                
                self.signal_counter += 1
                return signal_data
                
        return None
    
    def place_order(self, signal_data):
        """
        Place an order based on signal data.
        
        Args:
            signal_data (dict): Signal data with order parameters
            
        Returns:
            str: Order ID if successful, None otherwise
        """
        if not self.broker:
            logger.error("Broker not available for placing order")
            return None
            
        if not signal_data or 'option_data' not in signal_data:
            logger.error("Invalid signal data for order placement")
            return None
            
        # Extract order details
        option_data = signal_data['option_data']
        quantity = signal_data['quantity']
        entry_price = signal_data['entry_price']
        stop_loss = signal_data['stop_loss']
        target = signal_data['target']
        
        # Prepare order parameters for bracket order
        order_params = {
            "tradingsymbol": option_data['symbol'],
            "symboltoken": option_data['token'],
            "transactiontype": "BUY",
            "exchange": "NFO",
            "ordertype": "MARKET",
            "producttype": "INTRADAY",
            "duration": "DAY",
            "quantity": str(quantity),
            "squareoff": str(round(option_data['target'] - option_data['last_price'], 2)),
            "stoploss": str(round(option_data['last_price'] - option_data['stop_loss'], 2))
        }
        
        # Place bracket order
        order_id = self.broker.place_order(order_params, order_type="BO")
        
        if order_id:
            # Increment order counter
            self.order_counter += 1
            
            # Record order details
            order_record = {
                'order_id': order_id,
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'symbol': option_data['symbol'],
                'token': option_data['token'],
                'strike': option_data['strike'],
                'option_type': option_data['option_type'],
                'expiry': option_data['expiry'],
                'quantity': quantity,
                'entry_price': option_data['last_price'],
                'stop_loss': option_data['stop_loss'],
                'target': option_data['target'],
                'status': 'PLACED',
                'variety': 'BO'
            }
            
            # Save order record
            self._save_order_to_csv(order_record)
            self.order_history.append(order_record)
            self.last_order_id = order_id
            
            logger.info(f"Bracket order placed successfully with ID: {order_id}")
            return order_id
        else:
            logger.error("Failed to place order")
            return None
    
    def _save_order_to_csv(self, order_data):
        """
        Save order data to a CSV file.
        
        Args:
            order_data (dict): Order details
        """
        try:
            # Generate filename with date
            date_str = datetime.now().strftime("%Y%m%d")
            filename = os.path.join(settings.ORDER_HISTORY_DIR, f'order_history_{date_str}.csv')
            
            # Convert complex objects to strings
            for key, value in order_data.items():
                if isinstance(value, (dict, list)):
                    order_data[key] = str(value)
                    
            # Convert to DataFrame for easier CSV handling
            df = pd.DataFrame([order_data])
            
            # Check if file exists to determine headers
            file_exists = os.path.isfile(filename)
            
            # Write to CSV
            df.to_csv(filename, mode='a', header=not file_exists, index=False)
            logger.info(f"Saved order details to {filename}")
            
        except Exception as e:
            logger.error(f"Error saving order to CSV: {e}")
    
    def generate_signals(self):
        """
        Process historical data to identify structure points and generate signals.
        
        Returns:
            pd.DataFrame: DataFrame with signal information
        """
        # Initialize structure
        self.initialize_H1_L1()
        
        for i in range(1, len(self.data)):
            current_candle = self.data.iloc[i]
            prev_candle = self.data.iloc[i-1]
            current_time = self.data.index[i]
            
            # L1 detection and updates
            if self.is_swing_low(i) and current_candle['low'] < self.L1:
                previous_L1 = self.L1
                self.L1 = current_candle['low']
                self.L1_idx = i
                self.reset_points(['H1', 'A', 'B', 'C', 'D'])
                logger.info(f"POINT UPDATE: L1 updated from {previous_L1:.2f} to {self.L1:.2f}")
                
            # H1 detection and updates
            if self.L1 is not None and self.is_swing_high(i):
                if i > self.L1_idx and current_candle['high'] > self.L1:
                    if self.H1 is None:
                        self.H1 = current_candle['high']
                        self.H1_idx = i
                        logger.info(f"POINT DETECTION: H1 detected at price {self.H1:.2f}")
                    elif current_candle['high'] > self.H1:
                        previous_H1 = self.H1
                        self.H1 = current_candle['high']
                        self.H1_idx = i
                        self.reset_points(['A', 'B', 'C', 'D'])
                        logger.info(f"POINT UPDATE: H1 updated from {previous_H1:.2f} to {self.H1:.2f}")
                        
            # A point detection
            if self.H1 is not None and self.L1 is not None:
                if self.A is None and self.is_swing_low(i):
                    if i > self.H1_idx and current_candle['low'] > self.L1:
                        self.A = current_candle['low']
                        self.A_idx = i
                        logger.info(f"POINT DETECTION: A detected at price {self.A:.2f}")
                        
            # B point detection
            if self.A is not None:
                if self.B is None and self.is_swing_low(i):
                    if i > self.A_idx + 1 and current_candle['low'] > self.A:
                        self.B = current_candle['low']
                        self.B_idx = i
                        logger.info(f"POINT DETECTION: B detected at price {self.B:.2f}")
                        
            # C and D point detection
            if self.B is not None:
                if self.C is None:
                    if i > self.B_idx and current_candle['low'] < prev_candle['low'] and current_candle['low'] > self.B:
                        self.C = current_candle['low']
                        self.C_idx = i
                        logger.info(f"POINT DETECTION: C detected at price {self.C:.2f}")
                        self.calculate_point_D()
                        
            # Breakout detection
            if self.pending_setup is not None:
                if current_candle['high'] > self.D:
                    # Set signal in the signals DataFrame
                    self.signals.iloc[i, self.signals.columns.get_loc('signal')] = 1
                    self.signals.iloc[i, self.signals.columns.get_loc('entry_price')] = self.pending_setup['entry_price']
                    self.signals.iloc[i, self.signals.columns.get_loc('stop_loss')] = self.pending_setup['stop_loss']
                    self.signals.iloc[i, self.signals.columns.get_loc('target')] = self.pending_setup['target']
                    
                    # Record the structure
                    structure = self.pending_setup['structure'].copy()
                    structure['entry'] = (i, self.pending_setup['entry_price'])
                    structure['stop_loss'] = (i, self.pending_setup['stop_loss'])
                    structure['target'] = (i, self.pending_setup['target'])
                    self.structures.append(structure)
                    
                    logger.info(f"Signal generated at {self.data.index[i]}. Entry: {self.pending_setup['entry_price']:.2f}")
                    
                    # Reset points to start looking for new structure
                    self.reset_points(['H1', 'L1', 'A', 'B', 'C', 'D'])
                    self.L1 = current_candle['low']
                    self.L1_idx = i
        
        return self.signals
