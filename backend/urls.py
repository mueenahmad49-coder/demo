from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/proctor/', include('proctor.urls')),
    path('api/ai/', include('ai_proctor.urls')),
]
