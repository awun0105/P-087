# Execution Plan: Studio data và deployment packaging

Date: 2026-10-03

## Status

Completed — packaging và local Linux proof. Cấu hình canonical Dockerfile/Compose, requirements offline Open3D 0.19.0, COMPOSE_FILE một lệnh và production templates theo ADR 0003 đã được xác thực thành công.

## Outcome

Đã xuất ZIP dữ liệu thật, giữ mật khẩu hai seed theo yêu cầu owner; bổ sung
source ZIP tương thích, một lệnh Compose và templates/runbook production theo
ADR 0003. Không đổi schema, job state, checksum, privacy gate hoặc policy review.

## Task Capsule And Authority

- Task/outcome: phân phối trạng thái Studio đã lưu cho teammate; đóng gói
  dependency/runtime startup và handoff production split-service.
- Authority: `AGENTS.md`, `docs/WORKFLOW.md`, `ARCHITECTURE.md`, `docs/PRD.md`,
  `docs/execution/TEAM_EXECUTION_CONTRACT.md`, `RUNTIME_POLICY.md`,
  `INTEGRATION_PLAYBOOK.md`, `TRACK_IMPLEMENTATION_GUIDE.md`, track `ex_product`,
  PRODUCT-08/12 và accepted ADR 0003.
- Dependencies: canonical SQLite/artifacts/demo/preview/Rerun của app nguồn;
  Docker Engine 29.8.0, Compose 5.5.1; external drive `/media/usb` writable.
- Inputs/outputs: snapshot nguồn → ZIP inventory/checksum → validated restore;
  source + packaging → API/web images; ZIP → default non-mutating production
  dry-run và explicit PostgreSQL/R2 import/provision commands.
- Owned paths: Studio packaging scripts/tests, Dockerfiles/Compose, deploy/studio,
  Makefile.studio, ignores, lockfile repair, distribution guide, README và plan này.
- Do not modify: source data/job state, REC/SCENE/SIM algorithms, shared contracts,
  task acceptance, unrelated contributor changes, Git refs hoặc cloud accounts.
- Proof: round-trip/negative tests, real ZIP verify/account comparison, real
  image builds/Compose restore/auth/HTTP artifact bytes, production dry-run.
- Limits: browser unavailable; NVIDIA/CUDA/Vulkan và provider access chưa có proof.

## Context And Decisions

- 2026-10-03 follow-up: owner yêu cầu làm sạch repo, thay cấu hình scaffold cũ khi
  đã có bản mới thay thế; không giữ song song chỉ vì nguồn gốc template. Quyền
  này áp dụng dependency/Docker packaging, không mở rộng sang source scaffold
  hoặc thay đổi product/contracts. Không có yêu cầu commit/push rõ ràng.
- Cleanup plan: hợp nhất Dockerfile.studio vào root Dockerfile; thay root Compose
  bằng stack Studio; GPU override canonical docker-compose.gpu.yml; đồng bộ refs.
  Gộp requirements-lidar vào offline.in/lock đúng Open3D0.19/Pydantic/settings;
  bỏ requirements.txt cũ và file nested sau proof. Core/dev locks giữ nguyên.
  Làm mới source ZIP/receipt/runbook trên ổ ngoài; data ZIP và seed giữ nguyên.

- Bootstrap branch `feat/pipeline-v2`, HEAD `b05b45b`; concurrent source commits
  được giữ nguyên. Không commit/push/merge/branch switch trong work này.
- App không dùng `data/real2sim-team-data` làm source. Source thật là
  `data/studio_local/runtime.db`, artifacts, thumbnail_cache, demo/library,
  asset_previews và rerun_recordings.
- Owner chọn external drive và yêu cầu giữ đúng hai seed accounts. ZIP giữ
  user identity/role/password hash/active, bỏ sessions/invites/transient worker
  credentials. Không ghi password plaintext hay provider key vào gói.
- Source job đang chờ thao tác metric được giữ trạng thái; không giả success,
  không bind lại runtime/checksum. Pack từ chối active processing/scene requests
  và nonempty trash, kiểm source logical fingerprint và file identities.
