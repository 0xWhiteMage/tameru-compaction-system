"""Seeded generators for the engine benchmark's NEW cases (synthetic, no copyrighted data).

Each generator takes (cluster index k, variant 'a'|'b') and returns a case dict via ``make_case``.
A cluster's failure (chain, ids) depends only on the cluster; the variant changes the amount and
position of surrounding noise.  Variants of one cluster share ``source_case`` and so share a split.
"""
from __future__ import annotations

import hashlib
import random

GENERIC_QUERY = "continue"

TOOL_CALLS = {
    "trace-python": "python app/main.py", "trace-java": "java -jar target/service.jar",
    "trace-dotnet": "dotnet run --project src/Orders", "trace-node": "node server.js",
    "trace-go": "go run ./cmd/worker", "trace-rust": "cargo run", "trace-ruby": "bundle exec rails runner jobs/run.rb",
    "trace-php": "php artisan queue:work", "trace-kotlin": "./gradlew bootRun", "trace-scala": "sbt run",
    "comp-gcc": "make -j8", "comp-clang": "make -j8", "comp-msvc": "msbuild app.sln /m", "comp-javac": "javac -d out @sources.txt",
    "comp-tsc": "npx tsc --noEmit", "comp-mypy": "mypy src", "comp-pyright": "pyright", "comp-eslint": "npx eslint .",
    "comp-govet": "go vet ./...", "comp-clippy": "cargo clippy", "comp-rustc": "cargo build", "comp-linker": "make link",
    "run-pytest": "pytest -x tests/", "run-jest": "npx jest", "run-gotest": "go test ./...", "run-cargo": "cargo test",
    "run-junit": "mvn test", "run-gradle": "./gradlew build", "run-dotnet": "dotnet test", "run-surefire": "mvn -q test",
    "run-rspec": "bundle exec rspec", "run-phpunit": "vendor/bin/phpunit",
}
SHAPE_TOOL = {"trace": "run the service", "build": "make", "test": "run the tests", "log": "tail -n 400 logs/app.log",
              "structured": "cat data/output.txt", "prose": "cat docs/notes.md", "code": "cat -n src/main.py", "diff": "git diff"}
ZH_USER_HANS = ["帮我看看上面命令的输出，到底哪里出错了？", "刚才跑的结果不对，请找出失败的原因。",
                "你先看一下这个输出，告诉我关键的错误信息和涉及的编号。", "继续吧，顺便把报错的那几行指出来。"]
ZH_USER_HANT = ["幫我看看上面指令的輸出，到底哪裡出錯了？", "剛才跑的結果不對，請找出失敗的原因。"]


def rng(tag: str) -> random.Random:
    return random.Random(int(hashlib.sha256(tag.encode()).hexdigest()[:12], 16))


def hexid(r: random.Random, n: int = 8) -> str:
    return "".join(r.choice("0123456789abcdef") for _ in range(n))


def ts(r: random.Random, i: int) -> str:
    return f"2026-11-0{1 + i % 7} 1{(i // 3600) % 10}:{(i // 60) % 60:02d}:{i % 60:02d}.{r.randint(0, 999):03d}"


def make_case(cid, source, ctype, shape, text, gold, language, task, forbidden=(), tool=None, zh=None):
    queries = {"task": task, "tool_call": tool or TOOL_CALLS.get(shape) or SHAPE_TOOL.get(ctype, "bash ./run.sh"),
               "generic": GENERIC_QUERY}
    if language in ("zh", "mixed"):
        pool = ZH_USER_HANT if zh == "hant" else ZH_USER_HANS
        queries["zh_user"] = pool[int(hashlib.sha256(cid.encode()).hexdigest()[:4], 16) % len(pool)]
    return {"id": cid, "source_case": source, "content_type": ctype, "shape": shape, "text": text,
            "gold": list(gold), "forbidden": list(forbidden), "language": language, "queries": queries}


# ---------------------------------------------------------------- Java chained exceptions
_JAVA_FRAMES = ["org.springframework.beans.factory.support.AbstractAutowireCapableBeanFactory.initializeBean",
                "org.springframework.beans.factory.support.DefaultSingletonBeanRegistry.getSingleton",
                "org.springframework.context.support.AbstractApplicationContext.refresh",
                "org.springframework.boot.SpringApplication.run", "com.zaxxer.hikari.pool.HikariPool.getConnection",
                "org.hibernate.engine.jdbc.internal.JdbcCoordinatorImpl.getLogicalConnection",
                "java.base/java.lang.reflect.Method.invoke", "java.base/java.util.concurrent.ThreadPoolExecutor.runWorker",
                "io.netty.channel.nio.NioEventLoop.run", "org.apache.kafka.clients.consumer.KafkaConsumer.<init>"]


