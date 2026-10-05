// =============================================================================
// TerraQuest Mint — Slice 2 (economy: treasury, tax config, faucet, founding)
// =============================================================================
//
// Module split (2026-09-26): bodies live here; lib.rs holds GlobalConfig's
// slice-2 fields, the shared error codes, and five thin #[program] wrappers
// so each source file stays independently push-sized.
//
// Locked rulings implemented (hub 2026-09-25/26 + Juan's DECISIONS):
//   * 3 flows / 1 treasury: taxed player faucet inflow, win-bounty outflow
//     (post-MVP, extension point only), one-time founding mint.
//   * Treasury PDA [b"treasury"] with program-only authority; seed-namespace
//     separation from player vaults [b"vault", player] and capture PDAs.
//   * Every movement emits an Anchor event (FaucetDrawn here; DatagramMinted
//     reused for the founding mint so indexers see one canonical mint event).
//   * Tax rate is a treasury-config param — Juan's number, ships inert at 0.
//   * House mints tax-exempt: the founding mint is a direct deposit to the
//     treasury, no draw and no split, exempt by construction.
//   * No init-if-needed anywhere: open_faucet_account is its own instruction.
//
// DELIBERATE DEFAULTS (devnet, nothing deployed yet; authority-adjustable):
//   * Economy mint: PDA [b"economy_mint"], decimals 6 (structural default,
//     not an economic ruling), mint authority = GlobalConfig PDA — the
//     config-PDA-as-mint-authority rule. Freeze authority burned post-init
//     (same rationale as slice 1: nobody grief-blocks transfers).
//   * Ship inert: tax_rate_bps = 0, faucet_max_per_draw = 0 (disabled),
//     founding_minted = false. Mechanism present, economics dead until Juan
//     sets his numbers via set_economy_params.
//
// =============================================================================

use anchor_lang::prelude::*;
use anchor_spl::associated_token::AssociatedToken;
use anchor_spl::metadata::{self, CreateMetadataAccountsV3, Metadata};
use anchor_spl::metadata::mpl_token_metadata::types::DataV2;
use anchor_spl::token::{self, Mint, MintTo, SetAuthority, Token, TokenAccount};
// Checkpoint 7 (docs.rs anchor-spl 0.31.1): AuthorityType is not re-exported
// from anchor_spl::token — same nested path proven in slice-1 CI run 5.
use anchor_spl::token::spl_token::instruction::AuthorityType;

use crate::terraquest_mint::{
    Datagram, DatagramMinted, ErrorCode, GeoTag, GlobalConfig, CAPTURE_MINT_SEED,
    CAPTURE_SEED, CONFIG_SEED, DATAGRAM_SPACE, METADATA_SEED,
};

/// PDA seeds — own namespace, never overlapping [b"vault", player], device,
/// capture, capture_mint, metadata, or global_config (seed-separation ruling).
pub const TREASURY_SEED: &[u8] = b"treasury";
pub const ECONOMY_MINT_SEED: &[u8] = b"economy_mint";

/// Structural default only — Juan rules any live value before it matters.
pub const ECONOMY_DECIMALS: u8 = 6;
/// Basis-point denominator for the tax split (rate <= 10000 enforced in setter).
pub const BPS_DENOM: u128 = 10_000;

// ---------------------------------------------------------------------------
// Account: Treasury — program-only authority (no admin-key field on purpose;
// every movement out of it is a program instruction, never a key signature)
// ---------------------------------------------------------------------------
#[account]
pub struct Treasury {
    pub bump: u8,
}

// ---------------------------------------------------------------------------
// Event — canonical movement record for the faucet flow (per-draw)
// ---------------------------------------------------------------------------
#[event]
pub struct FaucetDrawn {
    pub player: Pubkey,
    pub amount: u64,
    pub net: u64,
    pub tax: u64,
    pub rate_bps: u16,
}

