from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .store import ObservationStore

ARCHIVE_FORMAT = "morns-station-backup"
ARCHIVE_VERSION = 1
DATABASE_SCHEMA_VERSION = 1
SQLITE_APPLICATION_ID = 0x4D4F524E  # "MORN"
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_EXTRACTED_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
EXPECTED_MEMBERS = {"manifest.json", "station.db", "station-config.json"}
PORTABLE_TABLES = (
    "observations",
    "archived_base_station_telemetry",
    "node_mobility_state",
    "node_mobility_transitions",
)
SECRET_TABLES = ("local_collector_credentials",)
SECRET_KEY_PARTS = (
    "api_key", "apikey", "credential", "password", "private_key", "secret",
    "session", "token",
)
PORTABLE_CONFIG_KEYS = {
    "station_name", "location_policy", "location_method", "country_code",
    "postal_code", "location_accuracy_m", "latitude", "longitude", "radius_km",
    "server_timezone", "observation_retention_days", "message_retention_days",
    "base_station_telemetry_archive_days", "map_windows_minutes", "updated_at",
}


class BackupError(ValueError):
    """A backup archive is unsafe, incompatible, or invalid."""


class BackupService:
    """Create and atomically restore portable, secret-free station archives."""

    def __init__(self, database_path: Path | str, app_version: str):
        self.database_path = Path(database_path)
        self.app_version = app_version

    def capabilities(self) -> dict[str, Any]:
        return {
            "format": ARCHIVE_FORMAT,
            "archive_version": ARCHIVE_VERSION,
            "database_schema_version": DATABASE_SCHEMA_VERSION,
            "admin_auth_available": False,
            "access_mode": "local_cli_only",
            "web_transfer_available": False,
            "max_archive_bytes": MAX_ARCHIVE_BYTES,
            "secrets_included": False,
        }

    def create_archive(self, destination: Path | str) -> dict[str, Any]:
        destination = Path(destination)
        if destination.resolve(strict=False) == self.database_path.resolve(strict=False):
            raise BackupError("Backup destination cannot replace the station database")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="morns-backup-") as work:
            workdir = Path(work)
            snapshot = workdir / "source-snapshot.db"
            portable = workdir / "station.db"
            config_file = workdir / "station-config.json"
            self._sqlite_snapshot(self.database_path, snapshot)
            counts = self._create_portable_database(snapshot, portable)
            config = _sanitize_config(ObservationStore(snapshot).get_setup() or {})
            _validate_config(config)
            config_file.write_text(
                json.dumps(config, sort_keys=True, separators=(",", ":")), encoding="utf-8"
            )
            files = {
                name: _file_metadata(path)
                for name, path in (("station.db", portable), ("station-config.json", config_file))
            }
            manifest = {
                "format": ARCHIVE_FORMAT,
                "archive_version": ARCHIVE_VERSION,
                "database_schema_version": DATABASE_SCHEMA_VERSION,
                "app_version": self.app_version,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "counts": counts,
                "files": files,
                "secret_policy": {
                    "included": False,
                    "excluded": [
                        "collector credentials", "API keys", "sessions", "private keys",
                        "passwords", "transient caches",
                    ],
                    "restore_behavior": "destination-local credentials are preserved",
                },
            }
            manifest_file = workdir / "manifest.json"
            manifest_file.write_text(
                json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8"
            )
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{destination.name}.tmp-", dir=destination.parent
            )
            os.close(descriptor)
            temporary = Path(temporary_name)
            try:
                with zipfile.ZipFile(
                    temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
                ) as archive:
                    for name in ("manifest.json", "station.db", "station-config.json"):
                        archive.write(workdir / name, arcname=name)
                if temporary.stat().st_size > MAX_ARCHIVE_BYTES:
                    raise BackupError("Created backup exceeds the maximum archive size")
                os.chmod(temporary, 0o600)
                _fsync_file(temporary)
                os.replace(temporary, destination)
                _fsync_directory(destination.parent)
            finally:
                temporary.unlink(missing_ok=True)
        return manifest

    def inspect_archive(self, archive_path: Path | str) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="morns-validate-") as work:
            return self._extract_and_validate(Path(archive_path), Path(work))[0]

    def restore_archive(
        self,
        archive_path: Path | str,
        *,
        post_replace_check: Callable[[Path], None] | None = None,
    ) -> dict[str, Any]:
        """Restore atomically; the caller must first stop all station writers."""
        archive_path = Path(archive_path)
        with tempfile.TemporaryDirectory(
            prefix="morns-restore-", dir=self.database_path.parent
        ) as work:
            workdir = Path(work)
            manifest, extracted = self._extract_and_validate(archive_path, workdir)
            current_stat = self.database_path.stat()
            current_credential = ObservationStore(self.database_path).local_collector_credential()
            snapshot_dir = self.database_path.parent / "backups"
            snapshot_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(snapshot_dir, 0o700)
            snapshot_name = datetime.now(timezone.utc).strftime("pre-restore-%Y%m%dT%H%M%S.%fZ.db")
            pre_restore_snapshot = snapshot_dir / snapshot_name
            descriptor = os.open(
                pre_restore_snapshot,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            os.close(descriptor)
            self._sqlite_snapshot(self.database_path, pre_restore_snapshot)
            os.chmod(pre_restore_snapshot, 0o600)

            candidate = workdir / "restore-candidate.db"
            shutil.copyfile(extracted["station.db"], candidate)
            candidate_store = ObservationStore(candidate)
            config = json.loads(extracted["station-config.json"].read_text(encoding="utf-8"))
            if config:
                candidate_store.save_setup(config)
            if current_credential:
                self._preserve_local_credential(candidate, current_credential)
            self._validate_installed_database(candidate, allow_local_credential=True)
            os.chmod(candidate, stat.S_IMODE(current_stat.st_mode))
            _preserve_owner(candidate, current_stat.st_uid, current_stat.st_gid)
            _fsync_file(candidate)

            rollback_copy = workdir / "rollback.db"
            try:
                os.replace(candidate, self.database_path)
                _fsync_directory(self.database_path.parent)
                self._validate_installed_database(
                    self.database_path, allow_local_credential=True
                )
                if post_replace_check:
                    post_replace_check(self.database_path)
            except Exception:
                shutil.copyfile(pre_restore_snapshot, rollback_copy)
                os.chmod(rollback_copy, stat.S_IMODE(current_stat.st_mode))
                _preserve_owner(rollback_copy, current_stat.st_uid, current_stat.st_gid)
                _fsync_file(rollback_copy)
                os.replace(rollback_copy, self.database_path)
                _fsync_directory(self.database_path.parent)
                raise
        return {
            "status": "restored",
            "manifest": manifest,
            "pre_restore_snapshot": str(pre_restore_snapshot),
            "local_credentials_preserved": bool(current_credential),
        }

    @staticmethod
    def _sqlite_snapshot(source: Path, destination: Path) -> None:
        if not source.is_file():
            raise BackupError("Station database does not exist")
        with sqlite3.connect(source) as source_db, sqlite3.connect(destination) as target_db:
            source_db.backup(target_db)
        _fsync_file(destination)

    @staticmethod
    def _create_portable_database(source: Path, destination: Path) -> dict[str, int]:
        destination_store = ObservationStore(destination)
        del destination_store
        counts: dict[str, int] = {}
        with sqlite3.connect(source) as source_db, sqlite3.connect(destination) as target_db:
            source_db.row_factory = sqlite3.Row
            available = {
                row[0] for row in source_db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            for table in PORTABLE_TABLES:
                if table not in available:
                    counts[table] = 0
                    continue
                source_columns = [
                    row[1] for row in source_db.execute(f'PRAGMA table_info("{table}")')
                ]
                target_columns = {
                    row[1] for row in target_db.execute(f'PRAGMA table_info("{table}")')
                }
                columns = [column for column in source_columns if column in target_columns]
                if not columns:
                    raise BackupError(f"Portable table has no compatible columns: {table}")
                names = ",".join(f'"{column}"' for column in columns)
                placeholders = ",".join("?" for _ in columns)
                cursor = source_db.execute(f'SELECT {names} FROM "{table}"')
                total = 0
                while rows := cursor.fetchmany(1000):
                    target_db.executemany(
                        f'INSERT INTO "{table}" ({names}) VALUES ({placeholders})',
                        (_portable_row(row, columns) for row in rows),
                    )
                    total += len(rows)
                counts[table] = total
            for table in SECRET_TABLES:
                target_db.execute(f'DELETE FROM "{table}"')
            target_db.execute(f"PRAGMA application_id = {SQLITE_APPLICATION_ID}")
            target_db.execute(f"PRAGMA user_version = {DATABASE_SCHEMA_VERSION}")
            target_db.commit()
        BackupService._validate_installed_database(destination)
        return counts

    def _extract_and_validate(
        self, archive_path: Path, destination: Path
    ) -> tuple[dict[str, Any], dict[str, Path]]:
        if not archive_path.is_file():
            raise BackupError("Backup archive does not exist")
        if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise BackupError("Backup archive exceeds the maximum accepted size")
        try:
            archive = zipfile.ZipFile(archive_path)
        except (OSError, zipfile.BadZipFile) as exc:
            raise BackupError("Backup archive is not a valid ZIP file") from exc
        extracted: dict[str, Path] = {}
        try:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or set(names) != EXPECTED_MEMBERS:
                raise BackupError("Backup archive contains missing, duplicate, or unexpected files")
            if sum(info.file_size for info in infos) > MAX_EXTRACTED_BYTES:
                raise BackupError("Expanded backup exceeds the maximum accepted size")
            for info in infos:
                if info.filename not in EXPECTED_MEMBERS or Path(info.filename).name != info.filename:
                    raise BackupError("Unsafe archive path")
                if info.is_dir() or info.flag_bits & 0x1 or _is_symlink(info):
                    raise BackupError("Directories, encrypted entries, and links are not accepted")
                limit = MAX_MANIFEST_BYTES if info.filename.endswith(".json") else MAX_EXTRACTED_BYTES
                if info.file_size > limit:
                    raise BackupError(f"Archive member is too large: {info.filename}")
                output = destination / info.filename
                digest = hashlib.sha256()
                written = 0
                with archive.open(info) as source, output.open("wb") as target:
                    while chunk := source.read(1024 * 1024):
                        written += len(chunk)
                        if written > limit:
                            raise BackupError(f"Archive member expanded beyond its limit: {info.filename}")
                        digest.update(chunk)
                        target.write(chunk)
                extracted[info.filename] = output
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            if isinstance(exc, BackupError):
                raise
            raise BackupError("Backup archive could not be safely extracted") from exc
        finally:
            archive.close()

        try:
            manifest = json.loads(extracted["manifest.json"].read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
            raise BackupError("Backup manifest is malformed") from exc
        self._validate_manifest(manifest, extracted)
        self._validate_installed_database(extracted["station.db"])
        self._validate_counts(extracted["station.db"], manifest["counts"])
        try:
            config = json.loads(extracted["station-config.json"].read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
            raise BackupError("Station configuration is malformed") from exc
        _validate_config(config)
        return manifest, extracted

    def _validate_manifest(self, manifest: Any, extracted: dict[str, Path]) -> None:
        if not isinstance(manifest, dict) or manifest.get("format") != ARCHIVE_FORMAT:
            raise BackupError("Backup manifest format is invalid")
        if manifest.get("archive_version") != ARCHIVE_VERSION:
            raise BackupError("Backup archive version is incompatible")
        if manifest.get("database_schema_version") != DATABASE_SCHEMA_VERSION:
            raise BackupError("Backup database schema version is incompatible")
        if not isinstance(manifest.get("created_at"), str) or not isinstance(
            manifest.get("app_version"), str
        ):
            raise BackupError("Backup manifest metadata is incomplete")
        try:
            datetime.fromisoformat(manifest["created_at"])
        except ValueError as exc:
            raise BackupError("Backup creation time is invalid") from exc
        secret_policy = manifest.get("secret_policy")
        if not isinstance(secret_policy, dict) or secret_policy.get("included") is not False:
            raise BackupError("Backup secret policy is invalid")
        if not isinstance(manifest.get("counts"), dict) or not isinstance(
            manifest.get("files"), dict
        ):
            raise BackupError("Backup manifest inventory is invalid")
        if set(manifest["files"]) != {"station.db", "station-config.json"}:
            raise BackupError("Backup manifest file inventory is invalid")
        for name, expected in manifest["files"].items():
            if not isinstance(expected, dict):
                raise BackupError("Backup checksum metadata is invalid")
            actual = _file_metadata(extracted[name])
            if (
                not isinstance(expected.get("bytes"), int)
                or isinstance(expected.get("bytes"), bool)
                or expected.get("sha256") != actual["sha256"]
                or expected.get("bytes") != actual["bytes"]
            ):
                raise BackupError(f"Backup checksum failed: {name}")

    @staticmethod
    def _validate_counts(database: Path, expected: dict[str, Any]) -> None:
        if set(expected) != set(PORTABLE_TABLES) or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in expected.values()
        ):
            raise BackupError("Backup row-count inventory is invalid")
        with sqlite3.connect(database) as db:
            for table, count in expected.items():
                actual = db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                if actual != count:
                    raise BackupError(f"Backup row count failed: {table}")

    @staticmethod
    def _validate_installed_database(
        database: Path, allow_local_credential: bool = False
    ) -> None:
        try:
            with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as db:
                db.execute("PRAGMA trusted_schema = OFF")
                db.execute("PRAGMA query_only = ON")
                if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise BackupError("Backup database integrity check failed")
                if db.execute("PRAGMA application_id").fetchone()[0] != SQLITE_APPLICATION_ID:
                    raise BackupError("Backup database application identifier is incompatible")
                if db.execute("PRAGMA user_version").fetchone()[0] != DATABASE_SCHEMA_VERSION:
                    raise BackupError("Backup database user version is incompatible")
                tables = {
                    row[0] for row in db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                required = set(PORTABLE_TABLES) | {"receiver_setup", "local_collector_credentials"}
                if tables - {"sqlite_sequence"} != required:
                    raise BackupError("Backup database schema is incomplete or contains unexpected tables")
                unsafe_objects = db.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type IN ('trigger', 'view')"
                ).fetchone()[0]
                if unsafe_objects:
                    raise BackupError("Backup database contains unsupported executable schema objects")
                if (
                    not allow_local_credential
                    and db.execute("SELECT COUNT(*) FROM local_collector_credentials").fetchone()[0]
                ):
                    raise BackupError("Portable backup contains local credentials")
        except sqlite3.DatabaseError as exc:
            raise BackupError("Backup database is malformed") from exc

    @staticmethod
    def _preserve_local_credential(database: Path, credential: dict[str, Any]) -> None:
        with sqlite3.connect(database) as db:
            db.execute(
                """INSERT OR REPLACE INTO local_collector_credentials
                (id, token_hash, token_prefix, created_at, last_used_at)
                VALUES (1, ?, ?, ?, ?)""",
                (
                    credential["token_hash"], credential["token_prefix"],
                    credential["created_at"], credential["last_used_at"],
                ),
            )


def _sanitize_config(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize_config(item)
            for key, item in value.items()
            if not any(part in key.lower().replace("-", "_") for part in SECRET_KEY_PARTS)
        }
    if isinstance(value, list):
        return [_sanitize_config(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise BackupError("Station configuration contains an unsupported value")


def _validate_config(config: Any) -> None:
    if not isinstance(config, dict) or config != _sanitize_config(config):
        raise BackupError("Station configuration contains a secret or unsupported structure")
    if set(config) - PORTABLE_CONFIG_KEYS:
        raise BackupError("Station configuration contains unsupported fields")


def _portable_row(row: sqlite3.Row, columns: list[str]) -> tuple[Any, ...]:
    values: list[Any] = []
    for column in columns:
        value = row[column]
        if column.endswith("_json") and isinstance(value, str):
            try:
                decoded = json.loads(value)
            except (TypeError, ValueError) as exc:
                raise BackupError(f"Stored JSON is malformed in {column}") from exc
            value = json.dumps(_sanitize_config(decoded), separators=(",", ":"), sort_keys=True)
        values.append(value)
    return tuple(values)


def _file_metadata(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF)


def _fsync_file(path: Path) -> None:
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _preserve_owner(path: Path, uid: int, gid: int) -> None:
    current = path.stat()
    if current.st_uid == uid and current.st_gid == gid:
        return
    try:
        os.chown(path, uid, gid)
    except PermissionError as exc:
        raise BackupError("Cannot preserve database ownership during restore") from exc
