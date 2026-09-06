import hardhatToolboxMochaEthersPlugin from "@nomicfoundation/hardhat-toolbox-mocha-ethers";
import { configVariable, defineConfig } from "hardhat/config";


export default defineConfig({
  plugins: [hardhatToolboxMochaEthersPlugin],
  paths: {
    sources: "./contracts",
    tests: {
      mocha: "./contracts/test",
    },
  },
  solidity: {
    version: "0.8.20",
    settings: {
      optimizer: {
        enabled: true,
        runs: 200,
      },
    },
  },
  networks: {
    sepolia: {
      type: "http",
      chainType: "l1",
      chainId: 11_155_111,
      url: configVariable("RPC_URL"),
      accounts: [configVariable("PRIVATE_KEY")],
    },
  },
});
