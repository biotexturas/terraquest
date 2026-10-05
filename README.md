# TerraQuest

**Mapping the intelligence beneath our feet.**

TerraQuest is a DePIN of Open Science Hardware that doubles as a web3 biotic-game console. A TerraScope — a DIY robotic microscope built from open hardware — captures living microbial behavior; an in-browser computer-vision pipeline turns each capture into a **datagram**; the datagram is minted on Solana with device-signed provenance, so anyone can verify where a piece of biological data came from.

## The story

TerraQuest starts from a claim the project keeps returning to: the intelligence beneath our feet is real, measurable, and worth mapping. Soil microbes coordinate, compete, and switch strategy when local resources run out — behavior complex enough to be worth tracking, frame by frame.

The instrument came first. The TerraScope is a DIY robotic microscope built from open hardware — a PCB, 3D-printed parts, a Raspberry Pi — designed so anyone can build their own and point it at a living colony. What it captures becomes a datagram: a signed record of a real biological observation, minted on Solana with device-signed provenance, so anyone can verify where the data came from.

Around that loop a game grew. Players with a TerraScope track colonies at fine grain. Players with a phone and a petri dish explore wider terrain. Players with no hardware at all pick three frames from TerraScope's open collections and run the computer-vision pipeline in the browser. Every run, and every choice a player makes, becomes data the next run learns from. The first datagram — the Ancient Datagram — was minted on devnet on October 4, 2026.

TerraQuest is built by [Biotexturas](https://biotexturas.org), a collective working on decentralized science, art and technology.

## What is in this repository

- `backend/` — the Solana Anchor program (the datagram mint) plus the CV pipeline scripts and analysis. Keys-free copy: no keypair files, no git history carried over. Runs on Solana devnet.
- The **frontend** lives in its own public repository: https://github.com/jekeymer/terraquest-frontend — the player-facing site (static HTML/JS): landing page, TerraScope Observatory, Seek & Track, Knowledge Engrams deck, Alife Ecology sim, Terrain Console, Ecosystem Arena, My workbench.

## The backend

The `backend/` tree is a keys-free mirror of the mint pipeline — a pinned snapshot (110 files, no keypairs, no carried-over git history) of the build that runs the MVP. Three parts:

- **The datagram mint program** (`backend/programs/`, Rust/Anchor). Turns a signed capture into an on-chain datagram under three hard rules:
  - **One datagram per capture hash, ever.** The capture hash — SHA-256 over the exact bytes of the capture — is the unique key. A second mint over the same hash fails on-chain.
  - **Device-signed.** Every mint carries the capturing device's signature, so origin is verified on-chain rather than trusted.
  - **Program-owned treasury.** A treasury PDA is the only account the program moves tokens from; three flows run through it: taxed faucet draws (players), win bounties (arena), and the founding mint. Economy parameters — mint tax (500 bps) and supply cap (1,000,000,000 units) — live in config accounts set by the program authority.
  - The founding mint is gated by a one-time config flag; after the first press it is closed permanently.
- **The CV pipeline** (`backend/cv/`). The analysis that turns frames into scores: Lucas-Kanade optical flow, frame-difference blob tracking, clustering, head-speed scoring. Versioned (`cv-pipeline v0.2`) so every on-chain score can point at the exact code that produced it.
- **The provenance machinery** (`backend/provenance/`). Hashes every frame of the open collections into per-collection manifests and roots — the data behind the Attestations section below.

Supporting pieces: `backend/scripts/` (client and setup scripts), `backend/.github/workflows/` (CI: Anchor build + the T1-T6 test suite — happy path, double-mint, replay, spoof, tamper, rogue device — plus cargo and CV tests, all green before anything ships), pinned build config in `Anchor.toml` / `Cargo.toml`.

Keypair files are deliberately not included anywhere in this repository — the import pipeline hard-fails if a `keys/` path appears in any bundle.

## Attestations

Every claim in the story above is backed by a machine-checkable record, committed in this repository:

**Open-collection provenance — what the game runs on.**

- All 14 collections (12 TerraQuest sections plus video1 and video2), 593 frames.
- `backend/provenance/manifests/` — one manifest per collection; every frame listed with filename, source id, SHA-256, and byte size.
- `backend/provenance/manifests/ROOTS.txt` — one root per collection, plus the global root over all 14:

  `af4471621a30f2bfb8c513bfad3181d223e344e1200f8d853f70c2282b3591d8`

- The complete set was attested by the project steward on 2026-10-05. This is the frozen provenance baseline for the MVP.

**The Ancient Datagram — the first mint.**

- Capture hash `59022e0c72476839737e37c29f98a6cb4ff131d106ce1a9fcd7c6ad765e7fd80`: SHA-256 over the exact bytes of the AVI capture (14,486,308 bytes). The on-chain datagram stores this same value.
- Preservation: those exact bytes live on Arweave (tx `mj6CwfZoDqkvSd_oQQ0WVHuNG4g515F_Y-d6yxkh6DE`); the gateway's signed digest over the stored file equals the capture hash above — the mint and the archive prove the same bytes.
- Mint record (devnet, 2026-10-04): transaction [64w4abEp...EwiZ](https://explorer.solana.com/tx/64w4abEpX1i7oSnkXsNcqCBfeJFnFQSaErs7M8XXMyULQc7FshjYQhMWixUkynUgxePBDxvWjBG9ePw8P5UbEwiZ?cluster=devnet), slot 507391878; the datagram account holds the capture hash plus the reference to the original work; the config flag is byte-verified `true`, closing the founding mint forever; token supply 1, held in the treasury.

**Verify it yourself.**

1. Re-hash any frame; compare with its manifest line.
2. Rebuild the roots from ROOTS.txt; compare the global root.
3. Read the datagram account on devnet; compare its capture hash with the Arweave-stored bytes.

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
