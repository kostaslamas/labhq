"""`name -> adapter factory`. A new exposure is a new registration, never a dispatcher edit."""

from collections.abc import Callable

from labhq.approvals.registry import Registry
from labhq.expose.base import ExposureAdapter
from labhq.expose.quick_tunnel import QuickTunnelAdapter

type AdapterFactory = Callable[[], ExposureAdapter]

exposures: Registry[AdapterFactory] = Registry("exposure")
exposures.register("quick-tunnel", QuickTunnelAdapter)
