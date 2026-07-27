"""
Tests for unsupervised network anomaly detection.

The critical property under test: the detector is fitted ONLY on benign traffic
and never sees a label. Attacks are then generated with realistic traffic
characteristics and must be found on their merits.

This is the opposite of v1, where the "anomaly" was assigned into the input
array before analysis began.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.ml.anomaly.detector import (  # noqa: E402
    Flow, NetworkAnomalyDetector, extract_features, build_matrix,
    from_zeek_conn_log, FEATURE_NAMES, N_FEATURES,
)

RNG = np.random.default_rng(1337)
T0 = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)


def _benign_flow(i: int) -> Flow:
    """Ordinary HTTPS browsing: short, modest byte counts, normal handshake."""
    n_fwd = int(RNG.integers(4, 25))
    n_bwd = int(RNG.integers(4, 40))
    fwd_lens = RNG.integers(60, 600, size=n_fwd).tolist()
    bwd_lens = RNG.integers(60, 1500, size=n_bwd).tolist()
    return Flow(
        ts=T0 + timedelta(seconds=i * 2),
        src_ip=f"10.0.0.{RNG.integers(2, 60)}",
        dst_ip=f"93.184.{RNG.integers(1, 250)}.{RNG.integers(1, 250)}",
        src_port=int(RNG.integers(40000, 65000)),
        dst_port=443,
        protocol="tcp",
        duration_ms=float(RNG.uniform(80, 2500)),
        fwd_packets=n_fwd,
        bwd_packets=n_bwd,
        fwd_bytes=int(sum(fwd_lens)),
        bwd_bytes=int(sum(bwd_lens)),
        fwd_pkt_lengths=fwd_lens,
        bwd_pkt_lengths=bwd_lens,
        inter_arrival_times=RNG.uniform(1, 120, size=max(1, n_fwd)).tolist(),
        tcp_flags={"syn": 1, "ack": n_fwd + n_bwd, "fin": 1, "psh": int(RNG.integers(0, 4))},
        label="BENIGN",
        flow_id=f"benign-{i}",
    )


def _syn_flood(i: int) -> Flow:
    """Half-open connections: many SYNs, no ACKs, no return traffic."""
    return Flow(
        ts=T0 + timedelta(seconds=600 + i),
        src_ip=f"198.51.100.{RNG.integers(1, 250)}",
        dst_ip="10.0.0.5",
        src_port=int(RNG.integers(1024, 65000)),
        dst_port=80,
        protocol="tcp",
        duration_ms=float(RNG.uniform(0.5, 6)),
        fwd_packets=int(RNG.integers(600, 1600)),
        bwd_packets=0,
        fwd_bytes=int(RNG.integers(35000, 95000)),
        bwd_bytes=0,
        fwd_pkt_lengths=[60] * 40,
        bwd_pkt_lengths=[],
        inter_arrival_times=RNG.uniform(0.001, 0.05, size=40).tolist(),
        tcp_flags={"syn": int(RNG.integers(600, 1600)), "ack": 0},
        label="DDOS",
        flow_id=f"synflood-{i}",
    )


def _port_scan(i: int) -> Flow:
    """One packet out, RST back, sweeping ports."""
    return Flow(
        ts=T0 + timedelta(seconds=900 + i),
        src_ip="203.0.113.77",
        dst_ip="10.0.0.9",
        src_port=54321,
        dst_port=int(RNG.integers(1, 1024)),
        protocol="tcp",
        duration_ms=float(RNG.uniform(0.1, 2.5)),
        fwd_packets=1,
        bwd_packets=1,
        fwd_bytes=60,
        bwd_bytes=60,
        fwd_pkt_lengths=[60],
        bwd_pkt_lengths=[60],
        inter_arrival_times=[0.001],
        tcp_flags={"syn": 1, "rst": 1, "ack": 0},
        label="PORTSCAN",
        flow_id=f"portscan-{i}",
    )


def _exfiltration(i: int) -> Flow:
    """Long-lived upload: huge outbound volume, inverted ratio."""
    n_fwd = int(RNG.integers(4000, 9000))
    return Flow(
        ts=T0 + timedelta(seconds=1200 + i * 30),
        src_ip="10.0.0.31",
        dst_ip=f"185.220.{RNG.integers(1, 250)}.{RNG.integers(1, 250)}",
        src_port=51000 + i,
        dst_port=8443,
        protocol="tcp",
        duration_ms=float(RNG.uniform(180_000, 600_000)),
        fwd_packets=n_fwd,
        bwd_packets=int(RNG.integers(50, 250)),
        fwd_bytes=int(RNG.integers(40_000_000, 120_000_000)),
        bwd_bytes=int(RNG.integers(3000, 18000)),
        fwd_pkt_lengths=[1460] * 60,
        bwd_pkt_lengths=[80] * 20,
        inter_arrival_times=RNG.uniform(1, 40, size=60).tolist(),
        tcp_flags={"syn": 1, "ack": n_fwd, "psh": int(RNG.integers(400, 900))},
        label="EXFILTRATION",
        flow_id=f"exfil-{i}",
    )


# --------------------------------------------------------------------------

def test_feature_vector_shape_and_finiteness():
    f = _benign_flow(0)
    vec = extract_features(f)
    assert vec.shape == (N_FEATURES,)
    assert len(FEATURE_NAMES) == N_FEATURES
    assert np.all(np.isfinite(vec)), "features must never contain NaN or inf"


def test_empty_flow_does_not_crash():
    empty = Flow(ts=T0, src_ip="1.1.1.1", dst_ip="2.2.2.2")
    vec = extract_features(empty)
    assert np.all(np.isfinite(vec))
    assert build_matrix([]).shape == (0, N_FEATURES)


def test_refuses_to_fit_on_too_little_data():
    det = NetworkAnomalyDetector()
    try:
        det.fit([_benign_flow(i) for i in range(5)])
        raise AssertionError("should have refused to fit on 5 flows")
    except ValueError as exc:
        assert "at least 20" in str(exc)


def test_detects_attacks_it_never_saw():
    """The core test: fit on benign only, then find attacks on their merits."""
    benign_train = [_benign_flow(i) for i in range(400)]

    det = NetworkAnomalyDetector(threshold_percentile=99.0)
    det.fit(benign_train)          # no labels used
    assert det.is_fitted

    test_flows = (
        [_benign_flow(i + 1000) for i in range(100)]
        + [_syn_flood(i) for i in range(15)]
        + [_port_scan(i) for i in range(15)]
        + [_exfiltration(i) for i in range(10)]
    )
    results = det.score(test_flows)
    assert len(results) == len(test_flows)

    by_label: dict[str, list[float]] = {}
    for r in results:
        by_label.setdefault(r.label, []).append(r.score)

    benign_mean = float(np.mean(by_label["BENIGN"]))
    for attack in ("DDOS", "PORTSCAN", "EXFILTRATION"):
        attack_mean = float(np.mean(by_label[attack]))
        assert attack_mean > benign_mean, (
            f"{attack} mean {attack_mean:.3f} not above benign {benign_mean:.3f}"
        )

    metrics = det.evaluate(results)
    assert metrics["recall"] >= 0.60, f"recall too low: {metrics}"
    assert metrics["auc_roc"] >= 0.85, f"AUC too low: {metrics}"


def test_attribution_explains_the_score():
    benign_train = [_benign_flow(i) for i in range(300)]
    det = NetworkAnomalyDetector().fit(benign_train)
    results = det.score([_exfiltration(0)])
    r = results[0]
    assert r.attribution, "an anomaly with no attribution is unactionable"
    features = {a["feature"] for a in r.attribution}
    # Exfiltration must be explained by volume/duration, not something arbitrary.
    assert features & {
        "fwd_bytes", "total_bytes", "duration_ms", "fwd_packets",
        "total_packets", "fwd_pkt_len_mean",
    }, f"attribution did not name a volume feature: {r.attribution}"


def test_clusters_campaign_into_one_incident():
    benign_train = [_benign_flow(i) for i in range(300)]
    det = NetworkAnomalyDetector().fit(benign_train)
    # 40 SYN floods from many sources = one campaign, not 40 alerts.
    results = det.score([_syn_flood(i) for i in range(40)]
                        + [_benign_flow(i + 5000) for i in range(40)])
    incidents = det.cluster_incidents(results)
    assert incidents, "expected at least one clustered incident"
    biggest = max(incidents, key=lambda inc: inc["member_count"])
    assert biggest["member_count"] >= 10
    assert biggest["severity"] in {"medium", "high", "critical"}


def test_evaluate_without_labels_is_honest():
    benign_train = [_benign_flow(i) for i in range(300)]
    det = NetworkAnomalyDetector().fit(benign_train)
    unlabeled = _benign_flow(1)
    unlabeled.label = None
    out = det.evaluate(det.score([unlabeled]))
    assert "error" in out


def test_zeek_conn_log_parsing():
    log_text = """#separator \\x09
