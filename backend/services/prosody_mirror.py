# CLEAN-ROOM (spec A §2): implement this module. The helper below is maintainer code; keep it.
import numpy as np


# A channel average that keeps less than this share of the loudest channel's
# energy means the channels largely cancel (an out-of-phase pair).
_PHASE_CANCEL_RATIO = 0.5


def _downmix(audio: np.ndarray) -> np.ndarray:
    """Average channels, unless they cancel: then use the loudest channel.

    Out-of-phase stereo averages to near silence, which would read as "no
    speech". The loudest channel alone still carries the delivery.
    """
    mixed = audio.mean(axis=1)
    channel_rms = np.sqrt(np.mean(np.square(audio, dtype=np.float64), axis=0))
    loudest = int(np.argmax(channel_rms))
    mixed_rms = float(np.sqrt(np.mean(np.square(mixed, dtype=np.float64))))
    if mixed_rms < _PHASE_CANCEL_RATIO * float(channel_rms[loudest]):
        return audio[:, loudest]
    return mixed