- `COMPRESSION=stored` rút ngắn capture window cho binary đã compressed.
- Compose dùng `python -m scripts.studio.container_entrypoint`, init bounded
  directories, UID1000, auto-restore chỉ khi chưa có DB. Symlink và unsafe archive
  bị từ chối. Restart không thêm account hoặc overwrite DB.
- Backend `linux/amd64`: usd-core26.8 CPython312 chưa có Linux ARM64 wheel.
  `STUDIO_BUILD_NETWORK=host` chỉ là workaround Linux bridge DNS của máy này;
  default portable vẫn là `default`.
- Production topology: Vercel UI, Railway API, Supabase PostgreSQL, Cloudflare R2,
  Vast.ai worker và RunPod fallback. Không dùng SQLite độc lập làm remote queue.
- Local `develop`/`origin/develop` ở `bdc4b92` khi audit, chưa có đầy đủ source đang
  dùng. Source ZIP được gửi cùng data, giải nén vào folder riêng; không ghi đè
  checkout teammate. Source snapshot base `fa6d5aa2f42bbaa586d7c7bd3cb1005801dea117`
  cộng packaging overlay; SOURCE_MANIFEST.json ghi hash từng file.

## Implementation Plan And Progress

- [x] Canonical Dockerfiles/Compose và reference migration.
- [x] Canonical offline requirements và fresh-env LiDAR CLI proof.
- [x] Narrow authority/onboarding updates và obsolete-file removal audit.
- [x] Rebuild/real ZIP Compose proof và refresh external source/receipt.

- [x] Inspect authority, source configuration, dependency manifests và data closure.
- [x] Implement pack/verify/unpack, seed policy, SQLite scrub/VACUUM, source-change
  detection, checksum/reference closure, unsafe-path/collision/rollback guards.
- [x] Compose API/web, GPU override, module entrypoint, volume permissions và
  focused positive/negative proof.
- [x] Production environment templates, Railway/Vercel manifests, publisher
  dry-run/apply, optional-volume provisioning và truthful runbook.
- [x] Export/verify real ZIP, build/restore/run isolated stack, observe HTTP data.
- [x] Final parent review và external source ZIP/instructions/checksum/receipt.

## Validation

VERIFIED real data package:

- `/media/usb/real2sim-team-data/r2s-studio-data.zip`: 2,969,912,392 bytes.
- 1,421 payload files, 2,969,063,274 payload bytes, five projects/scenes,
  1,233 artifact references. `data-verify KEEP_SEED_ACCOUNTS=1` exit0.
- ZIP SHA256: `49ce10d6731e88339267d1047303ab941fc4ceb65f05ee93b6d09efded69aa89`.
- Source/package `(user_id,password_hash,active)` comparison matches exactly two
  seed users. Archived sessions0/invites0; source sessions unchanged.
- Read-only logical fingerprint still equals package capture at final HTTP proof.
  Source API8010/web3010 kept running throughout.

VERIFIED executable checks:

```text
.venv/bin/python -m pytest tests/test_packaging tests/test_orchestration/test_runtime_migrations.py -q
56 passed, 4 skipped (5.29s)

ruff check scripts/studio/data_package.py scripts/studio/container_entrypoint.py scripts/cloud/package_publish.py tests/test_packaging
All checks passed

ruff format --check [same paths]
6 files already formatted

docker compose config --quiet (CPU and CPU+GPU override)
exit0

git diff --check
exit0
```

- Broader auth/studio/scene API/service suite: 77 passed, 9 skipped at earlier
  source revision (fixture proof). It is not a claim of the full current suite.
- Final source catalog/scene API suite: `.venv/bin/python -m pytest
  tests/test_api/test_scene_v2_routes.py -q`: 19 passed (1.23s).
- Actual API image and editor-aware frontend build passed: npm ci, editor build,
  Next build/TypeScript; no framework upgrade. Corrected missing optional
  @emnapi1.11.3 lock entries only.
- Actual Compose `up --build -d --wait` restored the real ZIP: 1,421 files/five
  projects, initially exactly two active seed users, zero sessions. API/web
  healthy; repeated `up --no-build -d --wait` preserves data.
