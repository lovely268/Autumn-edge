import pandas as pd
import sys
import os

# Add the directory to path so we can import
sys.path.append('/home/team/shared/aurum_edge_v1')

from execution_agent import check_price_action

def test_pa_rejection_long():
    # Setup a series of candles where the last one has a long lower wick
    # total size = 10, lower wick = 6
    candles = []
    for i in range(9):
        candles.append({'open': 100, 'high': 110, 'low': 90, 'close': 105})
    
    # Last candle: Open 100, High 105, Low 90, Close 102
    # Total size: 105 - 90 = 15
    # Lower wick: min(100, 102) - 90 = 10
    # 10 / 15 = 0.66 > 0.5 (REJECTION OK)
    # BUT we also need BOS.
    # recent_swing_high = max of highs of previous 9 = 110.
    # Current close = 102. 102 < 110 (BOS FAIL)
    candles.append({'open': 100, 'high': 105, 'low': 90, 'close': 102})
    
    result = check_price_action("long", candles)
    print(f"Test Long Rejection + No BOS: {result} (Expected: False)")

def test_pa_rejection_and_bos_long():
    candles = []
    for i in range(9):
        candles.append({'open': 100, 'high': 110, 'low': 90, 'close': 105})
    
    # Rejection in candle -2
    # Open 100, High 105, Low 90, Close 102 (Lower wick = 10, Total = 15, Ratio = 0.66)
    candles[-1] = {'open': 100, 'high': 105, 'low': 90, 'close': 102}
    
    # BOS in candle -1
    # Close must be > 110
    candles.append({'open': 105, 'high': 115, 'low': 104, 'close': 112})
    
    result = check_price_action("long", candles)
    print(f"Test Long Rejection + BOS: {result} (Expected: True)")

if __name__ == "__main__":
    test_pa_rejection_long()
    test_pa_rejection_and_bos_long()
