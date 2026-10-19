# RunPod auto provisioning và scale-to-zero — source audit và implementation plan

## 1. Trạng thái và phạm vi

- Ngày: 2026-10-19. Base HEAD: `45cd6f43d9a5276b3287975b403edc2ad213d2df`.
- Audit gồm cả thay đổi **chưa commit** đang có trong workspace, đặc biệt distributed demo. Khi implement phải kiểm tra lại diff; không coi HEAD là toàn bộ baseline.
- Yêu cầu điều khiển lượt này: **audit prompt, inspect code, tạo plan; chưa implement**. Những câu “implement now” trong phụ lục là nội dung prompt được audit, không mở rộng phạm vi lượt này.
- Không dùng docs/reports/README làm bằng chứng về hành vi. Không đọc telemetry report mà prompt gợi ý; thay bằng worker, queue, admission và publication code hiện tại. CodeGraph/graphify dùng để định vị, kết luận đối chiếu source trên đĩa.
- Không sửa source/config/secret, không chạy tests hoặc gọi cloud, không commit/push. Chỉ tạo file plan này.
- User xác nhận: bucket **`real2sim`**, Supabase đã active, RunPod đã có credit. Đây là thông tin user cung cấp, chưa kiểm tra live trong audit. Khi implement sửa bucket trong private deployment configuration từ giá trị dự kiến cũ; không ghi credentials vào plan/repo.
- Credit không phải chấp thuận chi tiêu. Chưa có trần USD/giờ hoặc ngân sách tổng được duyệt. Mọi live GPU test vẫn bị khóa đến khi có phê duyệt cụ thể.

## 2. Kết luận audit prompt

**Hợp lý về mục tiêu, nhưng chưa đủ chính xác để giao implement nguyên trạng mà không có các bổ sung bên dưới.** Giữ PostgreSQL queue, worker và R2; bổ sung control plane RunPod, không chuyển sang Serverless.

| Điểm cần làm rõ | Điều chỉnh bắt buộc |
| --- | --- |
| Scale 0 → 1 không được phụ thuộc worker đang online | Release capability/image catalog bền vững cho first boot, enqueue và chọn runtime. Heartbeat chỉ chứng minh liveness. |
| “Mọi GPU work” không đồng nghĩa mọi queue cần GPU | Tách demand làm bật GPU với active execution/publication đang giữ Pod. CPU-only cần execution lane tồn tại khi GPU=0. |
| Runtime của job đã có stage | Khởi động image có software identity tương thích, không bỏ job chỉ vì worker hết TTL; không tùy tiện rebind job đã có stage. |
| Một Pod không đồng nghĩa một worker | `STUDIO_WORKERS=1` ban đầu; vẫn kiểm kê mọi process/reservation, demo child và các phần CPU của job. |
| List/name không tự tạo idempotency cho create | Durable intent trước HTTP; timeout thành UNKNOWN và reconcile, không POST lại mù. Tính nhất quán/list pagination và ownership phải được kiểm chứng. |
| Drain phải đóng race với claim | Gate trong transaction của từng queue claim, main và demo cùng nhìn deployment control state; supervisor và child đều tuân thủ. |
| Health khi không có GPU | API vẫn healthy khi worker=0. Tách control plane readiness khỏi compute availability. |
| Watchdog ngoài Pod | Controller sống cùng API có thể xử lý worker chết; không bảo đảm cleanup nếu toàn bộ Railway/control plane ngừng hoạt động. Cần failsafe độc lập hoặc công khai giới hạn, không hứa vô điều kiện. |
| Max lifetime/budget không cắt job khỏe | Chuyển sang drain, ngừng nhận mới, giữ lease/publication. Hard cap không thể đồng thời bảo đảm không gián đoạn job dài tùy ý. |
| Production-ready toàn bộ pipeline | Image hiện tại chưa cung cấp Isaac runtime. Không được đánh dấu validation supported chỉ vì queue/worker Python tồn tại. |

## 3. Bằng chứng từ code hiện tại

Các line anchor là snapshot lúc audit, có thể thay đổi khi implement.

