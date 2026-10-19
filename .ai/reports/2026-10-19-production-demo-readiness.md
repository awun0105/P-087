# Kế hoạch sẵn sàng triển khai demo Studio

Ngày rà soát: 2026-10-19. Baseline: `develop`, commit `45cd6f43d9a5276b3287975b403edc2ad213d2df`.

Đây là báo cáo rà soát và kế hoạch implementation, chưa phải bằng chứng nghiệm thu cloud. Không sửa implementation, thay đổi dữ liệu job, build/publish image, tạo tài nguyên cloud hoặc thay đổi visibility của repo trong lần rà soát này.

## 1. Kết luận và phạm vi

Chưa nên deploy nguyên trạng để mở demo tương tác có tính toán thật trên web/API và GPU ở hai máy. Luồng job thông thường đã có nền tảng PostgreSQL + R2 + worker lease, nhưng phiên demo mới vẫn dùng SQLite và filesystem cùng máy. Worker demo còn có lỗi cấu hình khi khởi động trong production.

Mục tiêu triển khai:

- Studio dùng được độc lập với laptop phát triển.
- Xem các giai đoạn có artifact thật của mẫu; chỉnh scene, sửa vùng, tạo mesh và chạy validation bằng dịch vụ thật trong phiên riêng.
- Hai người mở cùng mẫu có dữ liệu chỉnh sửa và hàng đợi riêng. Đóng/timeout phiên thu hồi quyền truy cập và dọn kết quả riêng; baseline không đổi.
- Có bundle gắn với code/image/runtime cụ thể, phục hồi được trên môi trường trống.
- Các số đo dùng để báo cáo hiệu năng phải có phạm vi và coverage; dữ liệu thiếu giữ unknown/partial.

Landing đã deploy riêng, nằm ngoài release này. Không yêu cầu public repo để đạt mục tiêu.

## 2. Kiến trúc triển khai đề xuất

Giữ hướng hiện có trong `deploy/studio/OVERVIEW.md`:

```text
Trình duyệt
  -> Studio Next.js: Vercel
       -> /api/v1: FastAPI trên Railway
                       -> PostgreSQL trên Supabase
                       -> private object storage trên R2
GPU worker thuê: pod chạy liên tục trong thời gian demo
  -> PostgreSQL: nhận việc, lease, heartbeat, tiến trình
  -> R2: lấy input, ghi artifact/output
Trình duyệt -> R2 bằng URL có hạn cho upload/download lớn
```

API và GPU không cần cùng máy hay IP GPU cố định. DB và object storage là giao diện phối hợp. Browser vẫn cần GPU của thiết bị để render viewer. Không dùng filesystem hoặc SQLite từ một máy làm giao thức chia sẻ giữa hai host.

Đề xuất lần demo đầu dùng một GPU worker chạy liên tục và giới hạn một tác vụ GPU nặng tại một thời điểm. Nhiều người vẫn xem/chỉnh độc lập; các thao tác nặng xếp hàng với trạng thái rõ ràng. Chỉ tăng concurrency sau khi đo RAM/VRAM/disk của workload thật. Serverless/autoscaling là giai đoạn sau; không phải điều kiện để demo đầu tiên hoạt động. Đây là đề xuất thứ tự triển khai, không thay đổi phạm vi các task T-039/T-041/T-042 hiện có.

Nếu muốn giữ private và không dùng gói Vercel phù hợp, có thể chạy `frontend/Dockerfile` trên host CPU cùng API dưới cùng origin. Phải nghiệm thu cách proxy/cookie/build đó riêng. Không cần chuyển webapp lên máy GPU chỉ để giải quyết giới hạn gói Git integration.

## 3. Kết quả rà soát

