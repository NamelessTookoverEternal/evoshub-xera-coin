const { ethers } = require("hardhat");

// Leaf = keccak256(keccak256(abi.encode(leafIndex, account, amount))) — matches
// XeraMigrationClaim.claim()'s `keccak256(bytes.concat(keccak256(abi.encode(...))))`.
function hashLeaf(leafIndex, account, amount) {
  const inner = ethers.keccak256(
    ethers.AbiCoder.defaultAbiCoder().encode(["uint256", "address", "uint256"], [leafIndex, account, amount])
  );
  return ethers.keccak256(inner);
}

function hashPair(a, b) {
  const [x, y] = BigInt(a) < BigInt(b) ? [a, b] : [b, a];
  return ethers.keccak256(ethers.concat([x, y]));
}

/**
 * Builds a simple binary Merkle tree (OpenZeppelin sorted-pair convention).
 * Returns { root, getProof(index) }.
 */
function buildTree(entries) {
  // entries: [{ leafIndex, account, amount }]
  let level = entries.map((e) => hashLeaf(e.leafIndex, e.account, e.amount));
  const layers = [level];

  while (level.length > 1) {
    const next = [];
    for (let i = 0; i < level.length; i += 2) {
      if (i + 1 < level.length) {
        next.push(hashPair(level[i], level[i + 1]));
      } else {
        next.push(level[i]); // odd one out carries up unchanged
      }
    }
    layers.push(next);
    level = next;
  }

  const root = level[0];

  function getProof(index) {
    const proof = [];
    let idx = index;
    for (let l = 0; l < layers.length - 1; l++) {
      const layer = layers[l];
      const pairIdx = idx % 2 === 0 ? idx + 1 : idx - 1;
      if (pairIdx < layer.length) proof.push(layer[pairIdx]);
      idx = Math.floor(idx / 2);
    }
    return proof;
  }

  return { root, getProof };
}

module.exports = { hashLeaf, buildTree };
