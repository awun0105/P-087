# T-019 — Deep code review: geometry review, region editing, shell build

Ngày: 2026-10-16. Baseline: branch `mvp-pipeline-v2`, HEAD `69611ea9c117b537cf4b90672565123400b666d1`.

**Kết luận: chưa đủ điều kiện nghiệm thu trên scene mới.** Có hai lỗi P1 đã tái hiện: build làm mất số đếm inpaint khiến
preflight chặn scene Ready; box khởi tạo khi mở lại editor có thể làm mất membership vừa duyệt. Full regression là một gate
riêng; suite xanh không loại bỏ hai lỗi này.

## Phạm vi và phương pháp

Review phần triển khai T-001..T-018 và T-020, tập trung các seam:

`preset → objectify Draft → source membership → region preview/apply → queue/partial build → representation → Walk/USD`.

Đã đọc `.ai/architecture.md`, roadmap, plan T-019, review T-008/T-011/T-015..T-018; đối chiếu invariant của
`TEAM_EXECUTION_CONTRACT.md` §1/§3.6, UX spec §2.3 và các entrypoint code hiện tại. Dùng graphify để định hướng và CodeGraph
để đọc source/callers. Các đoạn lớn bị CodeGraph cắt được đọc tiếp đúng vùng chưa trả về. Không audit toàn bộ repo hoặc
xác nhận lại mọi acceptance đã ghi ở task cũ.

Chứng cứ gồm full regression, test CoACD/USD local, probe service dùng fixture và benchmark. Probe cố ý xác nhận hành vi lỗi,
không phải regression test để nghiệm thu bản sửa. Không chạy train, không sửa/retry job thật, không dùng dịch vụ GPU trả phí.

## Phát hiện còn mở

| ID | Mức | Phát hiện | Chứng cứ |
| --- | --- | --- | --- |
| GR-01 | P1 | Mất `inpainted_gaussians` khi build geometry, làm hỏng kiểm tra background representation | Probe với PLY đầy đủ: preflight FAIL; sửa đúng count trong bản sao in-memory → PASS |
| GR-02 | P1 | Mở lại Region Editor dùng box tâm 0 dù membership đã lệch tâm | Không kéo box: preview tự loại 121/600 Gaussian |
| GR-03 | P2 | Vật đã Ignore vẫn có thể chặn build vì lỗi vỏ, nhưng banner bỏ vật đó khỏi cảnh báo | Probe build thất bại trên vật IGNORED |
| GR-04 | P2 | Preview cho phép claim làm vật cho còn dưới 50 hàng; Apply mới từ chối | Preview claim 400/400; Apply trả lỗi donor dưới 50 |
| GR-05 | P2 | Preview 2 triệu hàng vượt mục tiêu 1,5 giây; cache cold giữ lock trong bước đọc/fit sàn | Benchmark và profile, chưa đo HTTP hoặc scene thật |
| GR-06 | P2 | Lỗi 409 ở preview không có luồng phục hồi như lỗi 409 ở Apply | Source: hook bỏ HTTP status, panel chỉ bật nút Tải lại từ catch của Apply |

### GR-01 — Giữ số đếm inpaint cùng revision mới

**Source:** `src/services/orchestration/scene/object_geometry_build.py:545` nhận `master, visual, _` từ
`run_inpaint_and_package`; `_build_environment` chỉ trả SceneEnvironment. `build_object_geometry:852` ghi provenance revision
mới mà không cập nhật số đếm inpaint. `src/services/scene/representation_integrity.py:52-73` kiểm số hàng background theo
`scene.provenance.inpainted_gaussians`, mặc định 0; provenance correction chỉ được chọn khi có `operation=reassign`.

**Trigger:** inpaint thật thêm bất kỳ hàng nào và scene còn vật cần SOURCE representation, ví dụ ứng viên chưa Confirm hoặc
vật Ignore/ẩn theo policy hiện tại. Background master có số hàng nguồn + hàng inpaint, nhưng count trong scene bằng 0 hoặc
giữ count cũ sau partial rebuild. Kiểm representation trả `SOURCE_BACKGROUND_INVALID`, kéo theo preflight FAIL và không tạo
CandidatePackage, dù geometry builder đã publish `object_geometry=ready`.

**Tái hiện:** dùng `draft_scene` với Gaussian PLY đủ 14 field bắt buộc; provider inpaint giữ nguyên prefix nền rồi thêm 1 hàng,
trả `inpainted_gaussians=1`; CoACD và SOG là test double. Sau `build`:

```text
issues = [('candidate-001', 'SOURCE_BACKGROUND_INVALID'), ('candidate-002', 'SOURCE_BACKGROUND_INVALID')]
preflight = FAIL
with correct in-memory count = PASS
```

