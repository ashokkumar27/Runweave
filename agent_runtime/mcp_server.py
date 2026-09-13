"""Local read-only MCP integration. No shell or file-execution capability."""

from fastmcp import FastMCP

mcp = FastMCP("Temperature conversion")


@mcp.tool
async def convert_temperature(celsius: float) -> float:
    """Convert Celsius to Fahrenheit."""
    return celsius * 9 / 5 + 32


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8001, show_banner=False)
