from statsmodels.tsa.arima.model import ARIMA
import pandas as pd
from .models import Requisition, RequisitionItem, Item, Profile, Notification, Approval, Fulfillment
from django.core.mail import send_mail
from django.conf import settings
from django.contrib import messages
from django.db.models import Count, F, Sum
from django.contrib.auth.models import User
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache
import csv
from io import BytesIO
from .forms import RequisitionForm, RequisitionItemFormSet, StockForm
from .analytics import train_arima_model
import pandas as pd
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import Requisition, RequisitionItem

try:
    import matplotlib
    matplotlib.use('Agg')  # Use non-GUI backend for server-side chart generation
    import matplotlib.pyplot as plt
except ImportError:
    matplotlib = None
    plt = None


def is_admin_or_head(user):
    return user.is_staff or user.profile.role == 'head'



@login_required
def requisition_create(request):
    # ENSURE USER HAS A PROFILE AND DEPARTMENT
    profile = getattr(request.user, 'profile', None)
    if not profile or not profile.department:
        messages.error(request, "Your profile is not properly configured. Please contact an administrator to assign a department to your account.")
        return redirect('user_home')

    if request.method == 'POST':
        form = RequisitionForm(request.POST)
        formset = RequisitionItemFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            requisition = form.save(commit=False)

            # Assign logged-in user and department
            requisition.requester = request.user
            requisition.department = request.user.profile.department
            requisition.status = 'submitted'
            requisition.save()

            # Track if any item exceeds stock
            stock_error = False

            for item_form in formset:
                item_instance = item_form.save(commit=False)
                item_instance.requisition = requisition

                actual_item = item_instance.item  # The real Item object

                # Check stock
                if item_instance.quantity > actual_item.stock:
                    messages.error(
                        request,
                        f"Not enough stock for {actual_item.name}. "
                        f"Available: {actual_item.stock}, Requested: {item_instance.quantity}"
                    )
                    stock_error = True
                    continue  # Skip saving this item

                # Reduce stock
                actual_item.stock -= item_instance.quantity
                actual_item.save()

                # Save the requisition item
                item_instance.save()

            if stock_error:
                # Delete the requisition if any item failed
                requisition.delete()
                return redirect('requisition_create')

            messages.success(request, "Requisition created successfully!")
            return redirect('requisition_list')

    else:
        form = RequisitionForm()
        formset = RequisitionItemFormSet(queryset=RequisitionItem.objects.none())

    return render(request, 'requisitions/requisition_form.html', {
        'form': form,
        'formset': formset
    })


@login_required
@never_cache
def requisition_detail(request, pk):
    req = get_object_or_404(Requisition, pk=pk)
    user = request.user
    profile = getattr(user, 'profile', None)

    # Permission check (check profile role FIRST):
    # - HOD can view only their department's
    # - Regular user can view only their own
    # - Admin can view any
    if not (
        (profile and profile.role == 'head' and profile.department == req.department) or
        user == req.requester or
        user.is_staff
    ):
        messages.error(request, "You do not have permission to view this requisition.")
        return redirect('requisition_list')

    return render(request,'requisitions/requisition_detail.html', {'req': req})
# Removed duplicate dashboard function above


