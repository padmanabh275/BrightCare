import { NextRequest, NextResponse } from "next/server";

const UPSTREAM = (process.env.API_PROXY_URL || "http://127.0.0.1:8000").replace(
  /\/$/,
  ""
);

async function proxy(req: NextRequest, path: string[]) {
  const targetPath = path.join("/");
  const url = new URL(req.url);
  const dest = `${UPSTREAM}/api/${targetPath}${url.search}`;

  const headers = new Headers();
  const auth = req.headers.get("authorization");
  const contentType = req.headers.get("content-type");
  const jobsSecret = req.headers.get("x-jobs-secret");
  if (auth) headers.set("authorization", auth);
  if (contentType) headers.set("content-type", contentType);
  if (jobsSecret) headers.set("x-jobs-secret", jobsSecret);

  const init: RequestInit = {
    method: req.method,
    headers,
    cache: "no-store",
  };

  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.text();
  }

  try {
    const upstream = await fetch(dest, init);
    const body = await upstream.arrayBuffer();
    return new NextResponse(body, {
      status: upstream.status,
      headers: {
        "content-type":
          upstream.headers.get("content-type") || "application/json",
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Upstream unreachable";
    return NextResponse.json(
      {
        detail: `API proxy failed (${UPSTREAM}). Set API_PROXY_URL to a public HTTPS FastAPI URL. ${message}`,
      },
      { status: 502 }
    );
  }
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}

export async function POST(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}

export async function PUT(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}

export async function PATCH(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}

export async function DELETE(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params;
  return proxy(req, path);
}
