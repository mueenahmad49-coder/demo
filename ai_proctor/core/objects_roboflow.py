"""Bounded HTTPS inference and strict parsing; no media or credentials are logged."""
import base64
import http.client
import json
import math
import re
import urllib.error
import urllib.request

from .objects_policy import Detection

MAX_RESPONSE_BYTES = 12 * 1024 * 1024


class ResponseError(ValueError):
    pass


class CloudError(RuntimeError):
    def __init__(self, reason, retryable=False):
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ResponseError('invalid_detection_number')
    return value


def parse_predictions(payload):
    """Accept one image only: REST outputs, UI results, and nested stream envelopes.

    An empty, valid prediction list means no detections. Missing or malformed
    predictions mean unknown, never an empty room. Do not traverse visualization.
    """
    node = payload
    for _ in range(8):
        if isinstance(node, list):
            if len(node) != 1:
                raise ResponseError('expected_one_image_result')
            node = node[0]
        elif isinstance(node, dict):
            if 'error' in node or 'errors' in node:
                raise ResponseError('server_reported_error')
            if isinstance(node.get('image'), dict) and isinstance(node.get('predictions'), list):
                break
            if 'outputs' in node:
                node = node['outputs']
            elif 'predictions' in node:
                node = node['predictions']
            else:
                raise ResponseError('missing_predictions')
        else:
            raise ResponseError('invalid_response_shape')
    else:
        raise ResponseError('response_nesting_limit')
    try:
        width, height = number(node['image']['width']), number(node['image']['height'])
        if not 0 < width <= 16384 or not 0 < height <= 16384:
            raise ResponseError('invalid_image_dimensions')
        if len(node['predictions']) > 10000:
            raise ResponseError('too_many_detections')
        detections = []
        for item in node['predictions']:
            if not isinstance(item, dict) or not isinstance(item.get('class'), str):
                raise ResponseError('invalid_detection_class')
            x, y, w, h, score = (number(item[k]) for k in ('x', 'y', 'width', 'height', 'confidence'))
            if w <= 0 or h <= 0 or not 0 <= score <= 1:
                raise ResponseError('invalid_detection_values')
            box = (x-w/2, y-h/2, x+w/2, y+h/2)
            if not all(math.isfinite(v) for v in box):
                raise ResponseError('invalid_box_coordinates')
            detections.append(Detection(item['class'], score, box))
        return width, height, detections
    except (KeyError, TypeError):
        raise ResponseError('missing_detection_fields') from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Prevent credentials or frame data being forwarded to another endpoint.
        return None


class RoboflowClient:
    def __init__(self, workspace, workflow, api_key, timeout=10, opener=None):
        for value in (workspace, workflow):
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
                raise ValueError('Invalid workspace or workflow identifier')
        if not isinstance(api_key, str) or not re.fullmatch(r'[!-~]+', api_key):
            raise ValueError('Invalid API key; enter it locally without spaces')
        if not 1 <= number(timeout) <= 60:
            raise ValueError('Request timeout must be between 1 and 60 seconds')
        self.url = f'https://serverless.roboflow.com/{workspace}/workflows/{workflow}'
        self._api_key = api_key
        self.timeout = timeout
        self._opener = opener or urllib.request.build_opener(NoRedirect())

    def infer(self, jpeg):
        if not isinstance(jpeg, bytes) or not 0 < len(jpeg) <= 4 * 1024 * 1024:
            raise ValueError('Encoded image must be between 1 byte and 4 MB')
        data = json.dumps({'inputs': {'image': {'type': 'base64',
                          'value': base64.b64encode(jpeg).decode('ascii')}}}).encode('utf-8')
        request = urllib.request.Request(self.url, data=data, method='POST', headers={
            'Content-Type': 'application/json', 'Authorization': f'Bearer {self._api_key}'})
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise CloudError('response_too_large')
            try:
                payload = json.loads(raw)
            except (ValueError, UnicodeError):
                raise CloudError('invalid_json_response') from None
            try:
                return parse_predictions(payload)
            except ResponseError:
                raise CloudError('invalid_predictions_response') from None
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            # Never print response bodies, URLs, request objects or raw exceptions.
            reason = {401: 'authentication_failed', 403: 'access_denied', 404: 'workflow_not_found',
                      429: 'rate_or_credit_limit'}.get(code, f'http_{code}')
            raise CloudError(reason, retryable=500 <= code < 600) from None
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
            raise CloudError('network_unavailable', retryable=True) from None
