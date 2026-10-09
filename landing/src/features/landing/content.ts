/**
 * Toàn bộ chữ của landing nằm ở đây để sửa nội dung không phải đụng vào bố cục.
 * Hỗ trợ song ngữ Tiếng Việt (mặc định) và Tiếng Anh.
 *
 * Nguồn: README, BRIEF, PRD và STUDIO_UX_SPEC của repo P-087 (cập nhật 08/10/2026),
 * cùng phần rà soát thị trường ngày 08/10/2026. Trang không nêu tên đối thủ.
 * Quy tắc: Không nhắc tên phần mềm 3D thương mại cụ thể;
 * không đưa số liệu, logo hay claim chưa có bằng chứng (UX spec §8 P8, D-05).
 */

import type { Language } from "@/lib/i18n";

export type Status = "done" | "building" | "later";
export type TrackState = "current" | "partial" | "later";

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
    later: "Giai đoạn sau",
  } as Record<Status, string>,

  NAV: [
    { href: "#context", label: "Bối cảnh" },
    { href: "#problem", label: "Bài toán" },
    { href: "#solution", label: "Giải pháp" },
    { href: "#workflow", label: "Quy trình" },
    { href: "#progress", label: "Tiến độ" },
    { href: "#roadmap", label: "Dùng ở đâu" },
    { href: "#start", label: "Bắt đầu" },
  ],

  HERO: {
    eyebrow: "Real2Sim cho robotics và mô phỏng",
    titleLead: "Từ video thật",
    titleEmphasis: "đến scene mô phỏng dùng được.",
    lead:
      "Real2Sim Studio biến video quay môi trường thật bằng camera di chuyển thành scene 3D đúng tỉ lệ mét, tách được từng vật thể và có collider, sẵn sàng đưa vào trình mô phỏng.",
    note:
      "Lát cắt đầu tiên đang chạy: nhà kho trong nhà và NVIDIA Isaac Sim. Kỹ sư xác nhận ở các bước then chốt, Reviewer duyệt trước khi phát hành.",
    benefits: [
      "Tỉ lệ theo đơn vị mét",
      "Vật thể tách riêng, có collider",
      "Có người duyệt trước khi phát hành",
    ],
    pillars: ["Visual", "Geometry", "Physics"],
    sceneLabel: "ví dụ: lối đi trong kho, nhìn từ trên",
  },

  HERO_CHAIN: [
    { label: "Video RGB", detail: "MP4, camera di chuyển", tone: "ink" },
    { label: "3DGS", detail: "Bản xem hình ảnh", tone: "geometry" },
    { label: "Hệ mét", detail: "Xác nhận khoảng cách tham chiếu", tone: "geometry" },
    { label: "Vật thể + collider", detail: "Người dùng xác nhận", tone: "ochre" },
    { label: "Gói OpenUSD", detail: "scene.usda + manifest", tone: "sage" },
  ] as const,

  CONTEXT: {
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
        body:
          "Nhiều công cụ đã làm được việc này. Bản dựng trông rất giống thật, nhưng robot chưa dùng được ngay. Phần dưới giải thích vì sao.",
      },
    ],
  },

  PROBLEM: {
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
  },

  SOLUTION: {
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
      body:
        "Cho robot ảo chạy thử từ điểm Start tới Goal để biết lối có đi được không (đang làm). Reviewer xem bằng chứng rồi mới duyệt cho cả nhóm dùng.",
    },
    contribution: {
      title: "Đóng góp của Real2Sim",
      notTitle: "Không làm lại",
      not: "Phần dựng 3D từ video. Nhóm dùng công cụ có sẵn cho bước này.",
      isTitle: "Nối phần còn thiếu",
      is:
        "Biến bản dựng thành scene tách được từng vật, có vật cản, đúng kích thước, chỉnh được và được kiểm tra, trong một trang web có người xác nhận ở các bước quan trọng.",
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
  },

  WORKFLOW: {
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
  },

  PROGRESS: {
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
  },

  ROADMAP: {
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
  },

  START: {
    titleLead: "Bắt đầu nhỏ.",
    titleEmphasis: "Thử một scene mẫu trước.",
    steps: [
      { title: "Thử scene mẫu", body: "Xem lại tiến trình đã ghi và mở scene đã xử lý sẵn. Không cần đăng nhập." },
      { title: "Đăng nhập và tải video", body: "Tạo scene, theo dõi từng bước và xác nhận ở các điểm then chốt." },
      { title: "Tải gói mô phỏng", body: "Nhận gói OpenUSD gắn đúng revision, kèm bảng đánh giá." },
    ],
  },

  FOOTER: {
    tagline: "Chuyển dữ liệu từ môi trường thật thành scene mô phỏng có cấu trúc, có người duyệt.",
    team: "Team P-087 · VinUni AI20K Build Phase, Cohort 4",
    github: "https://github.com/AI20K-Build-Phase-Cohort-4/P-087",
    license: "MIT License",
  },
};

