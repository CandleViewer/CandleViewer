// Fixtures for cv-ws-no-credential-log-ts (E17-X02, SR-122).
declare const token: string;
declare const accessToken: string;
declare const authorization: string;
declare const authHeader: string;
declare const auth_header: string;
declare const bearer: string;
declare const cookie: string;
declare const secret: string;
declare const secretKey: string;
declare const msg: { accessToken: string; p: { token: string }; id: string; code: string };
declare const headers: Headers;
declare const plain: Record<string, string>;
declare const a: number;
declare const b: number;
declare const TOKEN_WAIT_MS: number;
declare const tokenExpiresAtMs: number;
declare const accessTokenTtlMs: number;

console.log(token); // ruleid: cv-ws-no-credential-log-ts
console.error("auth failed", accessToken); // ruleid: cv-ws-no-credential-log-ts
console.warn(msg.accessToken); // ruleid: cv-ws-no-credential-log-ts
console.info("auth", msg.p.token); // ruleid: cv-ws-no-credential-log-ts
console.debug(`auth ${token}`); // ruleid: cv-ws-no-credential-log-ts
console.error("auth", { token }); // ruleid: cv-ws-no-credential-log-ts
console.log(authorization); // ruleid: cv-ws-no-credential-log-ts
console.log("handshake", authHeader); // ruleid: cv-ws-no-credential-log-ts
console.log("handshake", auth_header); // ruleid: cv-ws-no-credential-log-ts
console.log(bearer); // ruleid: cv-ws-no-credential-log-ts
console.log(cookie); // ruleid: cv-ws-no-credential-log-ts
console.log(secret); // ruleid: cv-ws-no-credential-log-ts
console.log(secretKey); // ruleid: cv-ws-no-credential-log-ts
console.error("auth", String(token)); // ruleid: cv-ws-no-credential-log-ts
console.error("auth", token.slice(0, 6)); // ruleid: cv-ws-no-credential-log-ts
console.log(plain["authorization"]); // ruleid: cv-ws-no-credential-log-ts
console.log("auth", msg.p["token"]); // ruleid: cv-ws-no-credential-log-ts
console.log(headers.get("Authorization")); // ruleid: cv-ws-no-credential-log-ts
console.log(headers.get("cookie")); // ruleid: cv-ws-no-credential-log-ts
console.table({ accessToken }); // ruleid: cv-ws-no-credential-log-ts
console.count(accessToken); // ruleid: cv-ws-no-credential-log-ts
console.assert(token.length > 0, "auth", authorization); // ruleid: cv-ws-no-credential-log-ts
console.log("auth", token.length, token); // ruleid: cv-ws-no-credential-log-ts
console.log("auth", (token + "x").length, token ?? ""); // ruleid: cv-ws-no-credential-log-ts

console.error("auth", token.length); // ok: cv-ws-no-credential-log-ts
console.error("auth", token?.length); // ok: cv-ws-no-credential-log-ts
console.error("auth", Boolean(token)); // ok: cv-ws-no-credential-log-ts
console.error("auth", !token); // ok: cv-ws-no-credential-log-ts
console.error("auth", token == null); // ok: cv-ws-no-credential-log-ts
console.error("auth", token != null); // ok: cv-ws-no-credential-log-ts
console.error("auth", token === null); // ok: cv-ws-no-credential-log-ts
console.error("auth", token !== null); // ok: cv-ws-no-credential-log-ts
console.error("auth", token === undefined); // ok: cv-ws-no-credential-log-ts
console.error("auth", token !== undefined); // ok: cv-ws-no-credential-log-ts
console.error("auth", typeof token); // ok: cv-ws-no-credential-log-ts
send({ token }); // ok: cv-ws-no-credential-log-ts
console.error("auth", token === ""); // ok: cv-ws-no-credential-log-ts
console.error("auth", token !== "", token != "", token == ""); // ok: cv-ws-no-credential-log-ts
console.error("auth", { n: token.length }); // ok: cv-ws-no-credential-log-ts
console.error(`len ${token.length}`); // ok: cv-ws-no-credential-log-ts
console.error("auth", token.length > 0 ? "set" : "unset"); // ok: cv-ws-no-credential-log-ts
console.error("auth", { at: tokenExpiresAtMs, ttl: accessTokenTtlMs, wait: TOKEN_WAIT_MS }); // ok: cv-ws-no-credential-log-ts
console.log("ws ping lag", (a - b) * 1000); // ok: cv-ws-no-credential-log-ts
console.log("ws ping", (a || b).toFixed()); // ok: cv-ws-no-credential-log-ts
console.error("[ws] client-bug error", msg.id, msg.code); // ok: cv-ws-no-credential-log-ts
console.error("auth failed", "token_expired"); // ok: cv-ws-no-credential-log-ts
console.warn("authorization header missing"); // ok: cv-ws-no-credential-log-ts
console.log(plain["user_id"]); // ok: cv-ws-no-credential-log-ts
console.log(headers.get("content-type")); // ok: cv-ws-no-credential-log-ts
console.table({ a: 1 }); // ok: cv-ws-no-credential-log-ts