| Hạng mục | Bằng chứng hiện tại | Việc phải làm |
| --- | --- | --- |
| Web/API/worker tách máy | Có deployment templates, PostgreSQL adapter, R2 upload/download, runtime discovery và lease cho job thường. | Nghiệm thu thật trên host tách biệt; không suy từ local. |
| Worker demo trong production | `session_worker._run` kế thừa APP_ENV nhưng đặt AUTH_REQUIRED=false; Settings bắt buộc auth ở production/staging. | Sửa ranh giới execution context và auth; giữ guard production của API. |
| Isolation demo | `session_settings` tạo SQLite, artifact/worker dirs riêng và tắt S3. `session_root` phụ thuộc artifact root local. Worker duyệt thư mục local. | Đưa catalog phiên/claim/expiry sang DB chung, runtime state và artifact có namespace riêng. |
| Runtime của demo | `_registry` lấy execution_profile từ registry nguồn nhưng đặt runtime_from_workers=false. | Bảo đảm demo dùng được runtime worker-discovery khi API không có manifest cục bộ; kiểm config/runtime compatibility. |
| Dữ liệu mẫu | Ba workspace frozen có sẵn trên máy local; `data/` bị loại khỏi Git và image. | Xuất/publish baseline riêng và bootstrap fail-closed nếu thiếu/sai checksum. |
| Mẫu hoàn thành mọi bước | DrJohnson baseline rev-198 có geometry-ready trong audit trước; Room rev-062 và Playroom rev-003 còn awaiting_review. | Chọn DrJohnson làm mẫu geometry-ready đầu tiên, chưa coi là simulation-validated. Mẫu Draft ghi đúng trạng thái; chỉ quảng bá hoàn chỉnh sau khi tạo mesh/validation thật và freeze bản mới. |
| Data package | Có pack/verify, scrub credential/session, kiểm refs/checksum, active-work gate, SQLite snapshot. | Dùng lại; bổ sung kiểm workspace graph, curated sample selection và acceptance trên dữ liệu mới. |
| Cloud publisher | Import tập bảng rõ ràng, upload main artifact tree vào R2, yêu cầu target rỗng. Demo/preview/Rerun chỉ được provision local. | Bổ sung publish/bootstrap catalog và baseline demo cho production; đối chiếu table coverage của pipeline mới. |
| GPU image | Có Dockerfile.gpu và install/entrypoint/preflight. File/doc còn ghi chưa build thật; chưa có receipt cloud trong bằng chứng rà soát này. | Build sạch, push digest, preflight và chạy workload thật. Không đánh dấu image ready từ Dockerfile tồn tại. |
| Input runtime registry | Worker sinh registry, production template vẫn yêu cầu chép file lên API. | Lần đầu đóng gói file đã qualify đúng runtime và cấp cho API; tự công bố DB là cải tiến riêng nếu chưa cần. |
| Isaac | Template để launcher/resources ở dạng tùy chọn; image chưa chứng minh chứa Isaac runtime. | Chuẩn bị runtime/image validation phù hợp, license và resource profile; test thật trước khi tuyên bố nút Isaac khả dụng. |
| Truyền file lớn | Direct multipart upload tới object store và presigned download đã có ở luồng job thường. Sample files hiện là FileResponse local. | Kiểm hết đường demo/frames/GLB/SOG/export/Rerun để tránh kéo file lớn qua function hoặc timeout proxy. |
| Telemetry | Audit riêng đã xác nhận thiếu time-to-usable, task clock và spans của bước mesh mới; cleanup demo xóa DB riêng. | Bổ sung theo mục 5; không dùng số tổng hiện tại làm kết quả benchmark đầy đủ. |
| CI | Run 39234540001 của HEAD hiện tại không khởi chạy được vì GitHub billing/spending limit; annotation được đọc lại ngày rà soát. | Khôi phục runner/billing hoặc runner hợp lệ khác; chạy gate rồi mới phát hành. |

### Dữ liệu workspace hiện có

Inventory read-only, tổng kích thước logical file; chưa phải kích thước ZIP, R2 billable storage hay scratch peak:

| Sample | Revision | Số file gồm snapshot.json | Bytes |
| --- | --- | ---: | ---: |
| drjohnson-f9f14e7f-d7be7c91-aligned | rev-198 | 952 | 2,301,366,350 |
| mip-nerf-360-room-images-4-bfc7d73f-024f857c-aligned | rev-062 | 863 | 633,356,660 |
| playroom-7c9820b4-784cdd45-aligned | rev-003 | 637 | 900,562,726 |

