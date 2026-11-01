"""Throwaway spikes (`spike/<epic>-<slug>` branches, never merged; C-4.5).

Nothing in `candleviewer` or `cvdev` imports this package. No wheel ships it and
`infra/images/Dockerfile.api` copies only `candleviewer`; a spike runs from its own checkout,
bind-mounted read-only into a one-off container of the `api` image (see each spike's README).
"""
