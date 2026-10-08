/**
 * Toàn bộ chữ của landing nằm ở đây để sửa nội dung không phải đụng vào bố cục.
 *
 * Nguồn: README, BRIEF, PRD và STUDIO_UX_SPEC của repo P-087 (cập nhật 08/10/2026),
 * cùng phần rà soát thị trường ngày 08/10/2026 (NVIDIA NuRec, World Labs Marble,
 * Niantic Scaniverse, Parallax Worlds, bài ϕ-RIE). Trang không nêu tên đối thủ.
 * Quy tắc theo UX spec §8 P8 và D-05: không đưa số liệu, logo hay claim chưa có bằng chứng.
 * Khi một hạng mục đổi trạng thái (ví dụ kiểm tra đường đi chạy thật), chỉ cần đổi `status` ở đây.
 */

export type Status = "done" | "building" | "later";

export const STATUS_LABEL: Record<Status, string> = {
  done: "Đã chạy thật",
  building: "Đang làm",
  later: "Giai đoạn sau",
};

export const NAV = [
  { href: "#context", label: "Bối cảnh" },
  { href: "#problem", label: "Bài toán" },
  { href: "#solution", label: "Giải pháp" },
  { href: "#workflow", label: "Quy trình" },
  { href: "#progress", label: "Tiến độ" },
  { href: "#roadmap", label: "Dùng ở đâu" },
  { href: "#start", label: "Bắt đầu" },
] as const;

export const HERO = {
  eyebrow: "Real2Sim cho robotics và mô phỏng",
  titleLead: "Từ video thật",
  titleEmphasis: "đến scene mô phỏng dùng được.",
  lead:
    "Real2Sim Studio biến video quay môi trường thật bằng camera di chuyển thành scene 3D đúng tỉ lệ mét, tách được từng vật thể và có collider, sẵn sàng đưa vào trình mô phỏng.",
  note: "Lát cắt đầu tiên đang chạy: nhà kho trong nhà và NVIDIA Isaac Sim. Kỹ sư xác nhận ở các bước then chốt, Reviewer duyệt trước khi phát hành.",
  benefits: ["Tỉ lệ theo đơn vị mét", "Vật thể tách riêng, có collider", "Có người duyệt trước khi phát hành"],
  pillars: ["Visual", "Geometry", "Physics"],
  sceneLabel: "ví dụ: lối đi trong kho, nhìn từ trên",
};

/** Sơ đồ ở Hero: chuỗi biến đổi dữ liệu (UX spec P8). Là sơ đồ, không phải ảnh chụp kết quả. */
export const HERO_CHAIN = [
  { label: "Video RGB", detail: "MP4, camera di chuyển", tone: "ink" },
  { label: "3DGS", detail: "Bản xem hình ảnh", tone: "geometry" },
  { label: "Hệ mét", detail: "Xác nhận khoảng cách tham chiếu", tone: "geometry" },
  { label: "Vật thể + collider", detail: "Người dùng xác nhận", tone: "ochre" },
  { label: "Gói OpenUSD", detail: "scene.usda + manifest", tone: "sage" },
] as const;

/** 01 · Bối cảnh: vì sao cần bản sao ảo, và hai cách làm nó. */
export const CONTEXT = {
  index: "01 / Bối cảnh",
  titleLead: "Robot chạy thử trong máy",
  titleEmphasis: "trước khi ra kho thật.",
  lead:
    "Thả robot vào kho thật ngay thì rủi ro: đâm vào hàng, kẹt giữa lối, làm hỏng đồ. Nên các nhóm robotics dựng một bản sao ảo của môi trường và cho robot chạy thử trong đó trước.",
  steps: [
    { title: "Dựng bản sao ảo", body: "Tái hiện kho trên máy tính: kệ, pallet, lối đi, đúng kích thước." },
    { title: "Robot chạy thử", body: "Cho robot ảo chạy hàng nghìn lần trong trình mô phỏng như Isaac Sim." },
    { title: "Ổn mới ra thật", body: "Chỉ triển khai robot vào kho thật khi đã chạy ổn trong máy." },
  ],
  waysTitle: "Có hai cách làm bản sao ảo",
  ways: [
    {
      name: "Dựng tay",
      verdict: "Chính xác, nhưng chậm",
      body: "Kỹ sư đo đạc rồi vẽ lại từng kệ, từng pallet. Mỗi lần kho thay đổi lại phải vẽ lại.",
    },
    {
      name: "Quay video, để máy dựng 3D",
      verdict: "Nhanh, nhưng chưa đủ",
      body: "Nhiều công cụ đã làm được việc này. Bản dựng trông rất giống thật, nhưng robot chưa dùng được ngay. Phần dưới giải thích vì sao.",
    },
  ],
};

