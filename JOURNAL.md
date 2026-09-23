# Weekly Journal — Team P-087 (Real2Sim Studio)

> Ghi theo nhóm kết quả, quyết định và bài học. Giai đoạn 17–23/09 là chuẩn bị/Foundation M0; theo [Execution Plan](docs/execution/TEAM_EXECUTION_PLAN.md), Tuần 1 subsystem bring-up bắt đầu 24/09.

---

## Tuần chuẩn bị / Foundation M0: 17/09/2026 - 23/09/2026

### Mục tiêu tuần này
- [x] Xác định Warehouse/Indoor AMR MVP và tài liệu sản phẩm làm source of truth.
- [x] Khóa ownership, shared handoff contracts và bộ task cho bốn track.
- [x] Chuẩn bị Foundation fixtures/tests để các track có thể bắt đầu độc lập.

### Đã hoàn thành
- Đồng bộ [BRIEF](docs/BRIEF.md), [PRD](docs/PRD.md), [Dataset Playbook](docs/DATASET_PLAYBOOK.md) và [execution docs](docs/execution/). TorWIC `Aisle_CW` được chọn làm traversal P0, `Aisle_CCW` là backup; bằng chứng REC-01B được ghi với phần chưa xác nhận tách riêng.
- Thiết lập [harness](AGENTS.md), [kiến trúc](ARCHITECTURE.md), track/task cards và Foundation code: typed contracts, artifact store, synthetic fixtures, positive/negative contract tests và handoff checker. Kết quả ở đây là fixture/integration proof.
- Khóa yêu cầu EX-PRODUCT: Web Studio có view **3DGS thật** ở P0 và kỹ sư chuyển sang geometry, point cloud, collider để kiểm tra; bổ sung source map/references đồ họa. Chưa implement browser renderer hay chứng minh tương thích với output Brush thật.
- Nâng cấp backend scaffold đa provider và luồng AI-log, chuẩn hóa Python 3.12/dependency setup; đây là hạ tầng phát triển, không phải Real2Sim E2E.

### Khó khăn & Giải pháp
| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| Tài liệu mô tả không thống nhất về SceneIR, ReconstructionBundle, validation, task ID và ranh giới dữ liệu GT. | Phân quyền source of truth, sửa contract/crosswalk và kiểm tra bằng shared schemas/fixtures. | Bốn track có handoff mẫu cùng schema; không cần chờ upstream chạy GPU để bắt đầu code. |
| Dễ nhầm dataset-native TorWIC facts với quy ước universal hoặc đánh đồng synthetic proof với real acceptance. | Tách TorWIC adapter/evaluation provenance khỏi canonical models; ghi rõ mức độ bằng chứng trong docs/checker. | Foundation không hard-code một traversal vào shared contract; real reconstruction/Isaac vẫn là việc sau M0. |
| Viewer ban đầu mô tả 3DGS là stretch hoặc coi mesh/point cloud là fallback. | Đồng bộ PRD, Architecture, Playbook và task EX-PRODUCT; 3DGS thành yêu cầu P0, các view kỹ thuật là chế độ xem riêng. | Scope của coding agent rõ hơn, nhưng renderer candidate vẫn phải kiểm chứng với Brush artifact thật. |

### Bài học
- Universal ở contract, concrete ở adapter: không để TorWIC, Brush hay Isaac định nghĩa dữ liệu trao đổi của toàn hệ thống.
- Fixture/contract pass giúp phát triển song song, nhưng không thay thế acceptance của pipeline thật, trình duyệt hay GPU runtime.
- Một quyết định kiến trúc phải cập nhật authority và các projection/task liên quan; tóm tắt chat không đủ làm source of truth.

### Kế hoạch tuần sau
- [ ] Bốn track branch từ cùng baseline SHA sau khi hoàn tất review/CI; giữ shared contract change dưới producer–consumer review.
- [ ] EX-REC inspect dữ liệu TorWIC thực trước REC-02; EX-SCENE, EX-SIM, EX-PRODUCT phát triển từ fixtures tương ứng.
- [ ] EX-PRODUCT scaffold frontend/backend workflow và kiểm chứng riêng browser 3DGS bằng Brush output thật; không báo fixture viewer là AC-11 pass.
- [ ] Khóa dần benchmark inputs và exact GPU/Isaac/tool versions khi có dữ liệu/máy thật; không tự điền TBD.

---

<!-- Các mục sau là khung trống, không phải báo cáo đã thực hiện hay cam kết milestone mới. -->

## Tuần 1 — Subsystem Bring-up: 24/09/2026 - 28/09/2026

### Mục tiêu tuần này
- [ ] [Mục tiêu thực tế của giai đoạn]

### Đã hoàn thành
- [Chỉ điền kết quả đã có bằng chứng]

### Khó khăn & Giải pháp
| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| [Vấn đề thực tế] | [Cách xử lý] | [Kết quả/evidence] |

### Bài học
- [Bài học từ công việc thực tế]

### Kế hoạch tuần sau
- [ ] [Bước tiếp theo khi đã xác nhận]

---

## Tuần 2 — Build + Integration #1: 29/09/2026 - 05/10/2026

### Mục tiêu tuần này
- [ ] [Mục tiêu thực tế của giai đoạn]

### Đã hoàn thành
- [Chỉ điền kết quả đã có bằng chứng]

### Khó khăn & Giải pháp
| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| [Vấn đề thực tế] | [Cách xử lý] | [Kết quả/evidence] |

### Bài học
- [Bài học từ công việc thực tế]

### Kế hoạch tuần sau
- [ ] [Bước tiếp theo khi đã xác nhận]

---

## Tuần 3 — E2E + Feature Freeze: 06/10/2026 - 12/10/2026

### Mục tiêu tuần này
- [ ] [Mục tiêu thực tế của giai đoạn]

### Đã hoàn thành
- [Chỉ điền kết quả đã có bằng chứng]

### Khó khăn & Giải pháp
| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| [Vấn đề thực tế] | [Cách xử lý] | [Kết quả/evidence] |

### Bài học
- [Bài học từ công việc thực tế]

### Kế hoạch tuần sau
- [ ] [Bước tiếp theo khi đã xác nhận]

---

## Giai đoạn Integration Buffer + Pitch Sprint: 13/10/2026 - 19/10/2026

### Mục tiêu tuần này
- [ ] [Mục tiêu thực tế của giai đoạn]

### Đã hoàn thành
- [Chỉ điền kết quả đã có bằng chứng]

### Khó khăn & Giải pháp
| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| [Vấn đề thực tế] | [Cách xử lý] | [Kết quả/evidence] |

### Bài học
- [Bài học từ công việc thực tế]

### Kế hoạch tuần sau
- [ ] [Bước tiếp theo khi đã xác nhận]

---

## Ngày 20/10/2026 — Nhật ký bổ sung (chưa có milestone trong Execution Plan)

### Mục tiêu tuần này
- [ ] [Mục tiêu thực tế của giai đoạn]

### Đã hoàn thành
- [Chỉ điền kết quả đã có bằng chứng]

### Khó khăn & Giải pháp
| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| [Vấn đề thực tế] | [Cách xử lý] | [Kết quả/evidence] |

### Bài học
- [Bài học từ công việc thực tế]

### Kế hoạch tuần sau
- [ ] [Bước tiếp theo khi đã xác nhận]

---

<!-- Sau 20/10, sao chép cùng cấu trúc khi cần; chỉ điền nội dung có evidence. -->
