"""Direct synchronous orchestration for the V1 pipeline."""

from typing import Protocol

from backend.app.collector import RawRedditCapture
from backend.app.extractor import Complaint
from backend.app.normalizer import NormalizedPost


class Collector(Protocol):
    """Collector dependency required by the pipeline."""

    def fetch_post(self, url: str) -> RawRedditCapture: ...


class Normalizer(Protocol):
    """Normalizer dependency required by the pipeline."""

    def normalize(self, raw: RawRedditCapture) -> NormalizedPost: ...


class Extractor(Protocol):
    """Extractor dependency required by the pipeline."""

    def extract(self, normalized: NormalizedPost) -> Complaint: ...


class Validator(Protocol):
    """Final validator dependency required by the pipeline."""

    def validate(
        self,
        complaint: Complaint,
        normalized: NormalizedPost,
    ) -> Complaint: ...


class SynchronousPipeline:
    """Run collector → normalizer → extractor → validator in the caller."""

    def __init__(
        self,
        collector: Collector,
        normalizer: Normalizer,
        extractor: Extractor,
        validator: Validator,
    ) -> None:
        self._collector = collector
        self._normalizer = normalizer
        self._extractor = extractor
        self._validator = validator

    def process_url(self, url: str) -> Complaint:
        """Collect and process one Reddit URL synchronously."""

        return self.process_post(self._collector.fetch_post(url))

    def process_post(self, post: RawRedditCapture) -> Complaint:
        """Process one already-collected RawReddit capture synchronously."""

        normalized = self._normalizer.normalize(post)
        complaint = self._extractor.extract(normalized)
        return self._validator.validate(complaint, normalized)
