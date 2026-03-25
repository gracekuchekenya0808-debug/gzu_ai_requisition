#!/usr/bin/env python
"""
Debug script to check requisitions and user profiles
Run with: python manage.py shell < debug_requisitions.py
"""

from django.contrib.auth.models import User
from requisitions.models import Requisition, Profile, Department

print("=" * 60)
print("USER PROFILES AND DEPARTMENTS")
print("=" * 60)

for user in User.objects.all():
    profile = getattr(user, 'profile', None)
    if profile:
        print(f"User: {user.username}")
        print(f"  Role: {profile.role}")
        print(f"  Department: {profile.department}")
        print()
    else:
        print(f"User: {user.username} - NO PROFILE")
        print()

print("=" * 60)
print("REQUISITIONS")
print("=" * 60)

for req in Requisition.objects.all():
    print(f"Req #{req.id}:")
    print(f"  Requester: {req.requester}")
    print(f"  Department: {req.department}")
    print(f"  Status: {req.status}")
    print()

print("=" * 60)
print("NULLS CHECK - Requisitions with NULL department")
print("=" * 60)

null_reqs = Requisition.objects.filter(department__isnull=True)
print(f"Requisitions with NULL department: {null_reqs.count()}")
for req in null_reqs:
    print(f"  Req #{req.id}: Requester={req.requester}, Status={req.status}")
