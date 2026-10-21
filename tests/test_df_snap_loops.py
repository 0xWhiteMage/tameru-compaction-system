from tameru.agent_formats import detect_test_runner, preprocess_test_output


def test_df_snap_loops_reduces_instead_of_failing_open():
    text = (
        "Filesystem      Size  Used Avail Use% Mounted on\n"
        + "\n".join(
            f"/dev/loop{i}      {50 + i}M  {50 + i}M     0 100% /snap/core/{1000 + i}"
            for i in range(20)
        )
        + "\n/dev/nvme0n1p2  468G  461G  7.0G  99% /\n"
        "tmpfs           7.8G  1.2M  7.8G   1% /run\n"
    )

    assert detect_test_runner(text) == "status_table"

    out = preprocess_test_output(text, "")
    assert out is not None
    assert "Filesystem      Size  Used Avail Use% Mounted on" in out
    assert "/dev/nvme0n1p2  468G  461G  7.0G  99% /" in out
    assert "/dev/loop7" not in out
    assert len(out) < len(text) * 0.4


def test_real_disk_at_95_percent_is_still_kept():
    text2 = (
        "Filesystem      Size  Used Avail Use% Mounted on\n"
        + "\n".join(
            f"/dev/sdb{i}       100G   20G   80G  20% /data{i}"
            for i in range(20)
        )
        + "\n/dev/sda1       100G   95G    5G  95% /\n"
    )

    out2 = preprocess_test_output(text2, "")
    assert out2 is not None
    assert "/dev/sda1       100G   95G    5G  95% /" in out2