Tổng 3,835,285,736 bytes, khoảng 3.57 GiB, chỉ cho ba workspace. Main artifact tree, public sample payload, image/runtime, cache, scratch và kết quả phiên tính riêng. Local copy dùng hardlink cho immutable artifact khi cùng filesystem; không nhân tổng này với số session để suy disk thực tế. Trên cloud phải đo cold-cache, download và output peak.

## 4. Quyết định kỹ thuật cho demo phân tán

### 4.1 Giữ logical identity, cô lập physical state

Hai phiên hiện giữ cùng source job_id/artifact URI để replay chính xác. Các bảng như jobs/scene_heads/scene_requests dùng job_id làm khóa. Vì vậy không thể chỉ trỏ mọi phiên vào cùng PostgreSQL và bật lại cùng R2 prefix: sẽ đụng row/key và có thể ghi vào baseline hoặc phiên khác.

Phương án ưu tiên để làm spike nhỏ trước implementation rộng:

- Catalog phiên ở DB điều khiển chung: capability hash, sample version, namespace, created/last_seen/expires, state, worker lease/fence và cleanup state.
- Mỗi phiên dùng schema PostgreSQL riêng, tên do server sinh/validate, để tái sử dụng các repository/queue hiện tại mà giữ logical job IDs. Schema không expose qua Supabase Data API. Không dùng capability do client gửi làm SQL identifier.
- `RuntimeDatabase` nhận scope rõ ràng; mọi transaction và migration phải vào đúng schema. Cache `_READY` phải phân biệt database + scope. Không để fallback sang public/main schema. Thiết lập scope trong transaction bằng cơ chế an toàn; không phụ thuộc URL `options=search_path` xuyên pooler.
- Artifact được phân giải trong namespace vật lý riêng, ví dụ `releases/<release>/baselines/<sample-version>/...` và `sessions/<session-id>/...`. Baseline read-only; output mới chỉ ghi trong session. Chọn full copy hoặc baseline-read/session-write overlay sau khi đo, không thay serialized artifact bytes/checksum để đổi đường dẫn.
- Namespace không đồng nghĩa với quyền sở hữu: API phải kiểm capability, job/project binding và published state; worker lấy descriptor đã xác thực từ catalog. Main credentials không đưa xuống browser.
- Resource admission và worker discovery vẫn ở control DB chung. Không để mỗi schema tự coi như có toàn bộ GPU/RAM khả dụng. Tách local scratch của mỗi worker khỏi dữ liệu bền vững.

Spike nghiệm thu trước khi chốt schema-per-session: hai API process + hai worker process, cùng logical job ID nhưng state riêng, migration đồng thời, PostgreSQL/pooler thực tế, DB scope không rò, resolver không ghi baseline, admission toàn cục. Nếu spike không đạt, dừng ở quyết định thiết kế và đánh giá namespace key trong các repository; không tự chuyển sang rewrite toàn bộ artifact graph/job IDs hoặc chia sẻ SQLite qua mạng.

### 4.2 Auth và vòng đời

- Public demo dùng capability giới hạn vào một session. API chính giữ `AUTH_REQUIRED=true`; quyền demo được inject ở request/runtime context đã xác thực. Worker không có lý do hạ guard auth cho toàn app.
- Claim/heartbeat/cancel/expiry dùng DB lease và fencing token, không dùng flock làm phối hợp giữa host.
- Đóng phiên: thu hồi capability trước, chặn claim/publication mới, yêu cầu hủy đúng operation, chờ lease/process ownership hết hiệu lực rồi dọn output/scratch/schema đúng namespace.
- Janitor chạy độc lập; browser DELETE/pagehide chỉ là tín hiệu hỗ trợ. Có recovery khi mất mạng, crash API/worker và khởi động lại. Close/cleanup phải idempotent.
- Ghi summary telemetry bền vững trước xóa runtime state. Thu hồi URL đã cấp là vấn đề riêng: URL ký sẵn có hiệu lực tới expiry; dùng TTL ngắn theo chính sách và kiểm hành vi sau cleanup.
- Có giới hạn session, số tác vụ nặng, thời lượng GPU, bytes output và dung lượng scratch. Mức khởi đầu đề xuất: một heavy GPU operation đồng thời; các trần khác dựa trên measurement và ngân sách demo, không gọi default 32 session là capacity đã chứng minh.
- Capability trong URL cần loại khỏi access log/referrer/analytics; không cache response riêng bằng cache key chung.

