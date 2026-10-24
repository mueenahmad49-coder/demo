from django.db import models

class Question(models.Model):
    question_text = models.TextField()

    def __str__(self):
        return self.question_text[:50]

class ProctorEvent(models.Model):
    student_id = models.CharField(max_length=100)
    event_type = models.CharField(max_length=100)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.student_id} - {self.event_type}"

class ProctorSnapshot(models.Model):
    student_id = models.CharField(max_length=100)
    image_data = models.TextField()  # Base64 encoded snapshot image
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Snapshot - {self.student_id} - {self.timestamp}"