import { ClobClient, SignatureTypeV2 } from "@polymarket/clob-client-v2";
import { createWalletClient, http } from "viem";
import { privateKeyToAccount } from "viem/accounts";

export function createPolymarketClient(config) {
  const account = privateKeyToAccount(config.privateKey);
  const signer = createWalletClient({
    account,
    transport: http(config.rpcUrl)
  });

  const builderConfig = config.builderCode
    ? { builderCode: config.builderCode }
    : undefined;

  const client = new ClobClient({
    host: config.host,
    chain: config.chain,
    signer,
    creds: config.apiCreds,
    signatureType: config.signatureType,
    funderAddress: config.depositWalletAddress,
    builderConfig
  });

  return {
    account,
    client
  };
}

export async function deriveApiCreds(config) {
  const account = privateKeyToAccount(config.privateKey);
  const signer = createWalletClient({
    account,
    transport: http(config.rpcUrl)
  });
  const client = new ClobClient({
    host: config.host,
    chain: config.chain,
    signer,
    signatureType: SignatureTypeV2.POLY_1271,
    funderAddress: config.depositWalletAddress
  });
  const creds = await client.createOrDeriveApiKey();
  return { account, creds };
}
