/**
 * Aethelgard — Cloudflare Worker image proxy (EXAMPLE).
 *
 * Deploy this in Cloudflare Workers (Workers & Pages → Create → paste code).
 * Then set secrets / vars:
 *   wrangler secret put API_KEY   (or Dashboard → Settings → Variables → API_KEY)
 * And ensure an AI binding named "AI" exists (Settings → Bindings → Workers AI).
 *
 * IMPORTANT
 * - Free tier is ~10,000 Neurons/day — NOT 100k images.
 *   SDXL ≈ 300–500 neurons/image → roughly 20–30 images/day.
 *   Prefer lightning / dreamshaper for more images per day.
 * - Never commit your API_KEY. Rotate it if it was pasted into chat.
 * - After deploy, put these in ~/.config/ai-images/env:
 *     CLOUDFLARE_WORKER_URL=https://YOUR-WORKER.YOUR-SUBDOMAIN.workers.dev
 *     CLOUDFLARE_WORKER_KEY=your-secret-here
 */

const MODELS = {
  // Faster / cheaper neurons (better for free-tier volume)
  "sdxl-lightning": "@cf/bytedance/stable-diffusion-xl-lightning",
  "dreamshaper": "@cf/lykon/dreamshaper-8-lcm",
  // Heavier — fewer free images/day
  "sdxl": "@cf/stabilityai/stable-diffusion-xl-base-1.0",
  // Flux returns { image: base64 } — handled below
  // NOTE: Flux Schnell license is often non-commercial; prefer SDXL for Etsy sells.
  "flux-schnell": "@cf/black-forest-labs/flux-1-schnell",
};

const ASPECT_SIZE = {
  "1:1": [1024, 1024],
  "4:5": [896, 1152],
  "2:3": [896, 1344],
  "3:2": [1344, 896],
  "16:9": [1344, 768],
  "9:16": [768, 1344],
};

export default {
  async fetch(request, env) {
    const API_KEY = env.API_KEY;
    const url = new URL(request.url);

    // CORS preflight (optional — dashboard calls from localhost via Python, not browser)
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }

    const auth = request.headers.get("Authorization") || "";
    if (!API_KEY || auth !== `Bearer ${API_KEY}`) {
      return json({ error: "Unauthorized" }, 401);
    }

    if (request.method !== "POST" || (url.pathname !== "/" && url.pathname !== "/generate")) {
      return json({ error: "Not allowed. POST / with JSON { prompt, model?, aspect? }" }, 405);
    }

    try {
      const body = await request.json();
      const prompt = (body.prompt || "").trim();
      if (!prompt) return json({ error: "Prompt is required" }, 400);

      const alias = body.model || "sdxl-lightning";
      const modelId = MODELS[alias] || alias; // allow raw @cf/... ids too
      const aspect = body.aspect || "4:5";
      const [width, height] = ASPECT_SIZE[aspect] || ASPECT_SIZE["4:5"];

      const input = {
        prompt,
        width,
        height,
        // Default ban — callers can override with body.negative_prompt
        negative_prompt:
          body.negative_prompt ||
          "text, letters, words, typography, labels, captions, handwriting, watermark, signature, logo, diagram, chart, frame, picture frame, mat, border, mockup, room, wall, blurry, blank, black image",
      };
      if (body.num_steps != null) input.num_steps = body.num_steps;
      if (body.guidance != null) input.guidance = body.guidance;
      if (body.seed != null) input.seed = body.seed;
      // Flux uses "steps" instead of num_steps on some bindings
      if (modelId.includes("flux") && body.steps != null) input.steps = body.steps;

      const result = await env.AI.run(modelId, input);

      // Flux-style: { image: "<base64>" }
      if (result && typeof result === "object" && result.image) {
        const binary = Uint8Array.from(atob(result.image), (c) => c.charCodeAt(0));
        return new Response(binary, {
          headers: { ...corsHeaders(), "Content-Type": "image/jpeg" },
        });
      }

      // SDXL / lightning: ReadableStream or raw bytes
      return new Response(result, {
        headers: { ...corsHeaders(), "Content-Type": "image/png" },
      });
    } catch (err) {
      return json(
        {
          error: "Failed to generate image",
          details: err && err.message ? err.message : String(err),
        },
        500
      );
    }
  },
};

function corsHeaders() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
  };
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...corsHeaders(), "Content-Type": "application/json" },
  });
}