| Source | Điều xác nhận |
| --- | --- |
| `scripts/cloud/gpu_autoscaler.py:92,105,117,126,298,334` | Provider protocol chỉ state/start/stop; Vast.ai; workload chỉ main jobs + scene requests; `last_active` trong RAM; không có durable controller election/drain/cost ledger. `runnable_waiting` dựa live runtime, sai cho staged jobs khi scale=0. |
| `src/services/orchestration/jobs/worker_cli.py:209,329,345,374,483` | Dispatch, job lease, expired recovery; chỉ rebind queued job chưa có stage; loop chạy pipeline → registration → validation → scene → import → demo. Recovery job chết đưa FAILED retryable, không có nghĩa tự rerun thành công. |
| `src/services/orchestration/jobs/queue.py:129` | Có hàm semantic `waiting_jobs`; cần dùng cùng điều kiện chờ review/finalize, không COUNT mọi RUNNING. |
| `src/services/orchestration/jobs/database.py:61,110,267,290,363,417,438,450` | Có jobs, scene requests, import operations, validation operations, registration operations, worker runtimes, job leases; migration mới nhất trong workspace là 24 cho demo control tables. |
| `src/services/orchestration/jobs/database.py:479–540` | PostgreSQL scope qua URL fragment regex `r2s_demo_<32hex>`, `SET LOCAL search_path`, kiểm namespace, không fallback public; connection mở/đóng theo transaction. |
| `src/services/orchestration/samples/distributed.py:48,151,174,219` | Reserve schema, ownership advisory transaction locks, enumerate open sessions, purge schemas/output prefixes. Không scan arbitrary `pg_namespace` rồi quản lý mọi schema có tên giống demo. |
| `src/services/orchestration/samples/session_worker.py:43,72,104,173,215` | Demo pending có pipeline/registration/validation/scene, không có import lane; parent giữ main admission reservation, child dùng DB/schema/prefix riêng, process tree bị dừng khi session đóng. Baseline profile mặc định GPU-required nên chưa là classifier CPU/GPU chính xác. |
| `src/services/orchestration/jobs/lease.py:57,69,90,123` | Lease token và fencing khi ghi job, thread renew trong attempt; phải giữ semantics này. |
| `src/services/orchestration/jobs/worker_runtimes.py:103,139,155` | Publish runtime, select ưu tiên live rồi newest, liveness/checksum riêng. Không có persisted RunPod identity/Pod readiness. |
| `src/services/orchestration/jobs/profile.py:13–31,63–80` | Software checksum loại GPU/VRAM/driver; cùng software có thể chạy trên GPU khác. Không được đồng nhất full hardware checksum với compatibility. |
| `src/services/orchestration/projects/registry.py:1877–1904` | Profile worker cũ có thể dùng để enqueue; chưa worker nào từng publish và không profile ghim thì job mới bị từ chối. Đây là first-boot circular dependency phải giải quyết. |
| `src/api/studio/assemblies.py:440` | API có profile availability gate trước run; phải kiểm cả API paths, không chỉ sửa autoscaler. |
| `src/services/orchestration/inputs/assembly.py:364` | Input qualification registry thiếu thì capabilities rỗng; không giả qualification từ tên GPU/image. |
| `src/services/orchestration/jobs/registration_worker.py:205,408–440` | Registration claim/heartbeat/publication; resource profile CPU-only, VRAM 0. |
| `src/services/orchestration/review/validation_worker.py:80,161,465` | Durable validation + lease/reservation giữ qua publication; cần runtime Isaac và GPU profile thực. |
| `src/services/orchestration/scene/objectify_queue.py:489,522,557,697,775,819` | Queue có recovery/lease/fencing/progress; GPU classification phụ thuộc mode và `box_candidates_require_gpu`, không chỉ tên mesh. |
| `src/services/orchestration/uploads/scene_imports.py:1135,1294` | Import là durable operation; SOG/CPU hoặc packaging có GPU tùy input và gpu_index; phải tính cả queue này. |
| `src/services/orchestration/jobs/admission.py:94–140` | Reservation bind job/operation, heartbeat, GPU-required riêng; CPU task vẫn giữ RAM/disk trên Pod. |
| `src/services/orchestration/processing/telemetry.py:60–81,159`; `jobs/runner.py:351–414` | Có sampled duration, peak RAM/VRAM/scratch và persisted resource usage theo attempt/runtime/config; best effort, có thể null/lỗi. Không là provider billing ledger hoặc đầy đủ pipeline/human timing. |
| `src/services/orchestration/artifacts/store.py:64,98,181,195`; `artifacts/remote.py:134,160,307` | Fetch verify SHA, immutable remote push, metadata checksum; không thay bằng ETag/“file local tồn tại”. |
| `src/api/studio/uploads.py:326,350` | Direct multipart có complete API; không cần truyền video trong create Pod request. |
| `src/main.py:21–57,106–138` | Lifespan có demo bootstrap/janitor, chưa GPU controller. `/ready` hiện đòi live worker, sẽ 503 khi scale=0; Railway hiện healthcheck `/health`. |
| `deploy/studio/railway-api.json` | Một API service start bằng container_entrypoint serve; chưa có scheduler/controller độc lập hiện hữu. |
| `Dockerfile.gpu:25–35,54–72`; `scripts/gpu/docker_entrypoint.sh` | CUDA 12.6.3, Vulkan/graphics, torch build arches 7.5/8.0/8.6/8.9, install native scene/ObjectGS, runtime manifest/qualification lúc boot, worker manager. Chưa chứng minh mọi GPU mới tương thích. |
| `scripts/gpu/make_runtime_manifest.py:37–66` | Runtime probing ghi Isaac/OpenUSD UNVERIFIED; image không có Isaac install stage. |
| `src/services/orchestration/samples/release.py:225–242` | ZIP + extracted staging cùng volume. P0 bootstrap disk vẫn tồn tại, tách ticket; không đổi trong GPU task. |

### 3.1 Workload inventory phải trở thành adapter có tests

| Nguồn | Schema / identity | Làm bật GPU? | Chặn shutdown khi đã chạy trên Pod? |
| --- | --- | --- | --- |
| Preview/reconstruction, reviewed preview, finalize | Main và demo `r2s_jobs` + `r2s_job_leases`, key `(scope, job_id, attempt)` | Có khi next executable phase cần GPU; exclude chờ metric/privacy/review/human | Có, gồm CPU prep/COLMAP phase, R2 finalization và CAS terminal state |
| Segmentation/ObjectGS/mesh/collider/membership/region | `r2s_scene_requests`, mode/config, operation id + generation | Theo classifier dùng chung với worker; mode hiện tại ở line 819 | Có đến finish commit và trả reservation |
| Registration | `r2s_registration_operations`, operation id + fencing token | Không cho algorithm hiện tại | Có nếu execution đang ở Pod; nếu chỉ queued thì route CPU lane |
| Isaac validation | `r2s_validation_operations` cùng validation run | Có, chỉ image đã qualify Isaac | Có, cả CLAIMED/CANCEL_REQUESTED, exporter/upload và terminal write |
| Import/packaging | Main `r2s_import_operations` + imports/uploads | Theo format/gpu_index và actual supported packaging | Có; SOG CPU vẫn không được cắt khi đang publish |
| Private demo | Chỉ sessions đã reserve/publish, scope fragment validated | Hợp tất cả các loại được demo hỗ trợ, không đếm session mở nhưng idle | Parent shared reservation + scoped leases + child heartbeat + publication |
| Browser edit/view/Walk, upload đang nhập, user confirmation | Không phải GPU execution queue | Không | Chỉ operation thực sự đã claim/đang finalize mới giữ Pod |

Không đếm trùng scene task như một pipeline job mới. Số đếm phải kèm lý do/kind/scope, không chỉ tổng integer. `CANCEL_REQUESTED` đang chạy giữ Pod; queued cancel chưa chạy không làm bật GPU. Unknown/corrupt/inaccessible scope không được coi là empty để terminate.

## 4. Thiết kế đề xuất

### 4.1 Deployment và ownership

