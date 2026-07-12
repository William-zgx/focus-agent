package ai.focusagent.app;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

import android.content.Intent;
import android.net.Uri;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class FocusAgentAppPluginDeepLinkTest {
    private static final String DEEP_LINK =
        "focusagent://app/c/conversation-1/t/thread-2/review";

    @Test
    public void coldLaunchIsConsumedOnlyByGetLaunchUrl() {
        FocusAgentAppPlugin.DeepLinkState state = new FocusAgentAppPlugin.DeepLinkState();
        Intent launchIntent = viewIntent(DEEP_LINK);

        state.captureLaunchIntent(launchIntent);

        assertNull(state.consumeNewIntent(launchIntent));
        assertEquals(DEEP_LINK, state.consumeLaunchUrl());
        assertNull(state.consumeLaunchUrl());
        assertNull(state.consumeNewIntent(launchIntent));
    }

    @Test
    public void hotIntentIsDeliveredOnceWithoutDeduplicatingSeparateOpens() {
        FocusAgentAppPlugin.DeepLinkState state = new FocusAgentAppPlugin.DeepLinkState();
        state.captureLaunchIntent(new Intent(Intent.ACTION_MAIN));
        Intent firstOpen = viewIntent(DEEP_LINK);
        Intent secondOpen = viewIntent(DEEP_LINK);

        assertEquals(DEEP_LINK, state.consumeNewIntent(firstOpen));
        assertEquals(DEEP_LINK, state.consumeNewIntent(secondOpen));
        assertNull(state.consumeNewIntent(firstOpen));
        assertNull(state.consumeNewIntent(secondOpen));
    }

    @Test
    public void invalidAndNonViewIntentsAreIgnored() {
        FocusAgentAppPlugin.DeepLinkState state = new FocusAgentAppPlugin.DeepLinkState();
        state.captureLaunchIntent(new Intent(Intent.ACTION_MAIN));

        assertNull(state.consumeNewIntent(null));
        assertNull(state.consumeNewIntent(new Intent(Intent.ACTION_MAIN, Uri.parse(DEEP_LINK))));
        assertNull(state.consumeNewIntent(new Intent(Intent.ACTION_VIEW)));
        assertNull(
            state.consumeNewIntent(
                viewIntent("https://app/c/conversation-1/t/thread-2")
            )
        );
        assertNull(
            state.consumeNewIntent(
                viewIntent("focusagent://other/c/conversation-1/t/thread-2")
            )
        );
        assertNull(
            state.consumeNewIntent(
                viewIntent("focusagent://user@app/c/conversation-1/t/thread-2")
            )
        );
        assertNull(
            state.consumeNewIntent(
                viewIntent("focusagent://app/c%2Fconversation-1/t/thread-2")
            )
        );
    }

    @Test
    public void concurrentConsumersObserveEachIntentAtMostOnce() throws Exception {
        FocusAgentAppPlugin.DeepLinkState state = new FocusAgentAppPlugin.DeepLinkState();
        Intent launchIntent = viewIntent(DEEP_LINK);
        Intent hotIntent = viewIntent("focusagent://app/admin/config");
        state.captureLaunchIntent(launchIntent);

        List<String> launchResults = consumeConcurrently(state::consumeLaunchUrl);
        List<String> hotResults = consumeConcurrently(
            () -> state.consumeNewIntent(hotIntent)
        );

        assertEquals(1, Collections.frequency(launchResults, DEEP_LINK));
        assertEquals(
            1,
            Collections.frequency(hotResults, "focusagent://app/admin/config")
        );
    }

    @Test
    public void destroyClearsPendingLaunchAndStopsDelivery() {
        FocusAgentAppPlugin.DeepLinkState state = new FocusAgentAppPlugin.DeepLinkState();
        state.captureLaunchIntent(viewIntent(DEEP_LINK));

        state.clear();

        assertNull(state.consumeLaunchUrl());
        assertNull(
            state.consumeNewIntent(viewIntent("focusagent://app/admin/config"))
        );
    }

    private static Intent viewIntent(String url) {
        return new Intent(Intent.ACTION_VIEW, Uri.parse(url));
    }

    private static List<String> consumeConcurrently(ValueSupplier supplier)
        throws Exception {
        int workerCount = 12;
        ExecutorService executor = Executors.newFixedThreadPool(workerCount);
        CountDownLatch ready = new CountDownLatch(workerCount);
        CountDownLatch start = new CountDownLatch(1);
        List<String> results = Collections.synchronizedList(new ArrayList<>());
        try {
            for (int index = 0; index < workerCount; index++) {
                executor.execute(
                    () -> {
                        ready.countDown();
                        try {
                            start.await();
                            results.add(supplier.get());
                        } catch (InterruptedException error) {
                            Thread.currentThread().interrupt();
                        }
                    }
                );
            }
            if (!ready.await(5, TimeUnit.SECONDS)) {
                throw new AssertionError("Workers did not become ready.");
            }
            start.countDown();
        } finally {
            executor.shutdown();
            if (!executor.awaitTermination(5, TimeUnit.SECONDS)) {
                executor.shutdownNow();
                throw new AssertionError("Workers did not finish.");
            }
        }
        return results;
    }

    private interface ValueSupplier {
        String get();
    }
}
