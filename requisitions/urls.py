from django.urls import path
from . import views

urlpatterns = [
    path('', views.requisition_list, name='requisition_list'),
    path('create/', views.requisition_create, name='requisition_create'),
    path('<int:pk>/', views.requisition_detail, name='requisition_detail'),
    path('<int:pk>/approve/', views.requisition_approve, name='requisition_approve'),
    path('<int:pk>/fulfill/', views.requisition_fulfill, name='requisition_fulfill'),
    path('api/dashboard-data/', views.dashboard_data, name='dashboard_data'),
    path('forecast/', views.arima_forecast, name='forecast'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('users/', views.user_list, name='user_list'),
    path("low-stock/", views.low_stock_items, name="low_stock"),
    # Removed duplicate dashboard_data and forecast paths
    path('requisition/<int:pk>/delete/', views.delete_requisition, name='delete_requisition'),
    path('print-requisitions/', views.hod_print_requisitions, name='hod_print_requisitions'),
    path('stock/', views.hod_view_stock, name='hod_view_stock'),
    path('forecast/', views.arima_forecast, name='arima_forecast'),
    path('requisitions/', views.requisition_list, name='requisition_list'),
]
