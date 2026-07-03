import os
import json
import config

class FuturesExecution:
    def __init__(self):
        # Placeholder for actual broker API (Tradovate/Rithmic/MT5)
        self.broker_connected = False
        
        # Tick values and sizes for Micro Futures
        self.FUTURES_SPECS = {
            "MES=F": {"tick_size": 0.25, "tick_value": 1.25, "point_value": 5.0, "full_name": "Micro S&P 500"},
            "MNQ=F": {"tick_size": 0.25, "tick_value": 0.50, "point_value": 2.0, "full_name": "Micro Nasdaq 100"},
            "MCL=F": {"tick_size": 0.01, "tick_value": 1.00, "point_value": 100.0, "full_name": "Micro Crude Oil"},
            "MGC=F": {"tick_size": 0.10, "tick_value": 1.00, "point_value": 10.0, "full_name": "Micro Gold"},
            "ES=F":  {"tick_size": 0.25, "tick_value": 12.50, "point_value": 50.0, "full_name": "E-mini S&P 500"},
            "NQ=F":  {"tick_size": 0.25, "tick_value": 5.00, "point_value": 20.0, "full_name": "E-mini Nasdaq 100"},
            "GC=F":  {"tick_size": 0.10, "tick_value": 10.00, "point_value": 100.0, "full_name": "Gold Futures"},
            "CL=F":  {"tick_size": 0.01, "tick_value": 10.00, "point_value": 1000.0, "full_name": "Crude Oil Futures"}
        }

    def calculate_position_size(self, risk_amount, stop_loss_dist, symbol):
        """
        Calculates position size in number of contracts.
        risk_amount: USD to risk
        stop_loss_dist: Difference in points
        """
        spec = self.FUTURES_SPECS.get(symbol)
        if not spec:
            print(f"WARNING: Symbol {symbol} not found in futures specs. Using conservative micro estimate.")
            # Default to Micro Nasdaq-like sizing for safety
            spec = {"point_value": 2.0, "tick_size": 0.25}
            
        point_value = spec["point_value"]
        
        # Points to stop
        points_to_stop = stop_loss_dist
        
        if points_to_stop <= 0:
            return 0
            
        # Contracts = Risk / (Points * PointValue)
        contracts = risk_amount / (points_to_stop * point_value)
        
        # Always floor to nearest contract
        final_contracts = int(contracts)
        
        # Prop Firm safety: Never exceed 10 Micros for a 25K account
        if "M" in symbol: # Micro symbols
            final_contracts = min(final_contracts, 10)
        else: # E-mini symbols
            final_contracts = min(final_contracts, 1) # Cap at 1 mini for 25K account
            # Safety Check: If 1 Mini exceeds 3% risk, don't take it (return 0)
            if final_contracts == 1:
                potential_risk = point_value * points_to_stop
                if potential_risk > 750: # 3% of 25K
                    print(f"WARNING: 1 Mini {symbol} exceeds safety limit (${potential_risk} > $750). Returning 0.")
                    return 0
            
        return final_contracts

    def execute_market_order(self, direction, contracts, sl_price, tp_price, symbol):
        """
        Placeholder for market order execution.
        """
        print(f"SIMULATION: {direction.upper()} {contracts} contracts of {symbol}")
        print(f"Entry at Market | SL: {sl_price} | TP: {tp_price}")
        return {"lastTransactionID": f"sim_{symbol}_{direction}_{contracts}"}

    def close_trade(self, trade_id):
        print(f"SIMULATION: Closing trade {trade_id}")
        return True

    def modify_stop_loss(self, trade_id, new_sl, symbol):
        print(f"SIMULATION: Modifying SL for {trade_id} to {new_sl}")
        return True
