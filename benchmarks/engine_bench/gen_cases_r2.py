"""Round-2 generated cases for the NEW sealed engine_bench split (synthetic, no copyrighted data).

Every family here is a format that appears in neither the round-1 engine_bench corpus nor the
session corpus's 45 families (see tests/test_engine_bench_r2.py for the programmatic non-overlap
check).  Per family ~11 source clusters; a cluster's content depends only on (family, source index),
the variant only on how much noise surrounds it, and variants share ``source_case`` so a cluster
never straddles a split.

Item kinds (``item_kind`` field):
  evidence       errors / failures / final status lines as gold, like round 1.
  s5_buried      one non-error assignment line (k=v, k: v, k -> v, a JSON msg with '=', or a zh
                 config line) buried in repetitive filler; gold = that whole line, fact = {key,
                 value, line}.
  s5_superseded  the same key twice, stale then newest; gold = the newest line (the stale line is
                 ``forbidden``), fact = the newest.
  csv_args       a CSV-like table with a buried assignment line; the tool_call args contain a token
                 that is also a CSV value (the plan's CSV pre-filter hypothesis, S5 (a)).

Queries: task_specific names the key or thing, task_vague names none, tool_call is the command,
generic is "continue", zh_user (zh/mixed cases only) is a conversational Chinese message.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .gen_cases import GENERIC_QUERY, hexid, rng, ts

# ------------------------------------------------------------------ parameters
_WORDS = ["billing", "orders", "ledger", "cache", "relay", "ingest", "export", "audit", "sync", "index"]
_WORDS_ZH = ["结算", "订单", "台账", "缓存", "中继", "采集", "导出", "审计", "同步", "索引"]
_ZH_USER = ["帮我看一下上面的输出，有问题的地方指出来。", "刚才跑的结果怎么样？有错误就告诉我。",
            "看一下这个输出，把重要的信息挑出来。", "看看运行结果，有异常的话说明原因。"]
_VAGUE_EN = ["check how the run went", "look at this output and report anything that looks wrong",
             "summarize the result of the last command"]
_VAGUE_ZH = ["看看这次运行的结果", "看一下这个输出有没有问题", "上面的输出帮我检查一下"]

# (en key, zh key) — config-ish keys whose assigned value a model must be able to read back.
_KEYS = [("retry_limit", "重试次数"), ("max_workers", "最大工作线程"), ("queue_depth", "队列深度"),
         ("cache_ttl", "缓存有效期"), ("batch_size", "批处理大小"), ("timeout_ms", "超时毫秒"),
         ("shard_count", "分片数量"), ("lease_seconds", "租约秒数"), ("pool_size", "连接池大小"),
         ("keep_days", "保留天数"), ("drain_seconds", "排空秒数"), ("fan_out", "扇出数")]


def _p(r, i, n, rid):
    """Template params: ``i`` per line, the rest per cluster."""
    return {"i": i, "j": i, "n": n, "m": r.randint(10, 999), "rid": rid, "ts": ts(r, i),
            "i3": i % 3, "i3p": i % 3 + 1, "i4": i % 4, "i4p": i % 4 + 1, "i5": i % 5, "i6": i % 6,
            "i8": i % 8 + 1, "i10": i % 10, "i40": i % 40 + 4, "i60": i % 60 + 5, "i90": i % 90 + 5,
            "host": f"host-{i % 24:02d}", "pid": r.randint(1000, 99999), "word": r.choice(_WORDS),
            "pkg": f"pkg-{r.randint(1, 60)}", "ver": f"{r.randint(0, 4)}.{r.randint(0, 20)}.{r.randint(0, 9)}",
            "cpu": f"{r.randint(0, 99)}.{r.randint(0, 9)}", "mem": f"{r.randint(0, 99)}.{r.randint(0, 9)}",
            "port": r.randint(2000, 9900), "ms": r.randint(1, 900), "ip": f"10.{r.randint(0, 9)}.{r.randint(0, 250)}.{r.randint(2, 250)}",
            "uuid": hexid(r, 12), "e": r.randint(1, 127), "c": r.randint(10, 990)}


def _F(fid, ctype, thing, tool, head, fill, fill_zh, err, tail, csv, fclass):
    return {"id": fid, "ctype": ctype, "thing": thing, "tool": tool, "head": head, "fill": fill,
            "fill_zh": fill_zh, "err": err, "tail": tail, "csv": csv, "fclass": fclass}


# Format classes no r2 family may belong to (they duplicate round-1 or session-corpus formats):
#   installer    package-installer logs (apt/pip/npm-like; conan/vcpkg/pnpm/composer excluded)
#   fileline-diag  one-line ``file:line(:col): severity:`` diagnostics (gcc/mypy/ruff/hadolint/rubocop)
#   js-test      JS test runners with check marks and expect diffs (jest/vitest/mocha/playwright)
#   access-log   web/proxy access logs (nginx/envoy/haproxy/traefik/caddy)
#   api-json     JSON API payloads (apijson/OTel spans/sentry events/aws JSON)
BLOCKED_FCLASSES = ("installer", "fileline-diag", "js-test", "access-log", "api-json")


# csv = (header, row template, tool template); ``{sel}`` in the tool is a token that is also a row value.
FAMILIES = [
    _F("robotfw", "test", "the Robot Framework suite", "robot --outputdir out suites/acme.robot",
       ["==============================================================================",
        "Acme {word}                                                            ",
        "=============================================================================="],
       ["Acme.{word}.Case{i:03d} :: step {j} completed                          | PASS |",
        "------------------------------------------------------------------------------"],
       ["Acme.{word}.用例{i:03d} :: 步骤 {j} 完成                                   | 通过 |"],
       ["Acme.{word}.Checkout :: submitting the order                           | FAIL |",
        "Error: gateway returned HTTP {e} for charge {uuid}"],
       ["==============================================================================",
        "Acme {word}                                                            | FAIL |",
        "1 critical test, 0 passed, 1 failed"],
       ("TEST,STATUS,TIME", "acme-{word}-{j:02d},PASS,{ms}ms", "rebot --report acme-{word}-{sel:02d}.xml"), "test-report"),
    _F("behave", "test", "the behave run", "behave features/checkout.feature",
       ["Feature: {word} checkout flow  # features/{word}.feature",
        "  Scenario: registered {word} user checks out"],
       ["    Given the cart holds item sku-{i:03d}                              # steps/cart.py",
        "    When the price service answers in {ms} ms                        # steps/price.py",
        "    Then the total shows {n}.{m}                                      # steps/total.py"],
       ["    当 购物车中有商品 sku-{i:03d}                              # steps/cart.py",
        "    那么 总价应显示 {n}.{m}                                       # steps/total.py"],
       ["    Then the payment is captured                                     # steps/pay.py",
        "      Assertion Failed: expected receipt rc-{uuid}, got none"],
       ["1 feature passed, 0 failed, 0 skipped",
        "1 scenario passed, 1 failed, 2 skipped, 0 undefined"],
       ("STEP,STATUS,DURATION", "acme-{word}-{j:02d},passed,{ms}ms", "behave --junit --junit-directory out acme-{word}-{sel:02d}"), "gherkin-report"),
    _F("systemctl", "log", "the acme service unit", "systemctl status acme-{word}.service",
       ["● acme-{word}.service - Acme {word} service daemon",
        "   Loaded: loaded (/etc/systemd/system/acme-{word}.service; enabled; preset: enabled)"],
       ["   Active: active (running) since {ts}; {m}s ago",
        " Main PID: {pid} (python3)", "      Tasks: {n} (limit: 4915)",
        "   Memory: {cpu}M", "      CPU: {c}ms"],
       ["   状态: 正在运行 自 {ts}；已运行 {m} 秒",
        " 主进程: {pid} (python3)"],
       ["{ts} node-07 systemd[1]: acme-{word}.service: Main process exited, code=exited, status={e}/FAILURE",
        "{ts} node-07 systemd[1]: acme-{word}.service: Failed with result 'exit-code'."],
       ["{ts} node-07 systemd[1]: Stopped Acme {word} service daemon."],
       ("UNIT,PID,STATE,MS", "acme-{word}-{j:02d},{pid},running,{ms}", "journalctl -u acme-{word}-{sel:02d}.service -n 50"), "unit-status"),
    _F("dmesg", "log", "the kernel ring buffer", "dmesg -T | tail -n 300",
       ["[{cpu}.{pid}] acme: module loaded, build {ver}"],
       ["[{cpu}.{pid}] acme_net {host}: link up, {port} Mbps full duplex",
        "[{cpu}.{pid}] acme_blk nvme0n1: wrote sector {uuid} ok",
        "[{cpu}.{pid}] audit: type=1300 audit({ts}): arch=c000003e syscall={i} success=yes"],
       ["[{cpu}.{pid}] 审计: 类型=1300 审计({ts})：系统调用={i} 成功=是"],
       ["[{cpu}.{pid}] acme_net {host}: firmware error {e}: queue reset failed",
        "[{cpu}.{pid}] watchdog: BUG: soft lockup - CPU#{e} stuck for {m}s!"],
       ["[{cpu}.{pid}] acme_net {host}: device left promiscuous mode"],
       ("TS,MODULE,EVENT,MS", "{cpu}.{pid},acme-{word}-{j:02d},ok,{ms}", "dmesg -T | grep acme-{word}-{sel:02d}"), "kernel-log"),
    _F("pstable", "structured", "the process table", "ps aux --sort=-%cpu",
       ["USER       PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND"],
       ["acme      {pid}  {cpu}  {mem} {m}0 {n}0 ?        S    {ts}   0:0{i10} /opt/acme/bin/{word}-worker --shard {j:02d}"],
       ["acme      {pid}  {cpu}  {mem} {m}0 {n}0 ?        S    {ts}   0:0{i10} /opt/acme/bin/{word}-worker --分片 {j:02d}"],
       ["acme      {pid} {e}.0  {mem} {m}0 {n}0 ?        R    {ts}   9:{ms} /opt/acme/bin/{word}-gc --aggressive",
        "acme      {pid} {e}.0  {mem} {m}0 {n}0 ?        Z    {ts}   0:00 [acme-{word}-gc] <defunct>"],
       ["USER       PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND"],
       ("USER,PID,%CPU,%MEM,COMMAND", "acme,{pid},{cpu},{mem},acme-{word}-{j:02d}", "ps aux | grep acme-{word}-{sel:02d}"), "proc-table"),
    _F("sstable", "structured", "the socket table", "ss -tlnp",
       ["State    Recv-Q Send-Q  Local Address:Port   Peer Address:Port  Process"],
       ["LISTEN   0      {n}         {ip}:{port}           0.0.0.0:*      users:((\"acme-{word}\",pid={pid},fd={j}))",
        "TIME-WAIT 0    0         {ip}:{port}          {ip}:{ms}      "],
       ["监听    0      {n}         {ip}:{port}           0.0.0.0:*      users:((\"acme-{word}\",pid={pid},fd={j}))"],
       ["LISTEN   0      {n}         {ip}:{port}           0.0.0.0:*      users:((\"acme-{word}\",pid={pid},fd={j}))",
        "{ts} kernel: TCP: request_sock_TCP: Possible SYN flooding on port {port}. Dropping request."],
       ["State    Recv-Q Send-Q  Local Address:Port   Peer Address:Port  Process"],
       ("STATE,LOCAL,PEER,PID", "LISTEN,{ip}:{port},acme-{word}-{j:02d},{pid}", "ss -tlnp | grep acme-{word}-{sel:02d}"), "socket-table"),
    _F("dftable", "structured", "the disk table", "df -h",
       ["Filesystem      Size  Used Avail Use% Mounted on"],
       ["/dev/sd{word[0]}1       {n}G  {m}G  {c}G  {i90}% /srv/{word}/vol{j:02d}"],
       ["/dev/sd{word[0]}1       {n}G  {m}G  {c}G  {i90}% /srv/{word}/卷{j:02d}"],
       ["/dev/sdb1       {n}G  {m}G  {c}K 100% /srv/{word}/wal",
        "df: /srv/{word}/wal: Input/output error"],
       ["Filesystem      Size  Used Avail Use% Mounted on"],
       ("FS,SIZE,USED,AVAIL,MOUNT", "acme-{word}-{j:02d},{n}G,{m}G,{c}G,/srv/acme-{word}-{j:02d}", "df -h /srv/acme-{word}-{sel:02d}"), "disk-table"),
    _F("iostat", "structured", "the io statistics", "iostat -x 1 5",
       ["avg-cpu:  %user   %nice %system %iowait  %steal   %idle",
        "           {cpu}    0.00    {mem}    {cpu}    0.00   {mem}"],
       ["Device            r/s     w/s  rMB/s  wMB/s %util",
        "sd{word[0]}           {cpu}   {mem}   {cpu}    {mem}  {i60}.{i10}"],
       ["设备            r/s     w/s  rMB/s  wMB/s %util",
        "sd{word[0]}           {cpu}   {mem}   {cpu}    {mem}  {i60}.{i10}"],
       ["Device            r/s     w/s  rMB/s  wMB/s %util",
        "sd{word[0]}           {cpu}   {mem}   {cpu}    {mem}  100.0{e}",
        "iostat: /dev/sd{word[0]}: device reported error {e} on sector {uuid}"],
       ["avg-cpu:  %user   %nice %system %iowait  %steal   %idle"],
       ("DEV,R/S,W/S,RMB,UTIL", "acme-{word}-{j:02d},{cpu},{mem},{cpu}.{mem},{i}", "iostat -x | grep acme-{word}-{sel:02d}"), "io-stats"),
    _F("cfevents", "log", "the CloudFormation deploy", "aws cloudformation describe-stack-events --stack-name acme-{word}",
       ["StackEvents", "|  Timestamp                LogicalResourceId        ResourceStatus           ResourceStatusReason"],
       ["|  {ts}  AWS::EC2::Instance     CREATE_IN_PROGRESS     -",
        "|  {ts}  acme{word}Volume{j:02d}   CREATE_COMPLETE        -"],
       ["|  {ts}  acme{word}卷{j:02d}   创建完成        -"],
       ["|  {ts}  AWS::EC2::Instance     CREATE_FAILED          API: ec2:RunInstances Not authorized for AMI ami-{uuid}",
        "|  {ts}  acme-{word}-stack      ROLLBACK_IN_PROGRESS   The following resource(s) failed to create: [acme{word}Instance]"],
       ["|  {ts}  acme-{word}-stack      ROLLBACK_COMPLETE      -"],
       ("TIME,RESOURCE,STATUS", "{ts},acme-{word}-{j:02d},CREATE_COMPLETE", "aws cloudformation describe-stack-events --stack-name acme-{word}-{sel:02d}"), "stack-events"),
    _F("nixbuild", "build", "the nix build", "nix build .#acme-{word}",
       ["these {n} derivations will be built:", "  /nix/store/{uuid}-acme-{word}-{ver}.drv"],
       ["building '/nix/store/{uuid}-acme-dep{j:02d}-{ver}.drv'...",
        "acme-{word}> unpacking sources", "acme-{word}> patching file {pkg}.nix"],
       ["acme-{word}> 正在解压源码包 {j:02d}", "acme-{word}> 正在修补文件 {pkg}.nix"],
       ["error: builder for '/nix/store/{uuid}-acme-{word}-{ver}.drv' failed with exit code {e}",
        "acme-{word}> make: *** [Makefile:{m}: {word}_gen.o] Error {e}"],
       ["error: {e} dependencies of derivation '/nix/store/{uuid}-acme-{word}-{ver}.drv' failed to build"],
       ("DRV,STATE,SIZE", "/nix/store/{uuid}-acme-{word}-{j:02d}.drv,built,{m}KiB", "nix path-info /nix/store/*acme-{word}-{sel:02d}*"), "build-log"),
    _F("shellcheck", "test", "the shellcheck run", "shellcheck scripts/*.sh",
       ["In scripts/acme-{word}.sh line {n}:", ""],
       ["In scripts/{pkg}.sh line {i}:",
        "  {word}_run $1",
        "            ^-- SC2086 (info): Double quote to prevent globbing and word splitting.",
        "In scripts/{pkg}.sh line {i}:",
        "  [ \"$a\" == \"x\" ]",
        "            ^-- SC2292 (style): Prefer [[ ]] over [ ] for tests."],
       ["In scripts/{pkg}.sh line {i}:",
        "  echo ${word}",
        "           ^-- SC2086 (提示): 使用双引号防止通配展开。"],
       ["In scripts/acme-{word}.sh line {i}:",
        "  eval ${word}_data",
        "       ^-- SC2046 (error): Quote this to prevent word splitting.",
        "In scripts/acme-{word}.sh line {i}:",
        "  out=$(acme-{word} $2)",
        "       ^-- SC2154 (warning): acme-{word}_conf is referenced but not assigned."],
       ["For more information:", "  https://www.shellcheck.net/wiki/SC2086"],
       ("FILE,LINE,CODE,SEV", "acme-{word}-{j:02d}.sh,{i},SC{n},info", "shellcheck acme-{word}-{sel:02d}.sh"), "lint-findings"),
    _F("trivy", "structured", "the trivy scan", "trivy image acme/{word}:{ver}",
       ["acme/{word}:{ver} (debian 12.{i10})", "Total: {n} (UNKNOWN: 0, LOW: {m}, MEDIUM: {c}, HIGH: {e}, CRITICAL: 1)"],
       ["│ {pkg}   │ CVE-2026-{n}   │ MEDIUM   │ {ver}      │ {ver}.1       │ acme-{word} overflow {j:02d}      │",
        "│ {pkg}   │ CVE-2026-{n}   │ LOW      │ {ver}      │ {ver}.1       │ acme-{word} info leak {j:02d}     │"],
       ["│ {pkg}   │ CVE-2026-{n}   │ 中      │ {ver}      │ {ver}.1       │ acme-{word} 溢出 {j:02d}          │"],
       ["│ lib{word}ssl │ CVE-2026-{e}04{j:02d} │ CRITICAL │ {ver}   │               │ acme-{word} remote code exec │",
        "│ {pkg}          │ CVE-2026-{n}   │ HIGH     │ {ver}      │ {ver}.1       │ acme-{word} privilege gain │"],
       ["├─────────┼────────────────┼──────────┼──────────┼─────────────┼──────────────────────────────┤"],
       ("LIB,CVE,SEV,FIXED", "acme-{word}-{j:02d},CVE-2026-{n},HIGH,{ver}", "trivy image acme-{word}-{sel:02d}:{ver}"), "cve-table"),
    _F("semgrep", "test", "the semgrep run", "semgrep --config auto src/",
       ["┌─────────────┐", "│ Scan Status │", "└─────────────┘", "  Scanning {n} files tracked by git"],
       ["  src/{pkg}/h{j:02d}.py:{i}: acme.{word}.no-{word}fmt",
        "    {word}_data = open(path).read()[:{m}]"],
       ["  src/{pkg}/h{j:02d}.py:{i}: acme.{word}.检查-{word}格式",
        "    {word}_data = open(path).read()[:{m}]"],
       ["  src/acme/{word}/conn.py:{i}: acme.{word}.insecure-socket",
        "    sock.connect((host, {port}))  # nosec would hide a real flaw"],
       ["Ran {n} rules on {m} files: {e} findings."],
       ("RULE,FILE,LINE", "acme-{word}-{j:02d},src/{pkg}.py,{i}", "semgrep --config auto acme-{word}-{sel:02d}/"), "lint-findings"),
    _F("bandit", "test", "the bandit run", "bandit -r src/ -f txt",
       ["[main]\tINFO\tprofile include tests: None",
        "[main]\tINFO\trunning on Python 3.13.{i}"],
       ["[node]\tINFO\tfile {pkg}{j:02d}.py processed, {m} nodes",
        "[tester]\tINFO\tacme-{word} check {j:02d} skipped (not selected)"],
       ["[tester]\tINFO\tacme-{word} 检查 {j:02d} 已跳过（未选中）"],
       [">> Issue: [B602:{word}_popen] subprocess call with shell=True, severity: High",
        "   Location: src/acme/{word}/run.py:{i}:23",
        "   More Info: https://bandit.readthedocs.io/en/latest/plugins/b602_subprocess_popen_with_shell_equals_true.html"],
       ["Test results:", "\t{e} issues identified.", "Code scanned:", "\tTotal lines of code: {n}00"],
       ("FILE,LINE,ISSUE,SEV", "acme-{word}-{j:02d}.py,{i},B{n},medium", "bandit -r acme-{word}-{sel:02d}/"), "lint-findings"),
    _F("checkov", "test", "the checkov run", "checkov -d infra/ --framework terraform",
       ["terraform scan results:", ""],
       ["Check: CKV_AWS_{n}: \"Ensure acme-{word} bucket {j:02d} has encryption\"",
        "\tPASSED for resource: aws_s3_bucket.acme_{word}_{j:02d}",
        "\tFile: /acme_{word}.tf:{i}-{m}"],
       ["检查: CKV_AWS_{n}: \"确保 acme-{word} 桶 {j:02d} 已加密\"",
        "\t通过 资源: aws_s3_bucket.acme_{word}_{j:02d}"],
       ["Check: CKV_AWS_{n}: \"Ensure acme-{word} security group restricts ingress\"",
        "\tFAILED for resource: aws_security_group.acme_{word}_sg",
        "\tFile: /acme_{word}.tf:{i}-{m}",
        "\tGuide: https://docs.prismacloud.io/en/enterprise-edition/policy-reference/aws-policies"],
       ["Passed checks: {c}, Failed checks: {e}, Skipped checks: 0"],
       ("CHECK,RESOURCE,RESULT", "CKV_AWS_{n},acme-{word}-{j:02d},PASSED", "checkov -d acme-{word}-{sel:02d}/ --framework terraform"), "policy-checks"),
    _F("rediscli", "log", "the redis-cli session", "redis-cli -h {ip} info",
       ["# Server", "redis_version:{ver}", "redis_mode:standalone"],
       ["# Clients", "connected_clients:{n}", "blocked_clients:{i4}",
        "# Memory", "used_memory_human:{m}.{i:02d}M", "mem_fragmentation_ratio:1.{i:02d}"],
       ["# 客户端", "已连接客户端:{n}", "被阻塞客户端:{i4}"],
       ["(error) MISCONF Redis is configured to save RDB snapshots, but it is currently not able to persist on disk.",
        "WARNING: The TCP backlog setting of {port} cannot be enforced"],
       ["# Persistence", "rdb_last_save_time:{pid}", "aof_enabled:0"],
       ("KEY,FIELD,VALUE", "acme-{word}-{j:02d},clients,{n}", "redis-cli -h {ip} info acme-{word}-{sel:02d}"), "kv-dump"),
    _F("mongo", "log", "the mongosh session", "mongosh acme_{word} --eval 'db.stats()'",
       ["Current Mongosh Log ID: {uuid}", "Using MongoDB: {ver}", "For mongosh info see: https://www.mongodb.com/docs/mongodb-shell/"],
       ["acme_{word}> db.acme_{word}_{j:02d}.stats()", "{{", "  ns: 'acme_{word}.acme_{word}_{j:02d}',", "  size: {n}00,",
        "  count: {m},", "  avgObjSize: {c},", "  storageSize: {n}0,", "}}", "acme_{word}>"],
       ["acme_{word}> db.acme_{word}_{j:02d}.stats()", "{{", "  ns: 'acme_{word}.acme_{word}_{j:02d}',", "  大小: {n}00,",
        "  文档数: {m},", "}}", "acme_{word}>"],
       ["acme_{word}> db.acme_{word}_{j:02d}.find().limit(1)",
        "MongoServerError: not authorized on acme_{word} to execute command {{ find: \"acme_{word}_{j:02d}\", lsid: {{ id: {uuid} }} }}"],
       ["acme_{word}> exit"],
       ("DB,NS,SIZE", "acme-{word}-{j:02d},acme_{word},{n}", "mongosh acme_{word} --eval 'db.acme-{word}-{sel:02d}.stats()'"), "db-shell"),
    _F("essearch", "structured", "the elasticsearch _cat call", "curl -s es-{ip}:9200/_cat/indices?v",
       ["health status index               uuid                   pri rep docs.count docs.deleted store.size pri.store.size"],
       ["green  open   acme-{word}-{j:02d}     {uuid}   {i4p}   1     {n}00            {m}      {c}.{i}mb         {c}.{i}mb"],
       ["green  open   acme-{word}-{j:02d}     {uuid}   {i4p}   1     {n}00            {m}      {c}.{i}mb         {c}.{i}mb"],
       ["yellow open   acme-{word}-{j:02d}     {uuid}   {i4p}   1     {n}00            {m}      {c}.{i}mb         {c}.{i}mb",
        "red    open   acme-{word}-hot       {uuid}   1   0"],
       ["health status index               uuid                   pri rep docs.count docs.deleted store.size pri.store.size"],
       ("INDEX,STATUS,DOCS,SIZE", "acme-{word}-{j:02d},green,{n},{c}mb", "curl -s es-{ip}:9200/_cat/indices/acme-{word}-{sel:02d}?v"), "index-table"),
    _F("kafka", "log", "the kafka consumer", "kafka-console-consumer --topic acme-{word} --from-beginning",
       ["[Consumer clientId=acme-{word}-c, groupId=acme-{word}-g] Subscribed to topic acme-{word}",
        "[Consumer clientId=acme-{word}-c] Seeking to offset {n}"],
       ["{{\"order\":\"ORD-{n}{i:03d}\",\"amount\":{m}.{i:02d}\",\"status\":\"ok\",\"partition\":{i6}}}",
        "{{\"event\":\"acme-{word}.tick\",\"seq\":{i:04d}\",\"lag\":{m}}}"],
       ["{{\"订单\":\"ORD-{n}{i:03d}\",\"金额\":{m}.{i:02d}\",\"状态\":\"成功\",\"分区\":{i6}}}"],
       ["{{\"order\":\"ORD-{n}{i:03d}\",\"status\":\"FAILED\",\"reason\":\"gateway code {e}\",\"partition\":{i6}}}",
        "[Consumer clientId=acme-{word}-c] ERROR: failed to deserialize record at offset {n}: poison pill"],
       ["Processed a total of {n} messages"],
       ("OFFSET,PARTITION,KEY,LEN", "{n},{i6},acme-{word}-{j:02d},{m}", "kafka-console-consumer --topic acme-{word}-{sel:02d} --from-beginning"), "record-stream"),
    _F("flyway", "build", "the flyway migrate", "flyway -url=jdbc:postgresql://{ip}/acme_{word} migrate",
       ["Flyway Community Edition {ver} by Redgate", "Database: jdbc:postgresql://{ip}/acme_{word} (PostgreSQL 16.{i4})"],
       ["Migrating schema \"acme_{word}\" to version \"{i}.{j:02d} - add {word} column {m}\"",
        "Successfully applied {n} migrations; now at table version v{n}"],
       ["迁移模式 \"acme_{word}\" 到版本 \"{i}.{j:02d} - 添加 {word} 列 {m}\""],
       ["ERROR: Migration of schema \"acme_{word}\" to version \"{i}.{j:02d} - add {word} column {m}\" failed!",
        "ERROR: Migration V{i}_{j:02d}__add_{word}_column.sql failed: ERROR: column \"{word}_id\" of relation \"orders\" already exists"],
       ["Successfully validated {n} migrations"],
       ("VER,NAME,STATE", "{i}.{j:02d},acme-{word}-{j:02d},applied", "flyway info -url=jdbc:postgresql://{ip}/acme-{word}-{sel:02d}"), "migration-log"),
    _F("dbt", "build", "the dbt run", "dbt run --select acme_{word}+",
       ["{ts}  Running with dbt={ver}", "{ts}  Registered adapter: postgres={ver}"],
       ["{ts}  {i:02d} of {n} OK created sql table model acme_{word}.stg_{word}_{j:02d} ........ [OK in {cpu}.{mem}s]",
        "{ts}  {i:02d} of {n} SKIP relation acme_{word}.stg_skip_{j:02d} ........ [SKIP]"],
       ["{ts}  {i:02d} / {n} 已创建模型 acme_{word}.stg_{word}_{j:02d} ........ [用时 {cpu}.{mem} 秒]"],
       ["{ts}  {i:02d} of {n} ERROR creating sql table model acme_{word}.fct_{word}_{j:02d} ... [ERROR in {cpu}.{mem}s]",
        "{ts}  Database Error in model fct_{word}_{j:02d} (models/acme_{word}/fct_{word}_{j:02d}.sql)",
        "  column \"{word}_amt\" does not exist"],
       ["{ts}  Completed with {e} error and 0 warnings:"],
       ("MODEL,STATE,TIME", "acme-{word}-{j:02d},OK,{cpu}s", "dbt run --select acme-{word}-{sel:02d}+"), "build-log"),
    _F("winevt", "log", "the Windows event export", "wevtutil qe Application /q:\"*[System[Provider[@Name='acme-{word}']]]\" /f:text",
       ["Event Log Query", "  Source: Application", "  Filter: Provider[@Name='acme-{word}']"],
       ["Event[{i}]:", "  Log Name: Application", "  Source: acme-{word}", "  Date: {ts}", "  Event ID: {n}", "  Task: None",
        "  Level: Information", "  Description:", "    acme-{word} worker {j:02d} heartbeat ok"],
       ["事件[{i}]:", "  日志名: 应用程序", "  来源: acme-{word}", "  日期: {ts}", "  事件 ID: {n}", "  级别: 信息",
        "  描述:", "    acme-{word} 工作进程 {j:02d} 心跳正常"],
       ["Event[{i}]:", "  Log Name: Application", "  Source: acme-{word}", "  Date: {ts}", "  Event ID: {n}", "  Task: None",
        "  Level: Error", "  Keywords: Classic", "  Description:",
        "    acme-{word} worker {j:02d} terminated unexpectedly, exit code {e} (0x{e:x})"],
       ["Event[{i}]:", "  Log Name: Application", "  Source: acme-{word}", "  Date: {ts}", "  Event ID: 6006", "  Task: None",
        "  Level: Information", "  Description:", "    The event log service was stopped."],
       ("EID,LEVEL,SOURCE,DATE", "{n},Error,acme-{word}-{j:02d},{ts}", "wevtutil qe Application /q:\"*[System[Provider[@Name='acme-{word}-{sel:02d}']]]\" /f:text"), "event-log"),
    _F("pserrors", "log", "the PowerShell transcript", "powershell -File scripts/acme-{word}.ps1",
       ["PS C:\\acme> .\\acme-{word}.ps1 -Batch {j:02d}", "VERBOSE: acme-{word} worker {j:02d} starting"],
       ["VERBOSE: acme-{word} step {i} wrote {m} rows in {ms} ms",
        "WARNING: retry {i4} for shard {j:02d} took {ms} ms"],
       ["VERBOSE: acme-{word} 步骤 {i} 写入 {m} 行，用时 {ms} 毫秒"],
       ["Write-Error: acme-{word} step {i}: The remote server returned an error: ({e}) Bad Request.",
        "At C:\\acme\\acme-{word}.ps1:{i} char:{m}",
        "+ Invoke-AcmeUpload -Shard {j:02d} -Endpoint https://acme-{ip}:{port}/v2/upload",
        "    + CategoryInfo          : InvalidOperation: (:) [Write-Error], WriteErrorException"],
       ["PS C:\\acme> exit {e}"],
       ("STEP,LEVEL,MSG", "{i},Error,acme-{word}-{j:02d}", "powershell -File acme-{word}-{sel:02d}.ps1"), "shell-transcript"),
    _F("k6", "structured", "the k6 summary", "k6 run --summary-export out.json acme-{word}.js",
       ["  execution: local", "     script: acme-{word}.js", "     output: -", "",
        "  scenarios: (100.00%) 1 scenario, {n} max VUs, 1m30s max duration"],
       ["     ✓ {word} status is 200",
        "     checks.........................: {cpu}.{mem}% ✓ {n}    ✗ {i3}",
        "     http_req_duration..............: avg={ms}ms min={i}ms med={ms}ms max={c}ms"],
       ["     ✓ {word} 状态为 200",
        "     checks.........................: {cpu}.{mem}% ✓ {n}    ✗ {i3}"],
       ["     ✗ {word} checkout returns 201",
        "     checks.........................: {cpu}.{mem}% ✓ {n}    ✗ {e}",
        "     http_req_failed................: {cpu}.{mem}%   ✓ {e}    ✗ {i}"],
       ["running (1m{m}.{i}s), {n}/{n} VUs, {c} complete and 0 interrupted iterations"],
       ("METRIC,AVG,P95,MAX", "acme-{word}-{j:02d}_duration,{ms}ms,{c}ms,{n}ms", "k6 run acme-{word}-{sel:02d}.js"), "bench-summary"),
    _F("wrk", "structured", "the wrk benchmark", "wrk -t4 -c{n} -d30s http://{ip}:{port}/acme/{word}",
       ["Running 30s test @ http://{ip}:{port}/acme/{word}", "  4 threads and {n} connections"],
       ["  Thread Stats   Avg      Stdev     Max   +/- Stdev",
        "    Latency    {ms}.00ms  {i}.{j}ms   {c}.{i}ms   {cpu}.{mem}%",
        "    Req/Sec    {m}.{i}k     {n}.{i}k    {c}.{j}k    {cpu}.{mem}%"],
       ["  线程统计   均值      标准差    最大值   偏差",
        "    延迟      {ms}.00ms  {i}.{j}ms   {c}.{i}ms   {cpu}.{mem}%"],
       ["  Socket errors: connect 0, read {i}, write 0, timeout {e}",
        "  Non-2xx or 3xx responses: {e}"],
       ["  {n} requests in 30.0{m}s, {c}.{i}MB read"],
       ("STAT,AVG,STDDEV,MAX", "acme-{word}-{j:02d},{ms}ms,{i}ms,{c}ms", "wrk -t4 -c{n} http://{ip}:{port}/acme-{word}-{sel:02d}"), "bench-summary"),
    _F("strace", "trace", "the strace capture", "strace -f -tt -o /tmp/acme.trace /opt/acme/bin/{word}-worker",
       ["{ts} acme-{word}({pid}) [pid {pid}] execve(\"/opt/acme/bin/{word}-worker\", [\"{word}-worker\", \"--shard\", \"{j:02d}\"], 0x{uuid}) = 0"],
       ["{ts} openat(AT_FDCWD, \"/etc/acme/{word}/conf{j:02d}.yaml\", O_RDONLY) = 3",
        "{ts} read(3, \"shard: {j:02d}\\n\", {m}) = {i40}",
        "{ts} futex(0x{uuid}, FUTEX_WAIT_PRIVATE, {i}, NULL) = 0"],
       ["{ts} openat(AT_FDCWD, \"/etc/acme/{word}/conf{j:02d}.yaml\", O_RDONLY) = 3",
        "{ts} read(3, \"分片: {j:02d}\\n\", {m}) = {i40}"],
       ["{ts} connect(4, {{sa_family=AF_INET, sin_port=htons({port}), sin_addr=inet_addr(\"{ip}\")}}, 16) = -1 ECONNREFUSED",
        "{ts} write(2, \"acme-{word}: connect failed errno={e}\\n\", {m}) = {m}",
        "{ts} exit_group({e})                          = ?"],
       ["{ts} +++ exited with {e} +++"],
       ("NR,CALL,ARGS,RET", "{j:02d},openat,/etc/acme-{word}-{j:02d}.conf,3", "strace -f -e trace=%file -o acme-{word}-{sel:02d}.trace"), "syscall-trace"),
    _F("perf", "structured", "the perf report", "perf report --stdio -i perf-{word}.data",
       ["# Total Lost Samples: {i}", "# Samples: {n}K of event 'cpu-clock:pppH'", "# Event count (approx.): {n}{m}"],
       ["  {cpu}.{mem}%  acme-{word}  lib{word}.so.{ver}    [.] {word}_parse_{j:02d}",
        "  {cpu}.{mem}%  acme-{word}  [kernel.kallsyms]     [k] __x64_sys_epoll_wait"],
       ["  {cpu}.{mem}%  acme-{word}  lib{word}.so.{ver}    [.] {word}_解析_{j:02d}"],
       ["  {cpu}.{mem}%  acme-{word}  lib{word}.so.{ver}    [.] {word}_flush_dirty_{j:02d}",
        "  {e}.{i}%   acme-{word}  libc.so.6               [.] __memcpy_avx_unaligned_erms",
        "Warning: kernel symbols for acme-{word} build {ver} could not be resolved"],
       ["#"],
       ("OVERHEAD,CMD,OBJ,SYM", "{cpu}.{mem}%,acme-{word}-{j:02d},lib{word}.so,{word}_fn", "perf report -i perf-acme-{word}-{sel:02d}.data"), "profile-table"),
    _F("airflow", "log", "the airflow task log", "airflow tasks logs acme_{word}_dag {word}_extract {ts}",
       ["[{ts}] {{taskinstance.py:1049}} INFO - Dependencies all met for ti=<TaskInstance: acme_{word}_dag.{word}_extract {ts}>",
        "[{ts}] {{taskinstance.py:1319}} INFO - Starting attempt {i3p} of 3"],
       ["[{ts}] {{acme_{word}.py:{m}}} INFO - shard {j:02d} pulled {n} rows in {ms} ms",
        "[{ts}] {{local_task_job_runner.py:225}} INFO - heartbeat ok {uuid}"],
       ["[{ts}] {{acme_{word}.py:{m}}} 信息 - 分片 {j:02d} 拉取 {n} 行，用时 {ms} 毫秒"],
       ["[{ts}] {{acme_{word}.py:{m}}} ERROR - shard {j:02d} upload failed: HTTP {e} from upload-{host}",
        "Traceback (most recent call last):",
        "  File \"/opt/acme/{word}/hook.py\", line {m}, in upload",
        "acme.{word}.UploadError: batch {uuid} rejected: checksum mismatch"],
       ["[{ts}] {{local_task_job_runner.py:341}} ERROR - Task failed with exception"],
       ("TS,LEVEL,STEP,MSG", "{ts},INFO,acme-{word}-{j:02d},ok", "airflow tasks logs acme_{word}_dag acme-{word}-{sel:02d} {ts}"), "task-log"),
    _F("spark", "log", "the spark driver log", "spark-submit --master yarn acme-{word}.jar",
       ["{ts} INFO  yarn.Client: Submitting application application_{n}_{i:04d}",
        "{ts} INFO  scheduler.DAGScheduler: Registering RDD {j} (acme-{word}-stage-{j:02d})"],
       ["{ts} INFO  scheduler.TaskSetManager: Finished task {i}.{j} in stage {n}.0 (TID {pid}) in {ms} ms on {host}",
        "{ts} INFO  storage.BlockManagerInfo: Added broadcast_{j}_piece{j:02d} in memory on {host}:{port}"],
       ["{ts} 信息  调度器: 分片 {j:02d} 已完成，耗时 {ms} 毫秒"],
       ["{ts} ERROR scheduler.TaskSetManager: Task {i}.{j} in stage {n}.0 failed 4 times; aborting job",
        "org.apache.spark.SparkException: Job aborted due to stage failure: acme-{word} shard {j:02d} lost",
        "Caused by: java.io.IOException: Connection reset by {host}:{port}"],
       ["{ts} INFO  yarn.Client: Application report for application_{n}_{i:04d} (state: FAILED)"],
       ("STAGE,STATE,MS,NODE", "acme-{word}-{j:02d},FAILED,{ms},{host}", "spark-submit acme-{word}-{sel:02d}.jar"), "driver-log"),
    _F("nomad", "structured", "the nomad alloc status", "nomad alloc status {uuid}",
       ["ID                  = {uuid}", "Eval ID             = {uuid}", "Name                = acme-{word}.worker[{i5}]", "Node ID             = {uuid}"],
       ["Task \"acme-{word}-{j:02d}\" is \"running\"", "Task Events:", "Started At          = {ts}",
        "Finished At         = N/A"],
       ["任务 \"acme-{word}-{j:02d}\" 状态 \"运行中\"", "任务事件:", "启动时间           = {ts}"],
       ["Task \"acme-{word}-{j:02d}\" is \"dead\"", "Task Events:",
        "Killed              = task exited with code {e}",
        "Finished At         = {ts}"],
       ["Placement Metrics", "  * Score \"acme-{word}.bin-pack\" = {cpu}.{mem}"],
       ("TASK,STATE,AT", "acme-{word}-{j:02d},dead,{ts}", "nomad alloc status acme-{word}-{sel:02d}"), "alloc-status"),
    _F("consul", "structured", "the consul members call", "consul members -detailed",
       ["Datacenter: dc1", "Partition: default"],
       ["Node                    Address          Status  Type    Build   Protocol  DC   Partition Segment",
        "acme-{word}-{j:02d}            {ip}:{port}    alive   server  {ver}  2         dc1  default   <all>"],
       ["节点                    地址             状态   类型    版本    协议    DC   分区   段",
        "acme-{word}-{j:02d}            {ip}:{port}    正常    server  {ver}  2         dc1  default   <all>"],
       ["acme-{word}-{j:02d}            {ip}:{port}    failed  server  {ver}  2         dc1  default   <all>",
        "acme-{word}-{j:02d}            {ip}:{port}    left    server  {ver}  2         dc1  default   <all>"],
       ["Node                    Address          Status  Type    Build   Protocol  DC   Partition Segment"],
       ("NODE,ADDR,STATUS,TYPE", "acme-{word}-{j:02d},{ip},failed,server", "consul members | grep acme-{word}-{sel:02d}"), "member-table"),
    _F("latexlog", "log", "the LaTeX build log", "latexmk -pdf acme-{word}.tex",
       ["This is pdfTeX, Version 3.141592653-2.6-1.40.{i} (TeX Live 2026) (preloaded format=pdflatex)",
        "entering extended mode", "(./acme-{word}.tex", "LaTeX2e <2026-06-01>"],
       ["({m}) [1{i} <./figs/{word}-{j:02d}.pdf>] [2{i}]", "Chapter {i8}.", "({m})"],
       ["({m}) [第{i}页 <./figs/{word}-{j:02d}.pdf>]"],
       ["! Undefined control sequence.", "l.{m} \\acme{word}value",
        "The control sequence at the end of the top line", "of your error message was never \\def'ed."],
       ["Output written on acme-{word}.pdf ({i} pages, {n}00 bytes)."],
       ("FILE,LINE,ERR", "acme-{word}-{j:02d}.tex,{m},undefined", "latexmk -pdf acme-{word}-{sel:02d}.tex"), "tex-log"),
    _F("unitylog", "log", "the Unity editor log", "tail -n 400 Editor.log",
       ["Initialize engine version: {ver}f{i}", "[Subsystems] Discovering subsystems at path Library/PackageCache",
        "acme-{word}: registered importer for .acme-{j:02d}"],
       ["acme-{word}: baked lightmap {j:02d} in {ms} ms (memory {m} MB)",
        "acme-{word}: scene {j:02d} serialized {n} objects"],
       ["acme-{word}: 烘焙光照贴图 {j:02d}，用时 {ms} 毫秒（内存 {m} MB）"],
       ["Scripts have compiler errors.", "Assets/Acme/{word}/Builder.cs({i},{m}): error CS1002: ; expected",
        "Compilation failed: {e} error(s) generated"],
       ["[AssetDatabase] Refresh: detecting changes", "Total cache size {n} MB"],
       ("FILE,LINE,ERR", "acme-{word}-{j:02d}.cs,{i},CS{n}", "tail -n 400 acme-{word}-{sel:02d}-Editor.log"), "editor-log"),
    _F("ffmpeg", "structured", "the ffmpeg probe", "ffmpeg -i acme-{word}-{j:02d}.mp4 -f null -",
       ["ffmpeg version {ver} Copyright (c) 2000-2026 the FFmpeg developers",
        "Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'acme-{word}-{j:02d}.mp4':"],
       ["  Stream #0:{i3}[0x{j:02d}](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p, 1920x1080, {n} kb/s",
        "frame= {n} fps={cpu} q={mem}.0 size=    {m}KiB time=00:00:{i:02d}.{j:02d} bitrate={c}.{i}kbits/s speed={cpu}x"],
       ["  流 #0:{i3}(und): 视频: h264 (High), yuv420p, 1920x1080, {n} kb/s"],
       ["acme-{word}-{j:02d}.mp4: corrupt decoded frame in stream 0",
        "Error while decoding stream #0:0: Invalid data found when processing input",
        "frame= {n} fps={cpu} q=28.0 Lsize=    {m}KiB time=00:00:{i:02d}.{j:02d} bitrate={c}.{i}kbits/s"],
       ["video:{m}KiB audio:{c}KiB subtitle:0KiB other streams:0KiB"],
       ("STREAM,CODEC,KBS,FPS", "acme-{word}-{j:02d},h264,{n},{cpu}", "ffmpeg -i acme-{word}-{sel:02d}.mp4 -f null -"), "media-probe"),
    _F("openssl", "structured", "the openssl s_client check", "openssl s_client -connect {ip}:443 -servername acme-{word}.example",
       ["CONNECTED(00000003)", "depth=2 C = US, O = Acme Root CA, CN = Acme Root R{i}", "verify return:1"],
       ["---", "Certificate chain", " {i} s:C = US, O = Acme, CN = acme-{word}-{j:02d}.example",
        "   i:C = US, O = Acme Intermediate, CN = Acme TLS I{i}",
        "-----BEGIN CERTIFICATE-----", "MIIF{uuid}"],
       ["---", "证书链", " {i} 主题:C = CN, O = Acme, CN = acme-{word}-{j:02d}.example",
        "   签发者:C = US, O = Acme Intermediate, CN = Acme TLS I{i}"],
       ["{ts}:error:{uuid}:SSL routines:tls_process_server_certificate:certificate verify failed:ssl/statem/statem_clnt.c:{n}:",
        "Verify return code: {e} (certificate has expired)"],
       ["    Timeout   : {ms} (ms)", "    Verify return code: 0 (ok)"],
       ("FIELD,VALUE", "acme-{word}-{j:02d},{e}", "openssl s_client -connect acme-{word}-{sel:02d}.example:443"), "tls-probe"),
    _F("puppet", "log", "the puppet agent run", "puppet agent --test --environment acme_{word}",
       ["Info: Using environment 'acme_{word}'", "Info: Retrieving pluginfacts", "Info: Retrieving plugin"],
       ["Notice: /Stage[main]/Acme::{word}/File[/etc/acme-{word}/conf{j:02d}.yaml]/content: content changed '{uuid}' to '{uuid}'",
        "Notice: /Stage[main]/Acme::{word}/Service[acme-{word}-{j:02d}]/ensure: ensure changed 'stopped' to 'running'"],
       ["Notice: /Stage[main]/Acme::{word}/Service[acme-{word}-{j:02d}]/ensure: 状态由 '已停止' 变为 '运行中'"],
       ["Error: /Stage[main]/Acme::{word}/Exec[acme-{word}-seed]/returns: change from 'notrun' to '0' failed: Command exceeded timeout",
        "Error: Systemd start for acme-{word} failed!"],
       ["Notice: Applied catalog in {ms}.{i} seconds"],
       ("STAGE,RESOURCE,CHANGE", "main,acme-{word}-{j:02d},content", "puppet agent --test --tags acme-{word}-{sel:02d}"), "agent-log"),
    _F("zpool", "structured", "the zpool status report", "zpool status acme-{word}",
       ["  pool: acme-{word}", " state: ONLINE", "  scan: scrub repaired 0B in {c}:{m}:{i10} with 0 errors on {ts}",
        "config:", "", "\tNAME        STATE     READ WRITE CKSUM", "\tacme-{word}  ONLINE       0     0     0"],
       ["\t  raidz1-{i4}  ONLINE       0     0     0", "\t    acme-{word}-{j:02d}  ONLINE       0     0     0",
        "\t  mirror-{i4}   ONLINE       0     0     0"],
       ["\t  raidz1-{i4}  在线         0     0     0", "\t    acme-{word}-{j:02d}  在线         0     0     0"],
       ["\t    acme-{word}-{j:02d}  FAULTED      {n}     {m}     {e}  too many errors",
        " state: DEGRADED", "status: One or more devices are faulted in response to persistent errors."],
       ["errors: No known data errors"],
       ("NAME,STATE,READ,WRITE,CKSUM", "acme-{word}-{j:02d},ONLINE,0,0,0", "zpool status acme-{word}-{sel:02d}"), "pool-status"),
    _F("dig", "structured", "the dig answer", "dig @{ip} acme-{word}.example",
       ["; <<>> DiG 9.18.{i4} <<>> @{ip} acme-{word}.example", ";; global options: +cmd",
        ";; Got answer:", ";; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: {n}"],
       [";; QUESTION SECTION:", ";acme-{word}-{j:02d}.example.\t\tIN\tA",
        ";; ANSWER SECTION:", "acme-{word}-{j:02d}.example.\t300\tIN\tA\t{ip}"],
       [";; 问题段:", ";acme-{word}-{j:02d}.example.\t\tIN\tA",
        ";; 应答段:", "acme-{word}-{j:02d}.example.\t300\tIN\tA\t{ip}"],
       [";; ->>HEADER<<- opcode: QUERY, status: SERVFAIL, id: {n}",
        ";; connection timed out; no servers could be reached"],
       [";; Query time: {ms} msec", ";; SERVER: {ip}#53({ip})", ";; WHEN: {ts}", ";; MSG SIZE  rcvd: {m}"],
       ("NAME,TTL,CLASS,TYPE,RDATA", "acme-{word}-{j:02d}.example,300,IN,A,{ip}", "dig @{ip} acme-{word}-{sel:02d}.example"), "dns-answer"),
    _F("smartctl", "structured", "the smartctl report", "smartctl -a /dev/sd{word}",
       ["smartctl {ver} [build {uuid}] (local build)", "Copyright (C) 2002-26, Bruce Allen",
        "=== START OF INFORMATION SECTION ===", "Device Model:     ACME-{word}-{n}", "Serial Number:    {uuid}"],
       ["ID# ATTRIBUTE_NAME          FLAG     VALUE WORST THRESH TYPE      UPDATED  WHEN_FAILED RAW_VALUE",
        "  {i:3d} acme-{word}-{j:02d}        0x0033   100   100   010    Pre-fail  Always       -       {m}"],
       ["ID# 属性名称          标志     当前值 最差值 阈值  类型      更新    失败时间 原始值",
        "  {i:3d} acme-{word}-{j:02d}        0x0033   100   100   010    预失效  总是       -       {m}"],
       ["=== START OF READ SMART DATA SECTION ===",
        "SMART overall-health self-assessment test result: FAILED!",
        "  {i:3d} Reallocated_Sector_Ct   0x0033   0{m}   0{m}   010    Pre-fail  Always   FAILING_NOW   {n}"],
       ["SMART Health Status: OK"],
       ("ID,ATTR,VALUE,WORST,RAW", "{i},acme-{word}-{j:02d},100,100,{m}", "smartctl -a /dev/acme-{word}-{sel:02d}"), "smart-attrs"),
    _F("tcpdump", "log", "the tcpdump capture", "tcpdump -nn -i eth0 host acme-{word}",
       ["tcpdump: verbose output suppressed, use -v or -vv for full protocol decode",
        "listening on eth0, link-type EN10MB (Ethernet), capture size 262144 bytes"],
       ["{ts} IP {ip}.{port} > {ip}.443: Flags [P.], seq {n}:{m}, ack {c}, win {m}, length {i}",
        "{ts} IP {ip}.443 > {ip}.{port}: Flags [.], ack {c}, win {m}, length 0"],
       ["{ts} IP {ip}.{port} > {ip}.443: 标志 [P.], seq {n}:{m}, ack {c}, win {m}, 长度 {i}"],
       ["{ts} IP {ip}.{port} > {ip}.443: Flags [R.], seq 0, ack {n}, win 0, length 0",
        "{ts} IP {ip}.{port} > {ip}.443: Flags [F.], seq {n}, ack {m}, win {c}, length 0",
        "tcpdump: pcap_loop: an interface has gone down"],
       ["{n} packets captured", "{m} packets received by filter", "{e} packets dropped by kernel"],
       ("TS,SRC,DST,FLAGS,LEN", "{ts},{ip},acme-{word}-{j:02d}.example,P,{m}", "tcpdump -nn host acme-{word}-{sel:02d}"), "packet-trace"),
]

SRC_PLAN = [("evidence", "en"), ("evidence", "en"), ("evidence", "en"), ("evidence", "mixed"),
            ("s5_buried", "en"), ("s5_buried", "en"), ("s5_buried", "zh"), ("s5_buried", "zh"),
            ("s5_superseded", "en"), ("csv_args", "en"), ("csv_args", "en")]
_VARIANTS = {"evidence": "ab", "s5_buried": "ab", "s5_superseded": "a", "csv_args": "a"}
FAMILY_IDS = [f["id"] for f in FAMILIES]


def _assign_line(r, fmt_i, key, key_zh, value, zh):
    """One non-error assignment line, cycled across the required surface forms."""
    if zh:
        return r.choice([f"# 配置 {key_zh}: {value}", f"{key_zh} = {value}", f"配置项 {key_zh} -> {value}"])
    if fmt_i % 4 == 0:
        return f"{key}={value}"
    if fmt_i % 4 == 1:
        return f"{key}: {value}"
    if fmt_i % 4 == 2:
        return f"{key} -> {value}"
    return '{"level":"info","msg":"' + f"{key}={value}" + '"}'


_TRANSCRIPT = None


def _this_checkout_build_query():
    """``build_query`` of THIS checkout's tameru (1.10.0) even when another engine's src is on sys.path —
    e.g. the 1.9.0 descriptor worktree, whose transcript.py has no build_query."""
    return _this_checkout_transcript().build_query


def _this_checkout_transcript():
    """THIS checkout's ``tameru.transcript`` module (see ``_this_checkout_build_query``)."""
    global _TRANSCRIPT
    if _TRANSCRIPT is None:
        src = str(Path(__file__).resolve().parents[2] / "src")
        saved_path = list(sys.path)
        saved_mods = {k: v for k, v in sys.modules.items() if k == "tameru" or k.startswith("tameru.")}
        for k in saved_mods:
            sys.modules.pop(k, None)
        try:
            sys.path.insert(0, src)
            import tameru.transcript as tt  # noqa: PLC0415
            assert str(Path(tt.__file__).resolve()).startswith(src), tt.__file__
            _TRANSCRIPT = tt
        finally:
            sys.path[:] = saved_path
            for k in [k for k in sys.modules if k == "tameru" or k.startswith("tameru.")]:
                sys.modules.pop(k, None)
            sys.modules.update(saved_mods)
    return _TRANSCRIPT


