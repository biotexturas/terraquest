// =============================================================================
// TerraQuest Mint - T1-T6: the six named-attack integration tests
// (spec b2-mint-program-spec-v2; build order: program -> tests -> devnet).
// =============================================================================
// Each test names the attack; every assertion answers "why is this here":
//   T1 happy path - valid device-signed mint stores every field as submitted,
//                   mints exactly one token to the device ATA, burns freeze
//                   authority, creates Metaplex metadata, emits DatagramMinted.
//   T2 double mint- same capture_hash with a FRESH valid signature rejected
//                   by the PDA init gate with ZERO state delta (exactly once).
//   T3 replay     - captured attestation over an older timestamp vs instruction
//                   args with ts=999 -> payload mismatch -> 6002; hash unminted,
//                   so only the signature layer can stop it.
//   T4 spoof      - unregistered device with valid self-signature fails at
//                   account resolution (empty device_record), pre-handler.
//   T5 tamper     - one flipped capture_hash byte -> attested payload mismatch:
//                   the uniqueness key itself is signed.
//   T6 rogue mgmt - has_one gate on add/remove (+init rollback), and
//                   close-to-revoke actually cuts the key off.
//
// CI run 15 CU fix: mint txs carry TWO instructions - the Ed25519 precompile
// ix (runtime verifies the signature crypto; in-program verify_strict burned
// >1.37M of the 1.4M CU cap) then MintDatagram (program binds attested pubkey
// + payload; no curve math in-handler). Layout mirrors Agave v2.1.13
// new_ed25519_instruction: [num_sigs, pad][7 x u16 LE offsets][pk 32][sig 64]
// [message]; ix-index fields = u16::MAX (bytes in this instruction's data).
//
// Runtime: LiteSVM; loads target/deploy/terraquest_mint.so (anchor build) +
// target/mpl_token_metadata.so (solana program dump) via CARGO_MANIFEST_DIR.
// CI: lean cargo-test compiles this file + runs artifact-free tests; the
// suite executes in anchor-build where the .so artifacts exist.
// =============================================================================

use anchor_lang::solana_program::hash;
use anchor_lang::solana_program::instruction::Instruction;
use anchor_lang::solana_program::program_option::COption;
use anchor_lang::solana_program::program_pack::Pack;
use anchor_lang::solana_program::system_program;
use anchor_lang::solana_program::sysvar;
use anchor_lang::{AccountDeserialize, InstructionData, ToAccountMetas};
use anchor_spl::associated_token::{self, get_associated_token_address};
use anchor_spl::metadata::ID as METADATA_ID;
use anchor_spl::token::spl_token::state::{Account as SplTokenAccount, Mint as SplMint};
use litesvm::types::{FailedTransactionMetadata, TransactionMetadata};
use litesvm::LiteSVM;
use solana_compute_budget::compute_budget::ComputeBudget;
use solana_keypair::Keypair;
use solana_message::Message;
use solana_signer::Signer;
use solana_transaction::Transaction;
use terraquest_mint::terraquest_mint::{
    Datagram, ErrorCode, GeoTag, CAPTURE_MINT_SEED, CAPTURE_SEED, CONFIG_SEED, DEVICE_SEED,
    METADATA_SEED,
};
use terraquest_mint::{accounts, instruction, ID as PROGRAM_ID};

const SOL: u64 = 1_000_000_000;
const SESSION: [u8; 32] = [9u8; 32];

// --- helpers ---------------------------------------------------------------

fn pda(seeds: &[&[u8]]) -> anchor_lang::solana_program::pubkey::Pubkey {
    anchor_lang::solana_program::pubkey::Pubkey::find_program_address(seeds, &PROGRAM_ID).0
}

fn metadata_pda(
    mint: &anchor_lang::solana_program::pubkey::Pubkey,
) -> anchor_lang::solana_program::pubkey::Pubkey {
    anchor_lang::solana_program::pubkey::Pubkey::find_program_address(
        &[METADATA_SEED, METADATA_ID.as_ref(), mint.as_ref()],
        &METADATA_ID,
    ).0
}

