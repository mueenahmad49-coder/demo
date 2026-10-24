from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import ProctorEvent, Question, ProctorSnapshot

@api_view(['POST'])
def log_proctor_event(request):
    student_id = request.data.get('student_id')
    event_type = request.data.get('event_type')
    
    if not student_id or not event_type:
        return Response({"error": "student_id and event_type are required"}, status=400)
    
    ProctorEvent.objects.create(
        student_id=student_id,
        event_type=event_type
    )
    return Response({"message": "Event logged successfully"}, status=201)

@api_view(['GET'])
def get_questions(request):
    questions = Question.objects.all().values('id', 'question_text')
    return Response(list(questions))

@api_view(['GET'])
def get_proctor_events(request):
    events = ProctorEvent.objects.all().order_by('-id').values('id', 'student_id', 'event_type', 'timestamp')
    return Response(list(events))

@api_view(['POST'])
def save_snapshot(request):
    student_id = request.data.get('student_id')
    image_data = request.data.get('image_data')

    if not student_id or not image_data:
        return Response({"error": "student_id and image_data are required"}, status=400)

    ProctorSnapshot.objects.create(
        student_id=student_id,
        image_data=image_data
    )
    return Response({"message": "Snapshot saved successfully"}, status=201)