import hashlib
import io
import json
from concurrent.futures import Future
from unittest.mock import Mock
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, SimpleTestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient
from ai_proctor.checks import Verification
from ai_proctor.inference import decode_frame
from ai_proctor.models import RegisteredReference, AISession, AIEvent
from ai_proctor.runtime import Registry
from ai_proctor.core.identity_policy import Sample
from ai_proctor.core.gaze_policy import Measurement
from proctor.models import Question, ProctorEvent, ProctorSnapshot


def jpeg():
    stream = io.BytesIO()
    Image.new('RGB', (640, 480), 'gray').save(stream, format='JPEG')
    return stream.getvalue()


class FakeAnalyzer:
    def __init__(self, path):
        self.sample = Sample(1, 'quality_ok', .8)
        self.live = 'verified_sample'
        self.measurement = Measurement(0, 0, 0, 0, 0, .3)
        self.closed = False

    def analyze(self, frame, now, need_liveness):
        return self.sample, self.live, self.measurement, 'valid' if self.measurement else 'no_face'

    def close(self):
        self.closed = True


@override_settings(AI_ENABLED=True, AI_MINIFAS_ACKNOWLEDGED=True, AI_REVERIFY_SECONDS=15, ROBOFLOW_API_KEY='')
class IntegrationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.registry = Registry()
        self.registry.started = True  # Test lifetimes are explicit; no background DB thread.
        self.patches = [patch('ai_proctor.views.registry', self.registry), patch('ai_proctor.runtime.Analyzer', FakeAnalyzer)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.reference = RegisteredReference.objects.create(student_id='TEST-1', private_filename='synthetic.image',
                                                             access_code_hash=make_password('test-access-code'))
        self.client = APIClient()
        self.now = 0.
        self.seq = 0

    def tearDown(self):
        self.registry.shutdown()

    def start(self, **kwargs):
        body = dict(student_id='TEST-1', access_code='test-access-code', consent=True, cloud_consent=False)
        body.update(kwargs)
        result = self.client.post('/api/ai/sessions', body, format='json')
        if result.status_code == 201:
            self.session = result.data['session_id']
            self.token = result.data['token']
            self.client.credentials(HTTP_AUTHORIZATION='Bearer '+self.token)
        return result

    def frame(self):
        self.seq += 1
        self.now += .5
        with patch('ai_proctor.views.time.monotonic', return_value=self.now):
            return self.client.post(f'/api/ai/sessions/{self.session}/frames',
                                    dict(frame=SimpleUploadedFile('f.jpg', jpeg(), 'image/jpeg'), sequence=self.seq))

    def action(self, name, **body):
        with patch('ai_proctor.views.time.monotonic', return_value=self.now):
            return self.client.post(f'/api/ai/sessions/{self.session}/{name}', body, format='json')

    def prepare(self):
        self.assertEqual(self.start().status_code, 201)
        for _ in range(14):
            self.assertEqual(self.frame().status_code, 200)

    def test_wrong_code_and_missing_consent_cannot_start(self):
        self.assertEqual(self.start(access_code='wrong').status_code, 403)
        self.assertEqual(self.start(consent=False).status_code, 400)
        self.assertEqual(AISession.objects.count(), 0)

    @override_settings(AI_MINIFAS_ACKNOWLEDGED=False)
    def test_license_ambiguity_acknowledgement_is_not_assumed(self):
        self.assertEqual(self.start().status_code, 503)

    def test_server_enforces_precheck_not_just_ui(self):
        self.start()
        self.assertEqual(self.action('begin').status_code, 409)
        for _ in range(14):
            result = self.frame()
        self.assertTrue(result.data['ready'])
        self.assertEqual(self.action('begin').status_code, 200)
        self.assertEqual(AISession.objects.get().status, 'exam')

    def test_failed_liveness_cannot_start_even_when_identity_matches(self):
        self.start()
        self.registry.get(self.session).analyzer.live = 'liveness_unconfirmed'
        for _ in range(14):
            self.frame()
        self.assertEqual(self.action('begin').status_code, 409)

    def test_expired_frame_evidence_cannot_start(self):
        self.prepare()
        self.now += 4
        self.assertEqual(self.action('begin').status_code, 409)

    def test_phase4_absence_return_and_mismatch_do_not_create_legacy_warnings(self):
        self.prepare()
        self.action('begin')
        analyzer = self.registry.get(self.session).analyzer
        analyzer.sample, analyzer.measurement = Sample(0, 'no_face'), None
        for _ in range(9):
            self.frame()
        self.assertEqual(AIEvent.objects.filter(event='face_absence_observed').count(), 1)
        analyzer.sample, analyzer.measurement = Sample(1, 'quality_ok', .8), Measurement(0, 0, 0, 0, 0, .3)
        for _ in range(5):
            self.frame()
        self.assertTrue(AIEvent.objects.filter(event='face_detection_restored').exists())
        analyzer.sample = Sample(1, 'quality_ok', .1)
        for _ in range(9):
            self.frame()
        self.assertTrue(AIEvent.objects.filter(event='identity_mismatch_review').exists())
        self.assertEqual(AISession.objects.get().status, 'exam')
        self.assertEqual(ProctorEvent.objects.count(), 0)

    def test_periodic_identity_and_liveness_reverification(self):
        self.prepare()
        self.action('begin')
        for _ in range(40):
            self.frame()
        self.assertTrue(AIEvent.objects.filter(event='identity_liveness_verified', details__stage='periodic').exists())

    def test_tokens_are_session_scoped_and_not_stored_plaintext(self):
        self.start()
        self.assertEqual(AISession.objects.get().token_hash, hashlib.sha256(self.token.encode()).hexdigest())
        self.client.credentials(HTTP_AUTHORIZATION='Bearer '+'x'*43)
        self.assertEqual(self.frame().status_code, 403)

    def test_revoked_reference_stops_api_access(self):
        self.start()
        self.reference.active = False
        self.reference.save()
        self.assertEqual(self.frame().status_code, 403)

    def test_replayed_frame_and_bad_jpeg_are_rejected(self):
        self.start()
        self.frame()
        self.seq -= 1
        self.assertEqual(self.frame().status_code, 400)
        result = self.client.post(f'/api/ai/sessions/{self.session}/frames', dict(frame=SimpleUploadedFile('x.jpg', b'bad'), sequence=99))
        self.assertEqual(result.status_code, 400)

    def test_stop_releases_models_and_session_cannot_resume(self):
        self.start()
        runtime = self.registry.get(self.session)
        self.assertEqual(self.action('stop').status_code, 200)
        self.assertTrue(runtime.analyzer.closed)
        self.assertEqual(self.frame().status_code, 410)

    def test_review_requires_authenticated_staff(self):
        self.start()
        self.assertEqual(self.client.get('/api/ai/review').status_code, 403)
        user = get_user_model().objects.create_user(username='reviewer', password='only-for-tests')
        self.client.force_authenticate(user=user)
        self.assertEqual(self.client.get('/api/ai/review').status_code, 403)
        user.is_staff = True
        user.save()
        self.assertEqual(self.client.get('/api/ai/review').status_code, 200)

    def test_metadata_does_not_store_frames_features_reference_paths_or_scores(self):
        self.prepare()
        serialized = json.dumps(list(AIEvent.objects.values('event', 'details')))
        for forbidden in ('synthetic.image', 'embedding', 'base64', 'similarity', 'score'):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(ProctorSnapshot.objects.count(), 0)

    @override_settings(ROBOFLOW_API_KEY='test-only-key')
    def test_no_cloud_upload_without_separate_consent(self):
        with patch('ai_proctor.runtime.RoboflowClient') as cloud:
            self.prepare()
            cloud.assert_not_called()

    def test_model_failure_becomes_unknown_not_old_success(self):
        self.prepare()
        runtime = self.registry.get(self.session)
        with patch.object(runtime.analyzer, 'analyze', side_effect=RuntimeError('private details')):
            result = self.frame()
        self.assertFalse(result.data['ready'])
        self.assertEqual(result.data['identity']['identity_status'], 'unknown')
        self.assertNotIn('private details', json.dumps(result.data))

    def test_backend_restart_requires_new_check(self):
        self.prepare()
        self.registry.get(self.session).analyzer.close()
        self.registry.remove(self.session)
        self.assertEqual(self.frame().status_code, 410)

    @override_settings(ROBOFLOW_API_KEY='test-only-key')
    def test_slow_cloud_does_not_block_local_checks_or_queue_frames(self):
        future = Future()
        pool = Mock()
        pool.submit.return_value = future
        with patch('ai_proctor.runtime.ThreadPoolExecutor', return_value=pool):
            self.start(cloud_consent=True)
        for _ in range(14):
            result = self.frame()
        self.assertTrue(result.data['ready'])
        self.assertEqual(pool.submit.call_count, 1)
        self.assertIsNone(result.data['objects']['counts'])

    @override_settings(ROBOFLOW_API_KEY='test-only-key')
    def test_cloud_failure_is_unknown_and_does_not_leak_secrets(self):
        future = Future()
        pool = Mock()
        pool.submit.return_value = future
        with patch('ai_proctor.runtime.ThreadPoolExecutor', return_value=pool):
            self.start(cloud_consent=True)
        self.frame()
        future.set_exception(RuntimeError('private-api-secret'))
        result = self.frame()
        self.assertEqual(result.data['objects']['status'], 'unavailable')
        self.assertIsNone(result.data['objects']['counts'])
        self.assertNotIn('private-api-secret', json.dumps(result.data))

    @override_settings(ROBOFLOW_API_KEY='test-only-key')
    def test_cloud_stale_result_never_becomes_clear_scene(self):
        future = Future()
        pool = Mock()
        pool.submit.return_value = future
        with patch('ai_proctor.runtime.ThreadPoolExecutor', return_value=pool):
            self.start(cloud_consent=True)
        self.frame()
        future.set_result((640, 480, []))
        self.now += 20
        result = self.frame()
        self.assertIsNone(result.data['objects']['counts'])
        self.assertEqual(result.data['objects']['active'], [])


class PreservedAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_question_and_browser_event_contracts_preserved(self):
        question = Question.objects.create(question_text='Existing question')
        self.assertEqual(self.client.get('/api/proctor/questions').data,
                         [dict(id=question.id, question_text='Existing question')])
        response = self.client.post('/api/proctor/log-event', dict(student_id='TEST', event_type='Tab-Switch'))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.client.get('/api/proctor/events').data[0]['event_type'], 'Tab-Switch')

    def test_existing_snapshot_storage_and_validation_preserved(self):
        self.assertEqual(self.client.post('/api/proctor/save-snapshot', {}).status_code, 400)
        response = self.client.post('/api/proctor/save-snapshot', dict(student_id='TEST', image_data='synthetic-test-data'))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(ProctorSnapshot.objects.get().image_data, 'synthetic-test-data')