// Signed payload binds capture_hash || timestamp_le || score_le - byte-for-byte
// the message mint_datagram rebuilds (and now attests against).
fn binding_msg(capture_hash: &[u8; 32], ts: u64, score: u16) -> Vec<u8> {
    let mut m = Vec::with_capacity(32 + 8 + 2);
    m.extend_from_slice(capture_hash);
    m.extend_from_slice(&ts.to_le_bytes());
    m.extend_from_slice(&score.to_le_bytes());
    m
}

fn sign_binding(device: &Keypair, capture_hash: &[u8; 32], ts: u64, score: u16) -> [u8; 64] {
    // solana-signer 2.x: the trait method is sign_message (there is no `sign`).
    let sig = device.sign_message(&binding_msg(capture_hash, ts, score));
    let bytes: &[u8] = sig.as_ref();
    bytes.try_into().expect("ed25519 signature is 64 bytes")
}

fn send_ix(
    svm: &mut LiteSVM,
    payer: &Keypair,
    ix: Instruction,
) -> Result<TransactionMetadata, FailedTransactionMetadata> {
    let msg = Message::new(&[ix], Some(&payer.pubkey()));
    let blockhash = svm.latest_blockhash();
    svm.send_transaction(Transaction::new(&[payer], msg, blockhash))
}

// Multi-instruction txs: attestation + mint (CI run 15 fix).
fn send_ixs(
    svm: &mut LiteSVM,
    payer: &Keypair,
    ixs: &[Instruction],
) -> Result<TransactionMetadata, FailedTransactionMetadata> {
    let msg = Message::new(ixs, Some(&payer.pubkey()));
    let blockhash = svm.latest_blockhash();
    svm.send_transaction(Transaction::new(&[payer], msg, blockhash))
}

// Ed25519 precompile ix over `message` (layout mirrors Agave
// new_ed25519_instruction - see header).
fn ed25519_ix(device: &Keypair, message: &[u8]) -> Instruction {
    let sig: [u8; 64] = device
        .sign_message(message)
        .as_ref()
        .try_into()
        .expect("ed25519 signature is 64 bytes");
    let pk = device.pubkey().to_bytes();
    const DATA_START: usize = 16; // 2 header bytes + 14 offsets
    let mut data = Vec::with_capacity(DATA_START + 32 + 64 + message.len());
    data.push(1u8); // num signatures
    data.push(0u8); // padding (unused by the precompile)
    data.extend_from_slice(&((DATA_START + 32) as u16).to_le_bytes()); // sig off = 48
    data.extend_from_slice(&u16::MAX.to_le_bytes()); // sig ix = this ix
    data.extend_from_slice(&(DATA_START as u16).to_le_bytes()); // pk off = 16
    data.extend_from_slice(&u16::MAX.to_le_bytes()); // pk ix = this ix
    data.extend_from_slice(&((DATA_START + 32 + 64) as u16).to_le_bytes()); // msg off = 112
    data.extend_from_slice(&(message.len() as u16).to_le_bytes()); // msg size
    data.extend_from_slice(&u16::MAX.to_le_bytes()); // msg ix = this ix
    data.extend_from_slice(&pk);
    data.extend_from_slice(&sig);
    data.extend_from_slice(message);
    Instruction {
        program_id: anchor_lang::solana_program::ed25519_program::ID,
        accounts: vec![],
        data,
    }
}

// Mint tx shape = [precompile attestation, mint ix]: the precompile verifies
// the signature crypto; the program binds attested pubkey + payload to args
// (missing/mismatched attestation = InvalidDeviceSignature, code 6002).
fn attest(device: &Keypair, message: &[u8], mint: Instruction) -> Vec<Instruction> {
    vec![ed25519_ix(device, message), mint]
}

