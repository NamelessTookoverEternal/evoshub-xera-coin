const solc = require("solc");
const fs = require("fs");
const path = require("path");

function findImports(importPath) {
  const candidates = [
    path.join(__dirname, "..", "node_modules", importPath),
    path.join(__dirname, "..", importPath),
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) return { contents: fs.readFileSync(c, "utf8") };
  }
  return { error: "File not found: " + importPath };
}

const contractsDir = path.join(__dirname, "..", "contracts");
const files = fs.readdirSync(contractsDir).filter(f => f.endsWith(".sol"));

const sources = {};
for (const f of files) {
  sources[f] = { content: fs.readFileSync(path.join(contractsDir, f), "utf8") };
}

const input = {
  language: "Solidity",
  sources,
  settings: {
    optimizer: { enabled: true, runs: 200 },
    outputSelection: { "*": { "*": ["abi", "evm.bytecode.object"] } },
  },
};

const output = JSON.parse(solc.compile(JSON.stringify(input), { import: findImports }));

let hasError = false;
if (output.errors) {
  for (const err of output.errors) {
    if (err.severity === "error") { hasError = true; console.log("ERROR:", err.formattedMessage); }
    else console.log("WARN:", err.formattedMessage);
  }
}
if (!hasError) {
  console.log("COMPILE OK. Contracts:", Object.keys(output.contracts || {}));
  for (const f of Object.keys(output.contracts || {})) {
    console.log(" -", f, Object.keys(output.contracts[f]));
  }
} else {
  process.exit(1);
}
