from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from requisitions.models import Profile

class Command(BaseCommand):
    help = 'List all users with their profile info (role, department)'

    def handle(self, *args, **options):
        self.stdout.write('Username | Email | Role | Department')
        self.stdout.write('-' * 50)
        
        for user in User.objects.all():
            try:
                profile = user.profile
                dept_name = profile.department.name if profile.department else "No department"
                role = profile.role
            except:
                dept_name = "No profile"
                role = "No profile"
            
            self.stdout.write(f"{user.username} | {user.email} | {role} | {dept_name}")
        
        self.stdout.write(self.style.SUCCESS(f'Listed {User.objects.count()} users.'))
