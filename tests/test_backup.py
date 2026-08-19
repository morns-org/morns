from __future__ import annotations

import json
import os
import sqlite3
import zipfile
from pathlib import Path

import pytest

from morns.backup import (
    ARCHIVE_VERSION,
    DATABASE_SCHEMA_VERSION,
    SQLITE_APPLICATION_ID,
    BackupError,
    BackupService,
)
from morns import backup_cli
from morns.store import ObservationStore


def populated_store(path: Path, *, node: str = "!source") -> ObservationStore:
    store = ObservationStore(path)
    store.save_setup({
        "station_name": "Test Station",
        "location_policy": "approximate",
        "latitude": 35.4,
        "longitude": -97.5,
        "radius_km": 8,
        "server_timezone": "America/Chicago",
        "api_key": "do-not-export-api-key",
        "nested": {"password": "do-not-export-password"},
    })
    # Remove an intentionally unsupported non-secret field so the fixture mirrors
    # configuration that the application itself accepts today.
    with store.connect() as db:
        setup = json.loads(db.execute("SELECT setup_json FROM receiver_setup").fetchone()[0])
        setup.pop("nested")
        db.execute(
            "UPDATE receiver_setup SET setup_json=? WHERE id=1",
            (json.dumps(setup),),
        )
    store.save_local_collector_credential("do-not-export-token-hash", "prefix")
    store.add({
        "receiver_id": "base",
        "from_node": node,
        "portnum": "POSITION_APP",
        "latitude": 35.5,
        "longitude": -97.6,
        "rssi": -103,
        "snr": 2.5,
        "transport": "LORA",
        "raw": {"from": node, "decoded": {"portnum": "POSITION_APP"}, "token": "raw-secret"},
    })
    return store


def rewrite_archive(source: Path, target: Path, transform) -> None:
    with zipfile.ZipFile(source) as incoming, zipfile.ZipFile(
        target, "w", compression=zipfile.ZIP_DEFLATED
    ) as outgoing:
        for info in incoming.infolist():
            outgoing.writestr(info.filename, transform(info.filename, incoming.read(info)))


def test_backup_round_trip_manifest_secret_exclusion_and_credential_preservation(tmp_path: Path):
    database = tmp_path / "morns.db"
    store = populated_store(database)
    service = BackupService(database, "0.1.0")
    archive = tmp_path / "station.morns-backup"

    manifest = service.create_archive(archive)
    inspected = service.inspect_archive(archive)

    assert inspected == manifest
    assert manifest["archive_version"] == ARCHIVE_VERSION
    assert manifest["database_schema_version"] == DATABASE_SCHEMA_VERSION
    assert manifest["counts"]["observations"] == 1
    assert manifest["files"]["station.db"]["sha256"]
    assert archive.stat().st_mode & 0o777 == 0o600
    with zipfile.ZipFile(archive) as backup:
        payload = b"".join(backup.read(name) for name in backup.namelist())
        extracted_db = tmp_path / "portable.db"
        extracted_db.write_bytes(backup.read("station.db"))
    assert b"do-not-export" not in payload
    assert b"raw-secret" not in payload
    with sqlite3.connect(extracted_db) as db:
        assert db.execute("PRAGMA application_id").fetchone()[0] == SQLITE_APPLICATION_ID
        assert db.execute("PRAGMA user_version").fetchone()[0] == DATABASE_SCHEMA_VERSION
        assert db.execute("SELECT COUNT(*) FROM local_collector_credentials").fetchone()[0] == 0

    original_credential = store.local_collector_credential()
    with store.connect() as db:
        db.execute("DELETE FROM observations")
    store.save_setup({"station_name": "Changed", "radius_km": 1})
    result = service.restore_archive(archive)

    restored = ObservationStore(database)
    assert restored.recent(minutes=0)[0]["from_node"] == "!source"
    assert restored.get_setup()["station_name"] == "Test Station"
    assert restored.local_collector_credential() == original_credential
    snapshot = Path(result["pre_restore_snapshot"])
    assert snapshot.is_file()
    assert snapshot.stat().st_mode & 0o777 == 0o600


def test_corrupted_file_checksum_is_rejected_without_touching_database(tmp_path: Path):
    database = tmp_path / "morns.db"
    store = populated_store(database)
    service = BackupService(database, "0.1.0")
    good = tmp_path / "good.morns-backup"
    bad = tmp_path / "bad.morns-backup"
    service.create_archive(good)
    rewrite_archive(good, bad, lambda name, data: data + b"damage" if name == "station.db" else data)

    with pytest.raises(BackupError, match="checksum"):
        service.restore_archive(bad)
    assert store.recent(minutes=0)[0]["from_node"] == "!source"
    assert not (tmp_path / "backups").exists()


