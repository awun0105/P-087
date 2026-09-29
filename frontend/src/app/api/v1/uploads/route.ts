/**
 * Stream video upload thẳng sang FastAPI.
 *
 * Rewrite `/api/v1/*` của Next buffer body tối đa 10MB rồi cắt (Next 16), nên video
 * thật hỏng giữa chừng. Route handler này được ưu tiên trước rewrite, chuyển tiếp
 * `request.body` dạng stream (không giữ cả file trong RAM) và trả nguyên response.
 */

const BACKEND_ORIGIN = process.env.REAL2SIM_API_URL ?? "http://127.0.0.1:8000";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function passthrough(response: Response): Response {
  return new Response(response.body, {
    status: response.status,
    headers: { "Content-Type": response.headers.get("Content-Type") ?? "application/json" },
  });
}

export async function POST(request: Request): Promise<Response> {
  const search = new URL(request.url).search;
  try {
    const response = await fetch(`${BACKEND_ORIGIN}/api/v1/uploads${search}`, {
      method: "POST",
      body: request.body,
      headers: { "Content-Type": request.headers.get("Content-Type") ?? "application/octet-stream" },
      // Node fetch cần `duplex` khi body là stream.
      duplex: "half",
      signal: request.signal,
    } as RequestInit & { duplex: "half" });
    return passthrough(response);
  } catch {
    return Response.json({ detail: "Không chuyển được video tới backend" }, { status: 502 });
  }
}

export async function GET(): Promise<Response> {
  try {
    return passthrough(await fetch(`${BACKEND_ORIGIN}/api/v1/uploads`, { cache: "no-store" }));
  } catch {
    return Response.json({ detail: "Không gọi được backend" }, { status: 502 });
  }
}
