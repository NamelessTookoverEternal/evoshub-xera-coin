// Mount-point awareness. Standalone (evosdata.xyz) BASE_URL is "/"; when the
// app is built for the Hub (VITE_BASE_PATH=/evosdata/) it is "/evosdata/".
// Every in-app route/link goes through these two helpers so the same source
// works at both mount points.
const RAW = (import.meta.env.BASE_URL || "/");
export const BASE = RAW.endsWith("/") ? RAW : RAW + "/";           // "/" or "/evosdata/"
const PREFIX = BASE === "/" ? "" : BASE.slice(0, -1);               // "" or "/evosdata"

export const IS_HUB_MOUNT = __HUB_MOUNT__;

/** "/shop" -> "/evosdata/shop" (or "/shop" standalone). */
export const withBase = (path = "/") => {
  const p = path.startsWith("/") ? path : `/${path}`;
  return PREFIX + p;
};

/** "/evosdata/shop" -> "/shop"; "/evosdata" -> "/". Standalone: unchanged. */
export const stripBase = (pathname = "/") => {
  if (PREFIX && (pathname === PREFIX || pathname.startsWith(PREFIX + "/"))) {
    return pathname.slice(PREFIX.length) || "/";
  }
  return pathname || "/";
};

/** Public-folder asset URL, e.g. asset("evosdata.png"). */
export const asset = (name) => BASE + name.replace(/^\//, "");
