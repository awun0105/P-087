# EX-PRODUCT — Metric baseline tuần 1

**Track Owner:** Cường.
**Ngày đo:** 26/09/2026.
**Nguồn yêu cầu:** [`TEAM_EXECUTION_PLAN.md`](../../TEAM_EXECUTION_PLAN.md) §5.4.1
(dòng 254-261) và bảng metric ownership §7.2.1 (dòng 433-449).

File này là **protocol + kết quả** cho ba metric Tier D mà `EX-PRODUCT` sở hữu.
Nó không định nghĩa metric mới và không đặt ngưỡng nghiệm thu.

---

## 1. Ba metric và vị trí của chúng

PRD §10.3 (dòng 1010-1021) xếp ba metric này vào **Tier D — Giá trị sản phẩm**, và
ghi rõ: *"So sánh workflow có công cụ với manual baseline; là KPI sản phẩm, **không
tự động chặn demo kỹ thuật**"*. Không được đọc baseline dưới đây thành release gate.

| Metric | Định nghĩa dùng để đo | Owner |
|---|---|---|
| **Human Active Time** | Thời gian người **thực sự thao tác**, không tính thời gian chờ máy | `EX-PRODUCT` + QA |
| **Manual Step Count** | Số thao tác thủ công phải làm để đi hết luồng | `EX-PRODUCT` + QA |
| **Time to Simulation-ready Scene** | Thời gian từ scene đến khi scene **tải được vào simulator mục tiêu và hoàn thành validation đã định nghĩa** | `EX-PRODUCT` + QA |
| **End-to-end runtime** | Thời gian hệ thống chạy hết một luồng, không có người trong vòng lặp | `EX-PRODUCT` |

**"Simulation-ready"** lấy nguyên định nghĩa ở glossary [PRD](../../PRD.md) dòng 1190:
*"Có thể tải vào phiên bản simulator mục tiêu và hoàn thành validation đã định
nghĩa"*. Đây là định nghĩa hẹp có mốc kết thúc kiểm được, không phải "trông có vẻ
xong".

**Human Active Time** phải theo SM-06 ([PRD](../../PRD.md) dòng 164): **cùng một
người** chạy quy trình thủ công và quy trình có công cụ **trên cùng một scene nhỏ**.
Đo hai người khác nhau rồi so là vô hiệu — đó là lý do metric này không thể thay
bằng script.

---

## 2. Protocol đo

### 2.1 Scene dùng đo

`scene-fixture-001` / `job-fixture-001`, seed từ
[`fixtures/scene_ir/scene.json`](../../../../fixtures/scene_ir/scene.json).

**Đây là fixture, không phải output của `EX-SCENE`.** Mọi số dưới đây là baseline
trên dữ liệu fixture; chưa có baseline trên scene do pipeline thật tạo ra.

### 2.2 Phía tool-assisted — đo được bằng máy

Hai phase, đếm trên **chuỗi lệnh HTTP thật** mà UI phát ra:

| Phase | Các bước | Manual Step Count |
|---|---|---|
| `inspect` | `GET /projects` → `GET /projects/{id}` → `POST /projects/{id}/jobs` → `GET /jobs/{id}/scene` → `GET /jobs/{id}/validation` → `GET /jobs/{id}/review` | **6** |
| `edit` | `GET /jobs/{id}/scene` → `POST /jobs/{id}/scene/edits` | **2** |

Đếm theo **lệnh HTTP**, không đếm click. Click không phải đơn vị ổn định — một
dropdown có thể phát 1 hoặc 3 request tuỳ cách nó cache, nên đếm click sẽ khiến con
số đổi theo implementation UI chứ không theo công việc thật.

**Cách bấm giờ:** `time.perf_counter()` bao quanh từng bước và cả phase; chạy
`REPS = 5` lần; bỏ **1 lần warm-up** vì lần đầu gánh lazy-init (import, đọc fixture,
tạo thư mục) nên không đại diện cho chi phí mỗi thao tác. Báo min/median/max.

Mỗi lần lặp tạo một **job mới** qua `POST /projects/{id}/jobs`, nên chuỗi revision
của job đó luôn bắt đầu từ `rev-001` — số liệu không bị nhiễu bởi revision tích luỹ
của các job cũ trong runtime root.

### 2.3 Phía manual baseline — **chưa chạy, cần một người**

Chưa thực hiện. Cần một người thật làm quy trình thủ công trên **cùng scene nhỏ**,
đối chiếu với 10 bước ở [PRD](../../PRD.md) §1.1 (dòng 80-89):

