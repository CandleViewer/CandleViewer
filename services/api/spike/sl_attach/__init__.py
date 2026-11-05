"""#856 (E32-K01): attached stop-loss versus `trading-stop`, the measurement harness. Throwaway,
on `spike/e32-sl-attach-latency`, never merged; it stacks on #843's harness
(`spike.oms_demo_path`) and reuses its guarded port, scrubber and offline corpus venue.

Arm (a) times a create carrying an attached `stopLoss` to its ack. Arm (b) opens with a far
attached backstop stop and times the `trading-stop` that tightens it, from the first
execution's `execTime` to the `200`, on the exchange clock (the owner's Q5 ruling: no position
is ever without a native stop, C-2.6). This slice (S1) is offline only.
"""
