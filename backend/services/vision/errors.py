"""Vision service errors (torch-free so the API layer and cloud provider can use them)."""


class VisionModelError(RuntimeError):
    """The model cannot be made available (missing/altered checkpoint, bad device)."""


class VisionProviderUnavailable(RuntimeError):
    """The configured provider cannot serve requests (HTTP 503)."""


class InvalidImageError(ValueError):
    """Input is corrupt, empty, or cannot be decoded (HTTP 400)."""


class UnsupportedImageError(ValueError):
    """Input is well-formed but not a supported type or radiograph (HTTP 415/422)."""

    def __init__(self, message: str, media_type: bool = False):
        super().__init__(message)
        self.media_type = media_type


class UnknownTargetError(ValueError):
    """Requested Grad-CAM target is not one of the model outputs (HTTP 422)."""
