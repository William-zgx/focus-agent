package ai.focusagent.app;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import com.getcapacitor.JSObject;
import com.getcapacitor.PluginCall;
import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.AbstractExecutorService;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.Test;

public class FocusAgentCancellableHttpPluginTest {

    @Test
    public void requestExecutorHasBoundedWorkersAndQueue() {
        ThreadPoolExecutor executor =
            FocusAgentCancellableHttpPlugin.createRequestExecutor();
        try {
            assertEquals(
                FocusAgentCancellableHttpPlugin.MAX_CONCURRENT_REQUESTS,
                executor.getCorePoolSize()
            );
            assertEquals(
                FocusAgentCancellableHttpPlugin.MAX_CONCURRENT_REQUESTS,
                executor.getMaximumPoolSize()
            );
            assertEquals(
                FocusAgentCancellableHttpPlugin.MAX_QUEUED_REQUESTS,
                executor.getQueue().remainingCapacity()
            );
        } finally {
            executor.shutdownNow();
        }
    }

    @Test
    public void utf8ResponseLimitAcceptsExactlyTwoMiB() throws Exception {
        byte[] payload =
            repeatedUtf8("é", FocusAgentCancellableHttpPlugin.MAX_RESPONSE_BYTES);

        String response = FocusAgentCancellableHttpPlugin.readUtf8Response(
            new ByteArrayInputStream(payload),
            new AtomicBoolean(false)
        );

        assertEquals(
            FocusAgentCancellableHttpPlugin.MAX_RESPONSE_BYTES,
            response.getBytes(StandardCharsets.UTF_8).length
        );
    }

    @Test
    public void utf8ResponseLimitRejectsMultibytePayloadByBytes() {
        byte[] payload = repeatedUtf8(
            "é",
            FocusAgentCancellableHttpPlugin.MAX_RESPONSE_BYTES + 2
        );

        IllegalStateException error = assertThrows(
            IllegalStateException.class,
            () ->
                FocusAgentCancellableHttpPlugin.readUtf8Response(
                    new ByteArrayInputStream(payload),
                    new AtomicBoolean(false)
                )
        );

        assertEquals(
            "Provider response exceeded the maximum size.",
            error.getMessage()
        );
    }

    @Test
    public void activeRequestLimitRecoversAfterCancellation() {
        HoldingExecutor executor = new HoldingExecutor();
        FocusAgentCancellableHttpPlugin plugin =
            new FocusAgentCancellableHttpPlugin(executor, 2);
        RecordingPluginCall first = postCall("first", "https://example.com");
        RecordingPluginCall second = postCall("second", "https://example.com");
        RecordingPluginCall overflow = postCall(
            "overflow",
            "https://example.com"
        );

        plugin.postJson(first);
        plugin.postJson(second);
        plugin.postJson(overflow);

        assertNull(first.rejection);
        assertNull(second.rejection);
        assertEquals(
            "Too many provider HTTP requests are active.",
            overflow.rejection
        );
        assertEquals(2, plugin.activeRequestCount());

        RecordingPluginCall cancel = cancelCall("first");
        plugin.cancel(cancel);
        RecordingPluginCall replacement = postCall(
            "replacement",
            "https://example.com"
        );
        plugin.postJson(replacement);

        assertEquals("Provider HTTP request cancelled.", first.rejection);
        assertTrue(cancel.resolved);
        assertNull(replacement.rejection);
        assertEquals(2, plugin.activeRequestCount());
        plugin.handleOnDestroy();
    }

    @Test
    public void rejectedSubmissionCleansStateAndRejectsPromise() {
        RejectingExecutor executor = new RejectingExecutor();
        FocusAgentCancellableHttpPlugin plugin =
            new FocusAgentCancellableHttpPlugin(executor, 1);
        RecordingPluginCall first = postCall("reusable", "https://example.com");
        RecordingPluginCall second = postCall("reusable", "https://example.com");

        plugin.postJson(first);
        plugin.postJson(second);

        assertEquals(
            "Provider HTTP service is temporarily unavailable.",
            first.rejection
        );
        assertEquals(
            "Provider HTTP service is temporarily unavailable.",
            second.rejection
        );
        assertNotNull(first.rejectionError);
        assertTrue(first.rejectionError instanceof RejectedExecutionException);
        assertEquals(0, plugin.activeRequestCount());
        plugin.handleOnDestroy();
    }

