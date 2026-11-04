/**
 * `@candleviewer/order-ticket-core` (E30-T01, #984): the one order-ticket core every ticket
 * surface shares: the model, exact decimals and instrument grids (S1), entry classification,
 * `validate()` (S2a); the deck messages (S2b), the sizing mirror and the submit pipeline follow.
 */
export * from "./model.js";
export * from "./decimal.js";
export * from "./instrument.js";
export * from "./classify.js";
export * from "./validate.js";
export * from "./messages.js";
