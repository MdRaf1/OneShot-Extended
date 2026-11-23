import time

from src.session import SessionStore, migrate_legacy_run_files


def test_upsert_and_get_target(tmp_path):
    store = SessionStore(tmp_path / "s.sqlite3")
    store.upsert_target("AA:BB:CC:DD:EE:FF", essid="home")
    t = store.get_target("AA:BB:CC:DD:EE:FF")
    assert t.essid == "home" and t.state == "pending"


def test_set_state_and_list_targets(tmp_path):
    store = SessionStore(tmp_path / "s.sqlite3")
    store.upsert_target("AA:BB:CC:DD:EE:FF")
    store.set_state("AA:BB:CC:DD:EE:FF", "running")
    assert store.list_targets()[0].state == "running"


def test_mark_cracked_sets_pin_and_psk(tmp_path):
    store = SessionStore(tmp_path / "s.sqlite3")
    store.upsert_target("AA:BB:CC:DD:EE:FF")
    store.mark_cracked("AA:BB:CC:DD:EE:FF", "12345670", "secretpsk")
    t = store.get_target("AA:BB:CC:DD:EE:FF")
    assert t.state == "cracked" and t.wps_pin == "12345670" and t.wpa_psk == "secretpsk"


def test_mark_failed_sets_state(tmp_path):
    store = SessionStore(tmp_path / "s.sqlite3")
    store.upsert_target("AA:BB:CC:DD:EE:FF")
    store.mark_failed("AA:BB:CC:DD:EE:FF")
    assert store.get_target("AA:BB:CC:DD:EE:FF").state == "failed"


def test_get_target_returns_none_for_unknown_bssid(tmp_path):
    store = SessionStore(tmp_path / "s.sqlite3")
    assert store.get_target("AA:BB:CC:DD:EE:FF") is None


def test_set_last_chain_step(tmp_path):
    store = SessionStore(tmp_path / "s.sqlite3")
    store.upsert_target("AA:BB:CC:DD:EE:FF")
    store.set_last_chain_step("AA:BB:CC:DD:EE:FF", "PIXIE_DUST")
    assert store.get_target("AA:BB:CC:DD:EE:FF").last_chain_step == "PIXIE_DUST"


def test_upsert_target_is_idempotent_and_preserves_existing_state(tmp_path):
    store = SessionStore(tmp_path / "s.sqlite3")
    store.upsert_target("AA:BB:CC:DD:EE:FF", essid="home")
    store.set_state("AA:BB:CC:DD:EE:FF", "running")
    store.upsert_target("AA:BB:CC:DD:EE:FF", essid="home")  # re-upsert
    assert store.get_target("AA:BB:CC:DD:EE:FF").state == "running"


def test_writes_are_durable_across_reopen(tmp_path):
    db = tmp_path / "s.sqlite3"
    store1 = SessionStore(db)
    store1.upsert_target("AA:BB:CC:DD:EE:FF")
    store1.update_bruteforce_mask("AA:BB:CC:DD:EE:FF", "1234567")
    del store1  # no explicit close/flush — simulates a hard kill right after the call returns
    store2 = SessionStore(db)
    assert store2.get_bruteforce_mask("AA:BB:CC:DD:EE:FF") == "1234567"


def test_cooldown_not_expired_immediately_after_set(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "s.sqlite3")
    store.upsert_target("AA:BB:CC:DD:EE:FF")
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    store.set_cooldown("AA:BB:CC:DD:EE:FF", seconds_from_now=60)
    assert store.is_cooldown_expired("AA:BB:CC:DD:EE:FF", now=1010.0) is False


def test_cooldown_expired_after_elapsed(tmp_path):
    store = SessionStore(tmp_path / "s.sqlite3")
    store.upsert_target("AA:BB:CC:DD:EE:FF")
    store.set_cooldown("AA:BB:CC:DD:EE:FF", seconds_from_now=60)
    future = time.time() + 61
    assert store.is_cooldown_expired("AA:BB:CC:DD:EE:FF", now=future) is True


def test_no_cooldown_set_means_not_blocked(tmp_path):
    store = SessionStore(tmp_path / "s.sqlite3")
    store.upsert_target("AA:BB:CC:DD:EE:FF")
    assert store.is_cooldown_expired("AA:BB:CC:DD:EE:FF") is True


