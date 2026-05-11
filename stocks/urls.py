from django.urls import path
from . import views

app_name = 'stocks'

urlpatterns = [
    #path('', views.dashboard, name='dashboard'),
    path('<str:ticker>/', views.symbol_detail, name='symbol_detail'),
    path('api/chart-data/<str:ticker>/', views.chart_data_api, name='chart_data_api'),
    path('api/test/<str:ticker>/', views.test_chart_api, name='test_chart_api'),
]
