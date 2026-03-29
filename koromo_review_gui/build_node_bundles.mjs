import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, "..");
const amaeRoot = path.join(repoRoot, "_external", "amae-koromo-scripts");
const esbuildPath = path.join(amaeRoot, "node_modules", "esbuild", "lib", "main.js");
const { build } = await import(`file:///${esbuildPath.replace(/\\/g, "/")}`);

const outDir = path.join(__dirname, "bundled");
const envShim = path.join(__dirname, "majsoul_env_shim.js");
const envShimPlugin = {
  name: "env-shim",
  setup(buildContext) {
    buildContext.onResolve({ filter: /^\.\/env$/ }, () => ({
      path: envShim,
    }));
  },
};

await build({
  entryPoints: [path.join(__dirname, "fetch_majsoul_record.js")],
  outfile: path.join(outDir, "fetch_majsoul_record.bundle.js"),
  bundle: true,
  platform: "node",
  format: "cjs",
  target: ["node18"],
  plugins: [envShimPlugin],
  logLevel: "info",
});

await build({
  entryPoints: [path.join(__dirname, "decode_majsoul_record.js")],
  outfile: path.join(outDir, "decode_majsoul_record.bundle.js"),
  bundle: true,
  platform: "node",
  format: "cjs",
  target: ["node18"],
  logLevel: "info",
});
