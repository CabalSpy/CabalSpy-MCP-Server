# Lets anyone self-host the server, and lets directories like Glama build and
# inspect it in a sandbox. The hosted server at mcp.cabalspy.xyz runs the same
# file; this image exists so the code can be verified independently.
FROM python:3.12-slim

WORKDIR /app

# Dependencies first, so a code change does not invalidate the layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY cabalspy_mcp.py .

# Bind to every interface inside the container; put a TLS terminating proxy in
# front of it in production.
ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8081
EXPOSE 8081

# No CABALSPY_API_KEY here on purpose. Each user supplies their own through the
# X-CabalSpy-Key header or an api_key query parameter. Baking one in would serve
# your credits to anyone who forgets theirs.

# Run as a non-root user.
RUN useradd --create-home --uid 10001 cabalspy
USER cabalspy

CMD ["python3", "cabalspy_mcp.py"]
