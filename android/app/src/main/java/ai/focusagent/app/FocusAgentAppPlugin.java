package ai.focusagent.app;

import android.content.Intent;
import android.net.Uri;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.util.Collections;
import java.util.Locale;
import java.util.Set;
import java.util.WeakHashMap;

@CapacitorPlugin(name = "App")
public class FocusAgentAppPlugin extends Plugin {
    private static final String EVENT_URL_OPEN = "appUrlOpen";
    private final DeepLinkState deepLinkState = new DeepLinkState();

    @Override
    public void load() {
        deepLinkState.captureLaunchIntent(getActivity().getIntent());
    }

    @Override
    protected void handleOnNewIntent(Intent intent) {
        String url = deepLinkState.consumeNewIntent(intent);
        if (url == null) {
            return;
        }
        JSObject event = new JSObject();
        event.put("url", url);
        notifyListeners(EVENT_URL_OPEN, event, true);
    }

    @PluginMethod
    public void getLaunchUrl(PluginCall call) {
        JSObject result = new JSObject();
        result.put("url", deepLinkState.consumeLaunchUrl());
        call.resolve(result);
    }

    @Override
    protected void handleOnDestroy() {
        deepLinkState.clear();
        super.handleOnDestroy();
    }

    static String intentUrl(Intent intent) {
        if (intent == null || !Intent.ACTION_VIEW.equals(intent.getAction())) {
            return null;
        }
        Uri data = intent.getData();
        if (
            data == null ||
            !data.isHierarchical() ||
            !"focusagent".equalsIgnoreCase(data.getScheme()) ||
            !"app".equalsIgnoreCase(data.getHost()) ||
            data.getUserInfo() != null ||
            data.getPort() != -1
        ) {
            return null;
        }
        String encodedPath = data.getEncodedPath();
        if (encodedPath != null) {
            String normalizedPath = encodedPath.toLowerCase(Locale.ROOT);
            if (normalizedPath.contains("%2f") || normalizedPath.contains("%5c")) {
                return null;
            }
        }
        return data.toString();
    }

    static final class DeepLinkState {
        private final Set<Intent> deliveredIntents =
            Collections.newSetFromMap(new WeakHashMap<>());
        private Intent launchIntent;
        private String launchUrl;
        private boolean active = true;

        synchronized void captureLaunchIntent(Intent intent) {
            active = true;
            launchIntent = intent;
            deliveredIntents.clear();
            launchUrl = intentUrl(intent);
        }

        synchronized String consumeLaunchUrl() {
            if (!active) {
                return null;
            }
            String url = launchUrl;
            launchUrl = null;
            return url;
        }

        synchronized String consumeNewIntent(Intent intent) {
            if (
                !active ||
                intent == launchIntent ||
                deliveredIntents.contains(intent)
            ) {
                return null;
            }
            String url = intentUrl(intent);
            if (url == null) {
                return null;
            }
            deliveredIntents.add(intent);
            return url;
        }

        synchronized void clear() {
            active = false;
            launchIntent = null;
            deliveredIntents.clear();
            launchUrl = null;
        }
    }
}