@login_required
@require_POST
def requisition_approve(request, pk):

    req = get_object_or_404(Requisition, pk=pk)

    # Permission: Only HOD of SAME department OR Admin (check HOD first)
    profile = getattr(request.user, 'profile', None)
    if not (
        (profile and profile.role == 'head' and profile.department == req.department) or
        request.user.is_staff
    ):
        messages.error(request, "You are not allowed to approve this requisition.")
        return redirect('requisition_list')

    # Prevent re-approval
    if req.status in ['approved', 'rejected']:
        messages.warning(request, "This requisition has already been processed.")
        return redirect('requisition_detail', pk=pk)

    action = request.POST.get('action')
    comment = request.POST.get('comment', '')

    # ----------------------
    # APPROVE
    # ----------------------
    if action == 'approve':
        low_stock_items = []  # track items that go low

        # Loop through all items in requisition
        for req_item in req.items.all():
            item = req_item.item

            # Prevent approving if stock is not enough
            if req_item.quantity > item.stock:
                messages.error(
                    request,
                    f"Not enough stock for {item.name}. Available: {item.stock}"
                )
                return redirect('requisition_detail', pk=req.id)

            # Deduct stock
            item.stock -= req_item.quantity
            item.save()

            # Check if stock is low
            if item.stock <= item.reorder_level:
                low_stock_items.append(item)

        # NOW approve (after stock update)
        req.status = 'approved'
        req.save()

        Approval.objects.update_or_create(
            requisition=req,
            defaults={
                'approver': request.user,
                'approved': True,
                'comment': comment
            }
        )

        messages.success(request, "Requisition approved and stock updated successfully.")

        # Notify HOD(s) if stock is low
        for item in low_stock_items:
            hods = Profile.objects.filter(
                role='head',
                department=req.department
            )

            for hod in hods:
                Notification.objects.create(
                    user=hod.user,
                    message=f"Low stock alert: {item.name} has only {item.stock} left."
                )

        subject = f"Requisition #{req.id} Approved"
        message = f"""
Hello {req.requester.username},

Your requisition #{req.id} has been APPROVED.

Stock has been updated.

Department: {req.department}
Approved by: {request.user.username}

Comment:
{comment}

GZU AI Requisition System
"""
        # Send email notification
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [req.requester.email],
            fail_silently=True,
        )

    # ----------------------
    # REJECT
    # ----------------------
    elif action == 'reject':
        req.status = 'rejected'
        req.save()

        Approval.objects.update_or_create(
            requisition=req,
            defaults={
                'approver': request.user,
                'approved': False,
                'comment': comment
            }
        )

        messages.success(request, "Requisition rejected.")

        subject = f"Requisition #{req.id} Rejected"
        message = f"""
Hello {req.requester.username},

Your requisition #{req.id} has been REJECTED.

Department: {req.department}
Rejected by: {request.user.username}

Comment:
{comment}

GZU AI Requisition System
"""
        # Send email notification
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [req.requester.email],
            fail_silently=True,
        )

    else:
        messages.error(request, "Invalid action.")
        return redirect('requisition_detail', pk=pk)

    return redirect('requisition_detail', pk=pk)

@login_required
@require_POST
def requisition_fulfill(request, pk):
    req = get_object_or_404(Requisition, pk=pk)

    # Permission: Only HOD of SAME department OR Admin (check HOD first)
    profile = getattr(request.user, 'profile', None)
    if not (
        (profile and profile.role == 'head' and profile.department == req.department) or
        request.user.is_staff
    ):
        messages.error(request, "You are not allowed to fulfill this requisition.")
        return redirect('requisition_list')

    req.status = 'fulfilled'
    req.save()
    Fulfillment.objects.update_or_create(
        requisition=req,
        defaults={'fulfilled_by': request.user}
    )
    messages.success(request, "Requisition marked as fulfilled.")
    return redirect('requisition_detail', pk=pk)

@login_required
def delete_requisition(request, pk):
    req = get_object_or_404(Requisition, pk=pk)

    # Permission: Only HOD of SAME department OR Admin (check HOD first)
    profile = getattr(request.user, 'profile', None)
    if not (
        (profile and profile.role == 'head' and profile.department == req.department) or
        request.user.is_staff
    ):
        messages.error(request, "You do not have permission to delete this requisition.")
        return redirect('requisition_list')

    # Cannot delete after approval
    if req.status == 'approved':
        messages.error(request, "Approved requisitions cannot be deleted.")
        return redirect('requisition_detail', pk=pk)

    # Soft delete instead of hard delete
    req.status = 'deleted'
    req.deleted_by = request.user
    req.save()

    # Create a notification for the requester
    Notification.objects.create(
        user=req.requester,
        message=f"Your requisition #{req.id} from {req.created.date()} was deleted by admin."
    )

    messages.success(request, f"Requisition #{req.id} has been deleted.")
    return redirect('requisition_list')

