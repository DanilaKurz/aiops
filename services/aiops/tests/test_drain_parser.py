from app.drain.parser import DrainParser


def test_parse_single_log():
    parser = DrainParser()
    result = parser.parse("Connection timeout to db-master after 30s")
    assert result["cluster_id"] is not None
    assert result["template"] is not None


def test_parse_groups_similar_logs():
    parser = DrainParser()
    r1 = parser.parse("Connection timeout to db-master after 30s")
    r2 = parser.parse("Connection timeout to payment-api after 45s")
    assert r1["cluster_id"] == r2["cluster_id"]


def test_get_clusters():
    parser = DrainParser()
    parser.parse("Connection timeout to db-master after 30s")
    parser.parse("Health check OK")
    clusters = parser.get_clusters()
    assert len(clusters) == 2


def test_batch_parse():
    parser = DrainParser()
    lines = [
        "Connection timeout to db-master after 30s",
        "Connection timeout to payment-api after 45s",
        "Health check OK",
    ]
    results = parser.batch_parse(lines)
    assert len(results) == 3
