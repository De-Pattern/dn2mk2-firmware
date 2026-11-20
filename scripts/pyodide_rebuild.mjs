// v0.65 (docs/packer.md): the patcher's build under Pyodide in node, from this tree, as the
// browser runs it (the WebAssembly planner). Needs `npm install pyodide@0.27.7` beside it:
//   node scripts/pyodide_rebuild.mjs SRC DN2PATCH DN2 DT2 MD MNM VERSION   -> prints SHA=...
import { loadPyodide } from "pyodide";
const [src, patch, dn2, dt2, md, mnm, ver] = process.argv.slice(2);
const py = await loadPyodide();
py.FS.mkdirTree("/run/code"); py.FS.mkdirTree("/host");
py.FS.mount(py.FS.filesystems.NODEFS, { root: "/" }, "/host");
py.globals.set("SRC", src); py.globals.set("PATCH", patch);
py.globals.set("A", [dn2, dt2, md, mnm]); py.globals.set("VER", ver);
const t = Date.now();
py.runPython(`
import shutil, sys, pathlib, hashlib, os
shutil.copytree("/host" + SRC + "/dnfw", "/run/code/dnfw", ignore=shutil.ignore_patterns("__pycache__"))
shutil.copy("/host" + PATCH, "/run/code/dn2patch.py")
open("/run/VERSION","w").write(VER + "\\n")
sys.path.insert(0, "/run/code")
import dn2patch
dn2patch.WORK = pathlib.Path("/run/work")
a = ["/host" + x for x in A]
print("SHA=" + dn2patch.build(a[0], a[1], a[2], "/run/out.syx", mnm=a[3]))
from dnfw.codec import aplibopt
print("backend", aplibopt.backend())
`);
console.log("seconds", (Date.now() - t) / 1000);
