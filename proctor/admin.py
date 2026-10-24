from django.contrib import admin
from .models import Question, ProctorEvent, ProctorSnapshot

admin.site.register(Question)
admin.site.register(ProctorEvent)
admin.site.register(ProctorSnapshot)