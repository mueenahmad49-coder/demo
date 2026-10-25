import uuid
from django.db import models


class RegisteredReference(models.Model):
    student_id = models.CharField(max_length=100, unique=True)
    private_filename = models.CharField(max_length=100)
    access_code_hash = models.CharField(max_length=256)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.student_id


class AISession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.ForeignKey(RegisteredReference, on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=32, default='precheck')
    cloud_consent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)


class AIEvent(models.Model):
    session = models.ForeignKey(AISession, on_delete=models.CASCADE, related_name='events')
    phase = models.CharField(max_length=32)
    event = models.CharField(max_length=100)
    details = models.JSONField(default=dict)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
