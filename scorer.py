
import json
import os

class InstitutionalScorer:
    def __init__(self):
        # Weights for the 'Heuristic ML' model (Rev 14 - Phase 4 Macro Alpha)
        self.weights = {
            'htf_trend': 0.08,      # Alignment with 1h Trend
            'mtf_trend': 0.04,      # Alignment with 15m Trend
            'daily_trend': 0.08,    # Alignment with 1d Trend
            'weekly_trend': 0.04,   # Alignment with 1wk Trend
            'yield_spread': 0.10,   # Yield divergence proxy
            'macro_dxy': 0.08,      # DXY momentum (Risk-off/on)
            'macro_vix': 0.04,      # VIX (Fear Gauge)
            'macro_gold': 0.04,     # Gold (Safe Haven flow)
            'cb_sentiment': 0.10,   # Central Bank NLP Sentiment
            'economic_surprise': 0.10, # Deviation (Actual vs Forecast)
            'retail_proxy': 0.05,   # Contrarian behavioral proxy
            'order_flow': 0.10,     # Layer 9: Volume Delta & Position Ratios
            'session_vola': 0.05,   # Peak liquidity timing
            'narrative_align': 0.10 # Phase 4 Narrative Integration
        }

    def calculate_score(self, symbol, direction, market_state):
        """
        Calculates a probability score (0-10) based on weighted confluences.
        Enhanced with Phase 4 Macro-Alpha and Macro Strategist Narratives.
        Hard-gated for Simultaneous Confluence.
        """
        raw_score = 0
        gate_failures = []

        # 1. Trends (Recursive Fractal Alignment) - MUST ALL ALIGN
        trends = {
            'conf_trend': market_state.get('conf_trend'),
            'mtf_trend': market_state.get('mtf_trend'),
            'htf_trend': market_state.get('htf_trend'),
            'daily_trend': market_state.get('daily_trend'),
            'weekly_trend': market_state.get('weekly_trend')
        }

        for k, v in trends.items():
            if v == direction:
                # Weighted contribution to score
                weight_key = k if k != 'conf_trend' else 'mtf_trend' # Use mtf_trend weight for conf for now or add new
                raw_score += self.weights.get(weight_key, 0.04)
            elif v != 'neutral':
                gate_failures.append(f"Fractal Conflict: {k} is {v} vs {direction}")

        # 2. Yield Spread (10%) - MUST SUPPORT
        yield_spread = market_state.get('yield_spread_momentum', 'neutral')
        if yield_spread == direction:
            raw_score += self.weights['yield_spread']
        elif yield_spread != 'neutral':
            gate_failures.append(f"Yield Conflict: Momentum is {yield_spread}")

        # 3. Macro DXY (8%) - MUST SUPPORT USD DIRECTION
        # If buying EURUSD, DXY should be bearish.
        # If buying ES=F (Stock Index), DXY should be bearish (Risk-On).
        dxy_trend = market_state.get('macro_dxy_trend', 'neutral')
        if "USD" in symbol or "=F" in symbol:
            is_usd_base = symbol.startswith("USD")
            # If Stock Index (ES, NQ), bullish direction prefers bearish DXY
            if "=F" in symbol and ("ES" in symbol or "NQ" in symbol or "YM" in symbol or "RTY" in symbol):
                expected_dxy = "bearish" if direction == "long" else "bullish"
            else:
                expected_dxy = direction if is_usd_base else ("bearish" if direction == "long" else "bullish")
                
            if dxy_trend == expected_dxy:
                raw_score += self.weights['macro_dxy']
            elif dxy_trend != 'neutral':
                gate_failures.append(f"DXY Conflict: DXY is {dxy_trend}")

        # 4. Macro VIX (4%) - RISK REGIME
        vix_trend = market_state.get('macro_vix_trend', 'neutral')
        # Risk-on: Long AUD, NZD, Indices (ES, NQ). Risk-off: Long USD, JPY, CHF, Gold (Safe Haven).
        risk_on_assets = ["AUD", "NZD", "GBP", "EUR", "ES=F", "NQ=F", "RTY=F", "YM=F"]
        risk_off_assets = ["USD", "JPY", "CHF"]
        
        asset_found = False
        for risk_on in risk_on_assets:
            if risk_on in symbol:
                if vix_trend == "bearish" and direction == "long": raw_score += self.weights['macro_vix']
                if vix_trend == "bullish" and direction == "short": raw_score += self.weights['macro_vix']
                asset_found = True; break
        
        if not asset_found:
            for risk_off in risk_off_assets:
                if risk_off in symbol:
                    if vix_trend == "bullish" and direction == "long": raw_score += self.weights['macro_vix']
                    if vix_trend == "bearish" and direction == "short": raw_score += self.weights['macro_vix']
                    asset_found = True; break

        # 5. Macro Gold (4%)
        gold_trend = market_state.get('macro_gold_trend', 'neutral')
        if gold_trend == direction and "XAU" in symbol:
            raw_score += self.weights['macro_gold']

        # 6. Central Bank Sentiment (10%)
        cb_sentiment = market_state.get('cb_sentiment_score', 0)
        # Positive score = Hawkish = Bullish for currency
        if (cb_sentiment > 0.2 and direction == "long") or (cb_sentiment < -0.2 and direction == "short"):
            raw_score += self.weights['cb_sentiment']
        elif abs(cb_sentiment) > 0.4: # Strong conflict
             gate_failures.append(f"Sentiment Conflict: Sentiment Score {cb_sentiment}")

        # 7. Economic Surprise (10%)
        surprise = market_state.get('economic_surprise', 0)
        if (surprise > 0 and direction == "long") or (surprise < 0 and direction == "short"):
            raw_score += self.weights['economic_surprise']

        # 8. Retail Behavioral Proxy (5%)
        retail = market_state.get('retail_sentiment', 'neutral')
        if (retail == 'short' and direction == 'long') or (retail == 'long' and direction == 'short'):
            raw_score += self.weights['retail_proxy']

        # 9. Order Flow (10%)
        net_vol = market_state.get('net_volume_delta', 0)
        long_pos = market_state.get('long_pos', 50)
        short_pos = market_state.get('short_pos', 50)

        order_flow_aligned = False
        if direction == 'long':
            if net_vol > 0 or short_pos > 60: order_flow_aligned = True
        elif direction == 'short':
            if net_vol < 0 or long_pos > 60: order_flow_aligned = True

        if order_flow_aligned:
            raw_score += self.weights['order_flow']
        else:
            gate_failures.append("Order Flow Conflict: No institutional pressure confirmed")

        # 10. Session Volatility (5%)
        import datetime
        hour = datetime.datetime.now(datetime.timezone.utc).hour
        is_kill_zone = False
        if 13 <= hour <= 17: # NY Open / London Close
            raw_score += self.weights['session_vola']
            is_kill_zone = True
        elif 8 <= hour <= 11: # London Open
            raw_score += self.weights['session_vola'] * 0.7
            is_kill_zone = True

        if not is_kill_zone:
            gate_failures.append("Session Conflict: Outside London/NY Kill Zones")

        # 11. Narrative Alignment (10%)
        narratives = market_state.get('narratives', {})
        narrative_support = False
        if isinstance(narratives, dict):
            # Narratives from Strategist (Policy Divergence, Safe Haven, etc.)
            # Check if any narrative direction matches our trade direction
            for n_name, n_dir in narratives.items():
                if n_dir == direction:
                    narrative_support = True
                    break

        if narrative_support:
            raw_score += self.weights['narrative_align']
        else:
            gate_failures.append("Narrative Conflict: No macro narrative supports this direction")

        # Normalize to 0-10
        score = raw_score * 10

        # Confluence bonus (Increased filter for AAA)
        # Must have at least 6 aligned layers for the bonus
        aligned_layers = 12 - len(gate_failures)

        if aligned_layers >= 10:
            score += 1.0
        elif aligned_layers >= 8:
            score += 0.5

        final_score = min(10, round(score, 1))

        # FINAL HARD GATING
        # No trade if:
        # 1. Score < 8.5 (Institutional Grade)
        # 2. Any "Critical" gate failure
        is_hard_gated = False
        if final_score < 8.5:
            is_hard_gated = True
        if len(gate_failures) > 0:
            # Any conflict is a hard gate failure per "Simultaneous Confluence"
            is_hard_gated = True

        return {
            'score': final_score,
            'is_hard_gated': is_hard_gated,
            'gate_failures': gate_failures,
            'aligned_layers': aligned_layers
        }

    def get_confidence_rating(self, score):
        if score >= 8.5: return "Institutional Grade (AAA)"
        if score >= 7.0: return "High Conviction (AA)"
        if score >= 5.0: return "Standard Setup (B)"
        return "Low Confidence (Discard)"
