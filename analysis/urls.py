from django.urls import path
from . import views, table_views

app_name = 'analysis'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('movement/', views.movement_analysis, name='movement'),
    path('volatility/', views.volatility_analysis, name='volatility'),
    path('what-if/', views.what_if_analysis, name='what_if'),
    path('table/', table_views.analysis_table, name='analysis_table'),
]
