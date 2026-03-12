from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Avg, Count, Q, F
from django.utils import timezone
from datetime import timedelta
import json
import plotly.graph_objs as go
import plotly.utils
import numpy as np

from stocks.models import Symbol, DailyPrice
from analysis.models import PriceMovementAnalysis, VolatilityAnalysis, WhatIfScenario
from analysis.forms import MovementAnalysisForm, WhatIfForm
from analysis.services import PriceMovementAnalyzer, VolatilityCalculator, WhatIfAnalyzer

@login_required
def dashboard(request):
    """Main dashboard view"""
    context = {
        'total_symbols': Symbol.objects.count(),
        'active_symbols': Symbol.objects.filter(is_active=True).count(),
        'total_prices': DailyPrice.objects.count(),
        'latest_date': DailyPrice.objects.order_by('-date').first(),
    }

    # Recent significant movements
    last_week = timezone.now().date() - timedelta(days=7)
    context['recent_movements'] = PriceMovementAnalysis.objects.filter(
        date__gte=last_week
    ).select_related('symbol').order_by('-actual_movement_pct')[:10]

    return render(request, 'analysis/dashboard.html', context)

@login_required
def movement_analysis(request):
    """Analyze price movements"""
    form = MovementAnalysisForm(request.GET or None)
    results = None

    if form.is_valid():
        analyzer = PriceMovementAnalyzer(
            threshold_pct=form.cleaned_data['threshold'],
            min_volume_factor=form.cleaned_data['min_volume_factor']
        )

        movements = analyzer.find_significant_movements(
            form.cleaned_data['start_date'],
            form.cleaned_data['end_date']
        )

        # Save to database
        if movements:
            PriceMovementAnalysis.objects.bulk_create(movements)

            # Prepare statistics
            results = {
                'total_movements': len(movements),
                'avg_subsequent_1d': np.mean([m.subsequent_1d_pct for m in movements if m.subsequent_1d_pct is not None]) if any(m.subsequent_1d_pct for m in movements) else 0,
                'avg_subsequent_5d': np.mean([m.subsequent_5d_pct for m in movements if m.subsequent_5d_pct is not None]) if any(m.subsequent_5d_pct for m in movements) else 0,
                'avg_subsequent_20d': np.mean([m.subsequent_20d_pct for m in movements if m.subsequent_20d_pct is not None]) if any(m.subsequent_20d_pct for m in movements) else 0,
                'win_rate_5d': _calculate_win_rate(movements, 'subsequent_5d_pct'),
                'chart': _create_movement_chart(movements),
            }

    return render(request, 'analysis/movement_analysis.html', {
        'form': form,
        'results': results
    })

@login_required
def volatility_analysis(request):
    """Analyze volatility"""
    symbol = request.GET.get('symbol')
    period = int(request.GET.get('period', 30))

    # Get all symbols for the dropdown
    symbols = Symbol.objects.filter(is_active=True).order_by('ticker')

    context = {
        'symbols': symbols,
        'message': 'Select a symbol to analyze volatility.'
    }

    if symbol:
        try:
            prices = DailyPrice.objects.filter(
                symbol__ticker=symbol
            ).order_by('-date')[:period*2]

            if prices:
                calculator = VolatilityCalculator()
                hv = calculator.calculate_historical_volatility(list(prices), period)
                atr = calculator.calculate_atr(list(prices), 14)

                # Create volatility chart
                chart = _create_volatility_chart(prices, period)

                context.update({
                    'symbol': symbol,
                    'hv': hv,
                    'atr': atr,
                    'atr_percent': (atr / float(prices[0].close)) * 100 if atr and prices else None,
                    'chart': chart,
                    'period': period,
                })
            else:
                context['message'] = f'No price data found for {symbol}'
        except Exception as e:
            context['message'] = f'Error analyzing {symbol}: {str(e)}'

    return render(request, 'analysis/volatility_analysis.html', context)

@login_required
def what_if_analysis(request):
    """Create and run what-if scenarios"""
    if request.method == 'POST':
        form = WhatIfForm(request.POST)
        if form.is_valid():
            scenario = form.save(commit=False)
            scenario.created_by = request.user
            scenario.save()

            # Run analysis
            analyzer = WhatIfAnalyzer(scenario)
            results = analyzer.run_analysis()

            return render(request, 'analysis/what_if_results.html', {
                'scenario': scenario,
                'results': results
            })
    else:
        form = WhatIfForm()

    # List existing scenarios
    scenarios = WhatIfScenario.objects.filter(
        Q(created_by=request.user) | Q(is_public=True)
    ).order_by('-created_at')

    return render(request, 'analysis/what_if.html', {
        'form': form,
        'scenarios': scenarios
    })

# Helper functions (no 'self' parameter)
def _calculate_win_rate(movements, field):
    """Calculate win rate for subsequent returns"""
    wins = 0
    total = 0
    for m in movements:
        value = getattr(m, field, None)
        if value is not None:
            total += 1
            if value > 0:
                wins += 1
    return (wins / total) * 100 if total > 0 else 0

def _create_movement_chart(movements):
    """Create Plotly chart of movement analysis"""
    rises = [m for m in movements if m.movement_type == 'rise']
    falls = [m for m in movements if m.movement_type == 'fall']

    fig = go.Figure()

    # Add trace for rises
    rise_values = [float(m.subsequent_5d_pct) for m in rises if m.subsequent_5d_pct is not None]
    if rise_values:
        fig.add_trace(go.Box(
            y=rise_values,
            name='After Rise',
            boxmean='sd'
        ))

    # Add trace for falls
    fall_values = [float(m.subsequent_5d_pct) for m in falls if m.subsequent_5d_pct is not None]
    if fall_values:
        fig.add_trace(go.Box(
            y=fall_values,
            name='After Fall',
            boxmean='sd'
        ))

    fig.update_layout(
        title='5-Day Subsequent Returns Distribution',
        yaxis_title='Return %',
        showlegend=True
    )

    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

def _create_volatility_chart(prices, period):
    """Create volatility chart"""
    dates = [p.date for p in prices]
    closes = [float(p.close) for p in prices]

    # Calculate rolling volatility
    if len(closes) > 1:
        returns = [(closes[i] - closes[i-1]) / closes[i-1] * 100 for i in range(1, len(closes))]
        volatility = []
        for i in range(len(returns)):
            start = max(0, i - period + 1)
            if i - start > 1:
                vol = np.std(returns[start:i+1]) * np.sqrt(252)
            else:
                vol = 0
            volatility.append(vol)
    else:
        returns = []
        volatility = []

    fig = go.Figure()

    if volatility and len(dates) > 1:
        fig.add_trace(go.Scatter(
            x=dates[1:],
            y=volatility,
            mode='lines',
            name=f'{period}-Day Volatility'
        ))

    fig.add_trace(go.Scatter(
        x=dates,
        y=closes,
        mode='lines',
        name='Price',
        yaxis='y2'
    ))

    fig.update_layout(
        title='Price and Volatility',
        xaxis_title='Date',
        yaxis_title='Volatility %',
        yaxis2=dict(
            title='Price',
            overlaying='y',
            side='right'
        )
    )

    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
