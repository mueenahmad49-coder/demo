from django.contrib import admin
from .models import RegisteredReference, AISession, AIEvent


@admin.register(RegisteredReference)
class ReferenceAdmin(admin.ModelAdmin):
    list_display = ('student_id', 'active', 'created_at')
    fields = ('student_id', 'active', 'created_at')
    readonly_fields = ('student_id', 'created_at')

    def has_add_permission(self, request):
        return False  # Enrollment validates a reference through the management command.

    def has_delete_permission(self, request, obj=None):
        return False  # revoke_reference also removes the private photo.


@admin.register(AISession)
class SessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'reference', 'status', 'created_at', 'ended_at')
    exclude = ('token_hash',)
    readonly_fields = ('id', 'reference', 'status', 'cloud_consent', 'created_at', 'ended_at')

    def has_add_permission(self, request):
        return False


@admin.register(AIEvent)
class EventAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'session', 'phase', 'event')
    list_filter = ('phase', 'event')
    readonly_fields = ('session', 'phase', 'event', 'details', 'timestamp')

    def has_add_permission(self, request):
        return False
