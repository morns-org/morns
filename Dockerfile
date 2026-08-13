FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .
RUN useradd --system --uid 10001 --create-home morns
RUN mkdir -p /data && chown morns:morns /data
USER morns
ENV MORNS_DATABASE=/data/morns.db MORNS_HOST=0.0.0.0
EXPOSE 8787
CMD ["morns"]