def _build_q(user_msg: str, tool: str, text: str, *, selector: bool = False) -> str:
    """The engine's own ``build_query`` (or ``build_selector_query`` when ``selector``) over a
    synthetic transcript [user task, assistant terminal call running ``tool``, tool result = the
    case text] — how both plugins actually query the engine."""
    messages = [
        {"role": "user", "content": user_msg},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "terminal", "arguments": {"command": tool}}}]},
        {"role": "tool", "tool_call_id": "c1", "content": text},
    ]
    tt = _this_checkout_transcript()
    fn = getattr(tt, "build_selector_query", None) if selector else tt.build_query
    return (fn or tt.build_query)(messages, 2)


def _queries(cid, lang, thing, tool, key=None, key_zh=None):
    r = rng(cid + ":q")
    if key:
        sp_en = f"the output assigns a value to {key} — what is it?"
        sp_zh = f"输出中 {key_zh} 被赋了什么值？"
    else:
        sp_en = f"what error or failure ended {thing}?"
        sp_zh = f"{thing} 的运行最后报了什么错误？"
    vague = r.choice(_VAGUE_ZH if lang == "zh" else (_VAGUE_ZH if lang == "mixed" else _VAGUE_EN))
    if lang == "en":
        specific = sp_en
    else:
        specific = sp_zh
    q = {"task_specific": specific, "task_vague": vague, "tool_call": tool, "generic": GENERIC_QUERY}
    if lang in ("zh", "mixed"):
        q["zh_user"] = r.choice(_ZH_USER)
    return q


