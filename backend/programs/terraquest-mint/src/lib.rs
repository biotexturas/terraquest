// =============================================================================
// TerraQuest Mint — datagram mint program (#[program] surface)
// =============================================================================
//
// Build / publish order:
//   1. programs/terraquest-mint (THIS FILE: types, errors, events, thin
//      wrappers) + mint1.rs (slice-1 bodies) + economy.rs (slice-2 bodies)
//   2. tests/                    (integration tests, T1–T6)
//   3. anchor build && anchor deploy (devnet only)
//
// Spec: b2-mint-program-spec-v2
//
// Custom rule: ONE datagram per capture_hash, device-signed, EXACTLY ONCE,
// EVER. The capture_hash -> datagram / datagram-mint PDA pair is the
// uniqueness gate: a resubmission hits `init` on an existing account and
// Anchor rejects with AccountAlreadyInitialized (T2).
//
// Non-goals (fenced): no genomic data on-chain (desc_ref is a URI pointer),
// no on-chain score verification, no payments/play-layer here, devnet only.
//
// Module split (2026-09-26/27): bodies live in mint1.rs (slice 1) and
// economy.rs (slice 2) so every source file stays independently push-sized.
//
// CI run 7 root cause, encoded here: Anchor 0.31.1's #[program] macro parses
// the FIRST path segment of each handler's Context accounts type and then
// resolves `crate::__client_accounts_<snake(segment)>` plus the bare struct
// name from the crate root (lang/syn/src/parser/program/mod.rs +
// codegen/program/accounts.rs, both verified against v0.31.1 source). So the
// wrappers below use BARE struct names, and the crate-root re-exports bring
// the structs and their derive-generated client modules into place.
//
// =============================================================================

// Crate-root prelude import: declare_id! and #[program] expand at the crate
// root, so the Anchor prelude must be in scope HERE, before declare_id. The
// module-level import alone left the program macro unresolvable (root cause
// of the 60-cascade compile failure in CI run 36271847141).
use anchor_lang::prelude::*;

// TODO: anchor keys sync — declare_id is the on-chain program id. Slice ships
// with a placeholder; the CI keys-sync pass rewrites this + Anchor.toml to
// the generated keypair on every run (idempotent since CI run 7).
declare_id!("CurN8UWQwD1pifo9rhzKLbVrJxNt5jiGDTtpT8h6KskS");

// Slice-1 instruction bodies (initialize/add/remove/mint_datagram) and the
// slice-2 economy (treasury, tax config, faucet, founding).
pub mod economy;
pub mod mint1;

// Anchor 0.31.1 codegen surface at the crate root (see header): the accounts
// structs named in #[program] Context types, plus the derive-generated client
// modules the macro's generated `accounts`/`cpi` mods re-export via
// `crate::__client_accounts_*` paths. Plain imports: the modules are
// pub(crate), mirroring what the old in-module placement provided through the
// macro's own `use self::terraquest_mint::*`.
#[allow(unused_imports)]
use economy::{
    __cpi_client_accounts_faucet_draw, __cpi_client_accounts_init_treasury,
    __cpi_client_accounts_mint_founding_datagram,
    __cpi_client_accounts_open_faucet_account, __cpi_client_accounts_set_economy_params,
    __client_accounts_faucet_draw, __client_accounts_init_treasury,
    __client_accounts_mint_founding_datagram, __client_accounts_open_faucet_account,
    __client_accounts_set_economy_params, FaucetDraw, InitTreasury,
    MintFoundingDatagram, OpenFaucetAccount, SetEconomyParams,
};
#[allow(unused_imports)]
use mint1::{
    __cpi_client_accounts_add_device, __cpi_client_accounts_initialize_config,
    __cpi_client_accounts_mint_datagram, __cpi_client_accounts_remove_device,
    __client_accounts_add_device, __client_accounts_initialize_config,
    __client_accounts_mint_datagram, __client_accounts_remove_device, AddDevice,
    InitializeConfig, MintDatagram, RemoveDevice,
};

#[program]
pub mod terraquest_mint {
    use anchor_lang::prelude::*;
    // Thin wrappers: bodies live in the split modules. Bare struct names in
    // the Context types are load-bearing (first-segment parse, CI run 7).
    use crate::{economy, mint1};
    use crate::economy::{
        FaucetDraw, InitTreasury, MintFoundingDatagram, OpenFaucetAccount,
        SetEconomyParams,
    };
    use crate::mint1::{AddDevice, InitializeConfig, MintDatagram, RemoveDevice};