#[allow(clippy::too_many_arguments)]
fn mint_ix(
    device: &Keypair,
    capture_hash: &[u8; 32],
    ts: u64,
    score: u16,
    geo_tag: GeoTag,
    desc_ref: Option<String>,
    signature: [u8; 64],
) -> Instruction {
    let device_pk = device.pubkey();
    let mint = pda(&[CAPTURE_MINT_SEED, capture_hash.as_ref()]);
    Instruction {
        program_id: PROGRAM_ID,
        accounts: accounts::MintDatagram {
            device: device_pk,
            config: pda(&[CONFIG_SEED]),
            device_record: pda(&[DEVICE_SEED, device_pk.as_ref()]),
            datagram: pda(&[CAPTURE_SEED, capture_hash.as_ref()]),
            mint,
            holder_ata: get_associated_token_address(&device_pk, &mint),
            metadata: metadata_pda(&mint),
            token_program: anchor_spl::token::spl_token::ID,
            associated_token_program: associated_token::ID,
            metadata_program: METADATA_ID,
            system_program: system_program::ID,
            rent: sysvar::rent::ID,
            instructions: sysvar::instructions::ID,
        }
        .to_account_metas(None),
        data: instruction::MintDatagram {
            capture_hash: *capture_hash,
            timestamp: ts,
            score,
            session_ref: SESSION,
            geo_tag,
            desc_ref,
            signature,
        }
        .data(),
    }
}

/// Boot: fresh LiteSVM + program loaded + config initialized + device
/// registered. Shared setup so each T-test starts from the same proven state.
fn boot() -> (LiteSVM, Keypair, Keypair) {
    let mut svm = LiteSVM::new()
        // 1.4M CU (the per-instruction max): attestation lookup + 3 CPIs
        // (token, ATA, Metaplex). The signature crypto runs in the Ed25519
        // precompile, not our handler (run 15 fix).
        .with_compute_budget(ComputeBudget {
            compute_unit_limit: 1_400_000,
            heap_size: 32 * 1024,
            ..ComputeBudget::default()
        })
        // unlimited logs: T1 asserts on the LAST Program-data line (our
        // event) - the default 10k cap would truncate it away.
        .with_log_bytes_limit(None);

    svm.add_program_from_file(
        PROGRAM_ID,
        concat!(env!("CARGO_MANIFEST_DIR"), "/../../target/deploy/terraquest_mint.so"),
    )
    .expect("target/deploy/terraquest_mint.so missing - run `anchor build` first");
    svm.add_program_from_file(
        METADATA_ID,
        concat!(env!("CARGO_MANIFEST_DIR"), "/../../target/mpl_token_metadata.so"),
    )
    .expect(
        "target/mpl_token_metadata.so missing - `solana program dump -u d \
         metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s target/mpl_token_metadata.so`",
    );

    let authority = Keypair::new();
    let device = Keypair::new();
    svm.airdrop(&authority.pubkey(), 10 * SOL).expect("airdrop authority");
    svm.airdrop(&device.pubkey(), 10 * SOL).expect("airdrop device");

    // Permissionless first-init is the spec'd front-run window (devnet MVP).
    let config = pda(&[CONFIG_SEED]);
    let ix = Instruction {
        program_id: PROGRAM_ID,
        accounts: accounts::InitializeConfig {
            config,
            authority: authority.pubkey(),
            system_program: system_program::ID,
        }
        .to_account_metas(None),
        data: instruction::InitializeConfig.data(),
    };
    send_ix(&mut svm, &authority, ix).expect("boot: initialize_config");

    // Authority registers the device - the T6 control path.
    let device_pk = device.pubkey();
    let ix = Instruction {
        program_id: PROGRAM_ID,
        accounts: accounts::AddDevice {
            config,
            device_record: pda(&[DEVICE_SEED, device_pk.as_ref()]),
            authority: authority.pubkey(),
            system_program: system_program::ID,
        }
        .to_account_metas(None),
        data: instruction::AddDevice { device_key: device_pk }.data(),
    };
    send_ix(&mut svm, &authority, ix).expect("boot: add_device");

    (svm, authority, device)
}

/// Assert the rejection surfaced as OUR custom program error `code`.
/// Debug-format match avoids solana-transaction-error re-exports; logs land
/// in the panic message so CI annotations carry the on-chain trace.
fn assert_custom(err: &FailedTransactionMetadata, code: u32, why: &str) {
    let dbg = format!("{:?}", err.err);
    assert!(
        dbg.contains(&format!("Custom({})", code)),
        "{}: expected custom program error {}, got: {}\nlogs:\n{}",
        why, code, dbg, err.meta.logs.join("\n")
    );
}

