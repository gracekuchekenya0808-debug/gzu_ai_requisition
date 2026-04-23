from django.urls import path
from . import views

urlpatterns = [
    path('', views.requisition_list, name='requisition_list'),
    path('create/', views.requisition_create, name='requisition_create'),
    path('<int:pk>/', views.requisition_detail, name='requisition_detail'),
    path('<int:pk>/approve/', views.requisition_approve, name='requisition_approve'),
    path('<int:pk>/fulfill/', views.requisition_fulfill, name='requisition_fulfill'),
    path('api/dashboard-data/', views.dashboard_data, name='dashboard_data'),
    path('api/demand-chart/', views.demand_chart_image, name='demand_chart_image'),
    path('forecast/', views.arima_forecast, name='arima_forecast'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('users/', views.user_list, name='user_list'),
    path("low-stock/", views.low_stock_items, name="low_stock"),
    path('requisition/<int:pk>/delete/', views.delete_requisition, name='delete_requisition'),
    path('print-requisitions/', views.hod_print_requisitions, name='hod_print_requisitions'),
    path('stock/', views.hod_view_stock, name='hod_view_stock'),
    path('home/', views.user_home, name='user_home'),
    path('my-requisitions/', views.user_requisition_list, name='user_requisition_list'),
    path('requisition/<int:pk>/print/', views.print_requisition, name='print_requisition'),
    
    # Department User Management (HOD only)
    path('manage-users/', views.manage_department_users, name='manage_department_users'),
    path('add-user/', views.add_department_user, name='add_department_user'),
    path('delete-user/<int:user_id>/', views.delete_department_user, name='delete_department_user'),
    path('activate-user/<int:user_id>/', views.activate_department_user, name='activate_department_user'),
    
    # Admin User Management
    path('users/activate/<int:user_id>/', views.activate_user, name='activate_user'),
    path('users/deactivate/<int:user_id>/', views.deactivate_user, name='deactivate_user'),
    
    path('add-stock/', views.add_stock, name='add_stock'),
    path('trend/', views.arima_forecast, name='trend'),
    path('trends/', views.trends_view, name='trends'),
    
]
