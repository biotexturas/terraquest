// =============================================================================
// TerraQuest Mint - slice-1 instruction bodies + accounts structs
// =============================================================================
// Relocated out of the #[program] module (after CI run 7); wrappers in lib.rs
// delegate here verbatim. UNCHANGED from the run-5 green compile except the
// CI-run-15 compute-unit fix in mint_datagram step 2: the Ed25519 precompile
// performs the signature crypto; this module only binds its attestation.
// Guards: devnet only, program -> tests -> devnet order.
// =============================================================================

use anchor_lang::prelude::*;
use anchor_lang::solana_program::ed25519_program::ID as ED25519_PROGRAM_ID;
use anchor_lang::solana_program::sysvar::instructions::{
    load_instruction_at_checked,
};
use anchor_spl::associated_token::AssociatedToken;
use anchor_spl::metadata::{self, CreateMetadataAccountsV3, Metadata};
use anchor_spl::metadata::mpl_token_metadata::types::DataV2;
use anchor_spl::token::{self, Mint, MintTo, SetAuthority, Token, TokenAccount};
// Checkpoint 7 (docs.rs anchor-spl 0.31.1): AuthorityType is not re-exported
// from anchor_spl::token - nested path proven in CI run 5.
use anchor_spl::token::spl_token::instruction::AuthorityType;

use crate::terraquest_mint::{
    Datagram, DatagramMinted, DeviceRecord, ErrorCode, GeoTag, GlobalConfig,
    CAPTURE_MINT_SEED, CAPTURE_SEED, CONFIG_SEED, DATAGRAM_SPACE, DEVICE_SEED,
    METADATA_SEED,
};

// ----- initialize_config ------------------------------------------------
// Honest front-run window: any signer can be first and become authority.
// Known, spec'd, acceptable for the devnet MVP; mainnet gates init behind a
// deployer key in a separate human-review pass (spec v2 non-goals).
#[derive(Accounts)]
pub struct InitializeConfig<'info> {
    #[account(
        init,
        payer = authority,
        space = 56, // disc 8 + authority 32 + bump 1 + rate 2 + cap 8 + flag 1 = 52, +4 slack
        seeds = [CONFIG_SEED],
        bump,
    )]
    pub config: Account<'info, GlobalConfig>,
    #[account(mut)]
    pub authority: Signer<'info>,
    pub system_program: Program<'info, System>,
}

pub fn initialize_config(ctx: Context<InitializeConfig>) -> Result<()> {
    let cfg = &mut ctx.accounts.config;
    cfg.authority = ctx.accounts.authority.key();
    cfg.bump = ctx.bumps.config;
    // Slice-2 economy fields: explicit inert defaults (alloc zero-fills; spelled
    // out so the ship-dead intent is legible on review).
    cfg.tax_rate_bps = 0;
    cfg.faucet_max_per_draw = 0;
    cfg.founding_minted = false;
    Ok(())
}

// ----- add_device -------------------------------------------------------
// T6: only config.authority registers devices - has_one is the trust root.
#[derive(Accounts)]
#[instruction(device_key: Pubkey)]
pub struct AddDevice<'info> {
    #[account(
        seeds = [CONFIG_SEED],
        bump = config.bump,
        has_one = authority @ ErrorCode::Unauthorized,
    )]
    pub config: Account<'info, GlobalConfig>,
    #[account(
        init,
        payer = authority,
        space = 8 + 32 + 32 + 8 + 1, // disc + device + authority + added_at + bump
        seeds = [DEVICE_SEED, device_key.as_ref()],
        bump,
    )]
    pub device_record: Account<'info, DeviceRecord>,
    #[account(mut)]
    pub authority: Signer<'info>,
    pub system_program: Program<'info, System>,
}

pub fn add_device(ctx: Context<AddDevice>, device_key: Pubkey) -> Result<()> {
    let rec = &mut ctx.accounts.device_record;
    rec.device = device_key;
    rec.authority = ctx.accounts.authority.key();
    rec.added_at = Clock::get()?.unix_timestamp;
    rec.bump = ctx.bumps.device_record;
    Ok(())
}

// ----- remove_device ----------------------------------------------------
// T6: authority-gated close-to-revoke - destroying the registry account cuts
// a leaked device key off without a new instruction state machine.
#[derive(Accounts)]
pub struct RemoveDevice<'info> {
    #[account(
        seeds = [CONFIG_SEED],
        bump = config.bump,
        has_one = authority @ ErrorCode::Unauthorized,
    )]
    pub config: Account<'info, GlobalConfig>,
    #[account(
        mut,
        close = authority,
        seeds = [DEVICE_SEED, device_record.device.as_ref()],
        bump = device_record.bump,
    )]
    pub device_record: Account<'info, DeviceRecord>,
    #[account(mut)]
    pub authority: Signer<'info>,
}

