# Ổn định pipeline, một mô hình tiến trình và xem scene nhanh — kế hoạch tổng (Sprint 8, T-046 → T-069)

> **Cho agent thực thi:** làm từng task theo `.ai/tasks/T-xxx/plan.md`, đúng thứ tự cột "Cần" trong `roadmap.md`.
> Mỗi task có bước test trước, rồi code, rồi commit. Đọc file này trước task đầu tiên của mỗi đợt.

**Mục tiêu:** pipeline chạy không kẹt, không chết vì lỗi thoáng qua; backend có **một** nguồn trả lời "pipeline đang ở
bước nào, ai đang phải làm gì"; giao diện chỉ hiển thị nguồn đó; mở trang scene và xem từng bước **nhanh, nhẹ, mượt**.
Đây là nền cho telemetry thời gian (làm sau, không thuộc sprint này).

**Kiến trúc:**
1. Sửa lỗ hổng chạy của ba hàng đợi job / tách vật / kiểm định.
2. Tải file theo checksum được trình duyệt giữ vĩnh viễn; backend không băm lại, không dựng lại thứ đã có; trang scene chỉ
   poll một endpoint nhẹ.
3. Ghi **mốc bước** vào bảng `r2s_step_marks` thay vì suy luận; một hàm trạng thái hình học; hàm thuần `next_action()`;
   endpoint `GET /api/v1/jobs/{job_id}/pipeline`.
4. Giao diện: một vòng poll, một bảng nhãn, viewer không dựng lại và không vẽ thừa, tải lười phần nặng.

**Công nghệ:** Python 3 / FastAPI / Pydantic v2, runtime DB SQLite hoặc PostgreSQL qua `RuntimeDatabase`; kho file R2;
Next.js / React / Vitest; PlayCanvas / supersplat-viewer; splat-transform.

**Căn cứ:** audit code ngày 20/10/2026, bảy báo cáo: mô hình trạng thái backend, giao diện tiến trình, độ ổn định khi chạy,
đường tải viewer, đường phục vụ backend, lượng request và re-render trang scene. Số dòng và số đo được chép vào "Context"
của từng task.

## Mốc đo hiện tại (đo trên dữ liệu thật trong `data/studio_local`, bản sao DB SQLite)

| Việc | Hiện tại |
|---|---|
| Tải lưới va chạm Walk (`/walk-collision`) | 760–1121 ms mỗi lần, 29 MB, dựng lại mỗi request, không bao giờ 304 |
| Tải một file artifact | ~60 ms cố định + SHA-256 cả file (SOG 31 MB: 138–209 ms) |
| `GET /jobs/{id}/scene` | 35–45 ms, SceneIR 590–660 KB không nén, băm + parse mỗi lần |
| `GET /jobs/{id}/scene/objectify` | 34–42 ms, parse cả SceneIR chỉ để đọc vài trường |
| `GET /scenes` | 31 ms warm, 588 ms lần đầu, 28 transaction mỗi lần poll |
| Bộ đệm trình duyệt cho file | không bao giờ trúng: `private, no-cache`; production đổi URL ký R2 mỗi lần |
| Trang scene, scene đã xong | ~18 request/phút, tải lại cả SceneIR mỗi 10 s (3,9–5,8 MB/phút), re-render cả trang mỗi 3 s, hai đồng hồ 1 s |
| Viewer Studio | một mảng `[]` mới mỗi render ép vẽ lại 3D; tab ẩn vẫn render; Walk tiếp tục vẽ khi đổi tab |
| Mở Studio scene Ready | Ammo 1,2 MB + lưới va chạm + 60 file PLY vật (47–96 MB) tải ngay, kể cả khi không Walk |
| Xem bước 5 → 6 → 7 → 8 | tải và giải mã lại 3–4 lần cùng một SOG 10–30 MB |
| Bước Frames | tới 48 ảnh PNG gốc 7–8 MB mỗi ảnh, không có ảnh thu nhỏ |
| Splat | 0,54–2,0 triệu splat, màu bậc 3, không có LOD |

Mỗi task tối ưu ghi số **trước / sau** vào `report.md` theo đúng cách đo trong plan của task.

## Quy tắc chung (mọi task phải tuân)

- Nhánh `develop`. Không tạo nhánh, không push, không PR. Commit nhỏ sau mỗi bước xanh, `git add` đúng path,
  message tiếng Anh, **không** `Co-Authored-By` / "Generated with".
