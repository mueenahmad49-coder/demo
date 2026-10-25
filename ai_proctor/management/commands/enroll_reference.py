from pathlib import Path
import secrets
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from ai_proctor.models import RegisteredReference
from ai_proctor.assets import verify_assets, face_paths


class Command(BaseCommand):
    help = 'Operator-only enrollment: validate and privately copy an approved reference; print a new access code once'

    def add_arguments(self, parser):
        parser.add_argument('--student-id', required=True)
        parser.add_argument('--reference', type=Path, required=True)
        parser.add_argument('--consent-confirmed', action='store_true')

    def handle(self, **options):
        from ai_proctor.core.face_engine import Engine
        from ai_proctor.inference import identity_settings
        student = options['student_id'].strip()
        if not options['consent_confirmed'] or not 1 <= len(student) <= 100:
            raise CommandError('An approved student ID and explicit consent are required')
        source = options['reference']
        if not source.is_file() or source.stat().st_size > 10000000:
            raise CommandError('Use a reference image smaller than 10 MB')
        if RegisteredReference.objects.filter(student_id=student).exists():
            raise CommandError('This student is already enrolled. Use revoke_reference before replacing the approved reference.')
        engine = Engine(face_paths(verify_assets()), identity_settings())
        try:
            feature = engine.reference(source)
            feature.fill(0)
        except Exception:
            raise CommandError('Reference rejected. Use exactly one clear frontal face with suitable lighting.') from None
        folder = settings.AI_REFERENCE_DIR
        folder.mkdir(parents=True, exist_ok=True)
        filename = secrets.token_hex(24)+'.image'
        target = folder/filename
        code = secrets.token_urlsafe(24)
        try:
            with target.open('xb') as stream:
                stream.write(source.read_bytes())
            RegisteredReference.objects.create(student_id=student, private_filename=filename, access_code_hash=make_password(code))
        except Exception:
            target.unlink(missing_ok=True)
            raise
        self.stdout.write('Reference enrolled. Give this exam access code privately to the student; it is shown only now:')
        self.stdout.write(code)