> nhận và kiểm tra dữ liệu khảo sát → tái dựng 3D → làm sạch hình học → xác định vật
> thể có ý nghĩa → chỉnh metric scale → tạo collision geometry → đồng bộ transform →
> xuất scene sang simulator → kiểm tra xuyên sàn/thiếu collider/đường bị chặn → làm
> lại khi scene thay đổi

Khung này là danh sách bước để đếm `Manual Step Count` phía thủ công.

### 2.4 Điều kiện tiên quyết

Đo trên **tiến trình backend sạch**. Lý do cụ thể: `SceneEditor` từng giữ revision
chỉ trong bộ nhớ, nên sau restart nó phục vụ revision cũ và lần sửa kế tiếp trả
**HTTP 500**. Số liệu lấy trên tiến trình chưa sửa sẽ sai hoặc rỗng. Lỗi này đã
được sửa ngày 26/09 (xem §5) và có test regression khoá lại.

### 2.5 Môi trường

| | |
|---|---|
| OS | Windows 11, build `10.0.26200` |
| Python | 3.11.9 |
| Backend | `uvicorn src.main:app --port 8000`, commit `e63a591`, nhánh `feat/product` |
| Runtime root | `data/artifacts` (`DEFAULT_RUNTIME_ROOT`) |
| Đo lúc | 26/09/2026, backend vừa khởi động lại |

`platform.platform()` báo `Windows-10-10.0.26200-SP0` — Python vẫn dùng sơ đồ
`10.0.x` cho Windows 11, nên chuỗi đó không mâu thuẫn với build `26200`.

---

## 3. Trạng thái metric (PRD §2.2)

PRD §2.2 bắt buộc mỗi metric có một trạng thái và **ghi lại mọi lần chuyển trạng
thái**. Bảng dưới là trạng thái sau ngày đo 26/09.

| Metric | Trạng thái | Ghi chú |
|---|---|---|
| End-to-end runtime | `MEASURE` → **`BASELINE`** | Đã đo trên fixture; xem §4 |
| Manual Step Count (phía tool) | `MEASURE` → **`BASELINE`** | Đếm được từ chuỗi HTTP; xem §4 |
| Manual Step Count (phía thủ công) | `MEASURE` | **Chưa có số** — chờ người |
| Human Active Time | `MEASURE` | **Chưa có số** — chờ người |
| Time to Simulation-ready Scene | `MEASURE` | **Chưa có số** — chờ simulator |

**Không có `LOCKED_ACCEPTANCE_THRESHOLD` nào được đặt.** Hai lý do, cả hai đều là
luật đã có:

- §5.4.1 dòng 259: *"chưa khóa improvement target trước khi baseline tồn tại"* — và
  baseline **thủ công** vẫn chưa tồn tại, nên chưa đủ điều kiện bàn tới target;
- PRD §2.2: *"Không được đặt hoặc thay đổi ngưỡng nghiệm thu sau khi đã xem kết quả
  cuối"* — khóa ngưỡng lúc này sẽ vi phạm cả tinh thần lẫn chữ của điều khoản đó.

**Chuyển trạng thái đã ghi nhận:** `End-to-end runtime` và `Manual Step Count (tool)`
từ `MEASURE` sang `BASELINE` ngày 26/09/2026, trên fixture. Đây là bản ghi duy nhất;
chưa có chuyển trạng thái nào khác.

---

## 4. Kết quả đo được

### 4.1 End-to-end runtime (giây)

5 lần đo, đã bỏ 1 warm-up. Cả 5 lần `apply_edit` đều trả **201**.

| Bước | min | median | max |
|---|---|---|---|
| `list_projects` | 0.0090 | 0.0180 | 0.0237 |
| `project_detail` | 0.0147 | 0.0157 | 0.0178 |
| `create_job` | 0.0267 | 0.0284 | 0.0321 |
| `viewer_scene` | 0.0154 | 0.0305 | 0.0314 |
| `validation` | 0.0220 | 0.0233 | 0.0286 |
| `review` | 0.0147 | 0.0154 | 0.0168 |
| `read_scene` | 0.0151 | 0.0166 | 0.0247 |
| `apply_edit` | 0.0225 | 0.0252 | 0.0272 |
| **INSPECT TOTAL** (6 bước) | **0.1096** | **0.1363** | **0.1412** |
| **EDIT TOTAL** (2 bước) | **0.0397** | **0.0423** | **0.0473** |

Đọc bảng này: `INSPECT TOTAL` median **0.1363 s** là thời gian hệ thống trả lời hết
luồng xem một scene; `EDIT TOTAL` median **0.0423 s** cho một lần sửa transform.
Đây là **thời gian máy**, không phải thời gian người — không được dùng thay cho
Human Active Time.

