from dataclasses import dataclass

from services.engine_evidence import snapshot
from api.public_engine_metadata import public_backends


@dataclass
class _Caps:
    family: str = "rocm"
    device_name: str = "AMD Radeon RX 6700 XT"


class _TorchEngine:
    gpu_compat = ("rocm", "cpu")
    _device = "cuda:0"
    _dtype = "float16"


class _FasterWhisper:
    gpu_compat = ("cuda", "cpu")
    _device = "cpu"
    _compute_type = "int8"


class _OnnxEngine:
    gpu_compat = ("cpu",)
    _provider = "CPUExecutionProvider"
    _dtype = "int8"


class _SidecarEngine:
    gpu_compat = ("rocm", "cpu")
    runs_out_of_process = True
    _device = "cuda:0"


class _LoadFallbackEngine:
    gpu_compat = ("cuda", "cpu")
    _device = "cpu"
    _fallback_reason = "CUDA memory was exhausted while loading the engine"
    _fallback_stage = "model_load"


def _snap(cls, routing):
    return snapshot(
        engine_id=cls.__name__, engine_cls=cls, instance=cls(), routing=routing, caps=_Caps()
    )


def test_loaded_rocm_torch_engine_reports_actual_device():
    evidence = _snap(_TorchEngine, {"routing_status": "accelerated", "routing_reason": None})
    assert evidence["actual_execution_device"] == "cuda:0"
    assert evidence["precision_or_quantization"] == "float16"
    assert evidence["gpu_name"] == "AMD Radeon RX 6700 XT"


def test_faster_whisper_cpu_fallback_names_reason_and_stage():
    evidence = _snap(
        _FasterWhisper,
        {"routing_status": "cpu_fallback", "routing_reason": "ROCm is unsupported"},
    )
    assert evidence["actual_execution_device"] == "cpu"
    assert evidence["cpu_fallback_reason"] == "ROCm is unsupported"
    assert evidence["cpu_fallback_stage"] == "routing_preflight"


def test_cpu_onnx_and_subprocess_observability_are_explicit():
    cpu = _snap(_OnnxEngine, {"routing_status": "cpu_only", "routing_reason": None})
    sidecar = _snap(_SidecarEngine, {"routing_status": "accelerated", "routing_reason": None})
    assert cpu["actual_execution_provider"] == "CPUExecutionProvider"
    assert cpu["parent_memory_observable"] is True
    assert sidecar["parent_memory_observable"] is False


def test_public_inventory_replaces_nested_private_fallback_detail():
    entry = {
        "routing_status": "cpu_fallback",
        "routing_reason": "/home/alice/private driver error",
        "execution_evidence": {"cpu_fallback_reason": "/home/alice/private driver error"},
    }
    public = public_backends([entry])[0]
    assert "alice" not in public["routing_reason"]
    assert "alice" not in public["execution_evidence"]["cpu_fallback_reason"]


def test_post_load_fallback_overrides_preflight_prediction():
    evidence = _snap(
        _LoadFallbackEngine,
        {"routing_status": "accelerated", "routing_reason": None},
    )
    assert evidence["actual_execution_device"] == "cpu"
    assert evidence["cpu_fallback_stage"] == "model_load"
    assert "memory" in evidence["cpu_fallback_reason"]
