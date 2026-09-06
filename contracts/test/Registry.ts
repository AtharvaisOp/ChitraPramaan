import { strict as assert } from "node:assert";

import { network } from "hardhat";
import { beforeEach, describe, it } from "mocha";


const { ethers } = await network.create();

describe("Registry", function () {
  const fingerprint = ethers.id("phase-5-fixture");
  const uri = "ipfs://fixture-claim";

  let registry: Awaited<ReturnType<typeof ethers.deployContract>>;

  beforeEach(async function () {
    registry = await ethers.deployContract("Registry");
    await registry.waitForDeployment();
  });

  it("returns exists=false for an unanchored fingerprint", async function () {
    const [exists, submitter, timestamp, storedUri] =
      await registry.verify(fingerprint);

    assert.equal(exists, false);
    assert.equal(submitter, ethers.ZeroAddress);
    assert.equal(timestamp, 0n);
    assert.equal(storedUri, "");
  });

  it("anchors once and verifies the complete record", async function () {
    const [signer] = await ethers.getSigners();
    const transaction = await registry.anchor(fingerprint, uri);
    const receipt = await transaction.wait();
    assert.ok(receipt);

    const block = await ethers.provider.getBlock(receipt.blockNumber);
    assert.ok(block);

    const [exists, submitter, timestamp, storedUri] =
      await registry.verify(fingerprint);
    assert.equal(exists, true);
    assert.equal(submitter, await signer.getAddress());
    assert.equal(timestamp, BigInt(block.timestamp));
    assert.equal(storedUri, uri);
  });

  it("reverts a second anchor for the same fingerprint", async function () {
    await (await registry.anchor(fingerprint, uri)).wait();

    await assert.rejects(
      registry.anchor(fingerprint, "ipfs://replacement"),
      /already anchored/,
    );
  });
});
