import numpy as np
from decimal import Decimal
from datetime import timedelta
from django.db.models import Avg, Max, Min, Q, F, OuterRef, Subquery
from stocks.models import Symbol, DailyPrice, TechnicalIndicator
from analysis.models import VolatilityAnalysis

class AnalysisTableService:
    """Service class for analysis table calculations"""

    def __init__(self, start_date, end_date, symbols=None, movement_threshold=5, time_period=30):
        self.start_date = start_date
        self.end_date = end_date
        self.symbols = symbols if symbols else Symbol.objects.filter(is_active=True)
        self.movement_threshold = movement_threshold
        self.time_period = time_period

    def get_analysis_data(self, min_volatility=0, max_volatility=100, movement_type=None, sector=None):
        """Get comprehensive analysis data for all symbols"""
        analysis_data = []

        # Filter symbols by sector if specified
        symbols_qs = self.symbols
        if sector:
            symbols_qs = symbols_qs.filter(sector=sector)

        for symbol in symbols_qs:
            try:
                # Get price data for the period
                prices = DailyPrice.objects.filter(
                    symbol=symbol,
                    date__gte=self.start_date,
                    date__lte=self.end_date
                ).order_by('date')

                if not prices.exists():
                    continue

                # Get latest price and technical indicators
                latest_price = prices.last()
                latest_indicators = TechnicalIndicator.objects.filter(
                    symbol=symbol,
                    date=self.end_date
                ).first()

                # Calculate various metrics
                data = {
                    'symbol': symbol,
                    'latest_price': float(latest_price.close) if latest_price and latest_price.close else None,
                    'change_1d': self._calculate_period_return(prices, 1),
                    'change_5d': self._calculate_period_return(prices, 5),
                    'change_20d': self._calculate_period_return(prices, 20),
                    'volatility_30d': self._calculate_volatility(prices, 30),
                    'volatility_regime': self._get_volatility_regime(symbol, self.end_date),
                    'max_drop': self._calculate_max_drop(prices),
                    'max_rise': self._calculate_max_rise(prices),
                    'drop_then_rise': self._calculate_drop_then_rise(prices, self.movement_threshold),
                    'avg_volume': float(prices.aggregate(Avg('volume'))['volume__avg']) if prices.exists() else None,
                    'rsi_14': float(latest_indicators.rsi_14) if latest_indicators and latest_indicators.rsi_14 else None,
                }

                # Apply volatility filters
                if data['volatility_30d'] is not None:
                    if data['volatility_30d'] < min_volatility or data['volatility_30d'] > max_volatility:
                        continue
                elif min_volatility > 0:  # If min volatility is set but we don't have data, skip
                    continue

                # Apply movement type filters
                if movement_type == 'rise' and (not data['max_rise'] or data['max_rise'] <= 0):
                    continue
                elif movement_type == 'fall' and (not data['max_drop'] or data['max_drop'] >= 0):
                    continue
                elif movement_type == 'drop_then_rise' and (not data['drop_then_rise'] or data['drop_then_rise'] <= 0):
                    continue

                analysis_data.append(data)

            except Exception as e:
                # Log error but continue processing other symbols
                print(f"Error processing {symbol.ticker}: {str(e)}")
                continue

        return analysis_data

    def _calculate_period_return(self, prices, days):
        """Calculate return over specified period"""
        if prices.count() < days + 1:
            return None

        prices_list = list(prices)
        start_price = float(prices_list[-days - 1].close)
        end_price = float(prices_list[-1].close)

        if start_price and end_price and start_price != 0:
            return float(((end_price - start_price) / start_price) * 100)
        return None

    def _calculate_volatility(self, prices, period):
        """Calculate historical volatility"""
        prices_list = list(prices)
        if len(prices_list) < period + 1:
            return None

        closes = [float(p.close) for p in prices_list[-period-1:]]
        returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes)) if closes[i-1] != 0]

        if returns and len(returns) > 1:
            return float(np.std(returns) * np.sqrt(252) * 100)
        return None

    def _get_volatility_regime(self, symbol, date):
        """Get volatility regime for symbol"""
        try:
            vol_analysis = VolatilityAnalysis.objects.filter(
                symbol=symbol,
                date__lte=date
            ).order_by('-date').first()

            if vol_analysis and vol_analysis.regime:
                return vol_analysis.regime
        except:
            pass
        return 'normal'

    def _calculate_max_drop(self, prices):
        """Calculate maximum percentage drop in the period"""
        prices_list = list(prices)
        if len(prices_list) < 2:
            return None

        max_drop = 0
        for i in range(len(prices_list)):
            for j in range(i + 1, len(prices_list)):
                if float(prices_list[i].high) > 0:
                    drop = float(((float(prices_list[j].low) - float(prices_list[i].high)) / float(prices_list[i].high)) * 100)
                    if drop < max_drop:
                        max_drop = drop
        return max_drop if max_drop < 0 else None

    def _calculate_max_rise(self, prices):
        """Calculate maximum percentage rise in the period"""
        prices_list = list(prices)
        if len(prices_list) < 2:
            return None

        max_rise = 0
        for i in range(len(prices_list)):
            for j in range(i + 1, len(prices_list)):
                if float(prices_list[i].low) > 0:
                    rise = float(((float(prices_list[j].high) - float(prices_list[i].low)) / float(prices_list[i].low)) * 100)
                    if rise > max_rise:
                        max_rise = rise
        return max_rise if max_rise > 0 else None

    def _calculate_drop_then_rise(self, prices, threshold):
        """Calculate instances where stock drops then rises within timeperiod"""
        prices_list = list(prices)
        if len(prices_list) < 10:
            return None

        best_drop_then_rise = 0

        for i in range(len(prices_list) - 5):
            # Look for a drop
            if float(prices_list[i].close) > 0:
                drop = float(((float(prices_list[i+1].close) - float(prices_list[i].close)) / float(prices_list[i].close)) * 100)

                if drop <= -threshold:  # Significant drop
                    # Look for subsequent rise within next few days
                    for j in range(i + 2, min(i + 6, len(prices_list))):
                        if float(prices_list[i+1].close) > 0:
                            rise = float(((float(prices_list[j].close) - float(prices_list[i+1].close)) / float(prices_list[i+1].close)) * 100)
                            if rise >= threshold:  # Significant rise after drop
                                total_move = rise + abs(drop)  # Net effect
                                if total_move > best_drop_then_rise:
                                    best_drop_then_rise = total_move
                                break

        return best_drop_then_rise if best_drop_then_rise > 0 else None

    def get_summary_stats(self, analysis_data):
        """Calculate summary statistics"""
        if not analysis_data:
            return {
                'total_symbols': 0,
                'avg_volatility': 0,
                'biggest_drop': 0,
                'biggest_rise': 0,
            }

        volatilities = [d['volatility_30d'] for d in analysis_data if d['volatility_30d'] is not None]
        drops = [d['max_drop'] for d in analysis_data if d['max_drop'] is not None]
        rises = [d['max_rise'] for d in analysis_data if d['max_rise'] is not None]

        return {
            'total_symbols': len(analysis_data),
            'avg_volatility': round(float(np.mean(volatilities)), 2) if volatilities else 0,
            'biggest_drop': round(float(min(drops)), 2) if drops else 0,
            'biggest_rise': round(float(max(rises)), 2) if rises else 0,
        }

