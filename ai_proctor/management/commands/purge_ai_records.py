from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from ai_proctor.models import AISession


class Command(BaseCommand):
    help = 'Remove AI session metadata older than a chosen retention period; references and legacy snapshots are separate'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=7)

    def handle(self, **options):
        if options['days'] < 1:
            raise ValueError('days must be at least 1')
        sessions = AISession.objects.filter(created_at__lt=timezone.now()-timedelta(days=options['days']))
        count = sessions.count()
        sessions.delete()
        self.stdout.write(f'Removed {count} old AI sessions and their events.')