// ----- init_treasury --------------------------------------------------------
// Creates the single treasury PDA + the economy mint + the treasury's ATA for
// it, in one transaction (mint-at-init for the ATA). Authority-gated via config.
#[derive(Accounts)]
pub struct InitTreasury<'info> {
    #[account(
        seeds = [CONFIG_SEED],
        bump = config.bump,
        has_one = authority @ ErrorCode::Unauthorized,
    )]
    pub config: Account<'info, GlobalConfig>,

    // Economy mint as a PDA: no external keypair anywhere. Mint authority =
    // the config PDA, so economic power is contract-bound, not key-bound.
    #[account(
        init,
        payer = authority,
        mint::decimals = ECONOMY_DECIMALS,
        mint::authority = config.key(),
        mint::freeze_authority = config.key(),
        seeds = [ECONOMY_MINT_SEED],
        bump,
    )]
    pub economy_mint: Account<'info, Mint>,

    #[account(
        init,
        payer = authority,
        space = 8 + 1, // discriminator + bump
        seeds = [TREASURY_SEED],
        bump,
    )]
    pub treasury: Account<'info, Treasury>,

    #[account(
        init,
        payer = authority,
        associated_token::mint = economy_mint,
        associated_token::authority = treasury,
    )]
    pub treasury_ata: Account<'info, TokenAccount>,

    #[account(mut)]
    pub authority: Signer<'info>,
    pub token_program: Program<'info, Token>,
    pub associated_token_program: Program<'info, AssociatedToken>,
    pub system_program: Program<'info, System>,
}

pub fn init_treasury(ctx: Context<InitTreasury>) -> Result<()> {
    let t = &mut ctx.accounts.treasury;
    t.bump = ctx.bumps.treasury;

    // Burn freeze authority post-init (slice-1 step 5 rationale verbatim):
    // a frozen economy mint would let leverage-holders grief-block transfers.
    // Mint authority stays with the config PDA for all faucet governance ops.
    // CI run 7 (E0609): explicit bump = config.bump, so no bumps.config field.
    let bump_arr = [ctx.accounts.config.bump];
    let config_seeds: &[&[u8]] = &[CONFIG_SEED, &bump_arr];
    let signer_seeds: &[&[&[u8]]] = &[config_seeds];
    let cpi_accounts = SetAuthority {
        account_or_mint: ctx.accounts.economy_mint.to_account_info(),
        current_authority: ctx.accounts.config.to_account_info(),
    };
    let cpi_ctx = CpiContext::new_with_signer(
        ctx.accounts.token_program.to_account_info(),
        cpi_accounts,
        signer_seeds,
    );
    token::set_authority(cpi_ctx, AuthorityType::FreezeAccount, None)?;

    Ok(())
}

// ----- set_economy_params ---------------------------------------------------
// The single knob surface. Ships inert (0 / 0): mechanism live, economics
// dead until the authority rules. Rate is basis points of each faucet draw.
#[derive(Accounts)]
pub struct SetEconomyParams<'info> {
    #[account(
        mut,
        seeds = [CONFIG_SEED],
        bump = config.bump,
        has_one = authority @ ErrorCode::Unauthorized,
    )]
    pub config: Account<'info, GlobalConfig>,
    pub authority: Signer<'info>,
}

pub fn set_economy_params(
    ctx: Context<SetEconomyParams>,
    tax_rate_bps: u16,
    faucet_max_per_draw: u64,
) -> Result<()> {
    // Rate ceiling: 10000 bps = 100%. Anything above is a typo or an attack;
    // reject loudly rather than mint a tax larger than the draw itself.
    require!(tax_rate_bps <= 10_000, ErrorCode::RateTooHigh);
    let cfg = &mut ctx.accounts.config;
    cfg.tax_rate_bps = tax_rate_bps;
    cfg.faucet_max_per_draw = faucet_max_per_draw;
    Ok(())
}

