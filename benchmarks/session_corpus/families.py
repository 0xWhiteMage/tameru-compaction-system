"""Family registry and the line-template engine of the session corpus.

A family is one kind of agent session (a tool and the outputs it prints): its tool calls, filler line templates
(English and Chinese), natural fact shapes (failing tests, versions, error codes, counts, config assignments), the
S5 buried singleton assignment shape that hides inside repetitive filler, its error block, typical output size, and
the user messages of a specific task (names the keys) and a vague task (names none).

Templates are plain strings with ``{name}`` placeholders.  ``key`` and ``value`` are filled by the generator; every
other name is a generator in ``G`` that draws from the ``random.Random`` it is given (no clock, no global state).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from random import Random
from typing import Callable

# ------------------------------------------------------------------------------------------------ vocabulary
WORDS = ("payment", "checkout", "inventory", "session", "billing", "search", "upload", "gateway", "router", "cache",
         "auth", "ledger", "report", "export", "scheduler", "notify", "profile", "catalog", "pricing", "shipping",
         "invoice", "audit", "metrics", "webhook", "tenant", "quota", "storage", "media", "orders", "refund")
VERBS = ("creates", "updates", "rejects", "retries", "expires", "renders", "parses", "merges", "flushes", "rolls_back",
         "times_out", "validates", "serializes", "migrates", "evicts", "streams")
SETTINGS = ("timeout_ms", "retries", "pool_size", "max_conns", "ttl_ms", "batch_size", "region", "replicas", "workers",
            "quota", "window_s", "backoff_ms", "page_size", "shard_count", "flush_interval", "max_body_kb")
UNITS = ("ms", "s", "mb", "kb", "x", "")
PKGS = ("requests", "urllib3", "pydantic", "fastapi", "sqlalchemy", "numpy", "pandas", "protobuf", "grpcio", "celery",
        "redis", "boto3", "jinja2", "lodash", "express", "react", "axios", "webpack", "typescript", "eslint", "zod",
        "prisma", "vite", "rollup", "tokio", "serde", "hyper", "clap", "anyhow", "reqwest", "spring-core", "jackson-databind",
        "guava", "netty-handler", "log4j-core", "commons-io", "gin", "cobra", "zap", "testify")
ZH_WORDS = ("支付", "订单", "库存", "会话", "账单", "搜索", "上传", "网关", "路由", "缓存", "认证", "报表", "导出",
            "调度", "通知", "用户", "目录", "价格", "物流", "发票", "审计", "租户", "配额", "存储")
ZH_PHRASES = ("已完成", "正在处理", "处理成功", "已跳过", "已是最新版本", "连接正常", "校验通过", "正在下载", "写入完成",
              "等待重试", "任务已提交", "同步完成", "缓存命中", "无需变更", "健康检查通过", "已加载配置", "开始执行",
              "执行结束", "数据已刷新", "索引已重建")
NAMESPACES = ("default", "prod", "staging", "payments", "data", "infra", "web")
REASONS = ("CrashLoopBackOff", "OOMKilled", "ImagePullBackOff", "ErrImagePull", "CreateContainerConfigError", "Evicted")
SQLSTATES = ("23505", "40P01", "53300", "42P01", "22003", "57014", "08006", "42703", "23503", "25P02")
EXIT_CODES = ("1", "2", "126", "127", "137", "139", "143")
HTTP_ERR = ("400", "401", "403", "404", "409", "422", "429", "500", "502", "503", "504")
TF_TYPES = ("aws_s3_bucket", "aws_iam_role", "aws_lambda_function", "aws_security_group", "google_compute_instance",
            "azurerm_storage_account", "aws_rds_cluster", "aws_sqs_queue", "kubernetes_deployment", "aws_route53_record")
LEVELS = ("INFO",) * 6 + ("DEBUG",) * 3 + ("WARN",)


def _hex(r: Random, n: int) -> str:
    return f"{r.getrandbits(4 * n):0{n}x}"


def _ts(r: Random) -> str:
    return f"2026-11-{r.randrange(1, 28):02d}T{r.randrange(24):02d}:{r.randrange(60):02d}:{r.randrange(60):02d}.{r.randrange(1000):03d}Z"


def _cfgval(r: Random) -> str:
    k = r.randrange(3)
    if k == 0:
        return f"{r.randrange(10, 9000)}{r.choice(UNITS)}"
    if k == 1:
        return f"{r.choice(WORDS)}-{_hex(r, 4)}"
    return f"{r.randrange(1, 64)}.{r.randrange(10, 99)}"


G: dict[str, Callable[[Random], str]] = {
    "n": lambda r: str(r.randrange(10000)), "n2": lambda r: str(r.randrange(100)), "n3": lambda r: str(r.randrange(1000)),
    "n5": lambda r: str(r.randrange(100000)), "ms": lambda r: str(r.randrange(1, 2500)),
    "sec": lambda r: f"{r.random() * 30:.2f}", "pct": lambda r: str(r.randrange(101)),
    "hex": lambda r: _hex(r, 8), "hex4": lambda r: _hex(r, 4), "hex5": lambda r: _hex(r, 5), "hex12": lambda r: _hex(r, 12),
    "sha7": lambda r: _hex(r, 7), "sha40": lambda r: _hex(r, 40),
    "word": lambda r: r.choice(WORDS), "Word": lambda r: r.choice(WORDS).capitalize(), "verb": lambda r: r.choice(VERBS),
    "zw": lambda r: r.choice(ZH_WORDS), "zp": lambda r: r.choice(ZH_PHRASES),
    "ts": _ts, "time": lambda r: f"{r.randrange(24):02d}:{r.randrange(60):02d}:{r.randrange(60):02d}",
    "ip": lambda r: f"10.{r.randrange(256)}.{r.randrange(256)}.{r.randrange(1, 255)}",
    "pod": lambda r: f"{r.choice(WORDS)}-{_hex(r, 5)}-{_hex(r, 5)}", "ns": lambda r: r.choice(NAMESPACES),
    "level": lambda r: r.choice(LEVELS), "line": lambda r: str(r.randrange(1, 2400)), "col": lambda r: str(r.randrange(1, 120)),
    "status": lambda r: r.choice(("200",) * 9 + ("201", "204", "304")), "method": lambda r: r.choice(("GET",) * 4 + ("POST", "PUT", "DELETE")),
    "pkg": lambda r: r.choice(PKGS), "ver": lambda r: f"{r.randrange(10)}.{r.randrange(40)}.{r.randrange(30)}",
    "bytes": lambda r: str(r.randrange(100, 2_000_000)), "float": lambda r: f"{r.random() * 100:.3f}",
    "host": lambda r: f"{r.choice(WORDS)}-{r.randrange(1, 40):02d}", "setting": lambda r: r.choice(SETTINGS),
    "tftype": lambda r: r.choice(TF_TYPES), "user": lambda r: r.choice(("alice", "bob", "chen.wei", "li.na", "deploy-bot", "ci")),
    "Cls": lambda r: r.choice(WORDS).capitalize() + r.choice(("Service", "Handler", "Repository", "Client", "Worker", "Controller")),
    "fn": lambda r: f"{r.choice(WORDS)}_{r.choice(VERBS)}",
}

# keys: distinct per scenario (the generator redraws on a clash)
KG: dict[str, Callable[[Random], str]] = {
    "suite": lambda r: f"{r.choice(WORDS)}_{r.randrange(10, 99)}",
    "cfgkey": lambda r: f"{r.choice(WORDS)}.{r.choice(SETTINGS)}_{r.randrange(10, 99)}",
    "pkg": lambda r: f"{r.choice(PKGS)}",
    "module": lambda r: f"{r.choice(WORDS)}-{r.choice(('core', 'api', 'worker', 'client', 'common', 'web'))}",
    "resource": lambda r: f"{r.choice(TF_TYPES)}.{r.choice(WORDS)}_{r.randrange(10, 99)}",
    "pod": lambda r: f"{r.choice(WORDS)}-api-{_hex(r, 5)}",
    "file": lambda r: f"src/{r.choice(WORDS)}/{r.choice(WORDS)}_{r.randrange(10, 99)}",
    "metric": lambda r: f"{r.choice(WORDS)}_{r.choice(('p99_latency_ms', 'error_rate', 'qps', 'queue_depth', 'cpu_pct', 'heap_mb'))}",
    "table": lambda r: f"{r.choice(WORDS)}_{r.randrange(10, 99)}",
    "endpoint": lambda r: f"/api/v{r.randrange(1, 4)}/{r.choice(WORDS)}/{r.choice(WORDS)}",
    "job": lambda r: f"{r.choice(WORDS)}-{r.choice(VERBS).replace('_', '-')}",
    "host": lambda r: f"{r.choice(WORDS)}-{r.randrange(10, 99)}",
    "subject": lambda r: f"fix {r.choice(WORDS)} {r.choice(VERBS).replace('_', ' ')} on {r.choice(WORDS)} path",
    "section": lambda r: f"{r.choice(WORDS).capitalize()} {r.choice(('limits', 'rollout', 'retention', 'ownership', 'escalation', 'quotas'))}",
    "image": lambda r: f"registry.local/{r.choice(WORDS)}-{r.choice(('api', 'worker', 'web'))}",
}

# values: natural shapes
VG: dict[str, Callable[[Random], str]] = {
    "testname": lambda r: f"test_{r.choice(WORDS)}_{r.choice(VERBS)}_{r.randrange(100, 999)}",
    "count": lambda r: str(r.randrange(2, 97)), "ver": lambda r: f"{r.randrange(1, 10)}.{r.randrange(41)}.{r.randrange(31)}",
    "sha7": lambda r: _hex(r, 7), "hex": lambda r: _hex(r, 8), "cfgval": _cfgval,
    "tscode": lambda r: f"TS{r.randrange(2000, 2900)}", "cscode": lambda r: f"CS{r.randrange(100, 9999):04d}",
    "errno": lambda r: f"E{r.randrange(1000, 9999)}", "http": lambda r: r.choice(HTTP_ERR), "exit": lambda r: r.choice(EXIT_CODES),
    "sqlstate": lambda r: r.choice(SQLSTATES), "reason": lambda r: r.choice(REASONS),
    "dur": lambda r: f"{r.randrange(100, 99999)}ms", "num": lambda r: f"{r.randrange(1, 9999)}.{r.randrange(100, 999)}",
    "port": lambda r: str(r.randrange(1024, 65000)), "ip": G["ip"], "digest": lambda r: "sha256:" + _hex(r, 12),
    "user": lambda r: f"{r.choice(('ops', 'sre', 'dev', 'data'))}-{r.choice(('ana', 'bo', 'chen', 'dana', 'eli', 'fei'))}{r.randrange(10, 99)}",
    "javaex": lambda r: r.choice(("IllegalStateException", "NullPointerException", "SQLTransientConnectionException",
                                   "ConcurrentModificationException", "ClassCastException", "SocketTimeoutException")) + f"#{r.randrange(100, 999)}",
    "lineno": lambda r: str(r.randrange(20, 2400)),
    "npmmod": lambda r: f"@acme/{r.choice(WORDS)}-{_hex(r, 4)}",
    "npmcode": lambda r: r.choice(("ERESOLVE", "ETARGET", "EINTEGRITY", "ENOENT", "EACCES", "ECONNRESET", "E404")),
}

_PLACE = re.compile(r"\{(\w+)\}")


def compile_tpl(s: str) -> tuple:
    """-> tuple of (0, literal) | (1, generator) | (2, slot name)."""
    parts: list = []
    pos = 0
    for m in _PLACE.finditer(s):
        if m.start() > pos:
            parts.append((0, s[pos:m.start()]))
        name = m.group(1)
        parts.append((1, G[name]) if name in G else (2, name))
        pos = m.end()
    if pos < len(s):
        parts.append((0, s[pos:]))
    return tuple(parts)


def render(tpl: tuple, r: Random, fixed: dict | None = None) -> str:
    out = []
    for kind, p in tpl:
        out.append(p if kind == 0 else p(r) if kind == 1 else fixed[p])
    return "".join(out)


# ------------------------------------------------------------------------------------------------ family spec
@dataclass(frozen=True)
class Shape:
    """A fact line (or block): ``kind`` natural | error; ``lines`` en / zh templates (a block is a tuple of lines, the
    line holding {key}/{value} is the fact line)."""
    kind: str
    en: tuple
    zh: tuple
    key: str
    value: str
    q_en: str
    q_zh: str


@dataclass(frozen=True)
class Family:
    id: str
    tool: str
    args: dict
    fill_en: tuple
    fill_zh: tuple
    shapes: tuple
    buried_en: str
    buried_zh: str
    task_en: str
    task_zh: str
    vague_en: str
    vague_zh: str
    median_chars: int = 20000
    burned_round1: bool = False
    compiled: dict = field(default_factory=dict, compare=False, repr=False)

    def tpl(self, s: str) -> tuple:
        t = self.compiled.get(s)
        if t is None:
            t = self.compiled[s] = compile_tpl(s)
        return t


def S(kind, en, zh, key, value, q_en, q_zh) -> Shape:
    en = (en,) if isinstance(en, str) else tuple(en)
    zh = (zh,) if isinstance(zh, str) else tuple(zh)
    return Shape(kind, en, zh, key, value, q_en, q_zh)


def F(fid, tool, args, fill_en, fill_zh, shapes, buried, task, vague, median=20000, burned=False) -> Family:
    return Family(fid, tool, dict(args), tuple(fill_en), tuple(fill_zh), tuple(shapes), buried[0], buried[1], task[0], task[1],
                  vague[0], vague[1], median, burned)


Q_CFG = ("What value does {key} end up with?", "{key} 最终的取值是多少？")
BUR_EQ = ("# config {key}={value}", "# 配置 {key}={value}")
BUR_COLON = ("  setting {key}: {value}", "  配置项 {key}: {value}")
BUR_ARROW = ("override {key} -> {value}", "覆盖 {key} -> {value}")
BUR_JSON = ('{"level":"info","msg":"{key} = {value}"}', '{"level":"info","msg":"配置 {key} = {value}"}')

# ------------------------------------------------------------------------------------------------ families
FAMILIES: tuple[Family, ...] = (
    # ---- the eight round-1 families (burned holdout material): reproduced here, pinned to dev ----
    F("pytest", "bash", {"command": "pytest -q tests/{word} -x --maxfail=50"},
      ["tests/{word}/test_{word}_{n2}.py::test_{fn}[{n2}] PASSED [{pct}%]",
       "tests/{word}/test_{word}.py::Test{Word}::test_{verb} PASSED",
       "{word}/{word}_{n2}.py:{line}: DeprecationWarning: {word}.{fn}() is deprecated"],
      ["tests/{word}/test_{word}_{n2}.py::test_{fn}[{zw}-{n2}] PASSED [{pct}%]", "日志: {zp} {word}_{n3} 用时 {ms}ms"],
      [S("error", "FAILED tests/{key}/test_{word}.py::{value} - AssertionError: assert {n3} == {n3}",
         "FAILED tests/{key}/test_{word}.py::{value} - AssertionError: 断言失败 {n3} != {n3}", "suite", "testname",
         "Which test failed in the {key} suite?", "{key} 套件里哪个测试失败了？"),
       S("natural", "=========== {key}: {value} failed, {n3} passed, {n2} skipped in {sec}s ===========",
         "=========== {key}: {value} failed, {n3} passed, {n2} skipped in {sec}s (共 {n3} 项) ===========", "suite", "count",
         "How many tests failed in the {key} run?", "{key} 这次运行失败了多少个测试？")],
      BUR_EQ, ("Run the {family} tests and report {keys}.", "运行测试，并汇报 {keys}。"),
      ("Run the tests and tell me what is going wrong.", "跑一下测试，看看哪里不对。"), 18000, True),
    F("maven", "bash", {"command": "mvn -pl {word}-core test"},
      ["[INFO] Running com.acme.{word}.{Cls}Test", "[INFO] Tests run: {n2}, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: {sec} s - in com.acme.{word}.{Cls}Test",
       "[INFO] Downloaded from central: https://repo.maven.apache.org/maven2/org/{word}/{word}-{word}/{ver}/{word}-{ver}.jar ({n3} kB at {n3} kB/s)"],
      ["[INFO] 正在运行 com.acme.{word}.{Cls}Test {zp}", "[INFO] Tests run: {n2}, Failures: 0, Errors: 0, Skipped: 0, 用时 {sec} s"],
      [S("error", "[ERROR] Tests run: {n2}, Failures: 1, Errors: 0 <<< FAILURE! - in com.acme.{key}.{value}",
         "[ERROR] Tests run: {n2}, Failures: 1 <<< 失败! - in com.acme.{key}.{value}", "suite", "testname",
         "Which test class failed in package {key}?", "{key} 包里哪个测试类失败了？"),
       S("natural", "[INFO] {key} ............................ SUCCESS [ {value} ]", "[INFO] {key} ............ 成功 [ {value} ]",
         "module", "dur", "How long did module {key} take to build?", "模块 {key} 构建用了多长时间？")],
      BUR_COLON, ("Run the Maven build and report {keys}.", "执行 Maven 构建并汇报 {keys}。"),
      ("Build it with Maven and tell me what's broken.", "用 Maven 构建一下，看看什么坏了。"), 22000, True),
    F("kubectl", "kubectl_logs", {"pod": "{pod}", "namespace": "{ns}", "tail": "5000"},
      ['{"ts":"{ts}","level":"{level}","logger":"{word}.http","msg":"{method} /api/{word} {status}","latency_ms":{ms}}',
       '{"ts":"{ts}","level":"{level}","logger":"{word}.worker","msg":"processed batch {n5}","items":{n3}}'],
      ['{"ts":"{ts}","level":"{level}","logger":"{word}.worker","msg":"批次 {n5} {zp}","items":{n3}}',
       '{"ts":"{ts}","level":"{level}","logger":"{word}.http","msg":"{method} /api/{word} {status} {zp}"}'],
      [S("error", '{"ts":"{ts}","level":"ERROR","logger":"kubelet","msg":"pod {key} restarted","reason":"{value}"}',
         '{"ts":"{ts}","level":"ERROR","logger":"kubelet","msg":"容器 {key} 重启","reason":"{value}"}', "pod", "reason",
         "Why did pod {key} restart?", "{key} 这个 pod 为什么重启？"),
       S("natural", '{"ts":"{ts}","level":"INFO","logger":"deploy","msg":"rollout {key} image tag={value}"}',
         '{"ts":"{ts}","level":"INFO","logger":"deploy","msg":"发布 {key} 镜像 tag={value}"}', "pod", "sha7",
         "Which image tag did rollout {key} use?", "{key} 发布用的是哪个镜像 tag？")],
      BUR_JSON, ("Check the pod logs and report {keys}.", "看一下 pod 日志，汇报 {keys}。"),
      ("Look at the logs and figure out why the service is flaky.", "看看日志，服务为什么不稳定？"), 24000, True),
    F("sql", "sql_query", {"query": "SELECT * FROM {word}_events ORDER BY id DESC LIMIT 5000"},
      [" {n5} | {word} | {status} | {ts} | {float}", " {n5} | {word}_{verb} | ok | {ts} | {n3}"],
      [" {n5} | {zw} | {status} | {ts} | {float}", " {n5} | {zw}_{n2} | 正常 | {ts} | {n3}"],
      [S("natural", " {n5} | {key} | config | {ts} | {value}", " {n5} | {key} | 配置 | {ts} | {value}", "cfgkey", "cfgval",
         "What value is stored for {key}?", "{key} 存的值是多少？"),
       S("error", "ERROR:  duplicate key value violates unique constraint \"{key}_pkey\" (SQLSTATE {value})",
         "错误:  重复键违反唯一约束 \"{key}_pkey\" (SQLSTATE {value})", "table", "sqlstate",
         "Which SQLSTATE did the insert into {key} return?", "插入 {key} 返回的 SQLSTATE 是什么？")],
      BUR_COLON, ("Query the events table and report {keys}.", "查询事件表并汇报 {keys}。"),
      ("Have a look at the recent rows and tell me if anything is off.", "看看最近的数据有没有异常。"), 20000, True),
    F("jest", "bash", {"command": "npx jest --ci {word}"},
      ["PASS src/{word}/{word}.test.ts ({ms} ms)", "  ✓ {word} {verb} correctly ({ms} ms)", "    at Object.<anonymous> (src/{word}/{word}.test.ts:{line}:{col})"],
      ["PASS src/{word}/{zw}.test.ts ({ms} ms)", "  ✓ {zw}{zp} ({ms} ms)"],
      [S("error", "  ● {key} › {value}", "  ● {key} › {value}（断言失败）", "suite", "testname",
         "Which test failed in the {key} describe block?", "{key} 里哪个用例失败了？"),
       S("natural", "Tests:       {value} failed, {n3} passed, {n3} total ({key})", "Tests:       {value} failed, {n3} passed（{key}）",
         "suite", "count", "How many tests failed in {key}?", "{key} 失败了多少个用例？")],
      BUR_ARROW, ("Run jest and report {keys}.", "运行 jest 并汇报 {keys}。"),
      ("Run the frontend tests and see what's up.", "跑一下前端测试看看情况。"), 16000, True),
    F("gotest", "bash", {"command": "go test ./... -run {Word} -count=1"},
      ["=== RUN   Test{Word}{Word}/{word}_{n2}", "--- PASS: Test{Word}{Word}/{word}_{n2} ({sec}s)", "ok  \tgithub.com/acme/{word}/internal/{word}\t{sec}s"],
      ["=== RUN   Test{Word}/{zw}_{n2}", "--- PASS: Test{Word}/{zw}_{n2} ({sec}s) {zp}"],
      [S("error", "--- FAIL: {value} ({sec}s)\n    {key}_test.go:{line}: {value}: unexpected status", "--- FAIL: {value} ({sec}s)\n    {key}_test.go:{line}: {value}: 状态不符合预期",
         "suite", "testname", "Which Go test failed in {key}_test.go?", "{key}_test.go 里哪个测试失败了？"),
       S("natural", "coverage: {value}% of statements in github.com/acme/{key}", "覆盖率: {value}% github.com/acme/{key}", "module", "num",
         "What coverage did package {key} report?", "{key} 包的覆盖率是多少？")],
      BUR_EQ, ("Run go test and report {keys}.", "运行 go test 并汇报 {keys}。"),
      ("Run the Go tests and summarise problems.", "跑一下 Go 测试，总结问题。"), 18000, True),
    F("cargo", "bash", {"command": "cargo test --workspace"},
      ["test {word}::{word}::{fn} ... ok", "   Compiling {word}-{word} v{ver} (/work/crates/{word})", "test result: ok. {n2} passed; 0 failed; 0 ignored; finished in {sec}s"],
      ["test {word}::{fn} ... ok // {zp}", "   Compiling {word}-{word} v{ver} ({zp})"],
      [S("error", "test {key}::{value} ... FAILED", "test {key}::{value} ... FAILED（失败）", "suite", "testname",
         "Which test failed in module {key}?", "{key} 模块里哪个测试失败了？"),
       S("natural", "   Compiling {key} v{value}", "   Compiling {key} v{value}（编译中）", "pkg", "ver",
         "Which version of crate {key} was compiled?", "编译的 {key} 是哪个版本？")],
      BUR_ARROW, ("Run cargo test and report {keys}.", "运行 cargo test 并汇报 {keys}。"),
      ("Run the Rust tests and tell me what's wrong.", "跑一下 Rust 测试，看看有什么问题。"), 17000, True),
    F("metrics", "read_file", {"path": "exports/{word}_metrics.csv"},
      ["{ts},{host},{word}_qps,{n3}", "{ts},{host},{word}_p99_latency_ms,{ms}", "{ts},{host},{word}_error_rate,0.0{n2}"],
      ["{ts},{host},{zw}_qps,{n3}", "{ts},{host},{zw}_延迟_ms,{ms}"],
      [S("natural", "{ts},{host},{key},{value}", "{ts},{host},{key},{value}", "metric", "num",
         "What is the reading of {key}?", "{key} 的读数是多少？"),
       S("error", "{ts},{host},alert_{key},FIRING code={value}", "{ts},{host},告警_{key},FIRING code={value}", "metric", "errno",
         "Which alert code fired for {key}?", "{key} 触发的告警代码是什么？")],
      BUR_EQ, ("Read the metrics export and report {keys}.", "读取指标导出文件并汇报 {keys}。"),
      ("Look over the metrics and tell me what looks unhealthy.", "看看指标数据，有什么不健康的地方？"), 22000, True),
    # ---- other families ----
    F("gradle", "bash", {"command": "./gradlew :{word}:check --info"},
      ["> Task :{word}{n2}:compileJava UP-TO-DATE", "> Task :{word}:test", "[ant:checkstyle] [WARN] /src/main/java/com/acme/{word}/{Cls}.java:{line}:{col}: Line is longer than 120 characters."],
      ["> Task :{word}{n2}:compileJava UP-TO-DATE ({zp})", "[警告] /src/main/java/com/acme/{word}/{Cls}.java:{line}: 行长度超过 120"],
      [S("natural", "> Configure project :{key}  version = '{value}'", "> Configure project :{key}  版本 = '{value}'", "module", "ver",
         "Which version does project :{key} configure?", "项目 :{key} 配置的版本是多少？"),
       S("error", "{key}Test > {value} FAILED", "{key}Test > {value} FAILED（失败）", "suite", "testname",
         "Which test in {key}Test failed?", "{key}Test 里哪个测试失败了？")],
      BUR_EQ, ("Run the Gradle check and report {keys}.", "执行 Gradle 检查并汇报 {keys}。"),
      ("Run the build and tell me what's unstable.", "跑一下构建，看看哪里不稳定。")),
    F("dotnet", "bash", {"command": "dotnet test src/{Word}.Tests"},
      ["  Passed {Cls}Tests.{Word}_{verb} [{ms} ms]", "  Determining projects to restore...", "  {Word}.Core -> /src/{Word}.Core/bin/Debug/net8.0/{Word}.Core.dll"],
      ["  已通过 {Cls}Tests.{Word}_{verb} [{ms} ms]", "  正在确定要还原的项目... {zp}"],
      [S("error", "  Failed {key}Tests.{value} [{ms} ms]", "  失败 {key}Tests.{value} [{ms} ms]", "suite", "testname",
         "Which test failed in {key}Tests?", "{key}Tests 里哪个测试失败了？"),
       S("error", "/src/{key}.cs({line},{col}): error {value}: The type or namespace name could not be found",
         "/src/{key}.cs({line},{col}): error {value}: 未能找到类型或命名空间名", "file", "cscode",
         "Which compiler error code did {key}.cs raise?", "{key}.cs 报了哪个编译错误代码？")],
      BUR_COLON, ("Run the .NET tests and report {keys}.", "运行 .NET 测试并汇报 {keys}。"),
      ("Run dotnet test and see what's failing.", "跑一下 dotnet test，看看什么失败了。")),
    F("ansible", "ansible_playbook", {"playbook": "site_{n2}.yml", "limit": "{host}"},
      ["ok: [{host}] => (item={pkg})", "TASK [common : install packages {n2}] ***************************************",
       "changed: [{host}] => {\"changed\": true, \"rc\": 0}"],
      ["ok: [{host}] => (item={pkg}) {zp}", "TASK [common : 安装依赖 {n2}] ***************************", "changed: [{host}] => {\"changed\": true, \"msg\": \"已更新 {n3} 个文件\"}"],
      [S("error", "fatal: [{key}]: FAILED! => {\"msg\": \"non-zero return code\", \"rc\": {value}", "fatal: [{key}]: FAILED! => {\"msg\": \"返回码非零\", \"rc\": {value}",
         "host", "exit", "What return code did host {key} fail with?", "{key} 主机失败的返回码是多少？"),
       S("natural", "PLAY RECAP {key} : ok={value} changed={n2} unreachable=0 failed=0", "PLAY RECAP {key} : ok={value} changed={n2} 失败=0",
         "host", "count", "How many ok tasks did {key} report in the recap?", "{key} 的汇总里 ok 有多少个？")],
      BUR_JSON, ("Run the playbook and report {keys}.", "执行 playbook 并汇报 {keys}。"),
      ("Run the deployment and explain why it's unstable.", "执行部署，说明为什么不稳定。")),
    F("gitlog", "bash", {"command": "git log --stat -n 400"},
      ["commit {sha40}", "Author: {user} <{user}@acme.dev>", "    {verb} {word} handling in {word} module", " src/{word}/{word}_{n2}.py | {n2} ++++---"],
      ["commit {sha40}", "    {zw}: {zp}（{word}）", " src/{word}/{word}_{n2}.py | {n2} ++--"],
      [S("natural", "{value} {key}", "{value} {key}（修复）", "subject", "sha7",
         "What is the short hash of the commit '{key}'?", "提交“{key}”的短哈希是多少？"),
       S("natural", "Merge: {sha7} {sha7}\n    release {key} signed-off-by: {value}", "Merge: {sha7} {sha7}\n    发布 {key} signed-off-by: {value}",
         "module", "user", "Who authored the release commit of {key}?", "{key} 的发布提交是谁写的？")],
      BUR_COLON, ("Read the git history and report {keys}.", "阅读 git 历史并汇报 {keys}。"),
      ("Go through the history and tell me what changed recently.", "看看历史记录，最近改了什么？")),
    F("gitdiff", "bash", {"command": "git diff origin/main...HEAD"},
      ["diff --git a/src/{word}/{word}_{n2}.py b/src/{word}/{word}_{n2}.py", "index {sha7}..{sha7} 100644", "-    return {word}_{n2}({word})", "+    return {fn}({word}, timeout={n2})", "     # {word} {verb}"],
      ["+    # {zw}：{zp}", "-    # {zw}：{zp}", "@@ -{line},{n2} +{line},{n2} @@ def {fn}():"],
      [S("natural", "+{key} = {value}", "+{key} = {value}  # 修改", "cfgkey", "cfgval", Q_CFG[0], Q_CFG[1]),
       S("natural", "+    \"{key}\": \"^{value}\",", "+    \"{key}\": \"^{value}\",  // 升级", "pkg", "ver",
         "Which version range does the diff set for {key}?", "这个 diff 把 {key} 升级到哪个版本？")],
      BUR_ARROW, ("Review the diff and report {keys}.", "审阅 diff 并汇报 {keys}。"),
      ("Review this diff and tell me if anything is risky.", "看一下这个 diff 有没有风险。")),
    F("grep", "bash", {"command": "rg -n \"{word}\" src"},
      ["src/{word}/{word}_{n2}.py:{line}:    {word} = {fn}({word})", "src/{word}/{Cls}.ts:{line}:  const {word} = await {word}.{verb}();"],
      ["src/{word}/{word}_{n2}.py:{line}:    # {zw}{zp}", "docs/{word}.md:{line}: {zw}{zp}"],
      [S("natural", "src/config/{word}.py:{line}:{key} = {value}", "src/config/{word}.py:{line}:{key} = {value}  # 配置", "cfgkey", "cfgval", Q_CFG[0], Q_CFG[1]),
       S("natural", "{key}.py:{value}:def {fn}():", "{key}.py:{value}:def {fn}():  # 入口", "file", "lineno",
         "On which line of {key}.py is the function defined?", "{key}.py 的函数定义在第几行？")],
      BUR_EQ, ("Search the code and report {keys}.", "搜索代码并汇报 {keys}。"),
      ("Search the repo and figure out where the bug might be.", "在仓库里搜一下，看看问题可能在哪。")),
    F("npm", "bash", {"command": "npm install --no-audit"},
      ["npm http fetch GET 200 https://registry.npmjs.org/{pkg} {ms}ms (cache revalidated)", "npm warn deprecated {pkg}@{ver}: this version is no longer supported",
       "added {n3} packages, changed {n2} packages in {sec}s"],
      ["npm http fetch GET 200 https://registry.npmmirror.com/{pkg} {ms}ms（镜像）", "npm warn 已弃用 {pkg}@{ver}"],
      [S("natural", "+ {key}@{value}", "+ {key}@{value}（已安装）", "pkg", "ver", "Which version of {key} was installed?", "安装的 {key} 是哪个版本？"),
       S("error", "npm error code {value} while installing {key}", "npm error code {value}：安装 {key} 失败",
         "pkg", "npmcode", "Which npm error code did {key} hit?", "{key} 遇到的 npm 错误代码是什么？")],
      BUR_EQ, ("Install the dependencies and report {keys}.", "安装依赖并汇报 {keys}。"),
      ("Install the packages and tell me if something is wrong.", "装一下依赖，看看有没有问题。")),
    F("pip", "bash", {"command": "pip install -r requirements.txt"},
      ["Collecting {pkg}>={ver}", "  Downloading {pkg}-{ver}-py3-none-any.whl ({n3} kB)", "Requirement already satisfied: {pkg} in ./.venv/lib/python3.13/site-packages ({ver})"],
      ["正在收集 {pkg}>={ver}", "  正在下载 {pkg}-{ver}-py3-none-any.whl ({n3} kB) {zp}"],
      [S("natural", "Successfully installed {key}-{value}", "成功安装 {key}-{value}", "pkg", "ver", "Which version of {key} got installed?", "装上的 {key} 是哪个版本？"),
       S("error", "ERROR: Could not find a version that satisfies the requirement {key}=={value}", "错误: 找不到满足要求的版本 {key}=={value}",
         "pkg", "ver", "Which pinned version of {key} could not be found?", "找不到的 {key} 固定版本是哪个？")],
      BUR_COLON, ("Install the requirements and report {keys}.", "安装依赖并汇报 {keys}。"),
      ("Set up the environment and tell me what went wrong.", "配置一下环境，看看哪里出错了。")),
    F("docker", "bash", {"command": "docker build -t {word}:dev ."},
      ["#{n2} [{n2}/{n2}] RUN apt-get install -y {pkg}", "#{n2} {sec} Setting up {pkg} ({ver}) ...", "#{n2} DONE {sec}s"],
      ["#{n2} {sec} 正在设置 {pkg} ({ver}) ... {zp}", "#{n2} 完成 {sec}s"],
      [S("natural", "#{n2} writing image {value} done ({key})", "#{n2} 写入镜像 {value} 完成（{key}）", "image", "digest",
         "Which digest did image {key} get?", "镜像 {key} 的 digest 是什么？"),
       S("error", "ERROR: failed to solve: process \"/bin/sh -c make {key}\" did not complete successfully: exit code: {value}",
         "错误: failed to solve: \"/bin/sh -c make {key}\" 执行失败: exit code: {value}", "job", "exit",
         "What exit code did step make {key} return?", "make {key} 返回的退出码是多少？")],
      BUR_ARROW, ("Build the image and report {keys}.", "构建镜像并汇报 {keys}。"),
      ("Build the container and tell me what's wrong.", "构建一下容器，看看哪里有问题。")),
    F("terraform", "bash", {"command": "terraform plan -no-color"},
      ["  # {tftype}.{word}_{n2} will be updated in-place", "      ~ tags = {", "          \"{word}\" = \"{word}-{n2}\"", "    }", "{tftype}.{word}_{n2}: Refreshing state... [id={hex12}]"],
      ["{tftype}.{word}_{n2}: 正在刷新状态... [id={hex12}]", "  # {tftype}.{word}_{n2} 将被原地更新（{zp}）"],
      [S("natural", "      ~ {key}.instance_type = \"m5.large\" -> \"{value}\"", "      ~ {key}.instance_type = \"m5.large\" -> \"{value}\"（变更）",
         "resource", "cfgval", "What does the plan change {key}.instance_type to?", "计划把 {key}.instance_type 改成什么？"),
       S("natural", "Plan: {value} to add, {n2} to change, {n2} to destroy. ({key})", "计划: 新增 {value}, 修改 {n2}, 销毁 {n2}（{key}）", "module", "count",
         "How many resources does the {key} plan add?", "{key} 计划新增多少个资源？")],
      BUR_ARROW, ("Run terraform plan and report {keys}.", "运行 terraform plan 并汇报 {keys}。"),
      ("Run the plan and tell me if anything is dangerous.", "跑一下 plan，看看有没有危险的变更。")),
    F("gcc", "bash", {"command": "make -j8"},
      ["gcc -O2 -Wall -c src/{word}/{word}_{n2}.c -o build/{word}_{n2}.o", "src/{word}/{word}_{n2}.c:{line}:{col}: warning: unused variable '{word}' [-Wunused-variable]",
       "[{pct}%] Building C object CMakeFiles/{word}.dir/src/{word}_{n2}.c.o"],
      ["[{pct}%] 正在构建 C 对象 {word}_{n2}.c.o {zp}", "src/{word}/{word}_{n2}.c:{line}:{col}: 警告: 未使用的变量 '{word}'"],
      [S("error", "{key}.c:{value}:{col}: error: implicit declaration of function '{fn}'", "{key}.c:{value}:{col}: 错误: 隐式声明函数 '{fn}'",
         "file", "lineno", "On which line of {key}.c is the implicit declaration error?", "{key}.c 的隐式声明错误在第几行？"),
       S("natural", "-- {key} version: {value}", "-- {key} 版本: {value}", "pkg", "ver", "Which {key} version did the build detect?", "构建检测到的 {key} 版本是多少？")],
      BUR_EQ, ("Build the project and report {keys}.", "构建项目并汇报 {keys}。"),
      ("Compile it and tell me what's broken.", "编译一下，看看哪里坏了。")),
    F("tsc", "bash", {"command": "npx tsc --noEmit -p ."},
      ["src/{word}/{word}.ts({line},{col}): warning: '{word}' is declared but its value is never read.", "  Type '{Word}' is not assignable to type '{Word}Props'.",
       "    {n2}   const {word} = use{Word}({word});"],
      ["src/{word}/{word}.ts({line},{col}): 警告: 已声明“{word}”，但从未读取其值。", "    {n2}   // {zw}{zp}"],
      [S("error", "{key}.ts({line},{col}): error {value}: Argument of type 'string' is not assignable to parameter of type 'number'.",
         "{key}.ts({line},{col}): error {value}: 类型“string”的参数不能赋给类型“number”的参数。", "file", "tscode",
         "Which TypeScript error code does {key}.ts report?", "{key}.ts 报的 TypeScript 错误代码是什么？"),
       S("natural", "Found {value} errors in {n2} files. ({key})", "在 {n2} 个文件中找到 {value} 个错误。（{key}）", "module", "count",
         "How many type errors did {key} report?", "{key} 报了多少个类型错误？")],
      BUR_COLON, ("Run the type checker and report {keys}.", "运行类型检查并汇报 {keys}。"),
      ("Type-check the project and tell me what's wrong.", "做一下类型检查，看看问题。")),
    F("javac", "bash", {"command": "javac -d out @sources.txt -Xlint:all"},
      ["src/com/acme/{word}/{Cls}.java:{line}: warning: [rawtypes] found raw type: List", "        List {word} = new ArrayList();", "        ^"],
      ["src/com/acme/{word}/{Cls}.java:{line}: 警告: [rawtypes] 找到原始类型: List", "        // {zw}{zp}"],
      [S("error", "src/com/acme/{key}.java:{value}: error: cannot find symbol", "src/com/acme/{key}.java:{value}: 错误: 找不到符号",
         "file", "lineno", "On which line of {key}.java is the cannot-find-symbol error?", "{key}.java 找不到符号的错误在第几行？"),
       S("natural", "{value} warnings ({key})", "{value} 个警告（{key}）", "module", "count", "How many warnings did {key} produce?", "{key} 产生了多少个警告？")],
      BUR_EQ, ("Compile the Java sources and report {keys}.", "编译 Java 源码并汇报 {keys}。"),
      ("Compile and tell me what needs fixing.", "编译一下，告诉我要修什么。")),
    F("trace-python", "bash", {"command": "python -m {word}.worker"},
      ["{ts} {level} {word}.worker: handled job {n5} in {ms}ms", "{ts} {level} {word}.db: pool size={n2} in_use={n2}"],
      ["{ts} {level} {word}.worker: 任务 {n5} {zp}，耗时 {ms}ms", "{ts} {level} {word}.db: 连接池 {n2}/{n2}"],
      [S("error", ("Traceback (most recent call last):", "  File \"/app/{word}/{word}.py\", line {line}, in {fn}", "    raise {key}Error(code)",
                   "{key}Error: upstream rejected request code={value}"),
         ("Traceback (most recent call last):", "  File \"/app/{word}/{word}.py\", line {line}, in {fn}", "{key}Error: 上游拒绝请求 code={value}"),
         "module", "errno", "Which code did the {key}Error carry?", "{key}Error 带的错误代码是什么？"),
       S("natural", "{ts} INFO {word}.boot: {key}={value} (from env)", "{ts} INFO {word}.boot: {key}={value}（来自环境变量）", "cfgkey", "cfgval", Q_CFG[0], Q_CFG[1])],
      BUR_JSON, ("Run the worker and report {keys}.", "运行 worker 并汇报 {keys}。"),
      ("Run the worker and figure out why jobs fail.", "运行 worker，查一下任务为什么失败。")),
    F("trace-java", "bash", {"command": "java -jar target/{word}.jar"},
      ["{ts} {level} [main] c.a.{word}.{Cls} - stage {n2} ok id={hex}", "\tat com.acme.{word}.{Cls}.{fn}({Cls}.java:{line})"],
      ["{ts} {level} [main] c.a.{word}.{Cls} - 阶段 {n2} {zp} id={hex}"],
      [S("error", ("{ts} ERROR [main] o.s.boot.SpringApplication - Application run failed", "java.lang.IllegalStateException: Failed to load {key}",
                   "Caused by: {value}: connection refused while loading {key}", "\tat com.acme.{word}.{Cls}.{fn}({Cls}.java:{line})"),
         ("{ts} ERROR [main] o.s.boot.SpringApplication - 应用启动失败", "Caused by: {value}: 连接被拒绝（{key}）"),
         "module", "javaex", "What is the root cause exception for {key}?", "{key} 的根因异常是什么？"),
       S("natural", "{ts} INFO [main] c.a.config - {key}: {value}", "{ts} INFO [main] c.a.config - 配置 {key}: {value}", "cfgkey", "cfgval", Q_CFG[0], Q_CFG[1])],
      BUR_EQ, ("Start the service and report {keys}.", "启动服务并汇报 {keys}。"),
      ("Start the service and tell me why it won't come up.", "启动服务，看看为什么起不来。")),
    F("trace-node", "bash", {"command": "node dist/server.js"},
      ["[{time}] info: {method} /api/{word} {status} {ms}ms", "    at {Cls}.{fn} (/app/dist/{word}.js:{line}:{col})"],
      ["[{time}] info: {method} /api/{word} {status} {ms}ms {zp}"],
      [S("error", ("Error: request to {key} failed with status {value}", "    at {Cls}.{fn} (/app/dist/{word}.js:{line}:{col})"),
         ("Error: 请求 {key} 失败，状态码 {value}", "    at {Cls}.{fn} (/app/dist/{word}.js:{line}:{col})"),
         "endpoint", "http", "Which status did {key} fail with?", "{key} 失败时返回的状态码是多少？"),
       S("natural", "[{time}] info: listening on port {value} ({key})", "[{time}] info: 监听端口 {value}（{key}）", "module", "port",
         "Which port is {key} listening on?", "{key} 监听的是哪个端口？")],
      BUR_ARROW, ("Run the server and report {keys}.", "运行服务并汇报 {keys}。"),
      ("Run the server and tell me what's going wrong.", "运行服务，看看哪里出问题了。")),
    F("trace-go", "bash", {"command": "go run ./cmd/{word}"},
      ["{ts} level=info msg=\"{word} tick\" n={n5} dur={ms}ms", "goroutine {n3} [select]:", "\t/app/internal/{word}/{word}.go:{line} +0x{hex4}"],
      ["{ts} level=info msg=\"{zw} {zp}\" n={n5}"],
      [S("error", ("panic: {key}: runtime error: index out of range [{value}] with length {n2}", "goroutine 1 [running]:", "main.{fn}(...)", "\t/app/internal/{key}/{key}.go:{line} +0x{hex4}"),
         ("panic: {key}: runtime error: index out of range [{value}] with length {n2}", "\t/app/internal/{key}/{key}.go:{line}（崩溃）"),
         "suite", "count", "What index caused the panic in package {key}?", "{key} 包里导致 panic 的下标是多少？"),
       S("natural", "{ts} level=info msg=\"config loaded\" {key}={value}", "{ts} level=info msg=\"已加载配置\" {key}={value}", "cfgkey", "cfgval", Q_CFG[0], Q_CFG[1])],
      BUR_EQ, ("Run the Go service and report {keys}.", "运行 Go 服务并汇报 {keys}。"),
      ("Run it and tell me why it crashes.", "运行一下，看看为什么崩溃。")),
    F("trace-csharp", "bash", {"command": "dotnet run --project src/{Word}"},
      ["info: {Word}.Worker[0]\n      Processed message {hex} in {ms} ms", "   at {Word}.{Cls}.{Word}Async() in /src/{Word}/{Cls}.cs:line {line}"],
      ["info: {Word}.Worker[0]\n      已处理消息 {hex}，耗时 {ms} ms（{zp}）"],
      [S("error", ("fail: {Word}.Worker[0]", "System.InvalidOperationException: Failed to process {key}", " ---> Microsoft.Data.SqlClient.SqlException (0x{value}): Login failed for job {key}"),
         ("fail: {Word}.Worker[0]", "System.InvalidOperationException: 处理 {key} 失败", " ---> Microsoft.Data.SqlClient.SqlException (0x{value}): 登录失败（{key}）"),
         "job", "hex", "Which SqlException code appeared while processing {key}?", "处理 {key} 时出现的 SqlException 代码是什么？"),
       S("natural", "info: Startup[0] {key} = {value}", "info: Startup[0] 配置 {key} = {value}", "cfgkey", "cfgval", Q_CFG[0], Q_CFG[1])],
      BUR_COLON, ("Run the service and report {keys}.", "运行服务并汇报 {keys}。"),
      ("Run it and work out why messages are failing.", "运行一下，查查消息为什么处理失败。")),
    F("configdump", "bash", {"command": "env | sort && cat /etc/{word}/{word}.conf"},
      ["{word}_{setting}={n3}", "{word}.{word}.{setting} = {n3}", "# {word} {verb} defaults"],
      ["# {zw}{zp}", "{word}_{setting}={n3}  # {zw}"],
      [S("natural", "{key}: {value}", "{key}: {value}  # 生产配置", "cfgkey", "cfgval", Q_CFG[0], Q_CFG[1]),
       S("natural", "{key}_PORT={value}", "{key}_PORT={value}  # 端口", "host", "port", "Which port is configured for {key}?", "{key} 配置的端口是多少？")],
      BUR_ARROW, ("Dump the configuration and report {keys}.", "导出配置并汇报 {keys}。"),
      ("Dump the config and tell me if anything is misconfigured.", "导出配置，看看有没有配错。"), 14000),
    F("apijson", "http_get", {"url": "https://api.acme.dev/v2/{word}?page={n2}"},
      ['  {"id": "{hex}", "name": "{word}-{n3}", "status": "active", "updated_at": "{ts}"},', '  {"id": "{hex}", "owner": "{user}", "count": {n3},'],
      ['  {"id": "{hex}", "name": "{zw}-{n3}", "status": "正常", "updated_at": "{ts}"},'],
      [S("natural", '  {"id": "{hex}", "name": "{key}", "limit": "{value}"},', '  {"id": "{hex}", "name": "{key}", "limit": "{value}", "备注": "{zp}"},',
         "table", "cfgval", "What limit does {key} have?", "{key} 的 limit 是多少？"),
       S("error", '  {"error": {"code": "{value}", "endpoint": "{key}"},', '  {"error": {"code": "{value}", "endpoint": "{key}", "message": "请求失败"},',
         "endpoint", "http", "Which error code did {key} return?", "{key} 返回的错误代码是什么？")],
      BUR_JSON, ("Call the API and report {keys}.", "调用接口并汇报 {keys}。"),
      ("Call the API and tell me what looks wrong.", "调一下接口，看看有什么不对。")),
    F("markdown", "read_file", {"path": "docs/{word}/README.md"},
      ["The {word} service {verb} requests from the {word} queue and retries on failure.", "- [ ] {Word} {verb} follow-up ({user})",
       "| {word} | {n3} | {status} |", "## {Word} {verb}"],
      ["{zw}服务会{zp}，失败时自动重试。", "- [ ] {zw}{zp}（{user}）", "## {zw}说明"],
      [S("natural", "> **{key}:** {value}", "> **{key}：** {value}", "section", "cfgval", "What does the doc state for {key}?", "文档里 {key} 写的是什么？"),
       S("natural", "| {key} | owner | {value} |", "| {key} | 负责人 | {value} |", "section", "user", "Who owns {key} according to the doc?", "文档里 {key} 的负责人是谁？")],
      BUR_COLON, ("Read the docs and report {keys}.", "阅读文档并汇报 {keys}。"),
      ("Read the docs and tell me what matters for the outage.", "看看文档，跟这次故障相关的有哪些？"), 15000),
    F("nginx", "bash", {"command": "tail -n 20000 /var/log/nginx/access.log"},
      ["{ip} - - [{time}] \"{method} /api/{word}/{n3} HTTP/1.1\" {status} {bytes} \"-\" \"Mozilla/5.0\"", "{ip} - - [{time}] \"GET /static/{word}.js HTTP/1.1\" 304 0"],
      ["{ip} - - [{time}] \"{method} /api/{word}/{n3} HTTP/1.1\" {status} {bytes} \"-\" \"{zw}客户端\""],
      [S("error", "{ip} - - [{time}] \"POST {key} HTTP/1.1\" {value} {bytes} \"-\" \"curl/8.5\"", "{ip} - - [{time}] \"POST {key} HTTP/1.1\" {value} {bytes} \"-\" \"{zw}客户端\"",
         "endpoint", "http", "Which status did POST {key} get?", "POST {key} 得到的状态码是多少？"),
       S("natural", "upstream {key} response time {value}", "上游 {key} 响应时间 {value}", "host", "dur", "What response time did upstream {key} report?", "上游 {key} 的响应时间是多少？")],
      BUR_EQ, ("Read the access log and report {keys}.", "读取访问日志并汇报 {keys}。"),
      ("Look at the access log and tell me what's failing.", "看看访问日志，哪些请求失败了？"), 26000),
    F("journald", "bash", {"command": "journalctl -u {word}.service --since today"},
      ["Nov {n2} {time} node-{n2} {word}[{n5}]: {level} heartbeat ok seq={n5}", "Nov {n2} {time} node-{n2} systemd[1]: Started {word}-timer.service."],
      ["Nov {n2} {time} node-{n2} {word}[{n5}]: {level} 心跳正常 seq={n5}", "Nov {n2} {time} node-{n2} systemd[1]: 已启动 {word}.service（{zp}）"],
      [S("error", "Nov {n2} {time} node-{n2} systemd[1]: {key}.service: Main process exited, code=exited, status={value}/FAILURE",
         "Nov {n2} {time} node-{n2} systemd[1]: {key}.service: 主进程退出, status={value}/FAILURE", "job", "exit",
         "Which exit status did {key}.service fail with?", "{key}.service 失败的退出状态是多少？"),
       S("natural", "Nov {n2} {time} node-{n2} {word}[{n5}]: limits {key}={value}", "Nov {n2} {time} node-{n2} {word}[{n5}]: 限制 {key}={value}", "cfgkey", "cfgval", Q_CFG[0], Q_CFG[1])],
      BUR_COLON, ("Read the journal and report {keys}.", "查看 journal 并汇报 {keys}。"),
      ("Read the journal and tell me why the unit keeps restarting.", "看看 journal，服务为什么一直重启。")),
    F("helm", "bash", {"command": "helm upgrade --install {word} ./charts/{word} --debug"},
      ["client.go:{n3}: [debug] Looking for resources to update: {word}-{hex5}", "  {word}: {n3}", "    - name: {word}\n      value: \"{n3}\""],
      ["client.go:{n3}: [debug] 正在检查待更新资源 {word}-{hex5}（{zp}）", "  # {zw}{zp}"],
      [S("natural", "  {key}: {value}", "  {key}: {value}  # 覆盖值", "cfgkey", "cfgval", Q_CFG[0], Q_CFG[1]),
       S("natural", "Release \"{key}\" has been upgraded to revision {value}.", "Release \"{key}\" 已升级到 revision {value}。", "module", "count", "Which revision did release {key} reach?", "{key} 发布到了第几个 revision？")],
      BUR_EQ, ("Upgrade the release and report {keys}.", "升级 release 并汇报 {keys}。"),
      ("Upgrade the chart and tell me whether anything broke.", "升级 chart，看看有没有出问题。")),
    F("rspec", "bash", {"command": "bundle exec rspec spec/{word}"},
      ["{Cls}", "  #{fn}", "    {verb} the {word} when {word} is present", "Finished in {sec} seconds (files took {sec} seconds to load)"],
      ["  #{fn}", "    {zw}存在时{zp}"],
      [S("error", "rspec ./spec/{key}_spec.rb:{line} # {value}", "rspec ./spec/{key}_spec.rb:{line} # {value}（失败）", "suite", "testname",
         "Which example failed in {key}_spec.rb?", "{key}_spec.rb 里哪个用例失败了？"),
       S("natural", "{n3} examples, {value} failures ({key})", "{n3} examples, {value} failures（{key}）", "suite", "count", "How many failures did {key} have?", "{key} 有多少个失败？")],
      BUR_ARROW, ("Run rspec and report {keys}.", "运行 rspec 并汇报 {keys}。"),
      ("Run the specs and tell me what's broken.", "跑一下 spec，看看哪里坏了。")),
    F("phpunit", "bash", {"command": "vendor/bin/phpunit --testdox"},
      ["{Cls} (App\\Tests\\{Word})", " ✔ {Word} {verb} correctly", "............................................................. {n3} / {n3} ({pct}%)"],
      [" ✔ {zw}{zp}", "............................................................. {n3} / {n3} ({pct}%) {zp}"],
      [S("error", " ✘ {key}Test::{value}\n   ┐\n   ├ Failed asserting that {n3} matches expected {n3}.\n   ┴", " ✘ {key}Test::{value}\n   ├ 断言失败 {n3} 与 {n3} 不符\n   ┴",
         "suite", "testname", "Which test failed in {key}Test?", "{key}Test 里哪个测试失败了？"),
       S("natural", "Tests: {n3}, Assertions: {n3}, Failures: {value}. ({key})", "Tests: {n3}, Assertions: {n3}, Failures: {value}.（{key}）", "suite", "count",
         "How many failures did {key} report?", "{key} 报告了多少个失败？")],
      BUR_COLON, ("Run phpunit and report {keys}.", "运行 phpunit 并汇报 {keys}。"),
      ("Run the PHP tests and tell me what's wrong.", "跑一下 PHP 测试，看看哪里不对。")),
    F("eslint", "bash", {"command": "npx eslint . --max-warnings=0"},
      ["/work/src/{word}/{word}.tsx", "  {line}:{col}  warning  Unexpected console statement  no-console", "  {line}:{col}  warning  '{word}' is assigned a value but never used  @typescript-eslint/no-unused-vars"],
      ["  {line}:{col}  warning  不应使用 console 语句  no-console", "/work/src/{word}/{zw}.tsx"],
      [S("error", "/work/{key}.tsx:{value}:{col}: error  React Hook useEffect has a missing dependency  react-hooks/exhaustive-deps",
         "/work/{key}.tsx:{value}:{col}: error  React Hook useEffect 缺少依赖  react-hooks/exhaustive-deps", "file", "lineno",
         "On which line of {key}.tsx is the exhaustive-deps error?", "{key}.tsx 的 exhaustive-deps 错误在第几行？"),
       S("natural", "✖ {n3} problems ({value} errors, {n3} warnings) in {key}", "✖ {n3} 个问题（{value} 个错误）于 {key}", "module", "count",
         "How many lint errors did {key} have?", "{key} 有多少个 lint 错误？")],
      BUR_EQ, ("Lint the code and report {keys}.", "检查代码规范并汇报 {keys}。"),
      ("Lint the project and tell me what matters.", "跑一下 lint，看看哪些重要。")),
    F("mypy", "bash", {"command": "mypy src --strict"},
      ["src/{word}/{word}_{n2}.py:{line}: note: Revealed type is \"builtins.{word}\"", "src/{word}/{word}_{n2}.py:{line}: error: Missing type parameters for generic type \"dict\"  [type-arg]"],
      ["src/{word}/{word}_{n2}.py:{line}: note: 推断类型为 \"builtins.{word}\"（{zp}）"],
      [S("error", "{key}.py:{value}: error: Incompatible return value type (got \"None\", expected \"int\")  [return-value]",
         "{key}.py:{value}: error: 返回值类型不兼容（得到 \"None\"，期望 \"int\"）  [return-value]", "file", "lineno",
         "On which line of {key}.py is the return-value error?", "{key}.py 的 return-value 错误在第几行？"),
       S("natural", "Found {value} errors in {n2} files (checked {n3} source files) [{key}]", "发现 {value} 个错误（检查了 {n3} 个文件）[{key}]", "module", "count",
         "How many mypy errors did {key} report?", "{key} 报告了多少个 mypy 错误？")],
      BUR_ARROW, ("Run mypy and report {keys}.", "运行 mypy 并汇报 {keys}。"),
      ("Type-check the Python code and tell me what's wrong.", "检查一下 Python 类型，看看有什么问题。")),
    F("webpack", "bash", {"command": "npx webpack --mode production"},
      ["asset {word}.{hex}.js {n3} KiB [emitted] [immutable] [minimized] (name: {word})", "orphan modules {n3} KiB [orphan] {n2} modules", "  ./src/{word}/{word}.ts {n3} bytes [built] [code generated]"],
      ["asset {word}.{hex}.js {n3} KiB [emitted]（{zp}）", "  ./src/{word}/{zw}.ts {n3} bytes [built]"],
      [S("error", "ERROR in ./src/{key}.ts\nModule not found: Error: Can't resolve '{value}' in './src/{key}'", "ERROR in ./src/{key}.ts\nModule not found: 无法解析 '{value}'（./src/{key}）", "file", "npmmod",
         "Which module could ./src/{key}.ts not resolve?", "./src/{key}.ts 解析不到哪个模块？"),
       S("natural", "webpack {value} compiled with {n2} warnings in {ms} ms ({key})", "webpack {value} 编译完成，{n2} 个警告（{key}）", "module", "ver",
         "Which webpack version built {key}?", "构建 {key} 用的 webpack 版本是多少？")],
      BUR_COLON, ("Build the bundle and report {keys}.", "构建前端包并汇报 {keys}。"),
      ("Build the frontend and tell me what's wrong.", "构建一下前端，看看哪里有问题。")),
    F("cmake", "bash", {"command": "cmake --build build -j 16"},
      ["[{pct}%] Building CXX object src/{word}/CMakeFiles/{word}.dir/{word}_{n2}.cpp.o", "[{pct}%] Linking CXX static library lib{word}.a", "-- Looking for {word}.h - found"],
      ["[{pct}%] 正在构建 CXX 对象 {word}_{n2}.cpp.o", "-- 查找 {word}.h - 已找到（{zp}）"],
      [S("error", "{key}.cpp:{value}:{col}: error: no matching function for call to '{fn}'", "{key}.cpp:{value}:{col}: 错误: 没有匹配的函数调用 '{fn}'", "file", "lineno",
         "On which line of {key}.cpp is the no-matching-function error?", "{key}.cpp 的“没有匹配函数”错误在第几行？"),
       S("natural", "-- Found {key}: /usr/lib/x86_64-linux-gnu (found version \"{value}\")", "-- 找到 {key}: /usr/lib (版本 \"{value}\")", "pkg", "ver",
         "Which version of {key} did CMake find?", "CMake 找到的 {key} 版本是多少？")],
      BUR_EQ, ("Build with CMake and report {keys}.", "用 CMake 构建并汇报 {keys}。"),
      ("Build the C++ code and tell me what's failing.", "构建 C++ 代码，看看哪里失败。")),
    F("apt", "bash", {"command": "apt-get install -y --no-install-recommends build-essential"},
      ["Get:{n3} http://deb.debian.org/debian bookworm/main amd64 {pkg} amd64 {ver} [{n3} kB]", "Unpacking {pkg} ({ver}) ...", "Setting up {pkg} ({ver}) ..."],
      ["获取:{n3} http://mirrors.aliyun.com/debian bookworm/main amd64 {pkg} {ver} [{n3} kB]", "正在解压 {pkg} ({ver}) ...", "正在设置 {pkg} ({ver}) ..."],
      [S("natural", "Setting up {key} ({value}) ...", "正在设置 {key} ({value}) ...", "pkg", "ver", "Which version of {key} was set up?", "安装的 {key} 是哪个版本？"),
       S("error", "E: Unable to locate package {key}-{value}", "E: 无法定位软件包 {key}-{value}", "pkg", "hex",
         "Which package suffix could apt not locate for {key}?", "apt 找不到的 {key} 包后缀是什么？")],
      BUR_COLON, ("Install the packages and report {keys}.", "安装软件包并汇报 {keys}。"),
      ("Install the build tools and tell me if something failed.", "安装构建工具，看看有没有失败。")),
    F("k8sevents", "kubectl", {"command": "kubectl get events -A --sort-by=.lastTimestamp"},
      ["{ns}  {n2}m  Normal  Pulled  pod/{pod}  Container image already present on machine", "{ns}  {n2}m  Normal  Scheduled  pod/{pod}  Successfully assigned {ns}/{pod} to node-{n2}"],
      ["{ns}  {n2}m  Normal  Pulled  pod/{pod}  镜像已存在于节点（{zp}）"],
      [S("error", "{ns}  {n2}m  Warning  BackOff  pod/{key}  Back-off restarting failed container, reason {value}", "{ns}  {n2}m  Warning  BackOff  pod/{key}  重启失败容器，原因 {value}",
         "pod", "reason", "Why is pod {key} backing off?", "{key} 为什么在 back-off？"),
       S("natural", "{ns}  {n2}m  Normal  ScalingReplicaSet  deployment/{key}  Scaled up replica set to {value}", "{ns}  {n2}m  Normal  ScalingReplicaSet  deployment/{key}  副本数扩到 {value}",
         "module", "count", "To how many replicas was {key} scaled?", "{key} 扩到了多少副本？")],
      BUR_JSON, ("List the cluster events and report {keys}.", "列出集群事件并汇报 {keys}。"),
      ("Check the cluster events and tell me what's wrong.", "看看集群事件，有什么问题？")),
    F("pglog", "bash", {"command": "tail -n 30000 /var/log/postgresql/postgresql-16-main.log"},
      ["{ts} UTC [{n5}] LOG:  duration: {float} ms  statement: SELECT * FROM {word} WHERE id = {n5}", "{ts} UTC [{n5}] LOG:  checkpoint complete: wrote {n3} buffers"],
      ["{ts} UTC [{n5}] 日志:  执行时间: {float} ms  语句: SELECT * FROM {word}", "{ts} UTC [{n5}] 日志:  检查点完成: 写入 {n3} 个缓冲区"],
      [S("error", "{ts} UTC [{n5}] ERROR:  deadlock detected on relation {key} (SQLSTATE {value})", "{ts} UTC [{n5}] 错误:  在关系 {key} 上检测到死锁 (SQLSTATE {value})",
         "table", "sqlstate", "Which SQLSTATE did the error on {key} carry?", "{key} 上的错误 SQLSTATE 是多少？"),
       S("natural", "{ts} UTC [{n5}] LOG:  parameter \"{key}\" changed to \"{value}\"", "{ts} UTC [{n5}] 日志:  参数 \"{key}\" 已改为 \"{value}\"", "cfgkey", "cfgval", Q_CFG[0], Q_CFG[1])],
      BUR_EQ, ("Read the Postgres log and report {keys}.", "读取 Postgres 日志并汇报 {keys}。"),
      ("Look at the database log and tell me why queries are slow.", "看看数据库日志，查询为什么慢。"), 24000),
    F("promtext", "http_get", {"url": "http://{host}:9090/metrics"},
      ["{word}_requests_total{method=\"{method}\",code=\"{status}\"} {n5}", "# HELP {word}_latency_seconds Request latency.", "{word}_latency_seconds_bucket{le=\"{sec}\"} {n5}"],
      ["# HELP {word}_latency_seconds 请求延迟（{zp}）", "{word}_requests_total{method=\"{method}\",code=\"{status}\"} {n5}"],
      [S("natural", "{key} {value}", "{key} {value}  # 当前值", "metric", "num", "What value does the {key} gauge show?", "{key} 指标的值是多少？"),
       S("error", "{key}_errors_total{code=\"{value}\"} 1", "{key}_errors_total{code=\"{value}\"} 1  # 错误", "module", "http",
         "Which error code is counted for {key}?", "{key} 计数的错误代码是什么？")],
      BUR_COLON, ("Scrape the metrics and report {keys}.", "抓取指标并汇报 {keys}。"),
      ("Scrape the metrics and tell me what's abnormal.", "抓一下指标，看看哪里异常。"), 22000),
    F("ghactions", "gh_run_view", {"run": "{n5}", "log": "true"},
      ["build\tRun actions/checkout@v4\t{ts} Syncing repository: acme/{word}", "test\tRun npm test\t{ts}   ✓ {word} {verb} ({ms} ms)", "build\t{ts} ##[group]Run {word}-{verb}"],
      ["test\tRun npm test\t{ts}   ✓ {zw}{zp} ({ms} ms)", "build\t{ts} ##[group]运行 {word}"],
      [S("error", "test\t{ts} ##[error]Process completed with exit code {value}. ({key})", "test\t{ts} ##[error]进程退出码 {value}（{key}）", "job", "exit",
         "Which exit code did job {key} end with?", "{key} 任务以哪个退出码结束？"),
       S("natural", "build\t{ts} cache key: {key}-{value}", "build\t{ts} 缓存键: {key}-{value}", "module", "hex", "Which cache key suffix did {key} use?", "{key} 用的缓存键后缀是什么？")],
      BUR_ARROW, ("Read the CI log and report {keys}.", "读取 CI 日志并汇报 {keys}。"),
      ("Read the CI run and tell me why it's red.", "看看 CI，为什么挂了。")),
    F("bazel", "bash", {"command": "bazel test //... --test_output=errors"},
      ["INFO: From Compiling src/{word}/{word}_{n2}.cc:", "//src/{word}:{word}_test                                PASSED in {sec}s", "[{n5} / {n5}] {n2} actions running"],
      ["//src/{word}:{word}_test                                PASSED in {sec}s（{zp}）", "信息: 正在编译 src/{word}/{word}_{n2}.cc"],
      [S("error", "//src/{key}:{value}                              FAILED in {sec}s", "//src/{key}:{value}                              FAILED in {sec}s（失败）", "suite", "testname",
         "Which Bazel target failed in //src/{key}?", "//src/{key} 里哪个 Bazel 目标失败了？"),
       S("natural", "INFO: Build option --{key} has changed, discarding analysis cache ({value})", "信息: 构建选项 --{key} 已改变 ({value})", "cfgkey", "cfgval", Q_CFG[0], Q_CFG[1])],
      BUR_EQ, ("Run the Bazel tests and report {keys}.", "运行 Bazel 测试并汇报 {keys}。"),
      ("Run the tests and tell me what failed.", "跑一下测试，看看什么失败了。")),
    F("csvexport", "read_file", {"path": "exports/{word}_{n2}.csv"},
      ["{n5},{word},{user},{ts},{float},ok", "{n5},{word}_{verb},{user},{ts},{n3},ok"],
      ["{n5},{zw},{user},{ts},{float},正常", "{n5},{zw}{zp},{user},{ts},{n3},正常"],
      [S("natural", "{n5},{key},{user},{ts},{value},override", "{n5},{key},{user},{ts},{value},覆盖", "table", "num", "What value does row {key} hold?", "{key} 这一行的值是多少？"),
       S("error", "{n5},{key},{user},{ts},ERR,{value}", "{n5},{key},{user},{ts},错误,{value}", "table", "errno", "Which error code is on row {key}?", "{key} 这一行的错误代码是什么？")],
      BUR_EQ, ("Read the export and report {keys}.", "读取导出文件并汇报 {keys}。"),
      ("Read the export and tell me what's odd.", "看看导出的数据有什么奇怪的。"), 22000),
)

FAMILY_BY_ID = {f.id: f for f in FAMILIES}
BURNED_ROUND1 = ("pytest-zh", "maven-en", "kubectl-zh", "sql-en", "jest-en", "gotest-zh", "cargo-en", "metrics-zh")
assert len(FAMILY_BY_ID) == len(FAMILIES)
