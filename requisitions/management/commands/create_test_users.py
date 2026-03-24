from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from requisitions.models import Department, Profile

class Command(BaseCommand):
    help = 'Create test HODs and 3 users per department'

    def handle(self, *args, **options):
        for dept in Department.objects.all():
            # Create HOD
            hod_username = f"hod_{dept.name.replace(' ', '_').lower()}"
            hod_email = f"{hod_username}@example.com"
            hod_user, created = User.objects.get_or_create(
                username=hod_username,
                defaults={
                    'first_name': f"{dept.name} HOD", 
                    'email': hod_email, 
                    'is_staff': True
                }
            )
            Profile.objects.get_or_create(
                user=hod_user,
                defaults={'role': 'head', 'department': dept}
            )
            self.stdout.write(
                self.style.SUCCESS(f"Created/verified HOD for {dept.name}: {hod_user.username}")
            )

            # Create 3 normal users
            for i in range(1, 4):
                user_username = f"{dept.name.replace(' ', '_').lower()}_user{i}"
                user_email = f"{user_username}@example.com"
                user, created = User.objects.get_or_create(
                    username=user_username,
                    defaults={
                        'first_name': f"User {i}", 
                        'email': user_email
                    }
                )
                Profile.objects.get_or_create(
                    user=user,
                    defaults={'role': 'user', 'department': dept}
                )
                self.stdout.write(
                    self.style.SUCCESS(f"Created/verified user: {user.username} in {dept.name}")
                )

        self.stdout.write(self.style.SUCCESS('Test users creation complete!'))
