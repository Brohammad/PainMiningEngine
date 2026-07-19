"""Direct synchronous orchestration for the V1 pipeline."""

from typing import Protocol
from uuid import UUID

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


class StageStorage(Protocol):
    """Independent insert-only persistence required by a durable pipeline."""

    def save_raw(self, post: RawRedditCapture) -> UUID: ...

    def save_normalized(
        self,
        post: NormalizedPost,
        raw_post_id: UUID,
    ) -> UUID: ...

    def save_complaint(
        self,
        complaint: Complaint,
        normalized_post_id: UUID,
    ) -> UUID: ...


class SynchronousPipeline:
    """Run collector → normalizer → extractor → validator in the caller."""

    def __init__(
        self,
        collector: Collector,
        normalizer: Normalizer,
        extractor: Extractor,
        validator: Validator,
        storage: StageStorage | None = None,
    ) -> None:
        self._collector = collector
        self._normalizer = normalizer
        self._extractor = extractor
        self._validator = validator
        self._storage = storage

    def process_url(self, url: str) -> Complaint:
        """Collect and process one Reddit URL synchronously."""

        return self.process_post(self._collector.fetch_post(url))

    def process_post(self, post: RawRedditCapture) -> Complaint:
        """Process one already-collected RawReddit capture synchronously."""

        raw_post_id = self._storage.save_raw(post) if self._storage else None
        normalized = self._normalizer.normalize(post)
        normalized_post_id = (
            self._storage.save_normalized(normalized, raw_post_id)
            if self._storage is not None and raw_post_id is not None
            else None
        )
        complaint = self._extractor.extract(normalized)
        validated = self._validator.validate(complaint, normalized)
        if self._storage is not None and normalized_post_id is not None:
            self._storage.save_complaint(validated, normalized_post_id)
        return validated
