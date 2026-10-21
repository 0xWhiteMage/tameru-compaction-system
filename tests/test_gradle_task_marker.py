from tameru.agent_formats import detect_test_runner, preprocess_test_output


def test_gradle_task_marker():
    text = "\n".join(f"> Task :lib{i}:compileJava UP-TO-DATE" for i in range(30)) + "\n> Task :app:compileJava FAILED\n/repo/app/src/main/java/com/acme/Billing.java:42: error: cannot find symbol\n        Invoice inv = InvoiceFactory.create(order);\n                      ^\n  symbol:   variable InvoiceFactory\n  location: class Billing\n1 error\n\nFAILURE: Build failed with an exception.\n"
    assert detect_test_runner(text) == "gradle"
    out = preprocess_test_output(text)
    assert out
    assert "[\u2026 30 gradle tasks omitted \u2026]" in out
    assert "passing suites" not in out
    assert "Billing.java:42: error: cannot find symbol" in out
    assert "> Task :app:compileJava FAILED" in out
