import { API_URL, ApiError, DEFAULT_TIMEOUT_MS, errorFromResponse, fetchFailure, linkedAbort } from "@/lib/api";
import type { AskEvent, AskFinal, AskRequest } from "@/lib/types";

const KNOWN_EVENTS = new Set(["start", "status", "tool_call", "tool_result", "token", "final", "error"]);
const BOUNDARY = /\r?\n\r?\n/; // a blank line ends an event; sse-starlette sends \r\n

export interface AskStreamOptions {
  signal?: AbortSignal;
  onEvent?: (event: AskEvent) => void;
  connectTimeoutMs?: number; // covers waking the backend, not the answer itself
}

// Parses one SSE block ("event: x\ndata: {...}") into an event, or null for pings/comments.
function parseBlock(block: string): AskEvent | null {
  let name = "message";
  const data: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (line === "" || line.startsWith(":")) continue; // ": ping" comments
    const i = line.indexOf(":");
    const field = i === -1 ? line : line.slice(0, i);
    let value = i === -1 ? "" : line.slice(i + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") name = value;
    else if (field === "data") data.push(value);
  }
  if (!data.length || !KNOWN_EVENTS.has(name)) return null;
  return { event: name, data: JSON.parse(data.join("\n")) } as AskEvent;
}

/**
 * POST /ask with stream=true. Calls onEvent for every event in order and resolves with the
 * final payload. Rejects with ApiError: busy (429), validation (422), stream (an SSE error
 * event), network/timeout/aborted.
 */
export async function askStream(
  req: AskRequest,
  { signal, onEvent, connectTimeoutMs = DEFAULT_TIMEOUT_MS }: AskStreamOptions = {},
): Promise<AskFinal> {
  const abort = linkedAbort(signal, connectTimeoutMs);
  let res: Response;
  try {
    res = await fetch(`${API_URL}/ask`, {
      method: "POST",
      signal: abort.signal,
      cache: "no-store",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ ...req, stream: true }),
    });
  } catch {
    abort.clear();
    throw fetchFailure(abort.timedOut(), Boolean(signal?.aborted), connectTimeoutMs);
  }
  abort.clear(); // connected: from here on only the caller's signal can stop the stream

  if (!res.ok) throw await errorFromResponse(res);
  if (!res.body) throw new ApiError("network", "The backend sent no stream.");

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  const stop = () => reader.cancel().catch(() => {});
  signal?.addEventListener("abort", stop, { once: true });

  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += value;

      let match: RegExpExecArray | null;
      while ((match = BOUNDARY.exec(buffer))) {
        const block = buffer.slice(0, match.index);
        buffer = buffer.slice(match.index + match[0].length);
        const event = parseBlock(block);
        if (!event) continue;
        onEvent?.(event);
        if (event.event === "final") return event.data;
        if (event.event === "error") throw new ApiError("stream", event.data.message);
      }
    }
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if (signal?.aborted) throw new ApiError("aborted", "Request cancelled.");
    throw new ApiError("network", "The connection dropped before the answer finished.");
  } finally {
    signal?.removeEventListener("abort", stop);
    stop();
  }

  if (signal?.aborted) throw new ApiError("aborted", "Request cancelled.");
  throw new ApiError("network", "The stream ended before the final answer.");
}