export interface FocusAgentModelOption {
  id: string;
  provider: string;
  provider_label: string;
  name: string;
  label: string;
  is_default: boolean;
  supports_thinking: boolean;
  default_thinking_enabled: boolean;
}

export interface FocusAgentModelsResponse {
  default_model: string;
  models: FocusAgentModelOption[];
}
