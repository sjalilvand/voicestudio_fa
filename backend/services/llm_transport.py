"""Provider SDK adapters. Importing the catalogue never imports cloud SDKs."""
from __future__ import annotations

import os
from types import SimpleNamespace


def create_client(provider):
    from services import llm_providers as registry
    if provider.transport == "openai":
        from openai import OpenAI
        return OpenAI(api_key=registry.resolve_api_key(provider),
                      base_url=registry.resolve_base_url(provider), max_retries=0)
    if provider.transport == "cli":
        from services.llm_cli import completion
        create = lambda **kwargs: completion(provider, **kwargs)
    else:
        create = lambda **kwargs: sdk_completion(provider, **kwargs)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def sdk_completion(provider, **kwargs):
    # LiteLLM's remote pricing fetch and telemetry are unnecessary for inference.
    # Set before its lazy import; opening settings must never trigger either.
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    os.environ["LITELLM_TELEMETRY"] = "False"
    import litellm
    from services import llm_providers as registry
    litellm.telemetry = False
    model = kwargs.pop("model")
    prefix = provider.sdk_provider
    if prefix and not model.startswith(prefix + "/"):
        model = prefix + "/" + model
    key = registry.resolve_api_key(provider)
    base = registry.resolve_base_url(provider)
    if key and key != "local":
        kwargs["aws_bearer_token_bedrock" if provider.id == "bedrock" else "api_key"] = key
    if base:
        kwargs["api_base"] = base
    if provider.id == "vertex":
        kwargs["vertex_project"] = registry.resolve_account_id(provider)
        kwargs["vertex_location"] = os.environ.get("VERTEXAI_LOCATION", "global")
    kwargs.update(num_retries=0, drop_params=True)
    return litellm.completion(model=model, **kwargs)
