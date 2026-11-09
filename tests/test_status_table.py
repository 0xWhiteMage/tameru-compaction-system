from tameru.agent_formats import detect_test_runner, _classify_status_table, preprocess_test_output
from tameru.compress_context import compress_context


def _health_text():
    rows = [
        f"svc-{i:<10} {'OK' if i not in (4, 17) else 'DOWN':10} {10 + i}ms"
        for i in range(30)
    ]
    return "\n".join(["SERVICE        STATUS     LATENCY"] + rows)


def test_status_table_health_compresses_outliers():
    text = _health_text()
    assert detect_test_runner(text) == "status_table"
    r = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)
    assert "svc-4" in r.compressed_text
    assert "svc-17" in r.compressed_text
    assert "DOWN" in r.compressed_text
    assert not r.fail_open
    assert len(r.compressed_text) < 0.3 * len(text)


def test_status_table_df_keeps_high_use_outlier():
    rows = [
        f"/dev/sd{chr(97 + i)}1      100G  {20 + i}G  50G  {20 + i}% /mnt/d{i}"
        for i in range(20)
    ]
    rows.append("/dev/sdz1      100G   97G   3G  97% /var/lib/postgresql")
    text = "\n".join(["Filesystem      Size  Used Avail Use% Mounted on"] + rows)
    assert detect_test_runner(text) == "status_table"
    r = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)
    assert "sdz1" in r.compressed_text
    assert not r.fail_open


def test_status_table_kubectl_top_keeps_cpu_outlier():
    rows = [f"web-{i}-abc        {20 + i}m          {150 + i}Mi" for i in range(20)]
    rows.append("worker-x-9        3950m        7900Mi")
    text = "\n".join(["NAME              CPU(cores)   MEMORY(bytes)"] + rows)
    assert detect_test_runner(text) == "status_table"
    r = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)
    assert "worker-x-9" in r.compressed_text
    assert not r.fail_open


def test_status_table_no_outliers_keeps_all():
    rows = [f"svc-{i:<10} {'OK':10} {10 + i}ms" for i in range(30)]
    lines = ["SERVICE        STATUS     LATENCY"] + rows
    keep, _, _ = _classify_status_table(lines)
    assert all(keep)


def test_status_table_too_many_outliers_keeps_all():
    rows = [
        f"svc-{i:<10} {'DOWN' if i < 10 else 'OK':10} {10 + i}ms"
        for i in range(30)
    ]
    lines = ["SERVICE        STATUS     LATENCY"] + rows
    keep, _, _ = _classify_status_table(lines)
    assert all(keep)


def test_status_table_not_detected_for_csv_prose_short_rows():
    csv = "\n".join(["SERVICE,STATUS,LATENCY"] + [f"svc-{i},OK,10ms" for i in range(15)])
    assert detect_test_runner(csv) is None

    prose = "\n".join(["This is a paragraph with words"] + [f"line {i} has words" for i in range(15)])
    assert detect_test_runner(prose) is None

    short = "\n".join(["SERVICE        STATUS     LATENCY"] + [f"svc-{i:<10} OK 10ms" for i in range(10)])
    assert detect_test_runner(short) is None


def test_kubectl_pods_still_detected_before_status_table():
    text = "\n".join([
        "NAME   READY   STATUS   RESTARTS   AGE",
        "pod-0  1/1     Running  0          1d",
        "pod-1  1/1     Running  0          1d",
        "pod-2  1/1     Running  0          1d",
    ])
    assert detect_test_runner(text) == "kubectl_pods"


def test_full_row_with_spaced_mount_survives():
    base = ('Filesystem Size Used Avail Use% Mounted on\n'
            + '\n'.join(f'tmpfs 100G 10G 90G 10% /mnt/vol{i}' for i in range(30)))
    full = '/dev/archive 100G 100G 0G 100% /mnt/archive data'
    source = base + '\n/dev/data 100G 95G 5G 95% /data\n' + full + '\n'
    for out in (preprocess_test_output(source, "which filesystems are full"),
                compress_context(source, "which filesystems are full",
                                 ccr=False, citations=False).compressed_text):
        assert full in out
        assert '/dev/data 100G 95G 5G 95% /data' in out
        assert 'Filesystem Size Used Avail Use% Mounted on' in out
        assert len(out) < len(source) / 2
