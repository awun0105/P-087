# Execution Plan: Sắp xếp lại UI/UX Real2Sim Studio

Date: 2026-10-01
Branch: `feat/studio-ux-restructure` (từ `develop` tại `bdc4b92`)

## Status

VALIDATING — đã triển khai increment feedback/navigation/stage views/drafts/lists/
account theo plan chốt 01/10/2026. Static/component proof đã chạy; browser visual
QA và real worker/GPU/roles còn cần evidence riêng (chi tiết checkpoint bên dưới).
Các increment trước vẫn VALIDATING — đã tích hợp landing page Stitch user cung cấp tại `/landing`,
CTA mở app Tổng quan `/`; lint/typecheck, production build và HTTP proof exit 0.
Workspace Inspect đã tới VALIDATING;
lint/typecheck, 187 frontend tests và Webpack production build exit 0. Còn
browser visual QA và real job/GPU proof cho luồng từng giai đoạn.
Đã triển khai `/` Tổng quan, `/scenes` thư viện và CTA tạo scene
trong Scenes. Lượt IA mới đã qua lint, typecheck và 165 frontend tests; HTTP
preview xác nhận hai trang riêng và đúng vị trí CTA. Production build bằng
Webpack exit 0; Turbopack bị EPERM trong môi trường hiện tại. Chưa hoàn tất
browser visual QA, upload qua browser
và real GPU/Isaac proof. Không ghi DONE cho toàn bộ plan khi các cổng này còn mở.
Plan này là record duy nhất cho đợt cải thiện UX sau PR #16; không thay thế
[plan tích hợp Studio](./2026-09-29-studio-completion.md) hoặc
[plan pipeline v2](./2026-09-30-pipeline-v2.md).

## Outcome

### Accepted implementation increment — 01/10/2026

User giao implement plan trong chat. Record này quản lý increment tiếp theo:

- Authority: PRD §3.4, PRODUCT §3.1/§7.1–7.4, D-04–D-12, shared revision/checksum
  contracts, Architecture frontend ownership. Plan mới chốt frontend trước,
  viewer stage riêng, session-tab drafts, account chỉ đọc.
- Owned: frontend Studio/shell/components/tests và PRODUCT/record này.
  Không sửa backend, vendor editor, shared schemas, dependency hoặc Git refs.
- Implementation order: (1) feedback primitives + errors, (2) next action/header,
  (3) URL/navigation guard, (4) progress/attempts/stage views, (5) drafts/auth,
  (6) list controls/account, (7) tests/static/build và runtime proof khả dụng.
- Feedback policy: field errors tại field; mutation/load errors tại panel;
  success toast sau response; autosave dùng revision status; hướng dẫn dài dùng
  HelpDetails. Không toast từ polling hoặc giả download-completed.
- URL: scene tab/mode, stage-6 view, wizard source/step/upload, list query/filter/
  view/sort/page. Native history giữ mounted viewer và metadata Next.
- Draft chỉ giữ field allow-list trong sessionStorage theo actor/source; validate
  upload và processing schema lại; đổi input reset consent; logout xoá drafts.
- Proof required: focused positive/negative tests cho feedback, drafts, guards,
  URL/list state, auth/revision gates; lint/typecheck/full tests/build. Browser
  và real worker/GPU/roles có evidence riêng, không suy từ mocked tests.
- VERIFIED baseline: branch feat/studio-ux-restructure sạch tại ea68053; API
  preview auth_required=false, scenes=[]; CUA chưa có browser.

#### Implementation checkpoint (01/10/2026, increment hiện tại)

- VERIFIED — `feedback.tsx`/`ui-error.ts`: Radix success toast, PageHeader,
  HelpDetails, field/panel errors; lỗi HTTP/network có thông báo phục hồi an toàn.
  Success chỉ sau upload/create/confirm/package/review/auth/team được API ack.
  Autosave vẫn dùng SaveStatus, package preflight FAIL không toast thành công.
- VERIFIED — ScenePage/NextAction/ProgressTab/AttemptHistory: timeline và lịch sử
  records từ API, checksum thu gọn; CTA dựa state/revision, lỗi đọc không suy thành
  thiếu gói. Viewer stage riêng, stage 6 comparison có URL. Bước chưa xong vẫn khoá.
  Default Studio trước SceneIR là viewer chỉ đọc, editor chỉ ở chế độ Gaussian.
- VERIFIED — NavigationGuard/editor-dirty: bridge kiểm origin + frame, timeout/
  abort/cleanup; dirty/UNKNOWN cần xác nhận trước rời editor hoặc đổi mode, kể cả
  native Back. Giữ metadata history Next. Đổi tab giữ mounted Studio; đóng metric
  về Progress, draft đo chỉ dùng trong cùng job/attempt/artifact.
- VERIFIED — NewSceneFlow/drafts/setup forms/useProcessingForm/AuthForms: URL
  source/step/upload/sample, auth next nội bộ xuyên login/register; bản nháp actor/
  source trong sessionStorage, input/schema được đối chiếu, đổi video reset consent.
  Không công bố preset mặc định trước khi restore draft; evaluation cũ bị ẩn khi
  sửa, lỗi có retry. Bỏ bản nháp reset preset; logout xoá storage draft.
- VERIFIED — ScenesHome/JobsPage/ListControls/AccountPage/AppShell: tìm/lọc/view/
  sort/page trong URL, Scenes 12/Jobs 20; import và mẫu nhóm riêng; readonly account
  từ /me, local/guest có state riêng, logout lỗi không báo success.
- Donor ADAPT: File Manager toolbar/grid/list, Tasks table/status, Profile summary,
  auth v2 layout/fields. Dùng Radix/shadcn có sẵn; không thêm dependency/copy vendor.
- Changed boundaries: chỉ PRODUCT, plan này, frontend Studio/shell/components/
  auth adapter và tests. Backend, shared schemas, vendor, package/lockfile, legacy
  routes, Git refs và checkout Claude không bị sửa.

#### Validation / limitations

- `cd frontend && npm run lint`: exit 0, không warning ở lượt cuối.
- `cd frontend && npm run typecheck`: exit 0, Next route typegen + TypeScript.
- `cd frontend && npm test -- --maxWorkers=4`: exit 0, **36 files / 211 tests**.
  24 tests thêm so với baseline 187: feedback/privacy/actor drafts, iframe guard /
  native Back, processing restoration/evaluation retry, account/auth next,
  ScenePage close/reopen và NextAction unknown/retryable; form remount/consent.
- First failures: tests nhãn Inspect cũ và raw transport messages được đổi đúng
  UX policy, vẫn giữ retry/revision/download gates; assertion kiểm nội dung lỗi an
  toàn. Test cancel dialog cần đợi Promise settle; dynamic import khi chạy nhiều
  worker vượt timeout 1s, dùng timeout 3s và 4 workers. Không sửa expected artifact/
  schema để làm xanh. Lint phát hiện declaration/effect issues và đã sửa.
- `cd frontend && REAL2SIM_API_URL=http://127.0.0.1:8011 npm run build -- --webpack`:
  exit 0, route `/account` và stage routes có trong production output. Dùng Webpack
  theo fallback đã ghi ở increment trước; không claim Turbopack build.
- Sau chỉnh snapshot ban đầu của URL hook để tránh SSR/hydration mismatch,
  `npm test -- tests/ux-feedback-drafts.test.tsx tests/ux-navigation-guard.test.tsx
  tests/ux-scene-flow.test.tsx tests/studio-input-flows.test.tsx --maxWorkers=4`:
  exit 0, **4 files / 21 tests**; production build cuối cũng exit 0.
- HTTP smoke trên dev preview `http://127.0.0.1:3011`: `/`, `/scenes`, `/jobs`,
  `/new?source=video&step=setup`, `/account`, `/login?next=...`, `/register`,
  `/landing` đều **200 HTML**. Auth/scenes proxy **200**:
  `auth_required=false`, không user, `scenes=[]`. Đây là HTTP proof, không phải
  browser interaction/hydration hoặc role acceptance.
- CUA inventory: `apps=[]`, `browsers=[]`. Chưa có browser visual QA/screenshots,
  WebGPU/WebGL renderer proof hoặc real upload→metric→objects→package→release.
  Không seed/mock job vào backend. Fixture tests không chứng minh Isaac acceptance.
- Next runtime acceptance: mở preview trong browser, kiểm desktop/hẹp, link tab /
  Back/Forward với Gaussian dirty; chạy real video/PLY và auth-enabled Editor /
  Reviewer khi backend pipeline/artifacts của Claude sẵn sàng. Profile/password
  mutations và Studio v2 theo ADR 0007 thuộc increment/backend khác.

#### Publication checkpoint (01/10/2026)

