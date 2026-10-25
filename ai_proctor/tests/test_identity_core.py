import contextlib
from dataclasses import replace
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
from ai_proctor.core.face_engine import Engine, frontal_enough
from ai_proctor.core.identity_policy import Monitor, Sample, Settings, identity_label

MATCH = Sample(1, 'quality_ok', .8)
MISMATCH = Sample(1, 'quality_ok', .1)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings()
        self.monitor = Monitor(self.settings)
        self.time = 0.

    def feed(self, sample, seconds):
        rows = []
        for _ in range(round(seconds/.25)+1):
            rows += self.monitor.update(sample, self.time)
            self.time += .25
        return rows

    def names(self, rows):
        return [r['event'] for r in rows]

    def test_match_needs_time_and_samples(self):
        self.assertEqual(self.feed(MATCH, .5), [])
        self.assertFalse(self.monitor.verified)
        self.assertEqual(self.names(self.feed(MATCH, 1)), ['reference_match_confirmed'])
        self.assertTrue(self.monitor.verified)

    def test_short_absence_does_not_alert(self):
        self.assertEqual(self.feed(Sample(0, 'no_face'), 1), [])
        self.assertNotIn('face_absence_observed', self.names(self.feed(MATCH, 2)))

    def test_sustained_absence_emits_once(self):
        rows = self.feed(Sample(0, 'no_face'), 8)
        self.assertEqual(self.names(rows), ['face_absence_observed'])
        self.assertEqual(rows[0]['reason'], 'no_face_detected')

    def test_visible_blurred_face_clears_absence_not_identity(self):
        self.feed(Sample(0, 'no_face'), 4)
        rows = self.feed(Sample(1, 'blur_uncertain'), 2)
        self.assertEqual(self.names(rows), ['face_detection_restored'])
        self.assertTrue(rows[0]['identity_confirmation_separate'])
        self.assertNotIn('identity_reverified', rows[0])
        self.assertFalse(self.monitor.verified)

    def test_camera_failure_does_not_count_as_absence_or_recovery(self):
        self.assertEqual(self.feed(Sample(None, 'camera_waiting'), 5), [])
        self.feed(Sample(0, 'no_face'), 4)
        rows = self.feed(Sample(None, 'camera_waiting'), 2)
        self.assertEqual(self.names(rows), ['face_absence_interrupted'])

    def test_multiple_faces_never_selects_an_identity(self):
        rows = self.feed(Sample(2, 'multiple_faces', .99), 4)
        self.assertEqual(self.names(rows), ['multiple_faces_observed'])
        self.assertFalse(self.monitor.verified)
        self.assertFalse(self.monitor.review_pending)

    def test_gray_zone_and_bad_quality_do_not_prove_mismatch(self):
        for sample in (Sample(1, 'quality_ok', .35), Sample(1, 'blur_uncertain', .01),
                       Sample(1, 'face_angle_uncertain', .01), Sample(1, 'quality_ok', math.nan),
                       Sample(1, 'quality_ok', True), Sample(1, 'quality_ok', 'bad')):
            self.assertEqual(self.feed(sample, 4), [])
        self.assertFalse(self.monitor.review_pending)

    def test_one_low_score_does_not_alert(self):
        self.assertEqual(self.feed(MISMATCH, 0), [])
        self.assertNotIn('identity_mismatch_review', self.names(self.feed(MATCH, 2)))

    def test_sustained_mismatch_alert_is_not_impersonation_finding(self):
        rows = self.feed(MISMATCH, 8)
        self.assertEqual(self.names(rows), ['identity_mismatch_review'])
        self.assertEqual(rows[0]['status'], 'review_needed')
        self.assertIn('not an impersonation finding', rows[0]['guidance'])

    def test_unknown_breaks_mismatch_confirmation(self):
        self.feed(MISMATCH, 2)
        self.feed(Sample(1, 'face_angle_uncertain'), .25)
        self.assertEqual(self.feed(MISMATCH, 2), [])

    def test_match_expires_immediately_on_tracking_loss(self):
        self.feed(MATCH, 2)
        rows = self.feed(Sample(0, 'no_face'), 0)
        self.assertEqual(self.names(rows), ['identity_recheck_required'])
        self.assertFalse(self.monitor.verified)
        self.feed(MATCH, .5)
        self.assertFalse(self.monitor.verified)

    def test_match_expires_on_ambiguous_comparison(self):
        self.feed(MATCH, 2)
        rows = self.feed(Sample(1, 'quality_ok', .35), 0)
        self.assertEqual(rows[0]['reason'], 'reference_comparison_changed')
        self.assertFalse(self.monitor.verified)

    def test_unresolved_review_survives_face_loss_and_requires_match(self):
        self.feed(MISMATCH, 4)
        self.feed(Sample(0, 'no_face'), 4)
        self.assertTrue(self.monitor.review_pending)
        rows = self.feed(MISMATCH, 4)
        self.assertNotIn('identity_mismatch_review', self.names(rows))
        rows = self.feed(MATCH, 2)
        self.assertIn('identity_review_resolved', self.names(rows))
        self.assertFalse(self.monitor.review_pending)
        self.assertIn('identity_mismatch_review', self.names(self.feed(MISMATCH, 4)))

    def test_time_gaps_do_not_accumulate_evidence(self):
        for i in range(10):
            self.assertEqual(self.monitor.update(MISMATCH, i*2), [])
        self.assertFalse(self.monitor.review_pending)

    def test_gap_invalidates_previous_match(self):
        self.feed(MATCH, 2)
        rows = self.monitor.update(MATCH, self.time+5)
        self.assertEqual(self.names(rows), ['identity_recheck_required'])
        self.assertFalse(self.monitor.verified)

    def test_stop_does_not_resolve_review(self):
        self.feed(MISMATCH, 4)
        self.assertEqual(self.monitor.interrupt('session_ended'), [])
        self.assertTrue(self.monitor.review_pending)

    def test_configuration_and_time_validation(self):
        for change in ({'match_threshold': .2}, {'match_samples': True}, {'sample_period': 2},
                       {'absence_seconds': 0}, {'min_sharpness': math.nan}):
            with self.assertRaises(ValueError):
                replace(self.settings, **change)
        with self.assertRaises(ValueError):
            self.monitor.update(MATCH, math.nan)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine.__new__(Engine)
        self.engine.s = Settings()
        self.engine.detector = Mock()
        self.engine.recognizer = Mock()
        rng = np.random.default_rng(7)
        self.frame = rng.integers(30, 210, size=(480, 640, 3), dtype=np.uint8)
        self.face = np.array([100, 100, 200, 220, 145, 160, 255, 160, 200, 210, 160, 265, 240, 265, .99], np.float32)
        self.engine.detector.detect.return_value = (None, np.array([self.face]))

    def test_no_face_and_multiple_faces(self):
        for faces, expected in ((None, 0), (np.array([self.face, self.face]), 2)):
            self.engine.detector.detect.return_value = (None, faces)
            face, sample, _ = self.engine.inspect(self.frame)
            self.assertIsNone(face)
            self.assertEqual(sample.faces, expected)

    def test_visible_low_quality_is_not_absent(self):
        _, sample, _ = self.engine.inspect(np.full_like(self.frame, 100))
        self.assertEqual((sample.faces, sample.reason), (1, 'blur_uncertain'))

    def test_full_profile_like_landmarks_do_not_reach_recognition(self):
        self.face[8] = 270
        self.engine.detector.detect.return_value = (None, np.array([self.face]))
        sample, _, _ = self.engine.evaluate(self.frame, np.ones((1, 128)))
        self.assertEqual(sample.reason, 'face_angle_uncertain')
        self.engine.recognizer.feature.assert_not_called()

    def test_frontal_shape_passes_geometry_guard(self):
        self.assertTrue(frontal_enough(self.face))

    def test_clipped_and_small_faces(self):
        for x, width, reason in ((-1, 200, 'face_clipped'), (100, 70, 'face_too_small')):
            face = self.face.copy()
            face[0], face[2] = x, width
            self.engine.detector.detect.return_value = (None, np.array([face]))
            self.assertEqual(self.engine.inspect(self.frame)[1].reason, reason)

    def test_score_is_not_in_diagnostic_metadata(self):
        self.engine.recognizer.feature.return_value = np.ones((1, 128))
        self.engine.recognizer.match.return_value = .7
        sample, info, _ = self.engine.evaluate(self.frame, np.ones((1, 128)))
        self.assertAlmostEqual(sample.score, .7)
        self.assertNotIn('score', info)
        self.assertNotIn('embedding', info)

    def test_invalid_model_output_is_unknown(self):
        self.engine.recognizer.feature.return_value = np.full((1, 128), np.nan)
        sample, _, _ = self.engine.evaluate(self.frame, np.ones((1, 128)))
        self.assertEqual(sample.reason, 'recognition_unavailable')

    def test_invalid_camera_frame_does_not_mean_absence(self):
        self.assertIsNone(self.engine.inspect(None)[1].faces)