## 5. Thứ tự implementation và điều kiện hoàn tất

Mỗi hàng là một scope review/commit riêng khi được yêu cầu triển khai. Không gộp đổi topology, telemetry và runtime image vào một thay đổi lớn.

| ID | Công việc, phạm vi dự kiến | Phụ thuộc | Điều kiện hoàn tất |
| --- | --- | --- | --- |
| D1 | Spike DB scope + artifact namespace; `jobs/database.py`, artifact resolver/store, session integration tests. | — | Hai phiên cùng mẫu/cùng logical IDs không thấy/ghi lẫn; main DB và baseline checksum không đổi; qua pooler thật. Chốt ADR trước D3. |
| D2 | Sửa production demo auth/worker context và runtime discovery; `samples/session_context.py`, `sessions.py`, `session_worker.py`, API deps/config và tests liên quan. | —; tích hợp lại sau D1 | APP_ENV=production khởi động được API/worker; API vẫn yêu cầu auth; request thiếu/sai capability bị từ chối; runtime được worker công bố hoạt động với demo. |
| D3 | Session catalog, dispatch, global resource gate, lease/fencing, expiry và janitor; giữ native scene/pipeline/validation workers. | D1, D2 | API và GPU hai host xử lý create/edit/rebuild/reset/cancel/close; late worker không publish vào phiên đã đóng; crash/restart cleanup không xóa baseline/phiên khác. |
| D4 | Demo bundle/export/publish/bootstrap; mở rộng `data_package.py`, `package_publish.py`, `samples/workspace.py`, CLI và tests packaging. | D1 | Release curated, đầy đủ refs, checksum, quyền dữ liệu; từ máy sạch load đủ các stage thực có; fail-closed khi thiếu/sai dữ liệu. |
| D5 | Container/runtime release; Dockerfiles, GPU build arguments, input registry, Isaac runtime nếu cung cấp nút chạy thật, release workflow. | D2; song song D3/D4 | API image build/start; GPU image build/preflight; native mesh operation và Isaac thực chạy thành công trên GPU thuê; lưu image digest và runtime/config checksums. |
| D6 | Telemetry theo audit đã có: workflow/operation identity, readiness milestones, leaf spans, human task/activity, aggregation/coverage và durable demo summary. | D3 cho demo lifecycle | Có machine step nhỏ/lớn, first usable, human task elapsed và active effort, combined effort và wall union; không đếm cha+con/overlap cùng actor; retries/failure/unknown có policy rõ. |
| D7 | Deployment config + file delivery + CI; `deploy/studio/*`, Next config/API URLs, CORS/cookie/cache, scoped release checks và runbook. | D3–D5; D6 nếu demo thu số benchmark | Kiểm env fail-closed; file lớn/range/presign qua domain thật; secrets server-only; gate CI chạy thật; deploy/rollback theo digest. |
| D8 | Staging acceptance, đóng bundle và release receipt. | D7 | Qua ma trận mục 8; restore từ bundle trên môi trường trống; mới gắn production demo URL vào kênh giới thiệu. |

Telemetry D6 là điều kiện bắt buộc nếu dùng demo để thu/công bố các chỉ số người + máy theo yêu cầu trước. Có thể triển khai staging trước khi hoàn thiện D6, nhưng không công bố benchmark tổng khi coverage chưa đủ.

Không cần hoàn thành autoscaler/serverless, chín scene dataset hoặc mọi backlog để phát hành demo đầu với một mẫu hoàn chỉnh. Không bỏ acceptance thật của các nút được cung cấp.

## 6. Bundle phát hành

Bundle gồm code/runtime, dữ liệu mẫu và cấu hình triển khai. Không đưa hàng GB artifact vào Git hay frontend build.

```text
real2sim-demo-<release>/
  RELEASE.json                 # code SHA, schema versions, image digests, runtime/config/registry checksums
  SHA256SUMS                   # checksum các file bundle
  deploy/                      # templates đã kiểm, không có secret
  runbook/                     # bootstrap, smoke, cancellation, backup/restore, rollback
  data/
    r2s-demo-data.zip           # canonical data package đã curated và verify
    sample-catalog.json        # ĐỀ XUẤT: danh sách sample/version/readiness; cần D4
  licenses/                    # notices và quyền phân phối dataset/runtime/weights
  evidence/                    # build/preflight, import/verify, acceptance và cleanup receipts đã lọc riêng tư
```

