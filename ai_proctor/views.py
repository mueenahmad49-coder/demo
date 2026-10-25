import hashlib
from pathlib import Path
import secrets
import time
from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from .models import RegisteredReference, AISession, AIEvent
from .runtime import registry
from .inference import decode_frame


class StartThrottle(AnonRateThrottle):
    rate = '10/minute'


@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def capabilities(request):
    return Response(dict(enabled=settings.AI_ENABLED, liveness_acknowledged=settings.AI_MINIFAS_ACKNOWLEDGED,
                         cloud_configured=bool(settings.ROBOFLOW_API_KEY),
                         reverify_seconds=settings.AI_REVERIFY_SECONDS))


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([StartThrottle])
def start(request):
    if not settings.AI_ENABLED:
        return Response({'error': 'AI checks are disabled by the operator'}, status=503)
    if not settings.AI_MINIFAS_ACKNOWLEDGED:
        return Response({'error': 'The operator must review the MiniFAS model-license notice before enabling liveness'}, status=503)
    data = request.data
    student = data.get('student_id')
    code = data.get('access_code')
    if not isinstance(student, str) or not 1 <= len(student.strip()) <= 100 or not isinstance(code, str) or len(code) > 200:
        return Response({'error': 'Enter the assigned student ID and exam access code'}, status=400)
    if data.get('consent') is not True or type(data.get('cloud_consent', False)) is not bool or type(data.get('head_only', False)) is not bool:
        return Response({'error': 'Explicit camera consent is required'}, status=400)
    reference = RegisteredReference.objects.filter(student_id=student.strip(), active=True).first()
    if reference is None or not check_password(code, reference.access_code_hash):
        return Response({'error': 'Student ID or access code is not valid'}, status=403)
    filename = reference.private_filename
    if Path(filename).name != filename:
        return Response({'error': 'Reference setup is unavailable'}, status=503)
    token = secrets.token_urlsafe(32)
    row = AISession.objects.create(reference=reference, token_hash=hashlib.sha256(token.encode()).hexdigest(),
                                   cloud_consent=data.get('cloud_consent', False))
    try:
        runtime = registry.create(row, settings.AI_REFERENCE_DIR/filename, row.cloud_consent, data.get('head_only', False))
    except Exception:
        row.status, row.ended_at = 'setup_unavailable', timezone.now()
        row.save(update_fields=['status', 'ended_at'])
        return Response({'error': 'Model/reference setup is unavailable or session capacity is full. Ask the operator to run check_ai_models.'}, status=503)
    return Response(dict(token=token, **runtime.view()), status=201)


def authorized(request, session_id):
    token = request.headers.get('Authorization', '')
    if not token.startswith('Bearer ') or not 20 <= len(token) <= 200:
        return None, Response({'error': 'Session authorization required'}, status=403)
    row = AISession.objects.select_related('reference').filter(pk=session_id).first()
    digest = hashlib.sha256(token[7:].encode()).hexdigest()
    if row is None or not secrets.compare_digest(digest, row.token_hash) or not row.reference.active:
        return None, Response({'error': 'Session authorization failed'}, status=403)
    runtime = registry.get(session_id)
    if runtime is None or runtime.closed:
        return None, Response({'error': 'Session ended or server restarted. Start a new camera check.'}, status=410)
    return runtime, None


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def frames(request, session_id):
    runtime, error = authorized(request, session_id)
    if error is not None:
        return error
    if not runtime.lock.acquire(blocking=False):
        return Response({'error': 'A frame is already being processed'}, status=409)
    try:
        upload = request.FILES.get('frame')
        if upload is None or upload.size > 1500000:
            return Response({'error': 'A JPEG frame smaller than 1.5 MB is required'}, status=400)
        raw = upload.read(1500001)
        sequence = int(request.data.get('sequence', '-1'))
        if sequence < 0:
            raise ValueError('Invalid sequence')
        frame = decode_frame(raw)
        return Response(runtime.frame(frame, raw, sequence, time.monotonic()))
    except (ValueError, TypeError):
        return Response({'error': 'Invalid, duplicate, or too-frequent frame'}, status=400)
    finally:
        runtime.lock.release()


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def control(request, session_id, action):
    runtime, error = authorized(request, session_id)
    if error is not None:
        return error
    if not runtime.lock.acquire(blocking=False):
        return Response({'error': 'Wait for the current frame to finish'}, status=409)
    try:
        if action == 'begin':
            runtime.begin(time.monotonic())
        elif action == 'retry':
            head_only = request.data.get('head_only')
            if head_only is not None and type(head_only) is not bool:
                raise ValueError('Invalid head-only setting')
            runtime.retry(head_only)
        elif action == 'stop':
            runtime.close('student_stopped')
            registry.remove(session_id)
            return Response({'stage': 'ended'})
        else:
            return Response({'error': 'Unknown action'}, status=404)
        return Response(runtime.view())
    except ValueError as error:
        return Response({'error': str(error)}, status=409)
    finally:
        runtime.lock.release()


@api_view(['GET'])
@authentication_classes([SessionAuthentication])
@permission_classes([IsAdminUser])
def review(request):
    rows = AIEvent.objects.select_related('session__reference').order_by('-id')[:100]
    return Response([dict(id=row.id, student_id=row.session.reference.student_id, session_id=str(row.session_id),
                          phase=row.phase, event=row.event, details=row.details, time=row.timestamp.isoformat()) for row in rows])
