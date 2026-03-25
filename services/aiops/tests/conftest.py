import os
import pytest
import tempfile


@pytest.fixture
def sample_openrca_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        base = os.path.join(tmpdir, "Bank", "2024_01_15")
        log_dir = os.path.join(base, "log")
        metric_dir = os.path.join(base, "metric")
        trace_dir = os.path.join(base, "trace")
        os.makedirs(log_dir)
        os.makedirs(metric_dir)
        os.makedirs(trace_dir)

        with open(os.path.join(log_dir, "gateway.csv"), "w") as f:
            f.write("timestamp,message\n")
            f.write("2024-01-15 10:10:00,Connection timeout to db-master after 30s\n")
            f.write("2024-01-15 10:10:01,Request processed in 120ms\n")
            f.write("2024-01-15 10:10:02,Health check OK\n")

        with open(os.path.join(metric_dir, "gateway.csv"), "w") as f:
            f.write("timestamp,metric_name,value\n")
            f.write("2024-01-15 10:10:00,cpu,0.45\n")
            f.write("2024-01-15 10:10:00,latency_p99,120\n")
            f.write("2024-01-15 10:15:00,cpu,0.92\n")
            f.write("2024-01-15 10:15:00,latency_p99,4200\n")

        with open(os.path.join(trace_dir, "traces.csv"), "w") as f:
            f.write("trace_id,span_id,parent_span_id,service,operation,duration_ms,status\n")
            f.write("t1,s1,,gateway,handle_request,4100,error\n")
            f.write("t1,s2,s1,payment-api,process_payment,4050,error\n")
            f.write("t1,s3,s2,db-master,query,4000,timeout\n")

        with open(os.path.join(base, "record.csv"), "w") as f:
            f.write("root_cause,component,description\n")
            f.write("db_lock_contention,db-master,Lock contention from unindexed query\n")

        yield tmpdir
