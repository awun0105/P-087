/**
 * Toàn bộ chữ của landing nằm ở đây để sửa nội dung không phải đụng vào bố cục.
 *
 * Nguồn: README, BRIEF, PRD và STUDIO_UX_SPEC của repo P-087 (cập nhật 08/10/2026).
 * Quy tắc theo UX spec §8 P8 và D-05: không đưa số liệu, logo hay claim chưa có bằng chứng.
 * Khi một hạng mục đổi trạng thái (ví dụ Isaac Sim chạy thật), chỉ cần đổi `status` ở đây.
 */

export type Status = "done" | "building" | "later";

export const STATUS_LABEL: Record<Status, string> = {
  done: "Đã chạy thật",
  building: "Đang làm",
  later: "Giai đoạn sau",
};

export const NAV = [
  { href: "#problem", label: "Bài toán" },
  { href: "#solution", label: "Giải pháp" },
  { href: "#workflow", label: "Quy trình" },
  { href: "#progress", label: "Tiến độ" },
  { href: "#start", label: "Bắt đầu" },
] as const;

export const HERO = {
  eyebrow: "Real2Sim cho Warehouse / Indoor AMR",
  titleLead: "Từ video nhà kho",
  titleEmphasis: "đến scene robot dùng được.",
  lead:
    "Real2Sim Studio biến video quay kho bằng camera di chuyển thành scene 3D đúng tỉ lệ mét, tách được từng vật thể, có collider và xuất OpenUSD cho NVIDIA Isaac Sim.",
  note: "Máy làm phần lặp lại. Kỹ sư xác nhận ở các bước then chốt, Reviewer duyệt trước khi phát hành.",
  benefits: ["Tỉ lệ theo đơn vị mét", "Vật thể tách riêng, có collider", "Có người duyệt trước khi phát hành"],
  pillars: ["Visual", "Geometry", "Physics"],
};

/** Sơ đồ ở Hero: chuỗi biến đổi dữ liệu (UX spec P8). Là sơ đồ, không phải ảnh chụp kết quả. */
export const HERO_CHAIN = [
  { label: "Video RGB", detail: "MP4, camera di chuyển", tone: "ink" },
  { label: "3DGS", detail: "Bản xem hình ảnh", tone: "geometry" },
  { label: "Hệ mét", detail: "Xác nhận khoảng cách tham chiếu", tone: "geometry" },
  { label: "Vật thể + collider", detail: "Người dùng xác nhận", tone: "ochre" },
  { label: "Gói OpenUSD", detail: "scene.usda + manifest", tone: "sage" },
] as const;

export const PROBLEM = {
  index: "01 / Bài toán",
  titleLead: "Scene nhìn giống thật.",
  titleEmphasis: "Robot vẫn chưa dùng được.",
  lead:
    "Video hay LiDAR của nhà kho chưa thể đưa thẳng vào Isaac Sim. Ba người cùng làm trên một scene, và mỗi người vướng ở một chỗ.",
  personas: [
    {
      role: "Kỹ sư mô phỏng",
      tag: "Người dựng scene",
      highlight: "10 bước thủ công",
      highlightNote: "từ nhận dữ liệu đến scene chạy được, theo quy trình nhóm đã liệt kê",
      pains: [
        "Dựng lại hình học và chỉnh tỉ lệ mét bằng tay",
        "Tách vật thể, tạo vùng va chạm qua nhiều công cụ",
        "Dời một pallet là phải làm lại nhiều bước",
      ],
      handoff: "Giao scene cho kỹ sư AMR",
    },
    {
      role: "Kỹ sư tích hợp AMR",
      tag: "Người chạy robot",
      highlight: "Nhìn đúng ≠ chạy đúng",
      highlightNote: "scene đẹp vẫn có thể sai đơn vị hoặc thiếu vật cản",
      pains: [
        "Robot kẹt hoặc đi xuyên vật vì collider sai",
        "Kích thước chưa theo mét nên đường đi không đáng tin",
        "Khó thử layout mới trước khi đổi kho thật",
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
  rootCauses: [
    { title: "Không có tỉ lệ mét", body: "Video cho thấy môi trường nhưng không cho biết kích thước thật." },
    { title: "Không có cấu trúc vật thể", body: "Bản tái tạo là một khối liền, không tách được pallet hay kệ." },
    { title: "Không có lớp vật lý", body: "Simulator cần collider, không chỉ cần hình đẹp." },
    { title: "Không có truy vết", body: "Không gắn được kết quả kiểm tra với đúng phiên bản scene." },
  ],
  footnote:
    "Nhóm đang đo thời gian của quy trình thủ công trên cùng một scene để làm mốc so sánh. Tỉ lệ cải thiện sẽ chỉ công bố sau khi có số đo.",
};

export const SOLUTION = {
  index: "02 / Giải pháp",
  titleLead: "Một workflow.",
  titleEmphasis: "Ba lớp biểu diễn luôn khớp nhau.",
  lead:
    "Real2Sim Studio gom các bước rời rạc vào một Web App. Scene được giữ dưới dạng có cấu trúc, mỗi thay đổi là một revision mới.",
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
      for: "Cho kỹ sư tích hợp AMR",
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
  /** Đường dẫn ảnh chụp Studio, ví dụ "/landing/step-02.webp". Để trống thì hiện sơ đồ. */
  image?: string;
};

export const WORKFLOW = {
  index: "03 / Quy trình",
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
  index: "04 / Tiến độ",
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
        "Màn xác nhận tỉ lệ cho luồng video + LiDAR",
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

export const ROADMAP = {
  index: "05 / Định hướng",
  titleLead: "Một lõi Real2Sim.",
  titleEmphasis: "Mở rộng theo từng miền.",
  lead:
    "Lõi xử lý được tách khỏi miền ứng dụng và trình mô phỏng. MVP 4 tuần chỉ cam kết một lát cắt: nhà kho trong nhà và Isaac Sim.",
  core: "Universal Real2Sim Core",
  adapters: ["DomainAdapter", "SimulatorAdapter"],
  tracks: [
    {
      tag: "MVP · đang triển khai",
      domain: "Warehouse / Indoor AMR",
      simulator: "NVIDIA Isaac Sim",
      body: "Một lát cắt hoàn chỉnh từ video kho đến gói scene được duyệt.",
      current: true,
    },
    {
      tag: "Sau MVP",
      domain: "Đường bộ",
      simulator: "CARLA và simulator khác",
      body: "Tái sử dụng cùng lõi xử lý, chỉ thay adapter của miền và simulator.",
      current: false,
    },
  ],
};

export const START = {
  index: "Bắt đầu",
  titleLead: "Bắt đầu nhỏ.",
  titleEmphasis: "Thử một scene mẫu trước.",
  steps: [
    { title: "Thử scene mẫu", body: "Xem lại tiến trình đã ghi và mở scene đã xử lý sẵn. Không cần đăng nhập." },
    { title: "Đăng nhập và tải video kho", body: "Tạo scene, theo dõi từng bước và xác nhận ở các điểm then chốt." },
    { title: "Tải gói mô phỏng", body: "Nhận gói OpenUSD gắn đúng revision, kèm bảng đánh giá." },
  ],
};

export const FOOTER = {
  tagline: "Chuyển dữ liệu kho thật thành scene mô phỏng có cấu trúc, có người duyệt.",
  team: "Team P-087 · VinUni AI20K Build Phase, Cohort 4",
  github: "https://github.com/AI20K-Build-Phase-Cohort-4/P-087",
  license: "MIT License",
};