def _frames(r, n, pkg="com.acme"):
    out = []
    for _ in range(n):
        base = r.choice(_JAVA_FRAMES) if r.random() < 0.7 else f"{pkg}.svc.Handler{r.randint(1, 40)}.process"
        out.append(f"\tat {base}({base.split('.')[-2].split('/')[-1]}.java:{r.randint(20, 2400)})")
    return out


def _java_chains(r):
    n, pid = r.randint(10, 99), r.randint(1000, 99999)
    ten = "tenant_" + hexid(r, 6)
    return [
        ("orderRepository", [("org.springframework.beans.factory.BeanCreationException", "Error creating bean with name 'orderRepository': Invocation of init method failed"),
                             ("org.hibernate.exception.JDBCConnectionException", "Unable to acquire JDBC Connection"),
                             ("java.sql.SQLTransientConnectionException", "HikariPool-1 - Connection is not available, request timed out after 30000ms."),
                             ("java.net.ConnectException", f"Connection refused: db-{n}.internal:5432")]),
        ("kafkaListener", [("org.apache.kafka.common.KafkaException", "Failed to construct kafka consumer"),
                           ("org.apache.kafka.common.config.ConfigException", f"Invalid value {pid} for configuration max.poll.interval.ms: must be at least 1")]),
        ("tenantService", [("java.lang.IllegalStateException", "Failed to load ApplicationContext"),
                           ("org.springframework.beans.BeanInstantiationException", "Failed to instantiate [com.acme.TenantService]: Constructor threw exception"),
                           ("java.lang.NullPointerException", f'Cannot invoke "String.length()" because "this.{ten}" is null')]),
        ("billingClient", [("org.springframework.web.client.ResourceAccessException", f"I/O error on POST request for \"https://billing-{n}.acme.io/v2/charge\""),
                           ("javax.net.ssl.SSLHandshakeException", "PKIX path validation failed: java.security.cert.CertPathValidatorException: validity check failed"),
                           ("java.security.cert.CertificateExpiredException", f"NotAfter: Tue Oct 14 09:{n % 60:02d}:11 UTC 2026")]),
        ("pluginLoader", [("java.util.ServiceConfigurationError", f"com.acme.plugin.Exporter: Provider com.acme.plugin.Export{n}Impl could not be instantiated"),
                          ("java.lang.NoClassDefFoundError", f"com/acme/shared/Codec{pid}"),
                          ("java.lang.ClassNotFoundException", f"com.acme.shared.Codec{pid}")]),
        ("keystoreInit", [("java.io.UncheckedIOException", "Cannot initialise key store"),
                          ("java.io.FileNotFoundException", f"/var/lib/acme/keystore-{pid}.jks (Permission denied)")]),
    ]


def java_case(k, variant):
    cid = f"gen-java-chain-{k + 1:02d}{variant}"
    r = rng(cid)
    bean, chain = _java_chains(rng(f"java-cluster-{k}"))[k]
    noise_n = 60 if variant == "a" else 220
    lines = [f"{ts(r, i)} INFO  [main] c.a.o.Bootstrap - stage {r.randint(1, 9)} ok id={hexid(r)}" for i in range(noise_n)]
    trace = [f"{ts(r, noise_n)} ERROR [main] o.s.boot.SpringApplication - Application run failed", f"{chain[0][0]}: {chain[0][1]}"]
    trace += _frames(r, r.randint(8, 14))
    for typ, msg in chain[1:]:
        trace.append(f"Caused by: {typ}: {msg}")
        trace += _frames(r, r.randint(5, 9))
        trace.append(f"\t... {r.randint(12, 60)} common frames omitted")
    if variant == "b":
        lines = lines[:150] + trace + lines[150:] + [f"{ts(r, 999)} WARN  [main] c.a.o.Bootstrap - shutdown requested pid={r.randint(100, 999)}"]
    else:
        lines = lines + trace
    gold = [f"{chain[0][0]}: {chain[0][1]}", f"Caused by: {chain[-1][0]}: {chain[-1][1]}"]
    return make_case(cid, f"gen-java-chain-{k + 1:02d}", "trace", "trace-java", "\n".join(lines), gold, "en",
                     f"why did the {bean} service fail to start?")


