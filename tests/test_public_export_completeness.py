import tameru


def test_all_public_names_resolve():
    for name in tameru.__all__:
        assert getattr(tameru, name) is not None


def test_lazy_exports_are_public():
    lazy = (tameru._ENGINE_EXPORTS | tameru._DECIDE_EXPORTS
            | tameru._LOSS_EXPORTS | tameru._PLAN_EXPORTS)
    assert lazy <= set(tameru.__all__)
