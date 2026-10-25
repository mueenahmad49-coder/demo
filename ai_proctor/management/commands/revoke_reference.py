from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from ai_proctor.models import RegisteredReference


class Command(BaseCommand):
    help = 'Revoke an enrollment and remove its private photo and associated AI records'

    def add_arguments(self, parser):
        parser.add_argument('--student-id', required=True)
        parser.add_argument('--confirm-delete', action='store_true')

    def handle(self, **options):
        if not options['confirm_delete']:
            raise CommandError('Add --confirm-delete to remove the reference and its AI session/event records')
        row = RegisteredReference.objects.filter(student_id=options['student_id']).first()
        if row is None:
            raise CommandError('No enrollment found')
        target = (settings.AI_REFERENCE_DIR/row.private_filename).resolve()
        if target.parent != settings.AI_REFERENCE_DIR.resolve():
            raise CommandError('Invalid reference storage path')
        row.active = False
        row.save(update_fields=['active'])
        target.unlink(missing_ok=True)
        row.delete()
        self.stdout.write('Enrollment and related AI records removed. Stop any existing browser test; idle model buffers expire within two minutes.')
