export async function handler(event) {
  try {
    const parsed = JSON.parse(event.body || "{}");
    const { method = "GET", body } = parsed;
    const path = parsed.path;

    // Guard — path must be provided
    if (!path || typeof path !== "string") {
      return {
        statusCode: 400,
        body: JSON.stringify({ success: false, error: "Missing path" }),
      };
    }

    const API_KEY = process.env.BUNDLES_GHANA_API_KEY;
    const API_SECRET = process.env.BUNDLES_GHANA_API_SECRET;

    if (!API_KEY || !API_SECRET) {
      return {
        statusCode: 500,
        body: JSON.stringify({ success: false, error: "API credentials not configured" }),
      };
    }

    const url = `https://fripalconnectgh.com/api/v1${path}`;

    const res = await fetch(url, {
      method,
      headers: {
        "X-API-Key": API_KEY,
        "X-API-Secret": API_SECRET,
        "Content-Type": "application/json",
        "Accept": "application/json",
      },
      body: method === "POST" ? JSON.stringify(body) : undefined,
    });

    const text = await res.text();

    // If response is not JSON, return a clean error
    if (!text || text.trim().startsWith("<")) {
      return {
        statusCode: res.status,
        body: JSON.stringify({
          success: false,
          error: `Bundles Ghana returned non-JSON response (status ${res.status})`,
        }),
      };
    }

    return {
      statusCode: res.status,
      body: text,
    };

  } catch (err) {
    return {
      statusCode: 500,
      body: JSON.stringify({ success: false, error: err.message }),
    };
  }
}
