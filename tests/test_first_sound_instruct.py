"""The actual onboarding defaults must pass the runtime engine validator."""
import json
from pathlib import Path

from omnivoice.models.omnivoice import _resolve_instruct


def test_first_sound_instruction_passes_runtime_taxonomy_validation():
    defaults = json.loads(
        (Path(__file__).parents[1] / "frontend/src/utils/firstSound.json").read_text()
    )
    instruct = defaults["instruct"]
    # VoiceDesign requires a nonempty description; OmniVoice validates tokens.
    assert instruct.strip()
    assert _resolve_instruct(instruct) == instruct
    assert _resolve_instruct(instruct, use_zh=True)
