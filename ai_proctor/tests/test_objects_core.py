import contextlib
import http.client
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import urllib.error

from ai_proctor.core.objects_policy import Settings, Detection, Monitor, filter_detections, conditions, iou
from ai_proctor.core.objects_roboflow import parse_predictions, ResponseError, RoboflowClient, CloudError, NoRedirect


def raw(label='person', score=.9, x=300, y=250, width=200, height=400):
    return dict(**{'class': label}, confidence=score, x=x, y=y, width=width, height=height)


def result(items=None, width=640, height=480):
    return dict(image=dict(width=width, height=height), predictions=items if items is not None else [raw()])


PERSON = Detection('person', .93, (100, 50, 300, 450))
PHONE = Detection('cell phone', .65, (200, 200, 250, 300))
BOOK = Detection('book', .75, (300, 200, 450, 380))


class ParsingTests(unittest.TestCase):
    def test_supported_result_envelopes(self):
        base = result()
        for payload in (base, [{'predictions': base}], {'outputs': [{'predictions': base}]},
                        {'outputs': {'predictions': base}},
                        {'predictions': {'predictions': base, 'visualization': {'type': 'image_ref'}}}):
            with self.subTest(payload=payload):
                w, h, ds = parse_predictions(payload)
                self.assertEqual((w, h), (640, 480))
                self.assertEqual(ds[0].box, (200, 50, 400, 450))

    def test_valid_empty_detections(self):
        self.assertEqual(parse_predictions(result([]))[2], [])

    def test_missing_predictions_are_unknown_not_empty(self):
        for payload in ({}, [], {'outputs': []}, {'error': 'failed'}, {'predictions': []},
                        {'outputs': [result(), result()]}, {'image': {'width': 640}}):
            with self.subTest(payload=payload), self.assertRaises(ResponseError):
                parse_predictions(payload)

    def test_invalid_numbers_rejected(self):
        for value in (float('nan'), float('inf'), True, '640', None, -1, 0):
            with self.subTest(value=value), self.assertRaises(ResponseError):
                parse_predictions(result(width=value))

    def test_malformed_detection_rejects_entire_sample(self):
        bad = [raw(score=2), raw(width=0), raw(x=float('nan')), {'class': 'person'},
               {**raw(), 'class': 1}, raw(height=-1)]
        for item in bad:
            with self.subTest(item=item), self.assertRaises(ResponseError):
                parse_predictions(result([raw(), item]))

    def test_class_names_not_ids(self):
        payload = result([{**raw('cell phone'), 'class_id': 77}, {**raw(), 'class_id': 999}])
        self.assertEqual([d.label for d in parse_predictions(payload)[2]], ['cell phone', 'person'])


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings()

    def test_user_phone_sample_counts_one_person(self):
        # Anonymized numerical output from the user's RF-DETR phone trial.
        payload = result([raw('person', .9272316, 825.5, 436, 903, 558),
                          raw('cell phone', .647241, 828.5, 409.5, 699, 543),
                          raw('person', .4504803, 821, 427.5, 912, 575)], 1280, 720)
        w, h, ds = parse_predictions(payload)
        counts, flags = conditions(filter_detections(ds, w, h, self.settings))
        self.assertEqual(counts, {'person': 1, 'cell phone': 1, 'book': 0})
        self.assertFalse(flags['multiple_people_visible'])

    def test_duplicate_above_confidence_is_suppressed(self):
        duplicate = Detection('person', .82, (102, 52, 298, 448))
        kept = filter_detections([PERSON, duplicate], 640, 480, self.settings)
        self.assertEqual(kept, [PERSON])

    def test_two_distinct_people_remain(self):
        second = Detection('person', .86, (400, 50, 600, 450))
        kept = filter_detections([PERSON, second], 640, 480, self.settings)
        self.assertTrue(conditions(kept)[1]['multiple_people_visible'])

    def test_overlapping_classes_are_not_suppressed(self):
        phone = Detection('cell phone', .85, PERSON.box)
        self.assertEqual(len(filter_detections([PERSON, phone], 640, 480, self.settings)), 2)

    def test_clipping_threshold_and_invalid_boxes(self):
        items = [Detection('book', .4, (-10, -10, 50, 50)), Detection('book', .2, (100, 100, 200, 200)),
                 Detection('person', .9, (100, 100, 90, 90)), Detection('dog', .99, (1, 1, 20, 20)),
                 Detection('cell phone', float('nan'), (1, 1, 20, 20))]
        self.assertEqual(filter_detections(items, 640, 480, self.settings), [Detection('book', .4, (0, 0, 50, 50))])

    def test_same_person_iou_near_one(self):
        self.assertGreater(iou((374, 157, 1277, 715), (365, 140, 1277, 715)), .96)

    def test_requires_duration_and_sample_count(self):
        monitor = Monitor(self.settings)
        self.assertEqual(monitor.update([PERSON, PHONE], 0), [])
        self.assertEqual(monitor.update([PERSON, PHONE], 1), [])
        events = monitor.update([PERSON, PHONE], 2)
        self.assertEqual(events[0]['observation'], 'phone_visible')
        self.assertEqual(events[0]['event'], 'observation_started')
        self.assertEqual(monitor.update([PERSON, PHONE], 3), [])

    def test_fast_samples_do_not_satisfy_duration(self):
        monitor = Monitor(self.settings)
        for t in (0, .1, .2, .3):
            self.assertEqual(monitor.update([PERSON, BOOK], t), [])
        self.assertEqual(monitor.update([PERSON, BOOK], 1)[0]['observation'], 'book_visible')

    def test_candidate_must_be_consecutive(self):
        monitor = Monitor(self.settings)
        for t, ds in [(0, [PERSON, PHONE]), (1, [PERSON, PHONE]), (2, [PERSON]), (3, [PERSON, PHONE])]:
            self.assertEqual(monitor.update(ds, t), [])

    def test_clear_requires_samples_and_time(self):
        monitor = Monitor(self.settings)
        for t in (0, 1, 2):
            monitor.update([PERSON, PHONE], t)
        self.assertEqual(monitor.update([PERSON], 3), [])
        self.assertEqual(monitor.update([PERSON], 4), [])
        self.assertEqual(monitor.update([PERSON], 5)[0]['event'], 'observation_ended')

    def test_gap_interrupts_instead_of_clearing(self):
        monitor = Monitor(self.settings)
        for t in (0, 1, 2):
            monitor.update([PERSON, PHONE], t)
        events = monitor.update([PERSON], 20)
        self.assertEqual(events[0]['event'], 'observation_interrupted')
        self.assertEqual(events[0]['status'], 'unknown')
        self.assertEqual(monitor.active(), [])

    def test_interruption_resets_pending_evidence(self):
        monitor = Monitor(self.settings)
        monitor.update([PERSON, PHONE], 0)
        monitor.update([PERSON, PHONE], 1)
        monitor.interrupt()
        self.assertEqual(monitor.update([PERSON, PHONE], 2), [])

    def test_slow_cloud_samples_explain_pending_resets(self):
        monitor = Monitor(self.settings)
        monitor.update([PERSON, PHONE], 0)
        events = monitor.update([PERSON, PHONE], 5.86)
        self.assertEqual(events, [dict(event='evidence_reset', status='unknown',
                                      reason='sample_gap_exceeded', sample_gap_seconds=5.86,
                                      max_sample_gap_seconds=5)])
        monitor.update([PERSON, PHONE], 13.45)
        self.assertEqual(monitor.progress()['phone_visible']['samples'], 1)
        self.assertEqual(monitor.active(), [])

    def test_cloud_test_profile_confirms_and_clears_with_slow_samples(self):
        cloud = Settings(max_sample_gap=15)
        self.assertEqual(cloud.confidence, self.settings.confidence)
        self.assertEqual((cloud.confirm_samples, cloud.clear_samples), (3, 3))
        monitor = Monitor(cloud)
        # Representative spacing using the user's reported response delays;
        # these are synthetic detections, not a reconstruction of missing frames.
        self.assertEqual(monitor.update([PERSON, PHONE], 0), [])
        self.assertEqual(monitor.update([PERSON, PHONE], 5.86), [])
        self.assertEqual(monitor.progress()['phone_visible']['samples'], 2)
        self.assertEqual(monitor.progress()['phone_visible']['state'], 'confirming')
        events = monitor.update([PERSON, PHONE], 13.45)
        self.assertEqual(events[0]['event'], 'observation_started')
        self.assertEqual(monitor.progress()['phone_visible']['state'], 'active')
        self.assertEqual(monitor.update([PERSON], 22.09), [])
        self.assertEqual(monitor.progress()['phone_visible']['state'], 'clearing')
        self.assertEqual(monitor.update([PERSON], 29.68), [])
        self.assertEqual(monitor.update([PERSON], 38.32)[0]['event'], 'observation_ended')
        self.assertEqual(monitor.progress()['phone_visible']['state'], 'idle')

    def test_cloud_test_profile_still_resets_long_gaps(self):
        cloud = Settings(max_sample_gap=15)
        monitor = Monitor(cloud)
        monitor.update([PERSON, PHONE], 0)
        monitor.update([PERSON, PHONE], 6)
        events = monitor.update([PERSON, PHONE], 22)
        self.assertEqual(events[0]['event'], 'evidence_reset')
        self.assertEqual(monitor.progress()['phone_visible']['samples'], 1)
        self.assertEqual(monitor.active(), [])

    def test_diagnostics_distinguish_clearing_from_gap(self):
        monitor = Monitor(self.settings)
        for t in (0, 1, 2):
            monitor.update([PERSON, PHONE], t)
        monitor.update([PERSON], 3)
        progress = monitor.progress()['phone_visible']
        self.assertEqual(progress, dict(state='clearing', samples=1, required_samples=3,
                                       elapsed_seconds=0, required_seconds=2))
        monitor.interrupt()
        self.assertEqual(monitor.progress()['phone_visible']['state'], 'idle')

    def test_reversed_time_is_explained_and_cannot_confirm(self):
        monitor = Monitor(self.settings)
        monitor.update([PERSON, PHONE], 10)
        events = monitor.update([PERSON, PHONE], 9)
        self.assertEqual(events[0]['reason'], 'timestamp_reversed')
        self.assertEqual(monitor.progress()['phone_visible']['samples'], 1)
        self.assertEqual(monitor.active(), [])

    def test_invalid_settings(self):
        for kwargs in ({'sample_period': 0}, {'max_sample_gap': float('inf')}, {'confirm_samples': True},
                       {'confidence': {'person': .5}}, {'confidence': ['person', 'cell phone', 'book']}, {'nms_iou': 2}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Settings(**kwargs)


class TransportTests(unittest.TestCase):
    def client(self, opener):
        return RoboflowClient('workspace', 'workflow', 'test-secret', opener=opener)

    def test_header_auth_and_base64_input_without_url_secret(self):
        from unittest.mock import Mock
        opener = Mock()
        opener.open.return_value = io.BytesIO(json.dumps({'outputs': [{'predictions': result()}]}).encode())
        self.assertEqual(len(self.client(opener).infer(b'fake-jpeg')[2]), 1)
        request = opener.open.call_args.args[0]
        self.assertNotIn('test-secret', request.full_url)
        self.assertNotIn(b'test-secret', request.data)
        self.assertEqual(request.get_header('Authorization'), 'Bearer test-secret')
        self.assertEqual(json.loads(request.data)['inputs']['image']['type'], 'base64')
        self.assertEqual(opener.open.call_count, 1)

    def test_http_errors_sanitized_and_classified(self):
        from unittest.mock import Mock
        for code, retry in ((401, False), (403, False), (404, False), (429, False), (500, True)):
            opener = Mock()
            opener.open.side_effect = urllib.error.HTTPError('https://x?test-secret', code, 'test-secret', {}, None)
            with self.subTest(code=code), self.assertRaises(CloudError) as raised:
                self.client(opener).infer(b'fake')
            self.assertNotIn('test-secret', str(raised.exception))
            self.assertEqual(raised.exception.retryable, retry)
            self.assertEqual(opener.open.call_count, 1)

    def test_network_error_sanitized(self):
        from unittest.mock import Mock
        for error in (urllib.error.URLError('test-secret'), http.client.IncompleteRead(b'test-secret')):
            opener = Mock()
            opener.open.side_effect = error
            with self.subTest(error=type(error)), self.assertRaises(CloudError) as raised:
                self.client(opener).infer(b'fake')
            self.assertEqual(str(raised.exception), 'network_unavailable')

    def test_invalid_json_or_schema_is_not_empty_detection(self):
        from unittest.mock import Mock
        for content in (b'not-json', b'{}', b'{"outputs": []}'):
            opener = Mock()
            opener.open.return_value = io.BytesIO(content)
            with self.subTest(content=content), self.assertRaises(CloudError):
                self.client(opener).infer(b'fake')

    def test_oversized_response_rejected(self):
        from unittest.mock import Mock
        opener = Mock()
        opener.open.return_value = io.BytesIO(b'x'*65)
        with patch('ai_proctor.core.objects_roboflow.MAX_RESPONSE_BYTES', 64), self.assertRaises(CloudError):
            self.client(opener).infer(b'fake')

    def test_endpoint_and_redirect_protection(self):
        for workspace in ('../x', 'x?api_key=y', 'https://example.com', ''):
            with self.subTest(workspace=workspace), self.assertRaises(ValueError):
                RoboflowClient(workspace, 'workflow', 'test-secret')
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com'))