export const PROBLEM = {
  index: "02 / Bài toán",
  titleLead: "Scene nhìn giống thật.",
  titleEmphasis: "Robot vẫn chưa dùng được.",
  lead:
    "Dựng 3D từ video và đưa vào simulator giờ đã làm được. Nhưng bản dựng đó là một khối liền, chưa có va chạm cho từng vật và chưa chắc đúng kích thước.",
  analogy: {
    title: "Giống khác biệt giữa bản scan và bản soạn thảo",
    have: {
      label: "Bản 3D từ video",
      like: "giống một file PDF scan",
      body: "Nhìn y như thật, nhưng cả trang chỉ là một tấm ảnh. Không chọn hay sửa riêng được phần nào.",
    },
    need: {
      label: "Thứ robot cần",
      like: "giống một file soạn thảo",
      body: "Từng vật là một phần riêng: biết nó là gì, nằm ở đâu, to bao nhiêu, đụng vào thì dừng lại.",
    },
  },
  issuesTitle: "Bốn chỗ còn vướng",
  issues: [
    {
      title: "Dính liền một khối",
      body: "Không chọn, dời hay xoá riêng được một pallet hay một kệ.",
      effect: "Muốn đổi một vật là phải sửa cả scene.",
    },
    {
      title: "Thiếu va chạm cho từng vật",
      body: "Bản dựng chỉ có hình. Simulator cần collider đúng hình từng vật.",
      effect: "Robot ảo đi xuyên qua kệ như không có gì.",
    },
    {
      title: "Chưa chắc đúng kích thước",
      body: "Tỉ lệ thường phải căn tay, không có đoạn đo để kiểm lại.",
      effect: "Vừa lối trong máy, kẹt lối ngoài đời.",
    },
    {
      title: "Cũ khi kho đổi bố trí",
      body: "Dời vài pallet là bản scan không còn đúng.",
      effect: "Phải quay và dựng lại, hoặc ngồi sửa tay.",
    },
  ],
  consequence:
    "Kết quả: kỹ sư vẫn phải sửa tay rất nhiều mới dùng được, và sửa lại mỗi lần môi trường thay đổi.",
  personasTitle: "Ai đang chịu nỗi đau này",
  personas: [
    {
      role: "Kỹ sư mô phỏng",
      tag: "Người dựng scene",
      highlight: "10 bước thủ công",
      highlightNote: "từ nhận dữ liệu đến scene chạy được, theo quy trình nhóm đã liệt kê",
      pains: [
        "Dựng lại hình học và chỉnh tỉ lệ mét bằng tay",
        "Tách vật thể, tạo vùng va chạm qua nhiều công cụ",
        "Môi trường đổi một chút là phải làm lại nhiều bước",
      ],
      handoff: "Giao scene cho kỹ sư robot",
    },
    {
      role: "Kỹ sư tích hợp robot",
      tag: "Người chạy robot",
      highlight: "Nhìn đúng ≠ chạy đúng",
      highlightNote: "scene đẹp vẫn có thể sai đơn vị hoặc thiếu vật cản",
      pains: [
        "Robot kẹt hoặc đi xuyên vật vì collider sai",
        "Kích thước chưa theo mét nên đường đi không đáng tin",
        "Khó thử bố trí mới trước khi thay đổi ngoài thực tế",
      ],
      handoff: "Gửi scene cho Reviewer",
    },
    {
      role: "Reviewer / Tech Lead",
      tag: "Người duyệt",
      highlight: "Không có một nơi",
      highlightNote: "để đối chiếu chất lượng tái tạo, hình học và kết quả mô phỏng",
      pains: [
        "Không rõ scene nào đã thực sự được kiểm tra",
        "Nguồn dữ liệu và lịch sử chỉnh sửa nằm rời rạc",
        "Khó truy lại đúng bản đã được duyệt",
      ],
      handoff: "Phát hành cho cả nhóm",
    },
  ],
  footnote:
    "Nhóm đang đo thời gian của quy trình thủ công trên cùng một scene để làm mốc so sánh. Tỉ lệ cải thiện sẽ chỉ công bố sau khi có số đo.",
};