- **Job và scene đã có phải xem và thao tác được như cũ.** Cụ thể:
  - Trường mới trong model đã lưu (JSON trong DB, artifact, journal) phải **không bắt buộc**, mặc định `None` / rỗng.
  - Model có checksum (`_seal_operation`, manifest, journal) thêm trường thì dùng
    `Field(default=None, exclude_if=lambda value: value is None)` như `JobAttemptRecord.requested_by`.
  - Thêm giá trị vào `Literal` thì được; **bỏ** giá trị cũ thì không.
  - Mỗi task chạm model đã lưu có một test đọc bản ghi cũ dạng JSON thật (dán literal trong test).
  - Artifact mới (SOG nhẹ, ảnh thu nhỏ, SOG của vật) chỉ có ở job mới hoặc được tạo lười; job cũ không có thì dùng đường
    cũ, không lỗi.
- Schema DB đổi bằng migration mới (`MIGRATIONS += ((26, (...)),)` trong `jobs/database.py`). Code cũ từ chối DB schema
  mới hơn (`database.py:646`), nên **API và worker phải lên cùng lúc**. Ghi rõ trong report của task có migration.
- Endpoint cũ giữ shape. Chỉ thêm trường hoặc thêm endpoint.
- **Bảo mật bộ đệm:** file chỉ được cache `private` (không `public`), vì mọi request vẫn qua kiểm quyền. Bộ đệm phía server
  khoá theo checksum hoặc revision, không theo tham số client tự chọn.
- Ghi mốc bước là ranh giới đo: lỗi ghi mốc ngoài transaction không làm hỏng job, nhưng `logger.warning` có mã job.
- Không đọc docs để ra quyết định. Gặp câu hỏi plan không trả lời: dừng, ghi vào `report.md`, đặt `changes-requested`.
- Câu hiển thị: tiếng Việt rõ, nói nguyên nhân và việc nên làm.
- Không chạy full suite trừ T-069. Mỗi task chạy lệnh trong "Tests required" + ruff cho Python đã sửa + `npm run typecheck`
  và eslint khi sửa TypeScript. Sau khi sửa code: `graphify update .`.
- Không đụng đóng gói / Docker / số worker uvicorn (việc của người khác); ghi khuyến nghị vào report nếu cần.

## Làm song song với phiên khác trên cùng cây (bắt buộc)

Có ít nhất một phiên Claude khác sửa code trên cùng thư mục, cùng nhánh `develop`. Không có nhánh riêng để gộp sau, nên
mọi xung đột xảy ra ngay trên đĩa. Quy tắc:

1. **Trước mỗi Step**: chạy `git status --short` và `git log --oneline -10`. File nào có thay đổi chưa commit mà không phải
   của mình thì **không sửa file đó**. Chờ phiên kia commit, hoặc ghi vào `report.md` và chuyển Step khác.
2. **Trước khi sửa một hàm**: đọc lại hàm từ đĩa (không dùng bản đã đọc từ trước), vì phiên kia có thể vừa commit thay đổi.
   Nếu thay đổi của họ đã làm một phần việc của Step, **dùng lại**, không viết bản thứ hai. Ghi vào report commit nào đã
   làm phần đó.
3. **Chỉ `git add` đúng file mình sửa**, không `-A`, không `.`. Không `git stash`, `git checkout -- <file>`, `git reset`,
   `git restore` trên file không phải của mình. Không sửa format hàng loạt (`ruff format` chỉ trên file mình sửa).
4. **Migration DB**: trước khi thêm, đọc `MIGRATIONS` mới nhất; dùng số kế tiếp **lúc commit**, không phải lúc lập plan.
   Nếu phiên kia đã dùng v26, lấy v27 và cập nhật plan/report.
5. **Hợp đồng chung** (`StageId`, `ObjectifyState`, `SceneSummary`, `JobProgressResponse`, kiểu trong
   `frontend/src/lib/contracts/*`): chỉ thêm, không đổi tên, không xoá. Thêm xong chạy test của cả backend và frontend có
   dùng kiểu đó.