- User yêu cầu `commit & push`; outcome là lưu increment này trên
  `origin/feat/studio-ux-restructure`. Authority: AGENTS §11 Git Safety.
- Trước publication: HEAD và remote branch đều `ea68053`; index rỗng, scope audit
  xác nhận 41 modified + 18 new source/test files thuộc increment. `.env`, `.next`
  và node_modules được ignore; scan không thấy credential thật trong changed files.
- Proof làm mới: `cd frontend && npm test -- --maxWorkers=4` exit 0,
  **36 files / 211 tests** (17:14 giờ local); `git diff --check` exit 0.
- Scope commit: PRODUCT, plan này và frontend source/tests của increment. Git
  commit/ref là evidence publication; status plan vẫn VALIDATING do runtime gates
  ở trên còn mở.

Người dùng hiểu mình đang ở đâu, có thể chọn đúng đường **dựng từ video / mở 3DGS /
thử mẫu**, theo dõi job, chỉnh scene, kiểm tra và lấy đúng loại kết quả mà không nhầm
preview, bản làm việc, candidate package và release. Điều hướng desktop/màn hẹp,
trạng thái quyền và hành động tiếp theo nhất quán giữa Scenes, Jobs và scene.

Plan đi từ **cấu trúc toàn app → đường nối giữa các màn → nội dung và trạng thái trong
từng màn**. Mỗi lát triển khai sau này phải có diff và proof riêng; chưa coi những
đề xuất trong plan là quyết định sản phẩm đã chấp nhận.

## Context And Authority

- **Authority:** [PRD](../../PRD.md) sở hữu hành vi và acceptance; [shared contract](../../execution/TEAM_EXECUTION_CONTRACT.md)
  sở hữu revision, validation/review/release; [Architecture](../../../ARCHITECTURE.md)
  đặt frontend tại `frontend/` và backend state tại FastAPI/shared artifacts.
- **Design handoff hiện hành:** [PRODUCT.md](../../../PRODUCT.md) §3.1, §7.1–7.4,
  D-04–D-12 và §13; [EX-PRODUCT track](../../execution/tracks/ex_product/TRACK.md).
  Baseline chọn global `Scenes · Jobs · Nhóm` và bốn vùng bên trong scene;
  video mẫu ở Scenes/Scene mới. Request tiếp theo của user thêm Tổng quan `/`
  và tách thư viện `/scenes`; quyết định đã lưu tại PRODUCT.md §3.1/S01.
- **Source đã inspect (VERIFIED, `bdc4b92`):** route group `frontend/src/app/(studio)/`;
  `features/shell/{AppShell,Breadcrumbs}.tsx`; `features/studio/{ScenesHome,JobsPage,NewSceneFlow,UploadDropzone,ScenePage,SceneWorkspace}.tsx`;
  `features/studio/scene/{ProgressTab,StudioTab,ReviewTab,ResultsTab}.tsx`;
  `lib/api/studio.ts`; `frontend/package.json`.
- **Tình trạng đồng thời:** checkout chính `feat/pipeline-v2` có thay đổi backend/shared
  contract chưa commit. Worktree UX tách riêng; không lấy các field còn dang dở làm
  nguồn dữ liệu UI. TEAM_EXECUTION_CONTRACT §3.7.0 vẫn ghi pipeline v2 là *Proposed*.
- **Baseline ban đầu:** inspect source/tài liệu tại `bdc4b92`; chưa lấy được ảnh
  browser trước edit. Đến lượt validation, API upload và HTTP route smoke đã chạy
  với dữ liệu QA cô lập; browser visual QA vẫn chưa chạy. Không gọi các quan sát
  HTTP hoặc jsdom là baseline screenshot hay browser acceptance.

### Donor UI được user chỉ định — VERIFIED

Checkout tham chiếu: `/home/lqaq/PROJECT/AI20K/private/UI-UX/next-shadcn-admin-dashboard`
tại commit `3502692575348c01512d5c496648e9a948769bd6` (MIT; `LICENSE`). Đã đọc
navigation, shell, các trang dưới đây và ảnh `media/default/default-light.webp`.
`frontend/THIRD_PARTY_NOTICES.md` xác nhận Real2Sim **đã** mang shadcn wrapper,
hook mobile và shell từ donor commit này; lát UX không copy lại bộ nền đã có.

| Donor source (tương đối với donor root) | Mẫu cần tận dụng trong Real2Sim | Ranh giới |
| --- | --- | --- |
| `src/navigation/sidebar/sidebar-items.ts`, `src/app/(main)/dashboard/_components/sidebar/{nav-main,app-sidebar,nav-user}.tsx` | Nhóm menu có tiêu đề, active item, submenu khi cần, thu sidebar thành icon hoặc sheet màn hẹp, CTA và tài khoản cuối thanh. Ánh xạ sang `features/shell/AppShell.tsx`. | Không copy danh sách Dashboards/Pages/Legacy/Misc, Quick Create phụ, account switcher mẫu hoặc mở menu cho route chưa có. |
| `src/app/(main)/dashboard/layout.tsx` | Nhịp shell/sidebar → header mảnh → vùng nội dung; màn editor được ưu tiên không gian ngang. | Không lấy theme switcher, layout playground, global search giả hoặc GitHub menu; giữ theme beige/cam D-04 và AppShell hiện có. |
| `src/app/(main)/dashboard/default/page.tsx` và `_components/` | Phân cấp tiêu đề/CTA/cards của trang hub; dùng cho Scenes: scene cần tiếp tục và trạng thái có nguồn. | Card doanh thu, chart khách hàng và metric mẫu không thành dữ liệu Real2Sim. |
| `src/app/(main)/dashboard/file-manager/{page.tsx,_components/*}` | Grid/list, toolbar tìm/lọc, file row/card và lựa chọn view cho Scenes cùng bước chọn upload đã có. Có thể dùng `?view=` làm tham khảo view state. | `data.ts` là danh sách mock; Upload/New folder/Share/Star/Trash không tạo workflow upload hay storage thật. Server Real2Sim vẫn nhận diện input theo nội dung. |
| `src/app/(main)/dashboard/tasks/{page.tsx,_components/*}` | Mật độ bảng, tìm/lọc/empty, responsive action cho Jobs; trạng thái chỉ đọc từ job thật. | `data.ts` dùng task synthetic; không mang priority, kéo đổi status, batch task hoặc một trang công việc domain khác. |
| `src/app/(main)/dashboard/infrastructure/{page.tsx,_components/*}` | Cách nhóm trạng thái và drill-down dùng trong Tiến trình của **một job**. | Không tạo trang quản trị server/GPU/deploy/uptime hoặc hứa có metric worker nếu API chưa cung cấp. |
| `src/app/(main)/dashboard/users/{page.tsx,_components/*}` | Bảng thành viên, search, quyền và empty state cho Nhóm. | `data.tsx` là user mock và role/workspace khác Real2Sim; chỉ Editor/Reviewer và API thật. |
| `src/app/(main)/auth/v2/{layout.tsx,login/page.tsx,register/page.tsx}` | Phân cấp form và responsive auth layout cho login/mã mời. | Không dùng Google SSO, self-register, chọn role hay quảng cáo của donor. |
| `src/app/(main)/unauthorized/page.tsx`, dashboard catch-all | Cấu trúc lỗi thiếu quyền/không tìm thấy và đường quay lại. | Message/redirect phải dùng quyền và route thật của Real2Sim. |

Donor là **thư viện pattern trang độc lập**, không có hành trình Real2Sim
“upload video → job → SceneIR → validation/release”. Ví dụ File Manager dùng mảng
`files`/`folders` trong `data.ts`, nút Upload không nối API; Tasks/Users dùng dữ
liệu synthetic. Chỉ ADAPT bố cục/tương tác đã kiểm; luồng và trạng thái nghiệp vụ
lấy từ PRD, contract và API Real2Sim. Nếu sao chép thêm code trong các lát sau,
kiểm exact file/dependency/license rồi cập nhật `frontend/THIRD_PARTY_NOTICES.md`.

## Scope

In scope:

- Sắp xếp phân cấp điều hướng, breadcrumb, CTA theo ngữ cảnh và nhãn màn hiện có.
- Làm rõ ba đường tiếp nhận dữ liệu và các bước form/upload/trạng thái tiếp theo.
- Sắp xếp nội dung của bốn vùng scene; phân biệt SceneObject revision với Gaussian
  export-only, candidate package với release.
- Trạng thái loading/empty/error/locked, quyền Editor/Reviewer, keyboard và màn hẹp.
- Cập nhật tài liệu authority **chỉ sau khi owner chốt** một quyết định thay đổi IA
  hoặc hành vi; không biến plan thành product policy.

Out of scope của đợt UX nền:

- Tạo API, schema, lifecycle state, task ID, role hoặc trang domain mới chỉ để lấp
  sidebar; tự xây dashboard số liệu không có nguồn.
- Nối gizmo, asset Isaac, Gaussian từng vật, physics inspector hoặc USD lai trước
  khi producer/consumer chốt contract v2 và có artifact thích hợp.
- Sửa `src/models/contracts/`, `src/services/`, `src/api/`, runtime GPU, vendor
  SuperSplat, UI legacy hoặc các thay đổi chưa commit trên `feat/pipeline-v2`.
- Claim upload, browser 3DGS, Isaac, review/release E2E từ static/mock proof.

## 1. Bản đồ baseline tại `bdc4b92` — VERIFIED

| Tầng | Surface đang có | Nguồn dữ liệu và giới hạn |
| --- | --- | --- |
| Toàn app | `/` Scenes, `/jobs`, `/team` (Reviewer), CTA `/new`, auth `/login` và `/register` | Sidebar `AppShell`; Jobs dựng từ `listScenes()` và chỉ hiển thị job mới nhất mỗi scene. |
| Tạo/nhập | `/new` gồm upload mới, chọn upload cũ, mẫu; `/imports/[importId]`; `/samples/[sampleId]/scene` | Video tạo reconstruction job; import 3DGS chỉ nén/xem/chỉnh Gaussian; mẫu dùng artifact xử lý sẵn và replay có nhãn. |
| Scene video | `/scenes/[jobId]` có Tiến trình, Studio, Kiểm tra & duyệt, Kết quả | Tab là browser state; progress/preview, SceneIR revision, package/review lấy từ backend. |
| Studio | Xác nhận tỉ lệ, vật thể, SuperSplat Gaussian | SceneObject action publish revision; SuperSplat edit ở phiên editor và chỉ export file. |
| Kết quả | Bản làm việc, candidate package, release | Có UI; Isaac validation/release chỉ được mô tả theo evidence thật, không suy từ card hiện diện. |
| Legacy | `(legacy)` sau cờ `LEGACY_UI=1` | D-10 giữ lại tới khi owner đồng ý bỏ sau parity. |

Các điểm gây rối từ source: sidebar có ba link phẳng, breadcrumb dùng tên chung
`Scene`; `/new` trộn ba loại đầu vào/kết quả; stepper mẫu và job thật dùng từ
“xử lý” gần nhau; tab Studio lại chứa mode metric, SceneObject và Gaussian;
tab khóa dùng `title` làm nơi giải thích chính; trạng thái tab đang xem không nằm
trong URL. Đây là **chẩn đoán từ source**, cần đối chiếu browser trước khi đổi layout.

## 2. Cấu trúc thông tin đề xuất — PROPOSAL

### 2.1 Toàn app

Route Tổng quan/Scenes đã được user chốt trong request tiếp theo. Giữ quyền và
route chi tiết hiện có. Nhóm/nhãn sidebar tham khảo cơ chế `NavGroup` và
active/collapsed item của donor, dùng nav Real2Sim theo bảng dưới.

| Vị trí | Mục hiện có | Hành động |
| --- | --- | --- |
| Ứng dụng | `Tổng quan` (`/`) | Giới thiệu Studio, hành trình, loại đầu vào và tổng hợp theo API hiện có (user chốt 2026-10-01). |
| Công việc | `Scenes` (`/scenes`), `Jobs` | Scenes là thư viện và nơi đặt CTA duy nhất `Scene mới` → `/new`; Jobs hiển thị xử lý theo API hiện có. |
| Quản lý | `Nhóm` | Chỉ Reviewer; account/quota/logout ở footer. |

Không thêm global `Objects`, `Simulation`, `Datasets`, `Releases`: các vùng này
thuộc scene hoặc chưa có nguồn dữ liệu độc lập (PRODUCT.md §3.1/D-07). Nếu owner
muốn `Mẫu`, `File đã tải` hay `Thư viện asset` thành trang riêng, phải chốt **đối
tượng người dùng, route, nguồn dữ liệu, quyền và CTA** trong `PRODUCT.md` trước;
`Thư viện asset` còn phụ thuộc pipeline v2. Đây là decision gate, không phải hạng
mục triển khai mặc định.

### 2.2 Bên trong một scene

Giữ bốn vùng D-07: `Tiến trình` → `Studio` → `Kiểm tra & duyệt` → `Kết quả`.
Header/breadcrumb thể hiện tên scene, job hoặc import, revision (khi có), trạng
thái thật và một CTA theo state/role. Tab khóa phải có lý do đọc được bằng chạm
và keyboard. Jobs đi vào cùng `/scenes/[jobId]`, không tạo màn job detail song song.

**PROPOSAL:** cân nhắc URL view state cho tab/mode để deep link, Back/Forward và
refresh trở lại đúng ngữ cảnh. Đây chỉ là trạng thái xem; job, SceneIR, review và
release vẫn do backend sở hữu. Trước khi làm, kiểm tra routing của editor iframe,
browser history và việc giữ viewer/GPU khi đổi tab.

## 3. Các đường nối và trạng thái — PROPOSAL

| Đường | Entry → chuyển tiếp hiện hành | Điều cần làm rõ trước khi sửa màn |
| --- | --- | --- |
| Khách | Scenes → mẫu → replay có nhãn → scene mẫu | Không gọi replay là job mới, không hiện ETA GPU từ tốc độ phát lại. |
| Editor: video | Scenes/Scene mới → upload hoặc file đã tải → khai báo/cấu hình → `createSceneFromUpload` → `/scenes/[jobId]` | Tách gửi bytes, máy chủ kiểm file, tạo job, chờ worker và đang xử lý. Chỉ chuyển màn sau khi API trả job thật. |
| Editor: 3DGS | Scene mới → PLY/ZIP → `createImport` → `/imports/[importId]` → workspace Gaussian | Ghi giới hạn: chưa metric/collision/validation/release; không hứa video reconstruction. |
| Tiếp tục | Scenes hoặc Jobs → cùng scene → Tiến trình/Studio theo khả năng hiện có | Giữ tên và ngữ cảnh scene, không tự đổi tab đang đọc khi stage tiến lên. |
| Chỉnh vật | SceneIR → chọn/xác nhận/sửa vật → backend trả revision mới | Hiện Đang lưu/Đã lưu/Lưu lỗi; 409 tải revision mới; sau edit, package/report/approval cũ không áp dụng. |
| Kiểm tra | Revision hiện tại → candidate package/preflight → validation khi có runtime → Reviewer → release | Mỗi verdict/download gắn đúng revision, package và evidence; phần chưa có runtime hiển thị điều kiện mở. |

Trước mỗi bước implementation, vẽ và review transition table với các state:
chưa đăng nhập, không có dữ liệu, đang tải, đang kiểm file, đang chờ worker,
đang chạy, chờ người dùng, thất bại, đã có preview, scene revision mới, stale
candidate và thiếu quyền. Không thêm lifecycle state backend từ tên step UI.

## 4. Nội dung từng màn — PROPOSAL

| Surface | Thứ bậc nội dung/hành động | Proof cần có khi triển khai |
| --- | --- | --- |
| Shell | Sidebar nhóm, breadcrumb tên thật, account/role/quota, CTA theo quyền; viewport có thể ưu tiên chiều rộng. | Route active đúng; desktop/hẹp; keyboard, focus và Reviewer/Editor/guest. |
| Scenes | Việc cần tiếp tục và scene thật trước; tìm/lọc/list-grid trên dữ liệu có; mẫu ghi “đã xử lý sẵn”; import mang nhãn giới hạn. | Không trộn sample/import với job thật; filter và back navigation giữ ngữ cảnh hợp lý. |
| Jobs | Job mới nhất/scene theo API hiện có, stage, trạng thái, hành động mở scene; không giả lịch sử mọi attempt. | Status khớp Scenes và header; lỗi/poll/empty rõ; không có action sửa job từ bảng. |
| `/new` | Đầu tiên chọn **Dựng từ video / Mở 3DGS / Thử mẫu**; sau đó chỉ hiện form đúng nhánh. Video: file → quyền/mô tả → preset/thông số nâng cao → summary → tạo job. | Video thật + PLY thật qua UI; lỗi file/attestation/quota giữ dữ liệu nhập; sample không gọi create job. |
| Tiến trình | Stage và hành động cần người dùng trước, chi tiết kỹ thuật mở khi cần; preview có nhãn “bản xem”. | Chờ metric, hủy, retry, stage lỗi và quay lại scene; không biến preview thành DONE. |
| Studio | Toolbar tách mode xem/chọn/đo khỏi lớp Visual/Geometry/Collider; danh sách vật–viewport–inspector; tên mode + revision/save state ở vị trí cố định. Gaussian editor ghi “chỉ export file”; object edit ghi revision backend. | Chọn vật đồng bộ list/viewport/inspector; chuyển mode không mất dữ liệu; real 3DGS/browser proof riêng. |
| Kiểm tra & duyệt | Tóm tắt revision → gói/preflight → validation/evidence → quyết định Reviewer. Có lý do “Chưa khả dụng” ở cổng chưa mở. | Không hiển thị PASS/approval fixture như thật; role, stale revision và rejection reason. |
| Kết quả | Ba loại tách rõ: bản làm việc, candidate, release; thời điểm, revision và quyền tải. | Download đúng artifact; sửa scene không còn trình bày candidate/release cũ là hiện hành. |
| Nhóm/auth | Thành viên/quyền/mã mời theo API hiện có; login trở lại nơi định tới. | Không mở role builder hoặc giả tài khoản; 401/403 và redirect có đường phục hồi. |