    // -------------------------------------------------------------------------
    // PDA seed constants
    // -------------------------------------------------------------------------
    pub const CONFIG_SEED: &[u8] = b"global_config";
    pub const DEVICE_SEED: &[u8] = b"device";
    pub const CAPTURE_SEED: &[u8] = b"capture";
    pub const CAPTURE_MINT_SEED: &[u8] = b"capture_mint";
    pub const METADATA_SEED: &[u8] = b"metadata";

    // -------------------------------------------------------------------------
    // Account: GlobalConfig
    // -------------------------------------------------------------------------
    // FORWARD-EXTENSIBLE: economy fields appended in slice 2. The treasury
    // lives in its own PDA ([b"treasury"], see economy.rs); bounty-gate fields
    // stay a post-MVP extension point. The config address never moves (seeds
    // fixed), so extending the schema never broke PDA derivation — and nothing
    // had deployed before the extension (devnet-only lane).
    #[account]
    pub struct GlobalConfig {
        pub authority: Pubkey,
        pub bump: u8,
        // --- slice 2 (economy) — ships inert: 0 / 0 / false ---
        /// Tax on each faucet draw, basis points (<= 10000). Juan's number.
        pub tax_rate_bps: u16,
        /// Per-draw pacing cap in economy-mint units; 0 = faucet disabled.
        pub faucet_max_per_draw: u64,
        /// One-time founding-mint flag; mint_founding_datagram flips it.
        pub founding_minted: bool,
    }

    // -------------------------------------------------------------------------
    // Account: DeviceRecord
    // -------------------------------------------------------------------------
    // PDA seeds: [DEVICE_SEED, device_pubkey]. Sealed by authority-gated
    // add/remove instructions.
    #[account]
    pub struct DeviceRecord {
        pub device: Pubkey,
        pub authority: Pubkey,
        pub added_at: i64,
        pub bump: u8,
    }

    // -------------------------------------------------------------------------
    // Account: Datagram
    // -------------------------------------------------------------------------
    // The capture_hash -> datagram PDA pair enforces uniqueness (T2).
    // Fields are stored exactly as submitted (T1 happy path). Optional
    // geo_tag and desc_ref NEVER affect uniqueness — only capture_hash does.
    //
    // COMPILE CHECKPOINT (item 10): DATAGRAM_SPACE is a manual serialization
    // math sum. Anchor does NOT verify account::space at compile time; the
    // loud failure modes are InsufficientFundsForRent on init, or a noisy
    // serialization error if desc_ref > 192 chars. We prefer the loud
    // failure to silent truncation.
    //
    // Arithmetic:
    //   8  (discriminator) + 32 (capture_hash) + 32 (device) + 8 (timestamp)
    // +  2 (score) + 17 (geo_tag) + 32 (session_ref) + 1 (Option disc)
    // +  4 (String prefix) + 192 (max desc_ref) + 32 (mint) + 1 (bump)
    // = 361 bytes -> padded up to 368 (8-byte alignment)
    pub const DATAGRAM_SPACE: usize = 368;

    #[account]
    pub struct Datagram {
        pub capture_hash: [u8; 32],
        pub device: Pubkey,
        pub timestamp: u64,
        pub score: u16,
        pub geo_tag: GeoTag,
        pub session_ref: [u8; 32],
        pub desc_ref: Option<String>,
        pub mint: Pubkey,
        pub bump: u8,
    }

    // -------------------------------------------------------------------------
    // GeoTag — explicit withheld marker (spec lean B)
    // -------------------------------------------------------------------------
    // Why B (explicit Withheld) beats empty-field: an optional/geo field
    // collapses the honest-withheld case into "didn't fill in the form".
    // Withheld | Disclosed{lat,lon} makes coverage accounting unambiguous.
    // Rig coordinates are never fine-precision on-chain (spec v2).
    #[derive(AnchorSerialize, AnchorDeserialize, Clone, Debug, PartialEq)]
    pub enum GeoTag {
        Withheld,
        Disclosed { latitude: f64, longitude: f64 },
    }