- Một controller process CPU trong **cùng Railway API container**, do container supervisor khởi động/giám sát, chạy độc lập HTTP/browser. Không nhét network sync loop vào FastAPI event loop, không cần thêm GPU/service thường trực.
- Mỗi replica có thể có process nhưng DB leader lease + epoch CAS chỉ cho một actor ghi desired state. Disabled mặc định. Mất controller health làm supervisor restart process; persisted timestamps khôi phục sau rollout.
- Railway service phải không sleep/scale-zero khi không HTTP. Triển khai phải kiểm actual service setting, không suy ra từ JSON hiện tại. CPU/RAM controller có chi phí trong API usage.
- CLI controller chạy riêng vẫn dùng được để vận hành; chỉ bật một cơ chế provisioning cho deployment. Không chạy Vast và RunPod autoscaler trên cùng demand.
- Managed ownership: deployment UUID + immutable provision intent UUID + persisted expected unique name và provider Pod ID, image digest. Adopt lost-create chỉ khi toàn bộ token/ownership evidence match; tên prefix đơn thuần không đủ. Không đụng Pod/volume unrelated.
- RunPod key chỉ controller; worker chỉ nhận DB/R2 và các runtime secrets tối thiểu qua allowlist. Không truyền toàn bộ env, không cấp key provider cho GPU.

### 4.2 Durable state (schema đề xuất, chưa tồn tại)

Migration kế tiếp sau current v24, kiểm lại số version lúc implement. Control tables **chỉ authoritative ở main schema**; demo migrations dùng chung có thể tạo table rỗng nhưng tuyệt đối không tạo leader/budget riêng cho mỗi demo.

- `r2s_gpu_deployments`: deployment_id, enabled, desired drain flag, controller owner/lease_until/epoch, current state/version, idle_since, last successful complete scan, health/error category.
- `r2s_gpu_provision_intents`: intent id, deployment id, generation, profile digest, unique name, status, created/last_request/ambiguity timestamps, retry_at/attempt count. Một nonterminal intent tối đa cho deployment.
- `r2s_gpu_pods`: Pod ID, intent, observed/desired state, quote/allocation, boot identity/worker ids, accepted timestamps, startup deadline, soft retire_at, drain epoch/ack, termination confirmed_at. Không xóa lịch sử để “về 0”.
- `r2s_gpu_cost_events`: unique event/interval keys, quote/rate units, conservative billed interval estimates, pending reservation amount; budget window/reset policy explicit. Không cộng dồn mỗi poll gây double charge.
- Release capability catalog: image digest, software identity/config/seed, input qualification refs/checksums, supported task kinds, VRAM/RAM/disk/CPU minimums, validated GPU architecture/driver constraints. Có thể là signed/checksummed release JSON + persisted registration; không khai VERIFIED khi chưa qualify native runtime.
- Worker lifecycle row/control reference: Pod/intent/deployment identity, boot token, ready/busy/draining ack, current scope/operation, outstanding publication, heartbeat generation. Main authority dùng explicit access, không phụ thuộc demo search_path.

Dùng DB time cho deadline/lease; unique constraints + epoch CAS cho mutation. Không giữ DB transaction qua RunPod HTTP call. Leader lease tự nó không đủ chống delayed HTTP create: durable intent và UNKNOWN reconciliation là bắt buộc.

### 4.3 Provider adapter

- Tạo typed provider interface riêng: list paginated/get/create/start/stop/terminate, capabilities/quote và errors phân loại auth, inventory, rate-limit, transport, ambiguous create.
- Ưu tiên create → execute → terminate; start/stop là capability để reconcile Pod stopped hiện có, không là default idle policy. Pod stopped của deployment phải được reconcile và terminate khi safe.
- Khi implement phải đối chiếu **official live RunPod API contract**, không dùng docs repo. Chưa audit HTTP API ở lượt này theo giới hạn source-only; không chốt endpoint fields/idempotency/pricing/expiry chưa kiểm.
- Persist intent trước create; deterministic project-specific name/ownership token. POST timeout/lost response → UNKNOWN, list/get/adopt, không create intent mới khi chưa chứng minh request cũ không còn khả năng tạo Pod. Không có provider idempotency thì không hứa exactly-once trước mọi partition; fail closed + actionable manual reconciliation.
- API list/get lỗi hoặc paginated response thiếu không coi absent; 404 xử lý theo operation/context, không retry mọi HTTP lỗi giống nhau. Honor Retry-After, bounded jitter/backoff/circuit breaker.
- Chỉ chọn approved resource profiles + provider quote <= configured hourly cap; validate actual allocation và worker GPU probe. Chưa có telemetry đủ thì cấu hình floor do operator duyệt và ghi provenance configured, không tự chọn 4090/A6000.
- Không network volume mặc định. Scratch container disk đủ model weights/datasets/build cache; terminate phải xác nhận Pod gone và không tạo persistent volume riêng. Không xóa shared volume không chứng minh ownership.

### 4.4 Cold start và workload discovery

1. Build/release output capability catalog ghim với image digest; API đọc profile/input registry ngay khi GPU=0. Metadata bootstrapping này không thuê Pod.
2. Giữ auth/privacy/quota checks trước enqueue. `job_profile` và assembly availability dùng catalog cho admissibility, không fabricated live worker.
3. Snapshot main queues và sessions qua control registry; scope có thể đang bị purge. Session open cung cấp demand; session closed/expired nhưng child, reservation, lease hoặc publication chưa kết thúc vẫn cung cấp keepalive. Chỉ skip khi purge/completion và execution teardown đã được chứng minh. Creating chưa publish không được claim. Dùng ownership/namespace validation; unexpected scan error → unknown, retain Pod và cảnh báo.
4. Classify pending eligible / blocked runtime / waiting human / active / cancelling / publishing / unknown. Staged jobs compatible image vẫn được demand ở scale=0; incompatible version ghi blocked reason, không rebind stage artifacts.
5. CPU lane managed subprocess cùng API deployment cho registration, CPU import và CPU scene modes thực sự supported. Dùng cùng stores/fencing/admission; không chạy heavy CPU trên event loop. Audit API image dependencies/resources trước enable lane; thiếu native runtime là blocker packaging cần giải quyết, không thuê GPU chỉ để che missing CPU lane.
6. Controller không download multi-GB geometry chỉ để đếm work. Reuse pure classifier/extracted resource estimator; không reuse `_profile` demo vốn fetch cloud artifacts trong scanner.
7. Worker không đạt capability/VRAM/RAM/disk thì chưa READY. `STUDIO_WORKERS=1`; worker startup readiness cần actual hardware, runtime software/config, R2/DB access và poll loop ack, không chỉ provider RUNNING.

