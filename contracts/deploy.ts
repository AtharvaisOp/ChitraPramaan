import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { network } from "hardhat";


const SEPOLIA_CHAIN_ID = 11_155_111n;

async function main(): Promise<void> {
  if (!process.env.RPC_URL || !process.env.PRIVATE_KEY) {
    throw new Error("RPC_URL and PRIVATE_KEY must both be set");
  }

  const { ethers, networkName } = await network.connect();
  const chain = await ethers.provider.getNetwork();
  if (chain.chainId !== SEPOLIA_CHAIN_ID) {
    throw new Error(
      `Refusing deployment to ${networkName} (chain ID ${chain.chainId}); ` +
        `expected Sepolia chain ID ${SEPOLIA_CHAIN_ID}`,
    );
  }

  const [deployer] = await ethers.getSigners();
  const balance = await ethers.provider.getBalance(deployer.address);
  if (balance === 0n) {
    throw new Error(`Deployer ${deployer.address} has no Sepolia ETH`);
  }

  console.log(`Deploying Registry to Sepolia from ${deployer.address}...`);
  const registry = await ethers.deployContract("Registry");
  const deployment = registry.deploymentTransaction();
  if (deployment === null) {
    throw new Error("Registry deployment transaction was not created");
  }
  const receipt = await deployment.wait();
  if (receipt === null || receipt.status !== 1) {
    throw new Error("Registry deployment transaction failed");
  }

  const address = await registry.getAddress();
  const chainDirectory = dirname(fileURLToPath(import.meta.url));
  const addressPath = resolve(chainDirectory, "deployed_address.txt");
  await mkdir(chainDirectory, { recursive: true });
  await writeFile(addressPath, `${address}\n`, "utf8");

  console.log(`Registry deployed at ${address}`);
  console.log(`Transaction: ${receipt.hash}`);
  console.log(`Address saved to ${addressPath}`);
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