### Ánh xạ mẫu trang thành đường đi của Real2Sim

Donor cung cấp **mẫu màn**; đường đi dưới đây là đề xuất ghép bằng route/API hiện có:

```text
Donor shell + Default hub  →  Real2Sim AppShell + Scenes
Donor File Manager         →  Scenes grid/list + chọn file đã upload trong /new
Donor Tasks                →  Jobs (job thật, chỉ đọc) → /scenes/[jobId]
Donor Infrastructure       →  Tiến trình của scene (stage/result/recovery)
Donor Users/Auth v2        →  Nhóm + đăng nhập/mã mời đúng quyền
Real2Sim viewer/editor     →  Studio, review, kết quả (không có donor tương đương)
```

Trước khi dùng pattern, lập wireflow cho từng nhánh guest/video/import và gắn
vào đúng surface ở bảng trên. Đối chiếu ít nhất một screenshot donor với màn
Real2Sim tương ứng về thứ bậc, spacing, chiều rộng, responsive và cách đặt CTA;
kiểm tra lại trên browser, không coi screenshot donor là bằng chứng usability.

## Approach — thứ tự các lát triển khai

| Lát | Phạm vi file dự kiến | Phụ thuộc/điểm dừng | Reviewable outcome |
| --- | --- | --- | --- |
| 0. Chốt IA | Plan này + `PRODUCT.md` **nếu owner chốt thay đổi** | Review bảng ADAPT/REJECT donor, route/role và trang toàn cục; chưa sửa code trước khi chốt phần thay đổi behavior. | Sơ đồ route/role, wireflow ba nhánh, transition table, baseline ảnh desktop/hẹp và bảng đối chiếu donor→Real2Sim. |
| 1. Shell | `features/shell/`, layout và focused tests | Dùng shell đã port từ donor; không cần contract v2; giữ sidebar collapse và auth. | Nhóm nav, breadcrumb/active state, CTA, lý do khi không có quyền. |
| 2. Ba cửa vào | `NewSceneFlow`, `UploadDropzone`, `SampleFlow`, `ImportScenePage` và focused tests | File Manager chỉ là pattern chọn/list, không là upload API; giữ API upload/import/sample và privacy policy. | Mỗi nhánh có tên, step, trạng thái và exit rõ; upload không lẫn sample. |
| 3. Ngữ cảnh scene | `ScenePage`, `scene/state`, `ProgressTab`, `Breadcrumbs` và focused tests | Tham khảo nhóm trạng thái của Infrastructure; giữ poll/preview và viewer lifecycle; chỉ thêm URL view state nếu Back/Forward đúng. | Mở từ Scenes/Jobs về cùng scene, biết revision và việc tiếp theo. |
| 4. Bên trong Studio | `StudioTab`, `ObjectReviewView`, `MetricConfirmView`, `EditorFrame`, viewer và tests | Chỉ chỉnh presentation của action có thật; gizmo/physics/asset v2 đợi contract/artifact. | Rõ hai loại edit, save/error, mode và lớp hiển thị; scene selection không lệch. |
| 5. Kiểm tra/kết quả | `ReviewTab`, `ResultsTab`, panels và tests | Không giả Isaac validation/release; preserve exact-candidate binding. | Các cổng, ba loại download và revision/stale state dễ phân biệt. |
| 6. QA tích hợp | Frontend tests, browser desktop/hẹp, runtime phù hợp | Cần môi trường và artifact thật cho proof tương ứng. | Danh sách lỗi còn lại, kết quả kiểm tra, giới hạn và handoff. |

Mỗi lát bắt đầu bằng `git status`/diff và rebase hoặc tích hợp từ `develop` chỉ
khi worktree sạch, có yêu cầu phù hợp và không đè thay đổi đang làm. Không commit,
push, merge hoặc đổi branch khác nếu chưa được yêu cầu. File plan này cập nhật
progress, quyết định, failed attempts và proof sau từng lát.

## Risks And Recovery

- **Claude đang sửa backend:** làm trong worktree/branch riêng; không sửa
  `src/models/contracts/`, API hoặc plan pipeline v2. Khi tới Studio v2, đọc
  contract được chốt, migration và artifact mới rồi mới thiết kế adapter UI.
- **IA mới vượt `PRODUCT.md` §3.1/D-07:** dừng phần trang mới; owner chốt quyết định
  nhỏ nhất và cập nhật source authority trước khi code. Phần nhóm nhãn/luồng trong
  IA hiện hành có thể làm độc lập.
- **Mất ngữ cảnh viewer khi đổi tab/URL:** giữ cơ chế lazy load + giữ Studio sống;
  kiểm tra GPU cleanup và history. Nếu regression, giữ tab local hiện có và tách
  URL view state thành lát sau.
- **Nhầm bản làm việc với bản phát hành:** giữ provenance/revision/checksum và
  nhãn giới hạn; không đổi golden/test expectation để hợp với wording mới.
- **Plan cũ ghi trạng thái chưa cập nhật:** dùng Git/code/runtime làm evidence
  hiện tại; không tự sửa hoặc đóng plan của workstream khác trong đợt này.

## Progress

- [x] 2026-10-01: đọc harness, workflow, PRD/contract/architecture, PRODUCT.md,
  track và source UI liên quan; xác nhận checkout chính có backend diff chưa commit.
- [x] 2026-10-01: tạo `feat/studio-ux-restructure` từ `develop` `bdc4b92` trong
  worktree riêng; chưa sửa frontend/backend.
- [x] 2026-10-01: ghi kế hoạch, phân biệt VERIFIED/PROPOSAL và các decision gate.
- [x] 2026-10-01: inspect donor `next-shadcn-admin-dashboard` commit `3502692`,
  license, ảnh sáng, nav/shell và các trang Default/File Manager/Tasks/Infrastructure/
  Users/Auth; ghi ánh xạ ADAPT/REJECT và dữ liệu mock vào cùng plan.
- [x] 2026-10-01: user giao triển khai theo plan; kiểm tra lại branch/status và
  authority. Giữ IA `Scenes · Jobs · Nhóm`, không thêm trang toàn cục. Bảng proof
  cần giữ: nav/role; ba nhánh input tách biệt; metric/preview không thành job DONE;
  SceneObject revision; candidate/release exact binding. Browser baseline chờ
  frontend dependencies và API có thể chạy trong worktree.
- [ ] Lát 0: baseline browser desktop/hẹp chưa có; wireflow/source/role đã inspect.
- [x] Lát 1: nhóm sidebar Công việc/Quản lý, active route, breadcrumb tên scene
  API và truncate tên dài; shell giữ collapse, quyền và palette beige/cam.
- [x] Lát 2: ba cửa vào riêng; tách `VideoSetupStep`/`ImportSetupStep`, lọc upload
  đúng loại, giữ attestation và cấu hình video, lỗi giữ dữ liệu, hủy upload khi
  unmount. Mẫu ghi phát lại có sẵn; import có loading/error/recovery và giới hạn.
- [x] Lát 3: header dùng nhãn trạng thái chung, tên/job ID và CTA theo state;
  poll không tự đẩy người đang đọc Tiến trình sang Studio khi preview xuất hiện;
  tab khóa giải thích bằng chạm/keyboard. Route scene key theo job ID để cleanup.
- [x] Lát 4: toolbar riêng cho mode, nhãn SceneObject/revision và Gaussian chỉ
  export file; tên vùng list/inspector và nút chọn vật bằng keyboard. Giữ viewer,
  lớp hiển thị, backend object commands và cơ chế Studio giữ sống khi đổi tab.
- [x] Lát 5: review/release theo role và revision; lỗi đọc có retry; kết quả tách
  bản làm việc/candidate/release. Download chỉ mở sau khi đối chiếu revision;
  chưa biết revision thì đọc SceneIR, không mặc định coi gói là hiện hành.
