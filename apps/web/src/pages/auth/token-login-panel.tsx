import { type FormEvent } from "react";

import { type LoginSubmitMode } from "./login-page-types";

export function TokenLoginPanel({
  clearStoredToken,
  onTokenSubmit,
  setShowToken,
  setToken,
  showToken,
  submitting,
  token,
}: {
  clearStoredToken: () => void;
  onTokenSubmit: (event: FormEvent<HTMLFormElement>) => Promise<void>;
  setShowToken: (value: (current: boolean) => boolean) => void;
  setToken: (value: string) => void;
  showToken: boolean;
  submitting: LoginSubmitMode | null;
  token: string;
}) {
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
            <button className="fa-auth-button" disabled={Boolean(submitting) || !token.trim()} type="submit">
              {submitting === "token" ? "验证中..." : "继续"}
            </button>
            <button
              className="fa-auth-button"
              disabled={Boolean(submitting)}
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
