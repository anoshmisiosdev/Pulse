import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = path.join(root, "dist");
const html = await readFile(path.join(dist, "index.html"), "utf8");
const entries = [...html.matchAll(/<script[^>]+src="([^"]+\.js)"/g)].map((match) => match[1]);
let total = 0;
for (const entry of entries) {
  const bytes = await readFile(path.join(dist, entry.replace(/^\//, "")));
  total += gzipSync(bytes).byteLength;
}
const social = await stat(path.join(dist, "churnary-social-card.png"));
const limit = 150 * 1024;
if (total > limit) throw new Error(`Initial JavaScript is ${(total / 1024).toFixed(1)} KB gzip; budget is 150 KB.`);
if (social.size === 0) throw new Error("Social card is empty.");
console.log(`Initial JavaScript: ${(total / 1024).toFixed(1)} KB gzip (budget: 150 KB).`);
