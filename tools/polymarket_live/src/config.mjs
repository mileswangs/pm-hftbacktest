import path from "node:path";

import { Chain, SignatureTypeV2 } from "@polymarket/clob-client-v2";

import { loadEnvFile } from "./env.mjs";

const DEFAULT_ENV_FILE = path.resolve(process.cwd(), ".env.polymarket.local");

export function loadPolymarketConfig(envFile = DEFAULT_ENV_FILE) {
  const env = loadEnvFile(envFile);
  const required = [
    "POLYMARKET_PRIVATE_KEY",
    "POLYMARKET_API_KEY",
    "POLYMARKET_API_SECRET",
    "POLYMARKET_API_PASSPHRASE",
    "POLYMARKET_DEPOSIT_WALLET_ADDRESS"
  ];

  for (const key of required) {
    if (!env[key]) {
      throw new Error(`Missing required config: ${key}`);
    }
  }

  return {
    envFile,
    host: env.POLYMARKET_CLOB_HOST || "https://clob.polymarket.com",
    rpcUrl: env.POLYMARKET_RPC_URL || "https://polygon.drpc.org",
    chain: Chain.POLYGON,
    privateKey: env.POLYMARKET_PRIVATE_KEY,
    signerAddress: env.POLYMARKET_SIGNER_ADDRESS || undefined,
    depositWalletAddress: env.POLYMARKET_DEPOSIT_WALLET_ADDRESS,
    walletAddress: env.POLYMARKET_WALLET || env.POLYMARKET_DEPOSIT_WALLET_ADDRESS,
    apiCreds: {
      key: env.POLYMARKET_API_KEY,
      secret: env.POLYMARKET_API_SECRET,
      passphrase: env.POLYMARKET_API_PASSPHRASE
    },
    relayerApiKey: env.POLYMARKET_RELAYER_API_KEY || undefined,
    relayerApiKeyAddress: env.POLYMARKET_RELAYER_API_KEY_ADDRESS || undefined,
    builderCode: env.POLYMARKET_BUILDER_CODE || undefined,
    signatureType: Number(env.POLYMARKET_SIGNATURE_TYPE || SignatureTypeV2.POLY_1271)
  };
}