/// Decode the first 8 payload bytes from a base64 log body (first 12 chars =
/// exactly 9 bytes; byte 7 does not depend on byte 8, so the disc is exact).
fn b64_first8(s: &str) -> Option<[u8; 8]> {
    const T: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let b = s.as_bytes();
    if b.len() < 12 {
        return None;
    }
    let mut out = [0u8; 9];
    for g in 0..3usize {
        let mut v = [0u32; 4];
        for i in 0..4usize {
            v[i] = T.iter().position(|&c| c == b[g * 4 + i])? as u32;
        }
        let n = (v[0] << 18) | (v[1] << 12) | (v[2] << 6) | v[3];
        out[g * 3] = (n >> 16) as u8;
        out[g * 3 + 1] = (n >> 8) as u8;
        out[g * 3 + 2] = n as u8;
    }
    Some([out[0], out[1], out[2], out[3], out[4], out[5], out[6], out[7]])
}

/// The LAST Program-data line must decode to sha256("event:DatagramMinted")[..8]
/// - the emit! at the end of the mint handler is the final event of the tx.
fn assert_datagram_minted_event(meta: &TransactionMetadata, why: &str) {
    let expected: [u8; 8] = hash::hash(b"event:DatagramMinted").to_bytes()[..8]
        .try_into()
        .unwrap();
    let line = meta.logs.iter().rev()
        .find(|l| l.starts_with("Program data: "))
        .unwrap_or_else(|| panic!("{}: DatagramMinted event missing; logs:\n{}", why, meta.logs.join("\n")));
    let got = b64_first8(&line["Program data: ".len()..])
        .unwrap_or_else(|| panic!("{}: event log is not decodable base64: {}", why, line));
    assert_eq!(got, expected, "{}: last emitted event must be DatagramMinted", why);
}

// --- T1: happy path --------------------------------------------------------

