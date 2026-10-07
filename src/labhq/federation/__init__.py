"""Federation: one labhq's CEO manages another labhq as a remote manager (issue #188).

The upstream instance registers a downstream one as a node and a manager whose adapter is
`remote`. The downstream instance dials out: it polls the upstream's federation endpoint for
orders and posts pointer reports back, so it needs no open port.

This package init stays empty on purpose. The scheduler imports `labhq.federation.cap`, and a
package init that pulled in the services would close an import cycle through `labhq.work`.
"""