    @Test
    public void destroyRejectsPendingPromiseAndRejectsLaterSubmissions() {
        HoldingExecutor executor = new HoldingExecutor();
        FocusAgentCancellableHttpPlugin plugin =
            new FocusAgentCancellableHttpPlugin(executor, 1);
        RecordingPluginCall pending = postCall(
            "pending",
            "https://example.com"
        );

        plugin.postJson(pending);
        assertEquals(1, plugin.activeRequestCount());
        plugin.handleOnDestroy();

        assertEquals("Provider HTTP request cancelled.", pending.rejection);
        assertEquals(0, plugin.activeRequestCount());
        assertTrue(executor.isShutdown());

        RecordingPluginCall afterDestroy = postCall(
            "after-destroy",
            "https://example.com"
        );
        plugin.postJson(afterDestroy);

        assertEquals(
            "Provider HTTP service is not available.",
            afterDestroy.rejection
        );
        assertEquals(0, plugin.activeRequestCount());
    }

    @Test
    public void urlSafetyAndCancellationRemainEnforced() {
        HoldingExecutor executor = new HoldingExecutor();
        FocusAgentCancellableHttpPlugin plugin =
            new FocusAgentCancellableHttpPlugin(executor, 1);
        RecordingPluginCall cleartext = postCall(
            "cleartext",
            "http://example.com"
        );
        RecordingPluginCall credentials = postCall(
            "credentials",
            "https://user:secret@example.com"
        );
        RecordingPluginCall safe = postCall("safe", "https://example.com");

        plugin.postJson(cleartext);
        plugin.postJson(credentials);
        plugin.postJson(safe);

        assertEquals("Provider requests must use HTTPS.", cleartext.rejection);
        assertEquals("Provider requests must use HTTPS.", credentials.rejection);
        assertNull(safe.rejection);

        RecordingPluginCall cancel = cancelCall("safe");
        plugin.cancel(cancel);

        assertEquals("Provider HTTP request cancelled.", safe.rejection);
        assertTrue(cancel.resolved);
        assertEquals(0, plugin.activeRequestCount());
        plugin.handleOnDestroy();
    }

    private static byte[] repeatedUtf8(String value, int byteLength) {
        byte[] unit = value.getBytes(StandardCharsets.UTF_8);
        assertEquals(0, byteLength % unit.length);
        byte[] payload = new byte[byteLength];
        for (int offset = 0; offset < payload.length; offset += unit.length) {
            System.arraycopy(unit, 0, payload, offset, unit.length);
        }
        return payload;
    }

    private static RecordingPluginCall postCall(
        String requestId,
        String url
    ) {
        JSObject data = new JSObject();
        data.put("request_id", requestId);
        data.put("url", url);
        data.put("body", "{}");
        data.put("headers", new JSObject());
        return new RecordingPluginCall("postJson", data);
    }

    private static RecordingPluginCall cancelCall(String requestId) {
        JSObject data = new JSObject();
        data.put("request_id", requestId);
        return new RecordingPluginCall("cancel", data);
    }

    private static final class RecordingPluginCall extends PluginCall {
        private String rejection;
        private Exception rejectionError;
        private boolean resolved;

        RecordingPluginCall(String methodName, JSObject data) {
            super(null, "FocusAgentCancellableHttp", "test", methodName, data);
        }

        @Override
        public void resolve() {
            resolved = true;
        }

        @Override
        public void resolve(JSObject data) {
            resolved = true;
        }

        @Override
        public void reject(String message) {
            rejection = message;
        }

        @Override
        public void reject(String message, Exception error) {
            rejection = message;
            rejectionError = error;
        }
    }

    private static final class HoldingExecutor
        extends AbstractExecutorService {

        private final List<Runnable> tasks = new ArrayList<>();
        private boolean shutdown;

        @Override
        public void shutdown() {
            shutdown = true;
        }

        @Override
        public List<Runnable> shutdownNow() {
            shutdown = true;
            List<Runnable> pending = new ArrayList<>(tasks);
            tasks.clear();
            return pending;
        }

        @Override
        public boolean isShutdown() {
            return shutdown;
        }

        @Override
        public boolean isTerminated() {
            return shutdown && tasks.isEmpty();
        }

        @Override
        public boolean awaitTermination(long timeout, TimeUnit unit) {
            return isTerminated();
        }

        @Override
        public void execute(Runnable command) {
            if (shutdown) {
                throw new RejectedExecutionException();
            }
            tasks.add(command);
        }
    }

    private static final class RejectingExecutor
        extends AbstractExecutorService {

        private boolean shutdown;

        @Override
        public void shutdown() {
            shutdown = true;
        }

        @Override
        public List<Runnable> shutdownNow() {
            shutdown = true;
            return Collections.emptyList();
        }

        @Override
        public boolean isShutdown() {
            return shutdown;
        }

        @Override
        public boolean isTerminated() {
            return shutdown;
        }

        @Override
        public boolean awaitTermination(long timeout, TimeUnit unit) {
            return shutdown;
        }

        @Override
        public void execute(Runnable command) {
            throw new RejectedExecutionException("test rejection");
        }
    }
}