@login_required
@never_cache
def requisition_list(request):
    user = request.user
    profile = getattr(user, 'profile', None)

    # Get filter from URL (e.g. ?status=submitted)
    status_filter = request.GET.get('status')

    # Admin/staff should always see all requisitions first.
    if user.is_staff:
        qs = Requisition.objects.exclude(status='deleted').order_by('-created')

    # HOD → only their department (excluding deleted)
    elif profile and profile.role == 'head' and profile.department:
        qs = Requisition.objects.filter(
            department=profile.department
        ).exclude(status='deleted').order_by('-created')

    # Normal user → only their own (excluding deleted)
    elif profile:
        qs = Requisition.objects.filter(
            requester=user
        ).exclude(status='deleted').order_by('-created')

    # Fallback (no profile)
    else:
        qs = Requisition.objects.none()

    # Apply status filter AFTER role filtering
    if status_filter:
        qs = qs.filter(status=status_filter)

    return render(
        request,
        'requisitions/requisition_list.html',
        {
            'requisitions': qs,
            'current_status': status_filter  # optional (for UI display)
        }
    )
@login_required
def dashboard_data(request):
    # Example: monthly counts of requests per item for past 12 months
    import pandas as pd
    from django.db.models import Count
    # Build time series: aggregate RequisitionItem by month
    q = RequisitionItem.objects.select_related('requisition','item').all()
    rows = []
    for ri in q:
        rows.append({'item': ri.item.name, 'date': ri.requisition.created.date(), 'quantity': ri.quantity})
    if not rows:
        return JsonResponse({'labels': [], 'datasets': []})
    df = pd.DataFrame(rows)
    df['month'] = pd.to_datetime(df['date']).dt.to_period('M').dt.to_timestamp()
    monthly = df.groupby(['month','item'])['quantity'].sum().reset_index()
    # pick top 5 items overall
    top_items = monthly.groupby('item')['quantity'].sum().nlargest(5).index.tolist()
    labels = sorted(monthly['month'].drop_duplicates().dt.strftime('%Y-%m'))
    datasets = []
    for item in top_items:
        series = monthly[monthly['item']==item].set_index('month').reindex(
            pd.to_datetime(labels).to_period('M').dt.to_timestamp(), fill_value=0
        )['quantity'].tolist()
        datasets.append({'label': item, 'data': series})
    return JsonResponse({'labels': labels, 'datasets': datasets})

@login_required
def demand_chart_image(request):
    # Render demand chart as PNG image (server-side)
    if plt is None:
        return HttpResponse("Matplotlib is not installed on this server.", status=503)
    try:
        import pandas as pd
        
        # Get the data
        q = RequisitionItem.objects.select_related('requisition','item').all()
        rows = []
        for ri in q:
            rows.append({'item': ri.item.name, 'date': ri.requisition.created.date(), 'quantity': ri.quantity})
        
        if not rows:
            # Return a simple placeholder image
            plt.figure(figsize=(10, 6))
            plt.text(0.5, 0.5, 'No data available for chart', ha='center', va='center', fontsize=14)
            plt.axis('off')
            buffer = BytesIO()
            plt.savefig(buffer, format='png')
            buffer.seek(0)
            plt.close()
            return HttpResponse(buffer.getvalue(), content_type="image/png")
        
        df = pd.DataFrame(rows)
        df['month'] = pd.to_datetime(df['date']).dt.to_period('M').dt.to_timestamp()
        monthly = df.groupby(['month','item'])['quantity'].sum().reset_index()
        
        # Pick top 5 items
        top_items = monthly.groupby('item')['quantity'].sum().nlargest(5).index.tolist()
        labels = sorted(monthly['month'].drop_duplicates().dt.strftime('%Y-%m'))
        
        # Use timestamp index for reindexing without .dt on PeriodIndex
        label_index = pd.to_datetime(labels).to_period('M').to_timestamp()
        
        plt.figure(figsize=(10, 6))
        for item in top_items:
            series = monthly[monthly['item']==item].set_index('month').reindex(
                label_index, fill_value=0
            )['quantity'].tolist()
            plt.plot(labels, series, marker='o', label=item)
        
        plt.title('Item Demand Trends')
        plt.xlabel('Month')
        plt.ylabel('Quantity')
        plt.legend(loc='best')
        plt.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        # Save to buffer
        buffer = BytesIO()
        plt.savefig(buffer, format='png')
        buffer.seek(0)
        plt.close()
        
        return HttpResponse(buffer.getvalue(), content_type="image/png")
    except Exception as e:
        # Return error image
        plt.figure(figsize=(10, 6))
        plt.text(0.5, 0.5, f'Error generating chart: {str(e)}', ha='center', va='center', fontsize=12)
        plt.axis('off')
        buffer = BytesIO()
        plt.savefig(buffer, format='png')
        buffer.seek(0)
        plt.close()
        return HttpResponse(buffer.getvalue(), content_type="image/png")


