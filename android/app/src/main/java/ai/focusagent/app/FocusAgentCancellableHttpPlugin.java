package ai.focusagent.app;

import android.os.Build;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.io.BufferedWriter;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStreamWriter;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.Semaphore;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONException;

@CapacitorPlugin(name = "FocusAgentCancellableHttp")
public class FocusAgentCancellableHttpPlugin extends Plugin {
    private static final int MAX_REQUEST_ID_LENGTH = 128;
    static final int MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
    static final int MAX_CONCURRENT_REQUESTS = 4;
    static final int MAX_ACTIVE_REQUESTS = 8;
    static final int MAX_QUEUED_REQUESTS =
        MAX_ACTIVE_REQUESTS - MAX_CONCURRENT_REQUESTS;

    private final Object lifecycleLock = new Object();
    private final ExecutorService executor;
    private final Semaphore activeRequestSlots;
    private final Map<String, RequestState> requests = new ConcurrentHashMap<>();
    private boolean destroyed;

    public FocusAgentCancellableHttpPlugin() {
        this(createRequestExecutor(), MAX_ACTIVE_REQUESTS);
    }

    FocusAgentCancellableHttpPlugin(
        ExecutorService executor,
        int maxActiveRequests
    ) {
        this.executor = Objects.requireNonNull(executor);
        if (maxActiveRequests < 1) {
            throw new IllegalArgumentException(
                "maxActiveRequests must be positive."
            );
        }
        activeRequestSlots = new Semaphore(maxActiveRequests);
    }

    static ThreadPoolExecutor createRequestExecutor() {
        ThreadPoolExecutor executor = new ThreadPoolExecutor(
            MAX_CONCURRENT_REQUESTS,
            MAX_CONCURRENT_REQUESTS,
            30L,
            TimeUnit.SECONDS,
            new ArrayBlockingQueue<>(MAX_QUEUED_REQUESTS),
            Executors.defaultThreadFactory(),
            new ThreadPoolExecutor.AbortPolicy()
        );
        executor.allowCoreThreadTimeOut(true);
        return executor;
    }

    @PluginMethod
    public void postJson(PluginCall call) {
        String requestId = call.getString("request_id");
        String rawUrl = call.getString("url");
        String body = call.getString("body");
        Integer connectTimeout = call.getInt("connect_timeout");
        Integer readTimeout = call.getInt("read_timeout");
        JSObject rawHeaders = call.getObject("headers", new JSObject());

        if (!isValidRequestId(requestId)) {
            call.reject("Missing or invalid request_id.");
            return;
        }
        if (rawUrl == null || body == null) {
            call.reject("Missing request URL or body.");
            return;
        }

        final URL url;
        try {
            url = new URL(rawUrl);
        } catch (Exception error) {
            call.reject("Invalid request URL.", error);
            return;
        }
        if (!isAllowedUrl(url)) {
            call.reject("Provider requests must use HTTPS.");
            return;
        }

        synchronized (lifecycleLock) {
            if (destroyed || executor.isShutdown()) {
                call.reject("Provider HTTP service is not available.");
                return;
            }
            if (!activeRequestSlots.tryAcquire()) {
                call.reject("Too many provider HTTP requests are active.");
                return;
            }

            RequestState state = new RequestState(call);
            if (requests.putIfAbsent(requestId, state) != null) {
                activeRequestSlots.release();
                call.reject(
                    "A request with this request_id is already active."
                );
                return;
            }

            try {
                Future<?> future = executor.submit(
                    () ->
                        executePost(
                            requestId,
                            state,
                            url,
                            rawHeaders,
                            body,
                            connectTimeout,
                            readTimeout
                        )
                );
                state.setFuture(future);
            } catch (RejectedExecutionException error) {
                try {
                    state.rejectUnavailable(error);
                } finally {
                    finishRequest(requestId, state);
                }
            }
        }
    }

    @PluginMethod
    public void cancel(PluginCall call) {
        String requestId = call.getString("request_id");
        if (!isValidRequestId(requestId)) {
            call.reject("Missing or invalid request_id.");
            return;
        }

        synchronized (lifecycleLock) {
            RequestState state = requests.remove(requestId);
            if (state != null) {
                try {
                    if (state.cancel()) {
                        state.rejectCancelled();
                    }
                } finally {
                    state.releaseSlot(activeRequestSlots);
                    purgeCancelledTasks();
                }
            }
        }
        call.resolve();
    }

    @Override
    protected void handleOnDestroy() {
        List<RequestState> cancelledStates = new ArrayList<>();
        synchronized (lifecycleLock) {
            destroyed = true;
            for (
                Map.Entry<String, RequestState> entry : new ArrayList<>(
                    requests.entrySet()
                )
            ) {
                RequestState state = entry.getValue();
                if (
                    requests.remove(entry.getKey(), state) && state.cancel()
                ) {
                    cancelledStates.add(state);
                }
                state.releaseSlot(activeRequestSlots);
            }
            executor.shutdownNow();
        }
        for (RequestState state : cancelledStates) {
            try {
                state.rejectCancelled();
            } catch (RuntimeException ignored) {
                // The WebView may already be gone during plugin destruction.
            }
        }
        super.handleOnDestroy();
    }

    private void executePost(
        String requestId,
        RequestState state,
        URL url,
        JSObject headers,
        String body,
        Integer connectTimeout,
        Integer readTimeout
    ) {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) url.openConnection();
            state.connection = connection;
            if (state.cancelled.get()) {
                return;
            }

            connection.setRequestMethod("POST");
            connection.setDoOutput(true);
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(boundedTimeout(connectTimeout, 30000));
            connection.setReadTimeout(boundedTimeout(readTimeout, 120000));
            applyHeaders(connection, headers);

