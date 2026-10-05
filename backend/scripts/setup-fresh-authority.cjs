#!/usr/bin/env node
// TerraQuest fresh-key setup (devnet): initialize_config + add_device.
// Usage: node setup.cjs <authority-keypair.json>
// Deliberately does NOT call set_economy_params - that waits on Juan's tax number.
const { readFileSync } = require('node:fs');
const {
  Connection, Keypair, PublicKey, SystemProgram,
  Transaction, TransactionInstruction,
} = require('@solana/web3.js');

const PROGRAM_ID = new PublicKey('CurN8UWQwD1pifo9rhzKLbVrJxNt5jiGDTtpT8h6KskS');
const DEVICE_KEY = new PublicKey('2Y8pzHzP3vKGm2Gix7Z9SbuAVx4Vwc8JBEXd5LBpCLKG');
const IX_INIT_CONFIG = Buffer.from([208,127,21,1,194,190,196,70]);
const IX_ADD_DEVICE = Buffer.from([21,27,66,42,18,30,14,18]);

async function main() {
  const keyPath = process.argv[2];
  if (!keyPath) { console.error('usage: node setup.cjs <authority-keypair.json>'); process.exit(1); }
  const authority = Keypair.fromSecretKey(Uint8Array.from(JSON.parse(readFileSync(keyPath, 'utf8'))));
  console.log('authority pubkey: ' + authority.publicKey.toBase58());

  const conn = new Connection('https://api.devnet.solana.com', 'confirmed');
  const [configPda] = PublicKey.findProgramAddressSync([Buffer.from('global_config')], PROGRAM_ID);
  const [deviceRecord] = PublicKey.findProgramAddressSync([Buffer.from('device'), DEVICE_KEY.toBuffer()], PROGRAM_ID);

  const lamports = await conn.getBalance(authority.publicKey);
  console.log('balance: ' + (lamports / 1e9).toFixed(4) + ' SOL');
  if (lamports < 5e7) {
    console.error('NOT ENOUGH SOL - fund the pubkey above at https://faucet.solana.com (devnet, 2 SOL), then rerun.');
    process.exit(1);
  }

  async function send(label, ix) {
    const bh = await conn.getLatestBlockhash();
    const tx = new Transaction({ feePayer: authority.publicKey, ...bh }).add(ix);
    tx.sign(authority);
    const sig = await conn.sendRawTransaction(tx.serialize());
    const res = await conn.confirmTransaction({ signature: sig, ...bh }, 'confirmed');
    if (res.value.err) { console.error(label + ' FAILED: ' + sig + ' ' + JSON.stringify(res.value.err)); process.exit(1); }
    console.log(label + ' OK, sig: ' + sig);
  }

  if (await conn.getAccountInfo(configPda)) {
    console.log('initialize_config: config already exists - skipping');
  } else {
    await send('initialize_config', new TransactionInstruction({
      programId: PROGRAM_ID,
      keys: [
        { pubkey: configPda, isSigner: false, isWritable: true },
        { pubkey: authority.publicKey, isSigner: true, isWritable: true },
        { pubkey: SystemProgram.programId, isSigner: false, isWritable: false },
      ],
      data: IX_INIT_CONFIG,
    }));
  }

  const rec = await conn.getAccountInfo(deviceRecord);
  if (rec && rec.data.length) {
    console.log('add_device: device already registered - skipping');
  } else {
    await send('add_device', new TransactionInstruction({
      programId: PROGRAM_ID,
      keys: [
        { pubkey: configPda, isSigner: false, isWritable: false },
        { pubkey: deviceRecord, isSigner: false, isWritable: true },
        { pubkey: authority.publicKey, isSigner: true, isWritable: true },
        { pubkey: SystemProgram.programId, isSigner: false, isWritable: false },
      ],
      data: Buffer.concat([IX_ADD_DEVICE, DEVICE_KEY.toBuffer()]),
    }));
  }

  const cfg = await conn.getAccountInfo(configPda);
  if (!cfg || cfg.data.length < 52) { console.error('readback FAILED: config missing'); process.exit(1); }
  const d = cfg.data;
  const stored = new PublicKey(d.subarray(8, 40)).toBase58();
  console.log('--- readback ---');
  console.log('config PDA:       ' + configPda.toBase58());
  console.log('authority:        ' + stored + (stored === authority.publicKey.toBase58() ? '  (matches your fresh key)' : '  (MISMATCH - STOP, tell b.2)'));
  console.log('tax_rate_bps:     ' + d.readUInt16LE(41) + '  (inert until your number)');
  console.log('faucet_max:       ' + d.readBigUInt64LE(43) + '  (0 = faucet off)');
  console.log('founding_minted:  ' + (d[51] === 1));
  const r2 = await conn.getAccountInfo(deviceRecord);
  console.log('device_record:    ' + deviceRecord.toBase58() + (r2 && r2.data.length ? '  REGISTERED' : '  MISSING'));
  console.log('done - paste this output to b.2 for independent verification.');
}
main().catch((e) => { console.error(e); process.exit(1); });
