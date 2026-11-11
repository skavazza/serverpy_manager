# SystemRAM vendor snapshot

This private snapshot is maintained inside ServerPy so the application does
not depend on a separate SystemRAM checkout. It was copied from the local
SystemRAM repository at commit `9379aa3`, with its pending ServerPy
integration changes included.

ServerPy-specific changes use the `vendor.systemram` package namespace, embed
the window as a child widget, and use the shared PySide6 runtime. Keep runtime
imports and fixes in this directory so the standalone reference checkout can
be removed safely.