# ---------------------------------------------------------------- .NET inner exceptions
def _dotnet_chains(r):
    n = r.randint(10, 99)
    gid = f"{hexid(r, 8)}-{hexid(r, 4)}"
    return [
        ("Acme.Orders.Worker", [("System.InvalidOperationException", "Failed to process message " + gid),
                                ("Microsoft.Data.SqlClient.SqlException (0x80131904)", f'Cannot open database "OrdersDb{n}" requested by the login. The login failed.'),
                                ("System.ComponentModel.Win32Exception (0x80004005)", "The wait operation timed out")]),
        ("Acme.Billing.Api", [("System.Net.Http.HttpRequestException", f"An error occurred while sending the request to billing-{n}"),
                              ("System.IO.IOException", "The response ended prematurely."),
                              ("System.Net.Sockets.SocketException (10054)", "An existing connection was forcibly closed by the remote host.")]),
        ("Acme.Catalog.Startup", [("System.AggregateException", "One or more errors occurred. (Unable to resolve service for type 'Acme.Catalog.IPriceCache')"),
                                  ("System.InvalidOperationException", f"Unable to resolve service for type 'Acme.Catalog.IPriceCache{n}' while attempting to activate 'Acme.Catalog.PriceService'.")]),
        ("Acme.Identity.Jwt", [("Microsoft.IdentityModel.Tokens.SecurityTokenException", "IDX10501: Signature validation failed."),
                               ("System.Security.Cryptography.CryptographicException", f"Keyset does not exist (kid {gid})")]),
        ("Acme.Search.Indexer", [("System.TypeInitializationException", "The type initializer for 'Acme.Search.Analyzers' threw an exception."),
                                 ("System.IO.FileNotFoundException", f"Could not load file or assembly 'Lucene.Net, Version=4.8.{n}.0' or one of its dependencies.")]),
        ("Acme.Export.Job", [("System.Threading.Tasks.TaskCanceledException", "A task was canceled."),
                             ("System.TimeoutException", f"The operation has timed out after 00:00:{n:02d} (export {gid})")]),
    ]


def _dotnet_frames(r, ns, n):
    return [f"   at {ns}.{r.choice(['Services', 'Data', 'Handlers'])}.{r.choice(['Repo', 'Client', 'Runner'])}{r.randint(1, 30)}.{r.choice(['Execute', 'GetAsync', 'Run'])}"
            f"() in /src/{ns.replace('.', '/')}/File{r.randint(1, 30)}.cs:line {r.randint(10, 900)}" for _ in range(n)]


def dotnet_case(k, variant):
    cid = f"gen-dotnet-chain-{k + 1:02d}{variant}"
    r = rng(cid)
    ns, chain = _dotnet_chains(rng(f"dotnet-cluster-{k}"))[k]
    noise_n = 50 if variant == "a" else 200
    lines = [f"info: {ns}[{r.randint(1, 9)}]\n      Handled item {r.randint(1000, 9999)} in {r.randint(1, 90)} ms" for _ in range(noise_n)]
    if variant == "a":
        trace = [f"fail: {ns}[0]\n      Unhandled exception", " ---> ".join(f"{t}: {m}" for t, m in chain),
                 "   --- End of inner exception stack trace ---"] + _dotnet_frames(r, ns, 8) + \
                ["   --- End of inner exception stack trace ---"] + _dotnet_frames(r, ns, 6)
        gold = [f"{chain[0][0]}: {chain[0][1]}", f"{chain[-1][0]}: {chain[-1][1]}"]
        text = "\n".join(lines + trace)
    else:
        trace = [f"fail: {ns}[0]\n      Unhandled exception"]
        for i, (t, m) in enumerate(chain):
            trace.append(f"{'' if i == 0 else f'---> (Inner Exception #{i - 1}) '}{t}: {m}")
            trace += _dotnet_frames(r, ns, r.randint(4, 7))
        gold = [f"{chain[0][0]}: {chain[0][1]}", f"(Inner Exception #{len(chain) - 2}) {chain[-1][0]}: {chain[-1][1]}"]
        text = "\n".join(lines[:120] + trace + lines[120:])
    return make_case(cid, f"gen-dotnet-chain-{k + 1:02d}", "trace", "trace-dotnet", text, gold, "en",
                     f"why did {ns} throw an unhandled exception?")