def low_stock_items(request):

    low_stock = Item.objects.filter(stock__lte=F('reorder_level'))

    return render(request,
        "requisitions/low_stock.html",
        {"items": low_stock}
    )



@login_required
@never_cache
def dashboard(request):

    profile = getattr(request.user, 'profile', None)

    # ---------- COUNTS ----------
    if request.user.is_staff:
        qs = Requisition.objects.all()
    elif profile and profile.role == 'head':
        qs = Requisition.objects.filter(department=profile.department)
    else:
        return redirect('user_home')

    total = qs.count()
    pending = qs.filter(status='submitted').count()
    approved = qs.filter(status='approved').count()
    rejected = qs.filter(status='rejected').count()

    # ---------- TREND DATA ----------
    data = RequisitionItem.objects.values(
        'requisition__created',
        'quantity'
    )

    df = pd.DataFrame(data)

    history = []
    forecast = []

    if not df.empty:
        df['created'] = pd.to_datetime(df['requisition__created'])

        monthly_data = df.groupby(
            pd.Grouper(key='created', freq='M')
        )['quantity'].sum()

        history = monthly_data.tolist()

        # ARIMA or fallback
        if len(monthly_data) >= 3:
            try:
                model_fit, forecast_series = train_arima_model(monthly_data)
                forecast = forecast_series.tolist()
            except:
                last_value = history[-1]
                forecast = [last_value, last_value, last_value]
        else:
            last_value = history[-1] if history else 0
            forecast = [last_value, last_value, last_value]

    # ---------- RENDER ONCE ----------
    return render(request, 'requisitions/dashboard.html', {
        'total': total,
        'pending': pending,
        'approved': approved,
        'rejected': rejected,
        'history': history,
        'forecast': forecast
    })
from django.http import JsonResponse
import pandas as pd
from .models import RequisitionItem
from .analytics import train_arima_model

def arima_forecast(request):
    if plt is None:
        return HttpResponse("Matplotlib is not installed on this server.", status=503)

    data = RequisitionItem.objects.values(
        'requisition__created',
        'quantity'
    )

    df = pd.DataFrame(data)

    if df.empty:
        return HttpResponse("No data available for forecast.", status=204)

    df['created'] = pd.to_datetime(df['requisition__created'])

    monthly_data = df.groupby(
        pd.Grouper(key='created', freq='ME')
    )['quantity'].sum()

    # Create chart
    plt.figure(figsize=(10, 6))

    # Plot historical data
    plt.plot(range(len(monthly_data)), monthly_data.values, marker='o', 
             label='Historical Demand', linewidth=2, color='blue')

    # -------------------------------
    # CASE 1: Not enough data
    # -------------------------------
    if len(monthly_data) < 3:
        last_value = monthly_data.iloc[-1] if len(monthly_data) > 0 else 0
        forecast = [last_value, last_value, last_value]
    else:
        # -------------------------------
        # CASE 2: ARIMA
        # -------------------------------
        try:
            model_fit, forecast_series = train_arima_model(monthly_data)
            forecast = forecast_series.tolist()
        except Exception:
            # -------------------------------
            # CASE 3: ARIMA fails - fallback
            # -------------------------------
            last_value = monthly_data.iloc[-1]
            forecast = [last_value, last_value, last_value]

    # Plot forecast (next 3 months)
    forecast_x = range(len(monthly_data), len(monthly_data) + len(forecast))
    plt.plot(forecast_x, forecast, marker='s', linestyle='--', 
             label='Predicted Demand', linewidth=2, color='red')

    # Add vertical line to separate history from forecast
    plt.axvline(x=len(monthly_data) - 0.5, color='gray', linestyle=':', alpha=0.7)

    plt.title('AI Requisition Demand Forecast')
    plt.xlabel('Month')
    plt.ylabel('Quantity')
    plt.legend(loc='best')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()

    # Save to buffer and return PNG
    buffer = BytesIO()
    plt.savefig(buffer, format='png')
    buffer.seek(0)
    plt.close()

    return HttpResponse(buffer.getvalue(), content_type="image/png")
