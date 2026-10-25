"""Model-independent observation rules. Outputs are not misconduct judgments."""
from dataclasses import dataclass, field
import math

TARGETS = ('person', 'cell phone', 'book')
CONDITIONS = ('phone_visible', 'book_visible', 'multiple_people_visible', 'person_not_detected')


@dataclass(frozen=True)
class Settings:
    confidence: dict = field(default_factory=lambda: {'person': .50, 'cell phone': .35, 'book': .35})
    nms_iou: float = .5
    confirm_seconds: float = 1
    confirm_samples: int = 3
    clear_seconds: float = 2
    clear_samples: int = 3
    max_sample_gap: float = 5
    sample_period: float = 1
    summary_interval: float = 10
    camera_failure_limit: int = 10

    def __post_init__(self):
        if not isinstance(self.confidence, dict) or set(self.confidence) != set(TARGETS):
            raise ValueError('confidence must specify person, cell phone, and book')
        for value in [*self.confidence.values(), self.nms_iou]:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 1:
                raise ValueError('Confidence and NMS IoU must be in (0, 1]')
        for key in ('confirm_seconds', 'clear_seconds', 'max_sample_gap', 'sample_period', 'summary_interval'):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'{key} must be finite and positive')
        for key in ('confirm_samples', 'clear_samples', 'camera_failure_limit'):
            if type(getattr(self, key)) is not int or getattr(self, key) < 1:
                raise ValueError(f'{key} must be a positive integer')


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    box: tuple  # Original-frame x1, y1, x2, y2, in pixels.


def iou(a, b):
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0, right-left) * max(0, bottom-top)
    area_a = max(0, a[2]-a[0]) * max(0, a[3]-a[1])
    area_b = max(0, b[2]-b[0]) * max(0, b[3]-b[1])
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0


def filter_detections(detections, width, height, settings):
    """Threshold, clip and class-aware suppress duplicates before person counting."""
    candidates = []
    for detection in detections:
        if detection.label not in TARGETS:
            continue
        if len(detection.box) != 4 or not all(math.isfinite(v) for v in (*detection.box, detection.confidence)):
            continue
        if not settings.confidence[detection.label] <= detection.confidence <= 1:
            continue
        x1, y1, x2, y2 = detection.box
        box = (max(0, min(width, x1)), max(0, min(height, y1)),
               max(0, min(width, x2)), max(0, min(height, y2)))
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        candidates.append(Detection(detection.label, detection.confidence, box))
    kept = []
    for candidate in sorted(candidates, key=lambda x: x.confidence, reverse=True):
        if not any(candidate.label == other.label and iou(candidate.box, other.box) > settings.nms_iou for other in kept):
            kept.append(candidate)
    return kept


def conditions(detections):
    counts = {label: sum(d.label == label for d in detections) for label in TARGETS}
    flags = dict(phone_visible=counts['cell phone'] > 0, book_visible=counts['book'] > 0,
                 multiple_people_visible=counts['person'] >= 2, person_not_detected=counts['person'] == 0)
    return counts, flags


class Evidence:
    def __init__(self):
        self.active = False
        self.since = None
        self.samples = 0
        self.candidate = None

    def update(self, present, now, settings):
        if present == self.active:
            self.since, self.samples, self.candidate = None, 0, None
            return None
        if self.candidate != present:
            self.since, self.samples, self.candidate = now, 0, present
        self.samples += 1
        seconds = settings.confirm_seconds if present else settings.clear_seconds
        samples = settings.confirm_samples if present else settings.clear_samples
        if now-self.since >= seconds and self.samples >= samples:
            self.active = present
            self.since, self.samples, self.candidate = None, 0, None
            return 'observation_started' if present else 'observation_ended'
        return None


class Monitor:
    def __init__(self, settings):
        self.settings = settings
        self.states = {key: Evidence() for key in CONDITIONS}
        self.last_sample = None

    def interrupt(self, reason='observation_gap'):
        events = [dict(event='observation_interrupted', observation=key,
                       status='unknown', reason=reason)
                  for key, state in self.states.items() if state.active]
        self.states = {key: Evidence() for key in CONDITIONS}
        self.last_sample = None
        return events

    def update(self, detections, now):
        if not math.isfinite(now):
            raise ValueError('Invalid monotonic timestamp')
        events = []
        if self.last_sample is not None and (now < self.last_sample or now-self.last_sample > self.settings.max_sample_gap):
            gap = now-self.last_sample
            events.extend(self.interrupt())
            # Pending confirmations used to reset silently. Always expose the gap,
            # even when no observation had accumulated enough samples to start.
            events.append(dict(event='evidence_reset', status='unknown',
                               reason='timestamp_reversed' if gap < 0 else 'sample_gap_exceeded',
                               sample_gap_seconds=round(gap, 3),
                               max_sample_gap_seconds=self.settings.max_sample_gap))
        self.last_sample = now
        counts, flags = conditions(detections)
        for key, present in flags.items():
            event = self.states[key].update(present, now, self.settings)
            if event:
                events.append(dict(event=event, observation=key, counts=counts,
                                   status='review_observation' if present else 'not_observed',
                                   reason='sustained_detection' if present else 'not_detected_in_recent_samples'))
        return events

    def active(self):
        return [key for key, state in self.states.items() if state.active]

    def progress(self):
        """Metadata-only evidence progress for the latest successfully analyzed frame."""
        result = {}
        for key, state in self.states.items():
            pending = state.candidate is not None
            clearing = state.candidate is False
            result[key] = dict(
                state=('clearing' if clearing else 'confirming') if pending else ('active' if state.active else 'idle'),
                samples=state.samples,
                required_samples=self.settings.clear_samples if clearing else self.settings.confirm_samples,
                elapsed_seconds=round(self.last_sample-state.since, 3) if pending else 0,
                required_seconds=self.settings.clear_seconds if clearing else self.settings.confirm_seconds)
        return result
