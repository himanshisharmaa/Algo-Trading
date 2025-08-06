"""
Angel One broker API integration module.
Handles authentication, order placement, websocket connections, and other broker interactions.
"""
import time
import random
import pyotp
import json
from datetime import datetime
import threading

from SmartApi import SmartConnect
from SmartApi.smartWebSocketV2 import SmartWebSocketV2

from ..utils.logger import logger, log_exception, log_order
from ..config import settings

class AngelOneBroker:
    """
    Angel One broker API wrapper class.
    Handles authentication, order placement, and other broker-related operations.
    """
    
    def __init__(self):
        """Initialize the broker connection."""
        self.api = None
        self.feed_token = None
        self.refresh_token = None
        self.websocket = None
        self.is_connected = False
        
        self._last_order_time = 0
        self._minute_order_count = 0
        self._minute_start_time = time.time()
        
        self._last_status_check = 0
        self._minute_status_count = 0
        self._minute_status_start = time.time()
        
    def generate_totp(self):
        """
        Generate TOTP for authentication.
        
        Returns:
            str: TOTP code
        """
        try:
            totp = pyotp.TOTP(settings.TOTP_KEY)
            return totp.now()
        except Exception as e:
            log_exception(e)
            return None
    
    def connect(self):
        """
        Connect to Angel One broker using SmartAPI.
        
        Returns:
            bool: True if connected successfully, False otherwise
        """
        try:
            if self.api is None:
                logger.info("Initializing SmartAPI connection...")
                totp = self.generate_totp()
                if not totp:
                    logger.error("Failed to generate TOTP for authentication")
                    return False

                self.api = SmartConnect(api_key=settings.API_KEY)
                data = self.api.generateSession(settings.USERNAME, settings.PASSWORD, totp)

                if data and data.get('status'):
                    self.refresh_token = data.get('data', {}).get('refreshToken')
                    self.feed_token = self.api.getfeedToken()
                    self.is_connected = True
                    logger.info(f"Successfully connected to broker. Feed token: {self.feed_token}")
                    return True
                else:
                    error_message = data.get('message', 'Unknown error') if data else 'No response from broker'
                    logger.error(f"Failed to connect to broker: {error_message}")
                    return False
            else:
                try:
                    profile = self.api.getProfile()
                    if profile and profile.get('status'):
                        logger.info("Broker connection is active")
                        return True
                    else:
                        logger.warning("Broker session expired, reconnecting...")
                        self.api = None
                        return self.connect()
                except Exception as e:
                    logger.warning(f"Error checking broker connection: {e}. Reconnecting...")
                    self.api = None
                    return self.connect()
        except Exception as e:
            log_exception(e)
            return False
            
    def place_order(self, order_params, order_type="NORMAL"):
        """
        Place an order with the broker.
        
        Args:
            order_params (dict): Order parameters
            order_type (str): Order type (NORMAL, BO, CO)
            
        Returns:
            str: Order ID if successful, None otherwise
        """
        try:
            if not self.connect():
                logger.error("Failed to connect to broker for placing order")
                return None
                
            # Rate limit handling
            current_time = time.time()
            
            # Check minute-based rate limit
            if current_time - self._minute_start_time >= 60:
                # Reset minute counter if a minute has passed
                self._minute_order_count = 0
                self._minute_start_time = current_time
            elif self._minute_order_count >= settings.MAX_REQUESTS_PER_MINUTE:
                # Wait for the remainder of the minute if we've hit the limit
                sleep_time = 60 - (current_time - self._minute_start_time)
                if sleep_time > 0:
                    logger.info(f"Reached minute order rate limit, waiting {sleep_time:.2f} seconds")
                    time.sleep(sleep_time)
                    self._minute_order_count = 0
                    self._minute_start_time = time.time()

            # Per-second rate limit
            time_since_last = current_time - self._last_order_time
            min_interval_sec = settings.MIN_REQUEST_INTERVAL_MS / 1000
            if time_since_last < min_interval_sec:  
                time.sleep(min_interval_sec - time_since_last)
                
            # Set the order variety
            if 'variety' not in order_params:
                order_params['variety'] = order_type
                
            # Place the order
            order_response = self.api.placeOrder(order_params)
            
            # Update rate limit tracking
            self._last_order_time = time.time()
            self._minute_order_count += 1

            # Process response
            order_id = None
            if isinstance(order_response, dict) and order_response.get('status'):
                order_id = order_response.get('data', {}).get('orderid')
            elif isinstance(order_response, str) and order_response.isalnum():
                order_id = order_response
                
            if order_id:
                logger.info(f"Order placed successfully with ID: {order_id}")
                return order_id
            else:
                logger.error(f"Order placement failed: {order_response}")
                return None
                
        except Exception as e:
            log_exception(e)
            return None
            
    def check_order_status(self, order_id, max_retries=3):
        """
        Check the status of a placed order.
        
        Args:
            order_id (str): Order ID to check
            max_retries (int): Maximum number of retry attempts
            
        Returns:
            dict: Order status information or None if failed
        """
        if not order_id:
            return None
            
        current_time = time.time()
        
        if current_time - self._minute_status_start >= 60:
            self._minute_status_count = 0
            self._minute_status_start = current_time
        elif self._minute_status_count >= settings.MAX_REQUESTS_PER_MINUTE:
            sleep_time = 60 - (current_time - self._minute_status_start)
            if sleep_time > 0:
                logger.info(f"Reached minute status check rate limit, waiting {sleep_time:.2f} seconds")
                time.sleep(sleep_time)
                self._minute_status_count = 0
                self._minute_status_start = time.time()
                
        for retry in range(max_retries):
            try:
                time_since_last = current_time - self._last_status_check
                min_interval_sec = settings.MIN_REQUEST_INTERVAL_MS / 1000
                if time_since_last < min_interval_sec:
                    time.sleep(min_interval_sec - time_since_last)

                order_book = self.api.orderBook()
                
                self._last_status_check = time.time()
                self._minute_status_count += 1

                if order_book and 'data' in order_book:
                    for order in order_book['data']:
                        if order.get('orderid') == order_id:
                            return {
                                'order_id': order_id,
                                'status': order.get('status'),
                                'filled_quantity': order.get('filledqty'),
                                'average_price': order.get('averageprice'),
                                'order_type': order.get('ordertype'),
                                'product_type': order.get('producttype'),
                                'variety': order.get('variety')
                            }
                    return None
                    
                if retry < max_retries - 1:
                    time.sleep(0.5)  
                    continue
                    
            except Exception as e:
                log_exception(e)
                if retry < max_retries - 1:
                    time.sleep(0.5)
                    continue
                break
                
        return None
        
    def get_option_greeks(self, name, expiry_date, max_retries=3):
        """
        Get option Greek values for a specific expiry date.
        
        Args:
            name (str): Instrument name (e.g., "NIFTY")
            expiry_date (str): Expiry date in format DDMMMYYYY (e.g., "29JUN2023")
            max_retries (int): Maximum number of retry attempts
            
        Returns:
            list: Option Greek data or None if failed
        """
        if not self.connect():
            logger.error("Failed to connect to broker for getting option Greeks")
            return None
            
        greek_param = {
            "name": name,
            "expirydate": expiry_date
        }
        
        for retry in range(max_retries):
            try:
                
                if retry > 0:
                    jitter = random.uniform(0, 0.1)
                    backoff = min(2 ** retry + jitter, 5)  
                    time.sleep(backoff)
                
                greek_res = self.api.optionGreek(greek_param)
                
                if greek_res and greek_res.get('status'):
                    return greek_res.get('data', [])
                else:
                    error_msg = greek_res.get('message', 'Unknown error')
                    logger.warning(f"Option Greeks API error: {error_msg}")
                    
                   
                    if any(phrase in str(error_msg).lower() for phrase in 
                          ['rate limit', 'too many requests', 'exceeding access']):
                       
                        time.sleep(min(5 * (retry + 1), 30))
                        
            except Exception as e:
                log_exception(e)
                
        return None
        
    def start_websocket(self, token_list, on_data_callback):
        """
        Start a websocket connection for real-time data.
        
        Args:
            token_list (list): List of tokens to subscribe to
            on_data_callback (function): Callback function for data
            
        Returns:
            SmartWebSocketV2: Websocket instance if successful, None otherwise
        """
        if not self.connect():
            logger.error("Failed to connect to broker for websocket")
            return None
            
        try:
            
            ws = SmartWebSocketV2(
                self.refresh_token, 
                settings.API_KEY, 
                settings.USERNAME, 
                self.feed_token
            )
            
            
            def on_open(wsapp):
                logger.info("WebSocket connection opened")
                correlation_id = "nifty_data_tracker"
                mode = 1  
                ws.subscribe(correlation_id, mode, token_list)
                
            def on_data_wrapper(wsapp, message):
                on_data_callback(message)
                
            def on_error(wsapp, error):
                logger.error(f"WebSocket error: {error}")
                
            def on_close(wsapp, close_status_code=None, close_reason=None):
                logger.info(f"WebSocket connection closed: {close_status_code} - {close_reason}")
                
          
            ws.on_open = on_open
            ws.on_data = on_data_wrapper
            ws.on_error = on_error
            ws.on_close = on_close
            
            
            def ws_connect_thread():
                ws.connect()
                
            thread = threading.Thread(target=ws_connect_thread, daemon=True)
            thread.start()
            
            self.websocket = ws
            return ws
            
        except Exception as e:
            log_exception(e)
            return None


broker = AngelOneBroker()