@staff_member_required
def user_list(request):
    users = User.objects.select_related('profile').all()
    return render(request, "requisitions/user_list.html", {"users": users})

# views.py



@login_required
def hod_print_requisitions(request):
    # Check profile role FIRST (before is_staff)
    profile = getattr(request.user, 'profile', None)
    
    # Only HODs or Admins can access
    if not (profile and profile.role == 'head' or request.user.is_staff):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied

    # If HOD, show only their department; if admin, show all
    if profile and profile.role == 'head':
        requisitions = Requisition.objects.filter(department=profile.department)
    else:
        requisitions = Requisition.objects.all()

    # Create CSV response
    import csv
    from django.http import HttpResponse

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="requisitions.csv"'

    writer = csv.writer(response)
    writer.writerow(['ID', 'Requester', 'Status', 'Created', 'Department'])

    for r in requisitions:
        writer.writerow([r.id, r.requester.username, r.status, r.created, r.department])

    return response

@login_required
def hod_view_stock(request):
    if not (request.user.is_staff or request.user.profile.role == 'head'):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied

    items = Item.objects.all().order_by('name')

    return render(request, "requisitions/hod_stock.html", {"items": items})

from django.contrib.auth import login
from django.contrib.auth.forms import AuthenticationForm

def login_view(request):
    form = AuthenticationForm(request, data=request.POST or None)

    if request.method == 'POST' and form.is_valid():
        user = form.get_user()
        login(request, user)

        # Role-based redirect
        if user.is_staff:
            return redirect('dashboard')
        elif user.profile.role == 'head':
            return redirect('dashboard')
        else:
            return redirect('user_home')

    return render(request, 'registration/login.html', {'form': form})

@login_required
def user_home(request):
    return render(request, 'requisitions/user_home.html')


@login_required
def user_requisition_list(request):
    user = request.user
    qs = Requisition.objects.filter(requester=user).order_by('-created')
    return render(request, 'requisitions/user_requisition_list.html', {'requisitions': qs})

@login_required
def print_requisition(request, pk):
    req = get_object_or_404(Requisition, pk=pk)
    user = request.user
    profile = getattr(user, 'profile', None)

    # Allow owner, HOD from same department, or admin (check HOD first)
    if not (
        (profile and profile.role == 'head' and profile.department == req.department) or
        user == req.requester or
        user.is_staff
    ):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied

    return render(request, 'requisitions/print_requisitions.html', {'req': req})


# ==============================
# DEPARTMENT USER MANAGEMENT (HOD ONLY)
# ==============================

@login_required
def manage_department_users(request):
    """View for HODs to manage users in their department"""
    profile = getattr(request.user, 'profile', None)
    
    # Only HODs can access this page
    if not (profile and profile.role == 'head' and profile.department):
        messages.error(request, "You do not have permission to manage users.")
        return redirect('dashboard')
    
    department = profile.department
    users_in_dept = User.objects.filter(profile__department=department).select_related('profile')
    
    return render(request, 'requisitions/manage_users.html', {
        'department': department,
        'users': users_in_dept
    })


@login_required
def add_department_user(request):
    """View for HODs to add users to their department"""
    profile = getattr(request.user, 'profile', None)
    
    # Only HODs can access this page
    if not (profile and profile.role == 'head' and profile.department):
        messages.error(request, "You do not have permission to add users.")
        return redirect('dashboard')
    
    department = profile.department
    
    if request.method == 'POST':
        from .forms import UserCreationForm, UserProfileForm
        user_form = UserCreationForm(request.POST)
        
        if user_form.is_valid():
            # Create the user
            user = user_form.save(commit=True)
            
            # Create profile for user
            from .models import Profile
            Profile.objects.get_or_create(
                user=user,
                defaults={
                    'department': department,
                    'role': 'user'  # Default role for new users
                }
            )
            
            messages.success(request, f"User {user.username} has been added to {department.name} department!")
            return redirect('manage_department_users')
        else:
            for field, errors in user_form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        from .forms import UserCreationForm
        user_form = UserCreationForm()
    
    return render(request, 'requisitions/add_user.html', {
        'department': department,
        'form': user_form
    })


