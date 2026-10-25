"""Single-process prototype registry; one in-flight frame and cloud request per session."""
import atexit
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone
from .models import AISession, AIEvent
from .inference import Analyzer, identity_settings, gaze_settings
from .checks import Verification
from .core.identity_policy import Monitor as IdentityMonitor, Sample
from .core.gaze_policy import Calibration, Direction, Observer, TrackingAvailability
from .core.objects_policy import Settings as ObjectSettings, Monitor as ObjectMonitor, filter_detections, conditions
from .core.objects_roboflow import RoboflowClient, CloudError


class SessionRuntime:
    def __init__(self, row, analyzer, cloud_consent, head_only=False):
        self.id, self.analyzer = row.id, analyzer
        self.lock = threading.Lock()
        self.last_activity = time.monotonic()
        self.last_frame = None
        self.last_sequence = -1
        self.closed = False
        self.model_error = False
        self.stage = 'precheck'
        self.identity = IdentityMonitor(identity_settings())
        self.verification = Verification(settings.AI_REVERIFY_SECONDS)
        self.gs = gaze_settings()
        self.head_only = head_only
        self.calibration = Calibration(self.gs, head_only)
        self.calibration_started = None
        self.direction = None
        self.observer, self.tracking = Observer(self.gs), TrackingAvailability(self.gs)
        self.gaze_status = 'calibrating'
        self.gaze_reason = 'look_at_screen_center'
        self.os = ObjectSettings(max_sample_gap=15, sample_period=5)
        self.objects = ObjectMonitor(self.os)
        self.object_counts = None
        self.object_status = 'disabled_by_consent' if not cloud_consent else 'not_configured'
        self.cloud = None
        if cloud_consent and settings.ROBOFLOW_API_KEY:
            self.cloud = RoboflowClient(settings.ROBOFLOW_WORKSPACE, settings.ROBOFLOW_WORKFLOW,
                                        settings.ROBOFLOW_API_KEY, timeout=12)
            self.object_status = 'waiting'
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='object-check') if self.cloud else None
        self.pending = None
        self.object_sampled_at = self.last_object = None
        self.next_object = 0
        self.requests = 0
        self.recent = deque(maxlen=30)
        self.record('session', [dict(event='session_created', cloud_uploads_enabled=self.cloud is not None)])

    def record(self, phase, rows):
        for row in rows:
            detail = {k: v for k, v in row.items() if k != 'event'}
            record = AIEvent.objects.create(session_id=self.id, phase=phase, event=row['event'], details=detail)
            self.recent.append(dict(id=record.id, phase=phase, event=record.event,
                                    details=detail, time=record.timestamp.isoformat()))

    def interrupt(self, reason):
        self.record('identity', self.identity.interrupt(reason))
        self.record('gaze', self.tracking.interrupt(reason)+self.observer.interrupt(reason))
        self.verification.streak = 0
        self.gaze_status, self.gaze_reason = 'unknown', reason

    def frame(self, image, jpeg, sequence, now):
        if sequence <= self.last_sequence:
            raise ValueError('Frames must have an increasing sequence number')
        if self.last_frame is not None and now-self.last_frame < .2:
            raise ValueError('Frames are arriving too quickly')
        self.last_sequence, self.last_activity = sequence, now
        if self.last_frame is not None and now-self.last_frame > 1.5:
            self.interrupt('frame_gap')
        self.last_frame = now
        try:
            sample, live, measurement, quality = self.analyzer.analyze(image, now, self.verification.due(now))
            self.model_error = False
        except Exception:
            # Never expose raw exceptions, paths, frames, credentials or old successes.
            self.interrupt('model_unavailable')
            if not self.model_error:
                self.record('system', [dict(event='model_unavailable', status='unknown')])
            self.model_error = True
            sample, live, measurement, quality = Sample(None, 'model_unavailable'), 'model_unavailable', None, 'model_unavailable'
        self.record('identity', self.identity.update(sample, now))
        self.record('liveness', self.verification.observe(live, now))
        if self.calibration_started is None:
            self.calibration_started = now
        if self.direction is None:
            if now-self.calibration_started > self.gs.calibration_timeout:
                self.gaze_status, self.gaze_reason = 'retry_needed', 'calibration_timed_out'
            else:
                baseline = self.calibration.add(measurement, now, quality)
                self.gaze_status, self.gaze_reason = 'calibrating', self.calibration.reason
                if baseline:
                    self.direction = Direction(baseline, self.gs, self.head_only)
                    self.gaze_status, self.gaze_reason = 'ready', 'calibrated'
                    self.record('gaze', [dict(event='calibration_completed', head_only=self.head_only)])
                    # Keep the baseline only; discard per-frame calibration samples.
                    self.calibration.samples.clear()
        else:
            available = measurement is not None and measurement.valid()
            self.record('gaze', self.tracking.update(available, now, quality))
            state, reason, _ = self.direction.classify(measurement, now)
            self.gaze_status, self.gaze_reason = state, reason
            if self.stage == 'exam':
                self.record('gaze', self.observer.update(state, now, reason))
        self.update_objects(jpeg, now)
        return self.view(now)

    def update_objects(self, jpeg, now):
        if self.cloud is None:
            return
        if self.pending and self.pending.done():
            try:
                width, height, predictions = self.pending.result()
                if now-self.object_sampled_at > 15:
                    raise CloudError('stale_result')
                detections = filter_detections(predictions, width, height, self.os)
                self.record('objects', self.objects.update(detections, self.object_sampled_at))
                self.object_counts, _ = conditions(detections)
                self.last_object = self.object_sampled_at
                self.object_status = 'available'
            except Exception:
                self.record('objects', self.objects.interrupt('cloud_unavailable'))
                self.object_counts = None
                self.object_status = 'unavailable'
            self.pending = None
        if self.last_object is not None and now-self.last_object > 15:
            self.record('objects', self.objects.interrupt('stale_result'))
            self.object_counts, self.last_object = None, None
            self.object_status = 'unknown'
        if not self.pending and now >= self.next_object and self.requests < settings.AI_CLOUD_MAX_REQUESTS:
            self.object_sampled_at = now
            self.pending = self.pool.submit(self.cloud.infer, jpeg)
            self.requests += 1
            self.next_object = now+self.os.sample_period
        elif not self.pending and self.requests >= settings.AI_CLOUD_MAX_REQUESTS:
            self.object_status = 'request_limit_reached'

    def ready(self, now):
        return (not self.closed and self.last_frame is not None and now-self.last_frame <= 2
                and self.identity.verified and self.verification.status == 'verified' and self.direction is not None)

    def view(self, now=None):
        now = time.monotonic() if now is None else now
        fresh = self.last_frame is not None and now-self.last_frame <= 2
        identity = self.identity.progress()
        if not fresh:
            identity = dict(identity, identity_status='unknown')
        object_fresh = self.last_object is not None and now-self.last_object <= 15
        return dict(session_id=str(self.id), stage=self.stage, ready=self.ready(now),
                    identity=identity, verification=self.verification.view(),
                    gaze=dict(status=self.gaze_status if fresh else 'unknown', reason=self.gaze_reason,
                              head_only=self.head_only, calibration_samples=len(self.calibration.samples)),
                    objects=dict(status=self.object_status, counts=self.object_counts if object_fresh else None,
                                 active=self.objects.active() if object_fresh else [], requests=self.requests,
                                 model_reported='rfdetr-small', checkpoint_verified=False),
                    frame_fresh=fresh, events=list(self.recent), sample_period_ms=400)

    def begin(self, now):
        if self.stage != 'precheck' or not self.ready(now):
            raise ValueError('Complete fresh identity, liveness and calibration checks first')
        self.stage = 'exam'
        self.verification.stage = 'periodic'
        self.verification.next_due = now+settings.AI_REVERIFY_SECONDS
        AISession.objects.filter(pk=self.id).update(status='exam')
        self.record('session', [dict(event='exam_monitoring_started')])

    def retry(self, head_only=None):
        self.record('identity', self.identity.interrupt('checks_restarted'))
        self.verification.retry('pre_exam' if self.stage == 'precheck' else 'periodic')
        if head_only is not None:
            self.head_only = head_only
        self.record('gaze', self.observer.interrupt('recalibration')+self.tracking.interrupt('recalibration'))
        self.calibration = Calibration(self.gs, self.head_only)
        self.direction = self.calibration_started = None
        self.gaze_status, self.gaze_reason = 'calibrating', 'look_at_screen_center'
        self.last_activity = time.monotonic()
        self.record('session', [dict(event='checks_restarted')])

    def close(self, reason='user_stopped'):
        if self.closed:
            return
        self.closed = True
        try:
            self.interrupt('session_ended')
            self.record('objects', self.objects.interrupt('session_ended'))
            self.record('session', [dict(event='session_ended', reason=reason)])
            AISession.objects.filter(pk=self.id).update(status='ended', ended_at=timezone.now())
        finally:
            self.analyzer.close()
            self.calibration.reset()
            self.direction = None
            if self.pending:
                self.pending.cancel()
            if self.pool:
                self.pool.shutdown(wait=False, cancel_futures=True)