def _lines(r, templates, count, n, rid):
    return [templates[i % len(templates)].format(**_p(r, i, n, rid)) for i in range(count)]


def _evidence(r, spec, n, rid, variant, zh=False):
    noise = _lines(r, spec["fill_zh" if zh else "fill"], 40 + r.randint(0, 50) if variant == "a" else 110 + r.randint(0, 120), n, rid)
    err = [t.format(**_p(r, 90 + i, n, rid)) for i, t in enumerate(spec["err"])]
    tail = [t.format(**_p(r, 97 + i, n, rid)) for i, t in enumerate(spec["tail"])]
    head = [t.format(**_p(r, 0, n, rid)) for t in spec["head"]]
    if variant == "a":
        lines = head + noise + err + tail
    else:
        lines = head + noise[: len(noise) // 2] + err + noise[len(noise) // 2:] + tail
    return lines, [err[0], tail[-1]], None, []


def _buried(r, spec, src_i, n, rid, variant, zh):
    key_en, key_zh = _KEYS[(src_i + n) % len(_KEYS)]
    value = str(n * 3 + src_i + 1)
    line = _assign_line(r, src_i + n, key_en, key_zh, value, zh)
    count = (45 + r.randint(0, 50)) if variant == "a" else (120 + r.randint(0, 130))
    noise = _lines(r, spec["fill_zh" if zh else "fill"], count, n, rid)
    head = [t.format(**_p(r, 0, n, rid)) for t in spec["head"]]
    at = len(head) + (count * r.randint(30, 70) // 100)
    lines = head + noise[:at - len(head)] + [line] + noise[at - len(head):]
    fact = {"key": key_zh if zh else key_en, "value": value, "line": line}
    return lines, [line], fact, []


def _superseded(r, spec, n, rid, variant, zh):
    key_en, key_zh = _KEYS[(n + 5) % len(_KEYS)]
    key, keyz = (key_zh, key_zh) if zh else (key_en, key_zh)
    stale_v, new_v = str(n), str(n * 7 + 3)
    stale = f"{key}: {stale_v}"
    newest = f"{key}: {new_v}"
    noise = _lines(r, spec["fill_zh" if zh else "fill"], 90 + r.randint(0, 80), n, rid)
    head = [t.format(**_p(r, 0, n, rid)) for t in spec["head"]]
    mid = len(head) + len(noise) // 3
    lines = head + noise[:mid - len(head)] + [stale] + noise[mid - len(head): 2 * (mid - len(head))] + [newest] + noise[2 * (mid - len(head)):]
    fact = {"key": key, "value": new_v, "line": newest}
    return lines, [newest], fact, [stale]


def _csv_args(r, spec, src_i, n, rid, variant, zh):
    key_en, _ = _KEYS[(src_i + n + 2) % len(_KEYS)]
    value = str(n + 40 + src_i)
    header, row_tpl, tool_tpl = spec["csv"]
    w = _WORDS[(n + src_i) % len(_WORDS)]

    def rp(i):
        p = _p(r, i, n, rid)
        p["word"] = w
        return p

    rows = [row_tpl.format(**rp(j)) for j in range(30 + r.randint(0, 40))]
    sel = r.randint(3, min(len(rows) - 2, 22))
    # The token acme-<w>-<sel> is a CSV value (row ``sel``'s id column) and also an arg of the tool call.
    line = f"{key_en}: {value}" if src_i % 2 else f"{key_en}={value}"
    at = 8 + r.randint(0, len(rows) - 8)
    head = [t.format(**_p(r, 0, n, rid)) for t in spec["head"]]
    lines = head + [header] + rows[:at] + [line] + rows[at:]
    tool = tool_tpl.format(sel=sel, **rp(0))
    fact = {"key": key_en, "value": value, "line": line}
    return lines, [line], fact, [], tool


def _source_case(fid, spec, src, variant, prefix="r2"):
    """One case dict of (family, source index, variant)."""
    kind, lang = SRC_PLAN[src]
    cid = f"{prefix}-{fid}-{src:02d}{variant}"
    r, c = rng(cid), rng(f"{prefix}c-{fid}-{src}")
    n, rid = c.randint(100, 999), hexid(c, 6)
    zh = lang == "zh"
    tool = spec["tool"].format(**_p(c, 0, n, rid))
    fact, forbidden = None, []
    if kind == "evidence":
        lines, gold, fact, forbidden = _evidence(r, spec, n, rid, variant, zh)
    elif kind == "s5_buried":
        lines, gold, fact, forbidden = _buried(r, spec, src, n, rid, variant, zh)
    elif kind == "s5_superseded":
        lines, gold, fact, forbidden = _superseded(r, spec, n, rid, variant, zh)
    else:
        lines, gold, fact, forbidden, tool = _csv_args(r, spec, src, n, rid, variant, zh)
    key, key_zh = (fact["key"], fact["key"]) if fact else (None, None)
    text = "\n".join(lines)
    q = _queries(cid, lang, spec["thing"].format(**_p(c, 0, n, rid)), tool, key, key_zh)
    q["build_specific"] = _build_q(q["task_specific"], tool, text)
    q["build_vague"] = _build_q(q["task_vague"], tool, text)
    case = {"id": cid, "source_case": f"{prefix}-{fid}-{src:02d}", "content_type": spec["ctype"], "shape": f"{prefix}-{fid}",
            "text": text, "gold": gold, "forbidden": forbidden,
            "language": lang, "queries": q,
            # 1.10.0 (S5): the same transcripts through build_selector_query — run.py passes them as
            # compress_context(..., selector_query=...) when the engine under test accepts the
            # parameter, so destructive pre-filters cannot key on the producing call's terms.
            "sel_queries": {
                "build_specific": _build_q(q["task_specific"], tool, text, selector=True),
                "build_vague": _build_q(q["task_vague"], tool, text, selector=True),
            },
            "family": fid, "item_kind": kind}
    if fact:
        case["fact"] = fact
    return case


def generated_cases_r2() -> list[dict]:
    """Every r2 case, deterministic. Two calls return byte-identical lists."""
    out = []
    for spec in FAMILIES:
        for src in range(len(SRC_PLAN)):
            for v in _VARIANTS[SRC_PLAN[src][0]]:
                out.append(_source_case(spec["id"], spec, src, v))
    return out
