from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from datetime import datetime, timedelta
import numpy as np
from .models import Symbol, DailyPrice, TechnicalIndicator

@login_required
def test_chart_api(request, ticker):
    """Simple test endpoint to verify API is working"""
    try:
        symbol = get_object_or_404(Symbol, ticker=ticker)
        return JsonResponse({
            'status': 'ok',
            'message': f'API is working for {ticker}',
            'symbol_exists': True
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


@login_required
def symbol_detail(request, ticker):
    """Display detailed information for a specific symbol"""
    symbol = get_object_or_404(Symbol, ticker=ticker)

    # Get date range from query params if provided
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')

    # Get the original source (analysis table or direct)
    source = request.GET.get('source', 'direct')

    # Initialize variables with default values
    latest_price = None
    daily_change = 0
    day_low = 0
    day_high = 0
    volume = 0
    year_low = 0
    year_high = 0
    rsi = None
    macd = None
    atr = None
    volatility = 0

    # Get latest price and calculate metrics
    latest_price_obj = DailyPrice.objects.filter(symbol=symbol).order_by('-date').first()

    if latest_price_obj:
        latest_price = float(latest_price_obj.close)
        day_low = float(latest_price_obj.low)
        day_high = float(latest_price_obj.high)
        volume = latest_price_obj.volume

        # Calculate daily change
        prev_day = DailyPrice.objects.filter(
            symbol=symbol,
            date__lt=latest_price_obj.date
        ).order_by('-date').first()

        if prev_day:
            daily_change = ((float(latest_price_obj.close) - float(prev_day.close)) / float(prev_day.close)) * 100

    # Get 52-week range
    one_year_ago = timezone.now().date() - timedelta(days=365)
    year_prices = DailyPrice.objects.filter(
        symbol=symbol,
        date__gte=one_year_ago
    )

    if year_prices.exists():
        year_high = max(float(p.high) for p in year_prices)
        year_low = min(float(p.low) for p in year_prices)

    # Get technical indicators
    latest_indicators = TechnicalIndicator.objects.filter(
        symbol=symbol
    ).order_by('-date').first()

    if latest_indicators:
        rsi = float(latest_indicators.rsi_14) if latest_indicators.rsi_14 else None
        macd = float(latest_indicators.macd) if latest_indicators.macd else None
        atr = float(latest_indicators.atr_14) if latest_indicators.atr_14 else None

    # Calculate volatility
    prices_30d = list(DailyPrice.objects.filter(
        symbol=symbol
    ).order_by('-date')[:31])  # Get 31 days to calculate returns

    if len(prices_30d) > 1:
        returns = []
        for i in range(len(prices_30d) - 1):
            # Calculate return between consecutive days
            current_close = float(prices_30d[i].close)
            next_close = float(prices_30d[i + 1].close)
            if next_close > 0:
                ret = (current_close - next_close) / next_close
                returns.append(ret)

        if returns:
            volatility = np.std(returns) * np.sqrt(252) * 100

    context = {
        'symbol': symbol,
        'latest_price': latest_price if latest_price is not None else 0,
        'daily_change': daily_change,
        'volume': volume,
        'day_low': day_low,
        'day_high': day_high,
        'year_low': year_low,
        'year_high': year_high,
        'rsi': rsi,
        'macd': macd,
        'atr': atr,
        'volatility': volatility,
        'from_date': from_date,
        'to_date': to_date,
        'source': source,
        'range': request.GET.get('range', '1y'),
    }

    return render(request, 'stocks/symbol_detail.html', context)

@login_required
def chart_data_api(request, ticker):
    """API endpoint to get chart data for a symbol"""
    try:
        symbol = get_object_or_404(Symbol, ticker=ticker)

        # Get date range from request
        range_param = request.GET.get('range', '1y')
        start_date = request.GET.get('start')
        end_date = request.GET.get('end')

        print(f"Received request: range={range_param}, start={start_date}, end={end_date}")  # Debug log

        # Calculate date range based on parameters
        end = timezone.now().date()

        # If custom dates are provided, use them
        if start_date and end_date:
            try:
                start = datetime.strptime(start_date, '%Y-%m-%d').date()
                end = datetime.strptime(end_date, '%Y-%m-%d').date()
                print(f"Using custom dates: {start} to {end}")
            except (ValueError, TypeError) as e:
                print(f"Error parsing custom dates: {e}")
                # Fall back to range parameter
                range_days = {
                    '1m': 30,
                    '3m': 90,
                    '6m': 180,
                    '1y': 365,
                    '2y': 730,
                    '5y': 1825,
                    'max': 3650
                }
                days = range_days.get(range_param, 365)
                start = end - timedelta(days=days)
        else:
            # Use range parameter
            range_days = {
                '1m': 30,
                '3m': 90,
                '6m': 180,
                '1y': 365,
                '2y': 730,
                '5y': 1825,
                'max': 3650
            }
            days = range_days.get(range_param, 365)
            start = end - timedelta(days=days)
            print(f"Using range {range_param}: {start} to {end}")

        # Ensure start is not after end
        if start > end:
            start, end = end, start

        print(f"Final date range for {ticker}: {start} to {end}")

        # Get price data
        prices = DailyPrice.objects.filter(
            symbol=symbol,
            date__gte=start,
            date__lte=end
        ).order_by('date')

        if not prices.exists():
            # Try to get any available data for this symbol
            all_prices = DailyPrice.objects.filter(symbol=symbol).order_by('date')
            if all_prices.exists():
                first_date = all_prices.first().date
                last_date = all_prices.last().date
                return JsonResponse({'error': f'No price data available for {ticker} from {start} to {end}. Data available from {first_date} to {last_date}.'}, status=404)
            else:
                return JsonResponse({'error': f'No price data available for {ticker}'}, status=404)

        # Prepare basic OHLC data
        dates = [p.date.strftime('%Y-%m-%d') for p in prices]
        opens = [float(p.open) for p in prices]
        highs = [float(p.high) for p in prices]
        lows = [float(p.low) for p in prices]
        closes = [float(p.close) for p in prices]
        volumes = [p.volume for p in prices]

        # Calculate technical indicators
        data = {
            'symbol': ticker,
            'range': range_param,
            'start_date': start.strftime('%Y-%m-%d'),
            'end_date': end.strftime('%Y-%m-%d'),
            'actual_start_date': prices.first().date.strftime('%Y-%m-%d'),
            'actual_end_date': prices.last().date.strftime('%Y-%m-%d'),
            'dates': dates,
            'opens': opens,
            'highs': highs,
            'lows': lows,
            'closes': closes,
            'volumes': volumes,
            'data_points': len(dates)
        }

        # Add moving averages
        data['sma20'] = calculate_sma(closes, 20)
        data['sma50'] = calculate_sma(closes, 50)
        data['sma200'] = calculate_sma(closes, 200)

        # Add Bollinger Bands
        bb_upper, bb_lower = calculate_bollinger_bands(closes, 20)
        data['bb_upper'] = bb_upper
        data['bb_lower'] = bb_lower

        return JsonResponse(data)

    except Exception as e:
        print(f"Error in chart_data_api: {str(e)}")  # Debug log
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)

def calculate_sma(prices, period):
    """Calculate Simple Moving Average"""
    if len(prices) < period:
        return [None] * len(prices)

    sma = []
    for i in range(len(prices)):
        if i < period - 1:
            sma.append(None)
        else:
            avg = sum(prices[i-period+1:i+1]) / period
            sma.append(round(avg, 2))
    return sma


def calculate_bollinger_bands(prices, period=20, num_std=2):
    """Calculate Bollinger Bands"""
    if len(prices) < period:
        return [None] * len(prices), [None] * len(prices)

    upper = []
    lower = []

    for i in range(len(prices)):
        if i < period - 1:
            upper.append(None)
            lower.append(None)
        else:
            window = prices[i-period+1:i+1]
            sma = sum(window) / period
            std = np.std(window)
            upper.append(round(sma + num_std * std, 2))
            lower.append(round(sma - num_std * std, 2))

    return upper, lower