### 4.5 Claim gate, drain và publication

- Thêm gate API dùng chung trong **tất cả claim transactions**: pipeline/finalize/reviewed-preview, registration, validation, scene, import, demo parent và child. Dùng explicit main control connection cho scoped workers; lock order thống nhất control → session → queue để tránh deadlock.
- Worker đăng ký Pod generation; gate rejects stale/retired generation, không ảnh hưởng standalone local worker khi provisioning disabled.
- Begin claim và transition drain serialize qua row lock/epoch. Active operation đăng ký trước nhả gate; không có “claimed nhưng chưa có active marker” window.
- Idle 240s mặc định, bắt đầu sau last active/publication completed và complete eligible scan=empty. Chờ user review không reset idle; CPU phase trong GPU attempt có reset.
- DRAINING đóng claims; worker manager và demo children ack cùng epoch. Recheck full scopes + active leases/reservations + publication markers. Pending work trước irreversible terminate → reopen gate, clear idle timer.
- Sau TERMINATING committed, enqueue mới vẫn durable và được Pod kế tiếp nhận. Không đảo ngược DELETE đã gửi; không provision replacement khi Pod cũ chưa confirmed gone, đảm bảo max=1.
- Giữ execution marker và lease đến khi R2 publication integrity + final DB/CAS hoàn tất. Source hiện có synchronous remote push; audit mọi finalization path và marker lifetime, không giả có separate publication queue.
- R2 verify dùng existing immutable refs/checksum/metadata, publication receipts cần bổ sung chỉ ở chỗ thiếu. Không rehash/tải toàn bộ scene mỗi controller tick.

### 4.6 Failure recovery và watchdog

- Startup timeout: no valid active work → mark failure/terminate owned Pod, bounded retry; keep demand queued. Auth/config failure không retry tạo vô hạn.
- Worker heartbeat stale nhưng live operation lease → chưa kill; reconcile provider/process signals, grace và lease semantics. Worker runtime TTL hiện không là busy signal duy nhất.
- Provider Pod gone: fence generation, recover attempts qua current queue-specific recovery. Main pipeline FAILED retryable khác automatic retry; chỉ retry theo existing policy, không tạo vòng lặp chi phí mới.
- DB unavailable: freeze create và normal termination, worker fail-closed claims theo gate. Không biết lease/publication → không coi idle.
- Soft max lifetime/budget exhausted → drain new claims, hoàn tất healthy current work. Không tự interrupt vì cost. Stuck renewing lease cần alert; không thể bảo đảm hard lifetime mà vẫn không cắt healthy job.
- Controller ngoài Pod xử lý worker crash. Toàn Railway/controller down là failure domain khác: xác minh provider-native expiry/shutdown có hỗ trợ thật không. Nếu không, cần operator-approved independent scheduled reconciler/watchdog; không tự tạo dịch vụ trả phí. Trước khi claim production-ready phải test watchdog hoặc công khai residual orphan-cost risk và giữ public provisioning disabled.
- Không để hai watchdog độc lập tự DELETE mà không kiểm valid lease/fencing. Alert và retained evidence trước emergency actions. Emergency interrupt policy chưa được duyệt, mặc định không có.

### 4.7 Cost guards và operations

Defaults đề xuất (tên env mới, chưa được implement):

| Setting | Default / validation |
| --- | --- |
| `GPU_AUTOPROVISION_ENABLED` | false |
| `GPU_AUTOPROVISION_DRY_RUN` | true khi triển khai lần đầu |
| `GPU_PROVIDER` / `GPU_DEPLOYMENT_ID` | runpod / explicit stable UUID |
| `RUNPOD_API_KEY` | server-only, required khi enabled |
| `GPU_MAX_PODS` / `STUDIO_WORKERS` | 1 / 1, reject unsupported >1 ban đầu |
| `GPU_POLL_SECONDS` / `GPU_IDLE_SECONDS` | 15 / 240 |
| `GPU_STARTUP_TIMEOUT_SECONDS` | 1200, operator tune theo image cold boot |
| `GPU_MAX_PROVISION_ATTEMPTS` | 3 per incident, backoff persisted, reconcile vẫn tiếp tục |
| `GPU_MAX_HOURLY_USD` | Không có default tiền; bắt buộc operator-approved positive value |
| `GPU_PROJECT_BUDGET_USD` / budget window | Không có default; explicit cumulative demo budget, không tự reset tháng |
| `GPU_MAX_LIFETIME_SECONDS` | Explicit positive config; soft drain, không hard kill |
| `GPU_WORKER_IMAGE` / profile catalog | Digest pinned, no latest; approved fallback GPU IDs, no arbitrary fallback |
| Drain/admin actions | CLI/status bằng current admin auth nếu HTTP; không public endpoint nhận raw provider command |

- Cost estimate bao gồm created/billable startup + busy + idle + stopped retention khi còn đó; rate unknown dùng conservative approved bound và block new provisioning. Không đồng nhất provisioned time với GPU utilization active time.
- Reserve estimate trước create, settled/reconciled history idempotent. Soft estimate có sai số invoice/storage/network; không là RunPod hard cap. Billing reconciliation không tự override user budget.
- Disable provisioning vẫn giữ reconciliation/cleanup owned Pod; admin drain không kill active job. Tắt toàn controller là thao tác riêng, phải cảnh báo mất cleanup.
- Logs không chứa env/token/DB URL hoặc provider response có secrets. Metrics: queue kinds/scopes aggregate, scan completeness, controller heartbeat, state durations, create failures, allocation mismatch, lease lag, busy/publish/idle duration, estimated cost, termination confirmations.
- API `/health` và control-plane `/ready` healthy tại scale=0; compute availability trong field riêng, không báo ready GPU. Không đổi landing/auth.

## 5. Trình tự implement và file boundaries

