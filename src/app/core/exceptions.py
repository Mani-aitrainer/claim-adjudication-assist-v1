"""Application-wide exception types."""


class AppError(Exception):
    """Base class for all application-raised errors."""


class AgentConfigError(AppError):
    """Raised when config/agents.yaml is missing, malformed, or references an unknown agent key."""


class LLMFactoryError(AppError):
    """Raised when an LLM client cannot be constructed for a given agent key."""


class OCRServiceError(AppError):
    """Raised when the OCR provider fails (e.g. a Textract service error)."""
