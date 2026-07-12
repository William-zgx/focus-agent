package ai.focusagent.app;

import static org.junit.Assert.*;

import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.security.NetworkSecurityPolicy;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import com.getcapacitor.JSObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/**
 * Instrumented test, which will execute on an Android device.
 *
 * @see <a href="http://d.android.com/tools/testing">Testing documentation</a>
 */
@RunWith(AndroidJUnit4.class)
public class ExampleInstrumentedTest {

    @Test
    public void useAppContext() throws Exception {
        // Context of the app under test.
        Context appContext = InstrumentationRegistry.getInstrumentation().getTargetContext();

        assertEquals("ai.focusagent.app", appContext.getPackageName());
    }

    @Test
    public void debugCleartextIsLimitedToEmulatorLoopback() {
        NetworkSecurityPolicy policy = NetworkSecurityPolicy.getInstance();

        assertTrue(policy.isCleartextTrafficPermitted("10.0.2.2"));
        assertTrue(policy.isCleartextTrafficPermitted("10.0.3.2"));
        assertFalse(policy.isCleartextTrafficPermitted("example.com"));
        assertFalse(policy.isCleartextTrafficPermitted("127.0.0.1"));
    }

    @Test
    public void appUrlOpenRetainsDeepLinkUntilListenerIsRegistered() {
        RetainingFocusAgentAppPlugin plugin = new RetainingFocusAgentAppPlugin();

        plugin.onNewIntent(
            new Intent(
                Intent.ACTION_VIEW,
                Uri.parse("focusagent://app/c/conversation-1/t/thread-2")
            )
        );

        assertEquals("appUrlOpen", plugin.eventName);
        assertEquals("focusagent://app/c/conversation-1/t/thread-2", plugin.url);
        assertTrue(plugin.retainUntilConsumed);
    }

    @Test
    public void appUrlOpenIgnoresNonViewIntent() {
        RetainingFocusAgentAppPlugin plugin = new RetainingFocusAgentAppPlugin();

        plugin.onNewIntent(new Intent(Intent.ACTION_MAIN));

        assertNull(plugin.eventName);
    }

    private static final class RetainingFocusAgentAppPlugin extends FocusAgentAppPlugin {
        private String eventName;
        private boolean retainUntilConsumed;
        private String url;

        void onNewIntent(Intent intent) {
            handleOnNewIntent(intent);
        }

        @Override
        protected void notifyListeners(
            String eventName,
            JSObject data,
            boolean retainUntilConsumed
        ) {
            this.eventName = eventName;
            this.retainUntilConsumed = retainUntilConsumed;
            this.url = data.getString("url");
        }
    }
}