# ---------------------------------------------------------------- Python / Go / JS traces
def py_case(k, variant):
    cid = f"gen-pytrace-{k + 1:02d}{variant}"
    r = rng(cid)
    c = rng(f"py-cluster-{k}")
    n, rid = c.randint(100, 999), hexid(c, 6)
    ch = [("KeyError", f"'customer_{n}'", "ValueError", f"invalid order payload {rid}"),
          ("ConnectionResetError", f"[Errno 104] Connection reset by peer (host cache-{n})", "RuntimeError", f"cache fetch failed for job {rid}"),
          ("json.decoder.JSONDecodeError", f"Expecting ',' delimiter: line {n} column 12 (char {n * 40})", "ConfigError", f"cannot parse settings {rid}.json"),
          ("PermissionError", f"[Errno 13] Permission denied: '/var/run/acme-{rid}.sock'", "OSError", f"worker {n} could not bind control socket")][k % 4]
    logs = [f"{ts(r, i)} INFO app.worker handled job={hexid(r)} in {r.randint(1, 90)}ms" for i in range(80 if variant == "a" else 260)]
    frames = [("handlers", "handle", "result = process(payload)"), ("service", "process", "return self.repo.load(key)"), ("repo", "load", "return self._conn.get(key)")]

    def tb(exc, msg):
        out = ["Traceback (most recent call last):"]
        for m, f, s in frames[: r.randint(2, 3)]:
            out += [f'  File "/srv/app/{m}.py", line {r.randint(10, 400)}, in {f}', f"    {s}"]
        return out + [f"{exc}: {msg}"]

    trace = tb(ch[0], ch[1]) + ["", "The above exception was the direct cause of the following exception:", ""] + tb(ch[2], ch[3])
    lines = logs[:60] + trace + logs[60:] if variant == "b" else logs + trace
    return make_case(cid, f"gen-pytrace-{k + 1:02d}", "trace", "trace-python", "\n".join(lines),
                     [f"{ch[0]}: {ch[1]}", f"{ch[2]}: {ch[3]}"], "en", "why did the worker crash?")


def go_case(k, variant):
    cid = f"gen-gotrace-{k + 1:02d}{variant}"
    r = rng(cid)
    c = rng(f"go-cluster-{k}")
    n, rid = c.randint(100, 999), hexid(c, 6)
    msg = [f"runtime error: index out of range [{n}] with length {n - 7}", f"send on closed channel for stream {rid}",
           f"assignment to entry in nil map (tenant {rid})"][k % 3]
    logs = [f"{ts(r, i)} level=info msg=\"tick handled\" shard={r.randint(1, 16)} id={hexid(r)}" for i in range(70 if variant == "a" else 180)]
    gor = [f"panic: {msg}", "", f"goroutine {r.randint(5, 99)} [running]:"]
    for _ in range(r.randint(6, 10)):
        gor += [f"acme/internal/{r.choice(['sync', 'store', 'queue', 'api'])}.(*Worker{r.randint(1, 9)}).{r.choice(['Run', 'Flush', 'Apply'])}(0xc000{hexid(r, 6)})",
                f"\t/src/internal/file{r.randint(1, 30)}.go:{r.randint(10, 600)} +0x{hexid(r, 3)}"]
    gor += ["exit status 2"]
    return make_case(cid, f"gen-gotrace-{k + 1:02d}", "trace", "trace-go", "\n".join(logs + gor), [f"panic: {msg}", "exit status 2"], "en", "why did the worker panic?")


def js_case(k, variant):
    cid = f"gen-jstrace-{k + 1:02d}{variant}"
    r = rng(cid)
    c = rng(f"js-cluster-{k}")
    n, rid = c.randint(100, 999), hexid(c, 6)
    err = [("TypeError", f"Cannot read properties of undefined (reading 'items{n}')"), ("Error", f"connect ECONNREFUSED 10.0.{n % 250}.7:6379"),
           ("UnhandledPromiseRejection", f"This error originated by rejecting a promise with no catch handler (req {rid})")][k % 3]
    logs = [f"[{ts(r, i)}] GET /api/cart/{r.randint(1, 999)} 200 {r.randint(1, 90)}ms" for i in range(70 if variant == "a" else 200)]
    st = [f"{err[0]}: {err[1]}"] + [f"    at {r.choice(['Cart.render', 'handle', 'Layer.handle', 'processTicksAndRejections'])} (/srv/app/{r.choice(['routes', 'lib', 'node_modules/express/lib'])}/f{r.randint(1, 20)}.js:{r.randint(5, 400)}:{r.randint(1, 40)})" for _ in range(r.randint(8, 14))]
    st += [f"Node.js v20.{r.randint(1, 18)}.0"]
    text = "\n".join(logs[:50] + st + logs[50:] if variant == "b" else logs + st)
    return make_case(cid, f"gen-jstrace-{k + 1:02d}", "trace", "trace-node", text, [f"{err[0]}: {err[1]}"], "en", "why did the node process crash?")


