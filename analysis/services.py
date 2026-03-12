import numpy as np
import pandas as pd
from decimal import Decimal
from datetime import timedelta
from django.db.models import Avg, StdDev, Count, Q, F
from stocks.models import DailyPrice, TechnicalIndicator
from analysis.models import PriceMovementAnalysis, VolatilityAnalysis, WhatIfScenario

class PriceMovementAnalyzer:
    """Analyze significant price movements"""

    def __init__(self, threshold_pct=10, min_volume_factor=1.5):
        self.threshold_pct = threshold_pct
        self.min_volume_factor = min_volume_factor

    def find_significant_movements(self, start_date, end_date):
        """Find all significant price movements in date range"""
        movements = []

        prices = DailyPrice.objects.filter(
            date__range=[start_date, end_date]
        ).select_related('symbol').order_by('symbol', 'date')

        # Group by symbol for processing
        symbols = set(p.symbol_id for p in prices)

        for symbol_id in symbols:
            symbol_prices = [p for p in prices if p.symbol_id == symbol_id]
            symbol_movements = self._analyze_symbol(symbol_prices)
            movements.extend(symbol_movements)

        return movements

    def _analyze_symbol(self, prices):
        """Analyze single symbol for significant movements"""
        movements = []

        for i in range(1, len(prices)):
            prev_close = float(prices[i-1].close)
            curr_close = float(prices[i].close)

            # Calculate price change
            change_pct = ((curr_close - prev_close) / prev_close) * 100

            # Check if movement exceeds threshold
            if abs(change_pct) >= self.threshold_pct:
                # Calculate average volume
                start_idx = max(0, i-20)
                avg_volume = sum(float(p.volume) for p in prices[start_idx:i]) / (i - start_idx)

                # Check volume condition
                if float(prices[i].volume) >= avg_volume * self.min_volume_factor:
                    movement = self._create_movement_record(
                        prices[i], change_pct, avg_volume, prices[i+1:] if i+1 < len(prices) else []
                    )
                    movements.append(movement)

        return movements

    def _create_movement_record(self, price, change_pct, avg_volume, subsequent_prices):
        """Create movement record with subsequent performance"""
        movement_type = 'rise' if change_pct > 0 else 'fall'

        # Calculate subsequent returns
        sub_1d = sub_5d = sub_20d = None

        if subsequent_prices:
            # 1-day subsequent
            if len(subsequent_prices) >= 1:
                sub_1d = ((float(subsequent_prices[0].close) - float(price.close)) / float(price.close)) * 100

            # 5-day subsequent
            if len(subsequent_prices) >= 5:
                sub_5d = ((float(subsequent_prices[4].close) - float(price.close)) / float(price.close)) * 100

            # 20-day subsequent
            if len(subsequent_prices) >= 20:
                sub_20d = ((float(subsequent_prices[19].close) - float(price.close)) / float(price.close)) * 100

        return PriceMovementAnalysis(
            symbol=price.symbol,
            date=price.date,
            movement_type=movement_type,
            threshold_pct=self.threshold_pct,
            actual_movement_pct=change_pct,
            start_price=price.close,
            end_price=price.close,  # This is the end price of the movement
            volume_during_move=price.volume,
            avg_volume_prev_20d=avg_volume,
            subsequent_1d_pct=sub_1d,
            subsequent_5d_pct=sub_5d,
            subsequent_20d_pct=sub_20d
        )

class VolatilityCalculator:
    """Calculate various volatility metrics"""

    @staticmethod
    def calculate_historical_volatility(prices, period=30):
        """Calculate historical volatility (annualized)"""
        if len(prices) < period + 1:
            return None

        # Calculate daily returns
        returns = []
        for i in range(1, len(prices)):
            ret = (float(prices[i].close) - float(prices[i-1].close)) / float(prices[i-1].close)
            returns.append(ret)

        # Calculate volatility
        recent_returns = returns[-period:]
        if len(recent_returns) < 2:
            return None

        std_dev = np.std(recent_returns)
        annualized = std_dev * np.sqrt(252)  # Annualize (252 trading days)

        return annualized * 100  # Return as percentage

    @staticmethod
    def calculate_atr(prices, period=14):
        """Calculate Average True Range"""
        if len(prices) < period + 1:
            return None

        true_ranges = []
        for i in range(1, len(prices)):
            high = float(prices[i].high)
            low = float(prices[i].low)
            prev_close = float(prices[i-1].close)

            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)

        # Calculate ATR (simple moving average of true ranges)
        atr = sum(true_ranges[-period:]) / period
        return atr

    @staticmethod
    def calculate_beta(symbol_prices, market_prices, period=90):
        """Calculate beta relative to market (e.g., SPY)"""
        if len(symbol_prices) < period + 1 or len(market_prices) < period + 1:
            return None

        # Align dates
        symbol_returns = []
        market_returns = []

        # This is simplified - in practice you'd need proper date alignment
        for i in range(1, min(len(symbol_prices), len(market_prices))):
            sym_ret = (float(symbol_prices[i].close) - float(symbol_prices[i-1].close)) / float(symbol_prices[i-1].close)
            mkt_ret = (float(market_prices[i].close) - float(market_prices[i-1].close)) / float(market_prices[i-1].close)
            symbol_returns.append(sym_ret)
            market_returns.append(mkt_ret)

        if len(symbol_returns) < period:
            return None

        # Calculate covariance and variance
        covariance = np.cov(symbol_returns[-period:], market_returns[-period:])[0][1]
        variance = np.var(market_returns[-period:])

        if variance == 0:
            return None

        beta = covariance / variance
        return beta

