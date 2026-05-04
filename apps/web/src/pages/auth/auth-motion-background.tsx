import { type ReactNode } from "react";

import { LOGIN_MOTION_ORBS } from "./auth-page-data";

function AuthMotionCanvas({ variant }: { variant: "account" | "login" }) {
  return (
    <div className="fa-auth-motion-canvas" aria-hidden="true">
      {variant === "account" ? (
        <>
          <span className="fa-auth-motion-mesh" />
          <span className="fa-auth-motion-vignette" />
          <span className="fa-auth-motion-grid-line" />
          <span className="fa-auth-motion-bubble fa-auth-motion-bubble-one" />
          <span className="fa-auth-motion-bubble fa-auth-motion-bubble-two" />
          <span className="fa-auth-motion-ripple" />
        </>
      ) : (
        <>
          <span className="fa-auth-motion-vignette" />
          <span className="fa-auth-motion-scanline" />
          <span className="fa-auth-motion-grid-line" />
          <span className="fa-auth-motion-ripple" />
          <span className="fa-auth-motion-bubble fa-auth-motion-bubble-one" />
          <span className="fa-auth-motion-bubble fa-auth-motion-bubble-two" />
          <span className="fa-auth-motion-mesh" />
        </>
      )}
    </div>
  );
}

function FloatingOrbs() {
  return (
    <div className="fa-auth-floating-orbs" aria-hidden="true">
      {LOGIN_MOTION_ORBS.map((orb) => (
        <span className={`fa-auth-orb ${orb.className}`} key={orb.className} />
      ))}
    </div>
  );
}

export function LoginPageShell({
  advanced,
  children,
  motionVariant,
}: {
  advanced?: ReactNode;
  children: ReactNode;
  motionVariant: "account" | "login";
}) {
  return (
    <div className="fa-auth-page">
      <section className="fa-auth-panel fa-auth-login-panel">
        <AuthMotionCanvas variant={motionVariant} />
        <FloatingOrbs />
        <div className="fa-auth-login-shell">{children}</div>
        {advanced}
      </section>
    </div>
  );
}
