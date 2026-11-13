import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = fileURLToPath(new URL("../..", import.meta.url));

function compactSource(sourceText) {
  return sourceText.split(/\s+/u).join(" ");
}

function readSource(relativePath) {
  return readFileSync(path.join(repoRoot, relativePath), "utf8");
}

test("thread auto-follow uses resize-driven sticking and resets on thread switches", () => {
  const autoFollowSource = readSource("apps/web/src/pages/thread/use-thread-auto-follow.ts");
  const threadPageSource = readSource("apps/web/src/pages/thread/thread-page.tsx");
  const compactAutoFollowSource = compactSource(autoFollowSource);

  assert.equal(autoFollowSource.includes("useLayoutEffect"), false);
  assert.equal(autoFollowSource.includes("shouldAutoFollowRef"), false);
  assert.equal(autoFollowSource.includes("hasTranscriptContent"), false);
  assert.equal(threadPageSource.includes("autoFollowSignature"), false);
  assert.equal(compactAutoFollowSource.includes('resize: "smooth"'), true);
  assert.equal(
    compactAutoFollowSource.includes(
      'void threadId; void scrollStickToBottom("instant"); }, [scrollStickToBottom, threadId]);',
    ),
    true,
  );
});

test("stream request registry memoizes its methods and returned API", () => {
  const registrySource = readSource(
    "apps/web/src/features/thread-stream/use-stream-request-registry.ts",
  );

  for (const method of [
    "beginStreamRequest",
    "completeStreamRequest",
    "hasStreamRequest",
    "isCurrentStreamRequest",
    "stopStreamRequest",
  ]) {
    assert.equal(registrySource.includes(`const ${method} = useCallback(`), true, method);
  }
  assert.equal(registrySource.includes("return useMemo("), true);
  assert.equal(registrySource.includes("abortControllersRef"), false);
  assert.equal(registrySource.includes("activeRequestIdsRef"), false);
  assert.equal(
    compactSource(registrySource).includes(
      "for (const request of requestsRef.current.values()) { request.controller.abort(); } requestsRef.current.clear();",
    ),
    true,
  );
});
