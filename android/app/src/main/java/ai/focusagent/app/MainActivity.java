package ai.focusagent.app;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(FocusAgentSecureStoragePlugin.class);
        super.onCreate(savedInstanceState);
    }
}
