from app.core.settings import Settings
from app.memory.long_term import SqliteMemoryStore, get_memory_store


def test_write_and_query_fact_roundtrip(tmp_path) -> None:
    store = SqliteMemoryStore(str(tmp_path / "memory.sqlite"))
    store.write_fact(
        scope_key="member_id",
        scope_value="MEM1001",
        fact_type="decision",
        fact_json={"status": "APPROVE"},
        source_run_id="run-1",
        ttl_days=90,
    )
    facts = store.query_facts("member_id", "MEM1001", fact_type="decision")
    assert len(facts) == 1
    assert facts[0]["fact"]["status"] == "APPROVE"
    assert facts[0]["source_run_id"] == "run-1"


def test_query_facts_scoped_to_matching_value_only(tmp_path) -> None:
    store = SqliteMemoryStore(str(tmp_path / "memory.sqlite"))
    store.write_fact("member_id", "MEM1001", "decision", {"a": 1}, "run-1", 90)
    store.write_fact("member_id", "MEM9999", "decision", {"a": 2}, "run-2", 90)
    facts = store.query_facts("member_id", "MEM1001")
    assert len(facts) == 1


def test_expired_fact_is_not_returned(tmp_path) -> None:
    store = SqliteMemoryStore(str(tmp_path / "memory.sqlite"))
    store.write_fact("member_id", "MEM1001", "decision", {"a": 1}, "run-1", ttl_days=-1)
    assert store.query_facts("member_id", "MEM1001") == []


def test_get_memory_store_returns_sqlite_locally(tmp_path) -> None:
    settings = Settings(sqlite_path=str(tmp_path / "checkpoints.sqlite"))
    store = get_memory_store(settings)
    assert isinstance(store, SqliteMemoryStore)