// ----- open_faucet_account --------------------------------------------------
// Explicit, separate open — no init-if-needed anywhere in this program. A
// second call fails at the ATA AlreadyInitialized gate by construction.
#[derive(Accounts)]
pub struct OpenFaucetAccount<'info> {
    #[account(mut)]
    pub player: Signer<'info>,
    #[account(seeds = [ECONOMY_MINT_SEED], bump)]
    pub economy_mint: Account<'info, Mint>,
    #[account(
        init,
        payer = player,
        associated_token::mint = economy_mint,
        associated_token::authority = player,
    )]
    pub player_ata: Account<'info, TokenAccount>,
    // CI run 7: init ATA constraint requires a non-optional token_program field.
    pub token_program: Program<'info, Token>,
    pub associated_token_program: Program<'info, AssociatedToken>,
    pub system_program: Program<'info, System>,
}

pub fn open_faucet_account(_ctx: Context<OpenFaucetAccount>) -> Result<()> {
    // Account creation is the whole operation; nothing else to write.
    Ok(())
}

// ----- faucet_draw ----------------------------------------------------------
// Taxed player faucet inflow (flow 1 of 3). Mints amount, splits it by the
// configured rate: net -> player ATA, tax -> treasury ATA. Config PDA is the
// mint authority, so every draw is contract-signed, never key-signed.
#[derive(Accounts)]
pub struct FaucetDraw<'info> {
    #[account(seeds = [CONFIG_SEED], bump = config.bump)]
    pub config: Account<'info, GlobalConfig>,
    #[account(mut, seeds = [ECONOMY_MINT_SEED], bump)]
    pub economy_mint: Account<'info, Mint>,
    #[account(seeds = [TREASURY_SEED], bump = treasury.bump)]
    pub treasury: Account<'info, Treasury>,
    #[account(
        mut,
        constraint = treasury_ata.mint == economy_mint.key()
            && treasury_ata.owner == treasury.key()
            @ ErrorCode::FaucetAccountMismatch,
    )]
    pub treasury_ata: Account<'info, TokenAccount>,
    // Not init here on purpose: open_faucet_account owns opening. This
    // constraint is what turns a missing open into a named error.
    #[account(
        mut,
        constraint = player_ata.mint == economy_mint.key()
            && player_ata.owner == player.key()
            @ ErrorCode::FaucetAccountMismatch,
    )]
    pub player_ata: Account<'info, TokenAccount>,
    pub player: Signer<'info>,
    pub token_program: Program<'info, Token>,
}

pub fn faucet_draw(ctx: Context<FaucetDraw>, amount: u64) -> Result<()> {
    let cap = ctx.accounts.config.faucet_max_per_draw;
    // Inert default: cap 0 disables the faucet entirely (ships dead).
    require!(cap > 0, ErrorCode::FaucetDisabled);
    // Per-draw pacing gate — Juan's cap, checked per draw, no rolling state.
    require!(amount <= cap, ErrorCode::ExceedsDrawCap);
    // An event with no movement would lie to indexers; reject zero draws.
    require!(amount > 0, ErrorCode::FaucetAmountZero);

    // u128 intermediates: amount * rate overflows u64 at realistic caps;
    // checked math on the exact figure the treasury books (no wraparound).
    let rate = ctx.accounts.config.tax_rate_bps as u128;
    let gross = amount as u128;
    let tax = gross * rate / BPS_DENOM;
    let net = gross - tax; // rate <= 10000 guarantees tax <= gross
    let rate_bps = ctx.accounts.config.tax_rate_bps;

    let bump_arr = [ctx.accounts.config.bump];
    let config_seeds: &[&[u8]] = &[CONFIG_SEED, &bump_arr];
    let signer_seeds: &[&[&[u8]]] = &[config_seeds];

    // Player net.
    let cpi_accounts = MintTo {
        mint: ctx.accounts.economy_mint.to_account_info(),
        to: ctx.accounts.player_ata.to_account_info(),
        authority: ctx.accounts.config.to_account_info(),
    };
    let cpi_ctx = CpiContext::new_with_signer(
        ctx.accounts.token_program.to_account_info(),
        cpi_accounts,
        signer_seeds,
    );
    token::mint_to(cpi_ctx, net as u64)?;

    // Tax inflow to treasury (skipped at rate 0 — no pointless zero transfer).
    if tax > 0 {
        let cpi_accounts = MintTo {
            mint: ctx.accounts.economy_mint.to_account_info(),
            to: ctx.accounts.treasury_ata.to_account_info(),
            authority: ctx.accounts.config.to_account_info(),
        };
        let cpi_ctx = CpiContext::new_with_signer(
            ctx.accounts.token_program.to_account_info(),
            cpi_accounts,
            signer_seeds,
        );
        token::mint_to(cpi_ctx, tax as u64)?;
    }

    // Canonical movement event (every movement emits — hub ruling).
    emit!(FaucetDrawn {
        player: ctx.accounts.player.key(),
        amount,
        net: net as u64,
        tax: tax as u64,
        rate_bps,
    });

    Ok(())
}

