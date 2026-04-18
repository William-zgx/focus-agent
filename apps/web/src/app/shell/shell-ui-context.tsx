import {
  createContext,
  type PropsWithChildren,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

export type LanguagePreference = "en" | "zh";
export type ThemePreference = "system" | "light" | "dark";
export type ColorPreference = "white" | "blue" | "mint" | "sunset" | "graphite";

interface ShellStatus {
  tone: "info" | "success" | "warn" | "danger";
  text: string;
}

interface ShellUiContextValue {
  languagePreference: LanguagePreference;
  themePreference: ThemePreference;
  colorPreference: ColorPreference;
  setLanguagePreference: (value: LanguagePreference) => void;
  setThemePreference: (value: ThemePreference) => void;
  setColorPreference: (value: ColorPreference) => void;
  shellStatus: ShellStatus | null;
  setShellStatus: (status: ShellStatus | null, options?: { autoClearMs?: number }) => void;
  createBranch: (options?: { parentThreadId?: string }) => Promise<void>;
  isCreatingBranch: boolean;
  isChineseUi: boolean;
}

const ShellUiContext = createContext<ShellUiContextValue | null>(null);

export function ShellUiProvider({
  children,
  value,
}: PropsWithChildren<{ value: Omit<ShellUiContextValue, "isChineseUi"> }>) {
  const contextValue = useMemo(
    () => ({
      ...value,
      isChineseUi: value.languagePreference === "zh",
    }),
    [value],
  );

  return <ShellUiContext.Provider value={contextValue}>{children}</ShellUiContext.Provider>;
}

export function useShellUi() {
  const context = useContext(ShellUiContext);
  if (!context) {
    throw new Error("useShellUi must be used within ShellUiProvider");
  }
  return context;
}

export function useTransientShellStatus(
  initial: ShellStatus | null = null,
): [ShellStatus | null, ShellUiContextValue["setShellStatus"]] {
  const [status, setStatus] = useState<ShellStatus | null>(initial);
  const clearTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (clearTimerRef.current !== null) {
        window.clearTimeout(clearTimerRef.current);
      }
    };
  }, []);

  function setShellStatus(next: ShellStatus | null, options?: { autoClearMs?: number }) {
    if (clearTimerRef.current !== null) {
      window.clearTimeout(clearTimerRef.current);
      clearTimerRef.current = null;
    }
    setStatus(next);
    if (next && options?.autoClearMs) {
      clearTimerRef.current = window.setTimeout(() => {
        setStatus(null);
        clearTimerRef.current = null;
      }, options.autoClearMs);
    }
  }

  return [status, setShellStatus];
}
