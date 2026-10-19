"""Preview immutable Gaussian rows and publish corrected ObjectGS output atomically."""

import hashlib
import json
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock

import numpy as np

from src.config import Settings, get_settings
from src.models.contracts.artifacts import ProductArtifactRef
from src.models.contracts.manifests import StageId
from src.models.contracts.object_membership import (
    ObjectMembershipArtifact,
    ObjectMembershipPreview,
    ObjectMembershipReassignCommand,
)
from src.models.contracts.scene import SceneIR
from src.services.orchestration.artifacts import ArtifactResolver, FilesystemArtifactStore
from src.services.orchestration.jobs.database import RuntimeTransaction
from src.services.orchestration.jobs.stage_views import job_bundle
from src.services.orchestration.projects.registry import ProjectRegistry
from src.services.orchestration.scene.editor import SceneEditor
from src.services.orchestration.scene.object_geometry_build import MembershipOverride, build_object_geometry
from src.services.orchestration.scene.objectify import (
    _ensure_not_cancelled,
    _reference,
)
from src.services.scene.decomposition.gaussian_split import positions, read_gaussian_ply
from src.services.scene.editing.membership import (
    ObjectMembershipValidationError,
    decode_gaussian_membership_labels,
    encode_gaussian_membership_labels,
    select_source_gaussians,
    validate_object_membership_command,
)
from src.services.scene.floor_model import above_floor_mask, fit_canonical_floor_model, point_cloud_checksum
from src.services.scene.geometry_state import object_geometry_state


@dataclass(frozen=True)
class MembershipSource:
    positions: np.ndarray
    rows: np.ndarray
    labels: np.ndarray
    manifest: ObjectMembershipArtifact
    floor_protected: np.ndarray | None


def _load_membership_source(
    resolver: ArtifactResolver, membership: ObjectMembershipArtifact, *, protect_floor: bool
) -> MembershipSource:
    payload = resolver.require(membership.source_visual_ref).read_bytes()
    if "sha256:" + hashlib.sha256(payload).hexdigest() != membership.source_visual_ref.artifact_checksum:
        raise ObjectMembershipValidationError("source PLY checksum mismatch")
    rows = read_gaussian_ply(payload)
    xyz = positions(rows)
    labels = decode_gaussian_membership_labels(resolver.require(membership.labels_ref).read_bytes(), membership)
    protected = None
    if protect_floor:
        floor = fit_canonical_floor_model(xyz, point_cloud_checksum(xyz))
        protected = ~above_floor_mask(xyz, floor)
    return MembershipSource(xyz, rows, labels, membership, protected)


_SourceArrays = tuple[np.ndarray, np.ndarray, np.ndarray | None]


@dataclass(frozen=True)
class _CachedSource:
    arrays: _SourceArrays
    nbytes: int


#: Khoá theo PLY nguồn (bất biến) chứ không theo nhãn: Apply đổi nhãn nhưng không đổi PLY, nên không đọc lại PLY (T-025).
_SOURCE_CACHE: OrderedDict[tuple[str, str], _CachedSource] = OrderedDict()
#: Một lần đọc PLY đang chạy cho mỗi khoá; yêu cầu khác cùng khoá chờ kết quả đó thay vì đọc lại.
_SOURCE_PENDING: dict[tuple[str, str], Future] = {}
#: Khoá chỉ bảo vệ hai bảng trên, không giữ khi đọc PLY hay fit sàn.
_SOURCE_LOCK = Lock()


def _source_cache_budget() -> int:
    return get_settings().product_region_source_cache_mib << 20


def _evict_over_budget(budget: int) -> None:
    """Bỏ mục cũ nhất cho tới khi dưới ngân sách byte; mục vừa đọc luôn được giữ. Gọi khi đã giữ `_SOURCE_LOCK`."""
    while len(_SOURCE_CACHE) > 1 and sum(item.nbytes for item in _SOURCE_CACHE.values()) > budget:
        _SOURCE_CACHE.popitem(last=False)


def _source_arrays(registry: ProjectRegistry, job_id: str, membership: ObjectMembershipArtifact) -> _SourceArrays:
    key = (job_id, membership.source_visual_ref.artifact_checksum)
    with _SOURCE_LOCK:
        cached = _SOURCE_CACHE.get(key)
        if cached is not None:
            _SOURCE_CACHE.move_to_end(key)
            return cached.arrays
        pending = _SOURCE_PENDING.get(key)
        owner = pending is None
        if owner:
            pending = _SOURCE_PENDING[key] = Future()
    if not owner:
        return pending.result()
    try:
        source = _load_membership_source(registry.runtime_resolver, membership, protect_floor=True)
        arrays: _SourceArrays = (source.positions, source.rows, source.floor_protected)
        for array in arrays:
            if array is not None:
                array.setflags(write=False)
        nbytes = sum(array.nbytes for array in arrays if array is not None)
        with _SOURCE_LOCK:
            _SOURCE_CACHE[key] = _CachedSource(arrays, nbytes)
            _SOURCE_CACHE.move_to_end(key)
            _evict_over_budget(_source_cache_budget())
        pending.set_result(arrays)
        return arrays
    except BaseException as error:
        pending.set_exception(error)
        raise
    finally:
        with _SOURCE_LOCK:
            _SOURCE_PENDING.pop(key, None)


