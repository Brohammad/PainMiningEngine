"""Source-aware normalizer dispatch."""

from backend.app.collector.sources import DiscussionSource
from backend.app.collector.types import RawDiscussion
from backend.app.normalizer.github import GitHubNormalizer
from backend.app.normalizer.reddit import NormalizedPost, RedditNormalizer


class DispatchingNormalizer:
    """Route RawDiscussion captures to the correct source normalizer."""

    def __init__(
        self,
        *,
        reddit: RedditNormalizer | None = None,
        github: GitHubNormalizer | None = None,
    ) -> None:
        self._normalizers = {
            DiscussionSource.REDDIT.value: reddit or RedditNormalizer(),
            DiscussionSource.GITHUB.value: github or GitHubNormalizer(),
        }

    def normalize(self, discussion: RawDiscussion) -> NormalizedPost:
        source = str(discussion["source"])
        normalizer = self._normalizers.get(source)
        if normalizer is None:
            raise ValueError(f"no normalizer registered for source: {source}")
        return normalizer.normalize(discussion)