- [ ] Lát 6: static/component/API smoke đã chạy; browser desktop/hẹp, hành trình
  upload thực qua UI, viewer/GPU và Isaac acceptance còn cần môi trường/artifact.

### Files và boundary đã thay đổi

- `frontend/src/features/shell/{AppShell,Breadcrumbs}.tsx`: nhóm menu, active,
  context tên màn chi tiết; không giữ job/artifact state trong shell.
- `frontend/src/features/studio/{ScenesHome,JobsPage}.tsx`: việc cần tiếp tục,
  tìm/lọc/empty, mẫu xử lý sẵn, lỗi nguồn riêng và ẩn dữ liệu private khi guest.
- `NewSceneFlow`, `VideoSetupStep`, `ImportSetupStep`, `UploadDropzone`,
  `inputKinds`, `SampleFlow`, `SampleScene`, `ImportScenePage`, `SceneWorkspace`:
  source-specific setup/copy/recovery, giữ upload/import/sample API hiện có.
- `ScenePage`, `scene/SceneTabs`, `sceneStatus`, scene route, `ObjectReviewView`:
  ngữ cảnh scene, tab/mode, keyboard selection; không sửa GPU implementation.
- `scene/{ReviewTab,ResultsTab}`, `ReviewPanel`, `SimulationPackagePanel`:
  revision/role/download gates và trình bày báo cáo.
- Tests mới: `studio-navigation`, `studio-input-flows`, `studio-results`;
  bổ sung `review-panel` và `object-review`. Canvas/worker được mock ở test UI.
- Không sửa backend, shared schema, dependency manifest/lock, vendor editor
  hoặc legacy. PRODUCT.md §3.1/S01 được cập nhật theo request tách Tổng quan/Scenes
  của user; không đổi contract, acceptance hoặc task đã khóa. Không commit/push/merge.

### Wireflow và state cần kiểm trong lượt triển khai

| Nhánh | Entry và hành động tiếp theo | Điểm không được nhầm |
| --- | --- | --- |
| Khách | Scenes → Thử mẫu → chọn sample → replay có nhãn → mở scene mẫu | Replay chỉ đọc artifact đã có; không tạo upload/job mới. |
| Video | Scene mới → chọn video mới/đã tải → khai báo + preset → summary → tạo job → Tiến trình → Studio | Upload byte, server verify và tạo job là ba trạng thái khác nhau. |
| 3DGS | Scene mới → PLY/ZIP mới/đã tải → đặt tên → import → chờ SOG → workspace Gaussian | Import chỉ xem/chỉnh và xuất file cục bộ; không có metric/review/release. |

Trong mọi nhánh: guest, loading, empty, lỗi mạng, thiếu quyền, dữ liệu sai loại,
đang gửi, đang chờ worker, lỗi job, chờ xác nhận tỉ lệ, có preview, scene revision
mới và stale candidate phải có lời nhắc/hành động hoặc lý do khóa tại đúng màn.

## Decisions

- 2026-10-01 (task-local): dùng một plan mới cho workstream UX **sau PR #16**, không
  mở lại task `PRODUCT-05` đã ghi DONE, không tạo task ID mới.
- 2026-10-01 (task-local): branch UX tách worktree từ `develop` để giữ nguyên
  thay đổi backend chưa commit. Các trang/sidebar mới ngoài IA hiện hành chỉ là
  phương án chờ owner, không phải quyết định đã chốt.
- 2026-10-01 (implementation): giữ tab/mode ở local view state; chưa làm URL
  view state vì chưa có browser history/viewer lifecycle proof. Không đưa asset,
  gizmo hoặc pipeline v2 API đang phát triển vào UI branch này.
- 2026-10-01 (user visual feedback): bỏ CTA tạo scene trùng ở global header,
  đầu Scenes và empty state của Scenes/Jobs. Giữ một CTA `Scene mới` trong
  sidebar, truy cập qua menu ở màn hẹp; route `/new`, quyền và API không đổi.
  **Được thay thế bởi request kế tiếp:** CTA nằm trong `/scenes`, sidebar không
  còn CTA; `/` trở thành Tổng quan như quyết định sau đây.
- 2026-10-01 (user decision): tách Tổng quan `/` và Scenes `/scenes`; giữ một
  nút `Scene mới` trong Scenes. Cập nhật `PRODUCT.md` §3.1/S01 để lưu quyết định
  này; không đổi task ID, API/schema, acceptance runtime hoặc legacy scaffold.
- 2026-10-01 (contract inspection): preflight FAIL không publish SceneIR mới;
  báo cáo trả `scene_revision` của enrichment tạm, còn `source_scene_revision`
  là scene hiện tại (`simulation_package.py::build_simulation_package`). Panel
  vẫn hiện báo cáo FAIL của source đúng; download chỉ dùng package revision đúng.

## Validation

- **Baseline plan-only:** branch/base SHA và donor provenance đã kiểm trước code;
  không có screenshot baseline. Các kết quả triển khai mới ở bảng dưới.
- **Khi code:** chạy scripts có thật trong `frontend/package.json`: `npm run lint`,
  `npm run typecheck`, `npm test`, `npm run build`; focused tests cho route/nav,
  form/branching, mode/revision và quyền. `build:editor` có mutation nên chỉ chạy
  khi thay editor source và đã inspect target.
- **Browser:** desktop và màn hẹp, keyboard/focus; guest/mẫu, Editor/video thật,
  import PLY/ZIP thật, Jobs→scene, chờ metric/lỗi/retry, object revision/409,
  Reviewer gate và download đúng loại. Ghi browser, dữ liệu/artifact, kết quả,
  giới hạn; mock/fixture không thay real upload/GPU/Isaac proof.

## Result

Đã triển khai phần source của lát 1–5 trong worktree UX riêng. Kết quả là luồng
chọn nguồn rõ hơn, scene có ngữ cảnh và mode riêng, review/download có gate theo
quyền và revision. Không đóng task PRODUCT lịch sử hoặc claim full Product E2E.

### Observed evidence các lát 1–5, trước tách Tổng quan — 2026-10-01

| Command / proof | Kết quả quan sát | Phạm vi |
| --- | --- | --- |
| `npm run lint` | exit 0 | ESLint frontend, không phải browser proof. |
| `npm run typecheck` | exit 0; Next typegen + tsc | TypeScript trên source/tests hiện tại. |
| `npm test` | exit 0; 27 files, 160 tests (10:27 ICT) | Unit/component + mocked API/renderer. Log `device lost` là negative fixture; Three.js warning có sẵn. |
| `REAL2SIM_API_URL=http://127.0.0.1:8010 npm run build` | exit 0 trên lượt cuối sau mọi source edit | Next production build; không chạy `build:editor` vì vendor không đổi. |
| `git diff --check` | exit 0 | Whitespace; tracked diff thuộc frontend, plan là file mới. |
| API riêng `/health`, `/auth/me` | HTTP 200; DB ok, local không auth | Uvicorn cổng 8010, `APP_ENV=test`, SQLite/artifacts/workers dưới `/tmp/p087-ux-validation`; không nối worker/LLM thật. |
| POST `/api/v1/uploads` + GET uploads | MP4 testsrc2 tạo bằng ffmpeg → 201 `rgb_video`; Gaussian PLY fixture 4 điểm → 201 `gaussian_ply`; point-cloud PLY → 422 | Real HTTP upload/detection/storage trên API hiện hành; không phải upload qua browser hay real reconstruction/3DGS render. |
| Next production `/`, `/new`, `/jobs`, `/login`, proxy auth/me và uploads | HTTP 200; proxy uploads trả 2 file QA | Server route/proxy smoke; không chứng minh hydration, responsive hoặc visual QA. `/new` dùng Suspense/useSearchParams nên 3 nhánh có proof component, không kiểm bằng SSR HTML. |
| `cua.getState()` / mở browser `iab` | không có browser kết nối; `Browser is not available: iab` | Browser QA chưa chạy; không có ảnh desktop/hẹp, GPU hoặc Back/Forward proof. |

### Failed attempts và môi trường

- `npm ci --prefer-offline --no-audit --no-fund` và retry
  `--legacy-peer-deps` fail `EUSAGE`: lock thiếu entry `@emnapi/runtime@`.
  Đây là limitation của cài sạch tại checkout hiện hành, chưa sửa lock ngoài UX.
- Install `--no-save --package-lock=false` tải registry quá chậm; đã dừng process
  trước validation cuối. Copy độc lập `node_modules` đã có từ checkout chính,
  dùng `cp -a --reflink=auto` (không symlink/shared write), không đổi manifest/lock.
  Một lượt test bị `Unexpected end of input` do install chưa dừng hoàn toàn;
  đã terminate install, copy lại dependencies đầy đủ và chạy lại full suite xanh.
