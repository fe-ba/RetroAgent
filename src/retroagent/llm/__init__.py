"""The provider adapter: the only component that talks to a model (ADR-0003).

``LiteLLMProvider`` lives in ``retroagent.llm.litellm_provider`` and is not imported here, so importing this package
does not load LiteLLM.
"""

from retroagent.llm.fake import FakeProvider
from retroagent.llm.provider import (
    AuthenticationRejected,
    Capabilities,
    ContextWindowExceeded,
    InvalidRequest,
    LLMProvider,
    Message,
    MissingCredential,
    ProviderError,
    ProviderUnavailable,
    QuotaExhausted,
    RateLimitExceeded,
    Request,
    Response,
    ToolCall,
    ToolDefinition,
    Usage,
    Wait,
    request_from_profile,
)

__all__ = [
    "AuthenticationRejected",
    "Capabilities",
    "ContextWindowExceeded",
    "FakeProvider",
    "InvalidRequest",
    "LLMProvider",
    "Message",
    "MissingCredential",
    "ProviderError",
    "ProviderUnavailable",
    "QuotaExhausted",
    "RateLimitExceeded",
    "Request",
    "Response",
    "ToolCall",
    "ToolDefinition",
    "Usage",
    "Wait",
    "request_from_profile",
]
