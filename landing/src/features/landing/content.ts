/**
 * Toàn bộ chữ của landing nằm ở đây để sửa nội dung không phải đụng vào bố cục.
 * Hỗ trợ song ngữ Tiếng Việt (mặc định) và Tiếng Anh.
 *
 * Mạch trang: Hero → Bài toán (vướng gì, gỡ thế nào) → Scene mẫu → Quy trình → Mỗi vai nhận gì → Tiến độ → Bắt đầu.
 * Mỗi ý chỉ nói một lần: chuỗi xử lý nằm ở WORKFLOW, vai trò ở ROLES, trạng thái ở PROGRESS.
 *
 * Quy tắc: không nhắc tên phần mềm 3D thương mại cụ thể;
 * không đưa số liệu, logo hay claim chưa có bằng chứng (UX spec §8 P8, D-05).
 */

import type { Language } from "@/lib/i18n";

export type Status = "done" | "building" | "later";

export type WorkflowStep = {
  code: string;
  title: string;
  actor: string;
  body: string;
  output: string;
  status: Status;
  image?: string;
};

export const CONTENT_VI = {
  STATUS_LABEL: {
    done: "Đã chạy thật",
    building: "Đang làm",
    later: "Để sau",
  } as Record<Status, string>,

  NAV: [
    { href: "#problem", label: "Bài toán" },
    { href: "#workflow", label: "Quy trình" },
    { href: "#roles", label: "Cho ai" },
    { href: "#progress", label: "Tiến độ" },
    { href: "#start", label: "Bắt đầu" },
  ],

  HERO: {
    eyebrow: "Real2Sim cho robot trong nhà kho",
    titleLead: "Từ video thật",
    titleEmphasis: "đến scene mô phỏng robot dùng được.",
    lead:
      "Quay một đoạn video nhà kho, Real2Sim Studio dựng thành scene 3D đúng kích thước thật. Mỗi pallet, mỗi kệ là một vật riêng, có sẵn vùng va chạm để robot ảo chạy thử trong trình mô phỏng như NVIDIA Isaac Sim.",
    note: "Hiện áp dụng cho nhà kho trong nhà.",
    benefits: [
      "Đúng kích thước thật, tính bằng mét",
      "Mỗi vật là một phần riêng, có vùng va chạm",
      "Có người xác nhận và duyệt trước khi dùng",
    ],
    pillars: ["Hình ảnh", "Hình học", "Va chạm"],
    sceneLabel: "minh hoạ: lối đi trong kho, nhìn từ trên xuống",
  },

  PROBLEM: {
    index: "01 / Bài toán",
    titleLead: "Scene nhìn giống thật,",
    titleEmphasis: "robot vẫn chưa dùng được.",
    lead:
      "Robot cần chạy thử trong bản sao ảo của kho trước khi ra kho thật. Dựng 3D từ video nhanh hơn vẽ tay, nhưng kết quả mới chỉ là một khối hình ảnh liền nhau.",
    analogy: {
      title: "Giống như file PDF scan và file soạn thảo",
      have: {
        label: "Bản dựng 3D từ video",
        like: "giống file PDF scan",
        body: "Nhìn y như thật, nhưng cả cảnh chỉ là một khối. Không chọn hay sửa riêng được từng vật.",
      },
      need: {
        label: "Thứ robot cần",
        like: "giống file soạn thảo",
        body: "Mỗi vật là một phần riêng: biết nó là gì, nằm ở đâu, to bao nhiêu, và đụng vào thì dừng lại.",
      },
    },
    issuesTitle: "Bốn chỗ vướng, và cách Real2Sim gỡ",
    issuesNote: "Bước dựng 3D từ video dùng công cụ có sẵn. Real2Sim làm phần còn thiếu phía sau.",
    issues: [
      {
        title: "Dính liền một khối",
        effect: "Muốn dời một pallet là phải sửa cả cảnh.",
        fix: "Tách thành từng vật: pallet, kệ, thùng. Máy gợi ý, bạn xác nhận.",
        status: "done" as Status,
      },
      {
        title: "Thiếu vùng va chạm",
        effect: "Robot ảo đi xuyên qua kệ như không có gì.",
        fix: "Gắn vùng va chạm (collider) cho từng vật và tách vật khỏi mặt sàn.",
        status: "done" as Status,
      },
      {
        title: "Chưa chắc đúng kích thước",
        effect: "Vừa lối trong máy, kẹt lối ngoài đời.",
        fix: "Căn tỉ lệ bằng một khoảng cách đo thật, rồi kiểm lại bằng một đoạn thứ hai.",
        status: "done" as Status,
      },
      {
        title: "Cũ khi kho đổi bố trí",
        effect: "Phải quay và dựng lại từ đầu.",
        fix: "Sửa ngay trong scene: thêm vật cản, ẩn vật đã dời. Dời và xoay vật đang làm.",
        status: "building" as Status,
      },
    ],
    extra: {
      title: "Rồi kiểm tra trước khi dùng",
      body:
        "Robot ảo chạy thử từ điểm Start tới Goal để biết lối có đi được không (đang làm). Người duyệt xem bằng chứng rồi mới cho cả nhóm dùng.",
    },
  },

  SAMPLES: {
    title: "Xem thử một scene đã xử lý",
    lead: "Mở ngay, không cần đăng nhập, không chạy GPU mới.",
  },

  WORKFLOW: {
    index: "02 / Quy trình",
    titleLead: "Từ một video",
    titleEmphasis: "đến một gói đã được duyệt.",
    lead:
      "Mỗi bước ghi rõ máy tự chạy hay đang chờ bạn. Xem được bản dựng 3D chưa có nghĩa là scene đã dùng được để mô phỏng.",
    steps: [
      {
        code: "01",
        title: "Tải video lên",
        actor: "Người",
        body: "Video MP4 quay bằng camera di chuyển, có thể thêm dữ liệu LiDAR. Hệ thống kiểm tra video, bạn khai báo quyền sử dụng dữ liệu.",
        output: "Công việc xử lý",
        status: "done",
      },
      {
        code: "02",
        title: "Dựng 3D",
        actor: "Máy",
        body: "Tự tách frame, ước lượng vị trí camera (COLMAP), dựng 3D Gaussian Splatting (3DGS) và nén để xem ngay trên trình duyệt.",
        output: "Bản xem 3D",
        status: "done",
      },
      {
        code: "03",
        title: "Căn tỉ lệ mét",
        actor: "Người",
        body: "Chọn một đoạn đã biết khoảng cách, một đoạn khác để kiểm lại, và mặt sàn. Hệ thống điền sẵn số ước lượng để bạn xem lại.",
        output: "Scene đúng kích thước",
        status: "done",
      },
      {
        code: "04",
        title: "Chọn vật thể",
        actor: "Máy + Người",
        body: "Máy (SAM2) gợi ý các vật. Bạn xác nhận, đổi tên, bỏ qua, hoặc thêm vật cản dạng hộp.",
        output: "Phiên bản scene",
        status: "done",
      },
      {
        code: "05",
        title: "Đóng gói",
        actor: "Máy",
        body: "Tách vật khỏi mặt sàn, tạo vùng va chạm, chạy 6 quy tắc kiểm tra rồi xuất gói OpenUSD (scene.usda).",
        output: "Gói mô phỏng",
        status: "done",
      },
      {
        code: "06",
        title: "Chạy thử trong Isaac Sim",
        actor: "Máy",
        body: "Nạp gói vào NVIDIA Isaac Sim, kiểm tra va chạm và đường đi giữa các cặp Start–Goal.",
        output: "Báo cáo kiểm tra",
        status: "building",
      },
      {
        code: "07",
        title: "Duyệt và phát hành",
        actor: "Người",
        body: "Người duyệt xem bằng chứng rồi duyệt hoặc từ chối. Bản đã duyệt được khoá lại, không sửa được nữa.",
        output: "Bản phát hành",
        status: "building",
      },
    ] as WorkflowStep[],
  },

  ROLES: {
    index: "03 / Cho ai",
    titleLead: "Mỗi người",
    titleEmphasis: "nhận được gì.",
    lead: "Ba vai cùng làm việc trên một scene, từ lúc dựng đến lúc duyệt.",
    columns: [
      {
        for: "Kỹ sư mô phỏng",
        title: "Dựng scene ngay trên trình duyệt",
        points: [
          "Tải video lên, hệ thống tự dựng 3D",
          "Căn tỉ lệ mét bằng một khoảng cách đã biết",
          "Xác nhận, đổi tên hoặc bỏ qua vật máy gợi ý",
          "Mỗi lần sửa được lưu thành một phiên bản",
        ],
        outcome: "Ít công cụ hơn · Không dựng lại từ đầu",
      },
      {
        for: "Kỹ sư tích hợp robot",
        title: "Scene có sẵn vùng va chạm",
        points: [
          "Mỗi vật có vùng va chạm riêng, tách khỏi mặt sàn",
          "Bật/tắt từng lớp (hình ảnh, lưới va chạm, hộp vật thể) để soi lỗi",
          "Xuất gói OpenUSD sau khi qua 6 quy tắc kiểm tra",
          "Kiểm tra va chạm và đường đi Start–Goal trong Isaac Sim (đang làm)",
        ],
        outcome: "Đúng mét · Có vùng va chạm",
      },
      {
        for: "Người duyệt (Reviewer)",
        title: "Duyệt dựa trên bằng chứng",
        points: [
          "Xem kết quả tự kiểm của từng bước xử lý",
          "Duyệt hoặc từ chối kèm lý do; sửa sau khi duyệt sẽ tạo phiên bản mới",
          "Bản phát hành được khoá, kèm mã kiểm tra (checksum)",
          "Ghi rõ ai tải dữ liệu, ai chạy, ai duyệt",
        ],
        outcome: "Truy vết được · Đúng bản đã kiểm",
      },
    ],
  },

  PROGRESS: {
    index: "04 / Tiến độ",
    titleLead: "Đã chạy thật.",
    titleEmphasis: "Phần chưa xong cũng nói rõ.",
    lead:
      "Studio đã chạy luồng từ video đến bản dựng 3D trên GPU cục bộ (Quadro T2000). Dưới đây là phần đã xong, phần đang làm và phần để sau.",
    tiers: [
      {
        status: "done" as Status,
        items: [
          "Từ video đến bản dựng 3D trên GPU cục bộ",
          "Căn tỉ lệ mét, gợi ý và xác nhận vật thể",
          "Gói mô phỏng đạt 6/6 quy tắc kiểm tra trên một job thật",
          "Tải về 3DGS (PLY/SOG) hoặc gói OpenUSD; chưa thử với từng phần mềm 3D khác",
        ],
      },
      {
        status: "building" as Status,
        items: [
          "Chạy kiểm tra trong NVIDIA Isaac Sim: va chạm và đường đi Start–Goal",
          "Dời, xoay vật trong scene; màn căn tỉ lệ cho video kết hợp LiDAR",
          "Dựng lại phần nền bị vật che khi gỡ vật, xuất USD kết hợp",
        ],
      },
      {
        status: "later" as Status,
        items: [
          "Luồng chỉ dùng LiDAR",
          "Môi trường khác nhà kho, ví dụ đường bộ với simulator CARLA",
          "Đưa Studio lên cloud",
        ],
      },
    ],
    metricsTitle: "Sẽ đo bằng",
    metrics:
      "Hình ảnh (PSNR, SSIM, LPIPS) · sai lệch tỉ lệ và hình học (Chamfer) · va chạm và đường đi (Collision F1, Path feasibility) · tỉ lệ nạp Isaac thành công và thời gian end-to-end. Ngưỡng nghiệm thu được khoá trước khi xem kết quả cuối.",
  },

  START: {
    titleLead: "Bắt đầu nhỏ.",
    titleEmphasis: "Thử một scene mẫu trước.",
    steps: [
      { title: "Thử scene mẫu", body: "Mở scene đã xử lý sẵn. Không cần đăng nhập." },
      { title: "Đăng nhập và tải video", body: "Tạo scene, theo dõi từng bước và xác nhận ở những điểm quan trọng." },
      { title: "Tải gói mô phỏng", body: "Nhận gói OpenUSD gắn với đúng phiên bản đã duyệt, kèm bảng đánh giá." },
    ],
  },

  FOOTER: {
    tagline: "Biến video môi trường thật thành scene mô phỏng có cấu trúc, có người duyệt.",
    team: "Team P-087 · VinUni AI20K Build Phase, Cohort 4",
    github: "https://github.com/AI20K-Build-Phase-Cohort-4/P-087",
    license: "MIT License",
  },
};

