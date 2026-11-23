from tameru import agent_extractive_engine as agent
from tameru import hermes_extractive_engine as hermes
from tameru import transcript


def test_transcript_aliases_export_the_same_public_helpers():
    assert set(agent.__all__) == set(hermes.__all__)
    for name in hermes.__all__:
        assert getattr(agent, name) is getattr(transcript, name)
