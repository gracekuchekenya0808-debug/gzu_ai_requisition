# Department Filtering Fix - Summary

## Issues Fixed

### 1. **Requisition List View** 
   - Added filtering to exclude deleted requisitions for all user types
   - HODs now only see non-deleted requisitions from their department
   
### 2. **Requisition Create View**
   - Added validation to ensure users have a profile and department assigned
   - Users without a department assignment are redirected with an error message
   - This prevents requisitions from being created with NULL departments

### 3. **Department-Based Access Control**
   - All views (detail, approve, delete, fulfill, print) now verify HODs can only access requisitions from their own department
   - Regular users can only see/manage their own requisitions
   - Admins have full access

## How to Verify the Fix

### Option 1: Check the Database
Run this in Django shell:
```bash
cd c:\Users\DELL\Desktop\gzu_ai_requsition\gzu_requisitions
python manage.py shell < debug_requisitions.py
```

Look for:
- Users with proper Profile assignments
- Departments correctly assigned to each profile  
- Requisitions with matching department values

### Option 2: Manual Testing
1. Log in as Medical HOD
2. Go to requisitions list
3. Should ONLY see requisitions where `requisition.department == Medical`

### Option 3: Direct Database Query
```bash
python manage.py shell
>>> from requisitions.models import Requisition, Profile, Department
>>> medical_dept = Department.objects.get(name='Medical')
>>> medical_hod = Profile.objects.get(role='head', department=medical_dept)
>>> medical_reqs = Requisition.objects.filter(department=medical_dept).exclude(status='deleted')
>>> print(f"Medical HOD sees {medical_reqs.count()} requisitions")
```

## What Can Still Cause Issues

1. **Existing requisitions with NULL department**
   - These might still show up for HODs
   - Solution: Update old requisitions in admin panel to assign correct departments

2. **Users without profiles**
   - Will not be able to create requisitions (by design)
   - Admin needs to create profiles for these users

3. **Users with no department assigned**
   - Will get an error when trying to create requisitions
   - Admin needs to assign a department to their profile

## Key Code Changes

### In `requisition_list()`:
- Added `.exclude(status='deleted')` to all querysets
- Ensures HODs only filter by their specific department

### In `requisition_create()`:
- Added profile and department validation at the start
- Prevents creation of requisitions with NULL departments

### In `requisition_detail()`, `requisition_approve()`, `delete_requisition()`, `requisition_fulfill()`, `print_requisition()`:
- All now verify HOD access to same department only
- Added `profile.department == req.department` checks
