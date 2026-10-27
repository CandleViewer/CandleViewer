import { useEffect, useRef, useState, type JSX, type ReactNode } from "react";
import { useLocation } from "react-router";
import type { Me } from "../../shell/bootstrap/store.js";
import { useShellSelector } from "../../shell/useShellSelector.js";
import { bindingFor } from "../../keymap/keymap";
import { sessionApi, SIGN_OUT_FAILED, type SessionApi } from "../session/sessionApi";
import { announce, forget } from "./announcer";
import { envBadgeName } from "./TopBarEnvBadge";
import { TopBar } from "./TopBar";

const ENV_ROUTE_KEY = "env:route"; // one message per navigation

/**
 * CMP-072's container (#304 S2) on `useShellSelector`: the environment (`unknown` is ENV UNKNOWN,
 * never a default), `/me`'s name and role, and Sign out by SCR-005's path, `POST /auth/logout` then
 * `endSession()`; a logout that revoked nothing keeps the session and says so. No `global.palette`
 * handler exists before E10-S03, so search stays T2. A route change announces the badge politely
 * through the shell announcer (`14` SCR-010 A11y; E10-D03 §3.5).
 */
export function TopBarSlot({
  connection,
  api = sessionApi,
}: {
  readonly connection: ReactNode;
  readonly api?: Pick<SessionApi, "signOut" | "endSession">;
}): JSX.Element {
  const env = useShellSelector((s) => s.environment);
  const name = useShellSelector((s) => {
    // a /me without `user` (a stub, a malformed answer) shows no name and never crashes the shell
    const user: Partial<Me["user"]> | undefined = s.me?.user;
    return user?.display_name ?? user?.username ?? null;
  });
  const role = useShellSelector((s) => s.me?.role ?? null);
  const [signOut, setSignOut] = useState({ busy: false, failed: false });
  const { pathname } = useLocation();
  const previous = useRef(pathname);
  useEffect(() => {
    if (previous.current === pathname) return;
    previous.current = pathname;
    forget(ENV_ROUTE_KEY);
    announce("polite", envBadgeName(env), ENV_ROUTE_KEY);
  }, [pathname, env]);
  const onSignOut = (): void => {
    if (signOut.busy) return;
    setSignOut({ busy: true, failed: false });
    void api.signOut().then((gone) => {
      if (gone) return api.endSession();
      setSignOut({ busy: false, failed: true });
      forget("signout:failed");
      announce("assertive", SIGN_OUT_FAILED, "signout:failed");
    });
  };

  return (
    <TopBar
      env={env}
      user={name === null || role === null ? null : { name, role }}
      connection={connection}
      searchHint={bindingFor("global.palette")}
      onSignOut={onSignOut}
      signingOut={signOut.busy}
      signOutFailed={signOut.failed}
    />
  );
}