#[test]
fn t1_happy_path_valid_signature_mints_exactly_one_datagram() {
    let (mut svm, _authority, device) = boot();
    let hash = [7u8; 32];
    let ts = 1_700_000_000u64;
    let score = 4242u16;
    let geo = GeoTag::Disclosed { latitude: 52.3676, longitude: 4.9041 };
    let desc = Some("https://terraquest.example/dg/7".to_string());
    let sig = sign_binding(&device, &hash, ts, score);

    let meta = send_ixs(
        &mut svm,
        &device,
        &attest(&device, &binding_msg(&hash, ts, score),
            mint_ix(&device, &hash, ts, score, geo.clone(), desc.clone(), sig)),
    )
    .expect("T1: valid device signature must mint");

    // Why: the record IS the capture provenance - every field round-trips
    // exactly as signed/submitted (spec T1 happy path).
    let dg_pk = pda(&[CAPTURE_SEED, &hash]);
    let dg_acc = svm.get_account(&dg_pk).expect("T1: datagram PDA must exist");
    assert_eq!(dg_acc.owner, PROGRAM_ID, "T1: datagram owned by our program");
    let mut dg_bytes: &[u8] = &dg_acc.data;
    let dg = Datagram::try_deserialize(&mut dg_bytes).expect("T1: datagram must deserialize");
    assert_eq!(dg.capture_hash, hash, "T1: capture_hash as submitted");
    assert_eq!(dg.device, device.pubkey(), "T1: device = tx signer");
    assert_eq!(dg.timestamp, ts, "T1: timestamp as submitted");
    assert_eq!(dg.score, score, "T1: score as submitted");
    assert_eq!(dg.geo_tag, geo, "T1: geo_tag round-trips");
    assert_eq!(dg.session_ref, SESSION, "T1: session_ref as submitted");
    assert_eq!(dg.desc_ref, desc, "T1: optional desc_ref as submitted");
    assert_eq!(dg.mint, pda(&[CAPTURE_MINT_SEED, &hash]), "T1: datagram points at its PDA mint");

    // Why: exactly one token, zero decimals, freeze authority burned -
    // nobody can grief-block the holder by freezing the mint.
    let mint_pk = dg.mint;
    let mint_acc = svm.get_account(&mint_pk).expect("T1: mint PDA must exist");
    let mint_state = SplMint::unpack(&mint_acc.data).expect("T1: mint state unpacks");
    assert_eq!(mint_state.supply, 1, "T1: supply is exactly 1");
    assert_eq!(mint_state.decimals, 0, "T1: datagram tokens are non-divisible");
    assert_eq!(mint_state.freeze_authority, COption::None,
        "T1: freeze authority burned post-init (no freeze griefing)");
    assert_eq!(mint_state.mint_authority, COption::Some(dg_pk),
        "T1: mint authority is the datagram PDA");

    // Why: the token landed in the DEVICE's ATA (slice-1 holder model).
    let ata_pk = get_associated_token_address(&device.pubkey(), &mint_pk);
    let ata_acc = svm.get_account(&ata_pk).expect("T1: holder ATA must exist");
    let ata_state = SplTokenAccount::unpack(&ata_acc.data).expect("T1: ATA unpacks");
    assert_eq!(ata_state.amount, 1, "T1: holder holds exactly 1");
    assert_eq!(ata_state.owner, device.pubkey(), "T1: ATA owned by device");
    assert_eq!(ata_state.mint, mint_pk, "T1: ATA for the datagram mint");

    // Why: Metaplex metadata exists at the deterministic PDA (off-chain URI
    // pointer is part of the mint contract, validated by seeds::program).
    let md_pk = metadata_pda(&mint_pk);
    let md_acc = svm.get_account(&md_pk).expect("T1: metadata account must exist");
    assert_eq!(md_acc.owner, METADATA_ID, "T1: metadata owned by Metaplex");

    // Why: one canonical DatagramMinted per mint (hub ruling: every movement
    // emits an event; indexers key off it).
    assert_datagram_minted_event(&meta, "T1");
}

// --- T2: double mint -------------------------------------------------------

#[test]
fn t2_double_mint_same_capture_hash_rejected_state_unchanged() {
    let (mut svm, _authority, device) = boot();
    let hash = [7u8; 32];

    send_ixs(&mut svm, &device,
        &attest(&device, &binding_msg(&hash, 100, 10),
            mint_ix(&device, &hash, 100, 10, GeoTag::Withheld, None,
                sign_binding(&device, &hash, 100, 10))))
    .expect("T2: first mint must succeed");

    // Attack: SAME capture_hash, fresh payload, fresh VALID attestation - so
    // if anything rejects this, it is the PDA `init` uniqueness gate, not the
    // signature layer (why: exactly-once must not depend on sig validity).
    let err = send_ixs(&mut svm, &device,
        &attest(&device, &binding_msg(&hash, 200, 20),
            mint_ix(&device, &hash, 200, 20, GeoTag::Withheld, None,
                sign_binding(&device, &hash, 200, 20))))
    .expect_err("T2: second mint on the same capture_hash must be rejected");
    let dbg = format!("{:?}", err.err);
    assert!(dbg.contains("InstructionError"),
        "T2: rejection must come from inside the program, got: {}\nlogs:\n{}",
        dbg, err.meta.logs.join("\n"));

    // Why: the security property is a ZERO state delta - first mint's payload
    // untouched, supply still 1, no second token anywhere.
    let dg_pk = pda(&[CAPTURE_SEED, &hash]);
    let dg_acc = svm.get_account(&dg_pk).expect("T2: first datagram must survive");
    let mut dg_bytes: &[u8] = &dg_acc.data;
    let dg = Datagram::try_deserialize(&mut dg_bytes).expect("T2: datagram unpacks");
    assert_eq!(dg.timestamp, 100, "T2: first mint payload NOT overwritten");
    assert_eq!(dg.score, 10, "T2: first mint score NOT overwritten");
    assert_eq!(dg.device, device.pubkey(), "T2: first mint device unchanged");

    let mint_pk = pda(&[CAPTURE_MINT_SEED, &hash]);
    let mint_acc = svm.get_account(&mint_pk).expect("T2: mint survives");
    let mint_state = SplMint::unpack(&mint_acc.data).unwrap();
    assert_eq!(mint_state.supply, 1, "T2: supply stays 1 after rejected double mint");
    let ata_pk = get_associated_token_address(&device.pubkey(), &mint_pk);
    let ata_acc = svm.get_account(&ata_pk).unwrap();
    let ata_state = SplTokenAccount::unpack(&ata_acc.data).unwrap();
    assert_eq!(ata_state.amount, 1, "T2: holder balance stays 1");
}

