// BarSeries (E12-S06, E12-D06 §3.2 / §4.1): the OHLC bar plugin. The candle plugin's machinery with
// the stem (part 3) and the ticks (part 2, a 10-vertex strip, BQ-15): the stem high → low on the
// centre column, the open tick to its left and the close tick to its right, at the wick weight
// (1 hairline up, 2 down); doji neutral, a zero-range bar the neutral zero-range mark. Below 5 CSS
// px it draws the candle mark (`CandleSeries.frame` switches the two batches' parts). Two draws.
import { CandleSeries } from "./series.js";
import type { CandleRing } from "./ring.js";

export class BarSeries extends CandleSeries {
  constructor(ring: CandleRing) {
    super(ring, "bars");
  }
}