`RELEASE.json`, catalog và release wrapper ở trên là đầu ra cần bổ sung, chưa phải CLI/format đã có. Image được lưu trên registry theo digest; có thể thêm OCI archive cho chuyển offline nếu cần, không cần nhét image vào ZIP dữ liệu.

### Nội dung dữ liệu

- Public demo manifest + public payload và frozen `workspace/snapshot.json`/artifact graph/history cần cho các stage/reset.
- Terminal validation records/selections và bản ghi cần replay nếu thực sự có. Không giả lập completed cho stage thiếu.
- Rerun recordings/preview cần thiết, kèm allowlist và retention. Worker scratch, caches tùy chọn và dữ liệu không liên quan bị loại.
- PostgreSQL seed/import tối thiểu nếu cần khôi phục job thực; active sessions/invites/tokens/leases không chuyển sang deployment mới. Không mang password hash dev mặc định sang production; bootstrap Reviewer theo runbook hiện có trên target đã import.
- Phân biệt public file allowlist với private baseline phục vụ worker. Raw input có thể cần tính toán nhưng không được biến thành public download bởi việc export workspace.
- Giữ rights attestation hiện có và kiểm license/attribution của từng dataset/model/vendor cho phạm vi phân phối. Không coi attestation là giấy phép phân phối mọi dependency.

### Dùng lại tooling hiện tại

Các lệnh sau là command template cho giai đoạn đóng gói; chưa chạy trong audit này. Dùng interpreter đúng môi trường (`.venv/bin/python`). Các đường dẫn `/secure/...` là chỗ đặt dữ liệu riêng do operator chuẩn bị.

```bash
.venv/bin/python -m scripts.studio.data_package pack --out /secure/releases/r2s-demo-data.zip
.venv/bin/python -m scripts.studio.data_package verify /secure/releases/r2s-demo-data.zip
.venv/bin/python -m scripts.studio.deploy_env check --source /secure/production.env
.venv/bin/python -m scripts.studio.deploy_env render --source /secure/production.env --out-dir /secure/rendered
```

Hiện `pack` lấy toàn bộ canonical roots, chưa có `--sample`/curated selection. Không chạy thẳng trên máy dev rồi coi toàn bộ data là gói demo chọn lọc. D4 cần selector hoặc staging export chỉ có dữ liệu đã duyệt, vẫn bảo toàn refs. Pack kiểm nguồn bất biến và từ chối active work; cần thời điểm snapshot ổn định. Không tự dừng job để lấy snapshot.

Publisher hiện có, với env của target staging riêng được nạp an toàn:

```bash
.venv/bin/python -m scripts.cloud.package_publish --package /secure/releases/r2s-demo-data.zip --report /secure/reports/publish-dry-run.json
.venv/bin/python -m scripts.cloud.package_publish --package /secure/releases/r2s-demo-data.zip --apply --report /secure/reports/publish.json
.venv/bin/python -m scripts.cloud.package_publish provision --package /secure/releases/r2s-demo-data.zip --target-root /app/data --report /secure/reports/provision.json
```

Hai lệnh cuối ghi dữ liệu thật. `--apply` hiện chỉ dành cho DB target rỗng và main artifact tree; `provision` copy optional demo/preview/Rerun lên volume, không publish chúng vào R2. Chúng chưa thay thế D3/D4. Không import lặp lên DB production đã có người dùng và không dùng publisher làm cơ chế migration nâng cấp.

Env secret là bàn giao riêng qua secret manager/provider env, không nằm trong release archive. Giữ nguyên logic scrub mặc định; chế độ giữ password của đúng hai seed user là khả năng kỹ thuật đã có, không phải lựa chọn mặc định cho demo công khai.

## 7. CI, repository và thứ tự deploy

### Repository

