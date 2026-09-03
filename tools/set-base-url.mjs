/*
 * Stamps your hosting URL into the manifest.
 *
 * Usage:
 *   node tools/set-base-url.mjs https://yourname.github.io/outlook-invite-addin
 *
 * Reads manifest.xml (the template with __BASE_URL__ placeholders) and writes
 * manifest.built.xml with the placeholders replaced. Sideload manifest.built.xml.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const base = (process.argv[2] || "").replace(/\/+$/, "");
if (!base || !/^https:\/\//i.test(base)) {
  console.error("Provide an HTTPS base URL, e.g.:");
  console.error("  node tools/set-base-url.mjs https://yourname.github.io/outlook-invite-addin");
  process.exit(1);
}

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const template = readFileSync(join(root, "manifest.xml"), "utf8");
const built = template.replaceAll("__BASE_URL__", base);
writeFileSync(join(root, "manifest.built.xml"), built);
console.log("Wrote manifest.built.xml with base URL:", base);
