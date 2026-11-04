"""Offline sanity model for the arcade driving assist (see docs/DRIVING_PLAN.md).

It runs the real shared/hk_drive_assist.h through ctypes on a simple planar vehicle with a
saturating tyre model. It checks signs, stability and rough targets. It does not replace the
in-engine HK.DriveTest: Chaos tyres, suspension and gearbox differ from this model.
"""
