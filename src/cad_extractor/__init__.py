"""
CAD Extractor IR - Standardized CAD Intermediate Representation & Extraction Engine.
"""

__version__ = "1.0.0"
__author__ = "La Vinci Engineering"

from .core import extract_cad_ir
from .models import CADIntermediateRepresentation

__all__ = ["extract_cad_ir", "CADIntermediateRepresentation"]
