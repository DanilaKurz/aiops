from app.adapters.openrca import OpenRCAAdapter


def test_load_logs(sample_openrca_dir):
    adapter = OpenRCAAdapter(sample_openrca_dir)
    logs = adapter.load_logs("Bank", "2024_01_15")
    assert len(logs) == 3
    assert logs[0].service == "gateway"
    assert "Connection timeout" in logs[0].message


def test_load_logs_by_service(sample_openrca_dir):
    adapter = OpenRCAAdapter(sample_openrca_dir)
    logs = adapter.load_logs("Bank", "2024_01_15", service="gateway")
    assert len(logs) == 3


def test_load_metrics(sample_openrca_dir):
    adapter = OpenRCAAdapter(sample_openrca_dir)
    result = adapter.load_metrics("Bank", "2024_01_15", service="gateway")
    assert "anomalies" in result
    assert "normal_metrics" in result
    assert isinstance(result["anomalies"], list)


def test_load_traces(sample_openrca_dir):
    adapter = OpenRCAAdapter(sample_openrca_dir)
    result = adapter.load_traces("Bank", "2024_01_15")
    assert "critical_path" in result
    assert result["bottleneck"] == "db-master"


def test_load_topology(sample_openrca_dir):
    adapter = OpenRCAAdapter(sample_openrca_dir)
    topo = adapter.load_topology("Bank")
    assert "nodes" in topo
    assert "edges" in topo


def test_load_ground_truth(sample_openrca_dir):
    adapter = OpenRCAAdapter(sample_openrca_dir)
    gt = adapter.load_ground_truth("Bank", "2024_01_15")
    assert gt["component"] == "db-master"
