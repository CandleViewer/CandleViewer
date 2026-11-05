/**
 * `@candleviewer/order-ticket-core` (E30-T01, #984): the one order-ticket core every ticket
 * surface shares. Slice S1 exports the model, exact decimals and instrument grids; validation,
 * the sizing mirror and the submit pipeline follow in S2–S4.
 */
export * from "./model.js";
export * from "./decimal.js";
export * from "./instrument.js";
