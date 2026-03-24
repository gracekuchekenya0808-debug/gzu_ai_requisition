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

def is_admin_or_head(user):
    return user.is_staff or user.profile.role == 'head'



@login_required
def requisition_create(request):
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
    return render(request,'requisitions/requisition_detail.html', {'req': req})
# Removed duplicate dashboard function above


@login_required
@require_POST
def requisition_approve(request, pk):

    req = get_object_or_404(Requisition, pk=pk)

    # ✅ Permission: Only Admin OR Head of SAME department
    if not (
        request.user.is_staff or
        (request.user.profile.role == 'head' and
         request.user.profile.department == req.department)
    ):
        messages.error(request, "You are not allowed to approve this requisition.")
        return redirect('requisition_list')

    # ✅ Prevent re-approval
    if req.status in ['approved', 'rejected']:
        messages.warning(request, "This requisition has already been processed.")
        return redirect('requisition_detail', pk=pk)

    action = request.POST.get('action')
    comment = request.POST.get('comment', '')

    # ----------------------
    # ✅ APPROVE
    # ----------------------
    if action == 'approve':
        low_stock_items = []  # track items that go low

    # ✅ Loop through all items in requisition
    for req_item in req.items.all():
        item = req_item.item

        # 🚨 Prevent approving if stock is not enough
        if req_item.quantity > item.stock:
            messages.error(
                request,
                f"Not enough stock for {item.name}. Available: {item.stock}"
            )
            return redirect('requisition_detail', pk=req.id)

        # ✅ Deduct stock
        item.stock -= req_item.quantity
        item.save()

        # ⚠️ Check if stock is low
        if item.stock <= item.reorder_level:
            low_stock_items.append(item)

    # ✅ NOW approve (after stock update)
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

    # 🔔 Notify HOD(s) if stock is low
    for item in low_stock_items:
        hods = Profile.objects.filter(
            role='head',
            department=req.department
        )

        for hod in hods:
            Notification.objects.create(
                user=hod.user,
                message=f"⚠️ Low stock alert: {item.name} has only {item.stock} left."
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
def requisition_fulfill(request, pk):
    req = get_object_or_404(Requisition, pk=pk)
    req.status = 'fulfilled'
    req.save()
    from .models import Fulfillment, Notification
    Fulfillment.objects.update_or_create(
        requisition=req,
        defaults={'fulfilled_by': request.user}
    )
    return redirect('requisition_detail', pk=pk)
@login_required


def delete_requisition(request, pk):
    req = get_object_or_404(Requisition, pk=pk)

    # Only admin or head can delete
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if not (request.user.is_staff or profile.role == 'head'):
        messages.error(request, "You do not have permission to delete this requisition.")
        return redirect('requisition_list')

    # ❌ Cannot delete after approval
    if req.status == 'approved':
        messages.error(request, "Approved requisitions cannot be deleted.")
        return redirect('requisition_detail', pk=pk)

    # ✅ Soft delete instead of hard delete
    req.status = 'deleted'
    req.deleted_by = request.user
    req.save()

    # ✅ Create a notification for the requester
    Notification.objects.create(
        user=req.requester,
        message=f"Your requisition #{req.id} from {req.created.date()} was deleted by admin."
    )

    messages.success(request, f"Requisition #{req.id} has been deleted.")
    return redirect('requisition_list')
@login_required
@login_required
def requisition_list(request):
    user = request.user
    profile = getattr(user, 'profile', None)

    # 🔍 Get filter from URL (e.g. ?status=submitted)
    status_filter = request.GET.get('status')

    # 👑 Admin → sees ALL requisitions
    if user.is_staff:
        qs = Requisition.objects.all().order_by('-created')

    # 👨‍💼 HOD → only their department
    elif profile and profile.role == 'head' and profile.department:
        qs = Requisition.objects.filter(
            department=profile.department
        ).order_by('-created')

    # 👤 Normal user → only their own
    elif profile:
        qs = Requisition.objects.filter(
            requester=user
        ).order_by('-created')

    # ⚠️ Fallback (no profile)
    else:
        qs = Requisition.objects.none()

    # ✅ Apply status filter AFTER role filtering
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
def dashboard(request):

    # Safely get profile (avoids crash if missing)
    profile = getattr(request.user, 'profile', None)

    # ✅ Admin or HOD → see dashboard
    if request.user.is_staff or (profile and profile.role == 'head'):

        total = Requisition.objects.count()
        pending = Requisition.objects.filter(status='submitted').count()
        approved = Requisition.objects.filter(status='approved').count()
        rejected = Requisition.objects.filter(status='rejected').count()

        return render(request, 'requisitions/dashboard.html', {
            'total': total,
            'pending': pending,
            'approved': approved,
            'rejected': rejected
        })

    # ✅ Normal users → redirect instead of 403
    return redirect('requisition_list')
@login_required
def hod_view_stock(request):
    if not (request.user.profile.role == 'head'):
        raise PermissionDenied

    items = Item.objects.all().order_by('name')

    return render(request, "requisitions/hod_stock.html", {"items": items})    
    
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
    users = User.objects.all()
    return render(request, "requisitions/user_list.html", {"users": users})

# views.py



@login_required
def hod_print_requisitions(request):
    # Only HODs or Admins can access
    if not (request.user.is_staff or request.user.profile.role == 'head'):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied

    # If admin, show all requisitions, otherwise only HOD's department
    if request.user.is_staff:
        requisitions = Requisition.objects.all()
    else:
        requisitions = Requisition.objects.filter(department=request.user.profile.department)

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

        # 🔥 Role-based redirect
        if user.is_staff:
            return redirect('dashboard')
        elif user.profile.role == 'head':
            return redirect('dashboard')
        else:
            return redirect('requisition_list')

    return render(request, 'registration/login.html', {'form': form})