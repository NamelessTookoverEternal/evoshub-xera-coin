require("@nomicfoundation/hardhat-toolbox");
require("dotenv").config();
const path = require("path");
const { subtask } = require("hardhat/config");
const { TASK_COMPILE_SOLIDITY_GET_SOLC_BUILD } = require("hardhat/builtin-tasks/task-names");

// Use the solc compiler installed from npm (devDependency `solc`) instead
// of letting Hardhat download it from binaries.soliditylang.org at build
// time. Two reasons:
//   1. It makes builds reproducible and pins the exact compiler alongside
//      every other dependency in package-lock.json, rather than depending
//      on a remote host being reachable and serving the same bytes.
//   2. It lets `npx hardhat test` run in restricted-egress environments
//      (CI sandboxes, this repo's own test environment) where
//      binaries.soliditylang.org isn't reachable.
// Hardhat still verifies the compiler produces the expected output; this
// only changes WHERE the compiler binary comes from, not how it's used.
subtask(TASK_COMPILE_SOLIDITY_GET_SOLC_BUILD, async (args, hre, runSuper) => {
  if (args.solcVersion === "0.8.24") {
    return {
      compilerPath: path.resolve(__dirname, "node_modules", "solc", "soljson.js"),
      isSolcJs: true,
      version: args.solcVersion,
      longVersion: "0.8.24",
    };
  }
  return runSuper();
});

const { DEPLOYER_PRIVATE_KEY, BSC_TESTNET_RPC_URL, BSC_MAINNET_RPC_URL, BSCSCAN_API_KEY } = process.env;

/** @type import('hardhat/config').HardhatUserConfig */
module.exports = {
  solidity: {
    version: "0.8.24",
    settings: {
      optimizer: { enabled: true, runs: 200 },
    },
  },
  networks: {
    hardhat: {},
    bscTestnet: {
      url: BSC_TESTNET_RPC_URL || "https://data-seed-prebsc-1-s1.binance.org:8545",
      chainId: 97,
      accounts: DEPLOYER_PRIVATE_KEY ? [DEPLOYER_PRIVATE_KEY] : [],
    },
    bscMainnet: {
      url: BSC_MAINNET_RPC_URL || "https://bsc-dataseed.binance.org",
      chainId: 56,
      accounts: DEPLOYER_PRIVATE_KEY ? [DEPLOYER_PRIVATE_KEY] : [],
    },
  },
  etherscan: {
    apiKey: {
      bscTestnet: BSCSCAN_API_KEY || "",
      bsc: BSCSCAN_API_KEY || "",
    },
  },
};
