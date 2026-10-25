from django.urls import path
from . import views

urlpatterns = [
    path('capabilities', views.capabilities),
    path('sessions', views.start),
    path('sessions/<uuid:session_id>/frames', views.frames),
    path('sessions/<uuid:session_id>/<str:action>', views.control),
    path('review', views.review),
]
