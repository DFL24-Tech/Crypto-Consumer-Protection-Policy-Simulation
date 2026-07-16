"""Object storage: uploads and presigned URLs against a real MinIO."""
import time

import httpx

from dfl24sim_server import storage


def test_upload_returns_metadata_and_keys_by_job(artifact_store):
    meta = storage.upload("job-1", "fig_battery.png", b"png-bytes", "image/png")
    assert meta == {
        "name": "fig_battery.png",
        "key": "jobs/job-1/fig_battery.png",
        "size_bytes": 9,
        "content_type": "image/png",
    }


def test_presigned_url_serves_the_bytes_without_credentials(artifact_store):
    meta = storage.upload("job-2", "battery.parquet", b"parquet-bytes", "application/octet-stream")
    url = storage.presign(meta["key"], expires_in=60)
    response = httpx.get(url)
    assert response.status_code == 200
    assert response.content == b"parquet-bytes"


def test_presigned_url_expires(artifact_store):
    meta = storage.upload("job-3", "a.txt", b"x", "text/plain")
    url = storage.presign(meta["key"], expires_in=1)
    time.sleep(2)
    assert httpx.get(url).status_code == 403


def test_storage_is_unconfigured_without_endpoint(monkeypatch):
    monkeypatch.delenv("DFL24_S3_ENDPOINT", raising=False)
    assert not storage.is_configured()


def test_presign_uses_the_public_endpoint_when_set(artifact_store, monkeypatch):
    """In compose the worker uploads via minio:9000 but the analyst's browser
    needs a host-reachable URL; SigV4 signs the host, so presigning must use
    the public endpoint."""
    meta = storage.upload("job-4", "fig.png", b"x", "image/png")
    monkeypatch.setenv("DFL24_S3_PUBLIC_ENDPOINT", "http://example.test:9000")
    url = storage.presign(meta["key"], expires_in=60)
    assert url.startswith("http://example.test:9000/")
