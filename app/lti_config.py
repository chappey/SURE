"""LTI tool configuration singleton."""

from __future__ import annotations

from pylti1p3.tool_config import ToolConfJsonFile

from app.config import LTI_CONFIG_PATH

tool_conf = ToolConfJsonFile(str(LTI_CONFIG_PATH))
