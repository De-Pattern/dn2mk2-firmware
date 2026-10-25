/* DN2 mod patcher: builds the mod in Python (Pyodide) off the page's thread.
 * In:  {zipUrl, zipSha, files: {dn2, dt2, md}: {name, bytes}}
 * Out: {log: text} ... then {done: bytes} or {error: text} */
const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.27.7/full/";
importScripts(PYODIDE + "pyodide.js");

let py = null;

async function hex(buf) {
  const h = await crypto.subtle.digest("SHA-256", buf);
  return [...new Uint8Array(h)].map(b => b.toString(16).padStart(2, "0")).join("");
}

self.onmessage = async (e) => {
  const { zipUrl, zipSha, files } = e.data;
  const log = (t) => self.postMessage({ log: t });
  try {
    if (!py) {
      log("Loading Python (Pyodide, about 10 MB, once)...");
      py = await loadPyodide({ indexURL: PYODIDE });
      py.setStdout({ batched: log });
      py.setStderr({ batched: log });
    }
    log("Fetching the mod's build code (" + zipUrl + ")...");
    const r = await fetch(zipUrl, { cache: "no-cache" });
    if (!r.ok) throw new Error("could not fetch " + zipUrl + " (" + r.status + ")");
    const zip = new Uint8Array(await r.arrayBuffer());
    if ((await hex(zip)) !== zipSha) throw new Error("the build code's sha256 is not the one listed; stopping");
    const run = "/run" + Date.now();
    py.FS.mkdirTree(run + "/in");
    py.FS.mkdirTree(run + "/code");
    py.unpackArchive(zip, "zip", { extractDir: run + "/code" });
    for (const k of ["dn2", "dt2", "md"]) py.FS.writeFile(run + "/in/" + k, files[k].bytes);
    log("Building (a few minutes; the page stays usable)...");
    py.globals.set("RUN", run);
    py.runPython(`
import sys, os, pathlib
for m in [m for m in sys.modules if m == "dnfw" or m.startswith("dnfw.") or m == "dn2patch"]:
    del sys.modules[m]
sys.path = [p for p in sys.path if not p.startswith("/run")]
sys.path.insert(0, RUN + "/code")
import dn2patch
dn2patch.WORK = pathlib.Path(RUN + "/work")
SHA = dn2patch.build(RUN + "/in/dn2", RUN + "/in/dt2", RUN + "/in/md", RUN + "/out.syx")
`);
    const out = py.FS.readFile(run + "/out.syx");
    self.postMessage({ done: out }, [out.buffer]);
  } catch (err) {
    let msg = String(err && err.message || err);
    const m = msg.match(/PatchError: (.*)/);
    if (m) msg = m[1];
    else if (msg.includes("Traceback")) msg = msg.trim().split("\n").slice(-1)[0];
    self.postMessage({ error: msg });
  }
};