export const SOLUTION = {
  index: "03 / Giải pháp",
  titleLead: "Từ bản scan",
  titleEmphasis: "thành bản soạn thảo của nhà kho.",
  lead:
    "Dựng 3D từ video thì nhiều công cụ đã làm được. Real2Sim tập trung vào phần sau đó: tách scene thành từng vật, gắn collider, đúng tỉ lệ mét, rồi kiểm tra và duyệt trước khi dùng.",
  mapTitle: "Mỗi chỗ vướng, một cách gỡ",
  map: [
    {
      problem: "Dính liền một khối",
      answer: "Tách thành từng vật riêng: pallet, kệ, thùng. Máy đề xuất, người xác nhận.",
      status: "done" as Status,
    },
    {
      problem: "Thiếu va chạm cho từng vật",
      answer: "Gắn collider cho từng vật và tách vật khỏi mặt sàn.",
      status: "done" as Status,
    },
    {
      problem: "Chưa chắc đúng kích thước",
      answer: "Căn tỉ lệ bằng một khoảng cách đo thật, có đoạn đo thứ hai để kiểm lại.",
      status: "done" as Status,
    },
    {
      problem: "Cũ khi kho đổi bố trí",
      answer: "Sửa ngay trong scene: đã thêm được vật cản và ẩn vật; dời, xoay vật đang làm.",
      status: "building" as Status,
    },
  ],
  extra: {
    title: "Rồi kiểm tra trước khi dùng",
    body: "Cho robot ảo chạy thử từ điểm Start tới Goal để biết lối có đi được không (đang làm). Reviewer xem bằng chứng rồi mới duyệt cho cả nhóm dùng.",
  },
  contribution: {
    title: "Đóng góp của Real2Sim",
    notTitle: "Không làm lại",
    not: "Phần dựng 3D từ video. Nhóm dùng công cụ có sẵn cho bước này.",
    isTitle: "Nối phần còn thiếu",
    is: "Biến bản dựng thành scene tách được từng vật, có vật cản, đúng kích thước, chỉnh được và được kiểm tra, trong một trang web có người xác nhận ở các bước quan trọng.",
  },
  columnsTitle: "Mỗi người nhận được gì",
  columns: [
    {
      for: "Cho kỹ sư mô phỏng",
      title: "Dựng scene trên trình duyệt",
      points: [
        "Tải video lên, hệ thống tự tách frame, ước lượng camera và dựng 3DGS",
        "Xác nhận tỉ lệ mét bằng một khoảng cách tham chiếu đã biết",
        "Hệ thống đề xuất vật thể; bạn xác nhận, đổi tên, bỏ qua hoặc thêm vật cản",
        "Mỗi thao tác được lưu thành một revision",
      ],
      outcome: "Ít công cụ hơn · Không dựng lại từ đầu",
    },
    {
      for: "Cho kỹ sư tích hợp robot",
      title: "Scene có vật lý tối thiểu",
      points: [
        "Vật được tách khỏi mặt sàn và có collider riêng",
        "Bật/tắt lớp 3DGS, lưới va chạm, hộp vật thể để soi lỗi",
        "Xuất gói OpenUSD kèm 6 luật kiểm tra trước khi đóng gói",
        "Kiểm tra va chạm và đường đi Start–Goal trong Isaac Sim (đang làm)",
      ],
      outcome: "Đúng mét · Có collider",
    },
    {
      for: "Cho Reviewer",
      title: "Duyệt dựa trên bằng chứng",
      points: [
        "Bảng đánh giá tự kiểm theo từng bước xử lý",
        "Duyệt hoặc từ chối kèm lý do; sửa sau khi duyệt sẽ tạo revision mới",
        "Bản phát hành được niêm phong bằng manifest và checksum",
        "Ghi rõ ai tải dữ liệu, ai chạy, ai duyệt",
      ],
      outcome: "Truy vết được · Đúng bản đã kiểm",
    },
  ],
  layers: [
    { code: "Visual", question: "Scene trông thế nào?", answer: "3D Gaussian Splatting, xem và điều hướng ngay trên trình duyệt.", tone: "geometry" },
    { code: "Geometry", question: "Bề mặt nằm ở đâu?", answer: "Mesh và point cloud theo đơn vị mét; LiDAR đã đăng ký là nguồn tuỳ chọn.", tone: "ink" },
    { code: "Physics", question: "Simulator va chạm với gì?", answer: "Collider cho từng vật, cùng transform với hai lớp còn lại.", tone: "ochre" },
  ],
  layersNote: "Di chuyển một vật thì cả ba lớp dùng chung một transform.",
  checkpoints: ["Xác nhận tỉ lệ mét", "Xác nhận vật thể", "Reviewer duyệt"],
};