@login_required
def delete_department_user(request, user_id):
    """View for HODs to delete users from their department"""
    profile = getattr(request.user, 'profile', None)
    user_to_delete = get_object_or_404(User, id=user_id)
    user_profile = getattr(user_to_delete, 'profile', None)
    
    # Only HODs can delete users
    if not (profile and profile.role == 'head' and profile.department):
        messages.error(request, "You do not have permission to delete users.")
        return redirect('dashboard')
    
    # Can only delete users from their own department
    if not user_profile or user_profile.department != profile.department:
        messages.error(request, "You can only delete users from your own department.")
        return redirect('manage_department_users')
    
    # Cannot delete yourself
    if user_to_delete == request.user:
        messages.error(request, "You cannot delete your own account.")
        return redirect('manage_department_users')
    
    # Soft delete: deactivate the user
    username = user_to_delete.username
    user_to_delete.is_active = False
    user_to_delete.save()
    
    messages.success(request, f"User {username} has been deactivated.")
    return redirect('manage_department_users')


@login_required
def activate_department_user(request, user_id):
    """Activate a user in the HOD department user list"""
    profile = getattr(request.user, 'profile', None)
    user_to_activate = get_object_or_404(User, id=user_id)
    user_profile = getattr(user_to_activate, 'profile', None)

    if not (profile and profile.role == 'head' and profile.department):
        messages.error(request, "You do not have permission to activate users.")
        return redirect('dashboard')

    if not user_profile or user_profile.department != profile.department:
        messages.error(request, "You can only activate users from your own department.")
        return redirect('manage_department_users')

    if user_to_activate == request.user:
        messages.error(request, "You cannot change your own account status here.")
        return redirect('manage_department_users')

    user_to_activate.is_active = True
    user_to_activate.save()
    messages.success(request, f"User {user_to_activate.username} has been activated.")
    return redirect('manage_department_users')


@staff_member_required
def activate_user(request, user_id):
    """View for admin to activate users"""
    user_to_activate = get_object_or_404(User, id=user_id)
    
    # Cannot activate yourself if you're already active (but allow if inactive)
    if user_to_activate == request.user and user_to_activate.is_active:
        messages.error(request, "You cannot modify your own active status.")
        return redirect('user_list')
    
    # Activate the user
    username = user_to_activate.username
    user_to_activate.is_active = True
    user_to_activate.save()
    
    messages.success(request, f"User {username} has been activated.")
    return redirect('user_list')


@staff_member_required
def deactivate_user(request, user_id):
    """View for admin to deactivate users"""
    user_to_deactivate = get_object_or_404(User, id=user_id)
    
    # Cannot deactivate yourself
    if user_to_deactivate == request.user:
        messages.error(request, "You cannot deactivate your own account.")
        return redirect('user_list')
    
    # Deactivate the user
    username = user_to_deactivate.username
    user_to_deactivate.is_active = False
    user_to_deactivate.save()
    
    messages.success(request, f"User {username} has been deactivated.")
    return redirect('user_list')


def normalize_item_name(name):
    import re
    return re.sub(r'[^a-z0-9]', '', name.lower())


def find_or_merge_existing_item(name):
    normalized = normalize_item_name(name)
    matches = [item for item in Item.objects.all() if normalize_item_name(item.name) == normalized]
    if not matches:
        return None

    primary = matches[0]
    for duplicate in matches[1:]:
        primary.stock += duplicate.stock
        if not primary.sku and duplicate.sku:
            primary.sku = duplicate.sku
        primary.reorder_level = max(primary.reorder_level, duplicate.reorder_level)
        duplicate.delete()

    primary.save()
    return primary


@login_required
def add_stock(request):

    profile = getattr(request.user, 'profile', None)

    # Restrict to HOD only
    if not (profile and profile.role == 'head'):
        raise PermissionDenied

    if request.method == 'POST':
        form = StockForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data['name'].strip()
            stock_amount = form.cleaned_data['stock']
            sku = form.cleaned_data['sku']
            reorder_level = form.cleaned_data['reorder_level']

            existing_item = find_or_merge_existing_item(name)

            if existing_item:
                existing_item.stock += stock_amount
                if sku:
                    existing_item.sku = sku
                existing_item.reorder_level = reorder_level
                existing_item.save()
                messages.success(request, f"Stock for '{existing_item.name}' has been updated by {stock_amount} units.")
            else:
                Item.objects.create(
                    name=name,
                    stock=stock_amount,
                    sku=sku,
                    reorder_level=reorder_level
                )
                messages.success(request, f"New stock item '{name}' has been added.")

            return redirect('hod_view_stock')
    else:
        form = StockForm()
    
    return render(request, 'requisitions/add_stock.html', {'form': form })

