# T-044: Trang tiến trình nói đúng và đủ cho cả scene thật lẫn scene mẫu

## Goal
Người xem trang tiến trình (scene thật) và trang phát lại "Thử mẫu" hiểu được mỗi bước làm gì **với chính scene đó**, bằng
tiếng Việt rõ ràng; khung xem bên cạnh mọi bước đều có nội dung; bản phát lại có đủ bước như scene thật.

Ba phần, làm theo thứ tự:
1. Viết lại câu mô tả từng bước cho đúng pipeline hiện tại.
2. Lấp khung xem trống của scene mẫu, thêm bước "Duyệt vật & Tạo mesh" vào bản phát lại, ghi đúng thời gian thật.
3. Dòng kết quả thật dưới mỗi bước của scene thật.

Scene mẫu sẽ được chủ dự án **chạy lại bằng pipeline mới rồi xuất lại**; task này không chạy lại pipeline, chỉ làm cho việc xuất
ghi đủ dữ liệu và trang hiển thị đúng.

## Context (đã kiểm trong code)
- Danh sách bước và câu mô tả: `frontend/src/features/studio/stages.ts` (`MVP_STAGES`, `METRIC_STAGE`, `GEOMETRY_STAGE`,
  `OBJECT_STAGE`, `GEOMETRY_REVIEW_STAGE`, ba bước LiDAR). Dùng chung cho tab Tiến trình (`scene/ProgressTab.tsx`) và trang phát
  lại (`SampleFlow.tsx` → `stagesFor`, `DemoShowcase.tsx` lấy `meta.description` làm chú thích).
- Câu mô tả đang lệch với pipeline:
  - Quyền riêng tư / Tách khung hình: không nói tới **che mặt và biển số** (EgoBlur) và việc **dừng chờ người dùng duyệt bản đã
    che** (`progress.sanitized_frame_stage`, `awaiting_anonymization_review`).
  - Xác nhận tỉ lệ mét: chỉ nói đo tay; thực tế hệ thống **tự đề xuất tỉ lệ** (`runner._propose_metric`, `MetricProposal.method`
    = `moge2_sparse_depth_scale_only` hoặc `lidar_trajectory_alignment`).
  - Collision môi trường: không nói tới collision **lấy từ LiDAR** (`select_lidar_collision_source`).
  - Duyệt vật & Tạo mesh: không nói tới bề mặt **từ ObjectGS** và việc **dùng cách cũ khi ObjectGS không đạt** (commit
    `7d348ea4`).
  - "Kiểm tra video": vẫn đúng với job video; giữ tên, nhưng câu mô tả phải đúng cả khi gói có thêm LiDAR/quỹ đạo.
- Khung xem của trang phát lại (`DemoShowcase.tsx`): `STAGE_PRESENTERS` (`showcase/registry.tsx:47`) chỉ có 5 bước đầu.
  Ba bước Xác nhận tỉ lệ mét, Collision môi trường, Tách vật thể **không có thẻ**, và 5 gói trong `data/demo/library` không kèm
  asset nào cho bước nào (`stages[].assets` rỗng) → cả 3 bước hiện "mẫu chưa kèm hình hay số đo để hiển thị".
- Bước "Duyệt vật & Tạo mesh" là hàng **chỉ có ở giao diện** (`GEOMETRY_REVIEW_STAGE_ID = "UI-GEOMETRY-REVIEW"`), trạng thái lấy
  từ `ObjectifyState`; bundle mẫu không có bước này nên bản phát lại dừng ở "Tách vật thể".
- Thời gian ba bước đầu trong cả 5 gói là `0.0` giây. Xuất mẫu (`samples/export.py:100–130`) tính `end - start` với `start`
  lấy `cursor` khi stage không có `started_at`; ba bước này hoàn tất gần như cùng lúc trong bước prepare nên ra 0.
- Asset của bundle: `DemoStageAsset.kind` ∈ `image`, `video`, `facts` (`samples/models.py:79`); xuất asset qua
  `load_stage_assets` / `StageAssetSpec`.
- Tab Tiến trình đã có chỗ cho dòng phụ dưới tên bước: `TimelineStageView.note` (`PipelineTimeline.tsx:24–28`).

## Phần 1 — Câu mô tả (chỉ frontend)
Viết lại `description` (và `title`/`short` nếu cần) trong `stages.ts`. Yêu cầu câu chữ:
- Tiếng Việt đời thường, mỗi bước 1–2 câu, nói **bước này làm gì cho scene của bạn** và **khi nào bạn phải làm gì**.
- Không dùng tên thư viện trừ khi giúp người dùng hiểu (được nói "COLMAP", "3D Gaussian Splatting"; tránh "CoACD", "REC-05",
  "voxel" không giải thích). Không viết tắt không giải thích.