Mỗi phase phải có diff review được; không tự commit/push/deploy khi chỉ có yêu cầu plan. Khi được yêu cầu implementation, tests trong prompt là acceptance scope được phép thực hiện.

| Phase | Thay đổi dự kiến | Hoàn tất khi |
| --- | --- | --- |
| P0 — freeze contracts | Inspect thêm enqueue/claim/publication callers bằng CodeGraph; official API contract; fixtures task/runtime resource matrix; capture existing dirty baseline | Không còn unknown queue kind; approved image profile và budget-required config tách live approval |
| P1 — state + catalog | `jobs/database.py`, mới `orchestration/gpu/{models,state,catalog}.py`; config validation | Migration main/demo scoped đúng; lease/CAS, unique intent, ledger idempotent; cold API enqueue không worker |
| P2 — workload adapters | Mới `gpu/workload.py`; shared pure classifier trong queue/admission; CPU lane CLI | Main+demo inventory đầy đủ; CPU-only không demand GPU; human waits không giữ Pod; unknown scan giữ an toàn |
| P3 — RunPod adapter | Mới `gpu/providers/{base,runpod}.py`, transport tests; preserve Vast CLI | REST contracts verified; ownership/quote/pagination; lost-create/UNKNOWN không duplicate |
| P4 — worker fencing | `worker_cli.py`, `samples/session_worker.py`, each queue claim, runtime/admission stores, worker manager | Drain atomic đối với mọi claim và demo child; generation readiness; R2 publication không mất protection |
| P5 — reconciler + cost | Mới `gpu/{controller,budget,recovery}.py`, `scripts/cloud/runpod_controller.py` | Durable 0→1→0, restart/rollout recovery, cap1, no active interruption, bounded retries |
| P6 — deploy wiring | `scripts/studio/container_entrypoint.py`, `src/main.py`, env renderer/examples, GPU entrypoint/image, Railway config nếu cần | Supervision/health không phụ thuộc HTTP; graceful exit; no secrets; CPU lane works without GPU; image supports advertised workloads |
| P7 — test + handoff | New focused tests, regression suites, runbook/report sau source đã implement | Actual commands/results, failures/skips explicit; no mocked claim for live concurrency/cloud |
| P8 — approved live smoke | Chỉ sau approval spend, image pushed/accessible và isolated DB/R2 namespace | Real small stage, R2 verify, automatic termination confirmed, second request reprovisions, no retained owned volume |

Isaac: packaging/qualification là dependency bắt buộc nếu bật validation; có thể dùng approved profile/image khác chạy tuần tự trên cùng max1 Pod. Khi đổi profile: drain current then terminate then create compatible image. Không advertise support trong khi native verification chưa có. Không cần gộp Isaac vào reconstruction image bằng mọi giá.

## 6. Test plan chi tiết — chưa chạy trong audit

### 6.1 Reuse hiện có

- `tests/test_gpu/test_gpu_autoscaler.py`, `test_gpu_autoscaler_runtime.py`: state/transport seams, runtime expiry fixtures; cập nhật expectations chỉ khi semantics được thay có chủ đích, giữ Vast regression.
- `tests/test_orchestration/test_job_lease.py`, `test_resource_admission.py`: lease renewal/fencing/reservation.
- `test_registration_worker.py`, `test_validation_queue.py`, `test_import_queue.py`: cancellation, stale lease, retry và publish failure.
- `test_artifact_remote.py`, `test_release_sealing_recovery.py`: immutable publication/checksum/terminal commit.
- `tests/test_api/test_demo_sessions.py`: session isolation; bổ sung PostgreSQL tests thực sự cho distributed path, không coi SQLite proof là đủ.

### 6.2 New matrix

1. Empty/human review/CPU-only queues: no create; CPU work vẫn chạy ở GPU=0.
2. First ever enqueue, no live runtime/no previous worker: catalog cho phép queue; unsupported/invalid catalog từ chối rõ.
3. Staged compatible job khi runtime offline: provision đúng digest; incompatible job blocked, không bị rewrite artifacts.
4. N simultaneous GPU requests + 2 controller processes: unique intent, one create; supervisor nhiều child vẫn inventory đúng.
5. Every queue kind main + demo; duplicate logical job IDs trong hai schemas không trộn; expired/closing/missing/corrupt scope.
6. CPU phase trong running GPU attempt, utilization=0, active validation/registration/import, cancel requested, long R2 upload: no terminate.
7. New enqueue during grace, before drain gate, after drain ack, immediately after irreversible termination: no lost work/no duplicate Pod, replacement only after gone.
8. Pause between claim and reservation creation; controller drain concurrently: transaction gate phải serialize.
9. Long reconstruction lease renew > grace/lifetime/budget: remains active, only stops new claims.
10. Worker crash, parent crash with demo child, stale runtime but valid lease, lease expired worker alive: recover/fence results đúng contract, owned Pod cleanup.
11. Kill controller before create, during create, after provider accepted before DB persist, during DELETE, after delete before confirm; adopt/UNKNOWN logic bounded.
12. Provider 401/403/404/409/429/5xx, timeout, partial paginated list, inventory unavailable, quote changed/allocation mismatch: không POST storm, không giả absent/READY.
13. Budget reservation crash/restart/repeated poll/reset: no double charge/reset bypass; exhausted/disabled forbids provisioning but reconcile still works.
14. Unrelated Pod cùng prefix, wrong token/image/account/deployment; never stop/delete. Stopped owned Pod no work eventually terminated; no network volume requested by default.
15. DB outage/pooler reconnect/leader lease expiry/controller rollout, unknown publication/queue scan: no unsafe idle; stale actor cannot claim/delete/create new generation.
16. API stays ready với GPU0; controller unhealthy observable; supervisor restarts child, reaps children SIGTERM; no browser request required.
17. Real PostgreSQL integration tests cho row/advisory lock, scopes, CAS, migrations, queue claim drain. SQLite/mocked threaded tests **không chứng minh multi-controller safety**.
18. Native GPU image tests CUDA+Vulkan+COLMAP+Brush+segmentation+ObjectGS; Isaac riêng. No credits or spend approval → mark not run.