@login_required
def trends_view(request):
    profile = getattr(request.user, 'profile', None)
    req_items = RequisitionItem.objects.select_related('requisition', 'item')

    # HOD sees their own department trends; admin sees all departments.
    if profile and profile.role == 'head' and profile.department:
        req_items = req_items.filter(requisition__department=profile.department)

    rows = []
    for ri in req_items:
        rows.append(
            {
                'item': ri.item.name,
                'date': ri.requisition.created.date(),
                'quantity': ri.quantity,
            }
        )

    if not rows:
        return render(
            request,
            'requisitions/trends.html',
            {
                'top_item_names': [],
                'top_item_totals': [],
                'chosen_item_name': '',
                'history_labels': [],
                'history_values': [],
                'forecast_labels': [],
                'forecast_values': [],
                'future_item_names': [],
                'future_item_totals': [],
            },
        )

    df = pd.DataFrame(rows)
    df['month'] = pd.to_datetime(df['date']).dt.to_period('M').dt.to_timestamp()

    item_totals = (
        df.groupby('item')['quantity']
        .sum()
        .sort_values(ascending=False)
    )
    top_items = item_totals.head(5).index.tolist()

    top_item_names = top_items
    top_item_totals = [int(item_totals[item]) for item in top_items]
    chosen_item_name = top_items[0] if top_items else ''

    # Build ARIMA forecast per top item to estimate future most-requested items.
    future_item_totals = {}
    chosen_item_history_labels = []
    chosen_item_history_values = []
    chosen_item_forecast_labels = []
    chosen_item_forecast_values = []

    for idx, item_name in enumerate(top_items):
        item_df = df[df['item'] == item_name]
        monthly_data = (
            item_df.groupby('month')['quantity']
            .sum()
            .sort_index()
            .asfreq('MS', fill_value=0)
        )

        history_values = [int(v) for v in monthly_data.tolist()]
        history_labels = [d.strftime('%Y-%m') for d in monthly_data.index]

        if len(monthly_data) >= 3:
            try:
                _, forecast_series = train_arima_model(monthly_data)
                forecast_values = [max(0, int(round(v))) for v in forecast_series.tolist()]
            except Exception:
                last_value = history_values[-1] if history_values else 0
                forecast_values = [last_value, last_value, last_value]
        else:
            last_value = history_values[-1] if history_values else 0
            forecast_values = [last_value, last_value, last_value]

        future_item_totals[item_name] = int(sum(forecast_values))

        # Keep one top item detailed line chart (the most requested one).
        if idx == 0:
            chosen_item_history_labels = history_labels
            chosen_item_history_values = history_values
            if monthly_data.index.size:
                last_month = monthly_data.index[-1]
                chosen_item_forecast_labels = [
                    (last_month + pd.DateOffset(months=i)).strftime('%Y-%m')
                    for i in range(1, len(forecast_values) + 1)
                ]
            else:
                chosen_item_forecast_labels = [
                    f'Future {i}' for i in range(1, len(forecast_values) + 1)
                ]
            chosen_item_forecast_values = forecast_values

    sorted_future_items = sorted(
        future_item_totals.items(),
        key=lambda x: x[1],
        reverse=True,
    )
    future_item_names = [name for name, _ in sorted_future_items]
    future_item_values = [value for _, value in sorted_future_items]

    context = {
        'top_item_names': top_item_names,
        'top_item_totals': top_item_totals,
        'chosen_item_name': chosen_item_name,
        'history_labels': chosen_item_history_labels,
        'history_values': chosen_item_history_values,
        'forecast_labels': chosen_item_forecast_labels,
        'forecast_values': chosen_item_forecast_values,
        'future_item_names': future_item_names,
        'future_item_totals': future_item_values,
    }

    return render(request, 'requisitions/trends.html', context)