# ProcessHunter vendor snapshot

This private snapshot is maintained inside ServerPy so the application does
not depend on a separate ProcessHunter checkout. It was copied from the local
ProcessHunter repository at commit `fb03eff`, with its pending ServerPy
integration changes included.

ServerPy-specific changes use the `vendor.processhunter` package namespace and
embed the window as a child widget. Keep runtime imports and fixes in this
directory so the standalone reference checkout can be removed safely.
