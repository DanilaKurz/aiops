import os
import pytest
import tempfile


@pytest.fixture
def sample_openrca_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Bank dataset root
        bank_dir = os.path.join(tmpdir, "Bank")
        os.makedirs(bank_dir)

        # Telemetry date directory
        base = os.path.join(bank_dir, "telemetry", "2021_03_04")
        log_dir = os.path.join(base, "log")
        metric_dir = os.path.join(base, "metric")
        trace_dir = os.path.join(base, "trace")
        os.makedirs(log_dir)
        os.makedirs(metric_dir)
        os.makedirs(trace_dir)

        # log_service.csv -- real format
        with open(os.path.join(log_dir, "log_service.csv"), "w") as f:
            f.write("log_id,timestamp,cmdb_id,log_name,value\n")
            f.write('abc001,1614787200,Tomcat01,gc,"3748789.580: [GC (CMS Initial Mark) 2462269K(3145728K)] 0.198s"\n')
            f.write('abc002,1614787260,Tomcat01,gc,"3748849.779: [CMS-concurrent-mark-start]"\n')
            f.write('abc003,1614787320,Tomcat02,gc,"1234567.890: [Full GC (Allocation Failure) 3145728K->2000000K(3145728K), 5.123 secs]"\n')
            f.write('abc004,1614790800,Tomcat01,gc,"3749000.100: [GC (CMS Initial Mark) 2500000K(3145728K)] 0.250s"\n')

        # metric_container.csv -- long format
        with open(os.path.join(metric_dir, "metric_container.csv"), "w") as f:
            f.write("timestamp,cmdb_id,kpi_name,value\n")
            f.write("1614787200,Tomcat01,CpuPercent,25.5\n")
            f.write("1614787200,Tomcat01,MemPercent,60.2\n")
            f.write("1614787200,Tomcat02,CpuPercent,15.3\n")
            f.write("1614787260,Tomcat01,CpuPercent,26.1\n")
            f.write("1614787260,Tomcat01,MemPercent,61.0\n")
            f.write("1614787260,Tomcat02,CpuPercent,92.5\n")  # spike
            f.write("1614790800,Tomcat01,CpuPercent,30.0\n")  # hour 1

        # metric_app.csv -- wide format
        with open(os.path.join(metric_dir, "metric_app.csv"), "w") as f:
            f.write("timestamp,rr,sr,cnt,mrt,tc\n")
            f.write("1614787200,100.0,100.0,22,53.27,ServiceTest1\n")
            f.write("1614787260,100.0,98.5,20,120.5,ServiceTest1\n")
            f.write("1614787200,100.0,100.0,15,30.0,ServiceTest2\n")

        # trace_span.csv -- real format
        with open(os.path.join(trace_dir, "trace_span.csv"), "w") as f:
            f.write("timestamp,cmdb_id,parent_id,span_id,trace_id,duration\n")
            f.write("1614787200000,dockerA1,,span001,trace001,100\n")
            f.write("1614787200010,Tomcat01,span001,span002,trace001,90\n")
            f.write("1614787200020,Mysql01,span002,span003,trace001,80\n")
            f.write("1614787200100,dockerA1,,span004,trace002,500\n")
            f.write("1614787200110,Tomcat02,span004,span005,trace002,490\n")
            f.write("1614787200120,Redis01,span005,span006,trace002,480\n")

        # record.csv at Bank root -- real format
        with open(os.path.join(bank_dir, "record.csv"), "w") as f:
            f.write("level,component,timestamp,datetime,reason\n")
            f.write("pod,Tomcat02,1614787260,2021-03-04 00:01:00,high CPU usage\n")
            f.write("pod,Mysql01,1614790800,2021-03-04 01:00:00,high memory usage\n")

        # query.csv at Bank root
        with open(os.path.join(bank_dir, "query.csv"), "w") as f:
            f.write("task_index,instruction,scoring_points\n")
            f.write('task_7,"On March 4, 2021, between 00:00 and 00:30, identify root cause.","Component: Tomcat02, Reason: high CPU usage"\n')

        yield tmpdir