def load_membership_source(registry: ProjectRegistry, job_id: str, scene: SceneIR) -> MembershipSource:
    """Cache immutable world rows/floor only; always decode a fresh current label array."""
    membership = scene.environment.membership
    if membership is None:
        raise ObjectMembershipValidationError("scene has no persisted Gaussian membership")
    positions, rows, floor_protected = _source_arrays(registry, job_id, membership)
    labels = decode_gaussian_membership_labels(
        registry.runtime_resolver.require(membership.labels_ref).read_bytes(), membership
    )
    return MembershipSource(positions, rows, labels, membership, floor_protected)


def prepare_correction(
    editor: SceneEditor, job_id: str, command: ObjectMembershipReassignCommand
) -> tuple[SceneIR, ObjectMembershipArtifact, np.ndarray, dict[str, object]]:
    scene = editor.current(job_id).scene
    membership = validate_object_membership_command(scene, command)
    source = _load_membership_source(editor.resolver, membership, protect_floor=command.source_object_id is None)
    xyz, labels, protected = source.positions, source.labels, source.floor_protected
    selected, preview = select_source_gaussians(
        xyz,
        labels,
        membership,
        command,
        protected=protected,
    )
    updated = labels.copy()
    target_labels = [
        int(key) for key, owner in membership.label_to_object_id.items() if owner == command.target_object_id
    ]
    updated[selected] = min(target_labels) if target_labels else -1
    preview["remaining_gaussians"] = {
        owner: int(
            np.isin(updated, [int(key) for key, bound in membership.label_to_object_id.items() if bound == owner]).sum()
        )
        for owner in preview["affected_object_ids"]
    }
    return scene, membership, updated, preview


def preview_correction(
    editor: SceneEditor, job_id: str, command: ObjectMembershipReassignCommand
) -> ObjectMembershipPreview:
    """Read-only; Apply must submit the identical revision/checksum-bound command."""
    return ObjectMembershipPreview.model_validate(prepare_correction(editor, job_id, command)[3])


def regenerate_membership(
    registry: ProjectRegistry,
    job_id: str,
    settings: Settings,
    workspace: Path,
    *,
    command: ObjectMembershipReassignCommand,
    actor_id: str,
    expected_revision: str,
    commit_guard: Callable[[RuntimeTransaction], bool] | None = None,
    cancel_event: Event | None = None,
    progress: Callable[[str], None] | None = None,
) -> str:
    _ensure_not_cancelled(cancel_event)
    if command.expected_scene_revision != expected_revision:
        raise ObjectMembershipValidationError("correction command and queue base revision differ")
    scene, membership, labels, preview = prepare_correction(registry.scene, job_id, command)
    if object_geometry_state(scene) != "ready":
        raise ObjectMembershipValidationError("queued membership regeneration requires a Ready scene")
    if scene.environment.collision_selection_ref is not None:
        raise ObjectMembershipValidationError("correct the source scene before selecting another collision source")
    if any(count < 50 for count in preview["remaining_gaussians"].values()):
        raise ObjectMembershipValidationError(
            "correction must retain at least 50 Gaussians per object; use Delete for removal"
        )
    job = registry.get_job(job_id)
    bundle = job_bundle(registry, job)
    if bundle is None or bundle.canonical_geometry_ref != membership.source_geometry_ref:
        raise ObjectMembershipValidationError("correction reconstruction source geometry mismatch")
    store = FilesystemArtifactStore(registry.runtime_resolver)

    def publish(reference: ProductArtifactRef, payload: bytes) -> ProductArtifactRef:
        if registry.runtime_resolver.locate(reference.artifact_uri) is not None:
            if registry.runtime_resolver.require(reference).read_bytes() != payload:
                raise ObjectMembershipValidationError("immutable correction artifact bytes differ")
            registry.runtime_resolver.published(reference.artifact_uri)
            return reference
        return store.publish(reference, payload)

    mapping = {}
    for owner in sorted(set(membership.label_to_object_id.values())):
        owner_labels = [int(key) for key, value in membership.label_to_object_id.items() if value == owner]
        label = min(owner_labels)
        labels[np.isin(labels, owner_labels)] = label
        mapping[str(label)] = owner
    mapping = dict(sorted(mapping.items(), key=lambda pair: int(pair[0])))
    payload = encode_gaussian_membership_labels(
        labels, gaussian_count=membership.gaussian_count, label_to_object_id=mapping
    )
    labels_ref = publish(
        _reference(
            job_id, "objects/membership/{digest}.i32le", "ObjectMembershipLabels", StageId.SCENE_DECOMPOSE, payload
        ),
        payload,
    )
    corrected = membership.model_copy(update={"labels_ref": labels_ref, "label_to_object_id": mapping}, deep=True)
    correction_payload = json.dumps(
        {
            "operation": "reassign",
            "actor_id": actor_id,
            "command": command.model_dump(mode="json"),
            "preview": preview,
            "source_membership": membership.model_dump(mode="json"),
            "corrected_membership": corrected.model_dump(mode="json"),
        },
        sort_keys=True,
    ).encode()
    correction_ref = publish(
        _reference(
            job_id,
            "objects/corrections/{digest}.json",
            "ObjectMembershipCorrection",
            StageId.SCENE_DECOMPOSE,
            correction_payload,
        ),
        correction_payload,
    )
    _ensure_not_cancelled(cancel_event)
    return build_object_geometry(
        registry,
        settings,
        job_id,
        expected_revision=expected_revision,
        workspace=workspace,
        object_ids=set(preview["affected_object_ids"]),
        membership_override=MembershipOverride(labels, corrected, correction_ref),
        commit_guard=commit_guard,
        cancel_event=cancel_event,
        progress=progress,
    )
