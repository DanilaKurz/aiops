from app.adapters.openrca import OpenRCAAdapter


def test_load_logs(sample_openrca_dir):
    adapter = OpenRCAAdapter(sample_openrca_dir)
    logs = adapter.load_logs("Bank", "2021_03_04")
    assert len(logs) == 4
    assert logs[0].service == "Tomcat01"
    assert "GC" in logs[0].message or "CMS" in logs[0].message


def test_load_logs_by_service(sample_openrca_dir):
    adapter = OpenRCAAdapter(sample_openrca_dir)
    logs = adapter.load_logs("Bank", "2021_03_04", service="Tomcat01")
    assert all(l.service == "Tomcat01" for l in logs)


def test_load_logs_by_hour(sample_openrca_dir):
    adapter = OpenRCAAdapter(sample_openrca_dir)
    logs_h0 = adapter.load_logs("Bank", "2021_03_04", hour=0)
    logs_h1 = adapter.load_logs("Bank", "2021_03_04", hour=1)
    assert len(logs_h0) == 3  # first 3 logs are in hour 0
    assert len(logs_h1) == 1  # 4th log is in hour 1


def test_load_metrics(sample_openrca_dir):
    adapter = OpenRCAAdapter(sample_openrca_dir)
    result = adapter.load_metrics("Bank", "2021_03_04")
    assert "anomalies" in result
    assert "normal_metrics" in result
    # Should have data from both metric_container.csv and metric_app.csv
    all_metrics = result["anomalies"] + result["normal_metrics"]
    services = {m["service"] for m in all_metrics}
    assert "Tomcat01" in services or "ServiceTest1" in services


def test_load_metrics_by_service(sample_openrca_dir):
    adapter = OpenRCAAdapter(sample_openrca_dir)
    result = adapter.load_metrics("Bank", "2021_03_04", service="Tomcat01")
    all_metrics = result["anomalies"] + result["normal_metrics"]
    assert all(m["service"] == "Tomcat01" for m in all_metrics)


def test_load_traces(sample_openrca_dir):
    adapter = OpenRCAAdapter(sample_openrca_dir)
    result = adapter.load_traces("Bank", "2021_03_04")
    assert "critical_path" in result
    assert len(result["critical_path"]) > 0
    assert result["bottleneck"] is not None
    assert result["total_spans_analyzed"] == 6


def test_load_topology(sample_openrca_dir):
    adapter = OpenRCAAdapter(sample_openrca_dir)
    topo = adapter.load_topology("Bank")
    assert "nodes" in topo
    assert "edges" in topo
    assert len(topo["nodes"]) > 0


def test_load_ground_truth(sample_openrca_dir):
    adapter = OpenRCAAdapter(sample_openrca_dir)
    gt = adapter.load_ground_truth("Bank", "2021_03_04")
    assert gt["component"] == "Tomcat02"
    assert gt["root_cause"] == "high CPU usage"


def test_load_ground_truth_all(sample_openrca_dir):
    adapter = OpenRCAAdapter(sample_openrca_dir)
    incidents = adapter.load_ground_truth_all("Bank", "2021_03_04")
    assert len(incidents) == 2


def test_load_queries(sample_openrca_dir):
    adapter = OpenRCAAdapter(sample_openrca_dir)
    df = adapter.load_queries("Bank")
    assert len(df) == 1
    assert "task_index" in df.columns
