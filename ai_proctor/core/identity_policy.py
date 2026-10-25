"""Temporal face-presence and reference-comparison observations, not exam decisions."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Settings:
    sample_period: float = .25
    max_sample_gap: float = 1.
    absence_seconds: float = 3.
    absence_samples: int = 5
    multiple_seconds: float = 2.
    multiple_samples: int = 3
    match_seconds: float = 1.
    match_samples: int = 3
    mismatch_seconds: float = 3.
    mismatch_samples: int = 5
    return_seconds: float = 1.
    return_samples: int = 3
    match_threshold: float = .45
    mismatch_threshold: float = .25
    detector_threshold: float = .9
    min_face: float = 100
    min_sharpness: float = 20
    min_brightness: float = 35
    max_brightness: float = 220
    summary_interval: float = 5

    def __post_init__(self):
        for key, value in vars(self).items():
            if key.endswith('_samples'):
                if type(value) is not int or value < 2:
                    raise ValueError(f'{key} must be an integer >= 2')
            elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'{key} must be finite and positive')
        if not 0 < self.mismatch_threshold < self.match_threshold < 1:
            raise ValueError('Require 0 < mismatch_threshold < match_threshold < 1')
        if not 0 < self.detector_threshold < 1 or self.sample_period >= self.max_sample_gap:
            raise ValueError('Invalid detection threshold or sample timing')
        if self.min_brightness >= self.max_brightness or self.max_brightness > 255:
            raise ValueError('Invalid brightness limits')


@dataclass(frozen=True)
class Sample:
    faces: int | None
    reason: str
    score: float | None = None


class Streak:
    def __init__(self, max_gap):
        self.max_gap = max_gap
        self.reset()

    def reset(self):
        self.label = self.last = self.start = None
        self.samples = 0

    def add(self, label, now):
        if label is None:
            self.reset()
            return
        if self.label != label or self.last is None or not 0 < now-self.last <= self.max_gap:
            self.label, self.start, self.samples = label, now, 0
        self.last = now
        self.samples += 1

    def ready(self, seconds, samples):
        return self.samples >= samples and self.last-self.start >= seconds


def identity_label(sample, settings):
    if sample.faces != 1 or sample.reason != 'quality_ok':
        return None
    score = sample.score
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not -1 <= score <= 1:
        return None
    if score >= settings.match_threshold:
        return 'match'
    if score <= settings.mismatch_threshold:
        return 'mismatch'
    return None


class Monitor:
    def __init__(self, settings):
        self.s = settings
        self.presence = Streak(settings.max_sample_gap)
        self.crowd = Streak(settings.max_sample_gap)
        self.identity = Streak(settings.max_sample_gap)
        self.last = None
        self.absent = self.multiple = self.verified = self.review_pending = False
        self.identity_status = 'unknown'

    def interrupt(self, reason):
        events = []
        if self.absent:
            events.append(dict(event='face_absence_interrupted', status='unknown', reason=reason))
        if self.multiple:
            events.append(dict(event='multiple_faces_interrupted', status='unknown', reason=reason))
        if self.verified:
            events.append(dict(event='identity_recheck_required', status='unknown', reason=reason))
        self.absent = self.multiple = self.verified = False
        self.identity_status = 'unknown'
        for streak in (self.presence, self.crowd, self.identity):
            streak.reset()
        self.last = None
        # An unresolved mismatch is not cleared by losing the camera or face.
        return events

    def update(self, sample, now):
        if not math.isfinite(now) or (sample.faces is not None and (type(sample.faces) is not int or sample.faces < 0)):
            raise ValueError('Invalid sample or timestamp')
        s, events = self.s, []
        if self.last is not None and not 0 < now-self.last <= s.max_sample_gap:
            events += self.interrupt('sample_gap')
        self.last = now
        if sample.faces is None:
            return events + self.interrupt(sample.reason)

        presence = 'absent' if sample.faces == 0 else 'present'
        self.presence.add(presence, now)
        if not self.absent and presence == 'absent' and self.presence.ready(s.absence_seconds, s.absence_samples):
            self.absent = True
            events.append(dict(event='face_absence_observed', status='review_observation', reason='no_face_detected',
                               guidance='Face detection is unavailable; a full turn or occlusion can also cause this.'))
        elif self.absent and presence == 'present' and self.presence.ready(s.return_seconds, s.return_samples):
            self.absent = False
            events.append(dict(event='face_detection_restored', status='detected', identity_confirmation_separate=True))

        crowd = 'multiple' if sample.faces > 1 else 'other'
        self.crowd.add(crowd, now)
        if not self.multiple and crowd == 'multiple' and self.crowd.ready(s.multiple_seconds, s.multiple_samples):
            self.multiple = True
            events.append(dict(event='multiple_faces_observed', status='review_observation', reason='more_than_one_face_detected'))
        elif self.multiple and crowd == 'other' and self.crowd.ready(s.return_seconds, s.return_samples):
            self.multiple = False
            events.append(dict(event='multiple_faces_cleared', status='detection_changed', reason='multiple_faces_no_longer_detected'))

        label = identity_label(sample, s)
        if self.verified and label != 'match':
            self.verified = False
            events.append(dict(event='identity_recheck_required', status='unknown',
                               reason=sample.reason if sample.reason != 'quality_ok' else 'reference_comparison_changed'))
        self.identity.add(label, now)
        self.identity_status = 'unknown' if label is None else 'pending_'+label
        if label == 'match' and self.identity.ready(s.match_seconds, s.match_samples):
            if not self.verified:
                events.append(dict(event='reference_match_confirmed', status='reference_match', liveness_checked=False))
                if self.review_pending:
                    events.append(dict(event='identity_review_resolved', status='reference_match', reason='reference_match_reconfirmed'))
            self.verified, self.review_pending = True, False
            self.identity_status = 'reference_match'
        elif label == 'mismatch' and self.identity.ready(s.mismatch_seconds, s.mismatch_samples):
            if not self.review_pending:
                events.append(dict(event='identity_mismatch_review', status='review_needed',
                                   reason='sustained_low_reference_similarity',
                                   guidance='Face the camera and retry. If unresolved, use supervised verification; this is not an impersonation finding.'))
            self.review_pending = True
            self.identity_status = 'review_needed'
        return events

    def progress(self):
        return dict(face_absence_active=self.absent, multiple_faces_active=self.multiple,
                    identity_status=self.identity_status, identity_review_pending=self.review_pending,
                    identity_evidence_samples=self.identity.samples)
