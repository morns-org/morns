from morns.collector import SerialCollector
from morns.store import ObservationStore


class _MyInfo:
    my_node_num = 1


class _Interface:
    myInfo = _MyInfo()


def test_serial_collector_uses_current_saved_station_location(tmp_path):
    store = ObservationStore(tmp_path / "collector.db")
    store.save_setup({"latitude": 35.5, "longitude": -97.5})
    collector = SerialCollector(store, "/dev/null", "base")
    collector._on_receive({
        "id": 7,
        "from": 2,
        "to": 1,
        "rxRssi": -110,
        "rxSnr": -3,
        "decoded": {"portnum": "TELEMETRY_APP"},
    }, _Interface())
    observation = store.recent(60)[0]
    assert observation["receiver_latitude"] == 35.5
    assert observation["receiver_longitude"] == -97.5