pub fn remove_device(_ctx: Context<RemoveDevice>) -> Result<()> {
    // close = authority in the accounts struct handles closure + rent return.
    Ok(())
}

// ---------------------------------------------------------------------------
// Ed25519-precompile attestation (CI run 15 compute-unit fix)
// WHY: ed25519-dalek verify_strict on SBF burns > 1.37M CU - the whole 1.4M
// per-instruction cap - so every mint died with "exceeded CUs meter" before
// the Metaplex CPI (T1/T2/T3/T5 failed; real devnet mints fail identically).
// The runtime Ed25519 program does the same verification during tx processing
// (verify_strict active on-cluster, near-zero CU). We do NOT redo curve math;
// we bind the precompile's attested (pubkey, message) to this instruction.
// Missing/mismatched attestation => InvalidDeviceSignature.
//
// Layout (verified 2026-09-27 vs Agave v2.1.13 sdk/src/ed25519_instruction.rs):
//   [0] u8 num_signatures (require 1); [1] u8 padding (unused);
//   [2..16] 7 x u16 LE: sig_off, sig_ix, pk_off, pk_ix, msg_off, msg_size,
//   msg_ix; then pubkey/signature/message at those offsets. ix index u16::MAX
//   = "bytes in THIS instruction's data" - the only reference shape accepted.
// ---------------------------------------------------------------------------

fn u16le(data: &[u8], at: usize) -> usize {
    u16::from_le_bytes([data[at], data[at + 1]]) as usize
}

/// Parse a single-signature, same-instruction attestation ->
/// (device pubkey, signature bytes, attested message). None = unsupported
/// shape; the caller rejects rather than falling back to anything weaker.
fn parse_ed25519_attestation(data: &[u8]) -> Option<(Pubkey, [u8; 64], Vec<u8>)> {
    if data.len() < 16 || data[0] != 1 {
        return None;
    }
    let sig_off = u16le(data, 2);
    let sig_ix = u16le(data, 4);
    let pk_off = u16le(data, 6);
    let pk_ix = u16le(data, 8);
    let msg_off = u16le(data, 10);
    let msg_sz = u16le(data, 12);
    let msg_ix = u16le(data, 14);
    if sig_ix != u16::MAX as usize
        || pk_ix != u16::MAX as usize
        || msg_ix != u16::MAX as usize
    {
        return None;
    }
    if data.len() < pk_off.saturating_add(32)
        || data.len() < sig_off.saturating_add(64)
        || data.len() < msg_off.saturating_add(msg_sz)
    {
        return None;
    }
    let pubkey = Pubkey::new_from_array(data[pk_off..pk_off + 32].try_into().ok()?);
    let signature: [u8; 64] = data[sig_off..sig_off + 64].try_into().ok()?;
    let message = data[msg_off..msg_off + msg_sz].to_vec();
    Some((pubkey, signature, message))
}

/// First Ed25519-program instruction in the tx, parsed. The precompile has
/// already verified every such instruction (an invalid one kills the tx
/// before this handler runs). None = absent or unparseable => reject.
fn find_ed25519_attestation(ix_sysvar: &AccountInfo) -> Option<(Pubkey, [u8; 64], Vec<u8>)> {
    for i in 0..64 {
        match load_instruction_at_checked(i, ix_sysvar) {
            Ok(ix) => {
                if ix.program_id == ED25519_PROGRAM_ID {
                    return parse_ed25519_attestation(&ix.data);
                }
            }
            Err(_) => break, // index past end of the instruction list
        }
    }
    None
}