# ---------------------------------------------------------------- build logs
def maven_case(k, variant):
    cid = f"gen-maven-{k + 1:02d}{variant}"
    r = rng(cid)
    c = rng(f"maven-cluster-{k}")
    n, mod = c.randint(10, 400), ["orders-service", "billing-core", "catalog-api", "gateway"][k % 4]
    dl = [f"[INFO] Downloaded from central: https://repo.maven.apache.org/maven2/org/acme/lib{r.randint(1, 99)}/1.{r.randint(0, 9)}.{r.randint(0, 9)}/lib-{r.randint(1, 99)}.jar ({r.randint(10, 900)} kB at {r.randint(100, 9000)} kB/s)" for _ in range(60 if variant == "a" else 200)]
    if k % 4 == 0:
        errs = [f"[ERROR] /src/{mod}/src/main/java/com/acme/Order{n}.java:[{n},17] cannot find symbol", "[ERROR]   symbol:   method getTenantId()", f"[ERROR]   location: variable order of type com.acme.Order{n}"]
        fail = f"[ERROR] Failed to execute goal org.apache.maven.plugins:maven-compiler-plugin:3.11.0:compile (default-compile) on project {mod}: Compilation failure"
        gold = [errs[0], fail]
    elif k % 4 == 1:
        errs = [f"[ERROR] Tests run: {n}, Failures: 2, Errors: 0, Skipped: 1", f"[ERROR] testRefund{n}(com.acme.BillingTest)  Time elapsed: 0.0{r.randint(1, 9)} s  <<< FAILURE!", f"java.lang.AssertionError: expected:<{n}.00> but was:<{n}.50>"]
        fail = f"[ERROR] Failed to execute goal org.apache.maven.plugins:maven-surefire-plugin:3.1.2:test (default-test) on project {mod}: There are test failures."
        gold = [errs[2], fail]
    elif k % 4 == 2:
        errs = [f"[ERROR] Failed to execute goal on project {mod}: Could not resolve dependencies for project com.acme:{mod}:jar:1.{n}-SNAPSHOT", f"[ERROR] dependency: org.acme:shared-codec:jar:2.{n}.0 (compile)", f"[ERROR]   org.acme:shared-codec:jar:2.{n}.0 was not found in https://repo.maven.apache.org/maven2 during a previous attempt"]
        fail = "[ERROR] -> [Help 1]"
        gold = [errs[0], errs[2]]
    else:
        errs = [f"[WARNING] src/main/java/com/acme/Util{n}.java:[{n}] (whitespace) FileTabCharacter: Line contains a tab character.", f"[ERROR] src/main/java/com/acme/Util{n}.java:[{n + 3}] (naming) MethodName: Method name 'Do_It{n}' must match pattern"]
        fail = f"[ERROR] Failed to execute goal org.apache.maven.plugins:maven-checkstyle-plugin:3.3.0:check (validate) on project {mod}: You have 1 Checkstyle violation."
        gold = [errs[1], fail]
    out = dl + ["[INFO] ------------------------------------------------------------------------", "[INFO] BUILD FAILURE", "[INFO] ------------------------------------------------------------------------"] + errs + [fail]
    return make_case(cid, f"gen-maven-{k + 1:02d}", "build", "build-maven", "\n".join(out), gold, "en", f"why did the maven build of {mod} fail?", tool="mvn -B clean verify")


def dotnetbuild_case(k, variant):
    cid = f"gen-dotnetbuild-{k + 1:02d}{variant}"
    r = rng(cid)
    c = rng(f"dotnetbuild-cluster-{k}")
    n = c.randint(10, 800)
    warns = [f"/src/Acme/File{r.randint(1, 60)}.cs({r.randint(1, 300)},{r.randint(1, 40)}): warning CS8618: Non-nullable property 'Name{r.randint(1, 99)}' must contain a non-null value when exiting constructor [/src/Acme/Acme.csproj]" for _ in range(40 if variant == "a" else 150)]
    errs = [[f"/src/Acme/Services/PriceService.cs({n},21): error CS0103: The name 'discountRate{n}' does not exist in the current context [/src/Acme/Acme.csproj]"],
            [f"/src/Acme/Api/Program.cs({n},5): error CS1061: 'IOrderStore' does not contain a definition for 'FetchAsync{n}' and no accessible extension method [/src/Acme/Acme.csproj]"],
            [f"/src/Acme/Acme.csproj : error NU1102: Unable to find package Acme.Shared.Codec{n} with version (>= 3.{n}.0) [/src/Acme/Acme.csproj]"]][k % 3]
    out = warns[:30] + errs + warns[30:] + ["Build FAILED.", f"    {len(warns)} Warning(s)", f"    {len(errs)} Error(s)", "Time Elapsed 00:00:12.31"]
    return make_case(cid, f"gen-dotnetbuild-{k + 1:02d}", "build", "build-dotnet", "\n".join(out), errs, "en", "why did dotnet build fail?", tool="dotnet build -c Release")


