# Registry deployment

This project uses Hardhat 3, its local EVM, and the Mocha/Ethers toolbox. The
contract compiles with Solidity 0.8.20. Local tests never contact a public
network or spend testnet funds.

## Local compile and test

```powershell
npm install
npm run contract:compile
npm run contract:test
```

## Sepolia deployment

Sepolia is the configured public deployment target (chain ID `11155111`). Set
the RPC endpoint and a dedicated, funded **testnet-only** private key in the
process environment; do not put either value in a tracked file. The root
`.env.example` documents these names but contains no secrets.

```powershell
$env:RPC_URL="https://your-sepolia-rpc.example"
$env:PRIVATE_KEY="0x..."
npm run contract:deploy:sepolia
```

The script refuses any chain other than Sepolia, waits for a successful
deployment receipt, prints the transaction and address, and writes the address
to `contracts/deployed_address.txt` for the shared pipeline client.

As of 2026-09-05, ethereum.org recommends Sepolia for application development
and lists several faucets. Faucet availability is external and can change, so
check the current ethereum.org networks page immediately before funding.

## Phase 6 Python client and IPFS pinning

Claim JSON is pinned through Pinata's `pinJSONToIPFS` endpoint using CIDv1.
Create a narrowly scoped Pinata JWT with `pinJSONToIPFS` permission, then keep
it in `PINATA_JWT`. `IPFS_API_KEY` is accepted as a compatibility fallback.

```powershell
python -m pip install -e ./pipeline
$env:PINATA_JWT="..."
```

`provenance_pipeline.chain.workflow.pin_and_anchor_claim(claim)` validates and
pins the complete claim, computes the Phase 1 body-only fingerprint, sends
`Registry.anchor`, and returns the confirmed Web3 transaction receipt. The
chain client reads the contract address from `CONTRACT_ADDRESS`,
`contracts/deployed_address.txt` in an editable checkout, or its packaged
Sepolia default.

The live pin-and-anchor test is deliberately opt-in:

```powershell
$env:RUN_PIN_ANCHOR_INTEGRATION="1"
python -m pytest tests/test_pin_anchor_integration.py -m integration -q
```

## Independent re-verification

Anyone with only a saved claim and the public contract address can recompute
the local fingerprint, read Registry through a public Sepolia RPC, fetch the
pinned claim through the public IPFS gateway, and compare all three values:

```powershell
python scripts/reverify.py --claim path/to/claim.json --contract 0x...
```

This command is read-only and requires no wallet key, search key, face model,
or Pinata credential. For reliability-sensitive use, set `RPC_URL` and/or
`IPFS_GATEWAY_URL` to infrastructure you control.
