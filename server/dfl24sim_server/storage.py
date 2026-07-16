"""S3-compatible artifact storage: MinIO in the compose stack, any S3 endpoint in prod.

Heavy job outputs (figures, parquet frames) land here, keyed by job id; the
JSON summaries never do — they stay in Postgres so reading numbers never
requires an object-storage round trip. Storage is configured entirely by
environment: DFL24_S3_ENDPOINT (unset = storage unavailable), DFL24_S3_BUCKET,
DFL24_S3_ACCESS_KEY, DFL24_S3_SECRET_KEY, DFL24_S3_REGION.
"""
import os

DEFAULT_BUCKET = "dfl24-artifacts"


def is_configured() -> bool:
    return bool(os.environ.get("DFL24_S3_ENDPOINT"))


def bucket_name() -> str:
    return os.environ.get("DFL24_S3_BUCKET", DEFAULT_BUCKET)


def artifact_key(job_id: str, name: str) -> str:
    return f"jobs/{job_id}/{name}"


def _client(endpoint: str | None = None):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=endpoint or os.environ["DFL24_S3_ENDPOINT"],
        aws_access_key_id=os.environ.get("DFL24_S3_ACCESS_KEY", ""),
        aws_secret_access_key=os.environ.get("DFL24_S3_SECRET_KEY", ""),
        region_name=os.environ.get("DFL24_S3_REGION", "us-east-1"),
        # fail fast: a worker must not hang on a dead endpoint — numbers
        # matter more than figures (the job degrades to a warning instead)
        config=Config(
            signature_version="s3v4",
            connect_timeout=3,
            read_timeout=10,
            retries={"max_attempts": 2},
        ),
    )


def _ensure_bucket(client) -> None:
    from botocore.exceptions import ClientError

    try:
        client.head_bucket(Bucket=bucket_name())
    except ClientError:
        try:
            client.create_bucket(Bucket=bucket_name())
        except ClientError as exc:
            # a concurrent upload may win the create race; that's success
            code = exc.response.get("Error", {}).get("Code", "")
            if code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                raise


def upload(job_id: str, name: str, data: bytes, content_type: str) -> dict:
    """Store one artifact; returns the metadata row kept in the job record."""
    client = _client()
    _ensure_bucket(client)
    key = artifact_key(job_id, name)
    client.put_object(
        Bucket=bucket_name(), Key=key, Body=data, ContentType=content_type
    )
    return {
        "name": name,
        "key": key,
        "bucket": bucket_name(),
        "size_bytes": len(data),
        "content_type": content_type,
    }


def presign(key: str, expires_in: int = 900, bucket: str | None = None) -> str:
    """Time-limited GET URL for one stored artifact.

    Signed against DFL24_S3_PUBLIC_ENDPOINT when set: SigV4 binds the host,
    and the URL must work from the analyst's browser, not the compose network.
    Pass the bucket recorded at upload time so links to old artifacts survive
    a DFL24_S3_BUCKET change; it defaults to the current setting.
    """
    public = os.environ.get("DFL24_S3_PUBLIC_ENDPOINT")
    return _client(endpoint=public).generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket or bucket_name(), "Key": key},
        ExpiresIn=expires_in,
    )
