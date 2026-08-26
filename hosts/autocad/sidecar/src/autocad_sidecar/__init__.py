"""AutoCAD sidecar: the agent's single entry point to the AutoCAD host.

Pipeline: command_dispatcher -> adapters -> host_adapter -> pipe transport
          -> NamedPipe -> AutoCAD.AgentHost plugin (in-process).
"""

from autocad_sidecar.adapter.context_adapter import ContextAdapter
from autocad_sidecar.adapter.host_adapter import HostAdapter
from autocad_sidecar.adapter.model_adapter import ModelAdapter
from autocad_sidecar.adapter.view_adapter import ViewAdapter
from autocad_sidecar.execution.command_dispatcher import CommandDispatcher

__all__ = [
    "CommandDispatcher",
    "ContextAdapter",
    "HostAdapter",
    "ModelAdapter",
    "ViewAdapter",
]

__version__ = "0.1.0"