def test_two_connections_write_different_bssids_without_corruption(tmp_path):
    db = tmp_path / "s.sqlite3"
    a, b = SessionStore(db), SessionStore(db)
    a.upsert_target("AA:AA:AA:AA:AA:AA")
    b.upsert_target("BB:BB:BB:BB:BB:BB")
    a.update_bruteforce_mask("AA:AA:AA:AA:AA:AA", "1111111")
    b.update_bruteforce_mask("BB:BB:BB:BB:BB:BB", "2222222")
    c = SessionStore(db)
    assert c.get_bruteforce_mask("AA:AA:AA:AA:AA:AA") == "1111111"
    assert c.get_bruteforce_mask("BB:BB:BB:BB:BB:BB") == "2222222"


def test_concurrent_writers_from_threads_do_not_corrupt_or_raise(tmp_path):
    import threading  # pylint: disable=import-outside-toplevel

    db = tmp_path / "s.sqlite3"
    store = SessionStore(db)
    bssids = [f"AA:AA:AA:AA:AA:{i:02X}" for i in range(10)]
    for bssid in bssids:
        store.upsert_target(bssid)

    errors = []

    def writer(bssid, mask):
        try:
            s = SessionStore(db)
            for _ in range(5):
                s.update_bruteforce_mask(bssid, mask)
        except Exception as e:  # pylint: disable=broad-except
            errors.append(e)

    threads = [
        threading.Thread(target=writer, args=(bssid, f"{i:07d}"))
        for i, bssid in enumerate(bssids)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    final = SessionStore(db)
    for i, bssid in enumerate(bssids):
        assert final.get_bruteforce_mask(bssid) == f"{i:07d}"


def test_migrate_converts_valid_bruteforce_mask_file(tmp_path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "AABBCCDDEEFF.run").write_text("1234567")
    store = SessionStore(tmp_path / "s.sqlite3")
    migrate_legacy_run_files(store, str(sessions_dir), str(tmp_path / "pixiewps"))
    assert store.get_bruteforce_mask("AA:BB:CC:DD:EE:FF") == "1234567"
    assert (sessions_dir / "AABBCCDDEEFF.run.migrated").exists()
    assert not (sessions_dir / "AABBCCDDEEFF.run").exists()


def test_migrate_converts_valid_pixie_pin_file(tmp_path):
    pixiewps_dir = tmp_path / "pixiewps"
    pixiewps_dir.mkdir()
    (pixiewps_dir / "AABBCCDDEEFF.run").write_text("12345670")
    store = SessionStore(tmp_path / "s.sqlite3")
    migrate_legacy_run_files(store, str(tmp_path / "sessions"), str(pixiewps_dir))
    assert store.get_pixie_pin("AA:BB:CC:DD:EE:FF") == "12345670"
    assert (pixiewps_dir / "AABBCCDDEEFF.run.migrated").exists()


def test_migrate_skips_malformed_file_without_raising(tmp_path, caplog):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "BADFILE000000.run").write_bytes(b"\xff\xfe not utf8 \x00")
    store = SessionStore(tmp_path / "s.sqlite3")
    migrate_legacy_run_files(store, str(sessions_dir), str(tmp_path / "pixiewps"))  # must not raise
    assert store.get_target("BA:DF:IL:E0:00:00") is None
    assert caplog.records


def test_migrate_skips_empty_bruteforce_mask_file(tmp_path, caplog):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "AABBCCDDEEFF.run").write_text("")
    store = SessionStore(tmp_path / "s.sqlite3")
    migrate_legacy_run_files(store, str(sessions_dir), str(tmp_path / "pixiewps"))
    assert store.get_target("AA:BB:CC:DD:EE:FF") is None
    assert caplog.records


def test_migrate_skips_non_numeric_content(tmp_path, caplog):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "AABBCCDDEEFF.run").write_text("not-a-mask")
    store = SessionStore(tmp_path / "s.sqlite3")
    migrate_legacy_run_files(store, str(sessions_dir), str(tmp_path / "pixiewps"))
    assert store.get_target("AA:BB:CC:DD:EE:FF") is None
    assert caplog.records


def test_migrate_is_idempotent(tmp_path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "AABBCCDDEEFF.run").write_text("1234567")
    store = SessionStore(tmp_path / "s.sqlite3")
    migrate_legacy_run_files(store, str(sessions_dir), str(tmp_path / "pixiewps"))
    migrate_legacy_run_files(store, str(sessions_dir), str(tmp_path / "pixiewps"))  # no .run left; must not raise
    assert store.get_bruteforce_mask("AA:BB:CC:DD:EE:FF") == "1234567"


def test_migrate_handles_missing_directories_gracefully(tmp_path):
    store = SessionStore(tmp_path / "s.sqlite3")
    migrate_legacy_run_files(
        store, str(tmp_path / "nonexistent_sessions"), str(tmp_path / "nonexistent_pixiewps")
    )  # must not raise