// ----- mint_founding_datagram -----------------------------------------------
// One-time founding mint (flow 3 of 3): the datagram pointing at the Ethereum
// original (Hato and Paeni). Predates the device fleet — no device signature;
// instead it is authority-gated AND flag-gated (exactly once, ever). The
// token is deposited straight to the treasury — house flow, tax-exempt by
// construction (no draw, no split).
#[derive(Accounts)]
#[instruction(capture_hash: [u8; 32])]
pub struct MintFoundingDatagram<'info> {
    #[account(
        mut,
        seeds = [CONFIG_SEED],
        bump = config.bump,
        has_one = authority @ ErrorCode::Unauthorized,
    )]
    pub config: Account<'info, GlobalConfig>,
    #[account(seeds = [TREASURY_SEED], bump = treasury.bump)]
    pub treasury: Account<'info, Treasury>,

    // Same two-layer gate as slice 1: PDA init = capture-hash uniqueness;
    // the founding_minted flag = one-time, even across hashes.
    #[account(
        init,
        payer = authority,
        space = DATAGRAM_SPACE,
        seeds = [CAPTURE_SEED, capture_hash.as_ref()],
        bump,
    )]
    pub datagram: Account<'info, Datagram>,

    #[account(
        init,
        payer = authority,
        mint::decimals = 0,
        mint::authority = datagram.key(),
        mint::freeze_authority = datagram.key(),
        seeds = [CAPTURE_MINT_SEED, capture_hash.as_ref()],
        bump,
    )]
    pub mint: Account<'info, Mint>,

    // Per-datagram ATA at the treasury (distinct from the economy-mint ATA
    // created in init_treasury — one ATA per mint, both treasury-owned).
    #[account(
        init,
        payer = authority,
        associated_token::mint = mint,
        associated_token::authority = treasury,
    )]
    pub treasury_mint_ata: Account<'info, TokenAccount>,

    #[account(mut)]
    pub authority: Signer<'info>,

    #[account(
        mut,
        seeds = [METADATA_SEED, metadata_program.key().as_ref(), mint.key().as_ref()],
        seeds::program = metadata_program.key(),
        bump,
    )]
    /// CHECK: validated by the metadata program via the seeds::program
    /// constraint above. We do not deserialize Metaplex state; the metadata
    /// program does, during the CPI — doc comment required by Anchor's
    /// account safety lint for UncheckedAccount (fixed in CI run 5).
    pub metadata: UncheckedAccount<'info>,

    pub token_program: Program<'info, Token>,
    pub associated_token_program: Program<'info, AssociatedToken>,
    pub metadata_program: Program<'info, Metadata>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

