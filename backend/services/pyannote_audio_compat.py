"""Compatibility surface for pyannote.audio on recent torchaudio releases."""

from functools import wraps
from numbers import Integral
from threading import RLock
from typing import NamedTuple


class AudioMetaData(NamedTuple):
    sample_rate: int
    num_frames: int
    num_channels: int
    bits_per_sample: int
    encoding: str


_INSTALL_LOCK = RLock()
_WRAPPER_MARKER = "_voicestudio_pyannote_soundfile_adapter"


def _sample_width(subtype: str) -> int:
    for prefix in ("PCM_", "DWVW_", "DPCM_", "ALAC_"):
        if subtype.startswith(prefix) and subtype[len(prefix):].isdigit():
            return int(subtype[len(prefix):])
    if subtype in {"PCM_U8", "PCM_S8", "ULAW", "ALAW"}:
        return 8
    if subtype == "FLOAT":
        return 32
    if subtype == "DOUBLE":
        return 64
    return 0


def _legacy_encoding(container: str, subtype: str) -> str:
    if container == "FLAC":
        return "FLAC"
    if subtype == "PCM_U8":
        return "PCM_U"
    if subtype.startswith("PCM_"):
        return "PCM_S"
    if subtype in {"FLOAT", "DOUBLE"}:
        return "PCM_F"
    if subtype in {"ULAW", "ALAW", "VORBIS"}:
        return subtype
    return "UNKNOWN"


# CLEAN-ROOM (spec W11-residue §B1): soundfile-backed replacement for torchaudio.info (_soundfile_info)


# CLEAN-ROOM (spec W11-residue §B2): soundfile-backed loader used for backend="soundfile" (_soundfile_load)


# CLEAN-ROOM (spec W11-residue §B3): replacement for torchaudio.list_audio_backends (_backends)


def ensure_pyannote_audio_compat() -> bool:
    """Install the legacy audio entry points needed by pyannote.audio 3.x."""
    import torchaudio

    with _INSTALL_LOCK:
        legacy_names = ("AudioMetaData", "info", "list_audio_backends")
        if all(hasattr(torchaudio, name) for name in legacy_names):
            return False

        import soundfile

        if not callable(getattr(soundfile, "SoundFile", None)):
            raise TypeError("The pyannote audio adapter needs a callable soundfile.SoundFile")
        current_load = getattr(torchaudio, "load", None)
        if not callable(current_load):
            raise TypeError("The torchaudio loader is unavailable to the pyannote audio adapter")

        if not getattr(current_load, _WRAPPER_MARKER, False):
            original_load = current_load

            @wraps(original_load)
            def compatible_load(*args, **kwargs):
                requested_backend = kwargs.get("backend")
                if "backend" not in kwargs and len(args) > 7:
                    requested_backend = args[7]
                if requested_backend == "soundfile":
                    return _soundfile_load(*args, **kwargs)
                return original_load(*args, **kwargs)

            setattr(compatible_load, _WRAPPER_MARKER, True)
            torchaudio.load = compatible_load

        replacements = {
            "AudioMetaData": AudioMetaData,
            "info": _soundfile_info,
            "list_audio_backends": _backends,
        }
        for name, replacement in replacements.items():
            if not hasattr(torchaudio, name):
                setattr(torchaudio, name, replacement)
        return True
