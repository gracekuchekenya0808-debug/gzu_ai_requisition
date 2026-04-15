from django.db import models
from django.contrib.auth.models import User
from django.utils.timezone import now

# ==============================
# ITEM
# ==============================
class Item(models.Model):
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=50, blank=True, null=True)
    unit = models.CharField(max_length=50, default='unit')
    description = models.TextField(blank=True)
    reorder_level = models.PositiveIntegerField(default=5)
    stock = models.PositiveIntegerField(default=0)

    def is_low_stock(self):
        return self.stock <= self.reorder_level

    def __str__(self):
        return self.name

# ==============================
# DEPARTMENT
# ==============================
class Department(models.Model):
    name = models.CharField(max_length=200)

    def __str__(self):
        return self.name

# ==============================
# PROFILE
# ==============================
class Profile(models.Model):
    ROLE_CHOICES = (
        ('admin', 'Admin'),
        ('head', 'Department Head'),
        ('user', 'User'),
    )

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='user')

    def __str__(self):
        return f"{self.user.username} - {self.role}"

# ==============================
# REQUISITION
# ==============================
class Requisition(models.Model):
    STATUS_CHOICES = [
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('fulfilled', 'Fulfilled'),
        ('deleted', 'Deleted'),
    ]

    requester = models.ForeignKey(User, on_delete=models.CASCADE, null=True)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True)

    created = models.DateTimeField(auto_now_add=True)
    request_date = models.DateField(default=now)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='submitted')
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Req {self.id} - {self.requester}"

# ==============================
# REQUISITION ITEMS
# ==============================
class RequisitionItem(models.Model):
    requisition = models.ForeignKey(
        Requisition,
        on_delete=models.CASCADE,
        related_name='items'   # FIXED HERE
    )
    item = models.ForeignKey(Item, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.quantity} x {self.item.name}"

# ==============================
# APPROVAL
# ==============================
class Approval(models.Model):
    requisition = models.OneToOneField(
        Requisition,
        on_delete=models.CASCADE,
        related_name='approval'
    )
    approver = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    approved = models.BooleanField()
    comment = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

# ==============================
# FULFILLMENT
# ==============================
class Fulfillment(models.Model):
    requisition = models.OneToOneField(
        Requisition,
        on_delete=models.CASCADE,
        related_name='fulfillment'
    )
    fulfilled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

# ==============================
# NOTIFICATIONS
# ==============================
class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Notification for {self.user.username} - {self.message[:20]}"