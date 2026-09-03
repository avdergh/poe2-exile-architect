from __future__ import annotations

import json
from types import SimpleNamespace
import urllib.error
import urllib.parse

import pytest

from server.compute.pob_code import decode_code, encode_code
from server.generation import pob_sharing


XML = "<PathOfBuilding2><Build level=\"95\" /></PathOfBuilding2>"


class _Response:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int) -> bytes:
        return self.body


@pytest.fixture(autouse=True)
def _verified_artifact(monkeypatch):
    monkeypatch.setattr(
        pob_sharing.artifacts,
        "read_final_build_artifact_for_export",
        lambda _artifact_id: (
            SimpleNamespace(
                artifact_id="final-build:test",
                source_hash="sha256:test",
            ),
            XML,
        ),
    )


def test_publish_posts_standard_pob_code_and_returns_safe_url(monkeypatch):
    seen = {}

    def fake_urlopen(request, *, timeout):
        seen["request"] = request
        seen["timeout"] = timeout
        return _Response(b"https://poe.ninja/poe2/pob/abc123\n")

    monkeypatch.setattr(pob_sharing.urllib.request, "urlopen", fake_urlopen)

    result = pob_sharing.publish_final_pob_artifact("final-build:test")

    request = seen["request"]
    posted = urllib.parse.parse_qs(request.data.decode("ascii"), strict_parsing=True)
    assert request.full_url == pob_sharing.UPLOAD_URL
    assert request.method == "POST"
    assert request.headers["Content-type"] == "application/x-www-form-urlencoded"
    assert decode_code(posted["code"][0]) == XML
    assert seen["timeout"] == pob_sharing.UPLOAD_TIMEOUT_SECONDS
    assert result["status"] == "published"
    assert result["url"] == "https://poe.ninja/poe2/pob/abc123"
    assert result["publicExternalUpload"] is True
    assert result["externalUploadContainsPobMaterial"] is True
    serialized = json.dumps(result)
    assert XML not in serialized
    assert encode_code(XML) not in serialized


@pytest.mark.parametrize(
    ("returned", "expected"),
    [
        ("https://poe2.ninja/pob/old123", "https://poe.ninja/poe2/pob/old123"),
        ("https://www.poe.ninja/poe2/pob/new_123/", "https://poe.ninja/poe2/pob/new_123"),
    ],
)
def test_publish_canonicalizes_allowed_legacy_hosts(monkeypatch, returned, expected):
    monkeypatch.setattr(
        pob_sharing.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _Response(returned.encode()),
    )

    result = pob_sharing.publish_final_pob_artifact("final-build:test")

    assert result["status"] == "published"
    assert result["url"] == expected


@pytest.mark.parametrize(
    "returned",
    [
        "https://example.com/poe2/pob/abc123",
        "http://poe.ninja/poe2/pob/abc123",
        "https://poe.ninja/poe2/pob/abc123?code=secret",
        "not-a-url",
        "",
    ],
)
def test_publish_rejects_untrusted_or_malformed_response(monkeypatch, returned):
    monkeypatch.setattr(
        pob_sharing.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _Response(returned.encode()),
    )

    result = pob_sharing.publish_final_pob_artifact("final-build:test")

    assert result["status"] == "failed"
    assert result["errorCode"] == "poe_ninja_upload_response_invalid"
    assert "url" not in result


def test_publish_normalizes_http_and_network_errors(monkeypatch):
    def http_error(*_args, **_kwargs):
        raise urllib.error.HTTPError(pob_sharing.UPLOAD_URL, 503, "down", None, None)

    monkeypatch.setattr(pob_sharing.urllib.request, "urlopen", http_error)
    http_result = pob_sharing.publish_final_pob_artifact("final-build:test")
    monkeypatch.setattr(
        pob_sharing.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )
    network_result = pob_sharing.publish_final_pob_artifact("final-build:test")

    assert http_result["errorCode"] == "poe_ninja_upload_http_error"
    assert network_result["errorCode"] == "poe_ninja_upload_unavailable"


def test_publish_does_not_upload_unverified_artifact(monkeypatch):
    monkeypatch.setattr(
        pob_sharing.artifacts,
        "read_final_build_artifact_for_export",
        lambda _artifact_id: None,
    )
    monkeypatch.setattr(
        pob_sharing.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network must not run")),
    )

    result = pob_sharing.publish_final_pob_artifact("final-build:missing")

    assert result["errorCode"] == "final_artifact_not_found_or_corrupt"
