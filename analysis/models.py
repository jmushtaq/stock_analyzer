from django.db import models
from django.contrib.postgres.fields import ArrayField, JSONField
from stocks.models import Symbol

class PriceMovementAnalysis(models.Model):
    """Track significant price movements for analysis"""
    symbol = models.ForeignKey(Symbol, on_delete=models.CASCADE)
    date = models.DateField()
    movement_type = models.CharField(max_length=20, choices=[
        ('rise', 'Rise'),
        ('fall', 'Fall'),
    ])

    # Movement details
    threshold_pct = models.DecimalField(max_digits=10, decimal_places=2)
    actual_movement_pct = models.DecimalField(max_digits=10, decimal_places=2)
    start_price = models.DecimalField(max_digits=15, decimal_places=4)
    end_price = models.DecimalField(max_digits=15, decimal_places=4)

    # Context
    volume_during_move = models.BigIntegerField()
    avg_volume_prev_20d = models.BigIntegerField()

    # Subsequent performance
    subsequent_1d_pct = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    subsequent_5d_pct = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    subsequent_20d_pct = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', 'symbol']
        indexes = [
            models.Index(fields=['movement_type', 'threshold_pct']),
            models.Index(fields=['date']),
        ]

    def __str__(self):
        return f"{self.symbol.ticker} - {self.date} - {self.movement_type} {self.actual_movement_pct}%"

class VolatilityAnalysis(models.Model):
    """Volatility metrics by symbol and period"""
    symbol = models.ForeignKey(Symbol, on_delete=models.CASCADE)
    date = models.DateField()

    # Historical volatility
    hv_10d = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    hv_30d = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    hv_60d = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)

    # Volatility percentiles
    hv_percentile_30d = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    hv_percentile_90d = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # Average true range
    atr_14 = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    atr_percent = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)

    # Beta
    beta_spy_30d = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    beta_spy_90d = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)

    # Volatility regime
    regime = models.CharField(max_length=20, choices=[
        ('low', 'Low Volatility'),
        ('normal', 'Normal Volatility'),
        ('high', 'High Volatility'),
        ('extreme', 'Extreme Volatility'),
    ], default='normal')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['symbol', 'date']
        ordering = ['symbol', '-date']

    def __str__(self):
        return f"{self.symbol.ticker} - {self.date} - HV: {self.hv_30d}%"

class CorrelationMatrix(models.Model):
    """Store correlation matrices for what-if analysis"""
    date = models.DateField()
    period_days = models.IntegerField()
    symbols = ArrayField(models.CharField(max_length=20))
    correlation_data = models.JSONField()  # Store correlation matrix
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['date', 'period_days']

    def __str__(self):
        return f"Correlation Matrix - {self.date} ({self.period_days} days)"

class WhatIfScenario(models.Model):
    """User-defined what-if scenarios"""
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_public = models.BooleanField(default=False)

    # Scenario parameters
    symbols = ArrayField(models.CharField(max_length=20))
    start_date = models.DateField()
    end_date = models.DateField()

    # Scenario rules (JSON structure for flexible rules)
    rules = models.JSONField(default=dict, help_text="""
        {
            "entry": {
                "type": "price_drop",
                "threshold": -10,
                "lookback_days": 1
            },
            "exit": {
                "type": "price_target",
                "target": 5,
                "max_hold_days": 20
            },
            "filters": {
                "min_volume": 1000000,
                "max_volatility": 50
            }
        }
    """)

    # Results
    results = models.JSONField(default=dict, blank=True)
    total_trades = models.IntegerField(default=0)
    win_rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    avg_return = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    sharpe_ratio = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    max_drawdown = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    executed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - {self.created_at.date()}"

class AnalysisReport(models.Model):
    """Saved analysis reports"""
    REPORT_TYPES = [
        ('movement', 'Price Movement Analysis'),
        ('volatility', 'Volatility Analysis'),
        ('correlation', 'Correlation Analysis'),
        ('scenario', 'What-If Scenario'),
    ]

    name = models.CharField(max_length=200)
    report_type = models.CharField(max_length=20, choices=REPORT_TYPES)
    created_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Parameters used
    parameters = models.JSONField()

    # Results (store as JSON or file)
    results = models.JSONField()

    # Optional chart/image
    chart = models.ImageField(upload_to='reports/charts/', null=True, blank=True)
    csv_export = models.FileField(upload_to='reports/exports/', null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - {self.report_type} - {self.created_at.date()}"