    // -------------------------------------------------------------------------
    // Error codes
    // -------------------------------------------------------------------------
    // Every #[msg] is phrased for a first-time reader so error logs read
    // like a mini-postmortem: what was attempted, which T-attack it maps to.
    #[error_code]
    pub enum ErrorCode {
        #[msg("Unauthorized: only the program authority may manage devices (T6).")]
        Unauthorized,
        #[msg("DeviceNotRegistered: signer is not in the device registry; spoof rejected at the device_record seeds constraint (T4).")]
        DeviceNotRegistered,
        #[msg("InvalidDeviceSignature: ed25519 signature over capture_hash||timestamp||score did not verify against the device key (T3 replay / T5 tamper).")]
        InvalidDeviceSignature,
        #[msg("DescRefTooLong: desc_ref exceeds 192 bytes; this datagram's account space is fixed at DATAGRAM_SPACE.")]
        DescRefTooLong,
        // --- slice 2 (economy) — one #[msg] per gate, same postmortem style ---
        #[msg("RateTooHigh: tax_rate_bps exceeds 10000 (100%); rate is basis points of each faucet draw.")]
        RateTooHigh,
        #[msg("FaucetDisabled: faucet_max_per_draw is 0 — the faucet ships inert until the authority sets a cap via set_economy_params.")]
        FaucetDisabled,
        #[msg("ExceedsDrawCap: requested draw exceeds faucet_max_per_draw (the per-draw pacing gate).")]
        ExceedsDrawCap,
        #[msg("FaucetAmountZero: zero-amount draw rejected — an event with no movement would lie to indexers.")]
        FaucetAmountZero,
        #[msg("FaucetAccountMismatch: token account is not the expected economy-mint ATA owned by the named party; open it with open_faucet_account first.")]
        FaucetAccountMismatch,
        #[msg("FoundingAlreadyMinted: the founding datagram is one-time (founding_minted flag on GlobalConfig); PDA init is the per-hash gate.")]
        FoundingAlreadyMinted,
    }

    // -------------------------------------------------------------------------
    // Events
    // -------------------------------------------------------------------------
    #[event]
    pub struct DatagramMinted {
        pub capture_hash: [u8; 32],
        pub device: Pubkey,
        pub mint: Pubkey,
        pub score: u16,
        pub timestamp: u64,
        pub geo_disclosed: bool,
    }

    // =========================================================================
    // Slice-1 thin wrappers (bodies in mint1.rs — run-5 green, unchanged)
    // =========================================================================

    pub fn initialize_config(ctx: Context<InitializeConfig>) -> Result<()> {
        mint1::initialize_config(ctx)
    }

    pub fn add_device(ctx: Context<AddDevice>, device_key: Pubkey) -> Result<()> {
        mint1::add_device(ctx, device_key)
    }

    pub fn remove_device(ctx: Context<RemoveDevice>) -> Result<()> {
        mint1::remove_device(ctx)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn mint_datagram(
        ctx: Context<MintDatagram>,
        capture_hash: [u8; 32],
        timestamp: u64,
        score: u16,
        session_ref: [u8; 32],
        geo_tag: GeoTag,
        desc_ref: Option<String>,
        signature: [u8; 64],
    ) -> Result<()> {
        mint1::mint_datagram(
            ctx,
            capture_hash,
            timestamp,
            score,
            session_ref,
            geo_tag,
            desc_ref,
            signature,
        )
    }

    // =========================================================================
    // Slice-2 thin wrappers (bodies in economy.rs). Everything here ships
    // inert — economy numbers are Juan's to set via set_economy_params.
    // =========================================================================

    pub fn init_treasury<'info>(
        ctx: Context<'_, '_, '_, 'info, InitTreasury<'info>>,
    ) -> Result<()> {
        economy::init_treasury(ctx)
    }

    pub fn set_economy_params<'info>(
        ctx: Context<'_, '_, '_, 'info, SetEconomyParams<'info>>,
        tax_rate_bps: u16,
        faucet_max_per_draw: u64,
    ) -> Result<()> {
        economy::set_economy_params(ctx, tax_rate_bps, faucet_max_per_draw)
    }

    pub fn open_faucet_account<'info>(
        ctx: Context<'_, '_, '_, 'info, OpenFaucetAccount<'info>>,
    ) -> Result<()> {
        economy::open_faucet_account(ctx)
    }

    pub fn faucet_draw<'info>(
        ctx: Context<'_, '_, '_, 'info, FaucetDraw<'info>>,
        amount: u64,
    ) -> Result<()> {
        economy::faucet_draw(ctx, amount)
    }

    pub fn mint_founding_datagram<'info>(
        ctx: Context<'_, '_, '_, 'info, MintFoundingDatagram<'info>>,
        capture_hash: [u8; 32],
        score: u16,
        desc_ref: String,
    ) -> Result<()> {
        economy::mint_founding_datagram(ctx, capture_hash, score, desc_ref)
    }
}