export const CONTENT_EN = {
  STATUS_LABEL: {
    done: "Working",
    building: "In progress",
    later: "Later",
  } as Record<Status, string>,

  NAV: [
    { href: "#problem", label: "Problem" },
    { href: "#workflow", label: "Workflow" },
    { href: "#roles", label: "Roles" },
    { href: "#progress", label: "Progress" },
    { href: "#start", label: "Get started" },
  ],

  HERO: {
    eyebrow: "Real2Sim for warehouse robots",
    titleLead: "From real-world video",
    titleEmphasis: "to simulation scenes robots can use.",
    lead:
      "Film a warehouse and Real2Sim Studio builds a 3D scene at true scale. Every pallet and rack is its own object with a collider, ready for robots to test in simulators like NVIDIA Isaac Sim.",
    note: "Currently focused on indoor warehouses.",
    benefits: [
      "True metric scale",
      "Separate objects, each with a collider",
      "Human-confirmed and reviewed before use",
    ],
    pillars: ["Visual", "Geometry", "Physics"],
    sceneLabel: "illustration: warehouse aisle, top-down view",
  },

  PROBLEM: {
    index: "01 / Problem",
    titleLead: "The scene looks real,",
    titleEmphasis: "but robots still can't use it.",
    lead:
      "Robots need to test in a virtual copy of the warehouse before the real one. Building 3D from video is faster than modeling by hand, but the result is still one fused block of imagery.",
    analogy: {
      title: "Like a scanned PDF versus an editable document",
      have: {
        label: "3D built from video",
        like: "like a scanned PDF",
        body: "Looks exactly like the real thing, but the whole scene is one block. You can't select or edit individual objects.",
      },
      need: {
        label: "What robots need",
        like: "like an editable document",
        body: "Every object is its own part: what it is, where it sits, how big it is, and that it stops you when you hit it.",
      },
    },
    issuesTitle: "Four obstacles, and how Real2Sim clears them",
    issuesNote: "Building 3D from video uses existing tools. Real2Sim covers what is missing after that.",
    issues: [
      {
        title: "One fused block",
        effect: "Moving a single pallet means editing the whole scene.",
        fix: "Split into separate objects: pallets, racks, boxes. The machine suggests, you confirm.",
        status: "done" as Status,
      },
      {
        title: "No collision shapes",
        effect: "Virtual robots drive straight through racks.",
        fix: "Attach a collider to each object and separate objects from the floor.",
        status: "done" as Status,
      },
      {
        title: "Scale not guaranteed",
        effect: "Fits the aisle in simulation, jams in the real one.",
        fix: "Calibrate scale with one measured distance, then check it with a second.",
        status: "done" as Status,
      },
      {
        title: "Outdated when the layout changes",
        effect: "You have to re-record and rebuild from scratch.",
        fix: "Edit in the scene: add obstacles, hide moved items. Moving and rotating objects is in progress.",
        status: "building" as Status,
      },
    ],
    extra: {
      title: "Then check before use",
      body:
        "A virtual robot drives from Start to Goal to confirm the aisle is passable (in progress). A reviewer inspects the evidence before the team uses the scene.",
    },
  },

  SAMPLES: {
    title: "Try a processed scene",
    lead: "Open it right away. No sign-in, no new GPU run.",
  },

  WORKFLOW: {
    index: "02 / Workflow",
    titleLead: "From one video",
    titleEmphasis: "to a reviewed package.",
    lead:
      "Each step shows whether the machine runs on its own or waits for you. Being able to view the 3D result does not mean the scene is ready for simulation.",
    steps: [
      {
        code: "01",
        title: "Upload video",
        actor: "Human",
        body: "An MP4 shot with a moving camera, optionally with LiDAR data. The system checks the video and you declare data usage rights.",
        output: "Processing job",
        status: "done",
      },
      {
        code: "02",
        title: "Build 3D",
        actor: "Machine",
        body: "Extracts frames, estimates camera positions (COLMAP), builds 3D Gaussian Splatting (3DGS) and compresses it for instant viewing in the browser.",
        output: "3D preview",
        status: "done",
      },
      {
        code: "03",
        title: "Set metric scale",
        actor: "Human",
        body: "Pick a segment with a known distance, another to cross-check, and the floor. The system pre-fills estimates for you to review.",
        output: "Scene at true scale",
        status: "done",
      },
      {
        code: "04",
        title: "Pick objects",
        actor: "Machine + Human",
        body: "The machine (SAM2) suggests objects. You confirm, rename, skip, or add box obstacles.",
        output: "Scene revision",
        status: "done",
      },
      {
        code: "05",
        title: "Package",
        actor: "Machine",
        body: "Separates objects from the floor, builds colliders, runs 6 pre-flight rules, then exports an OpenUSD package (scene.usda).",
        output: "Simulation package",
        status: "done",
      },
      {
        code: "06",
        title: "Test in Isaac Sim",
        actor: "Machine",
        body: "Loads the package into NVIDIA Isaac Sim and checks collisions and paths between Start–Goal pairs.",
        output: "Validation report",
        status: "building",
      },
      {
        code: "07",
        title: "Review and release",
        actor: "Human",
        body: "A reviewer inspects the evidence and approves or rejects. An approved release is locked and can no longer be edited.",
        output: "Release",
        status: "building",
      },
    ] as WorkflowStep[],
  },

  ROLES: {
    index: "03 / Roles",
    titleLead: "What each person",
    titleEmphasis: "gets.",
    lead: "Three roles work on one scene, from building it to approving it.",
    columns: [
      {
        for: "Simulation engineer",
        title: "Build scenes in the browser",
        points: [
          "Upload a video and the system builds the 3D",
          "Set metric scale from one known distance",
          "Confirm, rename or skip the objects the machine suggests",
          "Every edit is saved as a revision",
        ],
        outcome: "Fewer tools · No rebuilding from scratch",
      },
      {
        for: "Robot integration engineer",
        title: "Scenes with colliders built in",
        points: [
          "Each object has its own collider, separated from the floor",
          "Toggle layers (visual, collision mesh, object boxes) to spot errors",
          "Export an OpenUSD package after 6 pre-flight rules pass",
          "Collision and Start–Goal path checks in Isaac Sim (in progress)",
        ],
        outcome: "True scale · Colliders included",
      },
      {
        for: "Reviewer",
        title: "Sign off on evidence",
        points: [
          "See the self-check results of each processing step",
          "Approve or reject with a reason; edits after approval create a new revision",
          "Releases are locked and carry a checksum",
          "Records who uploaded, who ran and who approved",
        ],
        outcome: "Traceable · Exactly the verified version",
      },
    ],
  },

  PROGRESS: {
    index: "04 / Progress",
    titleLead: "Already running.",
    titleEmphasis: "What isn't done is stated plainly.",
    lead:
      "Studio already runs video to 3D reconstruction on a local GPU (Quadro T2000). Below: what is done, what is in progress, and what comes later.",
    tiers: [
      {
        status: "done" as Status,
        items: [
          "Video to 3D reconstruction on a local GPU",
          "Metric scale calibration, object suggestion and confirmation",
          "Simulation package passes 6/6 pre-flight rules on a real job",
          "Download 3DGS (PLY/SOG) or an OpenUSD package; not yet tested with other 3D tools",
        ],
      },
      {
        status: "building" as Status,
        items: [
          "Checks in NVIDIA Isaac Sim: collisions and Start–Goal paths",
          "Moving and rotating objects; scale screen for video plus LiDAR",
          "Rebuild the background behind removed objects, hybrid USD export",
        ],
      },
      {
        status: "later" as Status,
        items: [
          "LiDAR-only pipeline",
          "Environments beyond warehouses, e.g. roads with the CARLA simulator",
          "Cloud deployment of Studio",
        ],
      },
    ],
    metricsTitle: "To be measured by",
    metrics:
      "Visual quality (PSNR, SSIM, LPIPS) · scale error and geometry (Chamfer) · collisions and paths (Collision F1, path feasibility) · Isaac import success rate and end-to-end time. Acceptance thresholds are locked before the final results are seen.",
  },

  START: {
    titleLead: "Start small.",
    titleEmphasis: "Try a sample scene first.",
    steps: [
      { title: "Try a sample scene", body: "Open a processed scene. No sign-in needed." },
      { title: "Sign in and upload video", body: "Create a scene, follow each step and confirm at the key points." },
      { title: "Download the package", body: "Get an OpenUSD package tied to the approved revision, with its evaluation sheet." },
    ],
  },

  FOOTER: {
    tagline: "Turn real-world video into structured, reviewed simulation scenes.",
    team: "Team P-087 · VinUni AI20K Build Phase, Cohort 4",
    github: "https://github.com/AI20K-Build-Phase-Cohort-4/P-087",
    license: "MIT License",
  },
};

