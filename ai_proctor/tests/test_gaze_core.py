import contextlib
from dataclasses import replace
import io
import json
import math
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch, Mock

import cv2
import numpy as np
from ai_proctor.core.gaze_policy import Settings, Measurement, Calibration, Direction, Observer, TrackingAvailability, angle_delta
from ai_proctor.core.gaze_vision import canonical_points, camera_matrix, solve_pose, eye_ratios, EYES, Vision

NEUTRAL = Measurement(0, 0, 0, 0, 0, .3)


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.settings = replace(Settings(), calibration_seconds=1, calibration_samples=5)

    def test_requires_duration_and_enough_samples(self):
        c = Calibration(self.settings)
        for t in (0, .1, .2, .3, .4):
            self.assertIsNone(c.add(NEUTRAL, t))
        self.assertEqual(c.add(NEUTRAL, 1), NEUTRAL)

    def test_rejects_unstable_head_baseline(self):
        c = Calibration(self.settings)
        for i in range(11):
            c.add(replace(NEUTRAL, yaw=15 if i % 2 else -15), i/10)
        self.assertIsNone(c.baseline)
        self.assertEqual(c.reason, 'calibration_moved_retry_while_still')

    def test_eyes_required_unless_head_only(self):
        no_eyes = replace(NEUTRAL, eye_x=None, eye_y=None)
        for head_only in (False, True):
            c = Calibration(self.settings, head_only)
            for i in range(11):
                c.add(no_eyes, i/10)
            self.assertEqual(c.baseline is not None, head_only)

    def test_pose_failure_is_not_reported_as_eye_failure(self):
        for head_only in (False, True):
            c = Calibration(self.settings, head_only)
            self.assertIsNone(c.add(None, 0, unavailable_reason='pose_fit_error'))
            self.assertEqual(c.reason, 'pose_fit_error')
            self.assertEqual(c.elapsed, 0)
        c = Calibration(self.settings)
        c.add(replace(NEUTRAL, eye_x=None), 0)
        self.assertEqual(c.reason, 'eyes_uncertain')

    def test_short_blink_does_not_add_evidence_time(self):
        c = Calibration(self.settings)
        c.add(NEUTRAL, 0)
        c.add(NEUTRAL, .2)
        c.add(None, .3)
        c.add(NEUTRAL, .5)
        self.assertAlmostEqual(c.elapsed, .2)
        self.assertEqual(len(c.samples), 3)

    def test_long_loss_resets_calibration(self):
        c = Calibration(self.settings)
        c.add(NEUTRAL, 0)
        c.add(NEUTRAL, .2)
        c.add(NEUTRAL, 2)
        self.assertEqual(len(c.samples), 1)
        self.assertEqual(c.elapsed, 0)

    def test_rejects_sideways_baseline(self):
        c = Calibration(self.settings)
        c.add(replace(NEUTRAL, yaw=50), 0)
        self.assertEqual(len(c.samples), 0)

    def test_invalid_configuration(self):
        for changes in ({'sample_period': 0}, {'confirm_samples': True}, {'return_ratio': 1},
                        {'min_brightness': 240, 'max_brightness': 220}, {'max_sample_gap': float('nan')}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(Settings(), **changes)


class DirectionTests(unittest.TestCase):
    def setUp(self):
        self.settings = replace(Settings(), smoothing_seconds=.001)

    def test_baseline_offsets_are_subtracted(self):
        baseline = replace(NEUTRAL, pitch=12, yaw=-9, eye_x=.1)
        d = Direction(baseline, self.settings)
        state, reason, values = d.classify(baseline, 0)
        self.assertEqual(state, 'centered')
        self.assertEqual(values['yaw_delta'], 0)

    def test_yaw_pitch_and_eye_deviation(self):
        for m, reason in ((replace(NEUTRAL, yaw=30), 'head_deviation'),
                          (replace(NEUTRAL, pitch=-25), 'head_deviation'),
                          (replace(NEUTRAL, eye_x=.25), 'eye_direction_deviation'),
                          (replace(NEUTRAL, eye_y=.1), 'eye_direction_deviation')):
            with self.subTest(reason=reason):
                state, actual, _ = Direction(NEUTRAL, self.settings).classify(m, 0)
                self.assertEqual((state, actual), ('away', reason))

    def test_roll_alone_does_not_imply_away(self):
        self.assertEqual(Direction(NEUTRAL, self.settings).classify(replace(NEUTRAL, roll=20), 0)[0], 'centered')

    def test_missing_eyes_not_evidence_of_away(self):
        d = Direction(NEUTRAL, self.settings)
        self.assertEqual(d.classify(replace(NEUTRAL, eye_x=None, eye_y=None), 0)[0], 'unknown')

    def test_turned_head_can_be_observed_with_unknown_eyes(self):
        d = Direction(NEUTRAL, self.settings)
        self.assertEqual(d.classify(replace(NEUTRAL, yaw=30, eye_x=None, eye_y=None), 0)[0], 'away')

    def test_head_only_disables_eye_heuristic(self):
        d = Direction(NEUTRAL, self.settings, head_only=True)
        self.assertEqual(d.classify(replace(NEUTRAL, eye_x=.4), 0)[0], 'centered')

    def test_hysteresis_prevents_boundary_flapping(self):
        d = Direction(NEUTRAL, self.settings, head_only=True)
        self.assertEqual(d.classify(replace(NEUTRAL, yaw=30), 0)[0], 'away')
        self.assertEqual(d.classify(replace(NEUTRAL, yaw=23), .1)[0], 'away')
        self.assertEqual(d.classify(replace(NEUTRAL, yaw=15), .2)[0], 'centered')

    def test_large_distance_change_needs_recalibration(self):
        d = Direction(NEUTRAL, self.settings)
        self.assertEqual(d.classify(replace(NEUTRAL, face_width=.6), 0)[:2], ('unknown', 'distance_changed_recalibrate'))

    def test_angle_wrap_uses_shortest_difference(self):
        self.assertEqual(angle_delta(-179, 179), 2)


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings()
        self.o = Observer(self.settings)
        self.now = 0

    def feed(self, state, seconds, observer=None):
        observer = observer or self.o
        events = []
        for _ in range(round(seconds/.1)+1):
            events.extend(observer.update(state, round(self.now, 5), 'test_geometry'))
            self.now += .1
        return events

    def test_brief_turn_does_not_start(self):
        self.assertEqual(self.feed('away', .5), [])
        self.assertEqual(self.feed('centered', 1), [])

    def test_start_then_clear_once(self):
        events = self.feed('away', 4)
        self.assertEqual([e['event'] for e in events], ['look_away_started'])
        events = self.feed('centered', 2)
        self.assertEqual([e['event'] for e in events], ['look_away_ended'])
        self.assertTrue(self.o.armed)

    def test_three_distinct_episodes_trigger_repeat(self):
        events = []
        for _ in range(3):
            events += self.feed('away', 2)
            events += self.feed('centered', 1)
        repeats = [e for e in events if e['event'] == 'repeated_look_away']
        self.assertEqual(len(repeats), 1)
        self.assertEqual(repeats[0]['count'], 3)

    def test_long_single_turn_is_not_repeated(self):
        events = self.feed('away', 20)
        self.assertNotIn('repeated_look_away', [e['event'] for e in events])
        self.assertEqual(len(self.o.episodes), 1)

    def test_short_blink_pauses_confirmation_time(self):
        self.feed('away', .5)
        before = self.o.seconds
        self.feed('unknown', .2)
        self.o.update('away', self.now)
        self.assertAlmostEqual(self.o.seconds, before)
        self.assertFalse(self.o.active)

    def test_unknown_never_counts_as_return(self):
        self.feed('away', 2)
        events = self.feed('unknown', 1)
        self.assertEqual([e['event'] for e in events], ['look_away_interrupted'])
        self.assertFalse(self.o.active)
        self.assertFalse(self.o.armed)

    def test_reacquiring_same_episode_does_not_count_twice(self):
        self.feed('away', 2)
        self.feed('unknown', 1)
        events = self.feed('away', 2)
        self.assertFalse(events[0]['distinct_episode'])
        self.assertEqual(len(self.o.episodes), 1)
        self.feed('centered', 1)
        self.feed('away', 2)
        self.assertEqual(len(self.o.episodes), 2)

    def test_large_sample_gap_interrupts(self):
        self.feed('away', 2)
        events = self.o.update('away', self.now+5)
        self.assertEqual(events[0]['event'], 'look_away_interrupted')
        self.assertEqual(self.o.samples, 1)
        self.assertFalse(self.o.active)

    def test_expired_episodes_leave_window(self):
        self.feed('away', 2)
        self.feed('centered', 61)
        self.assertEqual(len(self.o.episodes), 0)

    def test_repeat_event_has_cooldown(self):
        events = []
        for _ in range(5):
            events += self.feed('away', 2)
            events += self.feed('centered', 1)
        self.assertEqual(sum(e['event'] == 'repeated_look_away' for e in events), 1)

    def test_nonfinite_time_rejected(self):
        with self.assertRaises(ValueError):
            self.o.update('away', math.nan)


class TrackingAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings()
        self.tracking = TrackingAvailability(self.settings)
        self.time = 0.

    def feed(self, available, samples, reason='no_face'):
        events = []
        for _ in range(samples):
            events += self.tracking.update(available, round(self.time, 5), reason)
            self.time += .1
        return events

    def test_brief_loss_and_scattered_bad_frames_do_not_confirm(self):
        for _ in range(3):
            self.assertEqual(self.feed(False, 10), [])
            self.assertEqual(self.feed(True, 2), [])
        self.assertFalse(self.tracking.active)

    def test_sustained_loss_then_recovery_emits_once_each(self):
        events = self.feed(False, 40)
        self.assertEqual([r['event'] for r in events], ['face_tracking_unavailable'])
        self.assertEqual(events[0]['reason'], 'no_face')
        self.assertEqual(events[0]['status'], 'unknown')
        events = self.feed(True, 20)
        self.assertEqual([r['event'] for r in events], ['face_tracking_recovered'])
        self.assertEqual(events[0]['unavailable_reason_counts'], {'no_face': 40})
        self.assertFalse(self.tracking.active)

    def test_brief_reappearance_does_not_report_recovery(self):
        self.feed(False, 25)
        self.assertEqual(self.feed(True, 4), [])
        self.assertEqual(self.feed(False, 20, 'image_blurred'), [])
        self.assertTrue(self.tracking.active)
        events = self.feed(True, 10)
        self.assertEqual(events[0]['unavailable_reason_counts'], {'no_face': 25, 'image_blurred': 20})

    def test_sparse_frames_do_not_prove_continuous_loss(self):
        for now in (0., 2., 4., 6.):
            self.assertEqual(self.tracking.update(False, now, 'no_face'), [])
        self.assertFalse(self.tracking.active)

    def test_gap_interrupts_active_loss_without_claiming_recovery(self):
        self.feed(False, 25)
        events = self.tracking.update(True, self.time+2)
        self.assertEqual([r['event'] for r in events], ['face_tracking_interrupted'])
        self.assertEqual(events[0]['reason'], 'sample_gap')

    def test_stop_does_not_claim_recovery(self):
        self.feed(False, 25)
        events = self.tracking.interrupt('session_ended')
        self.assertEqual([r['event'] for r in events], ['face_tracking_interrupted'])
        self.assertEqual(self.tracking.interrupt('session_ended'), [])

    def test_recovery_can_happen_while_head_remains_away(self):
        self.feed(False, 25)
        direction = Direction(NEUTRAL, self.settings, head_only=True)
        state = direction.classify(replace(NEUTRAL, yaw=40), self.time)[0]
        self.assertEqual(state, 'away')
        events = self.feed(True, 10)
        self.assertEqual(events[0]['event'], 'face_tracking_recovered')
        self.assertNotIn('look_away_ended', [r['event'] for r in events])

    def test_missing_face_never_increments_direction_episodes(self):
        observer = Observer(self.settings)
        for i in range(50):
            self.tracking.update(False, i*.1, 'no_face')
            self.assertEqual(observer.update('unknown', i*.1, 'no_face'), [])
        self.assertTrue(self.tracking.active)
        self.assertEqual(len(observer.episodes), 0)


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.objects = canonical_points(Path(__file__).resolve().parents[2]/'model_assets/canonical_face_model.obj')

    def test_pnp_recovers_projected_known_rotations(self):
        for pitch, yaw, roll in ((0, 0, 0), (20, 0, 0), (0, -30, 0), (10, 25, 5)):
            rx, ry, rz = [cv2.Rodrigues(np.array(axis, float))[0] for axis in
                          ((math.radians(pitch), 0, 0), (0, math.radians(yaw), 0), (0, 0, math.radians(roll)))]
            rotation = rz @ ry @ rx
            vector = cv2.Rodrigues(rotation)[0]
            points = cv2.projectPoints(self.objects, vector, np.array([0., 0., 60.]), camera_matrix(640, 480), np.zeros(5))[0].reshape(-1, 2)
            pose = solve_pose(points, self.objects, 640, 480, 150, .07)
            self.assertIsNotNone(pose)
            np.testing.assert_allclose(pose[:3], (pitch, yaw, roll), atol=.01)

    def test_bad_pose_fit_rejected(self):
        points = cv2.projectPoints(self.objects, np.zeros(3), np.array([0., 0., 60.]),
                                  camera_matrix(640, 480), np.zeros(5))[0].reshape(-1, 2)
        points[0] += [15., -10.]
        info = {}
        self.assertIsNone(solve_pose(points, self.objects, 640, 480, 100, .001, info))
        self.assertEqual(info['pose_failure'], 'pose_fit_error')
        self.assertGreater(info['reprojection_ratio'], .001)

    def test_small_landmark_noise_does_not_lose_neutral_pose(self):
        # Regression: unseeded ITERATIVE/DLT put some of these faces behind the
        # camera. Never use personal images/landmarks as test fixtures.
        rng = np.random.default_rng(81)
        for case in range(60):
            vector = rng.uniform(-.12, .12, 3)
            points = cv2.projectPoints(self.objects, vector, np.array([0., 0., 60.]),
                                      camera_matrix(1280, 720), np.zeros(5))[0].reshape(-1, 2)
            points += rng.normal(0, 2, points.shape)
            expected = cv2.RQDecomp3x3(cv2.Rodrigues(vector)[0])[0]
            info = {}
            with self.subTest(case=case):
                pose = solve_pose(points, self.objects, 1280, 720, 300, .07, info)
                self.assertIsNotNone(pose)
                np.testing.assert_allclose(pose[:3], expected, atol=6)
                self.assertNotIn('pose_failure', info)

    def test_extreme_turn_remains_unknown(self):
        vector = np.array([0., math.radians(83), 0.])
        points = cv2.projectPoints(self.objects, vector, np.array([0., 0., 60.]),
                                  camera_matrix(640, 480), np.zeros(5))[0].reshape(-1, 2)
        info = {}
        self.assertIsNone(solve_pose(points, self.objects, 640, 480, 150, .07, info))
        self.assertEqual(info['pose_failure'], 'pose_angle_out_of_range')

    def test_negative_depth_is_still_rejected(self):
        vector, translation = np.zeros((3, 1)), np.array([[0.], [0.], [-60.]])
        points = np.arange(12., dtype=float).reshape(6, 2)
        points[1, 0] += 3
        info = {}
        with patch('ai_proctor.core.gaze_vision.cv2.solvePnP', return_value=(True, vector, translation)), \
                patch('ai_proctor.core.gaze_vision.cv2.solvePnPRefineLM', return_value=(vector, translation)):
            self.assertIsNone(solve_pose(points, self.objects, 640, 480, 150, .07, info))
        self.assertEqual(info['pose_failure'], 'pose_behind_camera')

    def test_collapsed_points_do_not_produce_pose(self):
        info = {}
        self.assertIsNone(solve_pose(np.ones((6, 2)), self.objects, 640, 480, 150, .07, info))
        self.assertEqual(info['pose_failure'], 'pose_invalid_points')

    def test_nonfinite_points_rejected(self):
        self.assertIsNone(solve_pose(np.full((6, 2), np.nan), self.objects, 640, 480, 200, .07))

    def test_iris_ratios_and_blink_guard(self):
        pts = np.zeros((478, 2), float)
        ids = EYES[0]
        pts[list(ids)] = [[100, 100], [140, 100], [110, 95], [110, 105], [130, 95], [130, 105], [120, 100]]
        np.testing.assert_allclose(eye_ratios(pts, ids, Settings()), [0, 0])
        pts[468] = [128, 100]
        np.testing.assert_allclose(eye_ratios(pts, ids, Settings()), [.2, 0])
        pts[[160, 144, 158, 153], 1] = 100
        self.assertIsNone(eye_ratios(pts, ids, Settings()))

    def test_multiple_faces_are_unknown(self):
        v = Vision.__new__(Vision)
        v.settings, v.last_ms = Settings(), -1
        v.mp = types.SimpleNamespace(Image=lambda **kw: kw, ImageFormat=types.SimpleNamespace(SRGB=1))
        v.detector = Mock()
        v.detector.detect_for_video.return_value = types.SimpleNamespace(face_landmarks=[[], []])
        m, info, _ = v.read(np.zeros((480, 640, 3), np.uint8), 1)
        self.assertIsNone(m)
        self.assertEqual(info['reason'], 'multiple_faces')