// --- T3: replay -------------------------------------------------------------

#[test]
fn t3_replay_signature_with_altered_timestamp_rejected() {
    let (mut svm, _authority, device) = boot();
    let hash = [7u8; 32];

    // Captured over (hash, ts=100, score=10); never minted with it.
    let captured = sign_binding(&device, &hash, 100, 10);

    // Replay: the precompile carries the CAPTURED attestation (ts=100) while
    // the instruction claims ts=999 - hash unminted, so ONLY the payload
    // binding can stop this (why: not the PDA gate).
    let err = send_ixs(&mut svm, &device,
        &attest(&device, &binding_msg(&hash, 100, 10),
            mint_ix(&device, &hash, 999, 10, GeoTag::Withheld, None, captured)))
    .expect_err("T3: replayed signature over altered timestamp must be rejected");
    assert_custom(&err, u32::from(ErrorCode::InvalidDeviceSignature),
        "T3: signature must not verify against the altered timestamp");

    // Why: rejected tx must leave zero state (SVM atomicity).
    assert!(svm.get_account(&pda(&[CAPTURE_SEED, &hash])).is_none(),
        "T3: no datagram may exist after rejected replay");
    assert!(svm.get_account(&pda(&[CAPTURE_MINT_SEED, &hash])).is_none(),
        "T3: no mint may exist after rejected replay");
}

// --- T4: spoof --------------------------------------------------------------

#[test]
fn t4_unregistered_device_spoof_fails_at_account_resolution() {
    let (mut svm, _authority, _device) = boot();
    let attacker = Keypair::new();
    svm.airdrop(&attacker.pubkey(), 10 * SOL).expect("airdrop attacker");
    let hash = [7u8; 32];

    // The attacker signs a PERFECTLY VALID self-signature - what must stop
    // them is the registry (why: T4 is a constraint-level block, not a
    // signature check).
    let sig = sign_binding(&attacker, &hash, 100, 10);
    let err = send_ixs(&mut svm, &attacker,
        &attest(&attacker, &binding_msg(&hash, 100, 10),
            mint_ix(&attacker, &hash, 100, 10, GeoTag::Withheld, None, sig)))
    .expect_err("T4: unregistered device must be rejected");
    assert_custom(&err, u32::from(anchor_lang::error::ErrorCode::AccountNotInitialized),
        "T4: empty device_record PDA must fail at account resolution (before handler)");

    // Why: constraint-level rejection - nothing in the handler ran.
    assert!(svm.get_account(&pda(&[CAPTURE_SEED, &hash])).is_none(),
        "T4: no datagram from spoofed mint");
    assert!(svm.get_account(&pda(&[CAPTURE_MINT_SEED, &hash])).is_none(),
        "T4: no mint from spoofed mint");
}

// --- T5: tamper -------------------------------------------------------------

#[test]
fn t5_tampered_capture_hash_invalidates_signature() {
    let (mut svm, _authority, device) = boot();
    let hash = [7u8; 32];
    let sig = sign_binding(&device, &hash, 100, 10);

    // One flipped byte of the uniqueness key: the attestation is over the
    // ORIGINAL hash while the instruction carries the tampered one, so the
    // payload binding fails (why: if capture_hash were not signed, an attacker
    // could remint any observed capture under a fresh PDA).
    let mut tampered = hash;
    tampered[0] ^= 0xFF;
    let err = send_ixs(&mut svm, &device,
        &attest(&device, &binding_msg(&hash, 100, 10),
            mint_ix(&device, &tampered, 100, 10, GeoTag::Withheld, None, sig)))
    .expect_err("T5: tampered capture_hash must invalidate the signature");
    assert_custom(&err, u32::from(ErrorCode::InvalidDeviceSignature),
        "T5: signature must fail against the tampered capture_hash");
    assert!(svm.get_account(&pda(&[CAPTURE_SEED, &tampered])).is_none(),
        "T5: no datagram from tampered mint");
}

