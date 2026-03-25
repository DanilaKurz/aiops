import pytest
from app.drain.anomaly import AnomalyDetector


def test_detect_normal_windows():
    detector = AnomalyDetector(window_seconds=300, contamination=0.1)
    normal_data = [
        {"window_start": f"2024-01-15T10:{i*5:02d}:00Z",
         "template_counts": {1: 100, 2: 50, 3: 20}}
        for i in range(10)
    ]
    anomalies = detector.detect(normal_data)
    assert len(anomalies) <= 1  # at most 1 false positive


def test_detect_anomalous_window():
    detector = AnomalyDetector(window_seconds=300, contamination=0.1)
    windows = [
        {"window_start": f"2024-01-15T10:{i*5:02d}:00Z",
         "template_counts": {1: 100, 2: 50}}
        for i in range(9)
    ]
    # Anomalous window: template 1 spikes 50x
    windows.append({
        "window_start": "2024-01-15T10:45:00Z",
        "template_counts": {1: 5000, 2: 50}
    })
    anomalies = detector.detect(windows)
    assert len(anomalies) >= 1
    assert anomalies[0]["window_start"] == "2024-01-15T10:45:00Z"


def test_detect_new_template():
    detector = AnomalyDetector(window_seconds=300, contamination=0.1)
    anomalies = detector.detect_new_templates(
        known_templates={1, 2, 3},
        current_templates={1, 2, 3, 99}
    )
    assert 99 in [a["cluster_id"] for a in anomalies]
