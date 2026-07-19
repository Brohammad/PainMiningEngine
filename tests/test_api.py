"""REST API contract and dependency-injection tests."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from backend.app.api import ApiContainer, create_app
from backend.app.api.services import (
    ComplaintQueryService,
    HealthService,
    MetricsService,
    ProcessingService,
)
from backend.app.schemas import (
    Complaint,
    ExtractionMeta,
    TextField,
    TriStateField,
)
from backend.app.storage import StageCounts

COMPLAINT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
DOCUMENT_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def make_complaint() -> Complaint:
    empty = TextField(value=None, evidence=[])
    return Complaint(
        pain_summary=empty,
        workflow=empty,
        workaround=empty,
        buyer=empty,
        budget_owner=TriStateField(value="unknown", evidence=[]),
        time_cost=empty,
        industry=empty,
        existing_tools=[],
        meta=ExtractionMeta(
            model="test-model",
            prompt_version="extract_v1",
            source_id="t3_test",
            document_id=DOCUMENT_ID,
            extracted_at=datetime(2026, 7, 19, 12, 30, tzinfo=UTC),
        ),
    )


class StaticPipeline:
    def __init__(self, complaint: Complaint) -> None:
        self.complaint = complaint
        self.urls: list[str] = []

    def process_url(self, url: str) -> Complaint:
        self.urls.append(url)
        return self.complaint


class MemoryStore:
    def __init__(self) -> None:
        self.complaints: dict[UUID, Complaint] = {}
        self.health_checks = 0

    def save_complaint(
        self,
        complaint: Complaint,
        normalized_post_id: UUID,
    ) -> UUID:
        assert normalized_post_id == complaint.meta.document_id
        self.complaints[COMPLAINT_ID] = complaint
        return COMPLAINT_ID

    def get_complaint(self, complaint_id: UUID) -> Complaint | None:
        return self.complaints.get(complaint_id)

    def count_stages(self) -> StageCounts:
        return StageCounts(raw_posts=3, normalized_posts=2, complaints=1)

    def check_health(self) -> None:
        self.health_checks += 1


def make_client() -> tuple[TestClient, StaticPipeline, MemoryStore]:
    complaint = make_complaint()
    pipeline = StaticPipeline(complaint)
    store = MemoryStore()
    container = ApiContainer(
        processing=ProcessingService(pipeline, store),
        complaints=ComplaintQueryService(store),
        health=HealthService(store),
        metrics=MetricsService(store),
    )
    return TestClient(create_app(container)), pipeline, store


def test_process_uses_injected_pipeline_and_returns_persisted_id() -> None:
    client, pipeline, _store = make_client()

    response = client.post(
        "/process",
        json={"url": "https://www.reddit.com/r/devops/comments/test/"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(COMPLAINT_ID)
    assert response.json()["complaint"]["meta"]["document_id"] == str(DOCUMENT_ID)
    assert pipeline.urls == ["https://www.reddit.com/r/devops/comments/test/"]


def test_get_complaint_returns_saved_result_and_404_for_missing_id() -> None:
    client, _pipeline, _store = make_client()
    client.post(
        "/process",
        json={"url": "https://www.reddit.com/r/devops/comments/test/"},
    )

    found = client.get(f"/complaints/{COMPLAINT_ID}")
    missing = client.get("/complaints/cccccccc-cccc-4ccc-8ccc-cccccccccccc")

    assert found.status_code == 200
    assert found.json()["id"] == str(COMPLAINT_ID)
    assert missing.status_code == 404
    assert "not found" in missing.json()["detail"]


def test_health_and_metrics_delegate_to_injected_services() -> None:
    client, _pipeline, store = make_client()

    health = client.get("/health")
    metrics = client.get("/metrics")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert store.health_checks == 1
    assert metrics.status_code == 200
    assert metrics.json() == {
        "raw_posts": 3,
        "normalized_posts": 2,
        "complaints": 1,
    }


def test_process_rejects_invalid_or_extra_request_fields() -> None:
    client, _pipeline, _store = make_client()

    invalid_url = client.post("/process", json={"url": "not-a-url"})
    extra_field = client.post(
        "/process",
        json={
            "url": "https://www.reddit.com/r/devops/comments/test/",
            "unexpected": True,
        },
    )

    assert invalid_url.status_code == 422
    assert extra_field.status_code == 422
