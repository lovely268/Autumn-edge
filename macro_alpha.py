import pandas as pd
import yfinance as yf
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import logging
import time
import os

class MacroAlpha:
    def __init__(self):
        self.analyzer = SentimentIntensityAnalyzer()
        self.cross_asset_symbols = {
            'US10Y': '^TNX',
            'UK10Y': '^GUK10', 
            'DE10Y': '^GDBR10',
            'JP10Y': '^GJGB10',
            'VIX': '^VIX',
            'Gold': 'GC=F',
            'Copper': 'HG=F',
            'DXY': 'DX-Y.NYB',
            'Oil': 'CL=F'
        }

    def get_cross_asset_data(self):
        """Fetches recent data for cross-asset leading indicators."""
        data = {}
        for name, symbol in self.cross_asset_symbols.items():
            try:
                # Try 1h first, fallback to 1d
                df = yf.download(symbol, period='10d', interval='1h', progress=False)
                if df.empty:
                    df = yf.download(symbol, period='1mo', interval='1d', progress=False)
                
                if not df.empty:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    data[name] = df
            except Exception as e:
                logging.debug(f"Error fetching {name} ({symbol}): {e}")
        return data

    def calculate_macro_filters(self):
        assets = self.get_cross_asset_data()
        correlations = self.calculate_correlations(assets)
        
        vix_data = correlations.get('VIX', {})
        vix_trend = vix_data.get('trend', 'neutral')
        vix_value = vix_data.get('last', 0)
        dxy_trend = correlations.get('DXY', {}).get('trend', 'neutral')
        gold_trend = correlations.get('Gold', {}).get('trend', 'neutral')
        oil_trend = correlations.get('Oil', {}).get('trend', 'neutral')
        copper_trend = correlations.get('Copper', {}).get('trend', 'neutral')
        
        regime = 'neutral'
        if vix_trend == 'bearish' and dxy_trend == 'bearish':
            regime = 'risk-on'
        elif vix_trend == 'bullish' and dxy_trend == 'bullish':
            regime = 'risk-off'
            
        # Narrative detection (Phase 4 Production Hardening)
        narratives = {
            'policy_divergence': False,
            'fiscal_dominance': False,
            'safe_haven_repricing': False,
            'commodity_sensitivity': False
        }
        
        # 1. Safe Haven Re-pricing
        if vix_value > 25 or (vix_trend == 'bullish' and gold_trend == 'bullish'):
            narratives['safe_haven_repricing'] = True
            
        # 2. Commodity Sensitivity
        if oil_trend != 'neutral' or copper_trend != 'neutral':
            narratives['commodity_sensitivity'] = True
            
        # 3. Policy Divergence (BoJ vs Fed as proxy)
        jp10y_trend = correlations.get('JP10Y', {}).get('trend', 'neutral')
        us10y_trend = correlations.get('US10Y', {}).get('trend', 'neutral')
        if jp10y_trend != us10y_trend and jp10y_trend != 'neutral' and us10y_trend != 'neutral':
            narratives['policy_divergence'] = True

        # 4. Fiscal Dominance (Yields rising while DXY flat/falling)
        if us10y_trend == 'bullish' and dxy_trend != 'bullish':
            narratives['fiscal_dominance'] = True
            
        de10y = correlations.get('DE10Y', {}).get('last', 0)
        uk10y = correlations.get('UK10Y', {}).get('last', 0)
        us10y = correlations.get('US10Y', {}).get('last', 0)
        
        return {
            'regime': regime,
            'indicators': correlations,
            'narratives': narratives,
            'spreads': {
                'DE_US': de10y - us10y,
                'UK_US': uk10y - us10y,
                'DE_UK': de10y - uk10y
            }
        }

    def calculate_correlations(self, asset_data):
        results = {}
        for name, df in asset_data.items():
            if df.empty: continue
            last_close = float(df['Close'].iloc[-1])
            lookback = 24 if len(df) > 24 else 1
            prev_close = float(df['Close'].iloc[-lookback-1]) if len(df) > lookback else float(df['Close'].iloc[0])
            
            change_pct = (last_close - prev_close) / prev_close if prev_close != 0 else 0
            results[name] = {
                'last': last_close,
                'change_pct': float(change_pct),
                'trend': 'bullish' if change_pct > 0.005 else ('bearish' if change_pct < -0.005 else 'neutral')
            }
        return results

    def analyze_cb_sentiment(self, text):
        if not text: return 0
        vs = self.analyzer.polarity_scores(text[:4000])
        return vs['compound']

    def get_latest_cb_speeches(self):
        speeches = []
        try:
            url = "https://www.federalreserve.gov/newsevents/speeches.htm"
            headers = {'User-Agent': 'Mozilla/5.0'}
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'html.parser')
                links = soup.find_all('a', href=lambda x: x and '/newsevents/speech/' in x)
                for link in links[:2]:
                    title = link.get_text(strip=True)
                    if not title: continue
                    full_link = "https://www.federalreserve.gov" + link['href']
                    transcript = self.fetch_transcript(full_link)
                    speeches.append({
                        'title': title, 
                        'link': full_link, 
                        'source': 'FED',
                        'content': transcript
                    })
        except Exception as e:
            logging.debug(f"Error fetching Fed speeches: {e}")
        return speeches

    def fetch_transcript(self, url):
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'html.parser')
                content_div = soup.select_one('.col-md-8') or soup.select_one('#article') or soup.select_one('.post-content')
                if content_div:
                    return content_div.get_text(separator=' ', strip=True)
        except: pass
        return ""

    def score_latest_speeches(self):
        speeches = self.get_latest_cb_speeches()
        scored_speeches = []
        for s in speeches:
            try:
                text_to_score = s['content'] if s['content'] else s['title']
                score = self.analyze_cb_sentiment(text_to_score)
                s['sentiment_score'] = score
                scored_speeches.append(s)
            except: continue
        return scored_speeches

if __name__ == "__main__":
    ma = MacroAlpha()
    print("Fetching cross-asset data...")
    assets = ma.get_cross_asset_data()
    results = ma.calculate_macro_filters()
    
    print("Cross-Asset Correlations:")
    for k, v in results['indicators'].items():
        print(f"{k}: {v['trend']} ({v['change_pct']:.2%})")
    
    print("\nNarratives Detected:")
    for k, v in results['narratives'].items():
        print(f"{k}: {v}")
    
    print("\nScoring latest speeches...")
    scored = ma.score_latest_speeches()
    if not scored:
        print("No recent speeches found or could not parse.")
    for s in scored:
        print(f"[{s['source']}] {s['title'][:50]}... Score: {s['sentiment_score']}")