export type WorkflowStep = {
  code: string;
  title: string;
  actor: "Máy" | "Người" | "Máy + Người";
  body: string;
  output: string;
  status: Status;
  /** Đường dẫn ảnh chụp Studio, ví dụ "/landing/step-02.webp". Để trống thì chỉ hiện chữ. */
  image?: string;
};

export const WORKFLOW = {
  index: "04 / Quy trình",
  titleLead: "Từ một video",
  titleEmphasis: "đến một gói đã được duyệt.",
  lead:
    "Mỗi bước cho biết máy đang chạy hay đang chờ bạn. Có bản xem 3DGS chưa có nghĩa là scene đã sẵn sàng mô phỏng.",
  steps: [
    {
      code: "01",
      title: "Nạp dữ liệu",
      actor: "Người",
      body: "Video MP4 quay bằng camera di chuyển; LiDAR đã đăng ký là tuỳ chọn. Hệ thống kiểm tra video, bạn khai báo quyền sử dụng dữ liệu.",
      output: "Job xử lý",
      status: "done",
    },
    {
      code: "02",
      title: "Tái tạo 3D",
      actor: "Máy",
      body: "Tách frame, COLMAP ước lượng vị trí camera, Brush dựng 3DGS, nén SOG để xem trên trình duyệt.",
      output: "Bản xem 3DGS",
      status: "done",
    },
    {
      code: "03",
      title: "Tỉ lệ mét",
      actor: "Người",
      body: "Chọn một đoạn đã biết khoảng cách, một đoạn kiểm độc lập và mặt sàn. Hệ thống có thể điền sẵn số ước lượng để bạn xem lại.",
      output: "Scene hệ mét",
      status: "done",
    },
    {
      code: "04",
      title: "Vật thể",
      actor: "Máy + Người",
      body: "SAM2 đề xuất vật thể ứng viên. Bạn xác nhận, đổi tên, bỏ qua hoặc thêm vật cản dạng hộp.",
      output: "Revision scene",
      status: "done",
    },
    {
      code: "05",
      title: "Gói mô phỏng",
      actor: "Máy",
      body: "Tách vật khỏi mặt sàn, tạo collider, chạy 6 luật kiểm tra trước rồi đóng gói scene.usda.",
      output: "Gói ứng viên",
      status: "done",
    },
    {
      code: "06",
      title: "Kiểm tra Isaac Sim",
      actor: "Máy",
      body: "Nạp gói vào NVIDIA Isaac Sim, kiểm tra va chạm và đường đi giữa các cặp Start–Goal.",
      output: "Báo cáo validation",
      status: "building",
    },
    {
      code: "07",
      title: "Duyệt & phát hành",
      actor: "Người",
      body: "Reviewer đối chiếu bằng chứng rồi duyệt hoặc từ chối. Bản được duyệt được niêm phong để không thể sửa.",
      output: "Bản phát hành",
      status: "building",
    },
  ] as WorkflowStep[],
};

