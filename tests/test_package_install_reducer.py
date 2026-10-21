from tameru.agent_formats import detect_test_runner, preprocess_test_output


def test_composer_package_install_reducer() -> None:
    text = (
        "Loading composer repositories with package information\n"
        "Updating dependencies\n"
        + "\n".join(f"  - Locking vendor/pkg{i} (v{i}.0.0)" for i in range(20))
        + "\nYour requirements could not be resolved to an installable set of packages.\n"
        "  Problem 1\n"
        "    - laravel/framework v11.9.0 requires php ^8.2 -> your php version (8.1.27) does not satisfy that requirement.\n"
    )

    assert detect_test_runner(text) == "package_install"

    out = preprocess_test_output(text, "")
    assert out is not None
    assert "php ^8.2" in out
    assert "8.1.27" in out
    assert "Problem 1" in out
    assert "vendor/pkg7" not in out
    assert "package lines omitted" in out
    assert len(out) < len(text) * 0.6


def test_npm_package_install_reducer() -> None:
    text = (
        "\n".join(
            f"npm WARN deprecated pkg{i}@1.{i}.0: This package is no longer supported."
            for i in range(25)
        )
        + "\nnpm ERR! code ERESOLVE\n"
        "npm ERR! ERESOLVE unable to resolve dependency tree\n"
        "npm ERR! Found: react@18.3.1\n"
        'npm ERR! Could not resolve dependency: peer react@"^17.0.0" from legacy-modal@2.1.0\n'
    )

    assert detect_test_runner(text) == "package_install"

    out = preprocess_test_output(text, "")
    assert out is not None
    assert "ERESOLVE" in out
    assert "legacy-modal@2.1.0" in out
    assert "pkg3@" not in out
    assert len(out) < len(text) * 0.4


def test_deprecated_package_named_in_error_is_kept() -> None:
    text = (
        "\n".join(f"npm WARN deprecated pkg{i}@1.0.0: old" for i in range(6))
        + "\nnpm WARN deprecated legacy-modal@2.1.0: unmaintained\n"
        'npm ERR! Could not resolve dependency: peer react@"^17.0.0" from legacy-modal@2.1.0\n'
    )

    out = preprocess_test_output(text, "")
    assert out is not None
    assert "npm WARN deprecated legacy-modal@2.1.0: unmaintained" in out
    assert "pkg2@" not in out


def test_yarn_package_install_reducer() -> None:
    text = (
        "yarn install v1.22.22\n"
        "[1/4] Resolving packages...\n"
        + "\n".join(
            f'warning pkg{i}@2.{i}.0: The engine "vscode" appears to be invalid.'
            for i in range(10)
        )
        + '\nerror Couldn\'t find package "left-padx@^1.3.0" required by "web-app@0.1.0" on the "npm" registry.\n'
    )

    assert detect_test_runner(text) == "package_install"

    out = preprocess_test_output(text, "")
    assert out is not None
    assert "left-padx@^1.3.0" in out
    assert "yarn install v1.22.22" in out
    assert "pkg4@" not in out


def test_short_npm_run_is_not_detected() -> None:
    assert detect_test_runner("npm WARN deprecated a@1.0.0: old\nadded 3 packages\n") is None