def test_incompatible_archive_version_is_rejected(tmp_path: Path):
    database = tmp_path / "morns.db"
    populated_store(database)
    service = BackupService(database, "0.1.0")
    good = tmp_path / "good.morns-backup"
    bad = tmp_path / "future.morns-backup"
    service.create_archive(good)

    def future_manifest(name: str, data: bytes) -> bytes:
        if name != "manifest.json":
            return data
        manifest = json.loads(data)
        manifest["archive_version"] = ARCHIVE_VERSION + 1
        return json.dumps(manifest).encode()

    rewrite_archive(good, bad, future_manifest)
    with pytest.raises(BackupError, match="version is incompatible"):
        service.inspect_archive(bad)


def test_database_application_id_is_required(tmp_path: Path):
    database = tmp_path / "morns.db"
    populated_store(database)
    service = BackupService(database, "0.1.0")
    good = tmp_path / "good.morns-backup"
    bad = tmp_path / "wrong-app.morns-backup"
    service.create_archive(good)
    extracted = tmp_path / "station.db"
    with zipfile.ZipFile(good) as archive:
        extracted.write_bytes(archive.read("station.db"))
        config = archive.read("station-config.json")
        manifest = json.loads(archive.read("manifest.json"))
    with sqlite3.connect(extracted) as db:
        db.execute("PRAGMA application_id=0")
    db_bytes = extracted.read_bytes()
    import hashlib
    manifest["files"]["station.db"] = {
        "bytes": len(db_bytes), "sha256": hashlib.sha256(db_bytes).hexdigest()
    }
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("station.db", db_bytes)
        archive.writestr("station-config.json", config)
    with pytest.raises(BackupError, match="application identifier"):
        service.inspect_archive(bad)


def test_unexpected_and_traversal_archive_members_are_rejected(tmp_path: Path):
    database = tmp_path / "morns.db"
    populated_store(database)
    service = BackupService(database, "0.1.0")
    good = tmp_path / "good.morns-backup"
    bad = tmp_path / "traversal.morns-backup"
    service.create_archive(good)
    with zipfile.ZipFile(good) as incoming, zipfile.ZipFile(bad, "w") as outgoing:
        for name in incoming.namelist():
            outgoing.writestr(name, incoming.read(name))
        outgoing.writestr("../escaped", "unsafe")
    with pytest.raises(BackupError, match="unexpected"):
        service.inspect_archive(bad)
    assert not (tmp_path.parent / "escaped").exists()


def test_post_replace_failure_rolls_back_database_and_credentials(tmp_path: Path):
    database = tmp_path / "morns.db"
    populated_store(database, node="!archive")
    service = BackupService(database, "0.1.0")
    archive = tmp_path / "station.morns-backup"
    service.create_archive(archive)

    current = ObservationStore(database)
    with current.connect() as db:
        db.execute("DELETE FROM observations")
    current.add({"receiver_id": "base", "from_node": "!current", "transport": "LORA", "raw": {}})
    current.save_setup({"station_name": "Current", "radius_km": 9})
    current.save_local_collector_credential("current-token-hash", "current")

    def fail_after_replace(_database: Path) -> None:
        raise RuntimeError("simulated post-replace failure")

    with pytest.raises(RuntimeError, match="simulated"):
        service.restore_archive(archive, post_replace_check=fail_after_replace)
    rolled_back = ObservationStore(database)
    assert rolled_back.recent(minutes=0)[0]["from_node"] == "!current"
    assert rolled_back.get_setup()["station_name"] == "Current"
    assert rolled_back.local_collector_credential()["token_hash"] == "current-token-hash"
    assert list((tmp_path / "backups").glob("pre-restore-*.db"))


def test_malformed_archive_is_rejected(tmp_path: Path):
    database = tmp_path / "morns.db"
    populated_store(database)
    bad = tmp_path / "bad.morns-backup"
    bad.write_bytes(b"not a zip archive")
    with pytest.raises(BackupError, match="valid ZIP"):
        BackupService(database, "0.1.0").inspect_archive(bad)


def test_oversized_archive_is_rejected_before_parsing(tmp_path: Path, monkeypatch):
    database = tmp_path / "morns.db"
    populated_store(database)
    bad = tmp_path / "large.morns-backup"
    bad.write_bytes(b"x" * 65)
    monkeypatch.setattr("morns.backup.MAX_ARCHIVE_BYTES", 64)
    with pytest.raises(BackupError, match="maximum accepted size"):
        BackupService(database, "0.1.0").inspect_archive(bad)


def test_backup_refuses_to_overwrite_live_database(tmp_path: Path):
    database = tmp_path / "morns.db"
    populated_store(database)
    with pytest.raises(BackupError, match="cannot replace"):
        BackupService(database, "0.1.0").create_archive(database)
    assert ObservationStore(database).recent(minutes=0)


def test_cli_restore_requires_explicit_offline_confirmation(
    tmp_path: Path, monkeypatch, capsys
):
    database = tmp_path / "morns.db"
    populated_store(database)
    archive = tmp_path / "station.morns-backup"
    BackupService(database, "0.1.0").create_archive(archive)
    monkeypatch.setattr(
        "sys.argv",
        ["morns-backup", "--database", str(database), "restore", str(archive)],
    )
    with pytest.raises(SystemExit) as stopped:
        backup_cli.main()
    assert stopped.value.code == 2
    assert "offline-only" in capsys.readouterr().err