### 4.2 Manual Step Count (phía tool)

**6** lệnh HTTP cho luồng xem; **2** lệnh HTTP cho một lần sửa transform.

### 4.3 Các ô **chưa có số** — để trống có chủ đích

| Metric | Trạng thái | Vì sao trống |
|---|---|---|
| Human Active Time | **chờ người** | SM-06 đòi cùng một người chạy cả hai quy trình. Không có người thì không có số, và không được suy ra từ `INSPECT TOTAL` |
| Manual Step Count (thủ công) | **chờ người** | Cần người chạy 10 bước ở §1.1 PRD và đếm |
| Time to Simulation-ready Scene | **chờ simulator** | `GET /jobs/{id}/validation` trả `isaac_runtime_proof: false` với `isaac_sim == "UNVERIFIED"`, nên **chưa có mốc kết thúc hợp lệ để bấm giờ**. Scene chưa load được vào Isaac thì chưa "simulation-ready" theo định nghĩa glossary |

Ba ô này **cố ý để trống**. Điền một con số ước lượng vào đây sẽ biến một giả định
thành "baseline" trong hồ sơ của nhóm — đúng thứ mà §5.4.1 ("không ước đoán") và
AGENTS.md §4 (nhãn `UNKNOWN`: "không được điền bằng giả định") cấm.

---

## 5. Lỗi đã tìm ra khi chuẩn bị đo

Việc đo lộ ra một lỗi thật, đã sửa trong cùng ngày.

**Triệu chứng:** sau khi backend restart, `GET /jobs/{id}/scene` trả `rev-001` trong
khi đĩa đã có `rev-001..rev-004`; lần `POST /scene/edits` đầu tiên trả **HTTP 500**
thay vì `201`.

**Nguyên nhân:** `SceneEditor._revisions` chỉ nằm trong bộ nhớ tiến trình và
`current()` seed `rev-001` từ fixture mà không tra đĩa. Tiến trình mới tính ra
`rev-002`, nhưng file đó đã tồn tại với **bytes khác** → `_publish_once` re-raise
`ArtifactAlreadyExistsError` → route không bắt → 500.

**Đã sửa:** `current()` phục hồi revision cao nhất đã publish trên đĩa (fail closed
nếu artifact không tự nhất quán), và route map `ArtifactStoreError` → 409 theo đúng
precedent của `/validation` và `/review`. 9 test mới khoá lại, trong đó 8 test **fail
trên code chưa sửa** — đã kiểm bằng cách vô hiệu hoá đường phục hồi rồi chạy lại.

Ảnh hưởng tới baseline: các số ở §4.1 lấy **sau** khi sửa, trên tiến trình sạch.

---

## 6. Limitations

- **Fixture, không phải output thật.** Scene đo là `scene-fixture-001`; chưa có
  baseline trên scene do pipeline `EX-REC`/`EX-SCENE` tạo ra.
- **Một máy, một lần đo.** Chưa đo trên máy khác, chưa đo lặp giữa các ngày.
- **Chưa có người trong vòng lặp.** Toàn bộ §4.1-4.2 là phía tool-assisted. Chưa có
  manual baseline, nên **chưa thể kết luận** SM-06 (thời gian có công cụ thấp hơn
  thủ công) đúng hay sai — đây mới là một nửa của phép so sánh.
- **Chưa có Isaac.** `Time to Simulation-ready Scene` không đo được cho tới khi có
  lần load Isaac Sim thật.
- **`REPS = 5` là mẫu nhỏ.** Median ổn định qua 5 lần nhưng chưa đủ để nói gì về
  phân bố hay đuôi.
- **Script đo không được commit.** Nó nằm ở `.smoke/measure.py`, và `.smoke/` nằm
  trong `.git/info/exclude` (local-only). Protocol ở §2 phải đủ để dựng lại script;
  nếu muốn giữ script lâu dài thì cần một chỗ canonical trong repo — việc đó chưa
  làm và cần bàn với nhóm trưởng.

---

## 7. Việc tiếp theo

1. Chạy **manual baseline** với một người thật trên cùng scene, đếm theo 10 bước
   §1.1 PRD, rồi điền Human Active Time + Manual Step Count (thủ công).
2. Đo lại **cùng người đó** trên quy trình có công cụ — điều kiện của SM-06.
3. Chỉ sau khi có cả hai vế mới bàn `PROPOSED_TARGET`, và chỉ sau khi target được
   xác nhận mới bàn tới `LOCKED_ACCEPTANCE_THRESHOLD`.
4. Đo `Time to Simulation-ready Scene` khi `EX-SIM` có lần load Isaac Sim thật.