Không chỉ dựa vào fixture có visual hỏng: probe đầu có lỗi visual riêng; probe thứ hai sửa layout/visual để chỉ còn lỗi
background. [Log probe cô lập](evidence/inpaint-valid-probe.txt).

**Hướng sửa:** đưa receipt/count inpaint từ helper về builder và ghi đúng metadata ở cùng revision với background master.
Full build và partial build đều phải thay count bằng lần chạy mới, kể cả từ dương về 0. Không sửa validator để bỏ kiểm đếm.

**Acceptance:** Draft → build với inpaint >0, giữ ít nhất một ứng viên → Confirm một vật → preflight + package PASS; partial
rebuild thay đổi count phải PASS; sửa sai prefix/count phải tiếp tục FAIL. Fixture phải có PLY đủ field, không chỉ trả count
giả mà giữ nguyên bytes.

### GR-02 — Không suy box tâm 0 từ kích thước sau chỉnh vùng

**Source:** `frontend/src/features/studio/region/region-session.ts:31-41` luôn tạo `center=[0,0,0]`, `half=dims/2`.
`object_region.py:145-170` và `object_geometry_build.py:797-818` giữ nguyên source frame, chỉ cập nhật kích thước `ptp`, không
đưa tâm bounding box local mới xuống client. `ObjectReviewView.tsx:675-677` gọi lại initializer khi mở phiên mới.

**Trigger:** Apply chỉnh vùng bất đối xứng, đóng panel rồi mở lại. Tâm nguồn phải giữ nguyên theo architecture §7.1; tâm nhóm
Gaussian mới không nhất thiết bằng 0. Kích thước chỉ cho độ dài cạnh, không đủ xác định box chứa nhóm hiện tại.

**Tái hiện:** fixture với source pose quay 90°, mở rộng membership theo một phía; Apply tạo nhóm 600 hàng. Local bounds mới:

```text
min = [-0.199632, -0.599990, -0.197485]
max = [ 0.198994,  0.199999,  0.199735]
initial half = [0.199313, 0.399995, 0.198610], center = [0,0,0]
preview khi mở lại: removed=121, remaining=479
```

Chỉ mở panel chưa ghi dữ liệu. Nếu người dùng Apply box mặc định đó, những hàng ngoài box bị trả về nền.
[Log](evidence/review-probes.txt).

**Hướng sửa:** trả/persist bounds hoặc box của membership theo source-local, rồi fit center `(min+max)/2` và half extent với
dung sai thống nhất. Nếu chọn persist box command, phải xử lý cả vật donor bị claim và chỉnh bằng Brush/Lasso. Không căn lại
`source_transform` để sửa lỗi UI.

**Acceptance:** chỉnh lệch tâm → Apply → đóng/mở → preview mặc định không loại hàng hiện có; kiểm cả Draft/Ready, donor bị
claim, source pose quay và Move hiện tại khác pose nguồn. Box ban đầu không được tự claim thêm Gaussian nền ngoài ý muốn;
việc mở lại command cũ và việc fit bounds cần có policy/test rõ ràng.

### GR-03 — Hiện đầy đủ vật thực sự chặn build

**Source:** `GeometryReviewBanner.tsx:8-27` loại IGNORED/DELETED/MERGED trước khi tính `shellErrors`.
`object_geometry_build.py:698-735` vẫn build mọi vật mapped, kể cả tombstone; `_build_shell:371-375` từ chối `shell_error`.
`object_region._resolve:78-83` không cho sửa trực tiếp vật đã Ignore/Delete/Merge.

**Tái hiện:** gắn `shell_error` cho vật A, Ignore A, giữ B → banner chỉ còn B, không hiện lỗi A; build vẫn fail ở A. Head cũ
được giữ. Đây là lỗi chỉ dẫn UX; việc build tombstone để Restore là quyết định đã được review T-007/T-011 chấp nhận.

**Hướng sửa:** cảnh báo theo tập vật builder thực sự xử lý; nêu vật đã loại vẫn cần hình học để Restore, chỉ đường Restore →
chỉnh vùng → build. Không âm thầm bỏ tombstone hoặc tạo OBB. **Acceptance:** test banner và service dùng chung case
Ignored+shell_error; người dùng thấy tên vật và hành động khắc phục trước khi bấm Tạo mesh.

### GR-04 — Preview phải báo tính hợp lệ của donor

**Source:** `region_box.resolve_region:109-127` chỉ kiểm số hàng của target; `object_region.preview_region:108-123` không gọi
`_require_remaining_rows`. Draft Apply:136-138 và Ready admission:245-247 mới kiểm donor.

**Tái hiện:** box bao hết 400 hàng của B, `claim_from=[B]` → preview hợp lệ với `claimed[B]=400`; Apply từ chối B còn 0 hàng.
Không có lỗi mất dữ liệu vì Apply fail trước publication. [Log](evidence/review-probes.txt).

