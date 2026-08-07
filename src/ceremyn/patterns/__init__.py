"""Read-only pattern discovery: detects `Pattern`s and studies their historical
performance. Never constructs a `Signal` and has no path to the OMS -- see
ARCHITECTURE_DECISIONS.md / ROADMAP_V2.md.
"""

from ceremyn.patterns.candlestick import available_patterns, detect
from ceremyn.patterns.chart_shape import detect as detect_chart_shapes
from ceremyn.patterns.opportunity import find_opportunities
from ceremyn.patterns.study import PatternPerformance, historical_performance
from ceremyn.patterns.swing import detect as detect_swing

__all__ = [
    "PatternPerformance",
    "available_patterns",
    "detect",
    "detect_chart_shapes",
    "detect_swing",
    "find_opportunities",
    "historical_performance",
]