- Observed versions: Node 24.11.1, npm 11.6.2; Next 16.3.6, React 19.2.8,
  Vitest 3.2.7, TypeScript 5.9.3, jsdom 30.1.1, radix-ui 1.6.7.
  jsdom/transitive engines cảnh báo Node yêu cầu mới hơn; không update Node global.
- Focused tests phát hiện regression ẩn preflight FAIL: đã sửa theo backend
  source/source revision, giữ fixture expectation đúng contract. Hai lỗi test
  mới (radio matcher và release URL) sửa theo control/API thực tế, không đổi API.

### Remaining acceptance và bước tiếp theo

1. Khi browser được kết nối: lấy baseline từ `bdc4b92` trong thư mục tạm, đối chiếu
   màn mới desktop/hẹp và donor; keyboard/focus/sidebar sheet, tên scene dài.
2. Chạy guest/mẫu, Editor/video, import PLY/ZIP qua UI; retry/attestation/quota,
   Jobs→scene, giữ tab khi stage đổi, metric/object/409 và Reviewer gate.
3. Real Brush artifact/viewer GPU cleanup, import SOG conversion và Isaac
   validation/release phải có producer/runtime thật; fixture không đóng các gate.
4. Cài sạch/CI cần xử lý lock inconsistency và Node engine trong workstream phù
   hợp trước handoff tích hợp. UI hiện đã qua checks trên dependencies local.

Preview tại handoff đầu tiên: `http://127.0.0.1:3011/new` (production build), proxy
API QA cổng 8010; đã được thay bằng dev preview/API 8011 trong mục Preview recovery.
Dữ liệu lúc handoff đầu chỉ có video test và Gaussian fixture; không có scene/job
thật, sample library hoặc reconstruction worker. Môi trường local không bật auth;
role gates hiện có proof component, chưa có browser auth proof.

### Task Capsule: Tổng quan và thư viện Scenes — 2026-10-01

- Task / outcome: theo request user, `/` giới thiệu/tổng hợp; `/scenes` quản lý
  scene; nút tạo scene chỉ trong thư viện, không lặp shell/empty state.
- Authority anchors: request user 2026-10-01; PRODUCT.md §3.1/S01; PRD §6;
  ARCHITECTURE frontend ownership; giữ shared revision/role/artifact contracts.
- Dependencies/current state: Next 16.3.6/React 19.2.8; API `listScenes` và
  `listImports` hiện có; QA riêng chưa có scene/worker/sample thật.
- Inputs/outputs: API scene/import summaries → số liệu đọc được, loading/error
  có retry; không tạo metrics/reports giả hay API/state backend mới.
- Owned paths: frontend overview/route/shell/library/backlinks/tests, PRODUCT.md
  phần IA được user đổi và plan này. Không sửa backend/vendor/legacy/locked tasks.
- Proof required: active route/breadcrumb, không fetch private data cho guest,
  số liệu API/partial failure, một CTA đúng vị trí, lint/typecheck/test/build/HTTP.
- Unknowns: browser visual QA và real GPU/Isaac chưa có proof; không chặn việc
  tách route/giới thiệu/dữ liệu đọc từ API hiện có.
- Implementation plan: tạo OverviewPage + `/scenes`, sửa menu/CTA/breadcrumb,
  đường quay lại danh sách, thêm focused tests rồi chạy gates và cập nhật evidence.

### Correction: CTA tạo scene bị lặp — 2026-10-01

- Placement sidebar trong correction này đã được thay bởi request Tổng quan/Scenes:
  CTA hiện nằm ở đầu `/scenes` theo decision phía trên.
- User phản hồi có quá nhiều nút Scene mới. Source xác nhận Scenes rỗng có
  4 entry cùng hành động: sidebar, header, đầu trang và empty state.
- Đã bỏ các bản trùng trong `AppShell`, `ScenesHome`, `JobsPage`; empty state
  dùng lời hướng dẫn tới menu. Không thêm component/dependency hay đổi workflow.
- Validation correction: `npm run lint`, `npm run typecheck`,
  `git diff --check` đều exit 0. GET `/` trên dev preview trả HTTP 200;
  parse SSR HTML xác nhận đúng 1 link `/new`. Source Scenes/Jobs không còn
  link tạo scene trùng; chưa có browser visual QA riêng cho correction này.

### Preview recovery — 2026-10-01

- User báo preview chưa mở được; kiểm tra cổng 3011 không có frontend đáp ứng.
- `next dev` trong sandbox fail `listen EPERM`; đã chạy ngoài sandbox sau approval.
- Preview hiện dùng dev server `http://127.0.0.1:3011/new`,
  `REAL2SIM_API_URL=http://127.0.0.1:8011` và API QA riêng cổng 8011.
  Dữ liệu cô lập dưới `/tmp/p087-ux-preview-20261001`, không dùng backend 8010.
- Đã quan sát HTTP 200 ở `/new`, API `/health` trả DB ok/env test và proxy
  `/api/v1/auth/me` trả local auth disabled. Chưa có dữ liệu scene/mẫu/worker.

### Implementation: Tổng quan `/` và Scenes `/scenes` — 2026-10-01

- `/` render `OverviewPage`: giới thiệu Studio, bốn vùng công việc, ba loại
  đầu vào và đường vào Scenes/Jobs. Tổng hợp đọc `listScenes`/`listImports`,
  loading/error/retry rõ; nguồn chưa tải không bị hiển thị như số 0. Guest không
  fetch nguồn private; summary unmount khi đổi user/đăng xuất.
- `/scenes` render `ScenesHome`: giữ tìm/lọc, mẫu, import và scene video; có
  đúng một nút `Scene mới` ở đầu trang. Shell và empty state không lặp CTA.
- Sidebar có Tổng quan/Scenes/Jobs/Nhóm theo quyền. Active menu, breadcrumb,
  link quay lại từ import/editor/404 đều trỏ đúng thư viện `/scenes`.
- Paths: route `/`, route mới `/scenes`, `OverviewPage`, shell, `ScenesHome`,
  `JobsPage`, `ImportScenePage`, `scene/StudioTab`, `not-found`, hai bộ test
  navigation/overview; PRODUCT.md §3.1/S01 và plan này. Không sửa backend,
  shared contracts, dependency manifest/lock hoặc vendor.
- `npm test -- tests/studio-overview.test.tsx tests/studio-navigation.test.tsx`:
  exit 0, 2 files/10 tests. Proof positive/negative: API totals, guest no private
  fetch, source failure/retry, CTA duy nhất, route active và breadcrumb parent.
- `npm run lint && npm run typecheck`: exit 0. `npm test`: exit 0,
  **28 files/165 tests** (11:12 ICT); mocked/component proof, không phải browser.
- GET `/`, `/scenes`, `/new`, `/jobs` trên dev preview: HTTP 200. Parse HTML:
  `/` có heading giới thiệu, 0 link `/new`; `/scenes` heading Scenes và 1 link
  `/new`. Preview host 3011 được recheck HTTP 200 sau build attempt.
- Build attempts: `REAL2SIM_API_URL=http://127.0.0.1:8011 npm run build` fail
  EPERM khi Turbopack xử lý CSS/mở cổng nội bộ; retry ngoài sandbox cùng lỗi.
  `npm run build -- --webpack` trong sandbox fail đọc output TypeScript
  `--showConfig` dù `tsc --showConfig` trực tiếp exit 0.
- `REAL2SIM_API_URL=http://127.0.0.1:8011 npm run build -- --webpack` ngoài
  sandbox: **exit 0**, compile + TypeScript + prerender 13 trang; route table có
  `/` và `/scenes`. Không đổi build script/config hay tắt check; đây là proof
  production build Webpack, không claim Turbopack build đã qua.
- Chưa có browser visual QA/hydration proof; QA hiện không có scene/mẫu/worker
  thật. `git diff --check` exit 0; branch vẫn `feat/studio-ux-restructure`,
  chưa commit/push. Next step: kiểm desktop/màn hẹp và real flows
  khi có browser/runtime theo Remaining acceptance.

### Preview data recovery: mở được mẫu — 2026-10-01

- User chưa kiểm tra được các màn phía sau. API preview xác nhận `/scenes`
  trả `scenes: []`, `/samples` trả `samples: []`; preview riêng chưa có dữ liệu.
- Kiểm hai bundle có sẵn `aisle-cw`, `aisle-cw-quick` bằng `DemoLibrary` của
  checkout UX: manifest parse đúng schema, 14 file mỗi mẫu qua size/checksum.
  Manifest ghi `origin: pipeline_job`; không chạy reconstruction mới trong lượt này.
