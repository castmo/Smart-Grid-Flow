"""Lägger integrationsmappen på sys.path så att ``core`` kan testas utan Home Assistant."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "custom_components" / "smart_grid_flow"))
