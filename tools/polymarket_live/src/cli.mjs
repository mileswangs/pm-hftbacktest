import { webcrypto } from "node:crypto";

if (!globalThis.crypto) {
  globalThis.crypto = webcrypto;
}

import { AssetType, Side } from "@polymarket/clob-client-v2";

import { loadPolymarketConfig } from "./config.mjs";
import { createPolymarketClient, deriveApiCreds } from "./client.mjs";

function roundPrice(value, tickSize) {
  const rounded = Math.round(value / tickSize) * tickSize;
  return Number(rounded.toFixed(6));
}

function choosePassiveBuyPrice(book) {
  const tickSize = Number(book.tick_size);
  const bids = Array.isArray(book.bids) ? book.bids : [];
  const asks = Array.isArray(book.asks) ? book.asks : [];
  const bestBid = bids.length > 0 ? Number(bids[0].price) : 0;
  const bestAsk = asks.length > 0 ? Number(asks[0].price) : 1;

  let candidate = bestBid > tickSize ? bestBid - tickSize : tickSize;
  candidate = Math.max(candidate, tickSize);
  if (candidate >= bestAsk) {
    candidate = Math.max(tickSize, bestAsk - (2 * tickSize));
  }
  return roundPrice(candidate, tickSize);
}

function chooseTestSize(book) {
  const minSize = Number(book.min_order_size || "1");
  return Number(minSize.toFixed(6));
}

async function resolveTokenId(client, explicitTokenId) {
  if (explicitTokenId) {
    return { tokenId: explicitTokenId, source: "explicit" };
  }

  const page = await client.getSamplingSimplifiedMarkets();
  const markets = Array.isArray(page?.data) ? page.data : [];
  for (const market of markets) {
    const tokens = market?.tokens || market?.outcomes || market?.clobTokens || market?.clobTokenIds;
    if (Array.isArray(tokens)) {
      for (const token of tokens) {
        const tokenId = token?.token_id || token?.tokenId || token?.id || token;
        if (typeof tokenId === "string" && tokenId.length > 0) {
          return {
            tokenId,
            source: "sampling_simplified_markets",
            market
          };
        }
      }
    }
  }

  throw new Error("Could not auto-select a Polymarket token id from sampling markets.");
}

async function main() {
  const command = process.argv[2];
  const config = loadPolymarketConfig();

  if (command === "derive-creds") {
    const result = await deriveApiCreds(config);
    console.log(JSON.stringify({
      signerAddress: result.account.address,
      depositWalletAddress: config.depositWalletAddress,
      creds: result.creds
    }, null, 2));
    return;
  }

  if (command === "book") {
    const tokenId = process.argv[3];
    if (!tokenId) throw new Error("Usage: node ./src/cli.mjs book <tokenId>");
    const { account, client } = createPolymarketClient(config);
    const book = await client.getOrderBook(tokenId);
    console.log(JSON.stringify({
      signerAddress: account.address,
      depositWalletAddress: config.depositWalletAddress,
      book
    }, null, 2));
    return;
  }

  if (command === "open-orders") {
    const { account, client } = createPolymarketClient(config);
    const orders = await client.getOpenOrders();
    console.log(JSON.stringify({
      signerAddress: account.address,
      depositWalletAddress: config.depositWalletAddress,
      orders
    }, null, 2));
    return;
  }

  if (command === "dry-run-order") {
    const explicitTokenId = process.argv[3];
    const { account, client } = createPolymarketClient(config);
    const token = await resolveTokenId(client, explicitTokenId);
    const balanceAllowance = await client.getBalanceAllowance({
      asset_type: AssetType.COLLATERAL
    });
    const book = await client.getOrderBook(token.tokenId);
    const price = choosePassiveBuyPrice(book);
    const size = chooseTestSize(book);
    const signedOrder = await client.createOrder({
      tokenID: token.tokenId,
      price,
      size,
      side: Side.BUY,
      builderCode: config.builderCode
    });
    console.log(JSON.stringify({
      signerAddress: account.address,
      depositWalletAddress: config.depositWalletAddress,
      tokenSelection: token,
      balanceAllowance,
      dryRun: {
        side: "BUY",
        price,
        size,
        tickSize: book.tick_size,
        minOrderSize: book.min_order_size,
        bestBid: book.bids?.[0]?.price ?? null,
        bestAsk: book.asks?.[0]?.price ?? null
      },
      signedOrder: {
        maker: signedOrder.maker,
        signer: signedOrder.signer,
        tokenId: signedOrder.tokenId,
        side: signedOrder.side,
        signatureType: signedOrder.signatureType,
        builder: signedOrder.builder,
        makerAmount: signedOrder.makerAmount,
        takerAmount: signedOrder.takerAmount,
        expiration: signedOrder.expiration,
        signaturePreview: typeof signedOrder.signature === "string"
          ? `${signedOrder.signature.slice(0, 18)}...${signedOrder.signature.slice(-10)}`
          : null
      }
    }, null, 2));
    return;
  }

  throw new Error("Unsupported command");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
