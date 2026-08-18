import io
import json
from unittest.mock import patch

from morns.remote import HttpObservationSink


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_remote_sink_sends_bearer_token_and_packet():
    captured = {}

    def open_request(request, timeout):
        captured["authorization"] = request.get_header("Authorization")
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response(b'{"status":"accepted","id":7}')

    sink = HttpObservationSink("http://127.0.0.1:8787", "secret")
    with patch("urllib.request.urlopen", open_request):
        assert sink.add({"receiver_id": "one", "transport": "LORA"}) == 7
    assert captured["authorization"] == "Bearer secret"
    assert captured["payload"]["receiver_id"] == "one"
    assert captured["timeout"] == 10
