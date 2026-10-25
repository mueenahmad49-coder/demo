"""Calibrated geometry and temporal observations, never attention/cheating judgments."""
from collections import Counter, deque
from dataclasses import dataclass
import math
import statistics


@dataclass(frozen=True)
class Settings:
    sample_period: float = .08
    calibration_seconds: float = 4
    calibration_samples: int = 30
    calibration_timeout: float = 45
    calibration_max_gap: float = 1
    calibration_angle_spread: float = 4
    calibration_eye_spread: float = .035
    yaw_threshold: float = 25
    pitch_threshold: float = 18
    eye_horizontal_threshold: float = .18
    eye_vertical_threshold: float = .08
    return_ratio: float = .7
    smoothing_seconds: float = .15
    confirm_seconds: float = 1.5
    confirm_samples: int = 5
    clear_seconds: float = .75
    clear_samples: int = 3
    tracking_loss_seconds: float = 2
    tracking_loss_samples: int = 5
    tracking_recovery_seconds: float = .75
    tracking_recovery_samples: int = 3
    unknown_grace: float = .5
    max_sample_gap: float = .6
    repeated_window: float = 60
    repeated_count: int = 3
    repeated_cooldown: float = 60
    summary_interval: float = 5
    min_face_width: float = 120
    min_eye_width: float = 18
    min_eye_open_ratio: float = .12
    min_sharpness: float = 20
    min_brightness: float = 35
    max_brightness: float = 220
    max_reprojection_ratio: float = .07

    def __post_init__(self):
        ints = ('calibration_samples', 'confirm_samples', 'clear_samples', 'repeated_count',
                'tracking_loss_samples', 'tracking_recovery_samples')
        for key, value in vars(self).items():
            if key in ints:
                if type(value) is not int or value < 2:
                    raise ValueError(f'{key} must be an integer >= 2')
            elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'{key} must be finite and positive')
        if not self.sample_period < self.max_sample_gap:
            raise ValueError('sample_period must be less than max_sample_gap')
        if not 0 < self.return_ratio < 1 or self.max_brightness > 255 or self.min_brightness >= self.max_brightness:
            raise ValueError('Invalid hysteresis or brightness range')


@dataclass(frozen=True)
class Measurement:
    pitch: float
    yaw: float
    roll: float
    eye_x: float | None
    eye_y: float | None
    face_width: float  # Fraction of frame width, used only to detect large distance changes.

    def valid(self, eyes=False):
        vals = (self.pitch, self.yaw, self.roll, self.face_width)
        if eyes:
            vals += (self.eye_x, self.eye_y)
        return all(v is not None and math.isfinite(v) for v in vals) and self.face_width > 0


def angle_delta(angle, baseline):
    return (angle-baseline+180) % 360-180


class Calibration:
    def __init__(self, settings, head_only=False):
        self.settings, self.head_only = settings, head_only
        self.reset()

    def reset(self):
        self.samples = []
        self.elapsed = 0
        self.last_good = None
        self.last_was_good = False
        self.baseline = None
        self.reason = 'look_at_screen_center'

    def add(self, measurement, now, unavailable_reason='tracking_unavailable'):
        if not math.isfinite(now):
            raise ValueError('Invalid timestamp')
        if self.last_good is not None and (now < self.last_good or now-self.last_good > self.settings.calibration_max_gap):
            self.reset()
        if measurement is None or not measurement.valid():
            self.last_was_good = False
            self.reason = unavailable_reason
            return None
        if not self.head_only and not measurement.valid(eyes=True):
            self.last_was_good = False
            self.reason = 'eyes_uncertain'
            return None
        if max(abs(measurement.yaw), abs(measurement.pitch), abs(measurement.roll)) > 35:
            self.reset()
            self.reason = 'face_camera_and_look_at_screen_center'
            return None
        if self.last_good is not None and self.last_was_good:
            self.elapsed += now-self.last_good
        self.last_good, self.last_was_good = now, True
        self.samples.append(measurement)
        self.samples = self.samples[-1000:]
        self.reason = 'hold_still_looking_at_screen_center'
        if self.elapsed < self.settings.calibration_seconds or len(self.samples) < self.settings.calibration_samples:
            return None
        keys = ['pitch', 'yaw', 'roll', 'face_width']
        if not self.head_only:
            keys += ['eye_x', 'eye_y']
        values = {k: [getattr(m, k) for m in self.samples] for k in keys}
        unstable = any(statistics.pstdev(values[k]) > self.settings.calibration_angle_spread for k in ('pitch', 'yaw', 'roll'))
        if not self.head_only:
            unstable |= any(statistics.pstdev(values[k]) > self.settings.calibration_eye_spread for k in ('eye_x', 'eye_y'))
        if unstable:
            self.reset()
            self.reason = 'calibration_moved_retry_while_still'
            return None
        medians = {k: statistics.median(v) for k, v in values.items()}
        medians.setdefault('eye_x', None)
        medians.setdefault('eye_y', None)
        self.baseline = Measurement(**medians)
        self.reason = 'calibrated'
        return self.baseline


