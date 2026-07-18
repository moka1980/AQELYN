"""In-memory append-only IdentityDetectionStore (EA-0027 I3)."""

from __future__ import annotations

import copy

from aqelyn.conventions.errors import (
    CrossTenantReference,
    IdentityNotFound,
    OptimisticConcurrencyConflict,
)
from aqelyn.idthreat.models import (
    DetectionType,
    IdentityDetection,
    IdentityReview,
    IdThreatConfig,
)
from aqelyn.idthreat.store import (
    validate_detection,
    validate_detection_id,
    validate_detection_type_filter,
    validate_limit,
    validate_new_detection,
    validate_review,
    validate_subject_filter,
    validate_tenant,
)


class InMemoryIdentityDetectionStore:
    def __init__(self, *, config: IdThreatConfig, mode: str = "local") -> None:
        self.config = config
        self.mode = mode
        self._records: dict[str, IdentityDetection] = {}
        self._reviews: dict[str, IdentityReview] = {}

    async def put(self, detection: IdentityDetection) -> IdentityDetection:
        stored = validate_new_detection(detection, config=self.config)
        existing = self._records.get(stored.id)
        if existing is not None:
            if existing.tenant_id != stored.tenant_id:
                raise CrossTenantReference("identity detection tenant_id cannot change")
            raise OptimisticConcurrencyConflict("identity detections are append-only")
        self._records[stored.id] = stored.model_copy(deep=True)
        return copy.deepcopy(stored)

    async def get(
        self,
        detection_id: str,
        *,
        tenant_id: str | None,
    ) -> IdentityDetection | None:
        validate_detection_id(detection_id)
        selected_tenant = validate_tenant(tenant_id)
        record = self._records.get(detection_id)
        if record is None or not self._visible(record.tenant_id, selected_tenant):
            return None
        return self._materialize(record)

    async def query(
        self,
        *,
        tenant_id: str | None,
        subject_ref: str | None = None,
        detection_type: DetectionType | None = None,
        limit: int = 100,
    ) -> list[IdentityDetection]:
        selected_tenant = validate_tenant(tenant_id)
        selected_subject = validate_subject_filter(subject_ref)
        selected_type = validate_detection_type_filter(detection_type)
        selected_limit = validate_limit(limit)
        rows = [
            self._materialize(record)
            for record in self._records.values()
            if self._visible(record.tenant_id, selected_tenant)
            and (selected_subject is None or record.subject_ref == selected_subject)
            and (selected_type is None or record.detection_type == selected_type)
        ]
        rows.sort(key=lambda record: (record.detected_at, record.id))
        return rows[:selected_limit]

    async def record_review(self, review: IdentityReview) -> IdentityReview:
        stored = validate_review(review)
        detection = self._records.get(stored.detection_id)
        if detection is None:
            raise IdentityNotFound(stored.detection_id)
        if detection.tenant_id != stored.tenant_id:
            raise CrossTenantReference("identity review tenant does not match detection")
        if stored.detection_id in self._reviews:
            raise OptimisticConcurrencyConflict("identity detection is already reviewed")
        self._reviews[stored.detection_id] = stored.model_copy(deep=True)
        return copy.deepcopy(stored)

    async def review_for(
        self,
        detection_id: str,
        *,
        tenant_id: str | None,
    ) -> IdentityReview | None:
        validate_detection_id(detection_id)
        selected_tenant = validate_tenant(tenant_id)
        review = self._reviews.get(detection_id)
        if review is None or not self._visible(review.tenant_id, selected_tenant):
            return None
        return copy.deepcopy(review)

    def _materialize(self, detection: IdentityDetection) -> IdentityDetection:
        status = "reviewed" if detection.id in self._reviews else detection.status
        selected = detection.model_copy(update={"status": status}, deep=True)
        return validate_detection(selected, config=self.config)

    def _visible(self, row_tenant_id: str | None, requested_tenant_id: str | None) -> bool:
        if self.mode == "local" and row_tenant_id is not None:
            return False
        return requested_tenant_id is None or row_tenant_id == requested_tenant_id