- Repo đang PRIVATE trong `AI20K-Build-Phase-Cohort-4`. Giữ repo hiện tại là phương án mặc định; không cần clone lên public để host app.
- Vercel hỗ trợ private repo, nhưng Hobby không kết nối private GitHub organization repo; Pro/Enterprise còn kiểm membership/commit author. Chọn gói/tài khoản phù hợp hoặc host frontend bằng container.
- Railway có GitHub App integration. Deploy private registry image là lựa chọn khác và hiện cần Pro; không đồng nhất giới hạn private registry với GitHub source deploy.
- GHCR private image có thể pull bằng quyền read package thích hợp. Secret pull chỉ cấp cho bên chạy image.
- Nếu sau này chủ động public code: làm audit tracked files + Git history + license/vendor và tách dữ liệu/secret trước. Audit hiện tại không chứng nhận repo/history đã an toàn để public.
- CI của SHA hiện tại thất bại trước khi có step vì billing/spending limit. Public repo không sửa lỗi kiến trúc demo; giải quyết runner độc lập rồi lấy receipts của release candidate.
- Workflow CI hiện chỉ lint/test/build, chưa có pipeline release image + data + acceptance. Frontend CI build cũng cần kiểm SuperSplat editor build từ fresh checkout, theo production command `npm run build:editor && npm run build`.

### Trình tự rollout

1. Hoàn thành D1–D5, D7; D6 cho số đo đầy đủ. Khóa release candidate SHA và các lockfiles; không dùng tag `latest` làm identity nghiệm thu.
2. Tạo staging DB/bucket-prefix riêng, credential và origin riêng. Cấu hình TLS, CORS R2 đúng methods/headers, auth cookie secure và auth origin. Kiểm không có URL localhost trong build/artifact links.
3. Build image trên máy đủ disk; `Dockerfile.gpu` cần `COLMAP_IMAGE` đã ghim. Push image digest; preflight trên GPU thuê. Ghi hardware/runtime evidence, qualification registry và launcher Isaac nếu cung cấp.
4. Verify bundle; dry-run import vào target trống; apply dữ liệu và catalog/baseline theo D4. Bootstrap Reviewer riêng sau import. Không khởi API tạo seed state trước rồi mong empty-target import vẫn qua.
5. Deploy API, janitor và worker. Kiểm `/health`, runtime discovery, readiness baseline, connectivity DB/R2 và queue. Session catalog main phải có trước khi nhận phiên.
6. Deploy Studio root `frontend/`, build editor và app, cấu hình `REAL2SIM_API_URL` tại build time. Railway config nested cần chọn rõ `deploy/studio/railway-api.json`; không giả định tự được phát hiện ở repo root.
7. Chạy ma trận nghiệm thu. Lưu release receipt; chỉ sau đó promote lên origin demo production với DB/bucket namespace riêng và cùng digest.
8. Xác nhận URL Studio cuối cùng. Landing chỉ cần trỏ đến URL đó nếu khác URL đang dùng; không build/deploy lại landing trong scope này.

## 8. Ma trận nghiệm thu trước mở demo

Đây là các kiểm tra cần chạy khi implementation/deployment được thực hiện, chưa chạy ở lần lập kế hoạch.

| Nhóm | Kịch bản bắt buộc |
| --- | --- |
| Fresh environment | Từ checkout/image/bundle, không dùng runtime hay artifact có sẵn trên laptop; khởi động production env, verify mọi identity. |
| Stage replay | Mở mọi stage có artifact của DrJohnson; mesh/collider/Walk/export theo gate thật; Draft samples thể hiện đúng điểm dừng. Không biến job SUCCEEDED thành bằng chứng tất cả stage ready. |
| Hai người cùng mẫu | A move/apply/build/reset; B vẫn baseline. Hai phiên cùng logical job IDs. Đổi API instance giữa hai request vẫn giữ đúng phiên. |
| GPU thật | Tạo mesh/áp vùng khi cần, pipeline rerun và Isaac nếu cung cấp; queue/progress/cancel/retry. Fixture/mock/idle worker không đủ nghiệm thu. |
| Revision | Thay scene trong lúc operation chạy; CAS/fence từ chối publication cũ, lỗi có thể hiểu và retry được; reset/root restore không đổi source. |
| Cleanup | Đóng tab, không gửi DELETE, mất mạng, TTL, kill worker/API rồi restart, unpublish sample. Thu hồi quyền trước dọn; không late publish, không orphan process, baseline và phiên B còn nguyên. |
| Resource | Queue giữa real job và demo; giới hạn GPU/RAM/disk hoạt động toàn cục, không mỗi session một quota máy riêng. Đo cold start, peak và chi phí workload thật. |
| File delivery | Upload multipart/resume và download file lớn, HTTP Range, URL hết hạn, CORS; GLB/SOG/frames/Rerun/export qua domain thật. Vercel Function limit không tự áp cho mọi external rewrite; kiểm đúng đường request, không đoán. |
| Access | Token thiếu/sai/đã đóng, request ngoài job/project, raw protected input, sample không publish, direct object path. Log/referrer không lộ capability/credentials. |
| Telemetry | First usable, mesh subspans, failed/cancelled/retry, human task/activity, overlap cùng người nhiều tab, coverage thiếu; summary còn sau cleanup. |
| Recovery | Restore bundle vào namespace trống khác, chạy lại smoke. Rollback app/image/config về release trước khi không tương thích schema; không xóa dữ liệu mới để ép rollback. |