#fields\tts\tuid\tid.orig_h\tid.orig_p\tid.resp_h\tid.resp_p\tproto\tduration\torig_bytes\tresp_bytes\torig_pkts\tresp_pkts\thistory
1753000000.123\tCabc123\t10.0.0.5\t51234\t93.184.216.34\t443\ttcp\t1.523\t4821\t28104\t14\t22\tShADadFf
1753000002.456\tCdef456\t10.0.0.7\t51999\t142.250.1.1\t80\ttcp\t0.201\t320\t1450\t3\t4\tShADf
"""
    flows = from_zeek_conn_log(log_text.splitlines())
    assert len(flows) == 2
    assert flows[0].src_ip == "10.0.0.5"
    assert flows[0].dst_port == 443
    assert flows[0].protocol == "tcp"
    assert abs(flows[0].duration_ms - 1523.0) < 1.0
    assert flows[0].tcp_flags["syn"] >= 1
    assert flows[0].flow_id == "Cabc123"


def test_zeek_json_lines_parsing():
    jsonl = (
        '{"ts":1753000000.5,"uid":"Cxyz","id.orig_h":"10.0.0.9",'
        '"id.orig_p":52000,"id.resp_h":"1.1.1.1","id.resp_p":53,'
        '"proto":"udp","duration":0.05,"orig_bytes":72,"resp_bytes":140,'
        '"orig_pkts":1,"resp_pkts":1,"history":"Dd"}'
    )
    flows = from_zeek_conn_log([jsonl])
    assert len(flows) == 1
    assert flows[0].protocol == "udp"
    assert flows[0].dst_port == 53


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL  {t.__name__}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