- Last API image: `sha256:afceaa7dff6d44a20a4fe11e1485096d56833aaeb97154576a2a8faf38fea5d6`.
  Web image: `sha256:e25254a26f02a158fc29f94df70e412d2f3e6f5e75b2b84718b49ee01ca9d2b0`.
- Runtime UID1000, source .env absent from image, packaging script hashes match
  worktree. Real bounded-root volume prepare/drop proof yields UID/GID1000 and
  writable thumbnail cache. Railway documents `RAILWAY_RUN_UID=0` support.
- Isolated auth HTTP proof uses one temporary fixture Reviewer in the restored
  test copy only. Original DB/archive retain two seed accounts. No source user,
  password or session was altered for proof.
- HTTP via Next proxy: anonymous management401, fixture login/me200 and cookie
  session; five scenes, two samples,34 previews; five artifact lists/stage views/
  JPEG thumbnails; SOG/GLB/Rerun range206 with actual bytes. Both sample manifests
  and splat-file ranges also passed. No browser visual claim.
- Final real ZIP production CLI default dry-run exit0: schema8; users2,
  projects5/jobs5/events49/uploads9/imports1/scene_requests1/audit48/resource_usage0.
  Target `/tmp/r2s-production-dryrun-target.db` was not created. Parser regression
  tests cover null artifact events, arbitrary canonical URI aliases and bad
  nested checksums. No PostgreSQL/R2/cloud mutation was performed.
- External receipt `VERIFICATION.json` records final ZIP hashes, source manifest,
  image identity, tests and observations. Source ZIP own hash remains outside
  this included plan to avoid a circular hash.

## Failed Attempts And Recovery

- Initial preserved-seed pack rejected changed SQLite file metadata; logical DB
  contents and payload files were stable. Packer now uses device/inode and logical
  fingerprint (including retained hashes/active), with WAL mutation/replacement
  negatives. Retry succeeded; partial ZIPs removed.
- Default Docker bridge DNS failed; Linux host-network build succeeded without
  daemon changes. First frontend npm ci exposed missing transitive lock entries;
  repaired and actual builds passed.
- First Compose API serve failed direct-script `src` import. All entrypoints now
  use module invocation; subprocess proof explicitly unsets PYTHONPATH.
- First production dry-run rejected valid null artifact events. Shared-verifier
  semantics restored; alias/nested-reference checks and final real dry-run pass.

## Remaining External Acceptance And Risks

- Real GPU image/job, Windows/WSL2, macOS/ARM and browser visual QA unverified.
  CPU Compose does not provide NVIDIA processing; GPU hosts use the override,
  other teammates use a shared Linux GPU deployment with PostgreSQL/R2.
- Provider deployments, actual PostgreSQL migration/R2 apply, Vercel cookies and
  remote-worker/browser acceptance have not run.
- Rented worker currently receives shared PG/R2 credentials; accepted least-
  privilege/token boundary is unimplemented. Do not call it production-ready.
- Production template retains `qa_verified`; current new-video route accepts
  only `self_attested`, so production video upload remains closed pending the
  approved QA/policy implementation. Packaging does not weaken this gate.
- Current source includes34 CC0/procedural catalog previews in the tracked
  configs, preferred in every environment (accepted ADR0010 section3). Converted
  Isaac fallback stays disabled on staging/production. Source bundle contains
  these new files; existing data ZIP remains unchanged.
- Demo/preview/Rerun use one Railway `/app/data` volume, not shared multi-region
  state. Provision still stages the full~2.97GB payload; run TMPDIR on that volume
  and allow ZIP + staging + copied auxiliary capacity.
- Accepted monitoring, uptime checks, DB keepalive and nightly pg_dump→R2 retention7
  are operational follow-up; no configured/deployed proof from this packaging.
- Unsaved browser view state and private provider keys are not part of data.

## Result

Local packaging outcome complete; files delivered on the external drive with
instructions and verification receipt. Git refs and provider accounts untouched.
The remaining items above require their actual GPU/OS/cloud environments or
owner policy work; they are not hidden behind local test success.
