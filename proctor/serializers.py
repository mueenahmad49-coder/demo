from rest_framework import serializers
from .models import ProctorEvent

class ProctorEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProctorEvent
        fields = ['student_id', 'event_type', 'timestamp']