def tsc_case(k, variant):
    cid = f"gen-tsc-{k + 1:02d}{variant}"
    r = rng(cid)
    c = rng(f"tsc-cluster-{k}")
    n = c.randint(10, 800)
    err = [f"src/cart/Cart{n}.tsx({n % 90 + 1},12): error TS2339: Property 'total{n}' does not exist on type 'CartState'.",
           f"src/api/client{n}.ts({n % 70 + 1},9): error TS2345: Argument of type 'string' is not assignable to parameter of type 'OrderId{n}'.",
           f"src/store/index.ts({n % 60 + 1},1): error TS2307: Cannot find module '@acme/shared{n}' or its corresponding type declarations."][k % 3]
    noise = [f"src/lib/util{r.randint(1, 80)}.ts({r.randint(1, 200)},{r.randint(1, 40)}): error TS6133: 'tmp{r.randint(1, 99)}' is declared but its value is never read." for _ in range(25 if variant == "a" else 90)]
    out = noise[:10] + [err] + noise[10:] + [f"Found {len(noise) + 1} errors in {len(noise) + 1} files."]
    return make_case(cid, f"gen-tsc-{k + 1:02d}", "build", "build-tsc", "\n".join(out), [err], "en", "which tsc error is the real blocker?", tool="npx tsc --noEmit")


# ---------------------------------------------------------------- test-runner output
def pytest_case(k, variant):
    cid = f"gen-pytest-{k + 1:02d}{variant}"
    r = rng(cid)
    c = rng(f"pytest-cluster-{k}")
    n, tid = c.randint(10, 999), hexid(c, 6)
    name = f"test_refund_{tid}"
    out = ["============================= test session starts =============================", f"collected {40 + n % 50} items", ""]
    out += [f"tests/test_mod{i}.py {'.' * r.randint(3, 12)} [{i * 4}%]" for i in range(20 if variant == "a" else 60)]
    out += ["=================================== FAILURES ===================================", f"_________________________________ {name} _________________________________",
            f">       assert refund.amount == Decimal('{n}.00')", f"E       AssertionError: assert Decimal('{n}.50') == Decimal('{n}.00')", f"tests/test_billing.py:{n}: AssertionError"]
    out += [f"INFO billing.refund captured line {i} for {tid}" for i in range(30)]
    out += ["=========================== short test summary info ============================", f"FAILED tests/test_billing.py::{name} - AssertionError: assert Decimal('{n}.50') == Decimal('{n}.00')", "======================== 1 failed, 39 passed in 3.21s ========================"]
    return make_case(cid, f"gen-pytest-{k + 1:02d}", "test", "test-pytest", "\n".join(out), [f"AssertionError: assert Decimal('{n}.50') == Decimal('{n}.00')", f"FAILED tests/test_billing.py::{name}"], "en", f"which test failed and why? ({name})")


def jest_case(k, variant):
    cid = f"gen-jest-{k + 1:02d}{variant}"
    r = rng(cid)
    c = rng(f"jest-cluster-{k}")
    n, tid = c.randint(10, 999), hexid(c, 5)
    out = [f"PASS src/__tests__/mod{i}.test.ts ({r.randint(1, 9)}.{r.randint(0, 99)} s)" for i in range(25 if variant == "a" else 80)]
    out += [f"FAIL src/__tests__/cart{tid}.test.tsx", f"  ● Cart totals › applies discount {tid}", "", "    expect(received).toBe(expected) // Object.is equality", f"    Expected: {n}", f"    Received: {n + 5}",
            f"      at Object.<anonymous> (src/__tests__/cart{tid}.test.tsx:{n % 90 + 5}:30)", "", "Tests:       1 failed, 120 passed, 121 total"]
    return make_case(cid, f"gen-jest-{k + 1:02d}", "test", "test-jest", "\n".join(out), [f"FAIL src/__tests__/cart{tid}.test.tsx", f"Expected: {n}", f"Received: {n + 5}"], "en", "which jest test failed?")