Lệnh dự kiến sau implementation (dùng interpreter/toolchain của workspace): Ruff check/format changed paths; focused pytest new controller/provider/workload/state modules; focused existing suites nêu trên; PostgreSQL integration suite với disposable local DB; `git diff --check`; bash syntax entrypoint; image build/preflight trên host đủ disk. Chạy tests phải ghi số thực, skip lý do. `graphify update .` sau sửa code.

## 7. Blockers / gates trước bật production

| Gate | Hiện trạng | Có thể làm local trước |
| --- | --- | --- |
| Spending approval | Chưa có approved hourly cap/total. Credit user báo có | Implement + mock/PG tests, disabled/dry-run config |
| RunPod API semantics/expiry/price | Chưa kiểm live official contract trong source-only audit | Thiết kế interfaces; xác minh contract trước adapter implementation, không cần tạo paid Pod |
| GPU image digest/native qualification | Docker recipe có, không phải bằng chứng image chạy được; Isaac thiếu | Build/package trên đủ disk, verify supported catalog; unsupported kinds block explicit |
| API CPU lane native deps | Chưa có independent CPU dispatch mode | Implement mode + package minimum deps, regression; không tuyên bố xử lý CPU ở scale0 trước test |
| Complete control-plane outage | Cùng API deployment không watchdog cho chính Railway down | Verify provider failsafe; independent reconciler nếu được duyệt; residual cost risk phải nêu |
| Private registry access | Phải cấu hình provider image pull phù hợp, tránh log credentials | Release digest/config validation; không yêu cầu public repo |
| Demo library bootstrap storage | Source vẫn staging ZIP+extract trên same volume. Prior footprint ~7.338 GB là input từ prompt, chưa đo lại trong audit | P0 riêng: measure current bundle and actual Railway quota; không lén refactor trong task này |
| R2/Supabase | Bucket `real2sim`, active/credit do user xác nhận | Apply private config khi được yêu cầu triển khai, verify access không lộ secret |

Không thiếu credential để bắt đầu viết implementation offline. Không cần hỏi lại các quyết định routine; thiếu approval chi tiêu chỉ chặn live paid test, không chặn code/tests.

## 8. Handoff / rollback

- Rollout default disabled → dry-run observation → isolated enabled smoke có approved cap → enable authorized jobs. Không tự nâng Railway plan hay bật anonymous uploads.
- Rollback: disable new provisioning, drain existing generation, wait jobs/publication, terminate/reconcile owned resources, rồi rollback API/worker digest; migration additive giữ lịch sử. Không drop demo/main schema hoặc reset jobs.
- Report bắt buộc phân biệt source/static, mocked, local PostgreSQL, image/native, live RunPod và 0→1→0. Idle GPU compute kỳ vọng 0 sau confirmed termination; API/DB/R2/container registry/storage vẫn có thể tính phí. Không báo tổng infrastructure=$0.
- File duy nhất được tạo trong audit: plan này. Không source changes, không tests/cloud mutation/commit/push. Phụ lục giữ nguyên prompt để lần implement đọc cùng các corrections và evidence phía trên.

## Phụ lục A — Prompt gốc của user (nguyên văn)

<!-- ORIGINAL_PROMPT_START -->

# TASK: Implement Production-Ready RunPod GPU Auto Provisioning & Scale-to-Zero for Real2Sim Studio

## 1. Context

Real2Sim Studio is an editable Real-to-Sim workspace for robotics. Its cloud architecture consists of:

- Vercel: Next.js Studio frontend.
- Railway: FastAPI backend, custom authentication, orchestration and scene operations.
- Supabase PostgreSQL: durable application state, jobs, worker leases, and demo sessions.
- Cloudflare R2: persistent video inputs, reconstructed scenes, artifacts, colliders and export bundles.
- RunPod: GPU infrastructure for compute-heavy jobs.

Our existing application already implements direct multipart upload to R2, asynchronous GPU workers, PostgreSQL-backed job dispatch, job state persistence and worker execution.

**The missing functionality is fully automatic GPU lifecycle management for RunPod.**

Currently, the proposed deployment relies on a manually provisioned, continuously running Pod during demo sessions. This is not acceptable as the final deployment model because it wastes GPU compute when no processing is required.

I want you to implement the missing functionality, not merely write another architectural recommendation or specification.

### Required outcome

When no GPU work exists, there should be **zero running and zero unnecessary stopped RunPod Pods** managed by Real2Sim.

When an eligible GPU job arrives, the system should automatically provision and start a compatible RunPod Pod, boot the existing worker, process the job, publish results to R2 and update PostgreSQL.

When all relevant work is complete, the system should automatically release the GPU infrastructure after a short, configurable idle grace period.

The user must not be required to manually start or stop a Pod.

## 2. First: Audit the existing repository

Before implementation, inspect the actual code, database schema, tests and deployment scripts.

Start with these known locations:

- `src/services/orchestration/jobs/worker_cli.py`
- `src/services/orchestration/samples/release.py`
- `src/api/studio/uploads.py`
- `scripts/cloud/gpu_autoscaler.py`
- `.ai/reports/telemetry-coverage-20261019/report.md`

Also inspect all relevant job models, migrations, demo session schemas, worker registration, dispatch, cancellation, lease handling, validation workflows, Docker build files and deployment configuration.

The repository already contains a Vast.ai autoscaler. Reuse provider-neutral logic where appropriate, but do not assume its existing workload accounting is complete or safe for RunPod.

Specifically determine:

1. Every source of GPU work, including primary job tables, isolated demo session schemas, registration, reconstruction, segmentation, ObjectGS, mesh/collider generation and validation tasks.
2. How workers discover, claim, lease, execute, cancel and acknowledge jobs.
3. How workers connect to demo-specific schemas without losing isolation.
4. Which tasks actually need a cloud GPU versus CPU-only execution.
5. How results are persisted to PostgreSQL and published to Cloudflare R2.
6. How worker health, heartbeat, initialization and failure are currently represented.
7. Whether existing Docker images and runtime entrypoints can execute all required GPU workloads.
8. Whether there is already a reliable scheduler/controller process that can be reused on Railway.
9. How GPU pricing, limits and Pod resource requirements are currently configured.
10. Which existing tests and abstractions can be reused.

**Do not invent missing schema details. Verify them from code.**

