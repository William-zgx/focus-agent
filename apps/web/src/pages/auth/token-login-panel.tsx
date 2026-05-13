import { type FormEvent } from "react";

import { type LoginSubmitMode } from "./login-page-types";

export function TokenLoginPanel({
  authReady,
  clearStoredToken,
  onTokenSubmit,
  setShowToken,
  setToken,
  showToken,
  submitting,
  token,
}: {
  authReady: boolean;
  clearStoredToken: () => void;
  onTokenSubmit: (event: FormEvent<HTMLFormElement>) => Promise<void>;
  setShowToken: (value: (current: boolean) => boolean) => void;
  setToken: (value: string) => void;
  showToken: boolean;
  submitting: LoginSubmitMode | null;
  token: string;
}) {
  const isSubmitDisabled = !authReady || Boolean(submitting);

  return (
    <div className="fa-auth-advanced">
      <button onClick={() => setShowToken((value) => !value)} type="button">
        使用 Bearer Token
      </button>
      {showToken ? (
        <form className="fa-auth-form" onSubmit={onTokenSubmit}>
          <label>
            Access token
            <textarea
              onChange={(event) => setToken(event.target.value)}
              rows={4}
              spellCheck={false}
              value={token}
            />
          </label>
          <div className="fa-auth-actions">
            <button className="fa-auth-button" disabled={isSubmitDisabled || !token.trim()} type="submit">
              {!authReady ? "准备中..." : submitting === "token" ? "验证中..." : "继续"}
            </button>
            <button
              className="fa-auth-button"
              disabled={isSubmitDisabled}
              onClick={() => {
                setToken("");
                clearStoredToken();
              }}
              type="button"
            >
              清空
            </button>
          </div>
        </form>
      ) : null}
    </div>
  );
}