export const PROGRESS = {
  index: "05 / Tiến độ",
  titleLead: "Đã chạy thật.",
  titleEmphasis: "Và nói rõ phần chưa xong.",
  lead:
    "Studio MVP đã chạy luồng video → 3DGS trên GPU cục bộ (Quadro T2000). Bảng dưới tách rõ việc đã chứng minh, việc đang làm và việc để giai đoạn sau.",
  tiers: [
    {
      status: "done" as Status,
      title: "Luồng dựng scene",
      items: [
        "Video → 3DGS chạy thật trên GPU cục bộ",
        "Xác nhận tỉ lệ mét, đề xuất và xác nhận vật thể",
        "Gói mô phỏng đạt 6/6 luật kiểm tra trước trên một job thật",
      ],
    },
    {
      status: "building" as Status,
      title: "Kiểm chứng mô phỏng",
      items: [
        "Chạy kiểm tra trong NVIDIA Isaac Sim, va chạm và đường đi Start–Goal",
        "Dời, xoay vật trong scene; màn xác nhận tỉ lệ cho luồng video + LiDAR",
        "Pipeline v2: scene theo vật, nền vá sẵn, xuất USD lai",
      ],
    },
    {
      status: "later" as Status,
      title: "Mở rộng",
      items: [
        "Luồng chỉ dùng LiDAR",
        "Miền và simulator khác, ví dụ đường bộ với CARLA",
        "Triển khai Studio lên cloud",
      ],
    },
  ],
  metricsTitle: "Nhóm cam kết đo",
  metrics: [
    { group: "Hình ảnh", items: "PSNR · SSIM · LPIPS" },
    { group: "Tỉ lệ & hình học", items: "Sai lệch tỉ lệ · Chamfer với hình học tham chiếu độc lập" },
    { group: "Va chạm & đường đi", items: "Collision F1 · Path feasibility" },
    { group: "Hệ thống", items: "Tỉ lệ nạp Isaac thành công · Thời gian end-to-end" },
  ],
  metricsNote: "Ngưỡng nghiệm thu được khoá trước khi xem kết quả cuối.",
  samplesTitle: "Scene mẫu đã xử lý sẵn",
  samplesLead: "Mở xem ngay, không cần đăng nhập và không chạy GPU mới.",
};

export type TrackState = "current" | "partial" | "later";

export const ROADMAP = {
  index: "06 / Dùng ở đâu",
  titleLead: "Một lõi Real2Sim.",
  titleEmphasis: "Nhiều nơi dùng scene.",
  lead:
    "Lõi xử lý được tách khỏi miền ứng dụng và trình mô phỏng. MVP 4 tuần chỉ cam kết một lát cắt; các hướng còn lại dùng chung lõi đó.",
  core: "Universal Real2Sim Core",
  adapters: ["DomainAdapter", "SimulatorAdapter"],
  tracks: [
    {
      state: "current" as TrackState,
      tag: "MVP · đang triển khai",
      domain: "Robot trong nhà kho",
      simulator: "NVIDIA Isaac Sim",
      body: "Lát cắt hoàn chỉnh từ video kho đến gói scene được duyệt.",
    },
    {
      state: "partial" as TrackState,
      tag: "Đã có một phần",
      domain: "Công cụ 3D khác",
      simulator: "3DGS (PLY / SOG) · OpenUSD",
      body: "Tải file 3DGS hoặc gói OpenUSD để mở ở công cụ khác. Nhóm chưa kiểm thử với từng phần mềm cụ thể.",
    },
    {
      state: "later" as TrackState,
      tag: "Sau MVP",
      domain: "Đường bộ",
      simulator: "CARLA và simulator khác",
      body: "Tái sử dụng cùng lõi xử lý, chỉ thay adapter của miền và simulator.",
    },
  ],
};

export const START = {
  titleLead: "Bắt đầu nhỏ.",
  titleEmphasis: "Thử một scene mẫu trước.",
  steps: [
    { title: "Thử scene mẫu", body: "Xem lại tiến trình đã ghi và mở scene đã xử lý sẵn. Không cần đăng nhập." },
    { title: "Đăng nhập và tải video", body: "Tạo scene, theo dõi từng bước và xác nhận ở các điểm then chốt." },
    { title: "Tải gói mô phỏng", body: "Nhận gói OpenUSD gắn đúng revision, kèm bảng đánh giá." },
  ],
};

export const FOOTER = {
  tagline: "Chuyển dữ liệu từ môi trường thật thành scene mô phỏng có cấu trúc, có người duyệt.",
  team: "Team P-087 · VinUni AI20K Build Phase, Cohort 4",
  github: "https://github.com/AI20K-Build-Phase-Cohort-4/P-087",
  license: "MIT License",
};