**Hướng sửa:** trả donor remaining/validation blocker trong preview hoặc dùng cùng validator trước trả preview. UI phải cho
thu box/bỏ claim mà không mất phiên. **Acceptance:** donor còn 49 → Apply disabled kèm tên và số hàng; còn 50 → được phép;
Draft/Ready cùng quy tắc, không làm lệch các bộ đếm membership chính xác.

### GR-05 — Chi phí preview và ngân sách bộ nhớ

**Source:** `membership_regeneration.load_membership_source:78-89` giữ `_SOURCE_LOCK` cả khi đọc PLY, checksum và fit sàn.
Cache 2 mục chứa positions/rows/floor; key chứa labels checksum nên Apply đổi labels sẽ làm đọc/fit lại cùng PLY nguồn.
`region_box.resolve_region:98-101` biến đổi toàn bộ source sang local; `object_region._resolve:96` tạo local toàn bộ lần nữa.
Giới hạn 100k hàng ở `preview_region:110-114` chỉ giảm bước dựng vỏ, không giảm hai lượt biến đổi hoặc decode labels.

Đo trên 2.000.000 hàng, seed 90, box 0,6 m chứa toàn bộ một khối điểm; PLY/store/shell/QA thật. Stub fit sàn và floor mask;
`OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1`; có regression và workload khác chạy đồng thời. Đây là số đo local có contention,
không phải throughput hay SLO của production.

| Lần đo | Cold | Warm 1 | Warm 2 | Peak RSS toàn process |
| --- | --- | --- | --- | --- |
| Đầu | 7,021 s | 2,158 s | 1,740 s | 486,1 MiB |
| Lặp có profile | 3,515 s | 2,133 s | 1,574 s | 486,4 MiB |

Profile một lần warm: tổng 1,871 s; `_shell` 1,119 s, `_filter_gaussians` 0,955 s; `_resolve` 0,725 s; loader 0,325 s.
Counts giữ đúng 2 triệu, shell chỉ dùng 100.000 hàng và QA pass. [Profile](evidence/preview-profile.txt).

Mục tiêu <1,5 s của architecture chưa đạt trong phép đo này. Fixture chỉ có 7 field float32; PLY 62 field float32 là ví dụ
248 byte/hàng: 2 triệu hàng đã ~473 MiB chỉ cho rows. Giới hạn 2 cache entry không phải giới hạn byte. RSS ở bảng gồm cả
fixture, import và vùng tạm, không phải kích thước cache riêng.

Test budget 300k hiện có cũng fail trong nhóm regression với 1,563 s; chạy riêng khi máy vẫn có tải trả 1,873 s, vẫn fail.
Không phân loại hai failure này thành flaky đã hết; giữ GR-05 là vấn đề hiệu năng còn mở. Không đổi giới hạn 1,5 s.

**Thứ tự tối ưu:** tái dùng một phép transform; cache dữ liệu nguồn/floor theo source identity và bảo vệ bằng ngân sách byte;
tách lock quản lý LRU khỏi công việc đọc/fit dài; đo profile lại trước giảm chi phí lọc kNN. Labels vẫn phải checksum/decode
đúng manifest hiện tại. Không cache mutable labels hoặc nới floor/QA để đạt latency.

**Acceptance:** benchmark cold/warm riêng, 1 và 16 box, ít/nhiều owner, PLY đủ SH, floor fit thật; đo p50/p95, RSS và hai job
đồng thời trên máy định danh; thêm HTTP/browser timing và abort. Không nâng timeout test để gọi đó là tối ưu.

### GR-06 — Phục hồi 409 từ preview

**Source:** `useRegionPreview.ts:62-65` chỉ lưu chuỗi lỗi, mất status 409; `RegionEditor.tsx:149-151,313-335` chỉ hiện nút
Tải lại khi catch của Apply đặt `conflict=true`.

**Trigger:** preview trả 409 do scene đổi trước khi có preview thành công. Apply bị disable đúng, nhưng panel không có CTA
Tải lại như trường hợp Apply 409. Cha có thể tự tải khi nhận revision mới; thiếu sót còn thấy khi chưa nhận revision đó.
Đây là phát hiện tĩnh, chưa xác minh trên browser có poll/network thật.

**Hướng sửa/acceptance:** hook giữ loại lỗi/status; preview409 và apply409 đều hiện Tải lại, giữ boxes/claims; sau reload chỉ
bật Apply khi có preview khớp revision/checksum mới. Test rejected preview409, reload rồi preview thành công.

## Regression đã sửa trong T-019