6. Test của phiên kia đỏ sau khi mình sửa: dừng, tìm nguyên nhân; không sửa test của họ cho xanh. Ghi vào report.
7. Phần việc đã biết phiên kia đang làm được đánh dấu "**Phiên khác**" trong plan task tương ứng.
8. Phạm vi phiên deploy (p-087-39) theo tin nhắn ngày 20/10: hạ tầng GPU / RunPod / release catalog; nếu sửa code chỉ ở
   `src/services/orchestration/gpu/*`, `scripts/cloud/gpu_catalog.py`, `scripts/gpu/*`, `Dockerfile.gpu`. Sprint 8 **không**
   sửa các đường dẫn đó. Họ đã commit: pool kết nối PostgreSQL (`e2735834`, `7fc53c0d`, `jobs/database.py`), đệm allow-list
   (`847c3aa9`, `projects/registry.py`), sửa băm lặp khi publish gói (`64be6c48`). Họ không thêm migration; v26 dành cho T-056.
9. **Production tự deploy khi `develop` được push** lên remote `awun0105` (API ở VM Seoul). Sprint 8 không push (quy tắc
   `.ai/README.md`). Chủ dự án push khi sẵn sàng; migration v26 sẽ lên production ngay lúc đó. Khi worker GPU đã bật, API và
   worker phải deploy cùng lúc. Ghi nhắc này trong report của T-056 và HANDOFF của T-069.

## Từ vựng thống nhất

| Khái niệm | Tên | Ở đâu |
|---|---|---|
| Mã bước | `StageId` hiện có, **thêm** `ANONYMIZATION_REVIEW = "ST-ANONYMIZATION-REVIEW"` | `src/models/contracts/manifests.py` |
| Bước người dùng duyệt vật trước Tạo mesh | `StageId.OBJECT_CONFIRM` (đã có, chưa dùng) | — |
| Bước Tạo mesh (vỏ, ObjectGS, collider, nền) | `StageId.SCENE_DECOMPOSE` (đã có, chỉ làm nhãn artifact) | — |
| Ai làm bước | `StepActor = Literal["system", "user"]` | `pipeline/models.py` (T-059) |
| Trạng thái bước | `StepState = Literal["pending","queued","running","waiting","succeeded","failed","cancelled","skipped"]`; `waiting` **chỉ** cho chờ người | `pipeline/models.py` |
| Mốc bước | bảng `r2s_step_marks`, model `StepMark` | `jobs/step_marks.py` (T-056) |
| Pha của hàng đợi tách vật | `ObjectifyPhase` (Literal) | `scene/objectify_queue.py` (T-057) |
| Việc tiếp theo | `NextActionKind`, `NextAction` | `pipeline/next_action.py` (T-058) |
| Trạng thái hình học theo vật | `object_geometry_state()` (cổng) + `object_geometry_view()` (hiển thị) | `src/services/scene/geometry_state.py` (T-055) |
| Bộ đệm đọc theo checksum | `ParsedArtifactCache` | `src/services/orchestration/artifacts/parsed_cache.py` (T-053) |

`NextActionKind` (thứ tự là thứ tự quy tắc trong T-058):
`wait_system`, `review_anonymization`, `confirm_metric`, `retry_job`, `job_failed`, `job_cancelled`, `retry_geometry`,
`review_objects`, `choose_object_method`, `confirm_objects`, `scene_ready`, `released`, `await_review`, `review_package`,
`fix_preflight`, `create_package`.

## Danh sách task

