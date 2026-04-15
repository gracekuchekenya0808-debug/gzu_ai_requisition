from statsmodels.tsa.arima.model import ARIMA
import pandas as pd
import matplotlib.pyplot as plt
from io import BytesIO
from django.http import HttpResponse
from .models import Requisition, RequisitionItem
from django.core.mail import send_mail
from django.conf import settings
from django.contrib import messages
from django.db.models import Count
from django.contrib.auth.models import User
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import F
from .models import Item
from django.core.exceptions import PermissionDenied
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
import csv

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Requisition, RequisitionItem, Item, Approval
from .forms import RequisitionForm, RequisitionItemFormSet
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Sum
from django.views.decorators.http import require_POST

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .forms import RequisitionForm, RequisitionItemFormSet
from .models import Requisition, RequisitionItem, Item, Profile, Notification
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.core.exceptions import PermissionDenied
from .forms import StockForm

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
# Mark fulfilled
@login_required
@require_POST
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
    from .models import Fulfillment, Notification
    Fulfillment.objects.update_or_create(
        requisition=req,
        defaults={'fulfilled_by': request.user}
    )
    messages.success(request, "Requisition marked as fulfilled.")
    return redirect('requisition_detail', pk=pk)
@login_required


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
def requisition_list(request):
    user = request.user
    profile = getattr(user, 'profile', None)

    # Get filter from URL (e.g. ?status=submitted)
    status_filter = request.GET.get('status')

    # Check profile role FIRST (before is_staff)
    # HOD → only their department (excluding deleted)
    if profile and profile.role == 'head' and profile.department:
        qs = Requisition.objects.filter(
            department=profile.department
        ).exclude(status='deleted').order_by('-created')

    # Admin → sees ALL requisitions (except deleted)
    elif user.is_staff:
        qs = Requisition.objects.exclude(status='deleted').order_by('-created')

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


def low_stock_items(request):

    low_stock = Item.objects.filter(stock__lte=F('reorder_level'))

    return render(request,
        "requisitions/low_stock.html",
        {"items": low_stock}
    )


@login_required
@login_required
def dashboard(request):

    profile = getattr(request.user, 'profile', None)

    # Check profile role FIRST (before is_staff)
    # HOD
    if profile and profile.role == 'head':
        return render(request, 'requisitions/dashboard.html', {
            'total': Requisition.objects.filter(department=profile.department).count(),
            'pending': Requisition.objects.filter(status='submitted', department=profile.department).count(),
            'approved': Requisition.objects.filter(status='approved', department=profile.department).count(),
            'rejected': Requisition.objects.filter(status='rejected', department=profile.department).count()
        })

    # Admin
    if request.user.is_staff:
        return render(request, 'requisitions/dashboard.html', {
            'total': Requisition.objects.count(),
            'pending': Requisition.objects.filter(status='submitted').count(),
            'approved': Requisition.objects.filter(status='approved').count(),
            'rejected': Requisition.objects.filter(status='rejected').count()
        })

    # NORMAL USER
    return redirect('user_home')

@login_required    
def arima_forecast(request):

    # Get requisition items with requisition date
    data = RequisitionItem.objects.values(
        'requisition__created',
        'quantity'
    )

    # Convert to DataFrame
    df = pd.DataFrame(data)

    if df.empty:
        return HttpResponse("Not enough data for forecasting.")

    # Convert date column
    df['created'] = pd.to_datetime(df['requisition__created'])

    # Aggregate quantity per month
    monthly_data = df.groupby(
        pd.Grouper(key='created', freq='M')
    )['quantity'].sum()

    # Fit ARIMA model
    model = ARIMA(monthly_data, order=(1,1,1))
    model_fit = model.fit()

    # Forecast next 3 months
    forecast = model_fit.forecast(steps=3)

    # Plot historical + forecast
    plt.figure(figsize=(8,5))

    monthly_data.plot(label="Historical Demand")
    forecast.plot(label="Predicted Demand")

    plt.title("AI Requisition Demand Forecast")
    plt.xlabel("Month")
    plt.ylabel("Quantity")
    plt.legend()

    # Save graph to memory
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