If all necessary information is available, proceed directly to implementation. Do not stop after the audit.

If something is genuinely blocked by missing credentials, missing external configuration, or an architectural ambiguity that cannot be resolved from the repository, report:

- Exact blocker.
- Relevant file and line numbers.
- Why it prevents implementation or verification.
- Your recommended resolution.
- Which portions can still be implemented without the missing dependency.

Do not request clarification for details you can reasonably resolve from existing code and documentation.

## 3. Implement the RunPod provider

Implement a RunPod provider adapter using the current official RunPod API.

Official references:

- https://docs.runpod.io/pods/manage-pods
- https://docs.runpod.io/api-reference/pods/POST/pods
- https://docs.runpod.io/pods/pricing

The provider must support:

- Listing and discovering managed Pods.
- Creating a GPU Pod from our worker Docker image or template.
- Inspecting Pod status, allocation and readiness.
- Starting an existing stopped Pod where appropriate.
- Stopping a Pod where appropriate.
- Terminating a Pod.
- Handling API errors, timeouts, rate limits and unavailable GPU inventory.
- Reconciliation after API failures or lost responses.

Prefer **Create → Execute → Terminate** for the initial implementation, since persistent R2 storage already exists and stopped Pods can continue generating storage costs.

Do not terminate unrelated Pods. Only manage Pods whose ownership can be positively verified using persisted identifiers and project-specific names or metadata.

Choose compatible GPU types from validated resource requirements and telemetry, not arbitrarily.

Do not hardcode a specific GPU model if the architecture already supports configurable providers or resource profiles.

## 4. Implement the GPU lifecycle controller

Implement an autonomous controller that runs independently of the GPU Pod.

Use the existing PostgreSQL orchestration infrastructure wherever possible.

The lifecycle must cover at least:

```text
NO_GPU_WORK
    |
    | Eligible GPU job detected
    v
PROVISIONING
    |
    | RunPod creates GPU Pod
    v
STARTING
    |
    | Worker boots and registers
    v
READY / BUSY
    |
    | Worker executes queued jobs
    | Progress persisted to PostgreSQL
    | Artifacts published to Cloudflare R2
    v
IDLE
    |
    | No outstanding GPU work
    | Configurable idle grace period
    v
DRAINING
    |
    | Recheck all queues and active leases
    v
TERMINATING
    |
    | RunPod Pod deleted
    v
NO_GPU_WORK
```

Additional transitions must handle failures, startup timeouts, provider interruptions, cancellations, retries and recovery.

### Provisioning requirements

- Scale from 0 to 1 GPU Pod automatically when work is eligible.
- Initial maximum concurrency: one GPU Pod.
- Prevent duplicate provisioning under concurrent controller instances.
- Support recovery when a Pod was created but the controller crashed before recording its ID.
- Reconcile actual RunPod state with PostgreSQL state after controller restarts.
- Verify that the requested GPU allocation is actually available before considering the worker ready.
- Handle unavailable GPU types with bounded retries/backoff and configurable compatible fallback types.

### Idle shutdown requirements

Use a configurable idle grace period, initially approximately 3–5 minutes.

A Pod is eligible for termination only if:

- No eligible queued work remains across all supported queues/schemas.
- No active worker is executing a GPU job.
- No valid job lease or heartbeat indicates ongoing processing.
- No required artifact publication/finalization remains in progress.
- No registration, reconstruction, geometry or validation task still requires that worker.
- Draining has prevented new claims, and the queue has been checked again safely before termination.

**Do not determine idleness solely from GPU utilization or absence of HTTP traffic.**

If a new job arrives during idle grace or draining, cancel shutdown where safe and resume processing.

Do not terminate a Pod while a valid job is running.

### Concurrency and crash safety

Use appropriate database-backed leader election, advisory locks, leases, compare-and-swap updates or equivalent mechanisms compatible with the existing architecture.

Ensure that:

- Multiple controller replicas cannot create duplicate Pods.
- Stale locks can be recovered.
- Repeated API calls and reconciliation passes are idempotent.
- Lost API responses do not trigger uncontrolled additional provisioning.
- A restarted controller can adopt and reconcile an existing Real2Sim-owned Pod.
- Jobs are not silently lost when Pod startup or termination fails.

## 5. Preserve existing job architecture

Do not redesign or replace the PostgreSQL job queue without a demonstrated technical necessity.

Preserve:

- Existing asynchronous worker execution.
- Job cancellation.
- Lease and heartbeat semantics.
- Retry and recovery behavior.
- Scene/session isolation.
- Worker registration.
- Progress reporting.
- Cloudflare R2 artifact publication.
- Baseline demo immutability.
- Custom authentication and authorization.

The new controller must account for both ordinary jobs and jobs associated with isolated demo sessions.

The existing Vast.ai autoscaler is not sufficient as-is because it does not account for all demo workloads. Reuse its abstractions only after verifying their correctness.

No mandatory migration to RunPod Serverless in this task.

## 6. Implement cost control and automatic cleanup

Cost efficiency is a core requirement.

Implement configurable safeguards including:

- Maximum running GPU Pods, initially 1.
- Maximum accepted GPU hourly price.
- Maximum Pod startup duration.
- Maximum idle duration.
- Maximum Pod lifetime, with safe handling of still-running jobs.
- Bounded provisioning retries.
- Project-level estimated compute expenditure.
- Warnings and blocking of new provisioning when the configured budget is exhausted.
- A provisioning disable/kill switch.
- An administrator-controlled drain mechanism.
- Logs/metrics for provisioned time, active job time, idle time and termination.

Do not treat RunPod's account-level spend limit as a project budget or hard spending cap.

A local estimated budget guardrail is not equivalent to a provider-enforced hard cap. Document this limitation explicitly.

Do not assume that any previously suggested budget (such as $20 or $80) has already been approved.

The controller must not automatically terminate healthy jobs simply because they exceed an estimated cost threshold, unless a documented emergency policy explicitly permits interruption with safe state recovery.

For emergency failure conditions, implement an external watchdog/reconciliation mechanism so a Pod cannot remain running indefinitely just because the worker inside it has crashed.

Use provider-supported expiry/failsafe controls if available and compatible, but verify them against the actual API.

