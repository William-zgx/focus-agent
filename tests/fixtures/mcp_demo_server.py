from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

server = FastMCP("demo")


@server.tool(
    annotations=ToolAnnotations(readOnlyHint=True),
    structured_output=False,
)
def add(a: int, b: int) -> int:
    return a + b


@server.tool(structured_output=False)
def fail() -> str:
    raise ValueError("demo failure")


if __name__ == "__main__":
    server.run(transport="stdio")
