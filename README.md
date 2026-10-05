# TerraQuest

**Mapping the intelligence beneath our feet.**

TerraQuest is a DePIN of Open Science Hardware that doubles as a web3 biotic-game console. A TerraScope — a DIY robotic microscope built from open hardware — captures living microbial behavior; an in-browser computer-vision pipeline turns each capture into a **datagram**; the datagram is minted on Solana with device-signed provenance, so anyone can verify where a piece of biological data came from.

Built by [Biotexturas](https://biotexturas.org).

## What is in this repository

- `backend/` — the Solana Anchor program (the datagram mint) plus the CV pipeline scripts and analysis. Keys-free copy: no keypair files, no git history carried over. Runs on Solana devnet.
- The **frontend** lives in its own public repository: https://github.com/jekeymer/terraquest-frontend — the player-facing site (static HTML/JS): landing page, TerraScope Observatory, Seek & Track, Knowledge Engrams deck, Alife Ecology sim, Terrain Console, Ecosystem Arena, My workbench.

## What the MVP does

1. **Observe** — TerraScope Observatory holds open collections of real microscope captures. Pick three consecutive frames; no hardware needed.
2. **Investigate** — Seek & Track runs the computer-vision pipeline right in the browser: flow fields, clusters, head speed. Adjust a parameter, run again, keep the run you like. Every run is logged, so the machine learns from what players choose.
3. **Prove** — mint a run as a datagram: connect a Solana wallet (devnet), sign, and the record lands on-chain — identifier, content hash, contributor signature. The heavy data stays off-chain; anyone can verify its origin.
4. **Play** — nine Knowledge Engrams, the Alife Ecology sim, the Terrain Console, and arena battles built from the same data.

## Live links

- MVP test site: https://microbes.biotexturas.org
- Reference build: https://sites.hellominds.ai/b1/biotic-model/index.html
- Construct your own TerraScope: https://sites.hellominds.ai/b0/terrascope/index.html
- Frontend source: https://github.com/jekeymer/terraquest-frontend

## Running the frontend

Static site, no build step:

```bash
git clone https://github.com/jekeymer/terraquest-frontend
cd terraquest-frontend
python3 -m http.server 8000
# open http://localhost:8000
```

## Building the backend

Requires Rust, the Solana CLI, and Anchor:

```bash
cd backend
anchor build
anchor deploy --provider.cluster devnet
```

Keypair files are deliberately NOT included. Deployment uses your own deployer key.

## On-chain facts (devnet)

- Program: `CurN8UWQwD1pifo9rhzKLbVrJxNt5jiGDTtpT8h6KskS`
- Founding mint (2026-10-04): [signature 64w4abEp...EwiZ](https://explorer.solana.com/tx/64w4abEpX1i7oSnkXsNcqCBfeJFnFQSaErs7M8XXMyULQc7FshjYQhMWixUkynUgxePBDxvWjBG9ePw8P5UbEwiZ?cluster=devnet)
- Capture hash (SHA-256 of the Ancient Datagram capture): `59022e0c72476839737e37c29f98a6cb4ff131d106ce1a9fcd7c6ad765e7fd80`
- Preserved on Arweave: tx `mj6CwfZoDqkvSd_oQQ0WVHuNG4g515F_Y-d6yxkh6DE`

## Prior work

The provenance loop — capture, device-signed hash, on-chain verification — first shipped in **TerraGenesis** on Avalanche Fuji testnet (contract `0xF7497fC600Bd4877A0Ad3C0B3BBBEE80b9038477`). TerraQuest is the Solana-native evolution.