pub fn mint_founding_datagram(
    ctx: Context<MintFoundingDatagram>,
    capture_hash: [u8; 32],
    score: u16,
    desc_ref: String,
) -> Result<()> {
    // One-time gate FIRST: the flag bounds founding to exactly once even if
    // a different capture_hash were presented; PDA init is the per-hash gate.
    // Any failure here reverts the whole transaction (Solana atomicity), so
    // the flag-check ordering vs account init is safe.
    require!(
        !ctx.accounts.config.founding_minted,
        ErrorCode::FoundingAlreadyMinted
    );
    // desc_ref is a required String at the ix boundary (not Option): the
    // founding datagram MUST carry the pointer to the Ethereum original.
    require!(desc_ref.len() <= 192, ErrorCode::DescRefTooLong);

    // CI run 7 (E0308): unix_timestamp is i64; stored timestamps are u64.
    let now = Clock::get()?.unix_timestamp as u64;

    let dg = &mut ctx.accounts.datagram;
    dg.capture_hash = capture_hash;
    // Predates the device fleet: the authority stands in as registrant.
    dg.device = ctx.accounts.authority.key();
    dg.timestamp = now;
    dg.score = score;
    // Honest pre-fleet defaults: no geotag claim, no session provenance.
    dg.geo_tag = GeoTag::Withheld;
    dg.session_ref = [0u8; 32];
    dg.desc_ref = Some(desc_ref.clone());
    dg.mint = ctx.accounts.mint.key();
    dg.bump = ctx.bumps.datagram;

    // Flip the one-time flag (house flow — tax-exempt by construction).
    let cfg = &mut ctx.accounts.config;
    cfg.founding_minted = true;

    // Datagram PDA signer seeds (mint_to / set_authority / metadata CPI).
    let bump_arr = [ctx.bumps.datagram];
    let datagram_seeds: &[&[u8]] = &[CAPTURE_SEED, capture_hash.as_ref(), &bump_arr];
    let signer_seeds: &[&[&[u8]]] = &[datagram_seeds];

    // Mint the founding token (supply 1) to the treasury's ATA.
    let cpi_accounts = MintTo {
        mint: ctx.accounts.mint.to_account_info(),
        to: ctx.accounts.treasury_mint_ata.to_account_info(),
        authority: ctx.accounts.datagram.to_account_info(),
    };
    let cpi_ctx = CpiContext::new_with_signer(
        ctx.accounts.token_program.to_account_info(),
        cpi_accounts,
        signer_seeds,
    );
    token::mint_to(cpi_ctx, 1)?;

    // Burn freeze authority post-init (slice-1 step 5 rationale verbatim).
    let cpi_accounts = SetAuthority {
        account_or_mint: ctx.accounts.mint.to_account_info(),
        current_authority: ctx.accounts.datagram.to_account_info(),
    };
    let cpi_ctx = CpiContext::new_with_signer(
        ctx.accounts.token_program.to_account_info(),
        cpi_accounts,
        signer_seeds,
    );
    token::set_authority(cpi_ctx, AuthorityType::FreezeAccount, None)?;

    // Metaplex metadata — same verified CPI shape as slice 1 (checkpoint 6):
    // uri = desc_ref (the Ethereum original pointer), zero royalties.
    let data_v2 = DataV2 {
        name: "TerraQuest Datagram".to_string(),
        symbol: "TRRA".to_string(),
        uri: desc_ref,
        seller_fee_basis_points: 0,
        creators: None,
        collection: None,
        uses: None,
    };
    let cpi_accounts = CreateMetadataAccountsV3 {
        metadata: ctx.accounts.metadata.to_account_info(),
        mint: ctx.accounts.mint.to_account_info(),
        mint_authority: ctx.accounts.datagram.to_account_info(),
        payer: ctx.accounts.authority.to_account_info(),
        update_authority: ctx.accounts.datagram.to_account_info(),
        system_program: ctx.accounts.system_program.to_account_info(),
        rent: ctx.accounts.rent.to_account_info(),
    };
    let cpi_ctx = CpiContext::new_with_signer(
        ctx.accounts.metadata_program.to_account_info(),
        cpi_accounts,
        signer_seeds,
    );
    metadata::create_metadata_accounts_v3(cpi_ctx, data_v2, true, true, None)?;

    // Canonical mint event, same shape as slice-1 mints (one event type for
    // indexers; geo_disclosed = false matches the Withheld field above).
    emit!(DatagramMinted {
        capture_hash,
        device: ctx.accounts.authority.key(),
        mint: ctx.accounts.mint.key(),
        score,
        timestamp: now,
        geo_disclosed: false,
    });

    Ok(())
}