export const CONTENT_EN = {
  STATUS_LABEL: {
    done: "Verified",
    building: "In progress",
    later: "Future phase",
  } as Record<Status, string>,

  NAV: [
    { href: "#context", label: "Context" },
    { href: "#problem", label: "Problem" },
    { href: "#solution", label: "Solution" },
    { href: "#workflow", label: "Workflow" },
    { href: "#progress", label: "Progress" },
    { href: "#roadmap", label: "Use Cases" },
    { href: "#start", label: "Get Started" },
  ],

  HERO: {
    eyebrow: "Real2Sim for robotics and simulation",
    titleLead: "From real-world video",
    titleEmphasis: "to actionable simulation scenes.",
    lead:
      "Real2Sim Studio turns moving-camera video of physical environments into structured 3D scenes with metric scale, segmented objects, and colliders, ready for simulation runtimes.",
    note:
      "First operational slice: indoor warehouses and NVIDIA Isaac Sim. Engineers verify critical checkpoints, and Reviewers sign off before release.",
    benefits: [
      "Metric scale calibration",
      "Isolated objects with colliders",
      "Audited gate before release",
    ],
    pillars: ["Visual", "Geometry", "Physics"],
    sceneLabel: "example: warehouse aisle, top-down view",
  },

  HERO_CHAIN: [
    { label: "RGB Video", detail: "MP4, moving camera", tone: "ink" },
    { label: "3DGS", detail: "Visual preview", tone: "geometry" },
    { label: "Metric scale", detail: "Ground-truth distance confirm", tone: "geometry" },
    { label: "Objects + collider", detail: "Human verification", tone: "ochre" },
    { label: "OpenUSD package", detail: "scene.usda + manifest", tone: "sage" },
  ] as const,

  CONTEXT: {
    index: "01 / Context",
    titleLead: "Test robots in simulation",
    titleEmphasis: "before live warehouse deployment.",
    lead:
      "Deploying robots directly into physical facilities carries risks: equipment collisions, aisle bottlenecks, and damaged goods. Robotics teams construct virtual replicas to validate autonomous navigation first.",
    steps: [
      { title: "Build digital replica", body: "Reconstruct the environment on computer: racks, pallets, aisles at true scale." },
      { title: "Simulate test runs", body: "Run simulated robots across thousands of cycles in runtimes like Isaac Sim." },
      { title: "Deploy with confidence", body: "Deploy autonomous systems to live sites only after passing virtual verification." },
    ],
    waysTitle: "Two ways to construct digital replicas",
    ways: [
      {
        name: "Manual CAD modeling",
        verdict: "Accurate, but slow",
        body: "Engineers measure and model every rack and pallet by hand. Any site rearrangement requires manual rework.",
      },
      {
        name: "Video capture to 3D",
        verdict: "Fast, but incomplete",
        body:
          "Modern engines reconstruct photorealistic 3D from video, but raw scans cannot be run directly by robots. Here is why.",
      },
    ],
  },

  PROBLEM: {
    index: "02 / Problem",
    titleLead: "Scenes look photorealistic.",
    titleEmphasis: "Robots still cannot use them.",
    lead:
      "Reconstructing 3D from video and loading into simulators is possible today. But raw reconstructions remain a monolithic blob lacking object colliders and metric verification.",
    analogy: {
      title: "Like the difference between a scanned PDF and an editable document",
      have: {
        label: "Raw 3D from video",
        like: "like a scanned PDF",
        body: "Looks identical to reality, but the whole scene is a single baked image. Nothing can be individually selected or edited.",
      },
      need: {
        label: "What robots require",
        like: "like an editable document",
        body: "Every object is an independent entity: known identity, exact position, bounding dimensions, and solid physics boundaries.",
      },
    },
    issuesTitle: "Four unresolved hurdles",
    issues: [
      {
        title: "Monolithic geometry",
        body: "Cannot select, move, or delete a single pallet or rack individually.",
        effect: "Modifying one object requires regenerating the entire scene.",
      },
      {
        title: "Missing object colliders",
        body: "Scans only provide visual appearance. Simulators require explicit rigid-body colliders.",
        effect: "Virtual robots drive straight through solid racks.",
      },
      {
        title: "Unverified metric dimensions",
        body: "Scale is estimated visually with no ground-truth distance reference.",
        effect: "Fits the virtual aisle, jams in the physical warehouse.",
      },
      {
        title: "Outdated on layout changes",
        body: "Relocating two pallets invalidates the entire reconstructed scan.",
        effect: "Requires re-recording and manual reconstruction from scratch.",
      },
    ],
    consequence:
      "Result: engineers spend substantial manual labor to make scenes usable, repeating the cycle on every environment change.",
    personasTitle: "Who carries this burden",
    personas: [
      {
        role: "Simulation Engineer",
        tag: "Scene Builder",
        highlight: "10 manual steps",
        highlightNote: "from raw intake to runnable simulation scene, mapped by our baseline audit",
        pains: [
          "Manual geometric retopology and metric scaling by hand",
          "Segmenting objects and generating collision meshes across disparate tools",
          "Minor site adjustments force repeating multiple tedious steps",
        ],
        handoff: "Handoff scene to Robot Engineer",
      },
      {
        role: "Robot Integration Engineer",
        tag: "Robot Operator",
        highlight: "Looks right ≠ runs right",
        highlightNote: "visual beauty does not prevent scale errors or missing collision hulls",
        pains: [
          "Robots collide or phase through geometry due to invalid colliders",
          "Unverified dimensions make simulated trajectories untrustworthy",
          "Hard to validate new layouts before physical warehouse changes",
        ],
        handoff: "Submit scene to Reviewer",
      },
      {
        role: "Reviewer / Tech Lead",
        tag: "Gatekeeper",
        highlight: "No single surface",
        highlightNote: "to cross-examine reconstruction visual fidelity, geometry, and sim results",
        pains: [
          "Unclear which scene variants were genuinely validated in simulation",
          "Data provenance and edit revisions remain scattered across folders",
          "Difficult to reproduce and audit the exact approved release",
        ],
        handoff: "Release to engineering team",
      },
    ],
    footnote:
      "We are measuring manual pipeline duration on reference scenes for baseline comparison. Quantitative acceleration will be reported upon measurement.",
  },

  SOLUTION: {
    index: "03 / Solution",
    titleLead: "From a static scan",
    titleEmphasis: "to an editable warehouse scene.",
    lead:
      "Reconstructing 3D from video is handled by existing open tools. Real2Sim focuses on what comes next: decomposing scenes into objects, attaching colliders, verifying metric scale, and auditing before use.",
    mapTitle: "A concrete resolution for each bottleneck",
    map: [
      {
        problem: "Monolithic geometry",
        answer: "Decompose into discrete objects: pallets, racks, bins. AI proposes, human confirms.",
        status: "done" as Status,
      },
      {
        problem: "Missing object colliders",
        answer: "Attach rigid colliders per object and isolate obstacles from floor plane.",
        status: "done" as Status,
      },
      {
        problem: "Unverified metric dimensions",
        answer: "Calibrate scale via known ground-truth distance, with independent check distance.",
        status: "done" as Status,
      },
      {
        problem: "Outdated on layout changes",
        answer: "Edit directly in scene: add box obstacles and hide moved items; transform tools in progress.",
        status: "building" as Status,
      },
    ],
    extra: {
      title: "Simulate and verify before sign-off",
      body:
        "Execute virtual Start-to-Goal robot navigation to verify pathway clearance (in progress). Reviewer inspects objective evidence before team release.",
    },
    contribution: {
      title: "Real2Sim Value Proposition",
      notTitle: "What we do not reinvent",
      not: "Raw 3D video reconstruction. We leverage battle-tested open tools for initial point clouds.",
      isTitle: "The missing bridge",
      is:
        "Transforming raw scans into segmented, metric-accurate, collider-equipped scenes with human verification at critical checkpoints.",
    },
    columnsTitle: "What each stakeholder receives",
    columns: [
      {
        for: "For Simulation Engineers",
        title: "Browser-native scene authoring",
        points: [
          "Upload video; system extracts frames, computes camera poses, and trains 3DGS",
          "Calibrate metric scale using a known ground-truth reference distance",
          "Review proposed object masks; confirm, rename, ignore, or insert obstacle boxes",
          "Every edit is tracked as an immutable scene revision",
        ],
        outcome: "Fewer tools · No rebuilding from scratch",
      },
      {
        for: "For Robot Integration Engineers",
        title: "Baseline simulation-ready physics",
        points: [
          "Objects isolated from ground plane with designated rigid colliders",
          "Toggle 3DGS, collision mesh, and bounding boxes to inspect geometry errors",
          "Export OpenUSD packages with 6 pre-flight packaging rules enforced",
          "Automated collision and Start-to-Goal path checks in Isaac Sim (in progress)",
        ],
        outcome: "Metric-accurate · Physics colliders",
      },
      {
        for: "For Reviewers",
        title: "Evidence-backed sign-off",
        points: [
          "Automated checklist reports for each processing pipeline stage",
          "Approve or reject with reason log; edits post-approval create fresh revisions",
          "Released packages sealed with cryptographic manifest checksums",
          "Complete provenance: who uploaded, who processed, who signed off",
        ],
        outcome: "Fully auditable · Exact verified package",
      },
    ],
    layers: [
      { code: "Visual", question: "What does it look like?", answer: "3D Gaussian Splatting, interactive in browser.", tone: "geometry" },
      { code: "Geometry", question: "Where are the surfaces?", answer: "Metric mesh and point clouds; registered LiDAR is optional.", tone: "ink" },
      { code: "Physics", question: "What does the robot collide with?", answer: "Rigid colliders sharing unified transform across layers.", tone: "ochre" },
    ],
    layersNote: "Moving an object transforms all three representation layers simultaneously.",
    checkpoints: ["Metric scale confirm", "Object candidate confirm", "Reviewer sign-off"],
  },

  WORKFLOW: {
    index: "04 / Workflow",
    titleLead: "From raw video",
    titleEmphasis: "to an audited simulation package.",
    lead:
      "Every step clearly distinguishes automated machine computation from human checkpoints. A photorealistic 3DGS preview does not mean the scene is simulation-ready.",
    steps: [
      {
        code: "01",
        title: "Data Intake",
        actor: "Human",
        body: "Upload MP4 video from a moving camera; registered LiDAR is optional. System validates video while you declare data license.",
        output: "Processing Job",
        status: "done",
      },
      {
        code: "02",
        title: "3D Reconstruction",
        actor: "Machine",
        body: "Frame extraction, COLMAP camera pose estimation, Brush 3DGS training, and SOG compression for instant browser preview.",
        output: "3DGS Preview",
        status: "done",
      },
      {
        code: "03",
        title: "Metric Scale",
        actor: "Human",
        body: "Pick reference points with known real-world distance, set independent validation distance and ground plane. Pre-fills estimates for review.",
        output: "Metric Scene",
        status: "done",
      },
      {
        code: "04",
        title: "Object Candidates",
        actor: "Machine + Human",
        body: "SAM2 proposes candidate objects. Confirm, rename, ignore, or insert proxy box colliders.",
        output: "Scene Revision",
        status: "done",
      },
      {
        code: "05",
        title: "Sim Package",
        actor: "Machine",
        body: "Isolate objects from floor, generate convex colliders, enforce 6 pre-flight packaging rules, and compile scene.usda.",
        output: "Candidate Package",
        status: "done",
      },
      {
        code: "06",
        title: "Isaac Sim Validation",
        actor: "Machine",
        body: "Load candidate package in NVIDIA Isaac Sim; execute collision and Start-to-Goal path feasibility checks.",
        output: "Validation Report",
        status: "building",
      },
      {
        code: "07",
        title: "Review & Release",
        actor: "Human",
        body: "Reviewer examines evidence and approves or rejects. Approved release is sealed with manifest checksum.",
        output: "Audited Release",
        status: "building",
      },
    ] as WorkflowStep[],
  },

  PROGRESS: {
    index: "05 / Progress",
    titleLead: "Proven in production.",
    titleEmphasis: "Transparent on what is next.",
    lead:
      "Studio MVP demonstrates video → 3DGS on local GPU (Quadro T2000). The matrix below separates proven capabilities, ongoing tasks, and future roadmap.",
    tiers: [
      {
        status: "done" as Status,
        title: "Scene authoring pipeline",
        items: [
          "Video → 3DGS executed on local GPU",
          "Metric scale calibration, object candidate confirmation",
          "Simulation packaging passes 6/6 pre-flight rules on reference job",
        ],
      },
      {
        status: "building" as Status,
        title: "Simulation validation",
        items: [
          "Automated validation in NVIDIA Isaac Sim: collision & Start-to-Goal paths",
          "Interactive translation/rotation; scale calibration for video + LiDAR inputs",
          "Pipeline v2: object-centric decomposition, inpainting, and hybrid USD export",
        ],
      },
      {
        status: "later" as Status,
        title: "Future extensions",
        items: [
          "LiDAR-only reconstruction pipeline",
          "Domain & simulator adapters, including autonomous driving in CARLA",
          "Cloud Studio deployment",
        ],
      },
    ],
    metricsTitle: "Committed evaluation metrics",
    metrics: [
      { group: "Visual", items: "PSNR · SSIM · LPIPS" },
      { group: "Scale & Geometry", items: "Scale error · Chamfer distance against reference geometry" },
      { group: "Collision & Trajectory", items: "Collision F1 · Path feasibility" },
      { group: "System", items: "Isaac Sim import pass rate · End-to-end processing time" },
    ],
    metricsNote: "Acceptance thresholds are locked prior to final evaluation runs.",
    samplesTitle: "Pre-processed sample scenes",
    samplesLead: "Explore interactive scenes immediately without login or GPU compute.",
  },

  ROADMAP: {
    index: "06 / Use Cases",
    titleLead: "One Real2Sim core.",
    titleEmphasis: "Multiple simulation runtimes.",
    lead:
      "Core processing is decoupled from domain logic and simulation runtimes. The 4-week MVP commits to a primary slice; other directions leverage the same core.",
    core: "Universal Real2Sim Core",
    adapters: ["DomainAdapter", "SimulatorAdapter"],
    tracks: [
      {
        state: "current" as TrackState,
        tag: "MVP · in progress",
        domain: "Indoor Warehouse Robots",
        simulator: "NVIDIA Isaac Sim",
        body: "End-to-end slice from warehouse video to reviewed simulation package.",
      },
      {
        state: "partial" as TrackState,
        tag: "Partial support",
        domain: "Other 3D Tools",
        simulator: "3DGS (PLY / SOG) · OpenUSD",
        body: "Export 3DGS files or OpenUSD packages to open in other tools. Tool-specific compatibility is not yet tested.",
      },
      {
        state: "later" as TrackState,
        tag: "Post-MVP",
        domain: "Autonomous Vehicles",
        simulator: "CARLA & other simulators",
        body: "Reuses core pipeline, swapping domain and simulator adapters.",
      },
    ],
  },

  START: {
    titleLead: "Start small.",
    titleEmphasis: "Try a sample scene first.",
    steps: [
      { title: "Try sample scenes", body: "Inspect recorded pipeline timeline and explore pre-built scenes. No account required." },
      { title: "Sign in & upload video", body: "Create scenes, trace pipeline stages, and confirm critical checkpoints." },
      { title: "Download sim package", body: "Receive sealed OpenUSD assets tied to verified revisions with audit report." },
    ],
  },

  FOOTER: {
    tagline: "Transform real-world capture into structured, audited simulation scenes.",
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
    oneObjectThreeLayers: "Một vật, ba lớp, một transform.",
    humanDecisions: "Những chỗ con người quyết định",
    diagramCaption: "Sơ đồ minh hoạ luồng xử lý, không phải ảnh chụp kết quả.",
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
    oneObjectThreeLayers: "One entity, three layers, one transform.",
    humanDecisions: "Human verification checkpoints",
    diagramCaption: "Pipeline schematic diagram, not rendered result.",
    step: "Step",
  },
};

export function getContent(lang: Language = "vi") {
  return lang === "en" ? CONTENT_EN : CONTENT_VI;
}

export function getUiLabels(lang: Language = "vi") {
  return lang === "en" ? UI_LABELS.en : UI_LABELS.vi;
}

// Giữ các export mặc định (tiếng Việt) để tương thích ngược hoàn toàn
export const STATUS_LABEL = CONTENT_VI.STATUS_LABEL;
export const NAV = CONTENT_VI.NAV;
export const HERO = CONTENT_VI.HERO;
export const HERO_CHAIN = CONTENT_VI.HERO_CHAIN;
export const CONTEXT = CONTENT_VI.CONTEXT;
export const PROBLEM = CONTENT_VI.PROBLEM;
export const SOLUTION = CONTENT_VI.SOLUTION;
export const WORKFLOW = CONTENT_VI.WORKFLOW;
export const PROGRESS = CONTENT_VI.PROGRESS;
export const ROADMAP = CONTENT_VI.ROADMAP;
export const START = CONTENT_VI.START;
export const FOOTER = CONTENT_VI.FOOTER;
