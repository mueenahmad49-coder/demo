"""Pre-exam and periodic bounded verification with retry and no misconduct verdict."""
class Verification:
    def __init__(self, interval=300):
        self.interval = interval
        self.status = 'checking'
        self.stage = 'pre_exam'
        self.attempt = 1
        self.started = self.last = self.next_due = None
        self.streak = 0
        self.reason = 'face_camera'

    def due(self, now):
        if self.status == 'verified' and self.next_due is not None and now >= self.next_due:
            self.retry('periodic')
        return self.status in ('checking', 'retry_wait')

    def retry(self, stage=None):
        self.status, self.attempt, self.streak = 'checking', 1, 0
        self.started = self.last = self.next_due = None
        self.reason = 'face_camera'
        if stage:
            self.stage = stage

    def observe(self, reason, now):
        if not self.due(now):
            return []
        if self.status == 'retry_wait':
            if now < self.next_due:
                return []
            self.status, self.started, self.streak = 'checking', None, 0
        if self.started is None:
            self.started = now
        if self.last is not None and now-self.last > 1.5:
            self.streak = 0
        self.last, self.reason = now, reason
        self.streak = self.streak+1 if reason == 'verified_sample' else 0
        if self.streak >= 5:
            self.status, self.next_due = 'verified', now+self.interval
            return [dict(event='identity_liveness_verified', stage=self.stage, attempt=self.attempt)]
        if now-self.started >= 15:
            self.streak = 0
            if self.attempt < 3:
                self.attempt += 1
                self.status, self.next_due = 'retry_wait', now+3
                return [dict(event='verification_retry', stage=self.stage, reason=reason, attempt=self.attempt)]
            self.status = 'review_needed'
            return [dict(event='verification_review_needed', stage=self.stage, reason=reason)]
        return []

    def view(self):
        return dict(status=self.status, stage=self.stage, attempt=self.attempt, reason=self.reason)