### Storage cleanup

Cloudflare R2 is the persistent artifact store.

RunPod local/container storage should be temporary unless there is a justified cache or shared-volume requirement.

Before normal termination:

1. Ensure processing has completed or reached a safely recoverable terminal state.
2. Finish all required R2 uploads.
3. Verify artifact references and integrity using the existing publication contract.
4. Persist the final job state in PostgreSQL.
5. Terminate the managed Pod.
6. Reconcile the provider state to confirm compute and unnecessary storage resources were released.

On failure, preserve the information needed to recover or retry the job before releasing resources.

## 7. Deployment integration

Deploy the lifecycle controller outside the GPU Pod.

Evaluate the cheapest reliable deployment option using our existing Railway infrastructure.

Requirements:

- The controller must operate without an incoming browser HTTP request.
- It must continue working when no user has the Studio page open.
- It must survive process restarts and deployment rollouts.
- Multiple Railway API instances must not create multiple GPU Pods.
- It must not rely on an in-memory timer as the only safety mechanism.
- It must not require a continuously running GPU for monitoring.
- It must not introduce an unnecessarily expensive extra service.

Choose the simplest reliable option supported by the existing code and Railway deployment model, and document the trade-offs.

All API credentials must remain server-side.

Use environment variables or secure deployment configuration for RunPod, PostgreSQL, R2 and registry credentials.

Never expose secrets to the browser or print them in logs.

Use an immutable/pinned GPU worker image where practical, and verify its entrypoint, CUDA dependencies, storage, R2 access and queue polling behavior.

## 8. Tests and acceptance criteria

Implement automated tests using mocked RunPod API responses first.

Required scenarios:

| Scenario | Expected outcome |
|---|---|
| Empty queue | No GPU Pod is created |
| First eligible job arrives | Exactly one Pod provisioned |
| Multiple jobs arrive together | Still only one Pod |
| Job currently running | Pod remains active |
| GPU utilization reaches zero during CPU work | Pod is not terminated |
| New job arrives during idle grace | Shutdown canceled |
| New job arrives during draining | No lost job; safe resumption |
| Main queue empty but demo work active | Pod remains active |
| Registration or validation work active | Pod remains active if GPU is required |
| Last job completes | Pod terminates after idle grace |
| R2 publication still running | Pod is retained |
| Worker crashes | Job recovered or safely failed; no orphaned Pod |
| Controller restarts | Existing Pod reconciled correctly |
| Two controllers run concurrently | No duplicate provisioning |
| RunPod API fails or times out | Bounded retry, no resource explosion |
| GPU unavailable | Safe retry/fallback or actionable failure |
| Budget blocks new provisioning | Jobs remain durably queued or explicitly rejected |
| Provisioning disabled | No new GPU resources created |
| Pod terminated | No unnecessary persistent storage retained |

Also validate shutdown and recovery when a worker is processing a long-running reconstruction job.

Do not mark a test as passing if it only exercises a mocked happy path while omitting critical failure handling.

### Integration validation

Once implementation and mocked tests pass, perform a real end-to-end RunPod smoke test **only if GPU credits are available and explicit spending approval exists**.

Expected flow:

1. Submit a real, small GPU-dependent job.
2. Observe automatic provisioning.
3. Confirm the worker becomes ready.
4. Execute the real pipeline stage.
5. Verify progress, result and R2 artifacts.
6. Observe automatic idle shutdown.
7. Confirm Pod termination through the RunPod API.
8. Verify no additional GPU Pod or unnecessary retained volume remains.
9. Submit another job and confirm the system can provision again.

If account balance is still $0, billing is blocked, or approval is unavailable, do not incur charges. Complete the implementation and automated tests, then report that live cloud verification remains blocked.

## 9. Scope boundaries and implementation quality

- Do not modify the landing page.
- Do not change the custom auth system.
- Do not unnecessarily replace existing orchestration architecture.
- Do not open unlimited reconstruction to anonymous users.
- Preserve user quotas and authorization checks.
- Keep GPU-specific provisioning isolated behind a provider interface.
- Use typed Python, clear modules, proper error handling and tests.
- Follow existing project coding conventions.

The previously identified Railway Hobby 5 GB volume issue versus approximately 7.338 GB bootstrap footprint remains a separate P0 deployment concern. Do not silently ignore it in the final deployment report, but do not let unrelated bootstrap refactoring expand this GPU lifecycle task unnecessarily.

Do not push, merge, deploy paid resources or alter production infrastructure without authorization. Local commits are permitted.

## 10. Required deliverables

Produce:

**A. Working implementation**

Actual code changes for RunPod provisioning, lifecycle reconciliation, job awareness, idle shutdown, cost guards and recovery.

**B. Tests**

Automated unit and integration-style tests covering the scenarios above.

**C. Deployment configuration**

Required environment variables, default values, Railway controller startup/health configuration and RunPod worker requirements.

**D. Documentation**

A concise architectural explanation covering:

- What starts the GPU.
- What prevents duplicate provisioning.
- How every job source is accounted for.
- How idle shutdown is determined.
- What prevents active work from being interrupted.
- How failed Pods are recovered.
- How spending is controlled.
- How to operate or disable the controller safely.

**E. Final implementation report**

Report:

1. Files changed and the main design decisions.
2. Features already reused versus newly implemented.
3. Test commands and actual results.
4. Remaining blockers, if any.
5. Whether real RunPod provisioning was tested.
6. Whether scale 0 → 1 → 0 was verified end-to-end.
7. Expected recurring infrastructure cost while no GPU work exists.
8. Any limitations that remain before enabling public GPU jobs.

## Final instruction

**Implement the solution end-to-end. Do not stop after producing a design document.**

Start by auditing the real implementation and resolving the unknowns from source code. Proceed through implementation and automated testing without waiting for intermediate approval.

Only pause for an external dependency or action that genuinely requires user authorization, such as spending GPU credits, introducing paid infrastructure or changing production secrets.

The final goal is a Real2Sim Studio deployment that can remain publicly accessible without paying for idle GPU compute, while automatically provisioning GPU processing whenever an authorized job requires it.

<!-- ORIGINAL_PROMPT_END -->