class WhatIfAnalyzer:
    """Perform what-if analysis on scenarios"""

    def __init__(self, scenario):
        self.scenario = scenario
        self.rules = scenario.rules

    def run_analysis(self):
        """Run the what-if scenario analysis"""
        # Get price data for symbols in range
        prices = DailyPrice.objects.filter(
            symbol__ticker__in=self.scenario.symbols,
            date__range=[self.scenario.start_date, self.scenario.end_date]
        ).select_related('symbol').order_by('symbol', 'date')

        # Convert to pandas for easier analysis
        df = self._create_dataframe(prices)

        # Apply entry rules
        entries = self._find_entries(df)

        # Apply exit rules
        trades = self._apply_exits(df, entries)

        # Calculate statistics
        results = self._calculate_statistics(trades)

        # Save results
        self.scenario.results = results
        self.scenario.total_trades = len(trades)
        self.scenario.win_rate = results.get('win_rate')
        self.scenario.avg_return = results.get('avg_return')
        self.scenario.sharpe_ratio = results.get('sharpe_ratio')
        self.scenario.max_drawdown = results.get('max_drawdown')
        self.scenario.executed_at = timezone.now()
        self.scenario.save()

        return results

    def _create_dataframe(self, prices):
        """Convert queryset to pandas DataFrame"""
        data = []
        for price in prices:
            data.append({
                'symbol': price.symbol.ticker,
                'date': price.date,
                'open': float(price.open),
                'high': float(price.high),
                'low': float(price.low),
                'close': float(price.close),
                'volume': price.volume
            })

        df = pd.DataFrame(data)
        df['date'] = pd.to_datetime(df['date'])
        return df

    def _find_entries(self, df):
        """Find entry signals based on rules"""
        entries = []
        entry_rule = self.rules.get('entry', {})

        if entry_rule.get('type') == 'price_drop':
            threshold = entry_rule.get('threshold', -10)
            lookback = entry_rule.get('lookback_days', 1)

            # Group by symbol
            for symbol in df['symbol'].unique():
                symbol_df = df[df['symbol'] == symbol].sort_values('date')

                # Calculate returns
                symbol_df['returns'] = symbol_df['close'].pct_change(lookback) * 100

                # Find drops below threshold
                entry_dates = symbol_df[symbol_df['returns'] <= threshold]['date'].tolist()
                entries.extend([(symbol, date) for date in entry_dates])

        return entries

    def _apply_exits(self, df, entries):
        """Apply exit rules to entries"""
        trades = []
        exit_rule = self.rules.get('exit', {})

        for symbol, entry_date in entries:
            # Get price data after entry
            symbol_df = df[df['symbol'] == symbol].sort_values('date')
            entry_idx = symbol_df[symbol_df['date'] == entry_date].index[0]
            subsequent = symbol_df.iloc[entry_idx+1:]

            if subsequent.empty:
                continue

            entry_price = symbol_df.loc[entry_idx, 'close']

            # Find exit
            exit_date = None
            exit_price = None
            exit_reason = None

            if exit_rule.get('type') == 'price_target':
                target = exit_rule.get('target', 5)
                max_days = exit_rule.get('max_hold_days', 20)

                for i, row in subsequent.iterrows():
                    days_held = (row['date'] - entry_date).days
                    if days_held > max_days:
                        # Exit at last price
                        exit_date = row['date']
                        exit_price = row['close']
                        exit_reason = 'timeout'
                        break

                    # Check if target reached
                    ret = (row['close'] - entry_price) / entry_price * 100
                    if ret >= target:
                        exit_date = row['date']
                        exit_price = row['close']
                        exit_reason = 'target'
                        break

            if exit_date and exit_price:
                trades.append({
                    'symbol': symbol,
                    'entry_date': entry_date,
                    'exit_date': exit_date,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'return_pct': (exit_price - entry_price) / entry_price * 100,
                    'exit_reason': exit_reason,
                    'days_held': (exit_date - entry_date).days
                })

        return trades

    def _calculate_statistics(self, trades):
        """Calculate statistics from trades"""
        if not trades:
            return {}

        returns = [t['return_pct'] for t in trades]
        winning_trades = [r for r in returns if r > 0]

        results = {
            'total_trades': len(trades),
            'win_rate': (len(winning_trades) / len(trades)) * 100 if trades else 0,
            'avg_return': np.mean(returns) if returns else 0,
            'median_return': np.median(returns) if returns else 0,
            'max_return': max(returns) if returns else 0,
            'min_return': min(returns) if returns else 0,
            'std_return': np.std(returns) if returns else 0,
            'sharpe_ratio': (np.mean(returns) / np.std(returns)) * np.sqrt(252) if np.std(returns) > 0 else 0,
            'max_drawdown': self._calculate_max_drawdown([t['return_pct'] for t in trades]),
            'avg_days_held': np.mean([t['days_held'] for t in trades]) if trades else 0,
        }

        # Exit reason breakdown
        exit_reasons = {}
        for trade in trades:
            reason = trade['exit_reason']
            exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

        results['exit_reasons'] = exit_reasons

        return results

    def _calculate_max_drawdown(self, returns):
        """Calculate maximum drawdown from a series of returns"""
        cumulative = np.cumprod(1 + np.array(returns) / 100)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - running_max) / running_max * 100
        return abs(min(drawdown)) if len(drawdown) > 0 else 0