| Đợt | ID | Tiêu đề | Cần | Cỡ |
|---|---|---|---|---|
| A. Chạy ổn định | T-046 | Vòng lặp worker không chết vì một lỗi | – | S |
| | T-047 | Tắt worker giữa chừng thì cho chạy lại, kể cả job cũ | – | S |
| | T-048 | Không còn job RUNNING mà không ai trông | T-047 | M |
| | T-049 | Chịu lỗi DB thoáng qua khi gia hạn và kiểm hủy | T-046 | M |
| | T-050 | Chờ tài nguyên và hạn tự tính không lặp vô hạn | T-049 | M |
| B. Backend phục vụ nhanh | T-051 | File theo checksum: trình duyệt giữ vĩnh viễn, không băm lại, URL R2 ổn định | – | L |
| | T-052 | Lưới va chạm Walk dựng một lần, trả 304 | T-051 | M |
| | T-053 | Đệm SceneIR / JobManifest đã parse; nén gzip; preflight CORS | – | M |
| | T-054 | Danh sách scene và stage-views nhẹ | T-053 | M |
| C. Một mô hình bước | T-055 | Một hàm trạng thái hình học theo vật | – | S |
| | T-056 | Bảng mốc bước, ghi từ pipeline job | T-048 | L |
| | T-057 | Pha có kiểu và mốc bước cho hàng đợi tách vật | T-050, T-056 | M |
| | T-058 | Hàm thuần "việc tiếp theo" | T-055 | M |
| | T-059 | Endpoint tiến trình hợp nhất, nhẹ, có 304 | T-053, T-056, T-057, T-058 | L |
| D. Giao diện gọn và nhẹ | T-060 | Một vòng poll mỗi trang, không re-render khi không đổi | T-059 | M |
| | T-061 | Dòng tiến trình vẽ từ bước thật | T-060 | M |
| | T-062 | Một nguồn "việc cần làm" cho chuông, banner, đầu trang, danh sách | T-061 | L |
| | T-063 | Một nguồn dữ liệu scene/gói/duyệt; dọn nhánh chết | T-062 | M |
| E. Viewer nhanh, mượt | T-064 | Viewer không dựng lại, không vẽ thừa, tab ẩn thì nghỉ | T-060 | M |
| | T-065 | Tải lười: Ammo, lưới va chạm, collider chỉ khi Walk; trang bước tải song song, chia nhỏ JS | T-064 | M |
| | T-066 | Ảnh frame thu nhỏ | T-051 | S |
| | T-067 | Vật nhẹ: SOG cho vật, tải giới hạn đồng thời, vỏ không tải lại khi chọn | T-064 | L |
| | T-068 | SOG xem nhanh: bản màu bậc 0 và LOD cho job mới | T-051 | L |
| Bàn giao | T-069 | Full regression, đo trước/sau, bàn giao | tất cả | M |

Thứ tự gợi ý: A và B chạy trước (B cho lợi ngay cho mọi scene cũ, không phụ thuộc mô hình bước). C sau. D và E sau T-059 /
T-060. T-066 và T-068 làm được sớm, độc lập giao diện.

## Ngoài phạm vi (ghi backlog, không làm)

- Telemetry thời gian (máy, người, tới khi scene dùng được) — đọc từ `r2s_step_marks`, làm sau.
- Chạy API nhiều tiến trình (uvicorn `--workers`): khuyến nghị 2–4 tiến trình trên VM production vì xử lý nặng một
  request chặn mọi poll khác; việc đóng gói/khởi động do người khác làm.
- Nén ở proxy trước API trên VM (cấu hình không nằm trong repo).
- Một viewer sống xuyên các trang bước (giữ WebGL giữa route) — cần đổi layout lớn; T-064 chỉ chặn dựng lại trong cùng trang.
- Gộp `ValidationRunView.run_status`/`.status`; bỏ `SceneRevisionStatus.PROCESSING/VALIDATING`.
- Đưa gói mô phỏng và kiểm định Isaac thành bước trên dòng tiến trình.
- Thống nhất TTL lease 10 phút của job với 90 giây của hai hàng đợi kia.

## Điểm dễ hỏng mà test phải giữ (Review Focus)

1. **Bản ghi cũ trong `r2s_scene_requests` có `phase` tự do** ("observations", "collider_and_background", "queued",
   "done", tên pha shell/objectgs/quality/collider/environment/publish, giá trị lạ). Đọc không lỗi; lạ thành `None`. T-057.
2. **Scene cũ thiếu khoá `object_geometry`**: không hiện hàng Duyệt vật / Tạo mesh, vẫn xuất gói được. T-055, T-059.
3. **Job cũ không có mốc** vẫn có dòng tiến trình đủ, `timing_source="inferred"`. T-059.
4. **Job FAILED vì tắt worker trước khi sửa** hiện nút Thử lại và `POST /retry` nhận. T-047.
5. **Xác nhận tỉ lệ mét ở tab khác** làm trang đang mở đi tiếp trong ≤ 15 giây không tải lại. T-060.
6. **File đổi nội dung nhưng giữ URI** (ví dụ ghi đè sai) không được phục vụ từ bộ đệm cũ: bộ đệm khoá theo checksum, kiểm
   theo `(kích thước, mtime)` như `require_unchanged`. T-051.
7. **Người không có quyền** không nhận được file từ bộ đệm phía server: kiểm quyền chạy trước mọi lần trả từ bộ đệm. T-051,
   T-052.
8. **Scene cũ không có SOG nhẹ, SOG vật, ảnh thu nhỏ** vẫn mở được bằng file gốc. T-066, T-067, T-068.