// --- T6: rogue device management + revocation -------------------------------

#[test]
fn t6_rogue_device_management_rejected_and_revocation_cuts_key_off() {
    let (mut svm, authority, device) = boot();
    let rogue = Keypair::new();
    svm.airdrop(&rogue.pubkey(), 10 * SOL).expect("airdrop rogue");
    let config = pda(&[CONFIG_SEED]);
    let device_pk = device.pubkey();
    let record = pda(&[DEVICE_SEED, device_pk.as_ref()]);

    // (a) rogue add_device: init runs BEFORE the has_one access check, so
    // also assert ROLLBACK - atomicity completes the authority gate (why: a
    // half-applied init would leave rogue registry state).
    let victim = Keypair::new();
    let victim_pk = victim.pubkey();
    let new_record = pda(&[DEVICE_SEED, victim_pk.as_ref()]);
    let ix = Instruction {
        program_id: PROGRAM_ID,
        accounts: accounts::AddDevice {
            config,
            device_record: new_record,
            authority: rogue.pubkey(),
            system_program: system_program::ID,
        }
        .to_account_metas(None),
        data: instruction::AddDevice { device_key: victim_pk }.data(),
    };
    let err = send_ix(&mut svm, &rogue, ix)
        .expect_err("T6a: non-authority add_device must fail");
    assert_custom(&err, u32::from(ErrorCode::Unauthorized),
        "T6a: has_one authority gate must reject the rogue");
    assert!(svm.get_account(&new_record).is_none(),
        "T6a: failed tx must roll back the PDA init (no rogue registry state)");

    // (b) rogue remove_device on the REAL record: fails at has_one BEFORE
    // close runs (why: a rogue revoke would burn rent to the attacker and
    // de-register the fleet).
    let ix = Instruction {
        program_id: PROGRAM_ID,
        accounts: accounts::RemoveDevice {
            config,
            device_record: record,
            authority: rogue.pubkey(),
        }
        .to_account_metas(None),
        data: instruction::RemoveDevice.data(),
    };
    let err = send_ix(&mut svm, &rogue, ix)
        .expect_err("T6b: non-authority remove_device must fail");
    assert_custom(&err, u32::from(ErrorCode::Unauthorized),
        "T6b: has_one authority gate must reject the rogue revoke");
    assert!(svm.get_account(&record).is_some(),
        "T6b: registry record must survive a rogue revoke");

    // (c) control + revocation semantics: the REAL authority can revoke, and
    // the revoked key can no longer mint (why: close-to-revoke must cut the
    // key off without a new instruction state machine).
    let ix = Instruction {
        program_id: PROGRAM_ID,
        accounts: accounts::RemoveDevice {
            config,
            device_record: record,
            authority: authority.pubkey(),
        }
        .to_account_metas(None),
        data: instruction::RemoveDevice.data(),
    };
    send_ix(&mut svm, &authority, ix).expect("T6c: authority remove_device must succeed");
    assert!(svm.get_account(&record).map(|a| a.data.is_empty()).unwrap_or(true),
        "T6c: close-to-revoke must destroy the registry record");

    let hash = [8u8; 32];
    let sig = sign_binding(&device, &hash, 100, 10);
    send_ixs(&mut svm, &device,
        &attest(&device, &binding_msg(&hash, 100, 10),
            mint_ix(&device, &hash, 100, 10, GeoTag::Withheld, None, sig)))
    .expect_err("T6c: revoked device must no longer mint");
    assert!(svm.get_account(&pda(&[CAPTURE_SEED, &hash])).is_none(),
        "T6c: no mint state after revocation");
}