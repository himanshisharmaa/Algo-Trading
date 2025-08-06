"""
Option model module.
Provides classes and functions for working with option data.
"""
import pandas as pd
import numpy as np
from datetime import datetime
from ..utils.logger import logger
from ..config import settings

class OptionData:
    """Class representing option data with Greeks and calculations."""
    
    def __init__(self, data=None):
        """
        Initialize option data.
        
        Args:
            data (dict, optional): Option data dictionary
        """
        self.symbol = data.get('symbol', '')
        self.token = data.get('token', '')
        self.strike = float(data.get('strike_float', 0))
        self.option_type = data.get('option_type', '')  
        self.expiry = data.get('expiry_date') if data.get('expiry_date') else data.get('expiry', '')
        self.lot_size = int(data.get('lotsize', settings.DEFAULT_LOT_SIZE))
        
        self.delta = float(data.get('delta', 0) or 0)
        self.gamma = float(data.get('gamma', 0) or 0)
        self.theta = float(data.get('theta', 0) or 0)
        self.vega = float(data.get('vega', 0) or 0)
        self.implied_volatility = float(data.get('impliedVolatility', 0) or 0)
        
        self.last_price = float(data.get('last_price', 0) or 0)
        self.bid_price = float(data.get('bid_price', 0) or 0)
        self.ask_price = float(data.get('ask_price', 0) or 0)
        self.volume = int(data.get('volume', 0) or 0)
        self.open_interest = int(data.get('open_interest', 0) or 0)
        
        self.stop_loss = None
        self.target = None
        self.risk_per_lot = None
        
    def __str__(self):
        """String representation of the option."""
        return f"{self.symbol} {self.strike} {self.option_type} {self.expiry}"
        
    def to_dict(self):
        """Convert to dictionary representation."""
        return {
            'symbol': self.symbol,
            'token': self.token,
            'strike': self.strike,
            'option_type': self.option_type,
            'expiry': self.expiry,
            'lot_size': self.lot_size,
            'delta': self.delta,
            'gamma': self.gamma,
            'theta': self.theta,
            'vega': self.vega,
            'implied_volatility': self.implied_volatility,
            'last_price': self.last_price,
            'bid_price': self.bid_price,
            'ask_price': self.ask_price,
            'volume': self.volume,
            'open_interest': self.open_interest,
            'stop_loss': self.stop_loss,
            'target': self.target,
            'risk_per_lot': self.risk_per_lot
        }
        
    def calculate_stop_loss(self, underlying_entry, underlying_sl):
        """
        Calculate option-specific stop loss using Greeks and underlying movement.
        
        Args:
            underlying_entry (float): Entry price of the underlying
            underlying_sl (float): Stop loss price of the underlying
            
        Returns:
            dict: Stop loss calculation details
        """
        try:
            underlying_move = abs(underlying_entry - underlying_sl)
            
            delta_impact = self.delta * underlying_move  
            gamma_impact = 0.5 * self.gamma * (underlying_move ** 2)  
            
            
          
            theta_impact = (abs(self.theta) / (24 * 6)) * (10/60)             
           
            total_sl = delta_impact + gamma_impact + theta_impact
            
            
            self.risk_per_lot = total_sl
            
            if self.last_price > 0:
                self.stop_loss = max(self.last_price - total_sl, 0.1)
                
               
                risk = self.last_price - self.stop_loss
                self.target = self.last_price + (2 * risk)
            
            return {
                'price_change': total_sl,
                'total_sl': total_sl,
                'components': {
                    'delta_impact': delta_impact,
                    'gamma_impact': gamma_impact,
                    'theta_impact': theta_impact
                }
            }
        except Exception as e:
            logger.error(f"Error calculating option stop loss: {e}")
            return None
            
    @staticmethod
    def select_optimal_strike(options_data, current_price, target_risk_range=(800, 900), lot_size=75):
        """
        Select the optimal strike based on risk parameters.
        
        Args:
            options_data (pd.DataFrame): DataFrame containing options data
            current_price (float): Current price of the underlying
            target_risk_range (tuple): Target risk range in rupees (min, max)
            lot_size (int): Standard lot size
            
        Returns:
            tuple: (selected_option, quantity, total_risk)
        """
        if options_data is None or options_data.empty:
            logger.error("No options data available for strike selection")
            return None, None, None
            
        target_min, target_max = target_risk_range
        target_mid = (target_min + target_max) / 2
        
       
        options = []
        for _, row in options_data.iterrows():
            option = OptionData(row.to_dict())
            options.append(option)
            
        
        valid_options = []
        for option in options:
            if option.calculate_stop_loss(current_price, current_price * 0.995): 
                valid_options.append(option)
                
        if not valid_options:
            logger.warning("No valid options with stop loss calculation")
            return None, None, None
            
       
        options_in_range = []
        for option in valid_options:
          
            for lots in range(1, 51): 
                quantity = lots * lot_size
                total_risk = option.risk_per_lot * quantity
                
                if target_min <= total_risk <= target_max:
                    options_in_range.append((option, quantity, total_risk, abs(total_risk - target_mid)))
                    
               
                if total_risk > target_max:
                    break
                    
        if options_in_range:
           
            options_in_range.sort(key=lambda x: x[3])  
            return options_in_range[0][:3] 
        else:
            
            valid_options.sort(key=lambda opt: abs(opt.risk_per_lot * lot_size - target_mid))
            closest_option = valid_options[0]
            return closest_option, lot_size, closest_option.risk_per_lot * lot_size