- Copy độc lập thư viện mẫu vào `/tmp/p087-ux-preview-20261001/demo` theo
  `PRODUCT_DEMO_DIR` của API QA. Không sửa bundle/schema hoặc dữ liệu checkout chính.
- API `/api/v1/samples` hiện trả 2 mẫu. GET `/samples/aisle-cw/scene` HTTP 200;
  GET file SOG qua Next proxy thành công và checksum khớp manifest. Revalidate
  toàn bộ file của cả hai bản sao cũng qua. Đây là HTTP/artifact proof,
  chưa có browser hydration, renderer/GPU hoặc editor interaction proof.
- Có thể thử `/new?sample=aisle-cw` → replay có nhãn → `/samples/aisle-cw/scene`.
  Mẫu chỉ mở workspace Gaussian; không giả job, metric/object state, validation,
  approval hoặc release để mở bốn tab của scene video.
- Current status filter: `action` chỉ chờ metric confirmation; `running` gồm
  QUEUED/RUNNING; `done` là SUCCEEDED của tái dựng; `failed` là FAILED. Nhóm
  `done` không chứng minh vật thể/gói/Isaac/release hoàn tất; nhóm `action`
  chưa tổng hợp mọi thao tác sau tái dựng. User đã được hỏi lựa chọn ưu tiên
  QA cho toàn bộ UI hoặc pipeline thật; phần này chưa tự mở rộng data harness.

### Preview restart sau user request — 2026-10-01

- Bật lại Next dev cổng 3011; frontend GET `/` HTTP 200. Lần launch API đầu
  bị user interrupt; đã bật lại Uvicorn cổng 8011 từ source worktree UX.
- Thư mục QA tạm trên host không còn; khôi phục đúng các thư mục QA và hai
  bundle mẫu, giữ database/artifact của checkout chính ngoài boundary.
  Copy lần đầu fail do thiếu thư mục cha; mkdir rồi copy lại thành công.
- API `/health` HTTP 200, database ok/env test; proxy `/api/v1/samples` trả
  hai mẫu; file SOG của `aisle-cw` qua proxy HTTP 200. Chưa có browser/GPU proof.

### Task capsule / plan: Inspect theo giai đoạn — 2026-10-01

- Outcome: stage đã xong trên timeline có selection/details/Inspect; route
  chung với tám nội dung, viewport/tool riêng cho 5–8, quay lại đúng Tiến trình.
- Authority: request user; PRODUCT.md §3.1 decision mới; PRD §6; Architecture
  EX-PRODUCT; shared artifact identity/revision; PRODUCT-06/09 và ADR 0005.
- Dependencies: progress, job/project, artifact allow-list, stage-views và
  công cụ viewer/editor/metric/object hiện có. Stage-views không có view cho
  1–2/8; camera chỉ public khi preview có, metric view khi bundle có. Phải
  giải thích thiếu dữ liệu và dùng đúng metadata/SceneIR, không fake artifact.
- Owned paths: frontend routes, inspector components, timeline/progress,
  breadcrumb, source contracts/API consumers nếu cần, focused tests và docs IA.
  Không sửa backend/shared schema/vendor/legacy/Claude checkout hoặc locked tasks.
- Plan: (1) helpers + gate; (2) timeline chọn/detail/link; (3) shared Inspect
  shell + data panels; (4) common scene workspace 5–8 dùng công cụ hiện có;
  (5) context return/breadcrumb; (6) focused + full checks/build/HTTP smoke.
- Proof: success + negative gate/direct link, eight stage mapping, no metric
  label on raw SfM, source errors/retry, backend revision/edit boundaries,
  route and keyboard navigation; mock != browser/GPU acceptance.
- User chốt Inspect 6 chỉ khi xong; đo/xác nhận lúc waiting vẫn ở Studio.
- User làm rõ Inspect là workspace dạng màn xem 3DGS, không phải trang report.
  Viewport lớn + stage tools là chính; metadata/artifact nằm trong panel thu gọn.

### Evidence / recovery: workspace theo giai đoạn — 2026-10-01

- **VERIFIED implementation:** timeline của job thật cho phép chọn bước
  `succeeded`, mở route `/scenes/[jobId]/stages/[stageId]`; mẫu replay không
  tạo link job giả. Direct link kiểm progress trước khi fetch output/mount viewer.
- Shell chung có header/back về `?tab=progress`, navigation 8 bước; panel đầu ra
  thu gọn mặc định. Nội dung 1–2 là metadata/quyền riêng tư từ project, 3 là ảnh
  frame, 4 là quỹ đạo camera top-down hiện có, 5 dùng `EditorFrame` hiện có, 6
  scene hệ mét/so sánh, 7 collision, 8 `ObjectReviewView` hiện có. Bước 8 đọc
  SceneIR hiện tại và thao tác tạo revision mới, không phải snapshot lịch sử.
- StageViewer lọc stage được chọn, giữ danh sách views đầy đủ cho dependency
  camera/collision. Thiếu view thì giải thích; riêng 6 cho phép xem lại Gaussian
  nguồn với cảnh báo và đơn vị SfM khi derivative canonical chưa được publish.
  Không xác nhận lại tỉ lệ đã publish. Key stage/layer giữ lifecycle unmount khi đổi.
- Files của lát mới: `inspection.ts`, `inspection/StageInspectionPage.tsx`,
  `inspection/StageSceneWorkspace.tsx`, stage route, timeline/ProgressTab,
  StageViewer, scene route/initialTab, Breadcrumbs; PRODUCT §3.1 và record này.
  Giữ nguyên backend/shared schema, package/lockfile, vendor và checkout Claude.
- **VERIFIED static:** `npm run lint && npm run typecheck` exit 0.
- **VERIFIED component/unit fixture:** `npm test` exit 0; 31 files / 187 tests.
  22 tests mới trong `studio-inspection.test.tsx`, `stage-workspace.test.tsx`,
  `stage-view-selection.test.tsx`: gate positive/negative, 8 nội dung, retry,
  editor artifact URL/checksum, stage tools/comparison, exact stage selection,
  fallback SfM và ưu tiên derivative hệ mét. Renderer mock; không phải GPU proof.
- **VERIFIED build:** `REAL2SIM_API_URL=http://127.0.0.1:8011 npm run build -- --webpack`
  exit 0; route `/scenes/[jobId]/stages/[stageId]` có trong build output.
- **VERIFIED HTTP:** dev 3011: `/`, `/scenes`, stage hợp lệ HTTP 200 với SSR shell;
  stage ngoài 8 bước HTTP 404. API 8011 `/health` HTTP 200, DB ok, env test;
  progress của job không tồn tại HTTP 404. SSR shell không chứng minh scene render.
- Failed attempts đã sửa: typecheck bắt field privacy không có trong contract
  (`privacy_mode` → dùng `inspection_scope`); test URL editor ban đầu thiếu `/v1`,
  sửa expectation theo endpoint owner thực tế và giữ assertion checksum.
  Warnings Three.js nhiều instance và renderer failure từ negative test vẫn có;
  full suite exit 0.
- **Limits:** CUA inventory không có browser; chưa có visual QA/GPU interaction.
  Preview chưa có job thật đủ 8 bước; mẫu là kết quả đã xử lý tới 3DGS và không
  thay proof upload/worker. API hiện không có report quality riêng cho 1–2,
  camera point-cloud 3D chưa có; bước 4 còn SVG top-down. Canonical viewer chỉ
  sẵn khi backend publish bundle sau geometry. Không claim toàn bộ plan DONE.
- **Next executable step:** với một job thật đã publish stage artifacts, mở
  Tiến trình → chọn từng bước xong → Inspect; kiểm viewport 5–8, đơn vị 6,
  collision toggle 7, chọn/chỉnh object và revision 8; đối chiếu các lớp/API
  backend mới của Claude khi tích hợp. Browser/GPU evidence ghi tại record này.

### Task capsule / plan: landing page Stitch — 2026-10-01

- Outcome: tích hợp giao diện `stitch_real2sim_studio_landing_page (1)/code.html`
  vào Next.js tại `/landing`; các CTA Open Studio dẫn tới app Tổng quan `/`.
- Authority anchors: request user cho phép lấy code; ARCHITECTURE EX-PRODUCT;
  PRD Claims Boundary; PRODUCT §3.1. Đây là scope mới user yêu cầu, thay giới hạn
  proposal cũ không tạo landing marketing trong prototype đầu tiên.
- Dependencies/current state: export có `code.html` và `screen.png`; scene SVG,
  inline CSS, Tailwind CDN và Google Fonts, không có API hoặc real scene runtime.
  Repo đã có Tailwind 4/Next/TypeScript; dùng stack này, không thêm dependency.
