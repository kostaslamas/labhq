"""Federation over Agent2Agent (A2A), issue #191.

A2A is the protocol at the boundary between two labhq instances. Inside one instance nothing
changes: orders, reports, caps and approvals are the #188 tables and services. This package
only translates between them and A2A's tasks, using the official SDK's wire types and
JSON-RPC dispatcher.

Like the package above it, this init stays empty so importing a submodule pulls in no services.
"""
