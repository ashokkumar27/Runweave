"""Client construction is called only outside deterministic workflows."""

import os

from openai import DefaultAsyncHttpxClient
from pydantic_ai.models import Model
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider


class OwnedClient:
    """Close SDK clients built by this adapter after the outermost model scope."""

    async def __aenter__(self):
        await super().__aenter__()
        self.runtime_entries = getattr(self, "runtime_entries", 0) + 1
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await super().__aexit__(exc_type, exc_val, exc_tb)
        self.runtime_entries -= 1
        if self.runtime_entries == 0:
            await self.client.close()


class OwnedOpenAIProvider(OwnedClient, OpenAIProvider):
    pass


class OwnedAnthropicProvider(OwnedClient, AnthropicProvider):
    pass


class SelectionModel(Model):
    """Connection-free workflow metadata; actual requests resolve inside activities."""

    def __init__(self, identity):
        super().__init__(profile={"supports_tools": True, "default_structured_output_mode": "tool"})
        self.identity = identity

    @property
    def model_name(self):
        return self.identity

    @property
    def system(self):
        return "registry"

    async def request(self, *args, **kwargs):
        raise RuntimeError("Model I/O requires an activity")


async def strip_authorization(request):
    request.headers.pop("authorization", None)


def build_model(registration, *, http_client=None):
    if not registration.tool_calling:
        raise ValueError("Model does not support required tool calling")
    if not registration.available():
        raise ValueError("provider_not_configured")
    if registration.adapter == "fake":
        from .runtime import fake_model

        return fake_model
    profile = {"supports_tools": True, "default_structured_output_mode": "tool"}
    key = os.environ[registration.credential_env] if registration.auth == "env" else "unused-local-no-auth"
    if registration.adapter in {"openai_responses", "openai_chat"}:
        from openai import AsyncOpenAI
        from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel

        # An inert placeholder prevents ambient OPENAI_API_KEY inheritance. Remove
        # the header so unauthenticated compatible servers receive no bearer token.
        if registration.auth == "none":
            http_client = http_client or DefaultAsyncHttpxClient()
            http_client.event_hooks["request"].append(strip_authorization)
        client = AsyncOpenAI(
            api_key=key,
            admin_api_key="",
            webhook_secret="",
            base_url=registration.endpoint,
            organization="",
            project="",
            max_retries=0,
            http_client=http_client,
        )
        cls = OpenAIChatModel if registration.adapter == "openai_chat" else OpenAIResponsesModel
        return cls(
            registration.upstream_model, provider=OwnedOpenAIProvider(openai_client=client), profile=profile
        )
    from anthropic import AsyncAnthropic
    from pydantic_ai.models.anthropic import AnthropicModel

    client = AsyncAnthropic(
        api_key=key, auth_token="", base_url=registration.endpoint, max_retries=0, http_client=http_client
    )
    return AnthropicModel(
        registration.upstream_model, provider=OwnedAnthropicProvider(anthropic_client=client), profile=profile
    )