- Input/output: adapt markup + CSS sang component TypeScript, CSS được scope
  trong landing, route riêng ngoài AppShell và fonts qua next/font. Open Studio
  cùng origin; các anchor section vẫn điều hướng trong trang.
- Owned paths: `frontend/src/features/landing/`, `frontend/src/app/landing/`,
  PRODUCT và record này. Không đổi route `/`, frontend app flow, backend, shared
  schema, package/lockfile, vendor hoặc checkout Claude.
- Proof required: lint/type/build, HTTP landing/app, CTA đúng `/`, internal
  anchors tồn tại, không tải Tailwind CDN/runtime script hoặc leak CSS vào app.
- Unknowns/limits: không có license riêng trong export user đưa; ghi provenance,
  không suy giấy phép. Các metric/trạng thái mẫu là minh họa, không runtime proof;
  nhãn preview rõ ràng. Browser visual QA hiện không có browser kết nối.
- Implementation plan: port markup/SVG, scope CSS + fonts, nối CTA và nhãn
  minh họa, ghi quyết định route, chạy proof và ghi result trong record này.

### Evidence / recovery: landing page Stitch — 2026-10-01

- **VERIFIED source:** export user cung cấp có `code.html` (1612 lines) và
  `screen.png`; đã đọc markup/assets và xem screenshot. SHA-256 code nguồn:
  `2cef504506e50a99b14e5927526ce328ab66165a7ff8abf62ca471125238bff4`.
  Nguồn không bị xóa/sửa; không có license riêng trong thư mục, không gán MIT.
- **VERIFIED implementation:** adapt HTML/SVG thành TypeScript component
  `frontend/src/features/landing/LandingPage.tsx`, stylesheet scope
  `frontend/src/features/landing/landing.css` và route
  `frontend/src/app/landing/page.tsx`. Tái dùng 14 SVG cùng bố cục/palette;
  Next/font phục vụ Plus Jakarta Sans + IBM Plex Mono từ local font assets.
- CTA header/hero/cuối trang là Next Link tới `/`; các anchor section giữ nguyên.
  GitHub dùng remote repo thực tế. Mock buttons/checkboxes là minh họa disabled;
  placeholder Privacy Policy/Security Whitepaper không giả thành policy pages.
  Header có nhãn preview giải thích scene/metric/validation là ví dụ; không lấy
  `v2.4-prod` hoặc systems-operational của template làm trạng thái app thật.
- Dùng Tailwind hiện có, bỏ browser Tailwind CDN và font CSS bên thứ ba. CSS
  custom, variables và animation names được scope trong landing; không đổi
  stylesheet global/AppShell hoặc route Tổng quan. Header navigation thu gọn
  trên màn nhỏ, reduced-motion tắt animation; overflow clip giữ sticky viewport.
- **VERIFIED static:** `npm run lint && npm run typecheck` exit 0.
- **VERIFIED production:**
  `REAL2SIM_API_URL=http://127.0.0.1:8011 npm run build -- --webpack` exit 0;
  `/landing` là static route. Chạy lại build sau lần chỉnh header/placeholder
  cuối để proof áp dụng đúng code hiện tại.
- **VERIFIED HTTP / SSR:** GET dev `/landing` và `/` HTTP 200. Parse HTML
  xác nhận 3 CTA Open Studio cùng href `/`, mọi fragment target tồn tại, 14 SVG,
  nhãn minh họa, không Tailwind CDN/Google Fonts CSS client. CSS HTTP có selector
  landing và utility hero/palette; font WOFF2 cùng origin HTTP 200. App Tổng quan
  không có markup `.landing-page` và vẫn có nội dung Tổng quan.
- Failed checks: helper kiểm font lúc đầu chỉ tìm URL absolute; CSS thực tế
  dùng `../media/*.woff2`, đã đọc source, resolve URL và tải HTTP 200. Attempt
  cleanup markup tạo patch quá dài bị tool reject, không sửa file; giữ TSX đã
  lint/typecheck. Không đổi backend, schema, dependencies/lockfile hay vendor.
- **Limits:** chưa browser visual QA/mobile screenshot; kiểm HTTP không thay
  kiểm layout bằng browser. Mọi UI scene/metrics trên landing là nội dung mẫu,
  không real pipeline/GPU/Isaac acceptance. Không chạy lại full component suite
  cho trang tĩnh riêng; broad suite gần nhất vẫn là evidence lát Inspect phía trên.
- **Next executable step:** mở `http://127.0.0.1:3011/landing`, kiểm desktop/màn
  nhỏ và click Open Studio; ghi browser evidence nếu browser được kết nối.

### Browser evidence sau khi merge vào `feat/pipeline-v2` — 2026-10-01

Môi trường: frontend bản production (`next start`) trỏ vào một API tạm có `AUTH_REQUIRED=true` trên bản sao DB
runtime; Chrome headless điều khiển qua CDP (click/gõ thật). Không phải deployment cloud.

- **VERIFIED — landing:** `/landing` render ở 1500 px và ~500 px; ba CTA `Open Studio` đều `href="/"`, bấm thì
  vào Tổng quan. Landing không có link đăng nhập/đăng ký và trong app không có link nào trỏ về `/landing`
  (đúng phạm vi PRODUCT §3.1; có nối thêm hay không là quyết định của owner).
- **VERIFIED — auth 19/19 bước:** khách ở `/` và `/scenes` thấy lời mời đăng nhập → `/login?next=/scenes` → sai
  mật khẩu báo lỗi → đúng mật khẩu quay về `/scenes` (13 scene, menu Nhóm) → `/team` tạo link mời → đăng xuất →
  `/register?code=…` (mã điền sẵn, mật khẩu < 10 ký tự bị chặn) → tự đăng nhập về `/` với role Editor →
  `/account` → `/team` báo chỉ Reviewer → đăng xuất. Qua proxy `/api/v1`: cookie `r2s_session` HttpOnly +
  SameSite=lax; khách gọi route cần quyền nhận 401, Editor gọi route Reviewer nhận 403; upload qua route
  handler có chuyển cookie.
- **Lỗi nối backend đã sửa:** `errorMessage` thay mọi `detail` của 401/403/409/429 bằng câu chung, nên sai mật
  khẩu hiện "Phiên đăng nhập đã hết hạn", và lỗi nghiệp vụ 409 của backend (vd "A–B quá ngắn so với C–D…; chọn
  vật dài hơn làm A–B", "Scene này không có số đo LiDAR; nhập khoảng cách đo ngoài đời") hiện thành "Dữ liệu đã
  thay đổi… Tải lại". Nay: `detail` là một câu an toàn (không trace/path/URI/checksum/JSON/HTML, không phải câu
  mặc định của framework) thì hiện ở 403/409/429/4xx khác; 401 và 404 giữ câu phục hồi chung; thao tác tài
  khoản dùng `authErrorMessage` (401 = bị từ chối có lý do). Hai assertion gốc của nhánh UX (`401 "raw"`,
  `409 "raw"`) giữ nguyên và vẫn pass. **PROPOSAL chờ owner xác nhận** vì đây là chỉnh UX policy về lỗi.
- **Limits:** chưa thử trên deployment thật (cookie `Secure` sau HTTPS, Vercel + Railway); chưa bấm thử các
  luồng tạo scene/import/trang giai đoạn với tài khoản thật; nội dung landing vẫn là minh hoạ (một số mục như
  CARLA, ROS2/pcap, "Sub-cm" không phải năng lực đã có của pipeline).

### Publication check — user yêu cầu commit & push, 2026-10-01

- User đã giao commit/push phần UI/UX đang có trên `feat/studio-ux-restructure`.
  Diff gồm frontend source/tests, PRODUCT và plan này; không có backend,
  dependencies/lockfile, vendor, runtime artifacts hoặc env trong phạm vi stage.
- **VERIFIED:** chạy lại `npm run lint && npm run typecheck && npm test`
  exit 0; 31 test files / 187 tests. Production build gần nhất áp dụng đúng
  code landing hiện tại đã exit 0; sau proof chỉ bỏ trailing whitespace trong
  export landing, không đổi behavior.
- `git diff --cached --check` phát hiện trailing whitespace trong file landing
  mới (chưa tracked khi chạy diff trước đó); đã bỏ whitespace trước commit.
  Kiểm ignore của `.env`,
  `frontend/.env`, `frontend/.env.local` thành công. Scan format private key,
  GitHub token, OpenAI project key và AWS access key trong changed files không
  có finding; đây không phải chứng nhận audit bảo mật toàn repo.
- Giữ status plan VALIDATING: commit/push feature work không thay browser/GPU
  acceptance hoặc deploy sản phẩm. Hash commit và remote ref được xác minh qua
  Git sau publication và báo trong handoff.
