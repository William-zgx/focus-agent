import type { FocusAgentModelOption } from "@focus-agent/web-sdk";

import { useModels } from "@/features/models/use-models";

export function ModelStatus() {
  const { data } = useModels();
  const selected =
    data?.models.find((item: FocusAgentModelOption) => item.is_default) ?? data?.models[0];

  return (
    <div className="fa-model-pill">
      {selected ? `Default model: ${selected.label}` : "Loading models..."}
    </div>
  );
}
