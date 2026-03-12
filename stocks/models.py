from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.contrib.postgres.fields import ArrayField
from django.utils import timezone

class Symbol(models.Model):
    """Stock symbols/tickers"""
    ticker = models.CharField(max_length=20, unique=True, db_index=True)
    company_name = models.CharField(max_length=200, blank=True)
    sector = models.CharField(max_length=100, blank=True)
    industry = models.CharField(max_length=100, blank=True)
    market_cap = models.BigIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    first_seen = models.DateField(null=True, blank=True)
    last_seen = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['ticker']

    def __str__(self):
        return self.ticker

class DailyPrice(models.Model):
    """Daily OHLCV price data"""
    symbol = models.ForeignKey(Symbol, on_delete=models.CASCADE, related_name='daily_prices')
    date = models.DateField(db_index=True)
    open = models.DecimalField(max_digits=15, decimal_places=4)
    high = models.DecimalField(max_digits=15, decimal_places=4)
    low = models.DecimalField(max_digits=15, decimal_places=4)
    close = models.DecimalField(max_digits=15, decimal_places=4)
    volume = models.BigIntegerField()

    # Calculated fields
    daily_return = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    daily_range = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)

    class Meta:
        unique_together = ['symbol', 'date']
        ordering = ['symbol', 'date']
        indexes = [
            models.Index(fields=['symbol', 'date']),
            models.Index(fields=['date']),
        ]

    def __str__(self):
        return f"{self.symbol.ticker} - {self.date}"

    def save(self, *args, **kwargs):
        # Calculate daily return and range
        if self.close and self.open:
            self.daily_return = ((self.close - self.open) / self.open) * 100
            self.daily_range = ((self.high - self.low) / self.open) * 100
        super().save(*args, **kwargs)

class IntradayPrice(models.Model):
    """Intraday price data for higher granularities"""
    GRANULARITY_CHOICES = [
        ('1min', '1 Minute'),
        ('15min', '15 Minutes'),
        ('1H', '1 Hour'),
        ('4H', '4 Hours'),
    ]

    symbol = models.ForeignKey(Symbol, on_delete=models.CASCADE, related_name='intraday_prices')
    datetime = models.DateTimeField(db_index=True)
    granularity = models.CharField(max_length=10, choices=GRANULARITY_CHOICES)
    open = models.DecimalField(max_digits=15, decimal_places=4)
    high = models.DecimalField(max_digits=15, decimal_places=4)
    low = models.DecimalField(max_digits=15, decimal_places=4)
    close = models.DecimalField(max_digits=15, decimal_places=4)
    volume = models.BigIntegerField()

    class Meta:
        unique_together = ['symbol', 'datetime', 'granularity']
        ordering = ['symbol', 'granularity', 'datetime']
        indexes = [
            models.Index(fields=['symbol', 'granularity', 'datetime']),
        ]

    def __str__(self):
        return f"{self.symbol.ticker} - {self.granularity} - {self.datetime}"

class PriceAlert(models.Model):
    """Custom price alerts for what-if analysis"""
    ALERT_TYPES = [
        ('above', 'Above Threshold'),
        ('below', 'Below Threshold'),
        ('cross_above', 'Cross Above'),
        ('cross_below', 'Cross Below'),
        ('volatility', 'Volatility Spike'),
    ]

    symbol = models.ForeignKey(Symbol, on_delete=models.CASCADE)
    alert_type = models.CharField(max_length=20, choices=ALERT_TYPES)
    threshold = models.DecimalField(max_digits=10, decimal_places=2)
    lookback_days = models.IntegerField(default=1)
    triggered_at = models.DateTimeField(null=True, blank=True)
    triggered_value = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.symbol.ticker} - {self.alert_type} - {self.threshold}%"

class TechnicalIndicator(models.Model):
    """Store pre-calculated technical indicators"""
    symbol = models.ForeignKey(Symbol, on_delete=models.CASCADE, related_name='indicators')
    date = models.DateField(db_index=True)

    # Moving averages
    sma_20 = models.DecimalField(max_digits=15, decimal_places=4, null=True)
    sma_50 = models.DecimalField(max_digits=15, decimal_places=4, null=True)
    sma_200 = models.DecimalField(max_digits=15, decimal_places=4, null=True)
    ema_20 = models.DecimalField(max_digits=15, decimal_places=4, null=True)

    # Volatility indicators
    bollinger_upper = models.DecimalField(max_digits=15, decimal_places=4, null=True)
    bollinger_lower = models.DecimalField(max_digits=15, decimal_places=4, null=True)
    atr_14 = models.DecimalField(max_digits=15, decimal_places=4, null=True)

    # Momentum indicators
    rsi_14 = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    macd = models.DecimalField(max_digits=15, decimal_places=4, null=True)
    macd_signal = models.DecimalField(max_digits=15, decimal_places=4, null=True)
    macd_histogram = models.DecimalField(max_digits=15, decimal_places=4, null=True)

    # Volume indicators
    volume_sma_20 = models.BigIntegerField(null=True)
    obv = models.BigIntegerField(null=True)

    # Volatility metrics
    volatility_30d = models.DecimalField(max_digits=10, decimal_places=4, null=True)
    volatility_90d = models.DecimalField(max_digits=10, decimal_places=4, null=True)
    beta = models.DecimalField(max_digits=10, decimal_places=4, null=True)

    class Meta:
        unique_together = ['symbol', 'date']
        ordering = ['symbol', 'date']

