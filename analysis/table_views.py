from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import datetime, timedelta
from stocks.models import Symbol
from analysis.table_analysis import AnalysisTableService

@login_required
def analysis_table(request):
    """View for comprehensive analysis table"""

    # Get filter parameters
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    preset_period = request.GET.get('preset_period', '')
    selected_symbols = request.GET.getlist('symbols')
    movement_threshold = float(request.GET.get('movement_threshold', 5))
    time_period = int(request.GET.get('time_period', 30))
    min_volatility = float(request.GET.get('min_volatility', 0))
    max_volatility = float(request.GET.get('max_volatility', 100))
    movement_type = request.GET.get('movement_type', '')
    selected_sector = request.GET.get('sector', '')

    # Handle preset periods
    preset_dates = {
        'covid_2020': ('2020-02-19', '2020-03-23'),
        'gfc_2008': ('2007-10-09', '2009-03-09'),
        'dotcom_2000': ('2000-03-24', '2002-10-09'),
        'euro_debt_2011': ('2011-02-01', '2011-09-30'),
        'russian_1998': ('1998-07-17', '1998-08-31'),
        'asian_1997': ('1997-07-02', '1998-09-30'),
        'recession_1990': ('1990-07-16', '1990-10-11'),
        'black_monday_1987': ('1987-08-25', '1987-10-19'),
        'volcker_1980': ('1980-11-28', '1982-08-12'),
        'correction_2018': ('2018-09-20', '2018-12-24'),
        'bear_2022': ('2022-01-03', '2022-06-16'),
    }

        # Override dates if preset period selected
    if preset_period and preset_period in preset_dates:
        from_date, to_date = preset_dates[preset_period]


    # Set default dates if not provided
    if not to_date:
        to_date = timezone.now().date()
    else:
        # Convert string to date
        try:
            to_date = datetime.strptime(to_date, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            to_date = timezone.now().date()

    if not from_date:
        from_date = to_date - timedelta(days=time_period * 2)
    else:
        try:
            from_date = datetime.strptime(from_date, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            from_date = to_date - timedelta(days=time_period * 2)

    # Validate date range
    if from_date > to_date:
        # Swap dates if invalid
        from_date, to_date = to_date, from_date

    # Get symbols queryset
    symbols = Symbol.objects.filter(is_active=True)
    if selected_symbols:
        symbols = symbols.filter(ticker__in=selected_symbols)

    # Initialize analysis service
    service = AnalysisTableService(
        start_date=from_date,
        end_date=to_date,
        symbols=symbols,
        movement_threshold=movement_threshold,
        time_period=time_period
    )

    # Get analysis data
    analysis_data = service.get_analysis_data(
        min_volatility=min_volatility,
        max_volatility=max_volatility,
        movement_type=movement_type,
        sector=selected_sector if selected_sector else None
    )

    # Get summary stats
    summary_stats = service.get_summary_stats(analysis_data)

    # Get unique sectors for filter dropdown
    sectors = Symbol.objects.filter(is_active=True).exclude(
        sector=''
    ).values_list('sector', flat=True).distinct().order_by('sector')

    context = {
        'analysis_data': analysis_data,
        'symbols': Symbol.objects.filter(is_active=True).order_by('ticker'),
        'selected_symbols': selected_symbols,
        'from_date': from_date.strftime('%Y-%m-%d') if from_date else '',
        'to_date': to_date.strftime('%Y-%m-%d') if to_date else '',
        'movement_threshold': movement_threshold,
        'time_period': time_period,
        'min_volatility': min_volatility,
        'max_volatility': max_volatility,
        'movement_type': movement_type,
        'selected_sector': selected_sector,
        'sectors': sectors,
        'preset_period': preset_period,
        **summary_stats,
    }

    return render(request, 'analysis/analysis_table.html', context)