export const UI_LABELS = {
  vi: {
    tryDemo: "Thử scene mẫu",
    openStudio: "Truy cập Studio",
    loginStudio: "Đăng nhập Studio",
    openSample: "Mở scene mẫu",
    brandAria: "Real2Sim Studio, về đầu trang",
    navAria: "Các phần của trang",
    menuOpen: "Mở menu",
    menuClose: "Đóng menu",
    themeDark: "Chuyển sang giao diện tối",
    themeLight: "Chuyển sang giao diện sáng",
    selectPalette: "Chọn giao diện",
    paletteTitle: "Bảng màu",
    paletteDefault: "Mặc định",
    paletteGruvbox: "Gruvbox",
    paletteDefaultNote: "be + cam",
    paletteGruvboxNote: "vàng kem + cam đất",
    langToEn: "Chuyển sang tiếng Anh (EN)",
    langToVi: "Chuyển sang tiếng Việt (VI)",
    sourceOnGithub: "Mã nguồn trên GitHub",
    consequence: "Hậu quả: ",
    result: "Kết quả",
    step: "Bước",
  },
  en: {
    tryDemo: "Try sample scene",
    openStudio: "Open Studio",
    loginStudio: "Sign in to Studio",
    openSample: "Open sample scene",
    brandAria: "Real2Sim Studio, top of page",
    navAria: "Page navigation",
    menuOpen: "Open menu",
    menuClose: "Close menu",
    themeDark: "Switch to dark theme",
    themeLight: "Switch to light theme",
    selectPalette: "Select palette",
    paletteTitle: "Color palette",
    paletteDefault: "Default",
    paletteGruvbox: "Gruvbox",
    paletteDefaultNote: "beige + ember",
    paletteGruvboxNote: "cream + ochre",
    langToEn: "Switch to English (EN)",
    langToVi: "Switch to Vietnamese (VI)",
    sourceOnGithub: "Source on GitHub",
    consequence: "Consequence: ",
    result: "Output",
    step: "Step",
  },
};

export function getContent(lang: Language = "vi") {
  return lang === "en" ? CONTENT_EN : CONTENT_VI;
}

export function getUiLabels(lang: Language = "vi") {
  return lang === "en" ? UI_LABELS.en : UI_LABELS.vi;
}

// Mặc định tiếng Việt cho các component nhận prop tuỳ chọn (HeroScene, CompareScene, StatusTag).
export const STATUS_LABEL = CONTENT_VI.STATUS_LABEL;
export const HERO = CONTENT_VI.HERO;
export const PROBLEM = CONTENT_VI.PROBLEM;