**GR-07 — palette, đã xử lý:** full frontend bắt 7 dòng mã màu viết cứng ở region-overlay/shell-glow. Đổi sang `themeColor`
với token `--studio-sage`, `--studio-rust`, `--studio-ochre`, `--studio-on-dark` và fallback cũ; không bypass palette test.
68 test palette/overlay/shell pass; full frontend sau sửa 839/839 pass. Màu/độ tương phản của lớp 3D vẫn cần xem trên browser.

Full frontend lần đầu còn có test region-editor kiểm spy trước khi effect flush và unified-input-flow timeout 5 s. Cả hai
pass khi chạy lại 3 file, rồi pass trong full rerun. Không sửa logic production hoặc tăng timeout để che hai lần fail này.

**GR-08 — partial build trên Draft, đã xử lý:** test có sẵn `test_objectgs_build_rejects_partial_object_ids` fail ổn định vì
builder không raise. Trước sửa, gọi service với `object_ids={A}` trên Draft bỏ qua gate full-build, chỉ dựng collider A rồi
ghi `object_geometry=ready` cho cả scene; B còn collider null. Đây là đường gọi service trực tiếp; route build hiện tại không
nhận `object_ids`, nên không kết luận có request HTTP công khai khai thác được lỗi này.

T-019 thêm guard ở `build_object_geometry:612`: chỉ nhận `object_ids` khi scene Ready. Full build Draft và partial Ready giữ
nguyên hành vi. Test mới `test_partial_draft_build_does_not_publish_ready` kiểm scene/head và danh sách artifact không đổi
khi từ chối. Các caller cần kiểm: objectify queue, region rebuild, membership regeneration; xem kết quả thực trong report.

## Đánh giá chất lượng code

| Khía cạnh | Đánh giá dựa trên source/test |
| --- | --- |
| Tách trách nhiệm | Region resolution thuần numpy; API, queue, artifact và geometry stages tách tương đối rõ. Helper dùng chung giữ CoACD/inpaint qua process boundary. |
| An toàn dữ liệu | Revision/checksum fence, immutable source frame, kiểm count và CAS giúp lỗi/cancel không thay head. Không thấy đường âm thầm dùng OBB để báo collider thành công trong luồng đã đọc. |
| Bảo mật API | Region/build dùng contributor và job mutation guard; role matrix nằm trong regression. Không thấy bỏ guard ở các route mới đã đọc. |
| Tính nhất quán | Hai seam chưa kín: inpaint receipt → provenance → representation validator; membership local bounds → editor initializer. Đây là lỗi tích hợp, không phải lỗi syntax/type. |
| Khả năng bảo trì | `build_object_geometry` dài gần 300 dòng; quy đổi local Gaussian/quaternion lặp ở Draft Apply và Ready rebuild. Ưu tiên test invariant trước khi tách thêm helper; chưa có lý do refactor lớn. |
| Quan sát lỗi | Build có phase, operation_id và durable failure; preview có shell_error. Shell asset load vẫn bị catch im lặng ở viewer; khó phân biệt chưa nạp/không có shell. |
| Test | Nhiều test cho fence/cancel/claim/legacy và CoACD thật. Khoảng trống: nonzero inpaint, reopen sau bất đối xứng, donor underflow trong preview, 2M/SH/floor thật, browser lifecycle thật. |

Fixture geometry trước T-019 dùng PLY 7 field và `visual_ref` trỏ bytes `preview`. Test đóng gói mới lộ hai giới hạn đó:
preflight pending SOURCE báo visual invalid, và hybrid exporter thiếu `rot_1`. T-019 bổ sung đủ layout và PLY local của từng
vật trong fixture, rồi chạy lại nhóm caller liên quan. Không sửa exporter hoặc bỏ validator để chấp nhận fixture hỏng.

## Thứ tự xử lý đề xuất

1. **GR-01**, backend: preserve receipt inpaint ở full/partial build; regression representation + package có pending object.
2. **GR-02**, backend/frontend: chọn nguồn bounds/command để khởi tạo lại region; giữ frame bất biến; test reopen/donor/Move.
3. **GR-03, GR-04, GR-06**, từng thay đổi UX nhỏ: blocker banner, donor validity, reload409. Không gộp vào tối ưu geometry.
4. **GR-05**, đo và tối ưu sau khi các invariant trên được khoá; giữ checksum/floor/quality gate.
5. Chạy E2E scene mới: Draft → chỉnh vùng → build → Confirm/Move → Walk → USD → Isaac, kèm cancel, lỗi QA và Restore.

Đây là backlog có acceptance trong tài liệu này; chưa tự tạo hoặc thực hiện task sửa các finding còn mở. GPU ObjectGS,
quality mask, kéo box thật, GPU-buffer lifetime và Isaac physics chưa được nghiệm thu. DevTools kết nối được nhưng chỉ có
`about:blank`, không có phiên Studio đang đăng nhập để kiểm các luồng đó.
