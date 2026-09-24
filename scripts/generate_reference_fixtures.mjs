// Generate reference attack-rating fixtures using Tom Clark's TypeScript calculator
// (https://github.com/ThomasJClark/elden-ring-weapon-calculator), which is widely
// used and matches in-game AR. Our Python implementation is tested against these.
//
// Usage (Node >= 22.6 for --experimental-strip-types):
//   git clone --depth 1 https://github.com/ThomasJClark/elden-ring-weapon-calculator ref
//   node --experimental-strip-types scripts/generate_reference_fixtures.mjs ref \
//        src/erbuild/data/regulation-vanilla-v1.17.json tests/fixtures/reference_ar.json

import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [refDir, dataPath, outPath, nCasesArg] = process.argv.slice(2);
const nCases = Number(nCasesArg ?? 3000);

const { decodeRegulationData } = await import(
  pathToFileURL(resolve(refDir, "src/regulationData.ts")).href
);
const { default: getWeaponAttack } = await import(
  pathToFileURL(resolve(refDir, "src/calculator/calculator.ts")).href
);

const weapons = decodeRegulationData(JSON.parse(readFileSync(dataPath, "utf8")));

// Deterministic PRNG (mulberry32) so fixtures are reproducible.
let seed = 1234567;
function rand() {
  seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
}
const randInt = (lo, hi) => lo + Math.floor(rand() * (hi - lo + 1));

// Bias stats toward interesting regions: around requirements and soft caps.
const interesting = [1, 8, 10, 11, 12, 15, 16, 17, 18, 19, 20, 25, 30, 40, 45, 50, 55, 60, 70, 80, 90, 99];
function randomStat(req) {
  const r = rand();
  if (r < 0.25 && req) return Math.max(1, Math.min(99, req + randInt(-2, 1)));
  if (r < 0.5) return interesting[randInt(0, interesting.length - 1)];
  return randInt(1, 99);
}

const cases = [];
for (let i = 0; i < nCases; i++) {
  const weapon = weapons[randInt(0, weapons.length - 1)];
  const attributes = {};
  for (const a of ["str", "dex", "int", "fai", "arc"]) {
    attributes[a] = randomStat(weapon.requirements[a]);
  }
  const upgradeLevel = randInt(0, weapon.attack.length - 1);
  const twoHanding = rand() < 0.4;
  const result = getWeaponAttack({ weapon, attributes, twoHanding, upgradeLevel });
  cases.push({
    weapon: weapon.variant ? `${weapon.name} (${weapon.variant})` : weapon.name,
    attributes,
    upgrade: upgradeLevel,
    twoHanding,
    attackPower: result.attackPower,
    ineffectiveAttributes: result.ineffectiveAttributes,
  });
}

writeFileSync(outPath, JSON.stringify({ source: "ThomasJClark/elden-ring-weapon-calculator", cases }));
console.log(`Wrote ${cases.length} cases to ${outPath}`);
