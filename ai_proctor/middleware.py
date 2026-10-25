from django.http import JsonResponse
from django.core.files.uploadhandler import MemoryFileUploadHandler


class AIUploadLimitMiddleware:
    """Bound AI requests before multipart parsing; never spool AI frames to disk."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/api/ai/') and request.method == 'POST':
            try:
                length = int(request.META.get('CONTENT_LENGTH', '0'))
            except ValueError:
                return JsonResponse({'error': 'Invalid request length'}, status=400)
            if not 0 <= length <= 2 * 1024 * 1024:
                return JsonResponse({'error': 'AI request is too large'}, status=413)
            request.upload_handlers = [MemoryFileUploadHandler(request)]
        return self.get_response(request)
