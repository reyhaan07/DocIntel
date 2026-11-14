"""docintel - relationship-aware document understanding for patient intake forms.

PDF -> entities + relationships -> validated JSON -> standardized form.
"""
__version__ = "0.1.0"

from .pipeline import process_pdf  # noqa: E402,F401