def gotest_case(k, variant):
    cid = f"gen-gotest-{k + 1:02d}{variant}"
    r = rng(cid)
    c = rng(f"gotest-cluster-{k}")
    n, tid = c.randint(10, 999), hexid(c, 5)
    out = [f"ok  \tacme/internal/pkg{i}\t{r.randint(1, 9)}.{r.randint(0, 99)}s" for i in range(25 if variant == "a" else 90)]
    out += [f"--- FAIL: TestQueueDrain{tid} (0.0{r.randint(1, 9)}s)", f"    queue_test.go:{n}: got {n} items, want {n + 1}", "FAIL", "FAIL\tacme/internal/queue\t0.31s", "FAIL"]
    return make_case(cid, f"gen-gotest-{k + 1:02d}", "test", "test-go", "\n".join(out), [f"--- FAIL: TestQueueDrain{tid}", f"got {n} items, want {n + 1}"], "en", "which go test failed?")


def dotnettest_case(k, variant):
    cid = f"gen-dotnettest-{k + 1:02d}{variant}"
    r = rng(cid)
    c = rng(f"dotnettest-cluster-{k}")
    n, tid = c.randint(10, 999), hexid(c, 5)
    out = [f"  Passed Acme.Tests.Mod{i}.Works{r.randint(1, 9)} [{r.randint(1, 90)} ms]" for i in range(30 if variant == "a" else 100)]
    out += [f"  Failed Acme.Tests.Orders.Total_{tid} [{r.randint(1, 90)} ms]", "  Error Message:", "   Assert.Equal() Failure: Values differ", f"Expected: {n}.00", f"Actual:   {n}.50",
            "  Stack Trace:", f"     at Acme.Tests.Orders.Total_{tid}() in /src/tests/Orders.cs:line {n}", "", "Failed!  - Failed:     1, Passed:   120, Skipped:     0, Total:   121"]
    return make_case(cid, f"gen-dotnettest-{k + 1:02d}", "test", "test-dotnet", "\n".join(out), [f"Failed Acme.Tests.Orders.Total_{tid}", f"Expected: {n}.00", f"Actual:   {n}.50"], "en", "which dotnet test failed and why?")


def surefire_case(k, variant):
    cid = f"gen-surefire-{k + 1:02d}{variant}"
    r = rng(cid)
    c = rng(f"surefire-cluster-{k}")
    n, tid = c.randint(10, 999), hexid(c, 5)
    out = [f"[INFO] Tests run: {r.randint(2, 20)}, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: {r.randint(0, 3)}.{r.randint(10, 99)} s - in com.acme.Mod{i}Test" for i in range(25 if variant == "a" else 90)]
    out += [f"[ERROR] Tests run: 3, Failures: 1, Errors: 0, Skipped: 0, Time elapsed: 0.04 s <<< FAILURE! - in com.acme.Ledger{tid}Test", f"[ERROR] com.acme.Ledger{tid}Test.balance  Time elapsed: 0.01 s  <<< FAILURE!",
            f"org.opentest4j.AssertionFailedError: expected: <{n}> but was: <{n + 2}>", f"\tat com.acme.Ledger{tid}Test.balance(Ledger{tid}Test.java:{n % 80 + 10})", "[ERROR] Failed to execute goal org.apache.maven.plugins:maven-surefire-plugin:3.1.2:test"]
    return make_case(cid, f"gen-surefire-{k + 1:02d}", "test", "test-surefire", "\n".join(out), [f"Ledger{tid}Test.balance", f"expected: <{n}> but was: <{n + 2}>"], "en", "which junit test failed?", tool="mvn test")


# ---------------------------------------------------------------- mixedlang_zh
def _zh_lines(r, n, kind):
    verbs = ["处理请求成功", "缓存命中", "任务已调度", "连接池检查通过"]
    return [f"{ts(r, i)} 信息 {kind}服务 {r.choice(verbs)} 编号={hexid(r)} 耗时={r.randint(1, 90)}毫秒" for i in range(n)]


