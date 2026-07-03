import os
import json
import config
from oandapyV20 import API
import oandapyV20.endpoints.instruments as instruments
import oandapyV20.endpoints.accounts as accounts
import oandapyV20.endpoints.orders as orders
import oandapyV20.endpoints.trades as trades
import oandapyV20.endpoints.positions as positions
from oandapyV20.endpoints.pricing import PricingInfo
from oandapyV20.exceptions import V20Error

class OandaExecution:
    def __init__(self):
        self.api_key = os.getenv("OANDA_API_KEY", config.OANDA_API_KEY)
        self.account_id = os.getenv("OANDA_ACCOUNT_ID", config.OANDA_ACCOUNT_ID)
        self.environment = os.getenv("OANDA_ENV", config.OANDA_ENVIRONMENT).lower()
        
        if not self.api_key or not self.account_id:
            print("WARNING: Oanda API Key or Account ID not set!")
        else:
            print(f"Oanda Execution Initialized for Account: {self.account_id} in {self.environment} environment.")
            
        self.client = API(access_token=self.api_key, environment=self.environment)

    def get_account_summary(self):
        """Fetches account balance and NAV."""
        try:
            r = accounts.AccountSummary(self.account_id)
            response = self.client.request(r)
            return response.get('account')
        except V20Error as e:
            print(f"Error fetching account summary: {e}")
            return None

    def get_spread(self, instrument):
        """Fetches current spread for an instrument."""
        try:
            r = PricingInfo(self.account_id, params={"instruments": instrument})
            resp = self.client.request(r)
            if not resp.get('prices'): return 999
            price = resp['prices'][0]
            bid = float(price['bids'][0]['price'])
            ask = float(price['asks'][0]['price'])
            return ask - bid
        except Exception as e:
            print(f"Error fetching spread for {instrument}: {e}")
            return 999

    def get_current_price(self, instrument):
        """Fetches current mid price for an instrument."""
        try:
            r = PricingInfo(self.account_id, params={"instruments": instrument})
            resp = self.client.request(r)
            if not resp.get('prices'): return None
            price = resp['prices'][0]
            bid = float(price['bids'][0]['price'])
            ask = float(price['asks'][0]['price'])
            return (bid + ask) / 2
        except Exception as e:
            print(f"Error fetching price for {instrument}: {e}")
            return None

    def calculate_position_size(self, risk_amount, stop_loss_dist, instrument, margin_rate=0.05):
        """
        Calculates position size in units.
        Handles different quote currencies and checks margin.
        """
        if stop_loss_dist <= 0:
            return 0
        
        # 1. Determine conversion for Risk to USD
        # Risk = Units * StopLossDist(QuoteCCY) * Conversion(QuoteCCY->USD)
        quote_ccy = instrument.split("_")[1]
        
        conv_to_usd = 1.0
        if quote_ccy != "USD":
            try:
                # Try Quote_USD (e.g. GBP_USD)
                pair = f"{quote_ccy}_USD"
                r = PricingInfo(self.account_id, params={"instruments": pair})
                resp = self.client.request(r)
                conv_to_usd = float(resp['prices'][0]['asks'][0]['price'])
            except:
                try:
                    # Try USD_Quote (e.g. USD_JPY)
                    pair = f"USD_{quote_ccy}"
                    r = PricingInfo(self.account_id, params={"instruments": pair})
                    resp = self.client.request(r)
                    conv_to_usd = 1.0 / float(resp['prices'][0]['asks'][0]['price'])
                except:
                    # Fallbacks
                    if quote_ccy == "JPY": conv_to_usd = 0.0065
                    elif quote_ccy == "GBP": conv_to_usd = 1.25
                    elif quote_ccy == "EUR": conv_to_usd = 1.08
                    elif quote_ccy == "CHF": conv_to_usd = 1.12
                    elif quote_ccy == "CAD": conv_to_usd = 0.73
                    elif quote_ccy == "AUD": conv_to_usd = 0.65
                    elif quote_ccy == "NZD": conv_to_usd = 0.60
        
        units = int(risk_amount / (stop_loss_dist * conv_to_usd))
        
        # 2. Check against Margin
        account = self.get_account_summary()
        if account:
            nav = float(account.get('NAV', 0))
            # Margin = Units * Base_USD * margin_rate
            base_ccy = instrument.split("_")[0]
            base_to_usd = 1.0
            if base_ccy != "USD":
                try:
                    pair = f"{base_ccy}_USD"
                    r = PricingInfo(self.account_id, params={"instruments": pair})
                    resp = self.client.request(r)
                    base_to_usd = float(resp['prices'][0]['asks'][0]['price'])
                except:
                    try:
                        pair = f"USD_{base_ccy}"
                        r = PricingInfo(self.account_id, params={"instruments": pair})
                        resp = self.client.request(r)
                        base_to_usd = 1.0 / float(resp['prices'][0]['asks'][0]['price'])
                    except:
                        base_to_usd = 1.0 # Default fallback
            
            max_units_by_margin = int((nav * 0.8) / (base_to_usd * margin_rate)) # Use 80% of NAV for safety
            if units > max_units_by_margin:
                print(f"Reducing units from {units} to {max_units_by_margin} due to margin.")
                units = max_units_by_margin
        
        return units

    def execute_market_order(self, direction, units, sl_price, tp_price, instrument):
        """Executes a market order with SL and TP."""
        order_units = units if direction == 'long' else -units
        precision = 3 if "JPY" in instrument else 5
        
        data = {
            "order": {
                "units": str(order_units),
                "instrument": instrument,
                "timeInForce": "FOK",
                "type": "MARKET",
                "positionFill": "DEFAULT",
                "stopLossOnFill": {
                    "price": f"{sl_price:.{precision}f}"
                },
                "takeProfitOnFill": {
                    "price": f"{tp_price:.{precision}f}"
                }
            }
        }
        try:
            r = orders.OrderCreate(self.account_id, data=data)
            response = self.client.request(r)
            print(f"Order executed: {response}")
            return response
        except V20Error as e:
            print(f"Error executing order: {e}")
            return None

    def get_active_trades(self, instrument=None):
        """Returns list of active trades, optionally filtered by instrument."""
        try:
            r = trades.OpenTrades(self.account_id)
            response = self.client.request(r)
            trds = response.get('trades', [])
            if instrument:
                return [t for t in trds if t['instrument'] == instrument]
            return trds
        except V20Error as e:
            print(f"Error fetching open trades: {e}")
            return []

    def modify_stop_loss(self, trade_id, new_sl_price, instrument):
        """Updates the stop loss for an existing trade."""
        precision = 3 if "JPY" in instrument else 5
        data = {
            "stopLoss": {
                "price": f"{new_sl_price:.{precision}f}"
            }
        }
        try:
            r = trades.TradeCRCDO(self.account_id, trade_id=trade_id, data=data)
            response = self.client.request(r)
            return response
        except V20Error as e:
            print(f"Error modifying SL: {e}")
            return None

    def close_trade(self, trade_id, units=None):
        """Closes a trade partially or fully."""
        try:
            data = {}
            if units:
                data["units"] = str(abs(int(units)))
            else:
                data["units"] = "ALL"
                
            r = trades.TradeClose(self.account_id, trade_id=trade_id, data=data)
            response = self.client.request(r)
            return response
        except V20Error as e:
            print(f"Error closing trade {trade_id}: {e}")
            return None

    def get_order_book(self, instrument):
        """Fetches the order book for an instrument."""
        try:
            r = instruments.InstrumentsOrderBook(instrument=instrument)
            response = self.client.request(r)
            return response.get('orderBook')
        except Exception as e:
            print(f"Error fetching order book for {instrument}: {e}")
            return None

    def get_position_book(self, instrument):
        """Fetches the position book for an instrument."""
        try:
            r = instruments.InstrumentsPositionBook(instrument=instrument)
            response = self.client.request(r)
            return response.get('positionBook')
        except Exception as e:
            print(f"Error fetching position book for {instrument}: {e}")
            return None

if __name__ == "__main__":
    executor = OandaExecution()