Các checks implementation phải theo scope thay đổi: Ruff check/format, focused backend tests, TypeScript/ESLint/Vitest, fresh frontend/editor build; PostgreSQL/R2 integration và cloud/browser/GPU/Isaac acceptance ghi riêng pass/fail/skip. Không gọi local test pass là cloud acceptance.

## 9. Rollback và vận hành

- Mỗi release giữ code SHA, image digest, config/runtime/registry checksums và sample versions. Baseline bất biến; thay mẫu bằng version mới, chuyển catalog pointer sau verify.
- Có cờ chặn nhận phiên/operation mới khi cần drain. Thu hồi session theo namespace; dừng đúng operation/worker ownership, không kill theo tên process chung hoặc xóa cả bucket.
- Backup DB và baseline trước migration/import; migration nâng cấp additive khi có thể. Nếu schema mới không tương thích image cũ, rollback cần forward fix hoặc restore sang môi trường riêng theo runbook, không chỉ redeploy image cũ.
- Monitor queue age, worker heartbeat/lease, operation error/cancel, session expiry backlog, orphan objects, disk/VRAM/RAM, upload/download failure và GPU hours. Phân biệt liveness `/health` với readiness có worker/baseline/runtime.
- Người vận hành cung cấp quyền provider/domain/registry và trần ngân sách. Code readiness, release receipts và bundle phải chuẩn bị xong trước bước tạo/deploy tài nguyên tính phí.

## 10. Bằng chứng và giới hạn của lần rà soát

- Đã dùng graphify query và CodeGraph trước khi dò nguồn; đọc deployment templates, DB adapter, session/workspace/worker code, data package/publisher, Dockerfiles và workflow CI.
- Đã đọc lại repo visibility, SHA, GitHub CI annotation và inventory workspace. Worktree sạch ở đầu audit.
- Dựa thêm vào báo cáo local đã commit: `2026-10-19-interactive-demo-sessions.md` và `telemetry-coverage-20261019/report.md`. Những kết quả local trước đó không được tính là test mới của audit này.
- Chưa chạy test suite, Docker build, cloud mutation, GPU workload, Isaac hay browser/DevTools trong lần lập kế hoạch. Chưa tạo ZIP bundle hoặc kiểm toàn bộ checksum của 3.57 GiB workspace. Chưa kiểm toàn bộ Git history/secrets hay mọi dependency license.
- Chỉ thêm file báo cáo này; không commit/push.

### Tài liệu nhà cung cấp được đối chiếu ngày rà soát

- [Vercel private Git repositories và giới hạn Hobby](https://vercel.com/docs/git#deploying-private-git-repositories).
- [Vercel external rewrites](https://vercel.com/docs/routing/rewrites), [Vercel Function limits](https://vercel.com/docs/functions/limitations).
- [Railway source/image services](https://docs.railway.com/services), [private registry](https://docs.railway.com/builds/private-registries).
- [GitHub Container Registry authentication](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).
- [Supabase PostgreSQL connection modes](https://supabase.com/docs/guides/database/connecting-to-postgres).
- [CI run của baseline](https://github.com/AI20K-Build-Phase-Cohort-4/P-087/actions/runs/39234540001).
