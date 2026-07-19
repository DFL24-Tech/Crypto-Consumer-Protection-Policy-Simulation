#!/usr/bin/env sh
# Back up Postgres (the job store) and MinIO (artifacts) for the prod stack.
#
# Run from the repository root, typically via cron on the VPS host:
#   0 3 * * *  cd /srv/dfl24sim && deploy/backup.sh >> /var/log/dfl24-backup.log 2>&1
#
# Writes to $BACKUP_DIR (default ./backups):
#   pg-<UTC timestamp>.sql.gz   — a compressed logical dump, one file per run
#   minio/<bucket>/...          — a mirror of the artifact bucket
# Postgres dumps older than $BACKUP_KEEP_DAYS (default 14) are pruned. The
# MinIO mirror never deletes, so it only ever accumulates artifacts.
set -eu

cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

ENV_FILE="${ENV_FILE:-.env.prod}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
BACKUP_KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"

compose() {
	docker compose -f docker-compose.yml -f docker-compose.prod.yml \
		--env-file "$ENV_FILE" "$@"
}

mkdir -p "$BACKUP_DIR/minio"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
dump="$BACKUP_DIR/pg-$timestamp.sql.gz"

echo "[backup] $timestamp postgres -> $dump"
# -T: no TTY, so the gzip stream reaches the redirect unmangled
if ! compose --profile backup run --rm -T pg-backup > "$dump"; then
	echo "[backup] ERROR: pg-backup failed; removing $dump" >&2
	rm -f "$dump"
	exit 1
fi
# Validate before trusting it: non-empty, valid gzip, and — the case a bare
# gzip check misses — ending in pg_dump's completion footer, so a dump
# truncated mid-stream (which can still be valid gzip) is rejected.
if [ ! -s "$dump" ] || ! gzip -t "$dump" 2>/dev/null || \
	! gzip -dc "$dump" | tail -c 512 | grep -q 'PostgreSQL database dump complete'; then
	echo "[backup] ERROR: postgres dump is empty, corrupt, or incomplete; removing $dump" >&2
	rm -f "$dump"
	exit 1
fi

echo "[backup] mirroring MinIO bucket -> $BACKUP_DIR/minio"
compose --profile backup run --rm minio-backup

echo "[backup] pruning postgres dumps older than $BACKUP_KEEP_DAYS days"
find "$BACKUP_DIR" -maxdepth 1 -name 'pg-*.sql.gz' -mtime +"$BACKUP_KEEP_DAYS" -delete

echo "[backup] done: $(ls -1 "$BACKUP_DIR"/pg-*.sql.gz 2>/dev/null | wc -l) dump(s) retained"