class Registry:
    def __init__(self):
        self.entries = {}
        self.lock = threading.RLock()
        self.started = False

    def create(self, row, reference_path, cloud, head_only):
        with self.lock:
            if len(self.entries) >= settings.AI_MAX_SESSIONS:
                raise ValueError('Prototype session limit reached; stop an earlier session or wait two minutes')
            analyzer = Analyzer(reference_path)
            try:
                runtime = SessionRuntime(row, analyzer, cloud, head_only)
            except Exception:
                analyzer.close()
                raise
            self.entries[str(row.id)] = runtime
            if not self.started:
                threading.Thread(target=self.reap, daemon=True, name='ai-cleanup').start()
                self.started = True
            return runtime

    def get(self, key):
        with self.lock:
            return self.entries.get(str(key))

    def remove(self, key):
        with self.lock:
            self.entries.pop(str(key), None)

    def reap(self):
        while True:
            time.sleep(5)
            close_old_connections()
            with self.lock:
                entries = list(self.entries.values())
            for runtime in entries:
                if time.monotonic()-runtime.last_activity > 120 and runtime.lock.acquire(blocking=False):
                    try:
                        runtime.close('idle_timeout')
                        self.remove(runtime.id)
                    except Exception:
                        self.remove(runtime.id)
                    finally:
                        runtime.lock.release()
            close_old_connections()

    def shutdown(self):
        for runtime in list(self.entries.values()):
            if runtime.lock.acquire(timeout=1):
                try:
                    runtime.close('server_stopped')
                except Exception:
                    pass
                finally:
                    runtime.lock.release()


registry = Registry()
atexit.register(registry.shutdown)