// ----- mint_datagram ----------------------------------------------------
// T1 happy path: fields stored exactly as submitted (options included);
// optional geo_tag/desc_ref never affect uniqueness - only capture_hash does.
#[allow(clippy::too_many_arguments)]
pub fn mint_datagram(
    ctx: Context<MintDatagram>,
    capture_hash: [u8; 32],
    timestamp: u64,
    score: u16,
    session_ref: [u8; 32],
    geo_tag: GeoTag,
    desc_ref: Option<String>,
    // Kept in the instruction surface for tx-shape compatibility with b1's
    // wrapper (handoff: wrapper tx shape unchanged). Crypto is verified by
    // the Ed25519 precompile - step 2 - so this copy is not re-checked.
    _signature: [u8; 64],
) -> Result<()> {
    // ----- (1) desc_ref length gate -------------------------------------
    // DATAGRAM_SPACE reserves 192 bytes for desc_ref: a longer URI would
    // silently truncate on write; fail loudly instead (DescRefTooLong).
    if let Some(ref uri) = desc_ref {
        require!(uri.len() <= 192, ErrorCode::DescRefTooLong);
    }

    // ----- (2) ed25519 device signature - precompile attestation binding ---
    // CI run 15 root cause (do NOT reintroduce in-program curve math):
    // verify_strict here cost > 1.37M of the 1.4M CU cap and aborted every
    // mint before the Metaplex CPI. The crypto runs in the Ed25519 precompile
    // during tx processing; what this handler proves is BINDING:
    //   attested pubkey  == device signer key (registered in device_record)
    //   attested message == capture_hash || timestamp_le || score_le
    // Missing/unsupported/mismatched => InvalidDeviceSignature - exactly what
    // T3 (captured attestation over older timestamp) and T5 (capture_hash
    // byte flipped) assert. Contract unchanged: the signature IS the binding;
    // the PDA is the uniqueness gate. Two layers, neither optional.
    let binding_message: Vec<u8> = {
        let mut m = Vec::with_capacity(32 + 8 + 2);
        m.extend_from_slice(&capture_hash);
        m.extend_from_slice(&timestamp.to_le_bytes());
        m.extend_from_slice(&score.to_le_bytes());
        m
    };

    let (attested_key, _attested_sig, attested_msg) =
        find_ed25519_attestation(ctx.accounts.instructions.as_ref())
            .ok_or_else(|| error!(ErrorCode::InvalidDeviceSignature))?;
    require!(
        attested_key == ctx.accounts.device.key(),
        ErrorCode::InvalidDeviceSignature
    );
    require!(
        attested_msg == binding_message,
        ErrorCode::InvalidDeviceSignature
    );
    // _attested_sig deliberately unread: an invalid signature could never
    // have let this handler run - the precompile would have killed the tx.

    // ----- (3) Store datagram fields (T1 happy path) --------------------
    let dg = &mut ctx.accounts.datagram;
    dg.capture_hash = capture_hash;
    dg.device = ctx.accounts.device.key();
    dg.timestamp = timestamp;
    dg.score = score;
    dg.geo_tag = geo_tag.clone();
    dg.session_ref = session_ref;
    dg.desc_ref = desc_ref.clone();
    dg.mint = ctx.accounts.mint.key();
    dg.bump = ctx.bumps.datagram;

    let geo_disclosed = matches!(geo_tag, GeoTag::Disclosed { .. });

    // ----- PDA signer seeds for mint_to / set_authority / metadata ------
    // Mint/freeze/update authority all = datagram PDA; the mint PDA seeds are
    // address-derivation only, signing uses the datagram seeds below.
    // Shape checkpoint: signer seeds are &[&[&[u8]]] (set, per-set, bytes).
    let datagram_bump = ctx.bumps.datagram;
    let bump_arr = [datagram_bump];
    let datagram_seeds: &[&[u8]] = &[
        CAPTURE_SEED,
        capture_hash.as_ref(),
        &bump_arr,
    ];
    let signer_seeds: &[&[&[u8]]] = &[datagram_seeds];

    // ----- (4) MintTo 1 token via CPI -----------------------------------
    // Supply is 1 by construction; mint is a PDA, only the datagram PDA
    // signs. COMPILE CHECKPOINT 6: MintTo { mint, to, authority }.
    let cpi_accounts = MintTo {
        mint: ctx.accounts.mint.to_account_info(),
        to: ctx.accounts.holder_ata.to_account_info(),
        authority: ctx.accounts.datagram.to_account_info(),
    };
    let cpi_ctx = CpiContext::new_with_signer(
        ctx.accounts.token_program.to_account_info(),
        cpi_accounts,
        signer_seeds,
    );
    token::mint_to(cpi_ctx, 1)?;

    // ----- (5) Burn freeze authority post-init ---------------------------
    // Freeze authority None: a frozen mint would let an attacker grief-block
    // the holder; burning it closes that surface. Mint authority stays with
    // the datagram PDA. COMPILE CHECKPOINT 7: SetAuthority { account_or_mint,
    // current_authority } + nested AuthorityType path + Option<Pubkey>.
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

    // ----- (6) Metaplex metadata CPI -------------------------------------
    // VERIFIED vs anchor-spl 0.31.1 + mpl-token-metadata 5.1.0:
    // create_metadata_accounts_v3(ctx, DataV2, is_mutable, ua_is_signer,
    // collection_details) over { metadata, mint, mint_authority, payer,
    // update_authority, system_program, rent }. uri = desc_ref (off-chain by
    // reference), zero royalties, update authority = datagram PDA signer.
    let uri = desc_ref.unwrap_or_default();
    let data_v2 = DataV2 {
        name: "TerraQuest Datagram".to_string(),
        symbol: "TRRA".to_string(),
        uri,
        seller_fee_basis_points: 0,
        creators: None,
        collection: None,
        uses: None,
    };
    let cpi_accounts = CreateMetadataAccountsV3 {
        metadata: ctx.accounts.metadata.to_account_info(),
        mint: ctx.accounts.mint.to_account_info(),
        mint_authority: ctx.accounts.datagram.to_account_info(),
        payer: ctx.accounts.device.to_account_info(),
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

    // ----- (7) Emit DatagramMinted ---------------------------------------
    // Canonical indexer event; geo_disclosed collapses GeoTag to a bool.
    emit!(DatagramMinted {
        capture_hash,
        device: ctx.accounts.device.key(),
        mint: ctx.accounts.mint.key(),
        score,
        timestamp,
        geo_disclosed,
    });

    Ok(())
}

// COMPILE CHECKPOINT (items 4, 5, 9): ATA init / mint init / metadata PDA
// constraint shapes on MintDatagram.
#[derive(Accounts)]
#[instruction(capture_hash: [u8; 32])]
pub struct MintDatagram<'info> {
    // T4: device is tx signer AND fee payer; an unregistered key cannot
    // satisfy the device_record seeds constraint, so the spoof fails at
    // account resolution before the handler runs - a constraint-level block.
    #[account(mut)]
    pub device: Signer<'info>,

    // Slice-2 tax insertion point - typed so the address never moves.
    #[account(
        seeds = [CONFIG_SEED],
        bump = config.bump,
    )]
    pub config: Account<'info, GlobalConfig>,

    // T4 (cont): device_record PDA derives from the device signer key.
    #[account(
        seeds = [DEVICE_SEED, device.key().as_ref()],
        bump = device_record.bump,
    )]
    pub device_record: Account<'info, DeviceRecord>,

    // T2: double mint fails at account creation - capture_hash PDA is the
    // uniqueness gate (init on an existing account = AccountAlreadyInialized).
    #[account(
        init,
        payer = device,
        space = DATAGRAM_SPACE,
        seeds = [CAPTURE_SEED, capture_hash.as_ref()],
        bump,
    )]
    pub datagram: Account<'info, Datagram>,

    // Mint PDA [CAPTURE_MINT_SEED, hash]; authorities = datagram PDA.
    // CHECKPOINT 5: mint::decimals / mint::authority / mint::freeze_authority.
    #[account(
        init,
        payer = device,
        mint::decimals = 0,
        mint::authority = datagram.key(),
        mint::freeze_authority = datagram.key(),
        seeds = [CAPTURE_MINT_SEED, capture_hash.as_ref()],
        bump,
    )]
    pub mint: Account<'info, Mint>,

    // Holder in slice 1 = the device signer's ATA (player-vault in slice 2).
    // CHECKPOINT 4: associated_token::mint + associated_token::authority.
    #[account(
        init,
        payer = device,
        associated_token::mint = mint,
        associated_token::authority = device,
    )]
    pub holder_ata: Account<'info, TokenAccount>,

    // CHECKPOINT 9: seeds::program = metadata_program is the Metaplex PDA
    // derivation ["metadata", metadata_program_id, mint].
    #[account(
        mut,
        seeds = [METADATA_SEED, metadata_program.key().as_ref(), mint.key().as_ref()],
        seeds::program = metadata_program.key(),
        bump,
    )]
    /// CHECK: validated by the metadata program via the seeds::program
    /// constraint above. We don't deserialize Metaplex state; the metadata
    /// program does, during the CPI - doc comment required by Anchor's
    /// account safety lint (IDL build failed without it, run 36275771577).
    pub metadata: UncheckedAccount<'info>,

    pub token_program: Program<'info, Token>,
    pub associated_token_program: Program<'info, AssociatedToken>,
    pub metadata_program: Program<'info, Metadata>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,

    // CI run 15: tx instruction list - lets the handler find the Ed25519
    // precompile attestation it binds against (step 2). Read-only sysvar.
    /// CHECK: address-pinned to the real instructions sysvar - the handler parses this account's data as the tx instruction list, so the address constraint is load-bearing (replaces Sysvar<Instructions>, which fails SolanaSysvar bounds on this toolchain - CI runs 6 and 16). Read path unchanged: load_instruction_at_checked in find_ed25519_attestation.
    #[account(address = anchor_lang::solana_program::sysvar::instructions::id())]
    pub instructions: UncheckedAccount<'info>,
}