class VerificationAndUploadTests(SimpleTestCase):
    def test_ai_uploads_reject_oversized_requests_before_parsing(self):
        from django.test import RequestFactory
        from ai_proctor.middleware import AIUploadLimitMiddleware
        downstream = Mock()
        request = RequestFactory().post('/api/ai/sessions', data=b'', content_type='application/json', CONTENT_LENGTH=str(3*1024*1024))
        response = AIUploadLimitMiddleware(downstream)(request)
        self.assertEqual(response.status_code, 413)
        downstream.assert_not_called()

    def test_retries_eventually_require_review_without_cheating_label(self):
        check = Verification()
        rows = []
        for i in range(130):
            rows += check.observe('liveness_unconfirmed', i*.5)
        self.assertEqual(check.status, 'review_needed')
        self.assertEqual([r['event'] for r in rows].count('verification_retry'), 2)
        self.assertNotIn('cheat', json.dumps(rows))

    def test_gap_resets_liveness_streak(self):
        check = Verification()
        for i in range(4):
            check.observe('verified_sample', i*.5)
        check.observe('verified_sample', 5)
        self.assertNotEqual(check.status, 'verified')

    def test_upload_limits_and_format(self):
        self.assertEqual(decode_frame(jpeg()).shape, (480, 640, 3))
        for raw in (b'bad', b'x'*1500001):
            with self.assertRaises(ValueError):
                decode_frame(raw)