- Nói đúng các nhánh: có/không che mặt; tỉ lệ do máy đề xuất hoặc đo tay; collision từ ảnh hoặc từ LiDAR; bề mặt vật từ
  ObjectGS hoặc cách cũ.
- Nội dung đề xuất (engineer được chỉnh câu, giữ ý):
  - Kiểm tra đầu vào: "Đọc toàn bộ video (và gói LiDAR, quỹ đạo nếu có), đo độ nét và độ rung trước khi chạy các bước nặng."
  - Quyền riêng tư: "Ghi nhận cam kết của người tải lên. Nếu bạn bật che mặt và biển số, hệ thống làm mờ ở bước tách khung
    hình."
  - Tách khung hình: "Tách video thành ảnh, giữ ảnh đủ nét. Nếu bật che, các ảnh được làm mờ và job dừng chờ bạn xem lại bản đã
    che trước khi dựng 3D."
  - Ước lượng camera: "Tìm vị trí và hướng máy quay ở từng ảnh (COLMAP). Có quỹ đạo hoặc LiDAR thì dùng làm điểm tựa."
  - Dựng 3DGS: "Dựng cảnh 3D xem được từ mọi góc (3D Gaussian Splatting) trên GPU."
  - Xác nhận tỉ lệ mét: "Hệ thống đề xuất tỉ lệ thật (từ ảnh hoặc từ LiDAR). Bạn chấp nhận đề xuất hoặc tự đo một khoảng cách
    thật, rồi chọn mặt sàn."
  - Collision môi trường: "Dựng lưới va chạm cho cả căn phòng để robot không đi xuyên tường, sàn. Có LiDAR thì có thể dùng lưới
    từ LiDAR."
  - Tách vật thể: "Tách scene thành từng vật ứng viên để bạn duyệt. Chưa có lưới va chạm riêng cho từng vật ở bước này."
  - Duyệt vật & Tạo mesh: "Bạn xác nhận vật, sửa vùng nếu cần, rồi bấm Tạo mesh: hệ thống dựng bề mặt và lưới va chạm cho từng
    vật (ObjectGS khi bật; vật nào không đạt thì dùng cách cũ), vá nền. Xong bước này mới đi bộ (Walk) và xuất gói được."
- Test: snapshot nhỏ không cần; thêm test kiểm mỗi bước có mô tả, không chứa các chữ cấm ("CoACD", "REC-", "voxel") và không
  dài quá 2 câu. Sửa test hiện có nếu so nguyên văn câu cũ.
- Commit: `Rewrite pipeline step descriptions in plain Vietnamese for the current pipeline`.

## Phần 2 — Khung xem và bản phát lại của scene mẫu
1. **Thẻ dựng sẵn cho 3 bước còn trống** (`showcase/registry.tsx`, `STAGE_PRESENTERS`), dựa trên dữ liệu bundle có (thêm trường
   nếu thiếu, xem mục 3):
   - Xác nhận tỉ lệ mét: tỉ lệ (m/đơn vị), nguồn (đo tay / máy đề xuất từ ảnh / từ LiDAR), đoạn kiểm C–D và sai số nếu có.
   - Collision môi trường: ảnh chụp lưới va chạm (image asset) hoặc số liệu (số tam giác, nguồn ảnh/LiDAR).
   - Tách vật thể: số vật ứng viên, ảnh có khung các vật nếu bundle có.
2. **Bước "Duyệt vật & Tạo mesh" trong bản phát lại**: thêm vào bundle một mục ghi kết quả bước này (đề xuất: `object_geometry`
   ở cấp manifest, gồm trạng thái, thời gian, số vật có bề mặt ObjectGS / cách cũ, số collider), và `stagesFor`/`SampleFlow`
   chèn hàng `GEOMETRY_REVIEW_STAGE` khi bundle có mục này. Bundle cũ không có mục → không hiện hàng (không vỡ).
3. **Xuất mẫu (`samples/export.py`)** ghi đủ dữ liệu cho 1–2: tỉ lệ và nguồn tỉ lệ, số liệu collision, số vật, mục
   `object_geometry`, và asset ảnh nếu job có sẵn ảnh xem trước (không render ảnh mới trong task này). Manifest bundle thêm trường
   phải **tuỳ chọn** để 5 gói cũ vẫn đọc được (`samples/models.py`, parser frontend `parseDemoManifest`).
