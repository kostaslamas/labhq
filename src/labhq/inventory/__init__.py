"""Session inventory (ADR 0010): scan every agent session, group by project, analyse on request.

This module imports nothing on purpose: `labhq.adoption.saved` reads the store layouts from
here, and adoption is imported by the scanner. Import the submodules you need.
"""