class Direction:
    def __init__(self, baseline, settings, head_only=False):
        self.baseline, self.settings, self.head_only = baseline, settings, head_only
        self.reset()

    def reset(self):
        self.filtered = None
        self.last = None
        self.head_away = self.eyes_away = False

    def classify(self, measurement, now):
        s, b = self.settings, self.baseline
        if measurement is None or not measurement.valid():
            self.reset()
            return 'unknown', 'tracking_unavailable', {}
        if not .65 <= measurement.face_width/b.face_width <= 1.5:
            self.reset()
            return 'unknown', 'distance_changed_recalibrate', {}
        values = [angle_delta(measurement.pitch, b.pitch), angle_delta(measurement.yaw, b.yaw)]
        eyes_ok = not self.head_only and measurement.valid(eyes=True) and b.valid(eyes=True)
        values += [measurement.eye_x-b.eye_x, measurement.eye_y-b.eye_y] if eyes_ok else [None, None]
        if self.last is None or now <= self.last or now-self.last > s.max_sample_gap:
            self.filtered = values
            self.head_away = self.eyes_away = False
        else:
            alpha = 1-math.exp(-(now-self.last)/s.smoothing_seconds)
            self.filtered = [v if v is None or old is None else old+alpha*(v-old)
                             for v, old in zip(values, self.filtered)]
        self.last = now
        pitch, yaw, ex, ey = self.filtered
        details = dict(pitch_delta=round(pitch, 1), yaw_delta=round(yaw, 1),
                       eye_x_delta=round(ex, 3) if ex is not None else None,
                       eye_y_delta=round(ey, 3) if ey is not None else None)
        ratio = s.return_ratio if self.head_away else 1
        self.head_away = abs(yaw) >= s.yaw_threshold*ratio or abs(pitch) >= s.pitch_threshold*ratio
        if self.head_away:
            self.eyes_away = False
            return 'away', 'head_deviation', details
        if self.head_only:
            return 'centered', 'near_calibrated_head_direction', details
        # Iris ratios become unreliable at larger head angles; do not manufacture gaze.
        if not eyes_ok or abs(yaw) > 15 or abs(pitch) > 12:
            self.eyes_away = False
            return 'unknown', 'eye_direction_uncertain', details
        ratio = s.return_ratio if self.eyes_away else 1
        self.eyes_away = abs(ex) >= s.eye_horizontal_threshold*ratio or abs(ey) >= s.eye_vertical_threshold*ratio
        return ('away', 'eye_direction_deviation', details) if self.eyes_away else ('centered', 'near_calibrated_direction', details)


class TrackingAvailability:
    """Debounced usable-face tracking, independent of direction and identity.

    Only analyzed frames contribute evidence. Camera outages interrupt this
    observation instead of being represented as missing faces or recovery.
    """
    def __init__(self, settings):
        self.settings = settings
        self.active = False
        self.last = None
        self.pending = None
        self.seconds = 0.
        self.samples = 0
        self.reasons = Counter()

    def _clear_pending(self):
        self.pending, self.seconds, self.samples = None, 0., 0

    def interrupt(self, reason):
        events = []
        if self.active:
            events.append(dict(event='face_tracking_interrupted', status='unknown', reason=reason,
                               unavailable_reason_counts=dict(self.reasons)))
        self.active, self.last = False, None
        self._clear_pending()
        self.reasons.clear()
        return events

    def update(self, available, now, reason='tracking_unavailable'):
        if type(available) is not bool or not math.isfinite(now):
            raise ValueError('Invalid tracking availability or timestamp')
        events = []
        dt = 0 if self.last is None else now-self.last
        if self.last is not None and (dt <= 0 or dt > self.settings.max_sample_gap):
            events += self.interrupt('sample_gap')
            dt = 0
        self.last = now
        desired = 'available' if self.active else 'unavailable'
        state = 'available' if available else 'unavailable'
        if not available:
            self.reasons[reason] += 1
        if state != desired:
            self._clear_pending()
            if not self.active:
                self.reasons.clear()
            return events
        if self.pending != state:
            self.pending, self.seconds, self.samples = state, 0., 0
        else:
            self.seconds += dt
        self.samples += 1
        required_seconds = self.settings.tracking_recovery_seconds if self.active else self.settings.tracking_loss_seconds
        required_samples = self.settings.tracking_recovery_samples if self.active else self.settings.tracking_loss_samples
        if self.seconds >= required_seconds and self.samples >= required_samples:
            if self.active:
                events.append(dict(event='face_tracking_recovered', status='tracking_available',
                                   reason='usable_face_tracking_restored', unavailable_reason_counts=dict(self.reasons)))
                self.active = False
                self.reasons.clear()
            else:
                self.active = True
                events.append(dict(event='face_tracking_unavailable', status='unknown',
                                   reason=self.reasons.most_common(1)[0][0],
                                   unavailable_reason_counts=dict(self.reasons),
                                   evidence_seconds=round(self.seconds, 2), samples=self.samples))
            self._clear_pending()
        return events

    def progress(self):
        return dict(unavailable_active=self.active, pending=self.pending, samples=self.samples,
                    evidence_seconds=round(self.seconds, 2))


