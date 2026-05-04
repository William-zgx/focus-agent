import type {
  FocusAgentCreateUserRequest,
  FocusAgentUser,
} from "@focus-agent/web-sdk";
import { type FormEvent, useState } from "react";

import { parseMetadataDraft, splitRoleDraft } from "@/features/admin-users/admin-user-utils";
import { useCreateAdminUser } from "@/features/admin-users/use-admin-users";

type UseAdminUserCreateFormOptions = {
  onCreated: (user: FocusAgentUser) => Promise<void> | void;
};

export function useAdminUserCreateForm(
  options: UseAdminUserCreateFormOptions,
) {
  const [newUserId, setNewUserId] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [newTenantId, setNewTenantId] = useState("");
  const [newRoles, setNewRoles] = useState("member");
  const [newMetadata, setNewMetadata] = useState("{}");
  const [formError, setFormError] = useState<string | null>(null);
  const createUser = useCreateAdminUser();

  async function handleCreateUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    const parsed = parseMetadataDraft(newMetadata);
    if (parsed.error || !parsed.metadata) {
      setFormError(parsed.error ?? "Metadata JSON is invalid.");
      return;
    }

    const request: FocusAgentCreateUserRequest = {
      user_id: newUserId.trim(),
      display_name: newDisplayName.trim() || undefined,
      email: newEmail.trim() || undefined,
      tenant_id: newTenantId.trim() || undefined,
      status: "active",
      roles: splitRoleDraft(newRoles),
      metadata: parsed.metadata,
    };

    try {
      const user = await createUser.mutateAsync(request);
      setNewUserId("");
      setNewDisplayName("");
      setNewEmail("");
      setNewTenantId("");
      setNewRoles("member");
      setNewMetadata("{}");
      await options.onCreated(user);
    } catch (error: unknown) {
      setFormError(error instanceof Error ? error.message : "Failed to create user.");
    }
  }

  return {
    createUser,
    formError,
    handleCreateUser,
    newDisplayName,
    newEmail,
    newMetadata,
    newRoles,
    newTenantId,
    newUserId,
    setFormError,
    setNewDisplayName,
    setNewEmail,
    setNewMetadata,
    setNewRoles,
    setNewTenantId,
    setNewUserId,
  };
}
