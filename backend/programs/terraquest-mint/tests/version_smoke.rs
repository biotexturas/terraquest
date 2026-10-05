//! Version-alignment smoke test for the T1-T6 harness.
//!
//! WHY THIS EXISTS: the LiteSVM test approach rests on one assumption - that
//! the program crate (anchor-lang 0.31.1 -> solana-program ^2) and the test
//! runtime (litesvm 0.7.1 / solana-sdk 2) resolve to the SAME solana-pubkey
//! version. If they drift across a major line, `Pubkey` becomes two different
//! types and no T1-T6 test can even compile. That mismatch is the #1 way an
//! Anchor test build sinks, so we catch it here - at the harness layer,
//! before any attack test exists - instead of misattributing it later.
//!
//! What it proves, in order:
//!   1. The program lib host-compiles (integration tests link it).
//!   2. anchor-lang's Pubkey and solana-sdk's Pubkey are one type - proven by
//!      passing the program's anchor-typed `ID` straight into solana-sdk's
//!      `find_program_address`. A drift fails THIS line at compile time.
//!   3. LiteSVM links and constructs, so the runtime crate is in the graph.

use anchor_lang::solana_program::pubkey::Pubkey as ProgramPubkey;

#[test]
fn program_and_test_runtime_share_one_pubkey_type() {
    // (1) Program crate links: its on-chain identity, typed by anchor-lang.
    let program_id: ProgramPubkey = terraquest_mint::ID;

    // (2) The type-boundary crossing. This only compiles if solana_sdk's
    // Pubkey IS anchor_lang's Pubkey (one solana-pubkey version). A major-line
    // drift breaks this line - the signal we want, early.
    let seeds: &[&[u8]] = &[&b"global_config"[..]];
    let (config_pda, config_bump) =
        solana_sdk::pubkey::Pubkey::find_program_address(seeds, &program_id);

    // The config PDA must not collide with the program id itself.
    assert_ne!(config_pda, program_id, "config PDA must differ from program id");
    // find_program_address returns a bump in 0..=255 (0 is valid), so only
    // assert it is a u8 rather than "non-zero".
    assert!(config_bump <= 255);

    // (3) LiteSVM constructs - the test runtime is compiled and linked.
    let svm = litesvm::LiteSVM::new();
    drop(svm);
}