class Observer:
    """Confirm deviations, return-to-baseline and distinct repeats in a sliding window.

    Unknown frames never contribute evidence time. A brief blink pauses evidence;
    longer uncertainty interrupts it. Reacquiring the same turn cannot count twice
    as a distinct episode without a confirmed return to baseline in between.
    """
    def __init__(self, settings):
        self.settings = settings
        self.active = False
        self.armed = True
        self.last = None
        self.last_state = None
        self.unknown_since = None
        self.pending = None
        self.samples = 0
        self.seconds = 0
        self.episodes = deque()
        self.last_repeat = -math.inf

    def interrupt(self, reason='tracking_unavailable'):
        events = []
        if self.active:
            events.append(dict(event='look_away_interrupted', status='unknown', reason=reason))
            self.armed = False
        self.active = False
        self.pending, self.samples, self.seconds = None, 0, 0
        self.last_state = None
        return events

    def update(self, state, now, reason=''):
        if state not in ('away', 'centered', 'unknown') or not math.isfinite(now):
            raise ValueError('Invalid observation or timestamp')
        events = []
        dt = 0 if self.last is None else now-self.last
        if self.last is not None and (dt < 0 or dt > self.settings.max_sample_gap):
            events.extend(self.interrupt('sample_gap'))
            dt = 0
            self.unknown_since = None
        if self.last is not None and now < self.last:
            self.episodes.clear()
            self.last_repeat = -math.inf
        self.last = now
        while self.episodes and now-self.episodes[0] > self.settings.repeated_window:
            self.episodes.popleft()
        if state == 'unknown':
            if self.unknown_since is None:
                self.unknown_since = now
            if now-self.unknown_since >= self.settings.unknown_grace:
                events.extend(self.interrupt(reason or 'tracking_unavailable'))
            self.last_state = 'unknown'
            return events
        if self.unknown_since is not None and now-self.unknown_since >= self.settings.unknown_grace:
            events.extend(self.interrupt('uncertainty_gap'))
        self.unknown_since = None
        desired = 'centered' if self.active else 'away'
        # A confirmed return can rearm an episode even after interrupted tracking.
        if not self.active and not self.armed and state == 'centered':
            desired = 'centered'
        if state != desired:
            self.pending, self.samples, self.seconds = None, 0, 0
        else:
            if self.pending != state:
                self.pending, self.samples, self.seconds = state, 0, 0
            elif self.last_state == state:
                self.seconds += dt
            self.samples += 1
            is_away = state == 'away'
            count = self.settings.confirm_samples if is_away else self.settings.clear_samples
            seconds = self.settings.confirm_seconds if is_away else self.settings.clear_seconds
            if self.samples >= count and self.seconds >= seconds:
                if is_away:
                    distinct = self.armed
                    self.active, self.armed = True, False
                    events.append(dict(event='look_away_started', reason=reason,
                                       status='review_observation', distinct_episode=distinct))
                    if distinct:
                        self.episodes.append(now)
                        if len(self.episodes) >= self.settings.repeated_count and now-self.last_repeat >= self.settings.repeated_cooldown:
                            events.append(dict(event='repeated_look_away', count=len(self.episodes),
                                               window_seconds=self.settings.repeated_window,
                                               status='review_observation'))
                            self.last_repeat = now
                else:
                    if self.active:
                        events.append(dict(event='look_away_ended', status='near_baseline', reason='returned_to_calibrated_direction'))
                    self.active, self.armed = False, True
                self.pending, self.samples, self.seconds = None, 0, 0
        self.last_state = state
        return events

    def progress(self):
        return dict(active=self.active, pending=self.pending, samples=self.samples,
                    evidence_seconds=round(self.seconds, 2), distinct_episodes_in_window=len(self.episodes))