4. **Thời gian thật**: không bao giờ ghi `0.0` giả. Ba bước chạy chung trong bước prepare: nếu không đo được riêng từng bước thì
   ghi `null` cho từng bước và thêm thời gian chung của bước prepare vào bước đầu kèm ghi chú "gộp chung 3 bước", hoặc cho runner
   ghi `started_at`/`completed_at` thật cho từng bước nếu làm được gọn. Chọn một, ghi lý do vào report. Bản phát lại hiện "chưa
   đo" thay vì "0 giây" khi `null`.
5. Test: export từ job giả có/không ObjectGS, có/không LiDAR, có/không che → manifest đúng trường; bundle cũ (fixture của gói
   hiện có) vẫn parse; replay hiện hàng Duyệt vật khi có mục, không hiện khi không có; không còn "0 giây" cho bước không đo được.
6. Kiểm thật: xuất **một** mẫu từ job hiện có (`job-b8f744da2286`) vào **thư mục tạm** (không ghi vào `data/demo/library`), mở
   bằng parser và ghi nội dung vào report. Không ghi đè thư viện mẫu.
7. Commit theo từng ý (thẻ, mục object_geometry, export, thời gian).

## Phần 3 — Dòng kết quả thật dưới mỗi bước của scene thật
1. Backend: thêm vào `StageProgress` một trường tuỳ chọn `note: str | None` (tiếng Việt, ngắn, một dòng) do máy chủ soạn từ dữ
   liệu đã có, **không đoán**:
   - Tách khung hình: "Đã che N vùng (mặt, biển số); bạn đã chấp nhận" / "Chờ bạn duyệt N vùng đã che" (từ bản đã che và
     acceptance, `anonymization_review.py`).
   - Xác nhận tỉ lệ mét: "Tỉ lệ máy đề xuất từ ảnh, bạn đã chấp nhận" / "từ LiDAR" / "Bạn đo tay" (từ `MetricProposal.method` và
     bản xác nhận của job).
   - Collision môi trường: "Lưới từ ảnh" / "Lưới từ LiDAR".
   - Tách vật thể: "N vật ứng viên".
   - Hàng Duyệt vật & Tạo mesh (frontend đang tự tính từ `ObjectifyState`): thêm vào note số vật có bề mặt ObjectGS và số vật dùng
     cách cũ, nếu dữ liệu QA có (commit `7d348ea4`).
   Bước không có dữ liệu → `note = None`, không hiện gì.
2. Contract hai phía: `progress.py` (`StageProgress`), mirror frontend `lib/contracts/studio.ts` (`StageProgress`,
   `parseJobProgress` kiểm `note` là chuỗi hoặc null), `scripts/check_contract_mirror.py` phải xanh.
3. Frontend `ProgressTab.tsx`: truyền `note` vào `TimelineStageView` (đã có chỗ hiển thị).
4. Chi phí: `job_progress` được gọi thường xuyên (UI poll). Không đọc artifact lớn mỗi lần: chỉ đọc manifest/receipt nhỏ, hoặc
   cache theo checksum revision. Đo thời gian `/progress` trước/sau trên 3 job local, ghi vào report; tăng quá 50 ms thì cache.
5. Test backend cho từng nhánh note; test frontend hiện note; test không có note không vỡ.
6. Commit theo từng ý.

## Acceptance criteria
1. Mọi bước có câu mô tả tiếng Việt rõ, đúng pipeline hiện tại, không chữ cấm.
2. Trang phát lại: không bước nào hiện "mẫu chưa kèm hình hay số đo" khi bundle mới có dữ liệu; có hàng "Duyệt vật & Tạo mesh"
   khi bundle có mục; không có "0 giây" giả; 5 gói cũ vẫn mở được.
3. Tab Tiến trình của scene thật hiện dòng kết quả thật ở các bước có dữ liệu; `/progress` không chậm đáng kể.
4. Contract mirror xanh.

## Tests required
```
.venv/bin/python -m pytest tests/test_orchestration/test_sample_export.py tests/test_api/test_sample_routes.py \
  tests/test_orchestration -q -k "progress or sample" 
.venv/bin/python scripts/check_contract_mirror.py
cd frontend && ./node_modules/.bin/vitest run tests/pipeline-timeline.test.tsx <test replay/showcase> <test ProgressTab> <test mới> \
  && npm run typecheck && ./node_modules/.bin/eslint <file đã sửa>
.venv/bin/ruff check <file py đã sửa> && .venv/bin/ruff format --check <file py đã sửa>
```

## Commit
Theo từng phần, từng ý. Đúng path. Không Co-Authored-By. `graphify update .`, `report.md`, `status.md`. Không ghi vào
`data/demo/library`. Kiểm giao diện bằng mắt là việc của chủ dự án.
