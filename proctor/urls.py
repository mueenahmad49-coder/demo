from django.urls import path
from .views import log_proctor_event, get_questions, get_proctor_events, save_snapshot

urlpatterns = [
    path('log-event', log_proctor_event, name='log-event'),
    path('questions', get_questions, name='get-questions'),
    path('events', get_proctor_events, name='get-events'),
    path('save-snapshot', save_snapshot, name='save-snapshot'),
]