def mixed_cases():
    out = []
    zh_tasks = ["为什么构建失败了？", "请找出导致崩溃的根本原因。", "哪个测试失败了，原因是什么？", "数据库连接为什么超时？", "这个异常是由哪个底层错误引起的？", "启动失败的原因是什么？"]
    for k in range(6):          # (a) Chinese task against an English log
        for v in "ab":
            cid = f"mixedlang_zh-zhq-{k + 1:02d}{v}"
            r, c = rng(cid), rng(f"zhq-cluster-{k}")
            n, rid = c.randint(100, 999), hexid(c, 6)
            noise = [f"{ts(r, i)} INFO  worker handled job={hexid(r)} in {r.randint(1, 90)}ms" for i in range(70 if v == "a" else 200)]
            kind = k % 3
            if kind == 0:
                core = [f"ERROR build step failed: cannot resolve module 'acme-{rid}' (exit code {n % 200 + 1})", f"npm ERR! code E404 package acme-{rid}@^{n}.0.0 not found"]
                shape, ctype, tool = "build-log", "build", "npm ci"
            elif kind == 1:
                core = [f'Exception in thread "main" java.lang.IllegalStateException: pool {rid} exhausted', f"Caused by: java.net.SocketTimeoutException: Read timed out after {n}ms"]
                shape, ctype, tool = "trace-java", "trace", "java -jar app.jar"
            else:
                core = [f"FAILED tests/test_pay_{rid}.py::test_capture - AssertionError: expected {n} got {n + 1}", f"E   KeyError: 'ledger_{rid}'"]
                shape, ctype, tool = "test-pytest", "test", "pytest -x"
            out.append(make_case(cid, f"mixedlang_zh-zhq-{k + 1:02d}", ctype, shape, "\n".join(noise[:40] + core + noise[40:]), core, "mixed", zh_tasks[k], tool=tool))
    en_tasks = ["why did the payment gateway time out?", "which order failed and with what error?", "what caused the database connection error?", "which service reported the failure?", "what error did the scheduler raise?"]
    for k in range(5):          # (b) English ask against a Chinese log
        for v in "ab":
            cid = f"mixedlang_zh-enq-{k + 1:02d}{v}"
            r, c = rng(cid), rng(f"enq-cluster-{k}")
            n, rid = c.randint(100, 999), hexid(c, 6)
            noise = _zh_lines(r, 80 if v == "a" else 220, "订单")
            core = [f"{ts(c, 5)} 错误 支付网关 连接超时: 订单号=ORD-{n}{rid[:3]} 重试次数={n % 5 + 1}", f"{ts(c, 6)} 错误 调度器 任务{rid}失败: 无法获取数据库连接 (主机 db-{n}.内部)"][: 1 + k % 2]
            core.append(f"原因: 连接被拒绝 端口 {5000 + n}")
            out.append(make_case(cid, f"mixedlang_zh-enq-{k + 1:02d}", "log", "mixedlang_zh", "\n".join(noise[:50] + core + noise[50:]), core, "mixed", en_tasks[k], tool="tail -n 300 logs/app.log"))
    zz = ["支付网关为什么超时了？", "哪个订单失败了，错误是什么？", "数据库连接错误的原因是什么？", "调度器报了什么错误？", "缓存服务为什么不可用？"]
    for k in range(5):          # (c) Chinese logs, Chinese queries
        for v in "ab":
            cid = f"mixedlang_zh-zhzh-{k + 1:02d}{v}"
            r, c = rng(cid), rng(f"zhzh-cluster-{k}")
            n, rid = c.randint(100, 999), hexid(c, 6)
            noise = _zh_lines(r, 80 if v == "a" else 220, "库存")
            core = [f"{ts(c, 5)} 错误 缓存服务 节点不可用: 键=商品{n}{rid[:2]} 超时={n}毫秒", f"异常: java.io.IOException: 连接被对方重置 (序列号 {rid})", "导致: 库存同步任务已中止"]
            out.append(make_case(cid, f"mixedlang_zh-zhzh-{k + 1:02d}", "log", "mixedlang_zh", "\n".join(noise[:60] + core + noise[60:]), core, "zh", zz[k], tool="tail -n 300 logs/app.log"))
    return out


def generated_cases():
    out = []
    for k in range(6):
        for v in "ab":
            out += [java_case(k, v), dotnet_case(k, v)]
    for k in range(4):
        for v in "ab":
            out += [py_case(k, v), maven_case(k, v)]
    for k in range(3):
        for v in "ab":
            out += [go_case(k, v), js_case(k, v), dotnetbuild_case(k, v), tsc_case(k, v),
                    pytest_case(k, v), jest_case(k, v), gotest_case(k, v), dotnettest_case(k, v), surefire_case(k, v)]
    return out + mixed_cases()