            try (
                BufferedWriter writer = new BufferedWriter(
                    new OutputStreamWriter(connection.getOutputStream(), StandardCharsets.UTF_8)
                )
            ) {
                writer.write(body);
            }
            if (state.cancelled.get()) {
                return;
            }

            int status = connection.getResponseCode();
            InputStream stream = status >= 400
                ? connection.getErrorStream()
                : connection.getInputStream();
            String responseBody = readResponse(stream, state);
            if (state.cancelled.get()) {
                return;
            }

            JSObject result = new JSObject();
            result.put("status", status);
            result.put("body", responseBody);
            resolveRequest(state, result);
        } catch (Exception error) {
            rejectRequestFailure(state, error);
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
            state.connection = null;
            finishRequest(requestId, state);
        }
    }

    private void finishRequest(String requestId, RequestState state) {
        requests.remove(requestId, state);
        state.releaseSlot(activeRequestSlots);
    }

    private void resolveRequest(RequestState state, JSObject result) {
        synchronized (lifecycleLock) {
            state.resolve(result);
        }
    }

    private void rejectRequestFailure(RequestState state, Exception error) {
        synchronized (lifecycleLock) {
            state.rejectFailure(error);
        }
    }

    private void purgeCancelledTasks() {
        if (executor instanceof ThreadPoolExecutor) {
            ((ThreadPoolExecutor) executor).purge();
        }
    }

    int activeRequestCount() {
        return requests.size();
    }

    private void applyHeaders(HttpURLConnection connection, JSObject headers) throws JSONException {
        Iterator<String> keys = headers.keys();
        while (keys.hasNext()) {
            String name = keys.next();
            Object value = headers.get(name);
            if (value instanceof String && isSafeHeaderName(name)) {
                connection.setRequestProperty(name, (String) value);
            }
        }
    }

    private String readResponse(InputStream stream, RequestState state)
        throws Exception {
        return readUtf8Response(stream, state.cancelled);
    }

    static String readUtf8Response(
        InputStream stream,
        AtomicBoolean cancelled
    ) throws Exception {
        if (stream == null) {
            return "";
        }
        try (InputStream input = stream) {
            ByteArrayOutputStream response = new ByteArrayOutputStream();
            byte[] buffer = new byte[8192];
            int totalBytes = 0;
            int read;
            while ((read = input.read(buffer)) != -1) {
                if (cancelled.get()) {
                    return "";
                }
                if (read > MAX_RESPONSE_BYTES - totalBytes) {
                    throw new IllegalStateException(
                        "Provider response exceeded the maximum size."
                    );
                }
                response.write(buffer, 0, read);
                totalBytes += read;
            }
            return new String(response.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    private boolean isAllowedUrl(URL url) {
        if (url.getUserInfo() != null || url.getHost().isEmpty()) {
            return false;
        }
        if ("https".equalsIgnoreCase(url.getProtocol())) {
            return true;
        }
        return isDebugEmulatorLoopbackUrl(url);
    }

    private boolean isDebugEmulatorLoopbackUrl(URL url) {
        if (!BuildConfig.DEBUG || !"http".equalsIgnoreCase(url.getProtocol())) {
            return false;
        }
        String host = url.getHost();
        return "10.0.2.2".equals(host) || "10.0.3.2".equals(host);
    }

    private boolean isSafeHeaderName(String name) {
        return name != null && name.matches("[A-Za-z0-9-]+");
    }

    private boolean isValidRequestId(String requestId) {
        return (
            requestId != null &&
            requestId.length() <= MAX_REQUEST_ID_LENGTH &&
            requestId.matches("[A-Za-z0-9_-]+")
        );
    }

    private int boundedTimeout(Integer timeout, int fallback) {
        if (timeout == null) {
            return fallback;
        }
        return Math.max(1, Math.min(timeout, 120000));
    }

    private static class RequestState {
        private final AtomicBoolean cancelled = new AtomicBoolean(false);
        private final PluginCall call;
        private volatile HttpURLConnection connection;
        private volatile Future<?> future;
        private boolean finished;
        private final AtomicBoolean slotReleased = new AtomicBoolean(false);

        RequestState(PluginCall call) {
            this.call = call;
        }

        synchronized boolean cancel() {
            if (finished) {
                return false;
            }
            finished = true;
            cancelled.set(true);
            HttpURLConnection activeConnection = connection;
            if (activeConnection != null) {
                activeConnection.disconnect();
            }
            Future<?> activeFuture = future;
            if (activeFuture != null) {
                activeFuture.cancel(true);
            }
            return true;
        }

        synchronized void setFuture(Future<?> activeFuture) {
            future = activeFuture;
            if (cancelled.get()) {
                activeFuture.cancel(true);
            }
        }

        synchronized void resolve(JSObject result) {
            if (cancelled.get() || finished) {
                return;
            }
            finished = true;
            call.resolve(result);
        }

        synchronized void rejectFailure(Exception error) {
            if (cancelled.get() || finished) {
                return;
            }
            finished = true;
            call.reject("Provider HTTP request failed.", error);
        }

        synchronized void rejectUnavailable(
            RejectedExecutionException error
        ) {
            if (cancelled.get() || finished) {
                return;
            }
            finished = true;
            call.reject(
                "Provider HTTP service is temporarily unavailable.",
                error
            );
        }

        void rejectCancelled() {
            call.reject("Provider HTTP request cancelled.");
        }

        void releaseSlot(Semaphore activeRequestSlots) {
            if (slotReleased.compareAndSet(false, true)) {
                activeRequestSlots.release();
            }
        }
    }
}
