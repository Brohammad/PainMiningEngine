"""Schema and provenance validation boundary."""

from backend.app.validator.complaint import (
    ComplaintValidationError,
    ComplaintValidator,
)

__all__ = ["ComplaintValidationError", "ComplaintValidator"]
